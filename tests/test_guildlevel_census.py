"""The bridge names, once a pass, how many guild members stand in a hub zone
whose quests have run out for them (guildlevel.census, #780).

The level walk leaves a zone once fewer than MIN_OPEN quests are open there for
the member. Whether that holds across the guilds was measured by hand against
the realm database: 13 of 46 members at 20+ stood in a hub zone with fewer than
3 open quests on 2026-10-10. The census line puts that count in the pass log,
per guild, from the open quests the pass already reads.
"""

import unittest

import guildlevel
from test_guildlevel_open_quests import (
    BRIDGE,
    DUROTAR,
    HILLSBRAD,
    KALIMDOR,
    WORLD,
    done_in,
    member,
)


class TheCensus(unittest.TestCase):
    def test_a_member_in_a_dry_hub_zone_is_counted_with_its_guild(self):
        dry = member("Tugga", level=26, rewarded=done_in(HILLSBRAD))
        wet = member("Rokk", level=26, rewarded=frozenset())
        line = guildlevel.census([dry, wet], WORLD)
        self.assertIn("Cave 1 of 2", line)
        self.assertIn("Tugga 26 in Hillsbrad", line)
        self.assertNotIn("Rokk", line)
        self.assertIn("fewer than %d open quests" % guildlevel.MIN_OPEN, line)

    def test_each_guild_is_counted_on_its_own(self):
        members = [
            member("Tugga", level=26, rewarded=done_in(HILLSBRAD)),
            member("Whakk", guild="Bonkers", level=26, rewarded=frozenset()),
            member("Zork", guild="Bonkers", level=26, rewarded=done_in(HILLSBRAD)),
        ]
        line = guildlevel.census(members, WORLD)
        self.assertIn("Bonkers 1 of 2", line)
        self.assertIn("Cave 1 of 1", line)
        self.assertIn("2 of 3", line)

    def test_who_is_not_counted(self):
        roster = guildlevel.World(
            bands=WORLD.bands,
            masters=WORLD.masters,
            roster=frozenset({"Fam"}),
            quests=WORLD.quests,
        )
        members = [
            # Below 20, a family member, at the cap, rewards unread.
            member("Low", level=19, rewarded=done_in(HILLSBRAD)),
            member("Fam", level=26, rewarded=done_in(HILLSBRAD)),
            member("Cap", level=guildlevel.LEVEL_CAP, rewarded=frozenset()),
            member("Unread", level=26, rewarded=None),
            # Standing in no hub zone: counted, never dry.
            member(
                "Orc", level=26, map_id=KALIMDOR, zone_id=DUROTAR, rewarded=frozenset()
            ),
        ]
        line = guildlevel.census(members, roster)
        self.assertIn("Cave 0 of 1", line)
        self.assertIn("1 unread", line)
        for name in ("Low", "Fam", "Cap", "Orc"):
            self.assertNotIn(name, line)

    def test_nothing_is_said_while_the_quests_are_unread(self):
        unread = guildlevel.World(bands=WORLD.bands, masters=WORLD.masters)
        self.assertEqual("", guildlevel.census([member()], unread))
        self.assertEqual("", guildlevel.census([member()], None))

    def test_the_named_members_are_capped(self):
        members = [
            member("M%02d" % i, level=26, rewarded=done_in(HILLSBRAD))
            for i in range(guildlevel.CENSUS_NAMED + 3)
        ]
        line = guildlevel.census(members, WORLD)
        self.assertIn("and 3 more", line)
        self.assertNotIn("M%02d" % (guildlevel.CENSUS_NAMED + 2), line)


class TheWiring(unittest.TestCase):
    def test_the_pass_logs_the_census_off_the_level_world(self):
        body = BRIDGE[BRIDGE.index("async def _plan_guild_jobs(") :][:6000]
        self.assertIn("guildlevel.census(members, leveling)", body)


if __name__ == "__main__":
    unittest.main()
