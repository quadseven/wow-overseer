"""The ordered campaign inside one dungeon, and which dungeons have one.

infra#4247 widened this module from "Scarlet Monastery's four wings" to "the
ordered stages of whichever dungeon the level frontier picked". The tests that
pinned the Scarlet behaviour are all still here and still pass unchanged: the
generalization was meant to add a second campaign, not to loosen the first.
"""

import pathlib
import unittest

import dungeonprogression

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"


class SuccessfulRuns(unittest.TestCase):
    def test_counts_only_explicit_completion_for_the_named_wing(self):
        rows = [
            {"portal_keyword": "scarlet", "outcome": "complete"},
            {"portal_keyword": "scarlet", "outcome": "left"},
            {"portal_keyword": "scarlet-library", "outcome": "wipe"},
            {"portal_keyword": "", "outcome": "complete"},
        ]
        counts = dungeonprogression.successful_runs(rows)
        self.assertEqual(1, counts["scarlet"])
        self.assertEqual(0, counts["scarlet-library"])
        self.assertEqual(0, counts["scarlet-armory"])
        self.assertEqual(0, counts["scarlet-cathedral"])

    def test_a_blackrock_depths_clear_is_counted_too(self):
        """The live read was `map_id = 189`, so a BRD run could not have been
        seen at all however it ended (infra#4247)."""
        rows = [
            {"portal_keyword": "blackrock-depths", "outcome": "complete"},
            {"portal_keyword": "blackrock-depths", "outcome": "complete"},
            {"portal_keyword": "blackrock-depths", "outcome": "emptied"},
            {"portal_keyword": "blackrock-depths", "outcome": "reset_failed"},
            {"portal_keyword": "blackrock-depths", "outcome": "left"},
            {"portal_keyword": "blackrock-depths", "outcome": "wipe"},
        ]
        self.assertEqual(
            2, dungeonprogression.successful_runs(rows)["blackrock-depths"]
        )

    def test_a_dungeon_with_no_clears_is_a_zero_and_not_an_absence(self):
        counts = dungeonprogression.successful_runs([])
        self.assertIn("blackrock-depths", counts)
        self.assertEqual(0, counts["blackrock-depths"])


class WhichCampaignsExist(unittest.TestCase):
    def test_scarlet_monastery_keeps_its_four_doors(self):
        self.assertEqual(
            ["scarlet", "scarlet-library", "scarlet-armory", "scarlet-cathedral"],
            [k for k, _ in dungeonprogression.campaign_stages(189)],
        )

    def test_blackrock_depths_is_one_door_and_not_four(self):
        """One map, one instance script, one entrance and one exit in
        areatrigger_teleport - so map id 230 identifies the run on its own and
        there is nothing for a durable keyword to disambiguate."""
        self.assertEqual(
            [("blackrock-depths", 52)],
            list(dungeonprogression.campaign_stages(230)),
        )

    def test_a_map_with_no_named_doors_says_so_rather_than_guessing(self):
        self.assertEqual((), dungeonprogression.campaign_stages(36))

    def test_the_adapter_reads_every_campaign_map(self):
        self.assertEqual((189, 230), dungeonprogression.CAMPAIGN_MAP_IDS)


class OrderedStage(unittest.TestCase):
    WINGS = dungeonprogression.SCARLET_WINGS

    def test_missing_ledger_does_not_guess_a_wing(self):
        self.assertIsNone(dungeonprogression.next_stage(None, 25, stages=self.WINGS))

    def test_starts_at_graveyard(self):
        self.assertEqual(
            "scarlet",
            dungeonprogression.next_stage({}, 25, stages=self.WINGS),
        )

    def test_advances_only_after_the_previous_wing_is_complete(self):
        self.assertEqual(
            "scarlet-library",
            dungeonprogression.next_stage({"scarlet": 25}, 25, stages=self.WINGS),
        )
        self.assertEqual(
            "scarlet-armory",
            dungeonprogression.next_stage(
                {"scarlet": 25, "scarlet-library": 25}, 25, stages=self.WINGS
            ),
        )
        self.assertEqual(
            "scarlet-cathedral",
            dungeonprogression.next_stage(
                {"scarlet": 25, "scarlet-library": 25, "scarlet-armory": 25},
                25,
                stages=self.WINGS,
            ),
        )

    def test_does_not_skip_an_incomplete_lower_wing(self):
        self.assertEqual(
            "scarlet",
            dungeonprogression.next_stage(
                {
                    "scarlet": 24,
                    "scarlet-library": 25,
                    "scarlet-armory": 25,
                    "scarlet-cathedral": 25,
                },
                25,
                stages=self.WINGS,
            ),
        )

    def test_completed_campaign_has_no_next_wing(self):
        counts = {keyword: 25 for keyword, _ in self.WINGS}
        self.assertIsNone(dungeonprogression.next_stage(counts, 25, stages=self.WINGS))

    def test_blackrock_depths_is_ordered_until_the_campaign_size_is_met(self):
        stages = dungeonprogression.campaign_stages(230)
        self.assertEqual(
            "blackrock-depths",
            dungeonprogression.next_stage({}, 25, stages=stages),
        )
        self.assertEqual(
            "blackrock-depths",
            dungeonprogression.next_stage({"blackrock-depths": 24}, 25, stages=stages),
        )
        self.assertIsNone(
            dungeonprogression.next_stage({"blackrock-depths": 25}, 25, stages=stages),
        )


class FrontierStage(unittest.TestCase):
    WINGS = dungeonprogression.SCARLET_WINGS

    def test_the_highest_door_the_family_can_reach(self):
        self.assertEqual(
            "scarlet", dungeonprogression.frontier_stage(self.WINGS, 28, slack=2)
        )
        self.assertEqual(
            "scarlet-cathedral",
            dungeonprogression.frontier_stage(self.WINGS, 41, slack=2),
        )

    def test_the_slack_is_the_callers_and_not_this_modules(self):
        self.assertEqual(
            "scarlet-library",
            dungeonprogression.frontier_stage(self.WINGS, 31, slack=2),
        )
        self.assertEqual(
            "scarlet", dungeonprogression.frontier_stage(self.WINGS, 31, slack=0)
        )

    def test_a_family_below_every_door_still_gets_the_first_one(self):
        """Not None: the READINESS gate is prospects()' job, and answering it
        twice in two places is how the two come to disagree."""
        self.assertEqual(
            "scarlet", dungeonprogression.frontier_stage(self.WINGS, 10, slack=2)
        )

    def test_no_stages_is_no_keyword(self):
        self.assertEqual("", dungeonprogression.frontier_stage((), 60, slack=2))


class ThePortalKeywordsTheWorldserverActuallyKnows(unittest.TestCase):
    """Every keyword this module can emit becomes `dungeon:<keyword>` on the
    roster, and mod_overseer.cpp's DoJob answers "unknown job mode" to any
    keyword its DungeonPortals() table has no row for - which means the job
    column is never written and the run never opens.

    So this is asserted against the pinned C++ as source text, the way
    test_jobs.py already pins IMPLEMENTED. A claim about another repo that
    nobody checks is exactly how `blackrock-depths` could ship looking wired.
    """

    @classmethod
    def setUpClass(cls):
        if not MODULE.exists():
            raise unittest.SkipTest(
                "mod-overseer submodule is not checked out: "
                "git submodule update --init "
                "production/docker/azerothcore-playerbots/mod-overseer"
            )
        cls.source = MODULE.read_text(encoding="utf-8", errors="replace")

    def _has_portal_row(self, keyword: str) -> bool:
        return '{"%s", ' % keyword in self.source

    def test_every_scarlet_wing_has_a_portal_row(self):
        for keyword, _ in dungeonprogression.SCARLET_WINGS:
            self.assertTrue(
                self._has_portal_row(keyword),
                "mod_overseer.cpp DungeonPortals() has no row for %r, so "
                "DoJob would answer 'unknown job mode' and the family would "
                "never be sent there" % keyword,
            )

    @unittest.expectedFailure
    def test_blackrock_depths_has_no_portal_row_yet(self):
        """THE KNOWN CROSS-REPO GAP, pinned rather than described (infra#4247).

        AC_OVERSEER_SHA c929cb15 carries eight portal rows - deadmines,
        shadowfang, the four Scarlet wings, stockades and wailing - and no
        Blackrock Depths. The infra half of this issue decides the target; the
        row that lets the coordinator walk to it belongs to mod-overseer, and
        the numbers it needs were read off this same pinned core:

            {"blackrock-depths", 0, 1466, 230, 1472, <inn x,y,z on map 0>}

        areatrigger 1466 stands on map 0 at (-7176.63, -937.667, 170.206) with
        radius 13 and lands on map 230; areatrigger 1472 stands inside on map
        230 at (456.969, 48.368, -65.2753) with radius 12 and lands back on
        map 0.

        expectedFailure and not a skip on purpose: the day that row lands this
        test reports an UNEXPECTED SUCCESS and fails the suite, so the gap
        cannot quietly stay described after it has been closed.
        """
        self.assertTrue(self._has_portal_row("blackrock-depths"))


if __name__ == "__main__":
    unittest.main()
