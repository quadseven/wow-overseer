"""The scenario fixture format (#2281).

    {
      "format": 1,
      "name": "synthetic-not-a-full-clear",
      "provenance": {"kind": "realm" | "synthetic", "source": "...", ...},
      "surface": "chronicle",
      "args": {...},                    what the surface is asked
      "reads": [{"sql", "params", "rows"}, ...],   recorded realm reads, in order
      "expect": {...},                  claims from the credited record
    }

`synthetic` marks rows written to exercise the machinery. They are never
realm truth and never stand as evidence for a ticket.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FORMAT = 1
REALM = "realm"
SYNTHETIC = "synthetic"
KINDS = (REALM, SYNTHETIC)


class FixtureError(ValueError):
    """A fixture file that does not follow the format."""


@dataclass(frozen=True)
class Read:
    sql: str
    params: tuple
    rows: list


@dataclass(frozen=True)
class Fixture:
    name: str
    kind: str
    source: str
    surface: str
    args: dict
    reads: tuple
    expect: dict


def _need(doc: dict, key: str, kind: type):
    if not isinstance(doc.get(key), kind):
        raise FixtureError("%s must be a %s" % (key, kind.__name__))
    return doc[key]


def parse(doc: dict) -> Fixture:
    """A Fixture from a decoded document; FixtureError when it is malformed."""
    if not isinstance(doc, dict):
        raise FixtureError("a fixture is a JSON object")
    if doc.get("format") != FORMAT:
        raise FixtureError("format must be %d" % FORMAT)
    provenance = _need(doc, "provenance", dict)
    if provenance.get("kind") not in KINDS:
        raise FixtureError("provenance kind must be one of %s" % ", ".join(KINDS))
    reads = []
    for i, read in enumerate(_need(doc, "reads", list)):
        if not isinstance(read, dict) or not isinstance(read.get("sql"), str):
            raise FixtureError("read %d needs sql text" % i)
        if not isinstance(read.get("params"), list):
            raise FixtureError("read %d needs a params list" % i)
        if not isinstance(read.get("rows"), list):
            raise FixtureError("read %d needs a rows list" % i)
        reads.append(Read(read["sql"], tuple(read["params"]), read["rows"]))
    return Fixture(
        name=_need(doc, "name", str),
        kind=provenance["kind"],
        source=str(provenance.get("source") or ""),
        surface=_need(doc, "surface", str),
        args=_need(doc, "args", dict),
        reads=tuple(reads),
        expect=_need(doc, "expect", dict),
    )


def load(path) -> Fixture:
    try:
        return parse(json.loads(Path(path).read_text()))
    except json.JSONDecodeError as err:
        raise FixtureError("%s: not JSON: %s" % (path, err)) from err
