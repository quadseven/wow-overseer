"""The scenario fixture format (#2281).

    {
      "format": 1,
      "name": "synthetic-not-a-full-clear",
      "provenance": {"kind": "realm" | "synthetic", "source": "...", ...},
      "surface": "chronicle",
      "args": {...},                    what the surface is asked
      "reads": [{"sql", "params", "rows"}, ...],   recorded realm reads, in order
      "expect": {...},                  claims from the credited record
      "proves": [2000, ...]             optional; realm fixtures only
    }

`synthetic` marks rows written to exercise the machinery. They are never
realm truth and never stand as evidence for a ticket.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

FORMAT = 1
REALM = "realm"
SYNTHETIC = "synthetic"
KINDS = (REALM, SYNTHETIC)


class FixtureError(ValueError):
    """A fixture file that does not follow the format."""


def encode(value):
    """`value` with the types MySQL rows carry that JSON lacks tagged: a time
    as {"$datetime": ISO}, a decimal as {"$decimal": text}."""
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value):
    """The inverse of `encode`."""
    if isinstance(value, dict):
        if set(value) == {"$datetime"}:
            return datetime.fromisoformat(value["$datetime"])
        if set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


@dataclass(frozen=True)
class Read:
    sql: str
    params: tuple
    rows: list
    gap: int = 0  # a missing table (1146) or column (1054) the realm answered with


@dataclass(frozen=True)
class Fixture:
    name: str
    kind: str
    source: str
    surface: str
    args: dict
    reads: tuple
    expect: dict
    proves: tuple = ()  # awaiting-live-check tickets whose behavior this proves


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
        reads.append(
            Read(
                read["sql"],
                tuple(decode(read["params"])),
                decode(read["rows"]),
                int(read.get("gap") or 0),
            )
        )
    proves = doc.get("proves") or []
    if not isinstance(proves, list) or not all(isinstance(t, int) for t in proves):
        raise FixtureError("proves must be a list of ticket numbers")
    if proves and provenance["kind"] != REALM:
        raise FixtureError("a synthetic fixture cannot prove a ticket")
    if provenance["kind"] == REALM and not str(provenance.get("source") or "").strip():
        raise FixtureError("a realm fixture must say where and when it was captured")
    return Fixture(
        name=_need(doc, "name", str),
        kind=provenance["kind"],
        source=str(provenance.get("source") or ""),
        surface=_need(doc, "surface", str),
        args=_need(doc, "args", dict),
        reads=tuple(reads),
        expect=_need(doc, "expect", dict),
        proves=tuple(proves),
    )


def load(path) -> Fixture:
    try:
        return parse(json.loads(Path(path).read_text()))
    except json.JSONDecodeError as err:
        raise FixtureError("%s: not JSON: %s" % (path, err)) from err
