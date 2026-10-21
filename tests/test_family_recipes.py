"""A family crafter walks to its trainer and buys the recipe its ladder needs.

WHAT WAS SEEN (wow-dev, 2026-10-10). Every crafter in both guilds is a family
member, and every rung of craft.RECIPES above the first is a trainer purchase.
A family member trains only through `overseer_roster.learn_skill`, and the
bridge wrote that column only for a rank. So nothing ever sent one to buy a
recipe: Og (Tailoring 81/150) held Linen Belt (8776) and Linen Bag (3755) and
not Bolt of Woolen Cloth (2964), the worldserver dropped his craft errand 14
times in a day ("does not know the recipe"), and Oz's Linen Bag (3755) 13
times. mod-overseer's TrainOnArrival already buys a trade's recipes at the
trainer's price once a learn errand brings the member there
(mod-overseer#862); `guildjobs.recipes_due` is what now writes that errand.

THE PACE. Ugga cast 25 Minor Healing Potions in 14 days while carrying the
herbs for 27 more: `craft_supply.TARGET` bought 5 Empty Vials a trip, so each
vendor walk paid for five casts. `craft_supply.vial_target` stocks what the
herbs in hand will use, up to one stack.

Fixtures are the live rows read 2026-10-10 (character_skills, character_spell,
characters.money, item_instance).
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import craft  # noqa: E402
import craft_rhythm  # noqa: E402
import craft_supply  # noqa: E402
import guildjobs  # noqa: E402
import learnaim  # noqa: E402
import standin  # noqa: E402
import tradechoice  # noqa: E402
from towntrip import Town  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

TAILORING, ALCHEMY, ENCHANTING, HERBALISM = 197, 171, 333, 182
LINEN_BELT, LINEN_BAG, BOLT_OF_WOOL = 8776, 3755, 2964
LESSER_HEALING, HEALING_POTION, MINOR_HEALING = 2337, 3447, 2330
WOOL_CLOTH, BOLT_OF_WOOLEN = 2592, 2997
PEACEBLOOM, SILVERLEAF, EMPTY_VIAL = 2447, 765, 3371

# Og: level 38, 358,300 copper, Tailoring 81/150, Enchanting 1/75.
OG_SKILLS = {TAILORING: (81, 150), ENCHANTING: (1, 75)}
OG_KNOWN = frozenset({LINEN_BELT, LINEN_BAG})
OG_WANTED = (TAILORING, ENCHANTING)
# Ugga: level 39, 122,278 copper, Alchemy 39/75, Herbalism 164/225.
UGGA_WANTED = (ALCHEMY, HERBALISM)


def ugga(value, cap=150):
    return {ALCHEMY: (value, cap), HERBALISM: (164, 225)}


class AFamilyCrafterIsDueATrainerRecipe(unittest.TestCase):
    def test_og_at_81_is_due_bolt_of_woolen_cloth(self):
        self.assertEqual(
            (TAILORING,),
            guildjobs.recipes_due(38, 358300, OG_SKILLS, OG_KNOWN, OG_WANTED),
        )
        self.assertEqual(
            ((TAILORING, BOLT_OF_WOOL),),
            guildjobs.recipe_spells_due(38, 358300, OG_SKILLS, OG_KNOWN, OG_WANTED),
        )

    def test_holding_the_rung_is_nothing_due(self):
        self.assertEqual(
            (),
            guildjobs.recipes_due(
                38, 358300, OG_SKILLS, OG_KNOWN | {BOLT_OF_WOOL}, OG_WANTED
            ),
        )

    def test_an_auto_learned_rung_is_never_bought(self):
        # Minor Healing Potion comes with Apprentice Alchemy.
        self.assertEqual(
            (),
            guildjobs.recipes_due(39, 122278, ugga(39, 75), frozenset(), UGGA_WANTED),
        )

    def test_the_next_rung_is_bought_before_the_skill_reaches_it(self):
        # At 76 the ladder's next rung (Lesser Healing Potion, at 80) is within
        # RANK_UP_MARGIN, and the trainer teaches it from 55.
        self.assertEqual(
            (ALCHEMY,),
            guildjobs.recipes_due(39, 122278, ugga(76), frozenset(), UGGA_WANTED),
        )

    def test_a_rung_the_trainer_teaches_only_higher_up_waits(self):
        # Healing Potion is the rung from 110 and the trainer's ReqSkillRank is
        # 110: at 107, with Lesser Healing Potion held, nothing is bought yet.
        held = frozenset({LESSER_HEALING})
        self.assertEqual(
            (), guildjobs.recipes_due(39, 122278, ugga(107), held, UGGA_WANTED)
        )
        self.assertEqual(
            (ALCHEMY,), guildjobs.recipes_due(39, 122278, ugga(110), held, UGGA_WANTED)
        )

    def test_the_purse_must_cover_the_price_and_the_floor(self):
        # Healing Potion costs 4000c; mod-overseer never spends below 100c.
        held = frozenset({LESSER_HEALING})
        self.assertEqual(
            (), guildjobs.recipes_due(39, 4099, ugga(110), held, UGGA_WANTED)
        )
        self.assertEqual(
            (ALCHEMY,), guildjobs.recipes_due(39, 4100, ugga(110), held, UGGA_WANTED)
        )

    def test_a_trade_the_roster_does_not_name_is_left_alone(self):
        self.assertEqual(
            (), guildjobs.recipes_due(38, 358300, OG_SKILLS, OG_KNOWN, (ENCHANTING,))
        )

    def test_a_trade_not_held_is_left_alone(self):
        self.assertEqual(
            (),
            guildjobs.recipes_due(
                38, 358300, {TAILORING: (0, 0)}, frozenset(), OG_WANTED
            ),
        )

    def test_oz_is_due_the_linen_bag_his_bag_errand_names(self):
        # Oz: Tailoring 46/75, 117,069 copper, holds no tailoring recipe; the
        # trainer teaches Linen Bag from 45.
        self.assertEqual(
            (TAILORING,),
            guildjobs.recipes_due(
                29, 117069, {TAILORING: (46, 75)}, frozenset(), OG_WANTED
            ),
        )

    def test_every_ladder_rung_has_its_trainer_row(self):
        for skill, recipes in craft.RECIPES.items():
            for recipe in recipes:
                if recipe.spell_id in craft.AUTO_LEARNED:
                    continue
                with self.subTest(skill=skill, recipe=recipe.name):
                    self.assertIn(recipe.spell_id, craft.TRAINER_RECIPES)

    def test_the_crew_and_the_family_share_one_auto_learned_set(self):
        self.assertIs(craft.AUTO_LEARNED, guildjobs.AUTO_LEARNED)


class TheLearnErrandCarriesARecipe(unittest.TestCase):
    """learnaim reads a recipe that is due exactly like a rank that is due."""

    def row(self, **kw):
        base = dict(
            character="Og",
            wanted=OG_WANTED,
            traded=(TAILORING, ENCHANTING),
            settled=(TAILORING, ENCHANTING),
            ranks=(TAILORING,),
        )
        base.update(kw)
        return learnaim.Row(**base)

    def test_an_empty_column_gets_the_errand(self):
        plan = learnaim.plan([self.row()])
        self.assertEqual(("Og", TAILORING), plan.learn)

    def test_a_settled_first_learn_does_not_end_it(self):
        self.assertEqual("", learnaim.finished(self.row(learn_skill=TAILORING)))

    def test_the_other_family_gets_the_same_recipe_errand(self):
        rows = tradechoice.learn_rows(
            [
                {
                    "name": "Oz",
                    "lead": 1,
                    "professions": "197,333",
                    "learn_skill": 0,
                    "learn_spell": 0,
                }
            ],
            [],
            {"Oz": "197,333"},
            recipes={"Oz": ((TAILORING, LINEN_BAG),)},
        )
        self.assertEqual(("Oz", TAILORING, LINEN_BAG), learnaim.plan(rows).learn)

    def test_missing_recipe_names_the_exact_spell_and_survives_settled_trade(self):
        due = self.row(ranks=(), recipes=((TAILORING, BOLT_OF_WOOL),))
        plan = learnaim.plan([due])
        self.assertEqual(("Og", TAILORING, BOLT_OF_WOOL), plan.learn)
        sql, params = learnaim.statements(plan)[0]
        self.assertIn("learn_spell = %s", sql)
        self.assertEqual((TAILORING, BOLT_OF_WOOL, "Og"), params)
        self.assertEqual(
            "",
            learnaim.finished(
                self.row(
                    learn_skill=TAILORING,
                    learn_spell=BOLT_OF_WOOL,
                    ranks=(),
                    recipes=((TAILORING, BOLT_OF_WOOL),),
                )
            ),
        )

    def test_a_clear_cannot_erase_a_new_recipe_for_the_same_trade(self):
        row = self.row(
            learn_skill=TAILORING, learn_spell=BOLT_OF_WOOL, ranks=(), recipes=()
        )
        sql, params = learnaim.statements(learnaim.plan([row]))[0]
        self.assertIn("AND learn_spell = %s", sql)
        self.assertEqual(("Og", TAILORING, BOLT_OF_WOOL), params)


class TheCraftErrandNamesOnlyAHeldRung(unittest.TestCase):
    OG = {"tailoring": 81, "enchanting": 1}
    TRADES = ("tailoring", "enchanting")
    WOOL = {WOOL_CLOTH: 40}

    def test_plain_craft_errand_waits_for_the_recipe_purchase(self):
        self.assertEqual(
            0, craft.craft_errand("Og", self.OG, self.TRADES, known=OG_KNOWN)
        )
        self.assertEqual(
            BOLT_OF_WOOL,
            craft.craft_errand(
                "Og", self.OG, self.TRADES, known=OG_KNOWN | {BOLT_OF_WOOL}
            ),
        )

    def test_og_is_not_aimed_at_a_recipe_he_does_not_hold(self):
        chosen = craft_rhythm.errand(
            "Og", self.OG, self.WOOL, self.TRADES, known=OG_KNOWN
        )
        self.assertNotEqual(BOLT_OF_WOOL, chosen.spell)
        self.assertIn("Bolt of Woolen Cloth (2964)", chosen.why)
        self.assertIn("trainer", chosen.why)

    def test_once_held_he_weaves_it(self):
        chosen = craft_rhythm.errand(
            "Og", self.OG, self.WOOL, self.TRADES, known=OG_KNOWN | {BOLT_OF_WOOL}
        )
        self.assertEqual(BOLT_OF_WOOL, chosen.spell)

    def test_an_unread_spellbook_changes_nothing(self):
        chosen = craft_rhythm.errand("Og", self.OG, self.WOOL, self.TRADES)
        self.assertEqual(BOLT_OF_WOOL, chosen.spell)

    def test_the_guild_bag_weave_names_only_a_held_bolt(self):
        # "Og weaves Bolt of Woolen Cloth toward a Woolen Bag".
        chosen = craft_rhythm.errand(
            "Og", self.OG, self.WOOL, self.TRADES, floor=6, known=OG_KNOWN
        )
        self.assertNotIn(chosen.spell, (BOLT_OF_WOOL, 3757))

    def test_oz_does_not_sew_a_linen_bag_he_does_not_hold(self):
        chosen = craft_rhythm.errand(
            "Oz",
            {"tailoring": 46, "enchanting": 1},
            {2996: 10, 2589: 375},
            self.TRADES,
            bags_wanted=2,
            known=frozenset(),
        )
        self.assertNotEqual(LINEN_BAG, chosen.spell)

    def test_oz_sews_it_once_held(self):
        chosen = craft_rhythm.errand(
            "Oz",
            {"tailoring": 46, "enchanting": 1},
            {2996: 10, 2589: 375},
            self.TRADES,
            bags_wanted=2,
            known=frozenset({LINEN_BAG}),
        )
        self.assertEqual(LINEN_BAG, chosen.spell)


class TheStandInSaysTheTrainerBuysIt(unittest.TestCase):
    def test_the_wall_names_the_walk_not_a_refusal(self):
        sys.path.insert(0, str(HERE / "tests"))
        from test_standin import facts

        why = standin.sits_out(
            facts(skills={"tailoring": 81, "enchanting": 1}, known=OG_KNOWN)
        )
        self.assertIn("Bolt of Woolen Cloth (2964)", why)
        self.assertNotIn("cannot buy", why)
        self.assertIn("trainer", why)


class VialsForTheHerbsInHand(unittest.TestCase):
    TOWN = Town(stocks=frozenset({EMPTY_VIAL}))

    def test_ugga_stocks_a_stack_for_27_casts_of_herbs(self):
        # 30 Peacebloom and 27 Silverleaf: 27 Minor Healing Potions.
        self.assertEqual(20, craft_supply.vial_target(MINOR_HEALING, 27))

    def test_a_few_herbs_still_keep_the_standing_five(self):
        self.assertEqual(
            craft_supply.TARGET, craft_supply.vial_target(MINOR_HEALING, 2)
        )

    def test_between_the_two_it_buys_what_the_herbs_use(self):
        self.assertEqual(12, craft_supply.vial_target(MINOR_HEALING, 12))

    def test_an_unjudged_recipe_keeps_the_standing_five(self):
        self.assertEqual(
            craft_supply.TARGET, craft_supply.vial_target(MINOR_HEALING, None)
        )

    def test_the_errand_buys_to_the_target(self):
        errand, note = craft_supply.reagent_errand(
            "Ugga", MINOR_HEALING, 0, 122278, 4, self.TOWN, target=20
        )
        self.assertIsNone(note)
        self.assertIn("count:20", errand.command)

    def test_a_walk_is_still_only_for_a_shortage(self):
        # The top-up is bought where vials are sold; a walk is for fewer than
        # the standing five, as before.
        town = Town(stocks=frozenset())
        self.assertIsNone(craft_supply.reagent_need("Ugga", MINOR_HEALING, 6, town))
        self.assertIsNotNone(craft_supply.reagent_need("Ugga", MINOR_HEALING, 4, town))
        self.assertEqual(
            (None, None),
            craft_supply.reagent_errand(
                "Ugga", MINOR_HEALING, 6, 122278, 4, town, target=20
            ),
        )


class TheBridgeWiresIt(unittest.TestCase):
    def test_the_learn_rows_carry_recipes_due(self):
        self.assertIn("guildjobs.recipe_spells_due(", BRIDGE)

    def test_the_craft_pass_reads_the_spellbook(self):
        self.assertTrue("known=known.get(name)" in BRIDGE, "known=known.get(name)")

    def test_the_vial_buy_reads_the_herbs(self):
        self.assertTrue(
            "craft_supply.vial_target(" in BRIDGE, "craft_supply.vial_target("
        )


if __name__ == "__main__":
    unittest.main()
