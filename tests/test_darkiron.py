"""The Dark Iron road: plans, reputation, the Black Forge and the Black Anvil.

#480. `fireplan` names a tank's Dark Iron pieces as upgrades and `raidsupply`
called them plans nobody holds. This suite pins the road (it lives in fireplan) between those two
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

import fireplan  # noqa: E402


def item_book() -> dict:
    with (ROOT / "data" / "bis" / "items.json").open() as fh:
        return json.load(fh)["items"]


class PlanTableTests(unittest.TestCase):
    def test_every_plan_makes_a_piece_the_item_book_knows(self):
        book = item_book()
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                row = book.get(str(plan.piece))
                self.assertIsNotNone(row, plan.piece_name)
                self.assertEqual(row["name"], plan.piece_name)
                self.assertEqual(row["fire_res"], plan.fire)
                self.assertLessEqual(row["req"], 60)

    def test_every_plan_teaches_the_spell_the_item_book_gives_the_piece(self):
        book = item_book()
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                crafts = [
                    s
                    for s in book[str(plan.piece)]["sources"]
                    if s.get("type") == "craft"
                ]
                self.assertEqual([s["spell"] for s in crafts], [plan.teaches])

    def test_the_plans_are_in_reputation_order(self):
        ranks = [fireplan.rank_index(p.rank) for p in fireplan.PLANS]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(ranks[0], fireplan.rank_index(fireplan.FRIENDLY))
        self.assertEqual(ranks[-1], fireplan.rank_index(fireplan.EXALTED))

    def test_every_plan_is_sold_at_a_rank_on_the_ladder(self):
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                self.assertIn(plan.rank, fireplan.RANK_VALUE)
                self.assertGreater(plan.bars, 0)
                self.assertTrue(plan.reagents)

    def test_the_turn_ins_are_ore_cores_leather_and_blood(self):
        self.assertEqual(
            [q for q, _needs in fireplan.TURNINS],
            [6642, 6643, 6644, 6645, 6646],
        )
        entries = {entry for _q, needs in fireplan.TURNINS for entry, _count in needs}
        self.assertEqual(
            entries,
            {
                fireplan.DARK_IRON_ORE,
                fireplan.FIERY_CORE,
                fireplan.LAVA_CORE,
                fireplan.CORE_LEATHER,
                fireplan.BLOOD_OF_THE_MOUNTAIN,
            },
        )
        for _q, needs in fireplan.TURNINS:
            for entry, count in needs:
                with self.subTest(entry=entry):
                    self.assertIn(entry, fireplan.ITEM_NAMES)
                    self.assertGreater(count, 0)

    def test_the_item_book_skill_is_past_the_classic_cap(self):
        book = item_book()
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                crafts = [
                    s
                    for s in book[str(plan.piece)]["sources"]
                    if s.get("type") == "craft"
                ]
                self.assertGreater(crafts[0]["skill"], fireplan.CLASSIC_SKILL)
        self.assertIn("300", fireplan.skill_note())


class PipelineTests(unittest.TestCase):
    def test_a_neutral_guild_is_sent_to_friendly_first(self):
        pipe = fireplan.iron_plan()
        self.assertEqual(pipe.step.kind, fireplan.GRIND)
        self.assertEqual(pipe.plan.rank, fireplan.FRIENDLY)
        self.assertIn("Friendly", pipe.step.said)
        self.assertIn("Dark Iron Ore", pipe.step.said)
        self.assertIn("Plans: Dark Iron Bracers", pipe.step.said)

    def test_the_grind_names_the_furthest_rank_the_first_plan_needs(self):
        pipe = fireplan.iron_plan(known=(17051,), made=(17014,))
        self.assertEqual(pipe.step.kind, fireplan.GRIND)
        self.assertEqual(pipe.plan.rank, fireplan.HONORED)
        self.assertIn("Honored", pipe.step.said)

    def test_friendly_buys_the_bracers_plan(self):
        pipe = fireplan.iron_plan(rank=fireplan.FRIENDLY)
        self.assertEqual(pipe.step.kind, fireplan.BUY)
        self.assertEqual(pipe.plan.entry, 17051)
        self.assertIn("Lokhtos", pipe.step.said)
        self.assertIn("Friendly", pipe.step.said)

    def test_a_known_plan_still_has_to_learn_the_smelt(self):
        pipe = fireplan.iron_plan(known=(17051,), rank=fireplan.FRIENDLY)
        self.assertEqual(pipe.step.kind, fireplan.LEARN)
        self.assertEqual(pipe.step.plan.piece, 17014)
        self.assertIn("Spectral Chalice", pipe.step.said)
        self.assertIn("Mining 230", pipe.step.said)
        self.assertIn("Star Ruby", pipe.step.said)

    def test_the_smelt_asks_for_the_ore_the_bars_need(self):
        pipe = fireplan.iron_plan(
            known=(17051,), rank=fireplan.FRIENDLY, smelt_known=True
        )
        self.assertEqual(pipe.step.kind, fireplan.SMELT)
        self.assertIn("4 Dark Iron Bars", pipe.step.said)
        self.assertIn("32 Dark Iron Ore", pipe.step.said)
        self.assertIn("Black Forge", pipe.step.said)

    def test_held_bars_skip_the_smelt(self):
        pipe = fireplan.iron_plan(
            known=(17051,),
            rank=fireplan.FRIENDLY,
            smelt_known=True,
            held={fireplan.DARK_IRON_BAR: 4},
        )
        self.assertEqual(pipe.step.kind, fireplan.GATHER)
        self.assertIn("2 Fiery Core", pipe.step.said)
        self.assertIn("2 Lava Core", pipe.step.said)

    def test_all_the_reagents_make_the_piece_at_the_black_anvil(self):
        pipe = fireplan.iron_plan(
            known=(17051,),
            rank=fireplan.FRIENDLY,
            smelt_known=True,
            held={
                fireplan.DARK_IRON_BAR: 4,
                fireplan.FIERY_CORE: 2,
                fireplan.LAVA_CORE: 2,
            },
        )
        self.assertEqual(pipe.step.kind, fireplan.CRAFT)
        self.assertIn("Dark Iron Bracers", pipe.step.said)
        self.assertIn("Black Anvil", pipe.step.said)

    def test_a_made_piece_moves_the_pipeline_on(self):
        pipe = fireplan.iron_plan(
            known=(17051,),
            rank=fireplan.HONORED,
            made=(17014,),
        )
        self.assertEqual(pipe.plan.entry, 19206)
        self.assertEqual(pipe.step.kind, fireplan.BUY)

    def test_every_plan_made_is_done(self):
        pipe = fireplan.iron_plan(
            known=[p.entry for p in fireplan.PLANS],
            rank=fireplan.EXALTED,
            made=[p.piece for p in fireplan.PLANS],
        )
        self.assertTrue(pipe.done)
        self.assertIn("every piece is made", pipe.line)


class SaidTests(unittest.TestCase):
    def test_a_piece_names_its_plan_and_rank_for_the_fire_plan(self):
        said = fireplan.iron_source(19148)
        self.assertIn("Plans: Dark Iron Helm", said)
        self.assertIn("Honored", said)
        self.assertIn("Black Anvil", said)

    def test_a_piece_this_module_does_not_know_has_no_road(self):
        self.assertEqual(fireplan.iron_source(12345), "")

    def test_the_road_names_the_place_the_rank_and_the_anvil(self):
        for word in ("Lokhtos", "Thorium Brotherhood", "Black Forge", "Black Anvil"):
            self.assertIn(word, fireplan.IRON_ROAD)

    def test_the_road_says_the_first_step_and_the_skill_note(self):
        self.assertIn(fireplan.iron_plan().line, fireplan.IRON_ROAD)
        self.assertIn(fireplan.skill_note(), fireplan.IRON_ROAD)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("fireplan.py", dockerfile)


class ErrandTests(unittest.TestCase):
    def test_a_blacksmith_with_no_plans_and_neutral_standing_is_sent_to_grind(self):
        pipe, errand = fireplan.iron_member("Smith", set(), 0, {})
        self.assertEqual(pipe.step.kind, fireplan.GRIND)
        self.assertEqual(errand.kind, "quest")
        self.assertEqual(errand.member, "Smith")
        self.assertEqual(errand.command, "take quest:%d" % fireplan.TURNINS[0][0])

    def test_a_member_holding_a_turnin_hands_it_in(self):
        _pipe, errand = fireplan.iron_member(
            "Smith", set(), 0, {fireplan.FIERY_CORE: 1}
        )
        self.assertEqual(errand.command, "turnin quest:6643")

    def test_a_member_at_rank_buys_the_plan(self):
        _pipe, errand = fireplan.iron_member("Smith", set(), 3000, {})
        self.assertEqual(errand.kind, "buy")
        self.assertIn("entry:17051 ", errand.command)

    def test_a_step_with_no_command_kind_queues_nothing(self):
        learned = {fireplan.PLANS[0].teaches}
        pipe, errand = fireplan.iron_member("Smith", learned, 3000, {})
        self.assertEqual(pipe.step.kind, fireplan.LEARN)
        self.assertIsNone(errand)

    def test_the_log_line_names_the_member_and_the_step(self):
        pipe, _errand = fireplan.iron_member("Smith", set(), 0, {})
        self.assertEqual(
            fireplan.iron_log("Smith", pipe),
            "dark iron: Smith step grind: " + pipe.step.said,
        )

    def test_the_bridge_plans_it_from_the_craft_supply_pass(self):
        src = (ROOT / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("await self._dark_iron_once(names)", src)
        self.assertIn("fireplan.iron_member(", src)
        self.assertIn("fireplan.iron_log(", src)


if __name__ == "__main__":
    unittest.main()
