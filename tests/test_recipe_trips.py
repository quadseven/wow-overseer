"""A family crafter is sent to its trainer whenever a ladder recipe is buyable (#2432).

WHAT WAS SEEN (dev realm, 2026-11-13, read only). The worldserver buys every
recipe a crafter can use once a learn errand brings it to its trade's trainer
(the last such visit bought eight leatherworking recipes in one stop). What
stalls is the bridge's side, which decides whether to write that errand:

  * First Aid was never asked. Three members stood at First Aid 60/75 with
    plenty of gold and no Heavy Linen Bandage (3276, trainer rank 40), so they
    could make only Linen Bandage, which is grey at 60. `ranks_due` lets First
    Aid through without a roster permission; `recipes_due` did not, and the
    Journeyman rank is not due until 70, so nothing ever sent them.
  * Only the rung at the skill now and five points on was asked, so a rung the
    trainer sells below the bracket it is cast in waited for a later trip.
  * The purse floor was one silver, a repair at level 60 costs gold.
  * The known set was `character_spell` alone, which lags the purchase by up
    to fifteen minutes and never holds a recipe a playerbot was granted at
    creation. A recipe the bot already holds but the table lacks would send it
    to the trainer for nothing, again and again.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import craft  # noqa: E402
import guildjobs  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

FIRST_AID, LEATHERWORKING, SKINNING, TAILORING = 129, 165, 393, 197
HEAVY_LINEN_BANDAGE = 3276
RICH = 4_000_000  # about what each live crafter carries


class FirstAidRecipesAreDue(unittest.TestCase):
    """Zork, read live: First Aid 60/75, Leatherworking 1/75, 427g."""

    SKILLS = {FIRST_AID: (60, 75), LEATHERWORKING: (1, 75)}

    def test_heavy_linen_bandage_is_due_without_a_roster_permission(self):
        self.assertIn(
            FIRST_AID,
            guildjobs.recipes_due(
                60, RICH, self.SKILLS, frozenset(), (LEATHERWORKING, SKINNING)
            ),
        )

    def test_held_it_is_not(self):
        self.assertNotIn(
            FIRST_AID,
            guildjobs.recipes_due(
                60, RICH, self.SKILLS, {HEAVY_LINEN_BANDAGE}, (LEATHERWORKING, SKINNING)
            ),
        )

    def test_a_first_aid_trade_not_held_is_not_started(self):
        self.assertEqual(
            (),
            guildjobs.recipes_due(60, RICH, {FIRST_AID: (0, 0)}, frozenset(), ()),
        )


class EveryLadderRungTheTrainerSellsNow(unittest.TestCase):
    def test_a_rung_sold_below_its_bracket_is_due_early(self):
        # Crimson Silk Pantaloons is cast from 205 and the trainer sells it at
        # 195. At 195 the rung for now and for 200 is Crimson Silk Vest; held,
        # the buy left is the one ahead, bought on this trip, not a later one.
        ladder = craft.RECIPES[TAILORING]
        rung = next(r for r in ladder if r.name == "Crimson Silk Pantaloons")
        rank, _cost = craft.TRAINER_RECIPES[rung.spell_id]
        self.assertLess(rank, rung.min_skill - guildjobs.RANK_UP_MARGIN)
        held = {r.spell_id for r in ladder if r.min_skill < rung.min_skill} | {
            r.spell_id for r in craft.BAG_RECIPES[TAILORING]
        }
        self.assertEqual(
            (TAILORING,),
            guildjobs.recipes_due(
                60, RICH, {TAILORING: (rank, 225)}, held, (TAILORING,)
            ),
        )

    def test_a_rung_the_trainer_sells_only_higher_up_is_not_due(self):
        alchemy = 171
        ladder = craft.RECIPES[alchemy]
        held = {r.spell_id for r in ladder if r.min_skill <= 110}
        self.assertEqual(
            (), guildjobs.recipes_due(60, RICH, {alchemy: (112, 150)}, held, (alchemy,))
        )

    def test_a_rung_already_past_is_not_due(self):
        # A tailor at 155 who never bought a rung it has outgrown is not sent
        # back for it.
        past = [r for r in craft.RECIPES[TAILORING] if r.max_skill < 155]
        held = {r.spell_id for r in craft.RECIPES[TAILORING] if r.max_skill >= 155} | {
            r.spell_id for r in craft.BAG_RECIPES[TAILORING]
        }
        self.assertTrue(any(r.spell_id in craft.TRAINER_RECIPES for r in past))
        self.assertEqual(
            (),
            guildjobs.recipes_due(
                60, RICH, {TAILORING: (155, 225)}, held, (TAILORING,)
            ),
        )


class ARungNoTrainerSellsIsSkipped(unittest.TestCase):
    def test_every_ladder_at_every_value_with_an_empty_book(self):
        # The ladder walk now meets auto-learned and plan-taught rungs, which
        # have no trainer price; each is skipped, never looked up.
        untaught = [
            r
            for rs in craft.RECIPES.values()
            for r in rs
            if r.spell_id not in craft.TRAINER_RECIPES
        ]
        self.assertTrue(untaught)
        for skill in craft.RECIPES:
            for value in range(0, 301, 5):
                with self.subTest(skill=skill, value=value):
                    guildjobs.recipes_due(
                        60, RICH, {skill: (value, 300)}, frozenset(), (skill,)
                    )


class TheRepairReserve(unittest.TestCase):
    def test_the_floor_grows_with_level(self):
        self.assertEqual(guildjobs.RECIPE_PURSE_FLOOR, guildjobs.recipe_purse_floor(1))
        self.assertEqual(36_000, guildjobs.recipe_purse_floor(60))
        self.assertLess(
            guildjobs.recipe_purse_floor(20), guildjobs.recipe_purse_floor(40)
        )

    def test_a_purse_inside_the_reserve_buys_nothing(self):
        skills = {FIRST_AID: (60, 75)}
        floor = guildjobs.recipe_purse_floor(60)
        cost = craft.TRAINER_RECIPES[HEAVY_LINEN_BANDAGE][1]
        self.assertEqual(
            (), guildjobs.recipes_due(60, floor + cost - 1, skills, frozenset(), ())
        )
        self.assertEqual(
            (FIRST_AID,),
            guildjobs.recipes_due(60, floor + cost, skills, frozenset(), ()),
        )


class AVisitThatBoughtNothingIsNotRepeated(unittest.TestCase):
    def test_a_trade_visited_lately_is_not_due_again(self):
        skills = {FIRST_AID: (60, 75)}
        self.assertEqual(
            (),
            guildjobs.recipes_due(
                60, RICH, skills, frozenset(), (), visited=(FIRST_AID,)
            ),
        )

    def test_another_trade_is_still_due(self):
        skills = {FIRST_AID: (60, 75)}
        self.assertEqual(
            (FIRST_AID,),
            guildjobs.recipes_due(
                60, RICH, skills, frozenset(), (), visited=(TAILORING,)
            ),
        )


class TheBridgeReadsTheWorldserversOwnBook(unittest.TestCase):
    def test_known_recipes_include_what_the_worldserver_recorded(self):
        # A bought recipe ('learn'), a cast one ('craft') and one the module
        # read with HasSpell at the trainer ('recipe-known').
        start = BRIDGE.find("_RECIPES_SEEN_SQL = (")
        self.assertNotEqual(-1, start, "_RECIPES_SEEN_SQL")
        seen = BRIDGE[start : start + 800]
        for kind in ("'learn'", "'craft'", "'recipe-known'"):
            self.assertTrue(kind in seen, kind)

    def test_recent_trainer_visits_are_read(self):
        for text in ("'trainer-visit'", "visited=visits.get(name, ())"):
            self.assertTrue(text in BRIDGE, text)

    def test_the_retry_window_is_hours(self):
        self.assertGreaterEqual(guildjobs.RECIPE_VISIT_RETRY_HOURS, 2)


if __name__ == "__main__":
    unittest.main()
