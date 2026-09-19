import unittest

import dungeonprogression


class SuccessfulRuns(unittest.TestCase):
    def test_counts_only_explicit_completion_for_the_named_wing(self):
        rows = [
            {"portal_keyword": "scarlet", "outcome": "complete"},
            {"portal_keyword": "scarlet", "outcome": "left"},
            {"portal_keyword": "scarlet-library", "outcome": "wipe"},
            {"portal_keyword": "", "outcome": "complete"},
        ]
        self.assertEqual(
            dungeonprogression.successful_runs(rows),
            {"scarlet": 1, "scarlet-library": 0,
             "scarlet-armory": 0, "scarlet-cathedral": 0},
        )


class OrderedWing(unittest.TestCase):
    def test_missing_ledger_does_not_guess_a_wing(self):
        self.assertIsNone(dungeonprogression.next_scarlet_wing(None, 25))

    def test_starts_at_graveyard(self):
        self.assertEqual(
            dungeonprogression.next_scarlet_wing({}, 25), "scarlet"
        )

    def test_advances_only_after_the_previous_wing_is_complete(self):
        self.assertEqual(
            dungeonprogression.next_scarlet_wing(
                {"scarlet": 25}, 25), "scarlet-library"
        )
        self.assertEqual(
            dungeonprogression.next_scarlet_wing(
                {"scarlet": 25, "scarlet-library": 25}, 25),
            "scarlet-armory",
        )
        self.assertEqual(
            dungeonprogression.next_scarlet_wing(
                {"scarlet": 25, "scarlet-library": 25,
                 "scarlet-armory": 25}, 25),
            "scarlet-cathedral",
        )

    def test_does_not_skip_an_incomplete_lower_wing(self):
        self.assertEqual(
            dungeonprogression.next_scarlet_wing(
                {"scarlet": 24, "scarlet-library": 25,
                 "scarlet-armory": 25, "scarlet-cathedral": 25}, 25),
            "scarlet",
        )

    def test_completed_campaign_has_no_next_wing(self):
        counts = {keyword: 25 for keyword, _ in dungeonprogression.SCARLET_WINGS}
        self.assertIsNone(dungeonprogression.next_scarlet_wing(counts, 25))


if __name__ == "__main__":
    unittest.main()
