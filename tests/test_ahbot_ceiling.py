"""What the auction house may reach for, and why one ceiling is not enough.

Pure unit tests. The item levels and required levels below are REAL values from
this realm's item table, not invented ones, because the whole point of the
decision under test is that it excludes a specific item somebody actually
bought. Netherweave Bag is item 21841 at item level 63 with no required level.

This suite also reads the deployed conf and asserts it agrees with the module,
so the two ceilings cannot be edited in the manifest without the reasoning
moving with them.
"""

import pathlib
import sys
import unittest

# tools/, not the top level: this module decides a number, it is not part of
# the running bridge, and the top level of this directory is what gets packed
# into the build's shared tarball against a ConfigMap size budget. Same import
# shape as tests/test_probe.py.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import ahbot_ceiling  # noqa: E402


AHBOT_CONF = (
    pathlib.Path(__file__).resolve().parents[1]
    / "oke"
    / "manifests"
    / "wow-dev"
    / "config"
    / "ahbot.overrides.conf"
)


def _limits(levels=ahbot_ceiling.ROSTER_LEVELS_MEASURED):
    return ahbot_ceiling.ceilings(ahbot_ceiling.top_level(levels))


class TopLevelTest(unittest.TestCase):
    def test_the_ceiling_serves_the_highest_character(self):
        self.assertEqual(ahbot_ceiling.top_level([23, 29, 26, 24, 28]), 29)

    def test_order_does_not_matter(self):
        self.assertEqual(
            ahbot_ceiling.top_level([29, 23]), ahbot_ceiling.top_level([23, 29])
        )

    def test_an_empty_roster_is_refused_rather_than_guessed(self):
        # A ceiling derived from no characters is a number nobody chose, and it
        # would be indistinguishable from one that was.
        with self.assertRaises(ValueError):
            ahbot_ceiling.top_level([])


class CeilingsTest(unittest.TestCase):
    def test_the_measured_roster_produces_the_deployed_numbers(self):
        limits = _limits()
        self.assertEqual(limits.max_required_level, 34)
        self.assertEqual(limits.max_item_level, 44)

    def test_the_ceiling_is_above_the_roster_not_at_it(self):
        # A ceiling at exactly the top character's level is stale on the next
        # ding, and it also means the house only ever sells gear that is about
        # to be replaced.
        limits = _limits()
        self.assertGreater(limits.max_required_level, ahbot_ceiling.top_level([23, 29]))

    def test_the_ceiling_rises_with_the_roster(self):
        self.assertLess(
            ahbot_ceiling.ceilings(29).max_required_level,
            ahbot_ceiling.ceilings(40).max_required_level,
        )

    def test_gear_at_the_required_level_ceiling_is_not_stripped_by_the_item_level_one(
        self,
    ):
        # THE INVARIANT THAT MAKES TWO CEILINGS SAFE TO COMBINE. Item level runs
        # about five ahead of required level for gear in this band, so an item
        # level ceiling set too close to the required level ceiling would quietly
        # re-filter the very gear the other ceiling was set to allow, and the
        # house would look thin for no stated reason.
        for roster_top in (10, 29, 45, 70):
            limits = ahbot_ceiling.ceilings(roster_top)
            at_the_ceiling_item_level = (
                limits.max_required_level + ahbot_ceiling.OBSERVED_GEAR_OFFSET
            )
            self.assertTrue(
                ahbot_ceiling.would_list(
                    at_the_ceiling_item_level, limits.max_required_level, limits
                ),
                "gear at the required level ceiling was stripped by the item "
                "level ceiling at roster top {}".format(roster_top),
            )

    def test_a_margin_below_the_observed_offset_is_refused(self):
        with self.assertRaises(ValueError):
            ahbot_ceiling.ceilings(29, margin=ahbot_ceiling.OBSERVED_GEAR_OFFSET - 1)

    def test_a_level_below_one_is_refused(self):
        with self.assertRaises(ValueError):
            ahbot_ceiling.ceilings(0)

    def test_the_realm_total_is_the_three_houses(self):
        self.assertEqual(_limits().total_listings, 2250)


class WouldListTest(unittest.TestCase):
    """Real items, measured item levels, against the deployed ceiling."""

    def setUp(self):
        self.limits = _limits()

    def test_the_bag_that_started_this_is_excluded(self):
        # Netherweave Bag, item 21841: item level 63, no required level.
        self.assertFalse(ahbot_ceiling.would_list(63, 0, self.limits))

    def test_the_required_level_ceiling_alone_would_not_have_excluded_it(self):
        # THE POINT OF THE WHOLE DESIGN, stated as a test rather than a comment.
        # The module's required-level filter skips any item whose RequiredLevel
        # is zero, and a container has none - so the key that sounds like the
        # answer passes this bag while looking like it is working. Only the item
        # level ceiling catches it.
        required_level_ceiling_only = ahbot_ceiling.Ceilings(
            max_required_level=self.limits.max_required_level,
            max_item_level=10_000,
            listings_per_house=self.limits.listings_per_house,
        )
        self.assertTrue(
            ahbot_ceiling.would_list(63, 0, required_level_ceiling_only),
            "if this ever fails the asymmetry has gone away and the second "
            "ceiling may no longer be needed - check the C++ before deleting it",
        )

    def test_the_outland_bags_siblings_go_too(self):
        for name, item_level in (
            ("Bottomless Bag", 62),
            ("Mooncloth Bag", 60),
        ):
            with self.subTest(name):
                self.assertFalse(ahbot_ceiling.would_list(item_level, 0, self.limits))

    def test_the_bags_a_party_in_the_twenties_can_actually_use_stay(self):
        for name, item_level in (
            ("Linen Bag", 5),
            ("Woolen Bag", 15),
            ("Small Silk Pack", 25),
            ("Mageweave Bag", 35),
        ):
            with self.subTest(name):
                self.assertTrue(ahbot_ceiling.would_list(item_level, 0, self.limits))

    def test_the_cloth_ladder_is_cut_at_the_right_rung(self):
        # The family farms and weaves the bottom of this ladder. Runecloth and
        # Netherweave are content they have not reached, so the house selling
        # them is the same failure as the bag.
        for name, item_level, listed in (
            ("Linen Cloth", 5, True),
            ("Wool Cloth", 15, True),
            ("Silk Cloth", 30, True),
            ("Mageweave Cloth", 40, True),
            ("Runecloth", 50, False),
            ("Netherweave Cloth", 60, False),
        ):
            with self.subTest(name):
                self.assertEqual(
                    ahbot_ceiling.would_list(item_level, 0, self.limits), listed
                )

    def test_gear_the_roster_can_equip_stays(self):
        # Twisted Sabre, item 2011: item level 26 at required level 21. A rare
        # this roster has already had drop for it.
        self.assertTrue(ahbot_ceiling.would_list(26, 21, self.limits))

    def test_gear_from_another_expansion_goes(self):
        self.assertFalse(ahbot_ceiling.would_list(115, 70, self.limits))

    def test_an_item_level_of_zero_is_kept(self):
        # The floor exists to be zero: a great many quest, key and misc items
        # carry ItemLevel 0, and the item level filter has no zero guard, so a
        # floor above zero would delete all of them.
        self.assertTrue(ahbot_ceiling.would_list(0, 0, self.limits))

    def test_a_high_required_level_is_excluded_even_at_a_low_item_level(self):
        self.assertFalse(ahbot_ceiling.would_list(20, 60, self.limits))


# DeployedConfTest (whole class) and DriftTest's
# test_a_roster_that_has_outgrown_the_conf_is_named_with_both_numbers
# removed here: both read quadseven/infra's
# production/oke/manifests/wow-dev/config/ahbot.overrides.conf, which this
# repo does not carry. Equivalent checks should live in infra's own wow-dev
# render-test suite instead - see the tracking issue for this split.


class DriftTest(unittest.TestCase):
    def test_a_missing_key_is_reported_as_the_dist_default_standing(self):
        reasons = ahbot_ceiling.drift("", ahbot_ceiling.ROSTER_LEVELS_MEASURED)
        self.assertTrue(all("is not set at all" in r for r in reasons), reasons)
        self.assertEqual(len(reasons), len(ahbot_ceiling.overrides(_limits())))


if __name__ == "__main__":
    unittest.main()
