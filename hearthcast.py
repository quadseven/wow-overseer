"""Who casts its hearthstone to a bind hub, who walks, and who is left (#2333).

WHY THIS EXISTS. A bag-room errand keeps a far hub by the head's hearthstone
point when "the head's stone will be cast there" (#2329), so the family
arrives in one cast and nobody walks across a continent to a vendor. That
"will be cast" was an inference from two facts only: where the stone is bound
and whether the bridge wrote a hearth row in the last hour. Nothing asked
whether the head carries a stone at all, whether a cast the bridge did not
write (a player's) has the stone on cooldown, or whether the head is alive.
mod-overseer refuses each of those ("character carries no hearthstone",
"hearthstone is on cooldown", "character is dead"), the cast never happens,
the hub was kept anyway, and the family walks the long way.

The second gap is the member the stone does not help. A member bound
somewhere else stays where it stands when the others cast. Next to the hub
that is a short walk. Far from it on the hub's map it is the long walk the
kept hub was meant to remove, and on another map it cannot follow at all.

WHAT IS DECIDED HERE.

  `decide` answers for one member: CAST (its stone lands by the hub and it
  can use it now), WALK (it already stands within a walk of the hub), or HOLD
  with the reason as a word. A HOLD for NOT_IN_WORLD is a member with no
  fresh reading, left out as the errand has always left it. Every other HOLD
  is a member the hub would leave behind or send on a long walk, and it
  `blocks` the hub.

  `keeps_hub` answers for the family: the hub is kept only when the head
  itself casts and no member blocks. Anything else drops the hub, which is
  what the errand did before #2329: it aims at a vendor near the head.

  A FACT THAT WAS NOT READ IS NEVER A CAST. A stone, a cooldown or a pulse
  the bridge could not read is None here and reads as "cannot cast", so a
  failed read gives the old behaviour and never a kept hub.

  A HEAD INSIDE AN INSTANCE STILL CASTS. The hearthstone works from inside a
  dungeon and mod-overseer's hearth has no refusal for it, so a head on an
  instance map with a stone bound by the hub is a CAST like any other.

PURE MODULE: facts in, decisions out. The bridge reads (hearthcast_data) and
chooses the aim (townerrand.choose_aim).
"""

from __future__ import annotations

from dataclasses import dataclass

import townerrand

# What a member does about the hub.
CAST = "cast"
WALK = "walk"
HOLD = "hold"

# Why, as words a test or a log line can read.
STONE_LANDS = "stone_lands_by_hub"
WITHIN_A_WALK = "within_a_walk"
NOT_IN_WORLD = "not_in_world"
NO_BIND_HUB = "no_bind_hub"
DEAD = "dead"
PULSE_UNREAD = "pulse_unread"
BOUND_ELSEWHERE = "bound_elsewhere"
NO_STONE = "no_stone"
STONE_UNREAD = "stone_unread"
ON_COOLDOWN = "stone_on_cooldown"
COOLDOWN_UNREAD = "cooldown_unread"

# A fact the bridge could not read. The failed read says so itself, once
# (hearthcast_data), so a verdict that rests on one adds no line of its own.
UNREAD = frozenset({PULSE_UNREAD, STONE_UNREAD, COOLDOWN_UNREAD})

# The same reasons as the end of a sentence about the member.
SAID = {
    STONE_LANDS: "casts its hearthstone to the hub",
    WITHIN_A_WALK: "stands within a walk of the hub",
    NOT_IN_WORLD: "has no fresh reading",
    NO_BIND_HUB: "has no hearthstone hub to cast to",
    DEAD: "is dead",
    PULSE_UNREAD: "could not be read alive",
    BOUND_ELSEWHERE: "is bound somewhere else",
    NO_STONE: "carries no hearthstone",
    STONE_UNREAD: "has bags that could not be read for a hearthstone",
    ON_COOLDOWN: "has its hearthstone on cooldown",
    COOLDOWN_UNREAD: "has a hearthstone cooldown that could not be read",
}


@dataclass(frozen=True)
class Member:
    """What the bridge read about one member. None is "not read"."""

    name: str
    at: dict | None = None  # its fresh snapshot row: map_id, pos_x, pos_y
    bind: object = None  # where its stone lands: a point with map, x, y
    stone: bool | None = None  # it carries a hearthstone
    cooldown: float | None = None  # seconds its stone is still on cooldown
    alive: bool | None = None


@dataclass(frozen=True)
class Decision:
    name: str
    act: str
    reason: str
    # Planar yards from the member to the hub; None on another map or unread.
    yards: float | None = None

    @property
    def blocks(self) -> bool:
        """The hub would leave this member behind or on a long walk."""
        return self.act == HOLD and self.reason != NOT_IN_WORLD


@dataclass(frozen=True)
class Verdict:
    """The family's answer. `who` and `reason` name the member that dropped
    the hub; both are empty when it is kept and when there is nothing to say
    (no bind hub, or the head already stands within a walk of it).
    `said` is also empty when the reason is a fact that was not read."""

    keep: bool
    who: str = ""
    reason: str = ""
    decisions: tuple = ()

    @property
    def said(self) -> str:
        """One sentence for the log, or "" when there is nothing to say."""
        if not self.who or self.reason in UNREAD:
            return ""
        return "%s %s" % (self.who, SAID.get(self.reason, self.reason))


def _alive_reason(member: Member) -> str:
    if member.alive is None:
        return PULSE_UNREAD
    return "" if member.alive else DEAD


def _stone_reason(member: Member) -> str:
    if member.stone is None:
        return STONE_UNREAD
    return "" if member.stone else NO_STONE


def _cooldown_reason(member: Member) -> str:
    if member.cooldown is None:
        return COOLDOWN_UNREAD
    return ON_COOLDOWN if member.cooldown > 0 else ""


def cannot_cast(hub: dict, member: Member) -> str:
    """Why this member's stone does not take it to `hub` now, or ""."""
    if member.alive is False:
        return DEAD
    if not townerrand._bound_at(hub, member.bind):
        return BOUND_ELSEWHERE
    return _stone_reason(member) or _cooldown_reason(member) or _alive_reason(member)


def _yards(hub: dict, at: dict) -> float | None:
    far = townerrand._planar(
        hub, {"map_id": at.get("map_id"), "x": at.get("pos_x"), "y": at.get("pos_y")}
    )
    return None if far == float("inf") else far


def decide(hub: dict, member: Member) -> Decision:
    """What one member does about a hub by a hearthstone point."""
    if not member.at:
        return Decision(member.name, HOLD, NOT_IN_WORLD)
    if not hub or not hub.get("bind"):
        return Decision(member.name, HOLD, NO_BIND_HUB)
    yards = _yards(hub, member.at)
    if townerrand.in_range(hub, member.at, townerrand.WALK_YARDS):
        return Decision(member.name, WALK, WITHIN_A_WALK, yards)
    reason = cannot_cast(hub, member)
    if reason:
        return Decision(member.name, HOLD, reason, yards)
    return Decision(member.name, CAST, STONE_LANDS, yards)


def plan(hub: dict, members) -> tuple:
    """Every member's decision, sorted by name."""
    return tuple(decide(hub, m) for m in sorted(members, key=lambda m: m.name))


def keeps_hub(hub: dict, leader: str, members) -> Verdict:
    """Does the family reach `hub` by its stones, so it stays the aim?

    Only when the head casts and nobody blocks. The head's own reason is
    named before another member's.
    """
    decisions = plan(hub, members)
    head = next((d for d in decisions if d.name == leader), None)
    if head is None or head.reason in (NOT_IN_WORLD, NO_BIND_HUB):
        return Verdict(False, decisions=decisions)
    if head.act == WALK:
        return Verdict(False, decisions=decisions)
    if head.act != CAST:
        return Verdict(False, head.name, head.reason, decisions)
    for d in decisions:
        if d.blocks:
            return Verdict(False, d.name, d.reason, decisions)
    return Verdict(True, decisions=decisions)


def members(names, positions, binds, hearthed, facts) -> list:
    """The Member of every name, from the bridge's reads.

    `positions`, `binds` and `hearthed` are the errand's own reads
    (bridge._fetch_positions and bridge._movement_reads). `facts` is
    hearthcast_data.Facts, or None when it was not read at all. A member the
    bridge sent home inside the stone's cooldown (`hearthed`) is on cooldown
    whatever the cooldown table says: that table is written on the save timer
    and can be minutes behind a cast.
    """
    stones = getattr(facts, "stones", None)
    cooldowns = getattr(facts, "cooldowns", None)
    alive = getattr(facts, "alive", None)
    out = []
    for name in sorted(names or ()):
        cooldown = None if cooldowns is None else float(cooldowns.get(name, 0.0))
        if name in (hearthed or ()):
            cooldown = max(cooldown or 0.0, 1.0)
        out.append(
            Member(
                name=name,
                at=(positions or {}).get(name),
                bind=(binds or {}).get(name),
                stone=None if stones is None else name in stones,
                cooldown=cooldown,
                alive=None if alive is None else alive.get(name),
            )
        )
    return out
