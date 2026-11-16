"""The forge build plan: restore, scrub, trim, stamp, package, push.

`plan()` turns a `Config` into an ordered list of `Step`s and touches nothing.
`execute()` walks them through a runner, which is the only part that starts a
process. Tests drive `execute()` with a recording runner; the CLI drives it with
`SubprocessRunner`.
"""

# ruff: noqa: S608
# S608 is a false positive here: every interpolated value is a validated schema or
# table identifier, a module constant, or a backup stamp matched by a strict regex.
# The caller-supplied workdir never reaches SQL; it is validated by check_workdir
# and shell-quoted where it enters a command.

from __future__ import annotations

import os
import pathlib
import re
import secrets
import shlex
import socket
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from forge import restore, scrub
from forge.classes import TableClass

CLASSES = ("lean", "full")
IMAGE_NAME = "wow-eph-template"
STAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")
TAG_RE = re.compile(r"^(?P<cls>lean|full)-(?P<stamp>\d{8}T\d{6}Z)$")
KEEP_STAMPS = 3
DEFAULT_PORT = 3307

# Throwaway server: durability is worthless for a datadir built once and copied.
MYSQL_FLAGS = (
    "--no-defaults",
    "--bind-address=127.0.0.1",
    "--innodb-flush-log-at-trx-commit=0",
    "--skip-log-bin",
    "--innodb-doublewrite=0",
)


class StepFailed(RuntimeError):
    pass


class ForeignServer(StepFailed):
    """Something other than the forge's own throwaway MySQL is in the way."""


class CredentialLeft(StepFailed):
    """The audit found a usable credential, address or contact detail."""


# An absolute path of plain characters. The workdir is caller-supplied and ends up
# in a `sh -c` script, so it is both validated here and shell-quoted there. The
# optional drive letter only lets the tests run on Windows; mysqld never sees it.
_WORKDIR_RE = re.compile(r"^(?:[A-Za-z]:)?/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def check_workdir(workdir: pathlib.PurePath) -> None:
    text = workdir.as_posix()
    if not _WORKDIR_RE.match(text) or ".." in text.split("/"):
        raise ValueError(
            f"workdir must be an absolute path of letters, digits, . _ - and /, not {text!r}"
        )


@dataclass(frozen=True)
class Config:
    template_class: str
    backup_dir: pathlib.Path
    workdir: pathlib.Path
    registry: str = ""
    backup_prefix: str = restore.DEFAULT_PREFIX
    mysql_host: str = "127.0.0.1"
    mysql_port: int = DEFAULT_PORT
    auth_dump: pathlib.Path | None = None
    db_import_cmd: tuple[str, ...] = ("dbimport",)
    keep: int = KEEP_STAMPS
    # A per-run nonce: the throwaway server is started with this --server-id and
    # the runner refuses any server that does not report it back.
    server_id: int = field(default_factory=lambda: secrets.randbelow(2**31 - 1) + 1)

    def __post_init__(self) -> None:
        if self.template_class not in CLASSES:
            raise ValueError(
                f"class must be one of {CLASSES}, not {self.template_class!r}"
            )
        restore.assert_local_mysql(self.mysql_host)
        check_workdir(self.workdir)
        restore.check_prefix(self.backup_prefix)


@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...] = ()
    sql: tuple[str, ...] = ()
    fn: Callable[[], None] | None = field(default=None, compare=False)
    env: tuple[tuple[str, str], ...] = ()
    background: bool = False
    keep: int = 0
    # (server id, datadir) the background server must report before anything runs.
    identity: tuple[int, str] | None = None
    # True when the step reaches MySQL through its own command (a restore pipe).
    needs_server: bool = False


def image_tag(template_class: str, stamp: str) -> str:
    if template_class not in CLASSES or not STAMP_RE.match(stamp):
        raise ValueError(f"bad template tag {template_class!r} {stamp!r}")
    return f"{IMAGE_NAME}:{template_class}-{stamp}"


def tags_to_prune(tags: Sequence[str], keep: int = KEEP_STAMPS) -> list[str]:
    """Template tags older than the newest `keep` per class. Foreign tags are left alone."""
    by_class: dict[str, list[str]] = {}
    for tag in tags:
        match = TAG_RE.match(tag)
        if match:
            by_class.setdefault(match["cls"], []).append(tag)
    doomed: list[str] = []
    for group in by_class.values():
        group.sort(key=lambda t: TAG_RE.match(t)["stamp"], reverse=True)  # type: ignore[index]
        doomed += group[keep:]
    return sorted(doomed)


def _marker_sql(
    cfg: Config, backup: restore.Backup, auth_source: str
) -> tuple[str, ...]:
    for value in (cfg.template_class, backup.stamp, backup.path.name, auth_source):
        if not re.match(r"^[A-Za-z0-9._-]+$", value):
            raise ValueError(f"unsafe marker value {value!r}")
    # The playerbots config a world built from this template must also carry. A
    # lean template only stays lean when the worldserver is told not to create
    # bot accounts; nothing in the database can say so, so the marker does.
    required_conf = (
        ";".join(f"{k}={v}" for k, v in scrub.LEAN_PLAYERBOTS_CONF.items())
        if cfg.template_class == "lean"
        else ""
    )
    return (
        "CREATE TABLE IF NOT EXISTS acore_characters.ephemeral_world ("
        " id TINYINT UNSIGNED NOT NULL PRIMARY KEY, template_stamp VARCHAR(32) NOT NULL,"
        " class VARCHAR(8) NOT NULL, source_backup VARCHAR(128) NOT NULL,"
        " auth_source VARCHAR(16) NOT NULL, required_conf VARCHAR(255) NOT NULL,"
        " built_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "DELETE FROM acore_characters.ephemeral_world",
        "INSERT INTO acore_characters.ephemeral_world (id, template_stamp, class, source_backup,"
        " auth_source, required_conf)"
        f" VALUES (1, '{backup.stamp}', '{cfg.template_class}', '{backup.path.name}', '{auth_source}',"
        f" '{required_conf}')",
    )


def _mysql_pipe(dump: pathlib.Path, cfg: Config) -> tuple[str, ...]:
    return tuple(
        restore.restore_command(
            restore.Backup(dump, ""), cfg.mysql_port, cfg.mysql_host
        )
    )


def plan(cfg: Config, classes: dict[str, TableClass]) -> list[Step]:
    if not cfg.registry:
        raise ValueError("a registry is required to push the template")
    backup = restore.newest_backup(cfg.backup_dir, cfg.backup_prefix)
    datadir = cfg.workdir / "datadir"
    layer = cfg.workdir / "layer.tar"
    tag = image_tag(cfg.template_class, backup.stamp)
    port = str(cfg.mysql_port)
    flags = " ".join([*MYSQL_FLAGS, f"--server-id={int(cfg.server_id)}"])
    datadir_flag = shlex.quote(f"--datadir={datadir.as_posix()}")
    start = (
        f"mysqld {flags} --initialize-insecure {datadir_flag} && "
        f"exec mysqld {flags} {datadir_flag} --port={int(cfg.mysql_port)}"
    )
    db_env = (
        ("AC_LOGIN_DATABASE_INFO", f"{cfg.mysql_host};{port};root;;acore_auth"),
        ("AC_WORLD_DATABASE_INFO", f"{cfg.mysql_host};{port};root;;acore_world"),
        (
            "AC_CHARACTER_DATABASE_INFO",
            f"{cfg.mysql_host};{port};root;;acore_characters",
        ),
        ("AC_UPDATES_ENABLE_DATABASES", "7"),
    )

    steps = [
        Step("verify-backup", fn=lambda: restore.verify_dump_complete(backup.path)),
        Step(
            "start-mysql",
            argv=("sh", "-c", start),
            background=True,
            identity=(cfg.server_id, datadir.as_posix()),
        ),
        Step(
            "restore",
            argv=tuple(restore.restore_command(backup, cfg.mysql_port, cfg.mysql_host)),
            needs_server=True,
        ),
        Step("db-import", argv=cfg.db_import_cmd, env=db_env, needs_server=True),
    ]

    if cfg.auth_dump is not None:
        auth_dump = cfg.auth_dump
        # The same check the characters dump gets, before any database work.
        steps.insert(
            1,
            Step(
                "verify-auth-dump", fn=lambda: restore.verify_dump_complete(auth_dump)
            ),
        )
        steps.append(
            Step(
                "auth-restore", argv=_mysql_pipe(cfg.auth_dump, cfg), needs_server=True
            )
        )
        auth_sql = scrub.auth_scrub_statements(
            "mysql"
        ) + scrub.auth_synthesis_statements("mysql", include_bots=False)
        auth_source = "dump"
    else:
        auth_sql = scrub.auth_synthesis_statements(
            "mysql"
        ) + scrub.auth_scrub_statements("mysql")
        auth_source = "synthesised"
    steps += [
        Step("auth", sql=tuple(auth_sql)),
        Step("playerbots-scrub", sql=tuple(scrub.playerbots_scrub_statements("mysql"))),
        Step("state-scrub", sql=tuple(scrub.state_scrub_statements(classes, "mysql"))),
    ]
    if cfg.template_class == "lean":
        steps.append(
            Step("lean-trim", sql=tuple(scrub.lean_statements(classes, "mysql")))
        )
    steps += [
        Step("marker", sql=_marker_sql(cfg, backup, auth_source)),
        Step(
            "credential-audit",
            sql=tuple(
                scrub.credential_audit_queries("mysql")
                + scrub.playerbots_audit_queries()
            ),
        ),
        Step("shutdown", sql=("SET GLOBAL innodb_fast_shutdown=0", "SHUTDOWN")),
        Step(
            "package",
            argv=(
                "tar",
                "-C",
                cfg.workdir.as_posix(),
                "-cf",
                layer.as_posix(),
                "datadir",
            ),
        ),
        Step(
            "push",
            argv=(
                "crane",
                "append",
                "-f",
                layer.as_posix(),
                "-t",
                f"{cfg.registry}/{tag}",
            ),
        ),
        Step(
            "prune", argv=("crane", "ls", f"{cfg.registry}/{IMAGE_NAME}"), keep=cfg.keep
        ),
    ]
    return steps


def _port_in_use(host: str, port: int) -> bool:
    """True when something accepts a connection on host:port."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


class Runner:
    """What `execute()` needs. Subclassed by the real runner and by test doubles."""

    def argv(self, step: Step) -> int:
        raise NotImplementedError

    def sql(self, step: Step) -> list[list[int]]:
        raise NotImplementedError

    def close(self) -> None:
        """Stop anything the runner started. Safe to call twice."""


def execute(steps: Sequence[Step], runner: Runner) -> None:
    """Run every step; always give the runner a chance to stop what it started."""
    try:
        _execute(steps, runner)
    finally:
        close = getattr(runner, "close", None)
        if close is not None:
            close()


def _execute(steps: Sequence[Step], runner: Runner) -> None:
    for step in steps:
        if step.fn is not None:
            try:
                step.fn()
            except restore.IncompleteDump as err:
                raise StepFailed(f"{step.name}: {err}") from err
        elif step.sql:
            try:
                rows = runner.sql(step)
            except scrub.EmptyKeepSet as err:
                raise StepFailed(f"{step.name}: {err}") from err
            if step.name == "credential-audit" and any(
                value for row in rows for value in row
            ):
                raise CredentialLeft(f"credential audit found leftovers: {rows}")
        elif step.argv:
            code = runner.argv(step)
            if code != 0:
                raise StepFailed(f"{step.name}: exit {code}")


class SubprocessRunner(Runner):
    """Runs steps as local processes. The only code in the forge that spawns one."""

    def __init__(
        self,
        cfg: Config,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        port_in_use: Callable[[str, int], bool] | None = None,
    ) -> None:
        self.cfg = cfg
        self._run = run
        self._popen = popen
        self._port_in_use = port_in_use or _port_in_use
        self._server: subprocess.Popen | None = None
        # What the spawned server must report; set when it is started.
        self._identity: tuple[int, str] | None = None

    def close(self) -> None:
        server, self._server = self._server, None
        if server is None or server.poll() is not None:
            return
        server.terminate()
        try:
            server.wait(timeout=60)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()

    def _mysql(self, statement: str) -> list[str]:
        return [
            "mysql",
            f"-h{self.cfg.mysql_host}",
            f"-P{self.cfg.mysql_port}",
            "-uroot",
            "--protocol=TCP",
            "-N",
            "-B",
            "-e",
            statement,
        ]

    def _reports(self, output: str) -> bool:
        """Does an identity query answer name the server the forge started?"""
        if self._identity is None:
            return False
        want_id, want_datadir = self._identity
        reported = output.strip().split("\t")
        return (
            len(reported) == 2
            and reported[0] == str(want_id)
            and reported[1].rstrip("/") == want_datadir.rstrip("/")
        )

    def _verify(self, step: Step) -> None:
        """Prove, right now, that the port is held by the server the forge started.

        Called before every database operation, so a server that exits and is
        replaced mid-build is caught before the next client connects to it.
        """
        if self._server is None or self._identity is None:
            raise ForeignServer(
                f"{step.name}: refusing to reach MySQL before the forge's own server is started"
            )
        if self._server.poll() is not None:
            raise ForeignServer(f"{step.name}: the server the forge started is gone")
        done = self._run(
            self._mysql("SELECT @@server_id, @@datadir"), capture_output=True, text=True
        )
        if done.returncode != 0 or not self._reports(done.stdout):
            raise ForeignServer(
                f"{step.name}: the server on the port is not the one the forge started"
            )

    def argv(self, step: Step) -> int:
        env = {**os.environ, **dict(step.env)}
        if step.background:
            return self._start_server(step, env)
        if step.needs_server:
            self._verify(step)
        if step.keep:
            return self._prune(step)
        return self._run(list(step.argv), env=env).returncode

    def _start_server(self, step: Step, env: dict[str, str]) -> int:
        if step.identity is None:
            raise ForeignServer(
                f"{step.name}: no identity to verify the server against"
            )
        if self._port_in_use(self.cfg.mysql_host, self.cfg.mysql_port):
            raise ForeignServer(
                f"something already listens on {self.cfg.mysql_host}:{self.cfg.mysql_port};"
                " refusing to start next to it"
            )
        self.cfg.workdir.mkdir(parents=True, exist_ok=True)
        self._server = self._popen(list(step.argv), env=env)
        self._identity = step.identity
        return self._wait_for_server()

    def _wait_for_server(self, attempts: int = 120) -> int:
        """Wait for the server we spawned, and only for it.

        A server that answers must report our per-run server id and our datadir.
        Anything else is a foreign server on the port: stop at once, run nothing.
        """
        for _ in range(attempts):
            if self._server is not None and self._server.poll() is not None:
                raise StepFailed("the spawned mysqld exited before it became ready")
            done = self._run(
                self._mysql("SELECT @@server_id, @@datadir"),
                capture_output=True,
                text=True,
            )
            if done.returncode == 0:
                if self._reports(done.stdout):
                    return 0
                raise ForeignServer(
                    "the server on the port is not the one the forge started"
                    f" (reported {done.stdout.strip()!r})"
                )
            time.sleep(2)
        return 1

    def _prune(self, step: Step) -> int:
        listing = self._run(list(step.argv), capture_output=True, text=True)
        if listing.returncode != 0:
            return listing.returncode
        repo = step.argv[-1]
        for tag in tags_to_prune(listing.stdout.split(), step.keep):
            code = self._run(["crane", "delete", f"{repo}:{tag}"]).returncode
            if code != 0:
                return code
        return 0

    def sql(self, step: Step) -> list[list[int]]:
        results: list[list[int]] = []

        def execute_one(statement: str) -> list[list[int]]:
            self._verify(step)
            done = self._run(self._mysql(statement), capture_output=True, text=True)
            if done.returncode != 0:
                raise StepFailed(
                    f"{step.name}: mysql exit {done.returncode}: {done.stderr.strip()[:200]}"
                )
            rows = [
                [int(v) for v in line.split("\t")]
                for line in done.stdout.splitlines()
                if line.strip()
            ]
            if statement.lstrip().upper().startswith("SELECT"):
                results.extend(rows)
            return rows

        scrub.run_lean(execute_one, list(step.sql))
        return results
