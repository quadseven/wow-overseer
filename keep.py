"""Items a character must keep: the bridge side of mod-overseer's overseer_keep.

The operator reserves an item on a character in `overseer_keep`, one instance
by `item_guid` or every instance of `item_entry`. mod-overseer then refuses to
sell, destroy, give, trade, mail, auction or guild-bank it, and moves it
between the character's own bank and its hands by level. This module stops
the bridge from ASKING it to: every disposal row a pass writes names its item
as `guid:<n>` or `entry:<n>`, and a row naming a reserved item is not written.

The world would refuse the row anyway. Not writing it keeps the refusals out
of the queue and out of the passes that read their own refusals back, and it
covers a world image that predates the module's refusal.

The reservations are read at most once a minute through a fetch the caller
supplies, so this file needs no database of its own and the tests need none.
A fetch that fails keeps the last list it read: a hiccup must not make a
reserved item fair game for a minute.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

RELOAD_SECONDS = 60.0

_GUID = re.compile(r"(?<![a-z_])guid:(\d+)")
_ENTRY = re.compile(r"(?<![a-z_])entry:(\d+)")


@dataclass(frozen=True)
class Reservations:
    """What is reserved, keyed by lower-cased character name.

    `guids` holds instance guids: the named ones, plus every instance a
    character currently holds of an entry-wide reservation (the fetch resolves
    those). `entries` holds the entry-wide ones, for a row that names an entry.
    """

    guids: frozenset = field(default_factory=frozenset)
    entries: frozenset = field(default_factory=frozenset)


def from_rows(rows) -> Reservations:
    """Fold fetched rows into Reservations.

    Each row is a mapping with `character_name`, `item_entry` and `item_guid`,
    where `item_guid` 0 means every instance of `item_entry`. Rows naming
    neither are ignored, as the module ignores them.
    """
    guids = set()
    entries = set()
    for row in rows:
        name = str(row.get("character_name") or "").strip().lower()
        if not name:
            continue
        guid = int(row.get("item_guid") or 0)
        entry = int(row.get("item_entry") or 0)
        if guid:
            guids.add((name, guid))
        elif entry:
            entries.add((name, entry))
    return Reservations(frozenset(guids), frozenset(entries))


def items_named(command: str) -> tuple:
    """The (guids, entries) a command string names."""
    text = command or ""
    return (
        tuple(int(g) for g in _GUID.findall(text)),
        tuple(int(e) for e in _ENTRY.findall(text)),
    )


def reserved(reservations: Reservations, holder: str, command: str) -> bool:
    """Does this row, written for this holder, name a reserved item?"""
    name = (holder or "").strip().lower()
    guids, entries = items_named(command)
    return any((name, g) in reservations.guids for g in guids) or any(
        (name, e) in reservations.entries for e in entries
    )


class Keep:
    """The reservations, read through `fetch` at most every RELOAD_SECONDS."""

    def __init__(self, fetch, clock=time.monotonic):
        self._fetch = fetch
        self._clock = clock
        self._read_at = None
        self._reservations = Reservations()

    def now(self) -> Reservations:
        at = self._clock()
        if self._read_at is None or at - self._read_at >= RELOAD_SECONDS:
            try:
                rows = self._fetch()
            except Exception:  # noqa: BLE001 - a failed read keeps the last list
                rows = None
            if rows is not None:
                self._reservations = from_rows(rows)
            # Asked again a minute later either way, so a failing database is
            # not asked on every row a pass writes.
            self._read_at = at
        return self._reservations

    def blocks(self, holder: str, command: str) -> bool:
        return reserved(self.now(), holder, command)
