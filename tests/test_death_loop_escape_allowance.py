"""A death loop's escape has an allowance of its own per guild per pass (#2152).

WHY THIS EXISTS. Read on the dev realm on 2026-11-17: the 14:41 and 14:48 guild
jobs passes refused four loopers, whose deaths since 13:24 came to 23, with
"waits: 6 guild job steps per guild per pass". A hearth is counted against
GEAR_STEPS_PER_GUILD, the allowance gear, trainer and stood-still hearths of
every other member also use, so the loopers' escape queued behind them and
nobody took it.
"""

import unittest

import deathloop
import guildjobs
import guildlevel
import guildroute
from test_guildjobs_death_loop_home import (
    ELWYNN,
    EASTERN_KINGDOMS,
    GOLDSHIRE_INN,
    HILLSBRAD,
    QUESTS,
    fact_rows,
    master_rows,
    member,
)


def looper(i):
    return member(
        "Looper%d" % i,
        rewarded=frozenset(),
        home_map=EASTERN_KINGDOMS,
        home_x=GOLDSHIRE_INN[0],
        home_y=GOLDSHIRE_INN[1],
        home_zone=ELWYNN,
    )


def loop_of(name):
    return deathloop.Loop(
        name=name,
        zone=HILLSBRAD,
        map_id=EASTERN_KINGDOMS,
        deaths=7,
        killer="Hillsbrad Farmer",
        level=26,
        first_age=3000,
        last_age=120,
    )


def plan(members, loops):
    return guildjobs.plan(
        members,
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=guildlevel.world(QUESTS, master_rows(), fact_rows=fact_rows()),
        cap=guildroute.FAR_WALK_YARDS,
        recent=(),
        loops=loops,
    )


def hearths(result):
    return [s for s in result.steps if s.action == "hearth"]


class TheEscapeAllowance(unittest.TestCase):
    def test_a_guild_of_loopers_is_escaped_past_the_gear_allowance(self):
        count = guildjobs.GEAR_STEPS_PER_GUILD + 1
        members = [looper(i) for i in range(count)]
        loops = {m.name: loop_of(m.name) for m in members}
        self.assertEqual(len(hearths(plan(members, loops))), count)

    def test_the_escape_allowance_is_still_a_bound(self):
        count = guildjobs.ESCAPE_STEPS_PER_GUILD + 3
        members = [looper(i) for i in range(count)]
        loops = {m.name: loop_of(m.name) for m in members}
        result = plan(members, loops)
        self.assertEqual(len(hearths(result)), guildjobs.ESCAPE_STEPS_PER_GUILD)
        self.assertIn("guild job steps per guild per pass", " ".join(result.notes))

    def test_a_hearth_of_a_member_in_no_loop_keeps_the_gear_allowance(self):
        step = guildjobs.guildcorps.Step("Nobody", "hearth", 0, "x")
        counters = guildjobs._plan_counters()
        found, cap = guildjobs._allowance(step, counters, 4, looping={"Other": 1})
        self.assertIs(found, counters["gear"])
        self.assertEqual(cap, guildjobs.GEAR_STEPS_PER_GUILD)

    def test_a_loopers_hearth_counts_against_the_escape_allowance(self):
        step = guildjobs.guildcorps.Step("Looper0", "hearth", 0, "x")
        counters = guildjobs._plan_counters()
        found, cap = guildjobs._allowance(step, counters, 4, looping={"Looper0": 1})
        self.assertIs(found, counters["escape"])
        self.assertEqual(cap, guildjobs.ESCAPE_STEPS_PER_GUILD)

    def test_a_loopers_level_walk_counts_against_the_escape_allowance(self):
        step = guildjobs.guildcorps.Step("Looper0", guildlevel.ACTION, 5, "x")
        counters = guildjobs._plan_counters()
        found, _cap = guildjobs._allowance(step, counters, 4, looping={"Looper0": 1})
        self.assertIs(found, counters["escape"])


if __name__ == "__main__":
    unittest.main()
