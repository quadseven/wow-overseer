"""The town errand: the whole family parks in its capital and does its shopping.

WHY ONE ERRAND AND NOT SIX PASSES. Every town pass in this package (mail,
equip, sell, gear, bank, hand-down) aimed the leader at its own counter and
queued rows for whoever the snapshot said was near it. Each was right on its
own and together they lost: measured on the dev realm on 2026-09-27, three
rounds of fixes to the mail and vendor passes moved slots worn by almost
nothing, because the family was always walking somewhere else when a row was
written, every take came back `mailbox not in range`, and the one traveller
was handed between passes before any walk landed.

A player does it the other way round: ride to the capital, stand at the
mailbox, empty it, put on what came, sell the junk, buy what is missing, bank
the rest, hand things down, then leave. That is this module.

THE STATES, with a clear entry and exit:

    IDLE    -> GO       `should_start` gives a reason (gear in the post, or a
                        member short of slots with gold of its own). Members
                        further than a walk from a home hub hearth there.
    GO      -> GATHER   the leader is read standing at the hub mailbox.
    GATHER  -> STEPS    every member is read standing within GATHER_YARDS of
                        the hub, or the gather window runs out (the steps then
                        run for whoever is there, and say who is not).
    STEPS               STEP_ORDER, one at a time; each ends when the bridge
                        reports it done or when its own window runs out.
    STEPS   -> DONE     after the last step.
    any     -> DONE     the whole errand's ceiling, a dungeon run, or a walk
                        that never landed (GO_SECONDS).

Every transition returns a sentence, so the log reads as the errand's diary.

"STANDING" IS ALWAYS A SETTLED READING. The bridge judges every position with
`travel.settled`: two fresh snapshot reads one tick apart, within two yards of
each other. Nothing here reads a position itself.

PURE MODULE: no MySQL, no clock, no core. The caller passes `now`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

IDLE = "idle"
GO = "go"
GATHER = "gather"
STEPS = "steps"
DONE = "done"

# The order a player does it in. `tidy` is the bag tidy pass (#375), run once
# more while the family stands together.
MAIL = "mail"
EQUIP = "equip"
VENDOR = "vendor"
BANK = "bank"
HANDDOWN = "handdown"
TIDY = "tidy"
STEP_ORDER = (MAIL, EQUIP, VENDOR, BANK, HANDDOWN, TIDY)

# How long each step may take before the errand moves on without it. The mail
# step is the longest: eight takes per visit, a few seconds apart, and a
# family's post runs to dozens of letters.
STEP_SECONDS = {
    MAIL: 900.0,
    EQUIP: 120.0,
    VENDOR: 480.0,
    BANK: 300.0,
    HANDDOWN: 120.0,
    TIDY: 180.0,
}
# The walk to the capital. A family on the same continent flies or rides; one
# that has not arrived in twenty minutes is not arriving.
GO_SECONDS = 1200.0
# The wait for the rest of the family once the leader is at the mailbox.
GATHER_SECONDS = 300.0
# The whole errand, start to release. The sum of the windows above is longer on
# purpose: a slow errand is cut here rather than holding the campaign for ever.
TOTAL_SECONDS = 3600.0
# Two errands per family are at least this far apart, however the first ended.
COOLDOWN_SECONDS = 7200.0

# THE WAY THERE (wow-dev 2026-09-27). The Alliance family is bound in Ratchet,
# which has a mailbox, armorers, a weaponsmith and two bankers beside the inn,
# and it was sent to Stormwind instead: 3,223 yards from a head fighting alone
# in the Burning Steppes, with three members 11,000 yards off in Tirisfal. A
# player shops at home and hearths there. So the hub is the mailbox by the
# head's hearthstone point when there is one, unless the head already stands in
# walking range of a capital; and every member further than a walk from the hub
# uses its hearthstone at the start, which is also what brings a scattered
# family back together.
#
# A walk further than this is a journey, not a walk to a counter (the module's
# own mailbox walk caps at the same 600 yards).
WALK_YARDS = 600.0
# How far the mailbox may stand from the hearthstone point and still be the
# town it is bound in.
BIND_MAILBOX_YARDS = 60.0
# How long after the hearth rows the leader is left alone: a walk written
# during the ten second cast moves him and interrupts it.
HEARTH_SECONDS = 45.0

# How close counts as at the hub. The core opens a mailbox from about ten
# yards; the leader lands within a few yards of a ground aim.
HUB_YARDS = 10.0
GATHER_YARDS = 12.0

# The entry test: gear in the post, or a member this short of slots with at
# least this much of its own gold.
START_EMPTY_SLOTS = 3
START_PURSE = 20000


@dataclass(frozen=True)
class State:
    """One family's errand. `step` indexes STEP_ORDER while in STEPS."""

    phase: str = IDLE
    started: float = 0.0
    phase_since: float = 0.0
    step: int = 0
    hub: dict = field(default_factory=dict)
    ended: float = 0.0
    why: str = ""
    hearth_until: float = 0.0

    @property
    def active(self) -> bool:
        return self.phase in (GO, GATHER, STEPS)

    @property
    def current_step(self) -> str:
        if self.phase != STEPS or self.step >= len(STEP_ORDER):
            return ""
        return STEP_ORDER[self.step]


def should_start(
    state: State, *, now: float, in_run: bool, mail_gear: dict, facts: dict
) -> str:
    """Why this family should go to town now, or '' when it should not.

    `mail_gear` is `mailrun.gear_waiting` (name -> letters of wearable gear in
    the post). `facts` is the gear facts per member (`equipped` slot names and
    `purse`). A family inside a dungeon run, on an errand already, or inside
    the cooldown since its last one does not go.
    """
    if state.active or in_run:
        return ""
    if state.ended and now - state.ended < COOLDOWN_SECONDS:
        return ""
    waiting = sorted(n for n, count in (mail_gear or {}).items() if count > 0)
    if waiting:
        return "bought gear waits in the mailbox for %s" % ", ".join(waiting)
    short = []
    for name, fact in sorted((facts or {}).items()):
        worn = [s for s in fact.get("equipped", {}) if s not in ("shirt", "tabard")]
        empty = 17 - len(worn)
        if empty >= START_EMPTY_SLOTS and int(fact.get("purse") or 0) >= START_PURSE:
            short.append("%s (%d empty)" % (name, empty))
    if short:
        return "%s short of gear with gold to spend" % ", ".join(short)
    return ""


def start(now: float, hub: dict, why: str, hearthed: bool = False) -> State:
    """A new errand, walking to `hub` (a mailbox spawn row). `hearthed` is
    whether hearth rows were written for it this tick."""
    return State(
        phase=GO,
        started=now,
        phase_since=now,
        hub=dict(hub),
        why=why,
        hearth_until=now + HEARTH_SECONDS if hearthed else 0.0,
    )


def choose_hub(bind_hub: dict, capital_hub: dict, leader_at) -> dict:
    """The errand's hub: the head's home town, or a capital he is already in.

    `bind_hub` is the mailbox by the head's hearthstone point ({} when none is
    within BIND_MAILBOX_YARDS of it), `capital_hub` the mailbox by the nearest
    auctioneer of the family's own house on the head's map ({} when none),
    `leader_at` the head's snapshot row. A capital wins only when the head is
    already within a walk of it; otherwise home, which a hearthstone reaches
    from anywhere. With no home mailbox, the capital as before.
    """
    if capital_hub and in_range(capital_hub, leader_at, WALK_YARDS):
        return dict(capital_hub)
    return dict(bind_hub or capital_hub or {})


def to_hearth(hub: dict, positions: dict, names, hearthed=frozenset()) -> list:
    """The members who use their hearthstone to reach `hub`, sorted.

    A member read on another map or further than WALK_YARDS from it. Only for
    a hub by the hearthstone point (`hub["bind"]`); a member with no fresh
    reading (offline) and one that hearthed inside the stone's cooldown
    (`hearthed`) are left to the walk.
    """
    if not hub or not hub.get("bind"):
        return []
    out = []
    for name in sorted(names):
        at = (positions or {}).get(name)
        if not at or name in hearthed:
            continue
        if not in_range(hub, at, WALK_YARDS):
            out.append(name)
    return out


def hearthing(state: State, now: float) -> State:
    """The errand after hearth rows were written at `now`: the leader is left
    alone for the cast. A member still far from home while the family walks
    or gathers hearths then (the start's cast refused as "moving", or a
    member that was offline), which is how a straggler rejoins."""
    return replace(state, hearth_until=now + HEARTH_SECONDS)


def aim_now(state: State, now: float) -> bool:
    """Whether the leader may be aimed: not inside a hearth's cast window."""
    return now >= state.hearth_until


def end(state: State, now: float, why: str) -> tuple:
    """Release the family, with the reason."""
    return replace(state, phase=DONE, ended=now, why=why), "released: %s" % why


def advance(
    state: State,
    now: float,
    *,
    in_run: bool = False,
    leader_at_hub: bool = False,
    gathered: bool = False,
    step_done: bool = False,
) -> tuple:
    """The next state and one sentence about what changed ('' when nothing).

    The bridge measures; this decides. `leader_at_hub` and `gathered` are
    settled readings; `step_done` is the bridge's read-back for the current
    step.
    """
    if not state.active:
        return state, ""
    if in_run:
        return end(state, now, "a dungeon run started")
    if now - state.started >= TOTAL_SECONDS:
        return end(state, now, "the errand's %ds ceiling" % int(TOTAL_SECONDS))
    held = now - state.phase_since
    if state.phase == GO:
        if leader_at_hub:
            return (
                replace(state, phase=GATHER, phase_since=now),
                "the leader stands at the mailbox; the family gathers",
            )
        if held >= GO_SECONDS:
            return end(
                state,
                now,
                "the walk to the capital did not land in %ds" % int(GO_SECONDS),
            )
        return state, ""
    if state.phase == GATHER:
        if gathered:
            return (
                replace(state, phase=STEPS, phase_since=now, step=0),
                "the whole family stands at the mailbox; the errands begin",
            )
        if held >= GATHER_SECONDS:
            return (
                replace(state, phase=STEPS, phase_since=now, step=0),
                "not everybody arrived in %ds; the errands begin for whoever "
                "is here" % int(GATHER_SECONDS),
            )
        return state, ""
    step = state.current_step
    timed_out = held >= STEP_SECONDS.get(step, 0.0)
    if not (step_done or timed_out):
        return state, ""
    said = "%s %s" % (step, "done" if step_done else "ran out of time")
    nxt = state.step + 1
    if nxt >= len(STEP_ORDER):
        new, line = end(state, now, "every step ran")
        return new, "%s; %s" % (said, line)
    return (
        replace(state, step=nxt, phase_since=now),
        "%s; next: %s" % (said, STEP_ORDER[nxt]),
    )


def in_range(spot, standing, yards: float) -> bool:
    """Is a settled reading on the spot's map within `yards` of it, planar."""
    if not spot or not standing:
        return False
    try:
        if int(spot.get("map_id")) != int(standing.get("map_id")):
            return False
        dx = float(spot.get("x")) - float(standing.get("pos_x"))
        dy = float(spot.get("y")) - float(standing.get("pos_y"))
    except (TypeError, ValueError):
        return False
    return dx * dx + dy * dy <= float(yards) ** 2
