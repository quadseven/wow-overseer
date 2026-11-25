"""The Molten Core first-kill order that writes itself.

WHAT THIS IS FOR. A Molten Core first-kill order is otherwise written only when
a person types one. Where the guild's eligible approved seats already meet the
first-kill quorum, this pass offers the same order the Upper Spire run writes
for itself (spirerun.order_slot), through the same queue row a typed first-kill
order writes. The queue then seats and starts it by the existing path.

OFF BY DEFAULT. The operator turns it on with RAID_MC_SELF_ORDER=1 in the
bridge's environment (see docs/OPERATIONS.md).

PURE MODULE, same seam as spirerun.py: rows in, decisions out, nothing that
talks to MySQL. bridge.py runs the statements named here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import raidrun
import spirerun

KEYWORD = raidrun.MOLTEN_CORE
SOURCE = "overseer:mc-first-kill"
ENV = "RAID_MC_SELF_ORDER"

ORDER = "order"
SHORT = "short"
WAIT = "wait"

LAST_SQL = spirerun.LAST_SQL
ORDER_SQL = (
    "INSERT INTO overseer_dungeon_queue "
    "(family, position, keyword, runs_wanted, source, first_kill) "
    "SELECT %s, %s, %s, %s, %s, 1 FROM (SELECT 1) AS one WHERE NOT EXISTS ("
    "SELECT 1 FROM overseer_dungeon_queue p WHERE p.family = %s AND p.keyword = %s "
    "AND p.status IN ('queued', 'active'))"
)


@dataclass(frozen=True)
class Decision:
    """What this pass does for one family, and the line to log."""

    action: str
    line: str
    slot: spirerun.Slot | None = None


def enabled(environ=None) -> bool:
    """Whether the operator turned the self-order on. Off when unset."""
    env = os.environ if environ is None else environ
    return str(env.get(ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def waiting(rows: list, last: spirerun.Last | None, now: float) -> str:
    """Why no order is owed yet, or "" when the family may be read.

    Cheap: it reads only the queue, so a family that waits costs no guild read.
    """
    for row in rows:
        if str(row.get("keyword")) == KEYWORD:
            return "waits: a Molten Core order is already %s" % row.get("status")
    ahead = spirerun._stands_ahead(rows)
    if ahead:
        return "waits behind %s" % ", ".join(
            "%s (%s)" % (r.get("keyword"), r.get("status"))
            for r in sorted(ahead, key=lambda r: int(r["position"]))
        )
    if last is not None and spirerun.order_slot([], last, now, KEYWORD) is None:
        return spirerun.wait_line(last, now)
    return ""


def shortage(roster: raidrun.FirstKillRoster, quorum: tuple) -> str:
    """What the eligible seats lack against the quorum, with the role named."""
    roles = [
        m.get("role")
        for g in roster.lineup.get("groups") or []
        for m in g.get("members") or []
    ]
    have = (len(roster.seats), roles.count("tank"), roles.count("healer"))
    gaps = [
        "%d %s" % (want - got, name)
        for got, want, name in zip(have, quorum, ("seats", "tanks", "healers"), strict=True)
        if got < want
    ]
    return "short by " + ", ".join(gaps) if gaps else ""


def decide(
    rows: list,
    last: spirerun.Last | None,
    now: float,
    roster: raidrun.FirstKillRoster,
    quorum: tuple,
) -> Decision:
    """Order, say short, or wait. Never rewrites the approved lineup."""
    why = waiting(rows, last, now)
    if why:
        return Decision(WAIT, why)
    if roster.refusal:
        return Decision(SHORT, shortage(roster, quorum) or roster.refusal)
    slot = spirerun.order_slot(rows, last, now, KEYWORD)
    if slot is None:
        return Decision(WAIT, "waits out its last order")
    return Decision(ORDER, roster.line, slot)
