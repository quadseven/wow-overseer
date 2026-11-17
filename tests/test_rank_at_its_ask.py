"""A family member buys a rank once the trainer would sell it (#2500).

WHAT WAS SEEN (wow-dev, 2026-11-17, read only). Uzza held Herbalism 125 of 150
and Alchemy 52 of 75. The trainer sells Expert Herbalism at skill 125 and
Journeyman Alchemy at skill 50, both within the member's level and purse, yet
no rank errand was due: `next_rank` waits until the value is within
RANK_UP_MARGIN of the ceiling, and the loop's gathering and crafting had not
brought any trade that close in three days. So no rank purchase had ever been
recorded and the ticket's live box could not be met.

THE RULE HERE. `ranks_due`, which only a roster family member's errand reads,
asks for the next rank as soon as the rank's own asks (level, skill value) hold
and the purse covers it. The guild crew's `next_rank` keeps its margin: a crew
member walks a trainer for its own reasons and would otherwise make three trips
per trade for 76 members.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guildjobs  # noqa: E402
import learnaim  # noqa: E402

HERB, ALCHEMY, TAILORING = guildjobs.HERBALISM, guildjobs.ALCHEMY, guildjobs.TAILORING


class ARankIsDueWhenTheTrainerWouldSellIt(unittest.TestCase):
    def test_uzza_herbalism_125_of_150_is_due_expert(self):
        self.assertEqual(
            (HERB,), guildjobs.ranks_due(60, 60000, {HERB: (125, 150)}, (HERB,))
        )

    def test_uzza_alchemy_52_of_75_is_due_journeyman(self):
        self.assertEqual(
            (ALCHEMY,), guildjobs.ranks_due(60, 60000, {ALCHEMY: (52, 75)}, (ALCHEMY,))
        )

    def test_a_trade_one_point_short_of_the_ask_waits(self):
        self.assertEqual(
            (), guildjobs.ranks_due(60, 60000, {HERB: (124, 150)}, (HERB,))
        )
        self.assertEqual(
            (), guildjobs.ranks_due(60, 60000, {ALCHEMY: (49, 75)}, (ALCHEMY,))
        )

    def test_ugga_herbalism_199_waits_for_artisan_and_200_buys_it(self):
        self.assertEqual(
            (), guildjobs.ranks_due(60, 600000, {HERB: (199, 225)}, (HERB,))
        )
        self.assertEqual(
            (HERB,), guildjobs.ranks_due(60, 600000, {HERB: (200, 225)}, (HERB,))
        )

    def test_a_short_purse_still_waits(self):
        self.assertEqual((), guildjobs.ranks_due(60, 4999, {HERB: (125, 150)}, (HERB,)))

    def test_the_level_ask_still_holds(self):
        # Artisan asks level 25 for Herbalism.
        self.assertEqual(
            (), guildjobs.ranks_due(24, 600000, {HERB: (200, 225)}, (HERB,))
        )

    def test_a_trade_the_roster_does_not_name_is_not_started(self):
        self.assertEqual((), guildjobs.ranks_due(60, 60000, {HERB: (125, 150)}, ()))

    def test_og_tailoring_157_of_225_is_not_due(self):
        self.assertEqual(
            (), guildjobs.ranks_due(60, 600000, {TAILORING: (157, 225)}, (TAILORING,))
        )

    def test_the_crew_rule_keeps_its_margin(self):
        self.assertIsNone(guildjobs.next_rank(HERB, 125, 150, 60))
        self.assertEqual(guildjobs.next_rank(HERB, 145, 150, 60).spell, 3571)

    def test_a_due_rank_becomes_a_rank_errand(self):
        due = guildjobs.ranks_due(60, 60000, {HERB: (125, 150)}, (HERB,))
        row = learnaim.Row(
            character="Uzza",
            leads=False,
            learn_skill=0,
            wanted=(HERB,),
            ranks=due,
        )
        self.assertEqual(("Uzza", HERB), learnaim.rank_errand([row]))


if __name__ == "__main__":
    unittest.main()
