"""May the economy send this member off on an errand of its own (#2323).

WHY THIS EXISTS. A member whose own errand kept its family waiting at a
dungeon door is handed the errand back after dungeonstall.RECALL_SECONDS
(#2280), and is then not to be sent out again for
dungeonstall.RECALL_COOLDOWN_SECONDS. That cooldown was read by one writer
only, the bag pressure vendor aim. The bank, guild bank, repair, craft supply
and forge passes asked nobody, so any of them could aim the same member again
on the next cycle: recall at ten minutes, a new aim, recall at ten minutes
again. Each recall also restarted the member's hold clock, so the 30 minute
stand-down behind the recall never came due.

The same held for the instance guard: only the bag pressure aim refused a
member standing inside an instance, and an aim taken there walks the member
out of the dungeon when the run stops clearing.

WHAT IS DECIDED HERE.

  `decide` is the one rule every economy aim writer asks before it writes: a
  member inside an instance is held, a member recalled inside the cooldown is
  held, anybody else is allowed. The answer is data (`Verdict`): the reason
  is a word a test or a log line can read, and the seconds left are counted.

  WHO IS "THE ECONOMY" is the pass that asks, named by its town slot claimant
  (`ECONOMY_CLAIMANTS`). The other claimants (`OTHER_CLAIMANTS`) walk for the
  campaign or for a member's progression and are not held, each with its
  reason written beside it. A claimant in neither set is allowed here and
  refused by the source scan in tests/test_errand_recall_loop.py, so a new
  pass is classified before it merges.

  `resume_since` and `recall_due` keep the stand-down clock across a recall.
  A member seen on an errand again inside the cooldown, under the same queue
  entry, goes on with the clock its recalled errand had (`Served`): it is
  counted from when that errand began, as if the recall had not happened.
  The time back with the party is counted too, on purpose. A clock that
  counted only the time seen on the errand would never grow where it matters,
  because a member aimed again between two passes is recalled the moment it
  is seen. A member whose clock reaches dungeonstall.HOLD_SECONDS is not
  recalled again: the stand-down is the answer, and repeated recalls cannot
  defer it. A run that credits a boss still starts every hold clock over
  (the bridge caps the age by the newest credit), so this ends only a run
  that has made no progress since the first errand began.

PURE MODULE: clocks and facts in, verdicts out. The bridge reads the map and
the recall book, and writes.
"""

from __future__ import annotations

from dataclasses import dataclass

import dungeonstall

# The reasons a verdict holds an aim, as words.
INSIDE_INSTANCE = "inside_instance"
RECALL_COOLDOWN = "recall_cooldown"
DEAD = "dead"

# The town slot claimants whose aim is a self-contained economy errand: the
# member leaves the party for a counter, a mailbox or a forge and comes back.
ECONOMY_CLAIMANTS = frozenset(
    {
        "auction",
        "bag pressure",
        "bags",
        "bank",
        "clearance",
        "craft_supply",
        "economy",
        "forge",
        "gear house",
        "gear vendor",
        "gearup",
        "guild bank",
        "mail",
        "towntrip",
    }
)

# The claimants that are not held, and why each is not the economy's.
OTHER_CLAIMANTS = {
    "attunement": "a step of the run's own attunement",
    "dark-iron": "a step of the fire resistance plan the raid waits on",
    "dungeon quests": "the run's own quest givers",
    "flight": "the family's flight network, walked by the leader",
    "gather": "a gatherer's walk to a node it can open",
    "guild route": "a guild courier's standing route",
    "level": "the family's move to its next levelling hub",
    "recipehunt": "a recipe the campaign plan asked for",
    "town errand": "the family's own town visit, taken together",
    "weapon master": "a weapon skill the campaign plan asked for",
}


def is_economy(claimant) -> bool:
    """Is this town slot claimant one of the economy's own passes?"""
    return str(claimant or "") in ECONOMY_CLAIMANTS


@dataclass(frozen=True)
class Verdict:
    """Whether an aim may be written, and why not when it may not."""

    allow: bool
    reason: str = ""
    left_seconds: float = 0.0

    def said(self, member: str, claimant: str) -> str:
        """The held aim in words for the log, or "" for an allowed one."""
        if self.reason == INSIDE_INSTANCE:
            return (
                "%s is inside an instance, so %s takes no errand for it; an "
                "errand belongs between runs" % (member, claimant)
            )
        if self.reason == RECALL_COOLDOWN:
            minutes = max(1, int(-(-self.left_seconds // 60)))
            return (
                "%s was called back from an errand of its own while its "
                "family waited at a door, so %s takes no errand for it for "
                "%d more minute(s)" % (member, claimant, minutes)
            )
        if self.reason == DEAD:
            return (
                "%s is dead or a ghost, so %s takes no errand for it; the "
                "corpse run comes first" % (member, claimant)
            )
        return ""


ALLOWED = Verdict(True)


def dead_hold(dead: bool) -> Verdict:
    """A dead or ghost traveller is aimed nowhere, by any claimant.

    The module refuses every walk for a character that is dead, so an aim
    written for one is handed back at once and the quest drive takes the
    leader again, over and over, while the corpse run never starts. Every
    claimant is held, the economy's and the campaign's alike: nothing walks
    a body that has not been recovered."""
    return Verdict(False, DEAD) if dead else ALLOWED


def decide(now, last_recall_at, aim_kind, inside_instance: bool = False) -> Verdict:
    """May the pass `aim_kind` (its town slot claimant) aim a member now?

    `last_recall_at` is when the member's errand was last handed back at a
    door, on the same clock as `now`, or None. `inside_instance` is whether
    its fresh snapshot reads an instance map."""
    if not is_economy(aim_kind):
        return ALLOWED
    if inside_instance:
        return Verdict(False, INSIDE_INSTANCE)
    if not dungeonstall.recall_cooling(last_recall_at, now):
        return ALLOWED
    left = dungeonstall.RECALL_COOLDOWN_SECONDS - (float(now) - float(last_recall_at))
    return Verdict(False, RECALL_COOLDOWN, left)


@dataclass(frozen=True)
class Served:
    """The errand time a member had served when it was recalled: under which
    queue entry, how many seconds, and when the recall was."""

    head_id: int
    seconds: float
    at: float


def resume_since(
    now,
    served: Served | None,
    head_id: int,
    window: float = dungeonstall.RECALL_COOLDOWN_SECONDS,
) -> float:
    """When a member's fresh errand clock is counted from.

    `now` for a member with no recall behind it. For one recalled under the
    same queue entry inside `window`, when the recalled errand began, so an
    errand taken up again goes on counting toward the stand-down."""
    now = float(now)
    if served is None or int(served.head_id) != int(head_id):
        return now
    if not 0 <= now - float(served.at) < float(window):
        return now
    return float(served.at) - max(0.0, float(served.seconds))


def recall_due(seconds, hold: float = dungeonstall.HOLD_SECONDS) -> bool:
    """Is a member this long on its errand still handed it back, or has it
    reached the bound where the run is stood down instead?"""
    return float(seconds) < float(hold)


def is_dead_row(row) -> bool:
    """Does a snapshot row (health, corpses) read dead or ghost? No row, no."""
    if not row:
        return False
    return int(row.get("health") or 0) <= 0 or int(row.get("corpses") or 0) > 0
