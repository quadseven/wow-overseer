"""Table classes: how the forge treats each table of the characters schema.

The classes live in `forge/table-classes.yaml`, one line per table. The file
uses a tiny subset of YAML (`name: class [spec]`, `#` comments) so the forge
needs no YAML library.

    keep           rows survive unchanged
    truncate       every row removed
    scrub          rows survive, named columns reset (spec names the rule)
    per-character  rows survive only for kept characters (spec: key column, or
                   `col > parent.col` to follow a parent table trimmed first)
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

KINDS = ("keep", "truncate", "scrub", "per-character")
DEFAULT_PATH = pathlib.Path(__file__).with_name("table-classes.yaml")

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_LINE = re.compile(
    rf"^(?P<table>{_IDENT})\s*:\s*(?P<kind>[a-z-]+)(?:\s+(?P<spec>.*?))?\s*$"
)
_DEPENDENT = re.compile(
    rf"^(?P<key>{_IDENT})\s*>\s*(?P<table>{_IDENT})\.(?P<col>{_IDENT})$"
)
_PLAIN_KEY = re.compile(rf"^{_IDENT}$")
_SCRUB_RULE = re.compile(r"^[a-z][a-z-]*$")


class ClassError(ValueError):
    """The classes file is malformed."""


@dataclass(frozen=True)
class TableClass:
    table: str
    kind: str
    spec: str = ""
    key: str = ""
    parent: tuple[str, str] | None = None


def parse_classes(text: str) -> dict[str, TableClass]:
    found: dict[str, TableClass] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = _LINE.match(line)
        if match is None:
            raise ClassError(f"line {number}: cannot read {raw!r}")
        table, kind, spec = match["table"], match["kind"], (match["spec"] or "").strip()
        if kind not in KINDS:
            raise ClassError(f"line {number}: {table}: unknown class {kind!r}")
        if table in found:
            raise ClassError(f"line {number}: {table} is classified twice")
        found[table] = _entry(number, table, kind, spec)
    _check_parents(found)
    return found


def _entry(number: int, table: str, kind: str, spec: str) -> TableClass:
    if kind == "per-character":
        if not spec:
            raise ClassError(
                f"line {number}: {table}: per-character needs a key column"
            )
        dependent = _DEPENDENT.match(spec)
        if dependent:
            return TableClass(
                table,
                kind,
                spec,
                dependent["key"],
                (dependent["table"], dependent["col"]),
            )
        if not _PLAIN_KEY.match(spec):
            raise ClassError(f"line {number}: {table}: bad key {spec!r}")
        return TableClass(table, kind, spec, spec)
    if kind == "scrub":
        if not _SCRUB_RULE.match(spec):
            raise ClassError(f"line {number}: {table}: scrub needs a rule name")
        return TableClass(table, kind, spec)
    if spec:
        raise ClassError(f"line {number}: {table}: {kind} takes no spec")
    return TableClass(table, kind)


def _check_parents(found: dict[str, TableClass]) -> None:
    for entry in found.values():
        if entry.parent is None:
            continue
        parent = found.get(entry.parent[0])
        if parent is None or parent.kind != "per-character":
            raise ClassError(
                f"{entry.table}: parent {entry.parent[0]} is not a per-character table"
            )
    for entry in found.values():
        seen = {entry.table}
        node = entry
        while node.parent is not None:
            name = node.parent[0]
            if name in seen:
                raise ClassError(f"{entry.table}: parent chain loops through {name}")
            seen.add(name)
            node = found[name]


def load_classes(path: pathlib.Path = DEFAULT_PATH) -> dict[str, TableClass]:
    return parse_classes(pathlib.Path(path).read_text(encoding="utf-8"))


def unclassified(tables: list[str], found: dict[str, TableClass]) -> list[str]:
    """Tables in the schema that have no class."""
    return sorted(t for t in tables if t not in found)


def stale(tables: list[str], found: dict[str, TableClass]) -> list[str]:
    """Classified tables that the schema no longer has."""
    present = set(tables)
    return sorted(t for t in found if t not in present)


def trim_order(found: dict[str, TableClass]) -> list[TableClass]:
    """Per-character tables, each after the parent it follows."""
    wanted = {n: e for n, e in found.items() if e.kind == "per-character"}
    ordered: list[TableClass] = []
    placed: set[str] = set()

    def place(name: str) -> None:
        if name in placed:
            return
        entry = wanted[name]
        if entry.parent is not None:
            place(entry.parent[0])
        placed.add(name)
        ordered.append(entry)

    for name in sorted(wanted):
        place(name)
    return ordered
