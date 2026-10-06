"""The family levels First Aid from its cloth and buys its next trade rank.

WHAT WAS SEEN (wow-dev, 2026-10-05). Every member of both families read First
Aid 1/75 in the raidcraft line while the guild crew climbed it. The second
family carried 83 to 355 Linen Cloth each. `craft.craft_errand` answers a
secondary only when no primary recipe exists, and every family member holds a
primary with a recipe at every value, so `craft_spell` was always the
primary's: a member out of its own reagent stood casting nothing with a Linen
Bandage's cloth in its bags.

THE RANKS. The crew buys a rank with `walk-to-trainer skill:`, which
mod-overseer refuses for a roster character. A family member's rank is bought
through the roster's own learn errand (`learn_skill`, TrainOnArrival), and
which rank is due is the crew's rule, guildjobs.ranks_due over guildjobs.RANKS.
Artisan First Aid (10847) and Artisan Tailoring (12181) are the realm's own
`trainer_spell` rows, verified against its Spell.dbc.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import craft_rhythm  # noqa: E402
import guildjobs  # noqa: E402
import learnaim  # noqa: E402
import tradechoice  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

FIRST_AID = 129
TAILORING = 197
ENCHANTING = 333
BLACKSMITHING = 164
MINING = 186
LINEN = 2589
ROUGH_STONE = 2835
LINEN_BANDAGE = 3275
ROUGH_SHARPENING_STONE = 2660
BOLT_OF_LINEN = 2963

# A family blacksmith as measured: Blacksmithing 5, Mining held, First Aid 1,
# 163 Linen Cloth and no Rough Stone.
SMITH = {"blacksmithing": 5, "mining": 1, "first aid": 1, "cooking": 1, "fishing": 1}
SMITH_TRADES = ("blacksmithing", "mining")
TAILOR = {"tailoring": 50, "enchanting": 1, "first aid": 1, "cooking": 1}
TAILOR_TRADES = ("enchanting", "tailoring")


class TheFamilyBandagesWhileItsCraftCannotRun(unittest.TestCase):
    def test_a_smith_out_of_stone_with_linen_makes_linen_bandages(self):
        chosen = craft_rhythm.errand(
            "Zug", SMITH, {LINEN: 163, ROUGH_STONE: 0}, SMITH_TRADES
        )
        self.assertEqual(LINEN_BANDAGE, chosen.spell)
        self.assertFalse(chosen.smelting)
        self.assertIn("First Aid", chosen.why)

    def test_a_smith_with_stone_keeps_its_craft(self):
        chosen = craft_rhythm.errand(
            "Zug", SMITH, {LINEN: 163, ROUGH_STONE: 4}, SMITH_TRADES
        )
        self.assertEqual(ROUGH_SHARPENING_STONE, chosen.spell)

    def test_no_cloth_keeps_the_craft_errand_standing(self):
        chosen = craft_rhythm.errand(
            "Zug", SMITH, {LINEN: 0, ROUGH_STONE: 0}, SMITH_TRADES
        )
        self.assertEqual(ROUGH_SHARPENING_STONE, chosen.spell)

    def test_a_smelt_is_not_replaced(self):
        chosen = craft_rhythm.errand(
            "Zug", SMITH, {LINEN: 50, ROUGH_STONE: 0, 2770: 6}, SMITH_TRADES
        )
        self.assertTrue(chosen.smelting)

    def test_a_tailor_keeps_the_cloth_its_bolt_eats(self):
        chosen = craft_rhythm.errand("Og", TAILOR, {LINEN: 1}, TAILOR_TRADES)
        self.assertNotEqual(LINEN_BANDAGE, chosen.spell)

    def test_no_bandage_past_linen_bandages_grey(self):
        skills = dict(SMITH, **{"first aid": 60})
        chosen = craft_rhythm.errand(
            "Zug", skills, {LINEN: 163, ROUGH_STONE: 0}, SMITH_TRADES
        )
        self.assertEqual(ROUGH_SHARPENING_STONE, chosen.spell)

    def test_the_cloth_is_counted_before_the_choice(self):
        wanted = craft_rhythm.reagents_to_count("Zug", SMITH, SMITH_TRADES)
        self.assertIn(LINEN, wanted)
        self.assertIn(ROUGH_STONE, wanted)

    def test_a_family_on_cloth_alone_reads_stocked_and_crafts(self):
        held = {LINEN: 163, ROUGH_STONE: 0}
        chosen = craft_rhythm.errand("Zug", SMITH, held, SMITH_TRADES)
        stand = craft_rhythm.stand(
            "Zug",
            chosen.spell,
            {r.entry: held.get(r.entry, 0) for r in craft_rhythm.feeds(chosen.spell)},
        )
        self.assertEqual(craft_rhythm.STOCKED, stand.verdict)
        plan = craft_rhythm.rhythm([stand], craft_rhythm.MODE_GATHER)
        self.assertEqual(craft_rhythm.MODE_CRAFT, plan.mode)


class TheArtisanRanks(unittest.TestCase):
    def test_artisan_first_aid_is_the_rank_at_200(self):
        self.assertEqual(10847, guildjobs.next_rank(FIRST_AID, 222, 225, 35).spell)
        self.assertIsNone(guildjobs.next_rank(FIRST_AID, 222, 225, 34))

    def test_artisan_tailoring_is_the_rank_at_200(self):
        self.assertEqual(12181, guildjobs.next_rank(TAILORING, 221, 225, 35).spell)
        self.assertEqual(300, guildjobs.next_rank(TAILORING, 221, 225, 35).cap)

    def test_the_tailoring_ladder_is_journeyman_expert_artisan(self):
        self.assertEqual(3912, guildjobs.next_rank(TAILORING, 72, 75, 10).spell)
        self.assertEqual(3913, guildjobs.next_rank(TAILORING, 146, 150, 20).spell)


class RanksDue(unittest.TestCase):
    def test_a_tailor_at_its_ceiling_is_due_expert(self):
        due = guildjobs.ranks_due(
            38, 60000, {TAILORING: (146, 150), FIRST_AID: (1, 75)}, (TAILORING,)
        )
        self.assertEqual((TAILORING,), due)

    def test_a_tailor_far_from_its_ceiling_is_due_nothing(self):
        self.assertEqual(
            (), guildjobs.ranks_due(38, 60000, {TAILORING: (50, 150)}, (TAILORING,))
        )

    def test_a_short_purse_waits(self):
        self.assertEqual(
            (), guildjobs.ranks_due(38, 4999, {TAILORING: (146, 150)}, (TAILORING,))
        )

    def test_a_primary_the_roster_does_not_name_is_never_due(self):
        self.assertEqual(
            (), guildjobs.ranks_due(38, 60000, {TAILORING: (146, 150)}, (ENCHANTING,))
        )

    def test_first_aid_needs_no_permission(self):
        self.assertEqual(
            (FIRST_AID,), guildjobs.ranks_due(10, 600, {FIRST_AID: (72, 75)}, ())
        )

    def test_an_unheld_trade_is_never_started(self):
        self.assertEqual(
            (), guildjobs.ranks_due(38, 60000, {TAILORING: (0, 0)}, (TAILORING,))
        )

    def test_cheapest_first(self):
        due = guildjobs.ranks_due(
            38,
            60000,
            {TAILORING: (146, 150), FIRST_AID: (72, 75)},
            (TAILORING,),
        )
        self.assertEqual((FIRST_AID, TAILORING), due)


def row(character, **kw):
    return learnaim.Row(character=character, **kw)


class TheRankErrand(unittest.TestCase):
    def test_a_due_rank_is_written_onto_an_empty_column(self):
        rows = [
            row("Grug", leads=True, wanted=(BLACKSMITHING, MINING)),
            row("Og", wanted=(ENCHANTING, TAILORING), ranks=(TAILORING,)),
        ]
        plan = learnaim.plan(rows)
        self.assertEqual(("Og", TAILORING), plan.learn)
        sql = learnaim.statements(plan)
        self.assertEqual(1, len(sql))
        self.assertIn("SET learn_skill = %s", sql[0][0])
        self.assertIn("learn_skill = 0 AND unlearn_skill = 0", sql[0][0])
        self.assertEqual((TAILORING, "Og"), sql[0][1])
        self.assertIn("Og", learnaim.report(plan))

    def test_the_leaders_rank_comes_first(self):
        rows = [
            row("Bork", ranks=(FIRST_AID,)),
            row("Og", leads=True, ranks=(TAILORING,)),
        ]
        self.assertEqual(("Og", TAILORING), learnaim.plan(rows).learn)

    def test_nothing_is_written_while_an_errand_is_outstanding(self):
        rows = [
            row(
                "Grug",
                leads=True,
                learn_skill=MINING,
                wanted=(MINING,),
                travel_npc="profession trainer",
            ),
            row("Og", wanted=(TAILORING,), ranks=(TAILORING,)),
        ]
        self.assertEqual((), learnaim.plan(rows).learn)

    def test_a_settled_first_learn_does_not_end_a_rank_errand(self):
        r = row(
            "Og",
            learn_skill=TAILORING,
            wanted=(ENCHANTING, TAILORING),
            traded=(TAILORING,),
            settled=(TAILORING,),
            ranks=(TAILORING,),
        )
        self.assertEqual("", learnaim.finished(r))
        self.assertEqual(TAILORING, learnaim.outstanding(r))
        self.assertTrue(learnaim.derived(r))

    def test_a_due_first_aid_rank_is_not_lifted_as_a_secondary(self):
        r = row("Bork", learn_skill=FIRST_AID, wanted=(165, 393), ranks=(FIRST_AID,))
        self.assertEqual("", learnaim.finished(r))

    def test_a_first_aid_errand_nobody_decided_is_still_lifted(self):
        r = row("Bork", learn_skill=FIRST_AID, wanted=(165, 393))
        self.assertEqual(learnaim.SECONDARY, learnaim.finished(r))

    def test_the_written_errand_is_walked_by_its_leader_next(self):
        r = row(
            "Og",
            leads=True,
            learn_skill=TAILORING,
            wanted=(TAILORING,),
            traded=(TAILORING,),
            settled=(TAILORING,),
            ranks=(TAILORING,),
        )
        plan = learnaim.plan([r])
        self.assertEqual("Og", plan.aim)
        self.assertEqual("Og", learnaim.traveller([r]))

    def test_another_family_carries_its_ranks(self):
        rows = tradechoice.learn_rows(
            [{"name": "Oz", "lead": 0, "professions": "197,333", "learn_skill": 0}],
            [],
            {},
            {"Oz": (TAILORING,)},
        )
        self.assertEqual((TAILORING,), rows[0].ranks)


class TheBridgeReadsTheRanks(unittest.TestCase):
    def test_both_learn_row_builders_carry_ranks(self):
        self.assertIn("ranks = _ranks_due(cur, roster)", BRIDGE)
        self.assertIn('ranks=ranks.get(row["name"], ())', BRIDGE)
        self.assertIn('state.get("ranks")', BRIDGE)

    def test_the_rank_facts_come_from_the_rank_table(self):
        self.assertIn("sorted(guildjobs.RANKS)", BRIDGE)
        self.assertIn("guildjobs.ranks_due(", BRIDGE)

    def test_a_campaign_writes_no_rank_errand(self):
        self.assertIn('aim="", skill=0, learn=()', BRIDGE)


if __name__ == "__main__":
    unittest.main()
