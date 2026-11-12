"""A death looper is offered a group-up with a guildmate in reach (#2277).

WHY THIS EXISTS. The death-loop pool never drains: the escape step works
per member, and a looper who escapes alone returns to the same content at
the same strength and loops again. The durable exit is help. The planning
pass already reads every member (guildjobs.Member carries guild, level,
online, alive, map and position), so the mates read needs no new bridge
read: it selects, from the members the pass already holds, the guildmates
who could group up with the looper, and the escape's no-step branch names
the offer, or the one reason no mate is in reach, beside the escape's own
logged reason.
"""

import unittest

import deathloop
import guildjobs
import guildroute
from test_guildlevel_open_quests import HILLSBRAD, member

CAP = guildroute.FAR_WALK_YARDS
NAME = "Looper"


def loop_of(name=NAME, level=26):
    return deathloop.Loop(
        name=name,
        zone=HILLSBRAD,
        map_id=0,
        deaths=7,
        killer="Hillsbrad Farmer",
        level=level,
        first_age=3000,
        last_age=120,
    )


class LoopMates(unittest.TestCase):
    def test_selects_an_online_guildmate_within_the_level_band(self):
        m = member(NAME)
        mate = member("Helper", level=29)
        self.assertEqual(guildjobs.loop_mates(m, [m, mate]), [mate])

    def test_skips_offline_dead_other_guild_and_out_of_band(self):
        m = member(NAME)
        skipped = [
            member("Off", online=False),
            member("Dead", alive=False),
            member("Other", guild="Bonkers"),
            member("Far", level=40),
            member("Busy", in_combat=True),
        ]
        self.assertEqual(guildjobs.loop_mates(m, skipped), [])

    def test_skips_a_mate_on_another_map(self):
        m = member(NAME)
        other_map = member("Elsewhere", map_id=1)
        self.assertEqual(guildjobs.loop_mates(m, [other_map]), [])

    def test_skips_a_mate_too_far_away_on_the_same_map(self):
        m = member(NAME)
        distant = member("Distant", x=m.x + 100000.0)
        self.assertEqual(guildjobs.loop_mates(m, [distant]), [])

    def test_skips_a_mate_whose_position_is_unknown(self):
        m = member(NAME)
        unknown = member("Unknown", x=None, y=None)
        self.assertEqual(guildjobs.loop_mates(m, [unknown]), [])

    def test_no_escape_names_no_mate_when_the_only_mate_is_out_of_reach(self):
        m = member(NAME, in_combat=True)
        distant = member("Distant", level=28, x=m.x + 100000.0)
        found = guildjobs.death_loop_first(m, loop_of(), None, (), CAP, mates=[distant])
        self.assertIsNone(found[0])
        self.assertIn("no guildmate in reach", found[2])
        self.assertNotIn("offered a group-up with Distant", found[2])

    def test_same_zone_first_then_closest_level(self):
        m = member(NAME)
        far_zone = member("Farzone", level=26, zone_id=130)
        near_far_level = member("Nearfar", level=30)
        near_close = member("Nearclose", level=27)
        got = guildjobs.loop_mates(m, [far_zone, near_far_level, near_close])
        self.assertEqual(got, [near_close, near_far_level, far_zone])


class TheHelpOfferLine(unittest.TestCase):
    def test_no_escape_names_the_group_up_offer(self):
        m = member(NAME, in_combat=True)
        mate = member("Helper", level=28)
        found = guildjobs.death_loop_first(m, loop_of(), None, (), CAP, mates=[mate])
        self.assertIsNone(found[0])
        self.assertIn("in combat", found[2])
        self.assertIn("offered a group-up with Helper", found[2])

    def test_no_escape_and_no_mate_names_the_one_reason(self):
        m = member(NAME, in_combat=True)
        found = guildjobs.death_loop_first(m, loop_of(), None, (), CAP, mates=[])
        self.assertIsNone(found[0])
        self.assertIn("no guildmate in reach", found[2])

    def test_the_offer_reaches_the_plan_notes(self):
        m = member(NAME, in_combat=True)
        mate = member("Helper", level=28)
        result = guildjobs.plan(
            [m, mate],
            masters={"Cave": "Grug", "Bonkers": "Zug"},
            leveling=None,
            cap=CAP,
            loops={NAME: loop_of()},
        )
        named = [n for n in result.notes if "offered a group-up with Helper" in n]
        self.assertEqual(len(named), 1)


if __name__ == "__main__":
    unittest.main()
