"""An Alliance member is not level-walked through the Barrens (ticket 2624).

Read on the dev realm on 2026-11-15: Horde guards killed Cave's Draenei 72
times in 24 hours (Orgrimmar Grunt in the Barrens, Splintertree Guard in
Ashenvale, Bluffwatcher at Thunder Bluff), 48 of them one shaman, who stood in
Dustwallow Marsh, was bound at Astranaar and levelled by flight-master walks.
Dustwallow Marsh is reached from the rest of the Alliance's Kalimdor only
across the Barrens, as the Horde's Stranglethorn Vale is reached across
Duskwood (guildlevel.POCKETS). The member leaves it by the Theramore boat, and
the road across the Barrens is never the way a level walk is written.
"""

import unittest

import guildlevel
import levelroute
from test_guildlevel import (
    DARKSHORE,
    EASTERN_KINGDOMS,
    HUMAN,
    KALIMDOR,
    NIGHT_ELF,
    ORC,
    QUESTS,
    master_rows,
    quests_in,
)

DUSTWALLOW = 15
ASHENVALE = 331
ALLIANCE = levelroute.ALLIANCE
HORDE = levelroute.HORDE

# The shared fixture's zones, with the two Kalimdor zones this module needs.
WORLD = QUESTS + tuple(
    quests_in(DUSTWALLOW, 36, 46, 9000) + quests_in(ASHENVALE, 20, 30, 9500)
)


def bands(team=ALLIANCE):
    return levelroute.bands(WORLD, team)


class TheGround(unittest.TestCase):
    def test_dustwallow_is_a_pocket_of_the_alliance_past_the_barrens(self):
        self.assertNotEqual(
            guildlevel.ground_of(ALLIANCE, KALIMDOR, DUSTWALLOW),
            guildlevel.MAIN_GROUND,
        )

    def test_the_rest_of_kalimdor_is_the_alliances_own_ground(self):
        for zone in (DARKSHORE, ASHENVALE, 405, 406, 357):
            self.assertEqual(
                guildlevel.ground_of(ALLIANCE, KALIMDOR, zone),
                guildlevel.MAIN_GROUND,
                zone,
            )

    def test_the_hordes_dustwallow_is_not_a_pocket(self):
        self.assertEqual(
            guildlevel.ground_of(HORDE, KALIMDOR, DUSTWALLOW),
            guildlevel.MAIN_GROUND,
        )


class TheChoice(unittest.TestCase):
    def masters(self):
        return guildlevel.hub_masters(master_rows())

    def test_a_member_on_the_main_ground_is_never_walked_into_dustwallow(self):
        only = {DUSTWALLOW: bands()[DUSTWALLOW]}
        low = bands()[DUSTWALLOW][0]
        got = guildlevel.choose(
            low, NIGHT_ELF, KALIMDOR, only, self.masters(), zone_id=DARKSHORE
        )
        self.assertIsNone(got.master)
        self.assertIn("past the other side's ground", got.refused)

    def test_a_member_in_dustwallow_is_not_walked_out_across_the_barrens(self):
        only = {ASHENVALE: bands()[ASHENVALE]}
        got = guildlevel.choose(
            bands()[ASHENVALE][0],
            NIGHT_ELF,
            KALIMDOR,
            only,
            self.masters(),
            zone_id=DUSTWALLOW,
        )
        self.assertIsNone(got.master)

    def test_a_member_in_dustwallow_takes_the_theramore_boat_to_a_hub_beyond(self):
        got = guildlevel.choose(
            20,
            HUMAN,
            KALIMDOR,
            bands(),
            self.masters(),
            zone_id=DUSTWALLOW,
        )
        self.assertIsNone(got.master)
        self.assertEqual(got.cross_to, EASTERN_KINGDOMS)
        self.assertIn("Theramore", got.transport)

    def test_a_member_in_dustwallow_with_a_dustwallow_hub_that_fits_stays_in_it(self):
        got = guildlevel.choose(
            bands()[DUSTWALLOW][0],
            HUMAN,
            KALIMDOR,
            {DUSTWALLOW: bands()[DUSTWALLOW]},
            self.masters(),
            zone_id=DUSTWALLOW,
        )
        self.assertEqual(got.hub.zone_id, DUSTWALLOW)
        self.assertIsNotNone(got.master)

    def test_the_hordes_level_walks_are_unchanged(self):
        horde = bands(HORDE)
        got = guildlevel.choose(
            14, ORC, KALIMDOR, horde, self.masters(), zone_id=DUSTWALLOW
        )
        self.assertEqual(got.hub.key, "barrens")


if __name__ == "__main__":
    unittest.main()
