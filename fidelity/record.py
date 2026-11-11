"""Record a scenario fixture from the overseer's own read paths (#2281).

    python3 -m fidelity.record --surface chronicle --guild <guild> \
        --name <scenario-name> --source "<where and when>" --out <file>

Environment: LIVEPROOF_DB_HOST and LIVEPROOF_DB_USER (required),
LIVEPROOF_DB_PASSWORD, LIVEPROOF_DB_PORT: the same read-only account the live
probes use. Capture is read-only twice over: every statement must be a single
SELECT (the liveproof guard) and the connection is pinned to read-only
transactions.

The surface runs unchanged over a RecordingReader, which keeps each read in
order. The expected claims are then derived from the capture by fidelity.derive
(never from the overseer's output), and the fixture is accepted only when
fidelity.verify re-derives the same claims from the same capture.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import realmread
from fidelity import derive, fixture, replay, surfaces, verify
from liveproof import run as liveproof

_PLACEHOLDER = re.compile(r"%%|%s")


class Refused(ValueError):
    """The capture is not accepted as a fixture."""


def guard(sql: str) -> None:
    """Refuse anything but a single read-only SELECT. Parameter placeholders
    stand in as a literal first, as they do not change what the statement is."""
    liveproof.check_select_only(
        _PLACEHOLDER.sub(lambda m: "%" if m.group() == "%%" else "1", sql)
    )


class RecordingReader(realmread.Reader):
    """A realm reader that guards each statement, asks `inner`, and keeps the
    read: statement, parameters, rows, and the gap if the realm lacks a table."""

    def __init__(self, inner: realmread.Reader) -> None:
        self.inner = inner
        self.reads: list = []

    def _run(self, sql: str, params) -> list:
        guard(sql)
        entry = {
            "sql": sql,
            "params": [] if params is None else list(params),
            "rows": [],
        }
        try:
            rows = self.inner.must(sql, params)
        except realmread.Gap as gap:
            entry["gap"] = gap.code
            self.reads.append(entry)
            raise
        entry["rows"] = [dict(r) for r in rows]
        self.reads.append(entry)
        return rows

    def close(self) -> None:
        self.inner.close()


def _alias(value, table: dict):
    if isinstance(value, str):
        for real, fake in table.items():
            value = value.replace(real, fake)
        return value
    if isinstance(value, dict):
        return {k: _alias(v, table) for k, v in value.items()}
    if isinstance(value, list):
        return [_alias(v, table) for v in value]
    return value


def record(
    surface: str,
    args: dict,
    reader: realmread.Reader,
    *,
    name: str,
    kind: str,
    source: str,
    alias: dict | None = None,
    captured_at: str = "",
) -> dict:
    """The fixture document for `surface` run over `reader`; Refused when the
    capture is not one the verifier accepts. Nothing is written here."""
    if kind not in fixture.KINDS:
        raise Refused("kind must be one of %s" % ", ".join(fixture.KINDS))
    if kind == fixture.REALM and not source.strip():
        raise Refused("a realm capture must say where and when it was taken")
    build, _project = surfaces.SURFACES[surface]
    tape = RecordingReader(reader)
    build(args, tape)
    provenance = {"kind": kind, "source": source}
    if captured_at:
        provenance["captured_at"] = captured_at
    table = alias or {}
    doc = {
        "format": fixture.FORMAT,
        "name": name,
        "provenance": provenance,
        "surface": surface,
        "args": _alias(args, table),
        "reads": [
            dict(
                read,
                params=_alias(fixture.encode(read["params"]), table),
                rows=_alias(fixture.encode(read["rows"]), table),
            )
            for read in tape.reads
        ],
        "expect": {},
    }
    try:
        doc["expect"] = derive.claims(fixture.parse(doc))
    except derive.NoCreditedRecord as err:
        raise Refused(str(err)) from err
    if not doc["expect"]["runs"]:
        raise Refused("the capture holds no run with a credited tally")
    problems = verify.problems(fixture.parse(doc))
    if problems:
        raise Refused("; ".join(problems))
    return doc


def main(argv=None, reader=None, env=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--surface", required=True, choices=sorted(surfaces.SURFACES))
    ap.add_argument("--guild", required=True, action="append")
    ap.add_argument("--name", required=True)
    ap.add_argument("--kind", choices=fixture.KINDS, default=fixture.REALM)
    ap.add_argument("--source", required=True)
    ap.add_argument("--alias", action="append", default=[], metavar="REAL=ALIAS")
    ap.add_argument("--out", required=True)
    opts = ap.parse_args(argv)
    table = dict(pair.split("=", 1) for pair in opts.alias)
    args = surfaces.default_args(opts.surface, opts.guild)
    own = reader is None
    if own:
        settings = liveproof.settings_from_env(os.environ if env is None else env)
        reader = realmread.Session(lambda: liveproof.connect(settings))
    try:
        doc = record(
            opts.surface,
            args,
            reader,
            name=opts.name,
            kind=opts.kind,
            source=opts.source,
            alias=table,
            captured_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
    except Refused as err:
        print("fidelity.record: not accepted: %s" % err, file=sys.stderr)
        return 1
    finally:
        if own:
            reader.close()
    Path(opts.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    result = replay.run(fixture.parse(doc))
    print("fidelity.record: wrote %s" % opts.out)
    for problem in result.problems:
        print("  the overseer disagrees with the record: %s" % problem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
