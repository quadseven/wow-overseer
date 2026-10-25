"""The Dark Iron road: plans, reputation, the Black Forge and the Black Anvil.

#480. `fireplan` names a tank's Dark Iron pieces as upgrades and `raidsupply`
called them plans nobody holds. This suite pins the road between those two
sentences: the reputation gate Lokhtos sells each plan behind, the plan
purchase, the smelt learned from The Spectral Chalice, the bars made at the
Black Forge, and the piece made at the Black Anvil.

WHAT THIS PINS THAT A LIVE RUN CANNOT. None of these gates fails loudly in the
world. A plan bought at the wrong rank is simply absent from the vendor's list;
a smelt cast at an ordinary forge returns a numeric `SpellCastResult` and no
bar; a craft at the wrong anvil does the same. The order is the whole
pipeline, so the order is what is tested.

THE ITEM BOOK'S SKILL NUMBERS ARE NOT CLASSIC. It gives these plans 315 and
320, and the classic cap is 300. The module says so rather than trusting the
number; the realm's own item_template is the authority.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import darkiron  # noqa: E402


def item_book() -> dict:
    with (ROOT / "data" / "bis" / "items.json").open() as fh:
        return json.load(fh)["items"]


class PlanTableTests(unittest.TestCase):
    def test_every_plan_makes_a_piece_the_item_book_knows(self):
        book = item_book()
        for plan in darkiron.PLANS:
            with self.subTest(plan=plan.name):
                row = book.get(str(plan.piece))
                self.assertIsNotNone(row, plan.piece_name)
                self.assertEqual(row["name"], plan.piece_name)
                self.assertEqual(row["fire_res"], plan.fire)
                self.assertLessEqual(row["req"], 60)

    def test_every_plan_teaches_the_spell_the_item_book_gives_the_piece(self):
        book = item_book()
        for plan in darkiron.PLANS:
            with self.subTest(plan=plan.name):
                crafts = [
                    s
                    for s in book[str(plan.piece)]["sources"]
                    if s.get("type") == "craft"
                ]
                self.assertEqual([s["spell"] for s in crafts], [plan.teaches])

    def test_the_plans_are_in_reputation_order(self):
        ranks = [darkiron.rank_index(p.rank) for p in darkiron.PLANS]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(ranks[0], darkiron.rank_index(darkiron.FRIENDLY))
        self.assertEqual(ranks[-1], darkiron.rank_index(darkiron.EXALTED))

    def test_every_plan_is_sold_at_a_rank_on_the_ladder(self):
        for plan in darkiron.PLANS:
            with self.subTest(plan=plan.name):
                self.assertIn(plan.rank, darkiron.RANK_VALUE)
                self.assertGreater(plan.bars, 0)
                self.assertTrue(plan.reagents)

    def test_the_turn_ins_are_ore_cores_leather_and_blood(self):
        self.assertEqual(
            [q for q, _needs in darkiron.TURNINS],
            [6642, 6643, 6644, 6645, 6646],
        )
        entries = {entry for _q, needs in darkiron.TURNINS for entry, _count in needs}
        self.assertEqual(
            entries,
            {
                darkiron.DARK_IRON_ORE,
                darkiron.FIERY_CORE,
                darkiron.LAVA_CORE,
                darkiron.CORE_LEATHER,
                darkiron.BLOOD_OF_THE_MOUNTAIN,
            },
        )
        for _q, needs in darkiron.TURNINS:
            for entry, count in needs:
                with self.subTest(entry=entry):
                    self.assertIn(entry, darkiron.ITEM_NAMES)
                    self.assertGreater(count, 0)

    def test_the_item_book_skill_is_past_the_classic_cap(self):
        book = item_book()
        for plan in darkiron.PLANS:
            with self.subTest(plan=plan.name):
                crafts = [
                    s
                    for s in book[str(plan.piece)]["sources"]
                    if s.get("type") == "craft"
                ]
                self.assertGreater(crafts[0]["skill"], darkiron.CLASSIC_SKILL)
        self.assertIn("300", darkiron.skill_note())


class PipelineTests(unittest.TestCase):
    def test_a_neutral_guild_is_sent_to_friendly_first(self):
        pipe = darkiron.plan()
        self.assertEqual(pipe.step.kind, darkiron.GRIND)
        self.assertEqual(pipe.plan.rank, darkiron.FRIENDLY)
        self.assertIn("Friendly", pipe.step.said)
        self.assertIn("Dark Iron Ore", pipe.step.said)
        self.assertIn("Plans: Dark Iron Bracers", pipe.step.said)

    def test_the_grind_names_the_furthest_rank_the_first_plan_needs(self):
        pipe = darkiron.plan(known=(17051,), made=(17014,))
        self.assertEqual(pipe.step.kind, darkiron.GRIND)
        self.assertEqual(pipe.plan.rank, darkiron.HONORED)
        self.assertIn("Honored", pipe.step.said)

    def test_friendly_buys_the_bracers_plan(self):
        pipe = darkiron.plan(rank=darkiron.FRIENDLY)
        self.assertEqual(pipe.step.kind, darkiron.BUY)
        self.assertEqual(pipe.plan.entry, 17051)
        self.assertIn("Lokhtos", pipe.step.said)
        self.assertIn("Friendly", pipe.step.said)

    def test_a_known_plan_still_has_to_learn_the_smelt(self):
        pipe = darkiron.plan(known=(17051,), rank=darkiron.FRIENDLY)
        self.assertEqual(pipe.step.kind, darkiron.LEARN)
        self.assertEqual(pipe.step.plan.piece, 17014)
        self.assertIn("Spectral Chalice", pipe.step.said)
        self.assertIn("Mining 230", pipe.step.said)
        self.assertIn("Star Ruby", pipe.step.said)

    def test_the_smelt_asks_for_the_ore_the_bars_need(self):
        pipe = darkiron.plan(known=(17051,), rank=darkiron.FRIENDLY, smelt_known=True)
        self.assertEqual(pipe.step.kind, darkiron.SMELT)
        self.assertIn("4 Dark Iron Bars", pipe.step.said)
        self.assertIn("32 Dark Iron Ore", pipe.step.said)
        self.assertIn("Black Forge", pipe.step.said)

    def test_held_bars_skip_the_smelt(self):
        pipe = darkiron.plan(
            known=(17051,),
            rank=darkiron.FRIENDLY,
            smelt_known=True,
            held={darkiron.DARK_IRON_BAR: 4},
        )
        self.assertEqual(pipe.step.kind, darkiron.GATHER)
        self.assertIn("2 Fiery Core", pipe.step.said)
        self.assertIn("2 Lava Core", pipe.step.said)

    def test_all_the_reagents_make_the_piece_at_the_black_anvil(self):
        pipe = darkiron.plan(
            known=(17051,),
            rank=darkiron.FRIENDLY,
            smelt_known=True,
            held={
                darkiron.DARK_IRON_BAR: 4,
                darkiron.FIERY_CORE: 2,
                darkiron.LAVA_CORE: 2,
            },
        )
        self.assertEqual(pipe.step.kind, darkiron.CRAFT)
        self.assertIn("Dark Iron Bracers", pipe.step.said)
        self.assertIn("Black Anvil", pipe.step.said)

    def test_a_made_piece_moves_the_pipeline_on(self):
        pipe = darkiron.plan(
            known=(17051,),
            rank=darkiron.HONORED,
            made=(17014,),
        )
        self.assertEqual(pipe.plan.entry, 19206)
        self.assertEqual(pipe.step.kind, darkiron.BUY)

    def test_every_plan_made_is_done(self):
        pipe = darkiron.plan(
            known=[p.entry for p in darkiron.PLANS],
            rank=darkiron.EXALTED,
            made=[p.piece for p in darkiron.PLANS],
        )
        self.assertTrue(pipe.done)
        self.assertIn("every piece is made", pipe.line)

    def test_points_and_names_reach_the_same_rank(self):
        self.assertEqual(darkiron.rank_of(3000), darkiron.FRIENDLY)
        self.assertEqual(darkiron.rank_of(8999), darkiron.FRIENDLY)
        self.assertEqual(darkiron.rank_of(9000), darkiron.HONORED)
        self.assertEqual(darkiron.rank_of(42000), darkiron.EXALTED)


class SaidTests(unittest.TestCase):
    def test_a_piece_names_its_plan_and_rank_for_the_fire_plan(self):
        said = darkiron.source(19148)
        self.assertIn("Plans: Dark Iron Helm", said)
        self.assertIn("Honored", said)
        self.assertIn("Black Anvil", said)

    def test_a_piece_this_module_does_not_know_has_no_road(self):
        self.assertEqual(darkiron.source(12345), "")

    def test_the_road_names_the_place_the_rank_and_the_anvil(self):
        for word in ("Lokhtos", "Thorium Brotherhood", "Black Forge", "Black Anvil"):
            self.assertIn(word, darkiron.ROAD)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("darkiron.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
