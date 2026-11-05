"""A roster member keeps to its family's campaign over the loop escape (#1873).

WHY THIS EXISTS. The death loop's escape (#1620) lets the guild pass walk a
roster family member out of the zone it keeps dying in, the one exception to
level_step's roster refusal. The pre-ship review of the bridge ship found the
exception read no campaign state: a roster member whose family holds a
dungeon campaign could be walked to a quest hub far from the dungeon
entrance the queue coordinator stages the family at. With a campaign held,
the roster refusal stands again and levelroute keeps the member, as it does
for every roster member outside a death loop. Without one, the escape walk
is unchanged.
"""

import unittest

import guildjobs
import guildroute
from test_guildjobs_death_loop import (
    NAME,
    hearth_cooling,
    loop_of,
    plain_world,
    roster_world,
)
from test_guildlevel_open_quests import level_steps, member


def plan(w, campaign=""):
    return guildjobs.plan(
        [member(NAME, rewarded=frozenset())],
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=w,
        cap=guildroute.FAR_WALK_YARDS,
        recent=hearth_cooling(),
        loops={NAME: loop_of()},
        campaign=campaign,
    )


class TheCampaignHoldsTheRoster(unittest.TestCase):
    def test_a_roster_member_in_its_loop_zone_with_a_campaign_gets_no_walk(self):
        self.assertEqual(level_steps(plan(roster_world(NAME), campaign="sm")), [])

    def test_the_same_member_without_a_campaign_still_walks_out(self):
        self.assertEqual(len(level_steps(plan(roster_world(NAME)))), 1)

    def test_a_member_off_the_roster_walks_out_through_a_campaign(self):
        # The campaign is the roster's: a member off the family roster is
        # not one of the run's party, so its escape walk stands.
        self.assertEqual(len(level_steps(plan(plain_world(), campaign="sm"))), 1)

    def test_level_step_alone_refuses_the_roster_member(self):
        m = member(NAME, rewarded=frozenset())
        step, doing, _note = guildjobs.level_step(
            m,
            roster_world(NAME),
            hearth_cooling(),
            guildroute.FAR_WALK_YARDS,
            loop_of(),
            campaign="sm",
        )
        self.assertIsNone(step)
        self.assertEqual(doing, "")


if __name__ == "__main__":
    unittest.main()
