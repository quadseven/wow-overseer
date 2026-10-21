"""Blacksmithing, Engineering and Enchanting buy their ranks past 75 (#774).

WHAT WAS SEEN (wow-dev, 2026-10-10). `guildjobs.RANKS` carried Herbalism,
Mining, Skinning, First Aid, Tailoring, Leatherworking and Alchemy, so
`guildjobs.ranks_due` never wrote a rank errand for a family smith (Grug,
Zug), engineer (Grog, Zrog) or enchanter (Og, Oz), and each would stop at 75.
The rows are the realm's own `trainer_spell` wrappers, each checked against
its Spell.dbc (md5 543b9fe6...): SPELL_EFFECT_LEARN_SPELL teaches the rank
spell and SPELL_EFFECT_SKILL_STEP (44) is step 1 to 4 of the skill.

THE LADDERS PAST 75 ARE NAMED, NOT FILLED. Every trainer recipe the realm
teaches between the stones' grey values needs an Anvil (Spell.dbc
RequiresSpellFocus 1), and nothing walks a crafter to one yet
(craft.FOCUS_AIMS holds only the Forge). The gaps are pinned below with that
reason, so a change that fills one has to update this test.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import craft  # noqa: E402
import guildjobs  # noqa: E402

BLACKSMITHING, ENGINEERING, ENCHANTING = 164, 202, 333

MEASURED = {
    # skill: (wrapper spells Apprentice..Artisan, prices in copper)
    BLACKSMITHING: ((2020, 2021, 3539, 9786), (10, 500, 5000, 50000)),
    ENGINEERING: ((4039, 4040, 4041, 12657), (10, 500, 5000, 50000)),
    ENCHANTING: ((7414, 7415, 7416, 13921), (10, 500, 5000, 50000)),
}


def spans(values):
    out = []
    for v in values:
        if out and out[-1][1] == v - 1:
            out[-1][1] = v
        else:
            out.append([v, v])
    return [tuple(s) for s in out]


class TheThreeTradesHaveRanks(unittest.TestCase):
    def test_the_rows_are_the_realms_trainer_rows(self):
        for skill, (spells, costs) in MEASURED.items():
            ranks = guildjobs.RANKS[skill]
            with self.subTest(skill=skill):
                self.assertEqual(spells, tuple(r.spell for r in ranks))
                self.assertEqual(costs, tuple(r.cost for r in ranks))
                self.assertEqual((75, 150, 225, 300), tuple(r.cap for r in ranks))
                self.assertEqual((0, 50, 125, 200), tuple(r.needs for r in ranks))

    def test_grug_at_blacksmithing_70_of_75_is_due_journeyman(self):
        # Grug: level 43, 456,677 copper; roster professions 164,186.
        self.assertEqual(
            (BLACKSMITHING,),
            guildjobs.ranks_due(43, 456677, {BLACKSMITHING: (70, 75)}, (164, 186)),
        )

    def test_grog_at_engineering_70_of_75_is_due_journeyman(self):
        self.assertEqual(
            (ENGINEERING,),
            guildjobs.ranks_due(40, 117329, {ENGINEERING: (70, 75)}, (186, 202)),
        )

    def test_og_at_enchanting_70_of_75_is_due_journeyman(self):
        self.assertEqual(
            (ENCHANTING,),
            guildjobs.ranks_due(38, 358300, {ENCHANTING: (70, 75)}, (197, 333)),
        )

    def test_below_the_margin_nothing_is_due(self):
        self.assertEqual(
            (), guildjobs.ranks_due(43, 456677, {BLACKSMITHING: (22, 75)}, (164, 186))
        )


class TheLadderGapsAreNamed(unittest.TestCase):
    """recipe_for answers a rung for every value or the gap is named here."""

    ANVIL = "every trainer recipe here needs an Anvil, and no walk reaches one"

    GAPS = {
        # The stones (no focus) grey at 100, 150, 210 and 260.
        # ANVIL route recipes now fill most gaps (operator, 2026-10-21).
        # Every rung needs an Anvil (focus 1) and trainer-taught smelts;
        # only Smelt Copper exists today. The rest wait on Smelt
        # Bronze/Iron/Gold/Mithril/Thorium (quadseven/mod-overseer#160).
        # Remaining gaps where no recipe's trainer floor <= gap start:
        BLACKSMITHING: {
            (150, 154): "no Anvil recipe with trainer floor <= 150",
            (160, 179): "no Anvil recipe with trainer floor <= 160",
        },
        ENGINEERING: {
            # Bronze Framework (3953) now fills 145-174 (no focus, needs Bronze Bar).
            # 260 remains a single-point gap: Dense Blasting Powder greys at 260;
            # Thorium Widget taught at 261.
            (260, 260): "Dense Blasting Powder greys at 260; next rung taught at 261",
        },
    }

    def test_every_value_has_a_rung_or_a_named_gap(self):
        for skill, named in self.GAPS.items():
            gaps = spans(v for v in range(1, 301) if craft.recipe_for(skill, v) is None)
            with self.subTest(skill=skill):
                self.assertEqual(sorted(named), gaps)

    def test_engineerings_anvil_rungs_wait_for_an_anvil_walk(self):
        gated = spans(
            v
            for v in range(1, 301)
            if (r := craft.recipe_for(ENGINEERING, v)) is not None
            and r.focus
            and r.focus not in craft.FOCUS_AIMS
        )
        self.assertEqual([(31, 75), (106, 124), (195, 250), (261, 300)], gated)
        self.assertNotIn(1, craft.FOCUS_AIMS)


if __name__ == "__main__":
    unittest.main()
