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
# Words that write, lock, combine statements or hand the text to another
# command: none of them can appear in a plain read-only SELECT, in a string
# or a comment aside (the tokeniser drops both before this check runs).
FORBIDDEN_WORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "TRUNCATE",
        "REPLACE",
        "ALTER",
        "CREATE",
        "GRANT",
        "REVOKE",
        "CALL",
        "SET",
        "EXECUTE",
        "HANDLER",
        "INTO",
        "OUTFILE",
        "DUMPFILE",
        "LOCK",
        "UNION",
        "INTERSECT",
        "EXCEPT",
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


def _tokens(sql: str) -> list[tuple[str, str]]:
    """(kind, value) tokens for `sql`, with comments and literals folded away.

    Words are upper-cased; a string literal, a number and a back-quoted name
    each become one token whose text the guard never reads, so a semicolon,
    a comment marker or a forbidden word inside one of them counts for
    nothing. Raises UnsafeStatement on an unterminated literal or comment
    and on a MySQL executable comment, whose text the server would run.
    """
    out: list[tuple[str, str]] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif (
            sql.startswith("--", i) and (i + 2 == n or sql[i + 2].isspace())
        ) or c == "#":
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
        elif sql.startswith("/*", i):
            if sql.startswith("/*!", i):
                raise UnsafeStatement("executable comments are not a plain SELECT")
            end = sql.find("*/", i + 2)
            if end < 0:
                raise UnsafeStatement("unterminated comment")
            i = end + 2
        elif c in "'\"":
            i += 1
            while i < n:
                if sql[i] == "\\" or (sql[i] == c and sql[i + 1 : i + 2] == c):
                    i += 2
                elif sql[i] == c:
                    break
                else:
                    i += 1
            if i >= n:
                raise UnsafeStatement("unterminated string literal")
            i += 1
            out.append(("literal", ""))
        elif c == "`":
            end = sql.find("`", i + 1)
            if end < 0:
                raise UnsafeStatement("unterminated quoted name")
            out.append(("name", sql[i + 1 : end].upper()))
            i = end + 1
        elif c.isalpha() or c in "_$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            out.append(("word", sql[i:j].upper()))
            i = j
        elif c.isdigit():
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "._"):
                j += 1
            out.append(("literal", ""))
            i = j
        else:
            out.append(("punct", c))
            i += 1
    return out


def _matching_paren(tokens: list[tuple[str, str]], start: int) -> int:
    """The index of the `)` closing the `(` at `start`, or -1 if there is none."""
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index] == ("punct", "("):
            depth += 1
        elif tokens[index] == ("punct", ")"):
            depth -= 1
            if depth == 0:
                return index
    return -1


def _check_with(tokens: list[tuple[str, str]]) -> None:
    """Validate the WITH prefix: CTE definitions, then one main SELECT."""
    pos = 1
    if pos < len(tokens) and tokens[pos] == ("word", "RECURSIVE"):
        pos += 1
    while True:
        if pos >= len(tokens) or tokens[pos][0] not in ("word", "name"):
            raise UnsafeStatement("WITH clause has no table name")
        pos += 1
        if pos < len(tokens) and tokens[pos] == ("punct", "("):
            close = _matching_paren(tokens, pos)
            if close < 0:
                raise UnsafeStatement("unbalanced parentheses")
            pos = close + 1
        if pos >= len(tokens) or tokens[pos] != ("word", "AS"):
            raise UnsafeStatement("WITH clause has no AS")
        pos += 1
        if pos >= len(tokens) or tokens[pos] != ("punct", "("):
            raise UnsafeStatement("WITH clause has no definition")
        if pos + 1 >= len(tokens) or tokens[pos + 1] not in (
            ("word", "SELECT"),
            ("word", "WITH"),
        ):
            raise UnsafeStatement("a WITH definition is not a SELECT")
        close = _matching_paren(tokens, pos)
        if close < 0:
            raise UnsafeStatement("unbalanced parentheses")
        pos = close + 1
        if pos < len(tokens) and tokens[pos] == ("punct", ","):
            pos += 1
            continue
        break
    if pos >= len(tokens) or tokens[pos] != ("word", "SELECT"):
        raise UnsafeStatement("WITH clause has no main SELECT")


def check_select_only(sql: str) -> None:
    """Raise UnsafeStatement unless `sql` is exactly one plain SELECT.

    A standard-library token guard, not a full parse (the lane check runs
    plain python3 with no third-party parser installed): the text must hold
    one SELECT (or WITH ... SELECT) statement and nothing else, with no
    forbidden word or function anywhere outside a literal or a comment.
    The database account is SELECT-only and the connection is read-only,
    so this guard is the first of three lines, not the only one.
    """
    tokens = _tokens(sql)
    while tokens and tokens[-1] == ("punct", ";"):
        tokens.pop()
    if not tokens:
        raise UnsafeStatement("expected one statement, found 0")
    if ("punct", ";") in tokens:
        raise UnsafeStatement("expected one statement, found more than one")
    depth = 0
    top_selects = 0
    for index, token in enumerate(tokens):
        kind, value = token
        if token == ("punct", "("):
            depth += 1
        elif token == ("punct", ")"):
            depth -= 1
            if depth < 0:
                raise UnsafeStatement("unbalanced parentheses")
        if kind != "word":
            continue
        if value in FORBIDDEN_WORDS:
            raise UnsafeStatement(f"forbidden clause: {value}")
        if value in FORBIDDEN_FUNCTIONS and tokens[index + 1 : index + 2] == [
            ("punct", "(")
        ]:
            raise UnsafeStatement(f"forbidden function: {value}")
        if value == "SELECT" and depth == 0:
            top_selects += 1
    if depth != 0:
        raise UnsafeStatement("unbalanced parentheses")
    if tokens[0] == ("word", "WITH"):
        _check_with(tokens)
    elif tokens[0] != ("word", "SELECT"):
        raise UnsafeStatement(f"not a SELECT: {tokens[0][1] or tokens[0][0]}")
    if top_selects != 1:
        raise UnsafeStatement(f"expected one SELECT, found {top_selects}")


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
