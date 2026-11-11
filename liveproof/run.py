"""Run every live proof probe against a read-only database; write verdicts.

Each probe is one .sql file under liveproof/probes/<repo>/<ticket>.sql: a
header (`-- ticket: N`, `-- repo: owner/name`) and one SELECT that returns a
single row of ticket, verdict, evidence. A statement that is not a single
SELECT is refused before it reaches the database. The run writes
verdicts-<UTC time>.json and exits 0 (a probe that fails is an `error`
verdict in the file, never a crash). See docs/LIVEPROOF.md (#2125).

Environment: LIVEPROOF_DB_HOST, LIVEPROOF_DB_USER (required),
LIVEPROOF_DB_PASSWORD, LIVEPROOF_DB_PORT, LIVEPROOF_OUT.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VERDICTS = ("proven", "disproven", "no_evidence")
ERROR = "error"
REPOS = ("quadseven/wow-overseer", "quadseven/mod-overseer")
MAX_EVIDENCE = 500
SCHEMA = 1
# Functions that read files, take locks or burn time: never part of a proof.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "SLEEP",
        "BENCHMARK",
        "LOAD_FILE",
        "GET_LOCK",
        "RELEASE_LOCK",
        "RELEASE_ALL_LOCKS",
        "IS_FREE_LOCK",
        "IS_USED_LOCK",
        "SYS_EXEC",
        "SYS_EVAL",
    }
)
_HEADER = re.compile(r"^--\s*(ticket|repo):\s*(\S+)\s*$")


class UnsafeStatement(ValueError):
    """The text is not a single read-only SELECT."""


class ProbeFileError(ValueError):
    """A probe file has a bad header or a name that does not match it."""


@dataclass(frozen=True)
class Probe:
    ticket: str
    repo: str
    sql: str
    path: str


def check_select_only(sql: str) -> None:
    """Raise UnsafeStatement unless `sql` parses as exactly one plain SELECT."""
    # AI-REVIEW 2026-11-11 [Codex/in-process/security-review] 2242-R1:
    # Parse function identities, including quoted names; never fall back to
    # a lexer that can miss the forbidden functions below (PR #2242).
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as err:
        raise UnsafeStatement(
            "SELECT validation requires sqlglot; install tests/requirements.txt"
        ) from err

    try:
        statements = [s for s in sqlglot.parse(sql, read="mysql") if s is not None]
    except sqlglot.errors.SqlglotError as err:
        raise UnsafeStatement(f"does not parse: {str(err)[:80]}") from err
    if len(statements) != 1:
        raise UnsafeStatement(f"expected one statement, found {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise UnsafeStatement(f"not a SELECT: {type(tree).__name__}")
    for node in tree.walk():
        if isinstance(node, (exp.Into, exp.Lock, exp.Command)):
            raise UnsafeStatement(f"forbidden clause: {type(node).__name__}")
        if isinstance(node, exp.Func):
            name = (
                node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            ).upper()
            if name in FORBIDDEN_FUNCTIONS:
                raise UnsafeStatement(f"forbidden function: {name}")


def load_probe(path: Path | str) -> Probe:
    path = Path(path)
    text = path.read_text()
    header = {}
    for line in text.splitlines():
        m = _HEADER.match(line)
        if m:
            header.setdefault(m.group(1), m.group(2))
    ticket, repo = header.get("ticket"), header.get("repo")
    if not ticket or not repo:
        raise ProbeFileError(f"{path}: header needs '-- ticket:' and '-- repo:'")
    if not ticket.isdigit() or path.stem != ticket:
        raise ProbeFileError(
            f"{path}: file name must be <ticket>.sql, header says {ticket}"
        )
    if repo not in REPOS:
        raise ProbeFileError(f"{path}: repo {repo} is not one of {', '.join(REPOS)}")
    return Probe(ticket=ticket, repo=repo, sql=text, path=str(path))


def load_probes(root: Path | str) -> list[Probe]:
    return [load_probe(p) for p in sorted(Path(root).glob("*/*.sql"))]


def _ascii(text: object, limit: int = MAX_EVIDENCE) -> str:
    return str(text).encode("ascii", "replace").decode("ascii")[:limit]


def _result(probe: Probe, verdict: str, evidence: object) -> dict:
    return {
        "ticket": probe.ticket,
        "repo": probe.repo,
        "verdict": verdict,
        "evidence": _ascii(evidence),
    }


def run_probe(conn, probe: Probe) -> dict:
    """Evaluate one probe. Never raises: a failure is an `error` verdict."""
    try:
        check_select_only(probe.sql)
    except UnsafeStatement as err:
        return _result(probe, ERROR, f"refused: {err}")
    try:
        with conn.cursor() as cur:
            cur.execute(probe.sql)
            rows = list(cur.fetchall())
    except Exception as err:  # noqa: BLE001 - any driver failure is recorded
        return _result(probe, ERROR, f"query failed: {type(err).__name__}: {err}")
    if len(rows) != 1:
        return _result(probe, ERROR, f"expected one row, got {len(rows)}")
    row = tuple(rows[0].values()) if isinstance(rows[0], dict) else tuple(rows[0])
    if len(row) != 3:
        return _result(probe, ERROR, f"expected 3 columns, got {len(row)}")
    ticket, verdict, evidence = row
    if str(ticket) != probe.ticket:
        return _result(
            probe, ERROR, f"row names ticket {ticket}, probe is {probe.ticket}"
        )
    if verdict not in VERDICTS:
        return _result(probe, ERROR, f"unknown verdict {verdict!r}")
    return _result(probe, verdict, evidence)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_all(probes: list[Probe], conn, now: str | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "run_at": now or _now(),
        "results": [run_probe(conn, p) for p in probes],
    }


def settings_from_env(env) -> dict:
    missing = [k for k in ("LIVEPROOF_DB_HOST", "LIVEPROOF_DB_USER") if not env.get(k)]
    if missing:
        raise SystemExit(f"liveproof: set {' and '.join(missing)}")
    return {
        "host": env["LIVEPROOF_DB_HOST"],
        "user": env["LIVEPROOF_DB_USER"],
        "password": env.get("LIVEPROOF_DB_PASSWORD", ""),
        "port": int(env.get("LIVEPROOF_DB_PORT", "3306")),
    }


def connect(settings: dict):
    """A MySQL connection pinned to read-only transactions."""
    import pymysql

    conn = pymysql.connect(
        host=settings["host"],
        user=settings["user"],
        password=settings["password"],
        port=settings["port"],
        connect_timeout=10,
        read_timeout=60,
        autocommit=True,
        charset="utf8mb4",
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.execute("SET SESSION time_zone = '+00:00'")
    return conn


class _Unavailable:
    """Stands in for a connection that never opened: every probe errors."""

    def __init__(self, err: Exception):
        self.err = err

    def cursor(self):
        raise self.err


def main(argv=None, env=None) -> int:
    env = os.environ if env is None else env
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--probes", default=str(here / "probes"))
    ap.add_argument("--out", default=env.get("LIVEPROOF_OUT") or str(here / "verdicts"))
    args = ap.parse_args(argv)

    probes = load_probes(args.probes)
    settings = settings_from_env(env)
    try:
        conn = connect(settings)
    except Exception as err:  # noqa: BLE001 - recorded per probe below
        conn = _Unavailable(err)
    doc = run_all(probes, conn)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = doc["run_at"].replace("-", "").replace(":", "")
    target = out / f"verdicts-{stamp}.json"
    target.write_text(json.dumps(doc, indent=2) + "\n")
    counts = {}
    for r in doc["results"]:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"liveproof: {len(probes)} probes, {counts}, wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
