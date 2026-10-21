"""The level step's same-map ride (guildlevel.Choice.ride_to): a Horde member
on the Eastern Kingdoms whose best hub is Grom'gol rides the Undercity to
Grom'gol zeppelin with one `ride-to-stop` row, under the same clock and walls
as a `cross-to-map` row (guildjobs.crossing_cooling, class_walls).

Before it, no row rode that zeppelin (it never leaves map 0, and
`cross-to-map` names only a map), so such a member stood in its outgrown zone,
refused, until Kalimdor's hubs fitted.
"""

import unittest

import classquest
import guildjobs
import guildlevel
import guildroute
from test_guildlevel_open_quests import (
    EASTERN_KINGDOMS,
    RANGES,
    STRANGLETHORN,
    UNDEAD,
    WORLD,
    done_in,
    level_steps,
    member,
)

NO_ROUTE = (
    "no transport the module knows sails from this map to that map for this faction"
)
RIDE = "ride-to-stop map:0 x:-12409.2 y:146.3"


def rider(**over):
    over.setdefault("rewarded", done_in(*(z for z in RANGES if z != STRANGLETHORN)))
    return member("Rotney", guild="Bonkers", race=UNDEAD, level=40, **over)


def plan(members, recent=()):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=WORLD,
        cap=guildroute.FAR_WALK_YARDS,
        recent=recent,
    )


def ride_row(age, status="error", reason="", retry=False):
    """One `ride-to-stop` row of the level step, as recent_from_rows reads it."""
    result = ""
    if reason:
        result = '{"outcome":"refused","reason":"%s","retry":%s,"map":0}' % (
            reason,
            "true" if retry else "false",
        )
    return guildjobs.recent_from_rows(
        [
            {
                "target_name": "Rotney",
                "command": RIDE,
                "source": guildjobs.source_for(guildlevel.CROSS_ACTION, "Rotney"),
                "status": status,
                "age": age,
                "result": result,
            }
        ]
    )[0]


class TheRideToGromgol(unittest.TestCase):
    def test_the_ride_is_one_ride_to_stop_row(self):
        steps = level_steps(plan([rider()]))
        self.assertEqual(len(steps), 1)
        self.assertEqual(len(steps[0].rows), 1)
        row = steps[0].rows[0]
        self.assertEqual(row.kind, "job")
        self.assertEqual(row.command, RIDE)
        self.assertEqual(row.source, "guildjobs:level-cross:Rotney")
        self.assertIsNone(steps[0].walk)
        self.assertIn("the zeppelin from the Undercity to Grom'gol", steps[0].said)
        self.assertTrue(classquest.is_cross_row(row.command))

    def test_a_young_ride_holds_the_member_with_no_new_row(self):
        result = plan([rider()], (ride_row(5, status="claimed"),))
        self.assertEqual([s for s in result.steps if s.holder == "Rotney"], [])
        self.assertIn("Grom'gol", result.lines["Rotney"])

    def test_a_refused_ride_is_a_named_wall_on_its_map(self):
        recent = (ride_row(classquest.CROSS_COOLDOWN_MINUTES + 5, reason=NO_ROUTE),)
        self.assertEqual(
            guildjobs.class_walls("Rotney", recent), {EASTERN_KINGDOMS: NO_ROUTE}
        )
        result = plan([rider()], recent)
        self.assertEqual(level_steps(result), [])
        self.assertIn(NO_ROUTE, "; ".join(result.notes))
        later = (ride_row(classquest.CROSS_WALL_MINUTES, reason=NO_ROUTE),)
        self.assertEqual(len(level_steps(plan([rider()], later))), 1)

    def test_a_retryable_refusal_is_asked_again_sooner(self):
        full = "the realm already has as many crossings as it allows (Overseer.Cross.AtOnce)"
        young = (ride_row(3, reason=full, retry=True),)
        self.assertEqual(level_steps(plan([rider()], young)), [])
        due = (ride_row(classquest.CROSS_RETRY_MINUTES, reason=full, retry=True),)
        self.assertEqual(len(level_steps(plan([rider()], due))), 1)


if __name__ == "__main__":
    unittest.main()
