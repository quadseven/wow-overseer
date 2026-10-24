"""Leave a door the family stalls at twice running (#1041).

WHY THIS EXISTS. On 2026-10-15 a family ran Shadowfang Keep eleven times in a
row with no clear. Every run credited the same first four or six encounters,
then stopped: mod-overseer's clearing watchdog spent its three `dc skip`s, the
dungeon module switched itself off with nothing left it could reach, and the
run ended "stalled". The campaign's job still read `dungeon:shadowfang`, so
mod-overseer opened the next run of the same door half a minute later. The
pace ladder (dungeonpace.py) steps a family down after two WIPES; a stall is
not a wipe, nobody died, and nothing else in the bridge read it.

WHAT COUNTS (`stall_of`, `stuck_doors`). Per Run keyword (campaignplan.RUNS,
an alternate door counting toward its wing), the two latest runs that met the
dungeon (dungeonpace.FOUGHT; a staging or reset failure never reached an
encounter and is skipped). The door is STUCK when both stalled and the later
got no further than the earlier: every encounter it credited the earlier had
credited too. "The same boss" is the common case; a later stall at an EARLIER
boss is the same wall reached on a worse day (the family alternated between
encounter 4 and encounter 6 all afternoon), and a later stall FURTHER in is
progress, which earns the door another run.

  A run stalled when its row says `stalled` or the timeline holds a
  `stalled` row for it (the hearth fallback can close the row under another
  word). How far it got is the mask on its last `boss` row, 0 for none.

WHAT HAPPENS (`leave`, carried out by the bridge). When the family's queue head
is a stuck door, every pending entry for that door is cancelled, the family is
put on the default job at once (mod-overseer stands its run coordinator down
on a job that leaves `dungeon`, and walks the party out if it is inside), and
a closed overseer_dungeon_pace row (decision DECISION) records why. The next
queue pass starts the next entry, or the planner chooses a door, refusing a
stuck one (`barred`, campaignplan.REFUSED_STALLED); with neither the family
quests.

HOW LONG. As long as the two stalls are the door's latest fought runs inside
WINDOW_HOURS, the same window the pace ladder reads. A door that has aged out
of it is offered again, on the chance the module that stalled it has changed.

PURE MODULE: rows in, decisions and sentences out. The bridge reads and writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import campaignplan
import council
import dungeonpace
import jobs

# The pace table's decision for a door left after two stalls. Recorded closed:
# it opens no stretch for the ladder to close later.
DECISION = "stall_out"
STALLED = "stalled"
WINDOW_HOURS = dungeonpace.WINDOW_HOURS

RUNS_SQL = (
    "SELECT id, map_id, portal_keyword, outcome FROM overseer_dungeon_run "
    "WHERE state = 'ended' AND leader_name IN ({holes}) "
    "AND started_at >= NOW() - INTERVAL %s HOUR ORDER BY id"
)
# THE DOOR FROM THE RUN'S OWN TIMELINE, on a realm whose ledger has no
# `portal_keyword` yet (the column comes with a worldserver roll). Every
# timeline row names the portal the run went through, so the first one is the
# run's door. The two tables sit in different collation groups (infra#3173);
# they meet only on the integer run id, and the one string test is written in
# the timeline's own collation. Without this, RUNS_SQL failed on such a realm,
# the stall reads came back empty, and nothing was ever stuck: on the dev
# realm 2026-10-23 the Alliance family stalled at the Cathedral and Uldaman
# for days, stepping down and back up between them, while every pass read "the
# run ledger by door cannot be read on this realm".
RUNS_SQL_TIMELINE = (
    "SELECT r.id, r.map_id, (SELECT e.portal FROM overseer_dungeon_run_event e "
    "WHERE e.run_id = r.id AND e.portal <> _utf8mb4'' COLLATE utf8mb4_unicode_ci "
    "ORDER BY e.id LIMIT 1) "
    "AS portal_keyword, r.outcome FROM overseer_dungeon_run r "
    "WHERE r.state = 'ended' AND r.leader_name IN ({holes}) "
    "AND r.started_at >= NOW() - INTERVAL %s HOUR ORDER BY r.id"
)
EVENTS_SQL = (
    "SELECT run_id, kind, detail FROM overseer_dungeon_run_event "
    "WHERE run_id IN ({holes}) AND kind IN ('boss', 'stalled') ORDER BY id"
)
CANCEL_SQL = (
    "UPDATE overseer_dungeon_queue SET status = 'cancelled', finished_at = NOW() "
    "WHERE id = %s AND status IN ('queued', 'active')"
)

# The module's boss row ends "(mask <before> -> <after>)" (RunTimelineEvents).
_MASK = re.compile(r"\(mask \d+ -> (\d+)\)")
# The module's stalled row when `dc skip` was refused because the dungeon
# module had disabled itself (mod-overseer's clearing watchdog).
_SWITCHED_OFF = "switched itself off"


def holes(count: int) -> str:
    return dungeonpace.holes(count)


def mask_of(detail: str) -> int | None:
    """The encounter mask a `boss` row ends on, or None for any other text."""
    found = _MASK.search(str(detail or ""))
    return int(found.group(1)) if found else None


def door_of(row: dict) -> str:
    """The Run keyword a ledger row counts toward, the way the planner counts."""
    return campaignplan.wing_of(str(row.get("portal_keyword") or "")) or next(
        (
            r.keyword
            for r in campaignplan.RUNS
            if r.map_id == int(row.get("map_id") or 0)
        ),
        "",
    )


@dataclass(frozen=True)
class Stall:
    """Where one run stopped: the last mask credited, and the module's reason."""

    run_id: int
    mask: int
    reason: str

    @property
    def encounters(self) -> int:
        return bin(self.mask).count("1")

    @property
    def switched_off(self) -> bool:
        """The dungeon module disabled itself: every boss left was skipped."""
        return _SWITCHED_OFF in self.reason

    def said(self) -> str:
        where = (
            "after encounter %d" % self.encounters
            if self.encounters
            else "before its first encounter"
        )
        if self.switched_off:
            return "run %d: the dungeon module switched itself off %s" % (
                self.run_id,
                where,
            )
        return "run %d stalled %s" % (self.run_id, where)


def stall_of(row: dict, events: list) -> Stall | None:
    """Where `row`'s run stalled, from its own timeline rows; None if it did not."""
    rid = int(row.get("id") or 0)
    mine = [e for e in events or () if int(e.get("run_id") or 0) == rid]
    reasons = [str(e.get("detail") or "") for e in mine if e.get("kind") == STALLED]
    outcome = str(row.get("outcome") or "")
    if outcome == dungeonpace.COMPLETE or not (outcome == STALLED or reasons):
        return None
    masks = [mask_of(e.get("detail")) for e in mine if e.get("kind") == "boss"]
    masks = [m for m in masks if m is not None]
    return Stall(rid, masks[-1] if masks else 0, reasons[-1] if reasons else "")


def _fought_by_door(runs: list) -> dict:
    """Run keyword -> its fought ledger rows, oldest first."""
    out: dict = {}
    for row in sorted(runs or (), key=lambda r: int(r.get("id") or 0)):
        door = door_of(row)
        if door and str(row.get("outcome") or "") in dungeonpace.FOUGHT:
            out.setdefault(door, []).append(row)
    return out


def event_ids(runs: list) -> list:
    """The run ids whose timeline the judgment needs: each door's last two."""
    ids = []
    for rows in _fought_by_door(runs).values():
        ids.extend(int(r["id"]) for r in rows[-2:])
    return sorted(ids)


@dataclass(frozen=True)
class Stuck:
    """A door whose two latest fought runs stalled, the later no further in."""

    door: str
    earlier: Stall
    later: Stall

    @property
    def why(self) -> str:
        cause = self.later.reason or self.earlier.reason
        return "%s stalled twice running, the second no further in (%s; %s)%s" % (
            council.keyword_place(self.door),
            self.earlier.said(),
            self.later.said(),
            ": " + cause if cause else "",
        )


def stuck_doors(runs: list, events: list) -> dict:
    """Run keyword -> Stuck, for every door the family should not run again."""
    out = {}
    for door, rows in _fought_by_door(runs).items():
        if len(rows) < 2:
            continue
        earlier, later = (stall_of(r, events) for r in rows[-2:])
        if earlier and later and not later.mask & ~earlier.mask:
            out[door] = Stuck(door, earlier, later)
    return out


def barred(stuck: dict) -> dict:
    """Run keyword -> why the planner refuses it (campaignplan.Facts.stalled),
    led by its kind the way the planner's own refusals are."""
    return {door: "stalled: " + s.why for door, s in stuck.items()}


@dataclass(frozen=True)
class Leave:
    """The queue entries to cancel for a stuck door, and the sentence for it."""

    door: str
    drop: tuple
    why: str


def leave(rows: list, stuck: dict) -> Leave | None:
    """The leave for this family's queue `rows` (pending, in order), or None
    when its head is not a stuck door."""
    if not rows:
        return None
    door = campaignplan.wing_of(str(rows[0].get("keyword") or ""))
    if door not in stuck:
        return None
    drop = tuple(
        int(r["id"])
        for r in rows
        if campaignplan.wing_of(str(r.get("keyword") or "")) == door
    )
    rest = [r for r in rows if int(r["id"]) not in drop]
    after = (
        "%s runs next" % council.keyword_place(str(rest[0]["keyword"]))
        if rest
        else "back to %s until the planner finds another door" % jobs.DEFAULT
    )
    return Leave(door, drop, "%s; left, %s" % (stuck[door].why, after))
