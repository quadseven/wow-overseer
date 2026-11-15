"""The forge build plan: restore, scrub, trim, stamp, package, push.

`plan()` turns a `Config` into an ordered list of `Step`s and touches nothing.
`execute()` walks them through a runner, which is the only part that starts a
process. Tests drive `execute()` with a recording runner; the CLI drives it with
`SubprocessRunner`.
"""

from __future__ import annotations

import os
import pathlib
import re
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


class CredentialLeft(StepFailed):
    """The audit found a usable credential, address or contact detail."""


@dataclass(frozen=True)
class Config:
    template_class: str
    backup_dir: pathlib.Path
    workdir: pathlib.Path
    registry: str = ""
    mysql_host: str = "127.0.0.1"
    mysql_port: int = DEFAULT_PORT
    auth_dump: pathlib.Path | None = None
    db_import_cmd: tuple[str, ...] = ("dbimport",)
    keep: int = KEEP_STAMPS

    def __post_init__(self) -> None:
        if self.template_class not in CLASSES:
            raise ValueError(
                f"class must be one of {CLASSES}, not {self.template_class!r}"
            )
        restore.assert_local_mysql(self.mysql_host)


@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...] = ()
    sql: tuple[str, ...] = ()
    fn: Callable[[], None] | None = field(default=None, compare=False)
    env: tuple[tuple[str, str], ...] = ()
    background: bool = False
    keep: int = 0


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
    return (
        "CREATE TABLE IF NOT EXISTS acore_characters.ephemeral_world ("
        " id TINYINT UNSIGNED NOT NULL PRIMARY KEY, template_stamp VARCHAR(32) NOT NULL,"
        " class VARCHAR(8) NOT NULL, source_backup VARCHAR(128) NOT NULL,"
        " auth_source VARCHAR(16) NOT NULL, built_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "DELETE FROM acore_characters.ephemeral_world",
        "INSERT INTO acore_characters.ephemeral_world (id, template_stamp, class, source_backup, auth_source)"
        f" VALUES (1, '{backup.stamp}', '{cfg.template_class}', '{backup.path.name}', '{auth_source}')",
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
    backup = restore.newest_backup(cfg.backup_dir)
    datadir = cfg.workdir / "datadir"
    layer = cfg.workdir / "layer.tar"
    tag = image_tag(cfg.template_class, backup.stamp)
    port = str(cfg.mysql_port)
    flags = " ".join(MYSQL_FLAGS)
    start = (
        f"mysqld {flags} --initialize-insecure --datadir={datadir.as_posix()} && "
        f"exec mysqld {flags} --datadir={datadir.as_posix()} --port={port}"
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
        Step("start-mysql", argv=("sh", "-c", start), background=True),
        Step(
            "restore",
            argv=tuple(restore.restore_command(backup, cfg.mysql_port, cfg.mysql_host)),
        ),
        Step("db-import", argv=cfg.db_import_cmd, env=db_env),
    ]

    if cfg.auth_dump is not None:
        steps.append(Step("auth-restore", argv=_mysql_pipe(cfg.auth_dump, cfg)))
        auth_sql = scrub.auth_scrub_statements(
            "mysql"
        ) + scrub.auth_synthesis_statements("mysql")
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


class Runner:
    """What `execute()` needs. Subclassed by the real runner and by test doubles."""

    def argv(self, step: Step) -> int:
        raise NotImplementedError

    def sql(self, step: Step) -> list[list[int]]:
        raise NotImplementedError


def execute(steps: Sequence[Step], runner: Runner) -> None:
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
    ) -> None:
        self.cfg = cfg
        self._run = run
        self._popen = popen
        self._server: subprocess.Popen | None = None

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

    def argv(self, step: Step) -> int:
        env = {**os.environ, **dict(step.env)}
        if step.background:
            self.cfg.workdir.mkdir(parents=True, exist_ok=True)
            self._server = self._popen(list(step.argv), env=env)
            return self._wait_for_server()
        if step.keep:
            return self._prune(step)
        return self._run(list(step.argv), env=env).returncode

    def _wait_for_server(self, attempts: int = 120) -> int:
        for _ in range(attempts):
            if self._run(self._mysql("SELECT 1")).returncode == 0:
                return 0
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
