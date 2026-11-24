"""Whether a leader holding a column errand may leave it by flight (#2541).

On 2026-11-14 on the dev realm a family leader hearthed to the capital with
a town errand standing in `travel_npc` - a mailbox aim, `at:` form, 35 yards
away at 22:20 - and a minute later was flying away from it, in steps, until
he stood in the Eastern Plaguelands about 12,000 yards from the goal. The
followers set off after him on foot and some died on the way.

THE CAUSE STAYED UNPROVEN, AND THIS FILE SAYS WHY PLAINLY. The column held
the mailbox aim all through, so no bridge aim sent him east; the only module
line that names a flight in that window is a REFUSAL to fly at 22:35, when
the module started walking him back. The candidates were the playerbot AI's
own `TravelFlight` state (the leader keeps the `new rpg` strategy), the
module's own flight leg, or the quest drive - and no log line anywhere
names which bot started a flight, let alone which of the three started it.
A cause cannot be quoted out of a log that never wrote it.

SO THIS IS THE DECISION THE NEXT OCCURRENCE IS JUDGED BY, IN PURE FORM. The
compiled module is a separate repository and its own change; what this repo
owns - the same split `flightlearn` already makes - is the rule, stated once
and pinned by tests, that a caller on either side applies:

  * A flight started by a leader holding a column errand produces ONE log
    line naming who started it (the module leg, the upstream rpg state, or
    the quest drive), the node, and the yards from the errand goal at
    takeoff. `assess` builds that line; it does not write it.
  * A flight whose destination is FARTHER from the goal than takeoff was -
    or on another map entirely - is refused. That one rule is the whole of
    the 35-yard case: no flight away from a standing errand is a shortcut,
    it is the errand being abandoned.
  * While an errand stands, the upstream rpg state is gated on the column:
    `rpg_flight_gated` says `new rpg` may not start `TravelFlight` on its
    own say-so for that leader.

ONLY A GROUND (`at:`) ERRAND CAN BE JUDGED HERE. A role keyword names no
coordinate, so "yards from the goal" is a number nobody on this side holds,
and `assess` answers None for it rather than inventing one - the same
refusal to fabricate a reading the rest of this package makes. Positions
are planar, like every other reach question here: a flight is judged across
the floor of one map, and a destination on a different map is refused
outright rather than measured.
"""

from __future__ import annotations

from dataclasses import dataclass

import travel

# Who can start a flight, spelled as the words the log line uses. A starter
# outside this table is a caller error, not a fourth candidate: naming it
# would be guessing at the very attribution this file exists to make exact.
STARTERS = {
    "module": "module leg",
    "rpg": "upstream rpg state",
    "quest": "quest drive",
}


@dataclass(frozen=True)
class FlightCheck:
    """One flight, judged: the log line, and whether it may go.

    `refused` is the verdict; `reason` is a whole sentence saying why, for
    the same log line or the caller's own. The two yardages ride along so a
    caller never has to recompute the numbers the line quotes.
    """

    log_line: str = ""
    refused: bool = False
    reason: str = ""
    yards_from_goal: float = 0.0
    destination_yards_from_goal: float = 0.0


def _goal_of(errand):
    """The (map_id, x, y) a ground errand names, or None.

    The authority on the `at:` spelling is the column's own form, written by
    `travel.ground_aim` on this side and by the module on its side, so this
    reads exactly that shape and nothing looser.
    """
    if not travel.is_ground_aim(errand):
        return None
    try:
        head, coords = str(errand)[len(travel.GROUND_AIM_PREFIX) :].split(":", 1)
        x, y, _z = (float(part) for part in coords.split(","))
        return int(head), x, y
    except (TypeError, ValueError):
        return None


def _yards(point, goal) -> float:
    return (
        (float(point["x"]) - goal[1]) ** 2 + (float(point["y"]) - goal[2]) ** 2
    ) ** 0.5


def rpg_flight_gated(errand) -> bool:
    """Whether `new rpg`'s own TravelFlight is gated for this leader.

    Any standing column errand gates it - a keyword errand as much as a
    ground one - because the gate is about WHO decides: while the column
    holds an errand, a flight is the errand owner's call, judged by
    `assess` where its goal is known, and never the rpg state's alone.
    """
    return bool(errand)


def assess(*, leader, errand, starter, node, takeoff, destination):
    """Judge one flight by a leader holding `errand`, or None if unjudgeable.

    `takeoff` and `destination` are {"map_id", "x", "y"} rows - the
    leader's position at takeoff and the flight node's own position.
    Returns None when no errand stands, or when the errand names no ground
    goal whose distance could be measured. Raises ValueError for a starter
    outside `STARTERS`, because an unnamed starter is the unproven-writer
    failure this ticket exists to end.
    """
    if starter not in STARTERS:
        raise ValueError("unknown flight starter: %r" % (starter,))
    goal = _goal_of(errand)
    if goal is None:
        return None
    try:
        yards = _yards(takeoff, goal)
        same_map = int(destination["map_id"]) == goal[0]
        dest_yards = _yards(destination, goal) if same_map else float("inf")
    except (TypeError, ValueError, KeyError):
        return None
    if not same_map:
        refused = True
        reason = (
            "the flight lands on map %s and the errand goal stands on map %d, "
            "so it leaves the errand behind entirely"
            % (destination.get("map_id"), goal[0])
        )
    elif dest_yards > yards:
        refused = True
        reason = (
            "the flight lands %d yards from the errand goal, farther from the "
            "errand goal than the %d yards at takeoff, so the errand would be "
            "abandoned rather than served" % (round(dest_yards), round(yards))
        )
    else:
        refused = False
        reason = "the flight lands nearer the errand goal than takeoff"
    line = (
        "flight guard: leader '%s' holding errand '%s' started a flight by "
        "%s to node %s, %d yards from the errand goal at takeoff; %s: %s"
        % (
            leader,
            errand,
            STARTERS[starter],
            node,
            round(yards),
            "refused" if refused else "allowed",
            reason,
        )
    )
    return FlightCheck(
        log_line=line,
        refused=refused,
        reason=reason,
        yards_from_goal=yards,
        destination_yards_from_goal=dest_yards,
    )
