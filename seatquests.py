"""Raid seats take the quests their quest items name (#2648).

Read on the dev realm on 2026-11-15: about 40 percent of the quest-class
stacks the guilds carry are named by a quest the holder has not taken and
could. Nothing sent the holder to take them, so they sat in the bags.

WHAT THIS DOES. For each approved raid seat in the world, once in
REFRESH_SECONDS, it reads the seat's quest-class items and the quests that
name them (`questuntaken`), keeps the quests the seat may take (class, race,
level window, prerequisites, never in the log, never rewarded) and the giver
spawns that start them, and hands the guild job the list on the member
(`guildjobs.Member.untaken`). `guildjobs._untaken_step` turns it into one walk
and one `take quest:` row on a town stop, once per quest on a cooldown. The
seat's own questing finishes the quest.

Nothing here reads the world: `relieve` is handed the read, as `seatbags` is.
A member whose rewarded quests are unread is never sent: unknown takes nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

import questbook
import questuntaken
import seatbags

PREFIX = "seat quests:"
REFRESH_SECONDS = 1800.0
# A quest more than this many levels over the seat is not taken for an item.
LEVEL_REACH = 4
ENV = "GUILD_SEAT_QUESTS"


def enabled(environ=None) -> bool:
    """On unless GUILD_SEAT_QUESTS says off."""
    env = os.environ if environ is None else environ
    return str(env.get(ENV, "on")).strip().lower() not in ("off", "0", "false", "no")


@dataclass(frozen=True)
class Read:
    """What one read of the world gives for a set of seats."""

    rows: tuple = ()  # quest_template joined rows naming the carried items
    carried: dict = field(default_factory=dict)  # name -> quest-class item ids
    givers: dict = field(default_factory=dict)  # quest id -> giver Spots


def applies(member) -> bool:
    """An approved raid seat in the world that can be told what it may take."""
    return bool(
        seatbags.is_seat(member)
        and member.online
        and member.alive
        and not member.follows
        and member.rewarded is not None
    )


def _quest_member(m) -> questbook.Member:
    return questbook.Member(
        name=m.name,
        class_id=int(m.class_id),
        race_id=int(m.race),
        level=int(m.level),
        rewarded=frozenset(m.rewarded or ()) | frozenset(m.quests_done or ()),
        held=frozenset(int(q) for q in (m.quest_log or {})),
    )


def covers(members, read: Read) -> dict:
    """name -> (Untaken, ...) the seat may take now, for the members given."""
    naming = questuntaken.item_quests(read.rows)
    catalog = {int(r["ID"]): questbook.Quest.from_row(r) for r in read.rows}
    starts = {int(r["ID"]): int(r.get("StartItem") or 0) for r in read.rows}
    out: dict = {}
    for m in members:
        carried = frozenset(int(i) for i in read.carried.get(m.name, ()))
        cover = questuntaken.untaken_for(_quest_member(m), carried, naming, catalog)
        keep = []
        for u in cover.quests:
            if int(catalog[u.quest_id].quest_level) > int(m.level) + LEVEL_REACH:
                continue
            givers = tuple(read.givers.get(u.quest_id, ()))
            start = starts.get(u.quest_id, 0)
            by_item = bool(start) and start in carried
            if not givers and not by_item:
                continue
            keep.append(replace(u, givers=givers, by_item=by_item))
        out[m.name] = (tuple(keep), cover)
    return out


class Memo:
    """Each seat's last answer, so the world is read at most once in
    REFRESH_SECONDS per seat."""

    def __init__(self):
        self._at: dict = {}
        self._found: dict = {}

    def fresh(self, name, now) -> bool:
        return name in self._at and now - self._at[name] < REFRESH_SECONDS

    def keep(self, name, found, now) -> None:
        self._at[name] = now
        self._found[name] = found

    def found(self, name) -> tuple:
        return self._found.get(name, ())


def relieve(members, read, now, memo, environ=None):
    """(members with each seat's takable quests attached, log lines).

    `read(names)` returns a `Read` for those seats, or None when the world
    could not be read; the pass then carries on with the members as they were.
    """
    if not enabled(environ):
        return list(members), ()
    seats = [m for m in members if applies(m)]
    due = [m for m in seats if not memo.fresh(m.name, now)]
    lines = []
    if due:
        got = read([m.name for m in due])
        if got is not None:
            for m in due:
                found, cover = covers([m], got)[m.name]
                memo.keep(m.name, found, now)
                if cover.quests or cover.refused:
                    lines.append(
                        "%s %s %d items covered, %d takable, %d with a giver, "
                        "%d closed"
                        % (
                            PREFIX,
                            m.name,
                            len(cover.items),
                            len(cover.quests),
                            len(found),
                            len(cover.refused),
                        )
                    )
    out = []
    for m in members:
        found = memo.found(m.name) if m in seats else ()
        out.append(replace(m, untaken=found) if found else m)
    return out, tuple(lines)
