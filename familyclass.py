"""A family member's class quest, between two runs of its campaign (#2336).

WHY THIS EXISTS. guildjobs plans a class step for maintenance, summoner and
raider members only, and class_step said "never at a roster family member
(levelroute walks those)". levelroute carries class quests as level-band hints
and has no paladin entry, so no family paladin could take the Redemption chain
of #2297, and a family whose only resurrection source is one priest lost a
Blackrock Depths run at 9 of 18 bosses when she died.

THE RULE STAYS: a class quest is owed before any dungeon. What changes is that
a family member may take a CLASS-ONLY step in the gap between two runs, where
nothing else is asked of it. The step is bounded so the gap is never stretched
by more than about WALK_MINUTES, and so a family is never walked off mid-run:

  idle family   no live run of its leader (`overseer_dungeon_run`, any state but
                'ended'), and no member standing in an instance. A run being
                staged or cleared is a live run.
  its moves     TAKE and TURN_IN only. A hunt or an item use can hold a member
                for hours, so they stay with the level route.
  the walk      the giver on the member's own map within WALK_YARDS (about
                WALK_MINUTES on foot with a detour), or the member already in
                reach of it. Another map is skipped and named, never crossed;
                a hearth route for a far giver is a follow-up.
  the pace      one class WALK per member per WALK_GAP_MINUTES. A step with no
                walk (the tome already in the bags) is held only by the usual
                class cooldown.
  a follower    a member grouped under its leader cannot walk (the module
                refuses a follower's walk, followhold.py), so it is planned
                only a step it can make where it stands.

  busy          a member on a town errand (its bag-room walk, its slot, its aim) is
                planned nothing (`errand_free`): the claims table does not carry
                the errand, so two walks fought over one character (#2338).
  the level     the giver's ground is read for its highest creature level
                (`danger_hold`); a member DANGER_MARGIN or more levels below it,
                or a giver whose ground is not read, does not walk. A giver in
                reach is taken where the member stands.
  no boat       an island crossing is not a gap step (`CROSSING_HOLD`).

Danger is the class step's own: a dead member, the walk backoff and the
deadly-way hold apply to a family member as to any other.

PURE: facts in, a sentence (or "") out. The bridge reads the rows.
"""

from __future__ import annotations

import math
import os

import classquest

ENV_SWITCH = "FAMILY_CLASS_STEPS"

# About twenty minutes on foot at a run of 7 yards a second, with a third of
# the way lost to bends: the longest a walk may stretch the gap between runs.
WALK_MINUTES = 20
WALK_YARDS = 5000.0
# One class walk per member per two hours: the chain is four short steps.
WALK_GAP_MINUTES = 120
# Within this of the giver a member makes the step where it stands.
REACH_YARDS = 40.0

NOT_A_GAP_STEP = (
    "only a take or a hand-in is planned between runs: not a hunt, an item use "
    "or a crossing"
)
# A giver whose ground holds a creature this many levels over the member is
# not walked to alone (levelroute.DANGER_GAP is the same five).
DANGER_MARGIN = 5
CROSSING_HOLD = (
    "%s's giver is across the water: a boat ride is not planned between runs"
)
GAP_MOVES = (classquest.TAKE, classquest.TURN_IN)


def enabled(environ=None) -> bool:
    """On unless FAMILY_CLASS_STEPS says off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


def idle_names(roster, live_leaders=(), inside=()) -> set:
    """The roster names whose family is between runs: no live run of its leader
    (the family key is the leader's name) and none of its members inside an
    instance. `roster` rows carry `name` and `family`."""
    families: dict = {}
    for row in roster or ():
        name = str(row.get("name") or "")
        if name:
            families.setdefault(str(row.get("family") or ""), []).append(name)
    live, within = set(live_leaders or ()), set(inside or ())
    out = set()
    for family, names in families.items():
        if family in live or any(n in live for n in names if n == family):
            continue
        if within.intersection(names):
            continue
        out.update(names)
    return out


def not_idle_holds(roster, live_leaders=(), inside=(), errands=()) -> dict:
    """name -> why a family cannot take its between-run class step this pass."""
    families: dict = {}
    for row in roster or ():
        name = str(row.get("name") or "")
        if name:
            families.setdefault(str(row.get("family") or ""), []).append(name)
    live, within, on_errand = (
        set(live_leaders or ()),
        set(inside or ()),
        set(errands or ()),
    )
    holds = {}
    for leader, names in families.items():
        if leader in live:
            reason = "its family has an active dungeon run"
        elif within.intersection(names):
            reason = "a family member is still inside an instance"
        else:
            continue
        holds.update({name: reason for name in names})
    holds.update({name: "the member is on a town errand" for name in on_errand})
    return holds


def _yards(m, spot) -> float:
    return math.hypot(float(m.x) - float(spot.x), float(m.y) - float(spot.y))


def holds(m, move, recent) -> str:
    """Why this family member is planned no class step now, "" when it may."""
    if move.kind not in GAP_MOVES:
        return NOT_A_GAP_STEP
    if move.spot is None:
        # An item-started take: nothing to walk to.
        return ""
    return _walk_hold(m, move.spot, recent)


def _walk_hold(m, spot, recent) -> str:
    """Why the walk to `spot` is held, "" when it may be made. Ground that is
    not read is not near ground: the walk is held until the member's place is."""
    if m.map_id is None or m.x is None or m.y is None:
        return (
            "%s's place is not read, so its walk to the giver is not bounded" % m.name
        )
    if int(m.map_id) != int(spot.map_id):
        return "%s's giver is on another map: too far for the gap between runs" % m.name
    yards = _yards(m, spot)
    if yards <= REACH_YARDS:
        return ""
    if getattr(m, "follows", False):
        return (
            "%s follows its leader and cannot walk to its giver; a follower makes "
            "only the class step in reach" % m.name
        )
    if yards > WALK_YARDS:
        return "%s's giver is %d yards away: too far for the gap between runs" % (
            m.name,
            int(yards),
        )
    return _gap_hold(m, recent)


def _gap_hold(m, recent) -> str:
    """The hold of one class walk per WALK_GAP_MINUTES, "" when none is held."""
    for r in recent or ():
        if (
            r.name == m.name
            and r.action == classquest.ACTION
            and r.walk
            and int(r.age_minutes) < WALK_GAP_MINUTES
        ):
            return "%s made a class walk %d minutes ago: one per %d minutes" % (
                m.name,
                int(r.age_minutes),
                WALK_GAP_MINUTES,
            )
    return ""


def errand_free(members, errand_names) -> list:
    """The family members that are not on a town errand. `errand_names` is every
    name of a family whose errand is active: a member of it is held for the
    errand's walks, so a lone class walk would fight them (#2338)."""
    on_errand = set(errand_names or ())
    return [m for m in members or () if m.name not in on_errand]


def danger_hold(m, move, top) -> str:
    """Why the lone walk to the giver is held for the ground's danger, "" when
    it may be made. `top` is the highest creature level read near the giver, or
    None when it was not read: ground not read is not safe ground."""
    if move.spot is None or _yards(m, move.spot) <= REACH_YARDS:
        return ""
    if top is None:
        return "%s's giver's ground is not read, so its walk is not known safe" % m.name
    if int(top) >= int(m.level) + DANGER_MARGIN:
        return (
            "%s is level %d and its giver's ground holds level %d creatures: "
            "no lone walk there" % (m.name, int(m.level), int(top))
        )
    return ""
