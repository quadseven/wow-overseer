"""A crafter's feed has somewhere to land (#2502).

The reagents exist but cannot land: a crafter's wool sits in the mailbox, its
vials in the bank and its stone in the guild bank, while the bags are full.
These tests hold the four parts of the fix: the reagent plan counts the slots
its fetched reagents need, the item plan makes that room first, a reagent
stack goes to its crafter and not to a bank, and the bank pass fetches a
crafter's reagent only once the deposits that make room are in the same plan
and ahead of it.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bank  # noqa: E402
import itemplan  # noqa: E402
import itemplan_route  # noqa: E402
import itemplan_shadow  # noqa: E402
import reagentplan  # noqa: E402
from test_itemplan import (  # noqa: E402
    DRUID,
    TAILORING,
    decide,
    member,
    stack,
)

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
EMPTY_VIAL, PEACEBLOOM, SILVERLEAF = 3371, 2447, 765
MINOR_HEALING_POTION = 2330


def _body(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == name
        ):
            return ast.get_source_segment(BRIDGE, node)
    raise AssertionError("%s not found in bridge.py" % name)


class TheReagentPlanCountsTheRoomItsFetchNeeds(unittest.TestCase):
    def _plan(self, **places):
        return reagentplan.plan(
            "Uzza",
            MINOR_HEALING_POTION,
            {
                PEACEBLOOM: reagentplan.Stock(bags=20),
                SILVERLEAF: reagentplan.Stock(bags=20),
                EMPTY_VIAL: reagentplan.Stock(**places),
            },
            {},
            {},
        )

    def test_a_short_reagent_in_the_bank_needs_a_slot(self):
        got = reagentplan.inbound_slots([self._plan(bank=34)])
        self.assertEqual({"Uzza": 1}, got)

    def test_the_mailbox_and_the_guild_bank_count_too(self):
        self.assertEqual({"Uzza": 1}, reagentplan.inbound_slots([self._plan(mail=34)]))
        self.assertEqual(
            {"Uzza": 1}, reagentplan.inbound_slots([self._plan(guild_bank=34)])
        )

    def test_a_reagent_bought_or_gathered_needs_no_room_made_ahead(self):
        # Nothing holds the vials: a vendor sells them, so the errand buys.
        self.assertEqual({}, reagentplan.inbound_slots([self._plan()]))

    def test_an_unjudged_plan_or_no_plan_names_nothing(self):
        unjudged = reagentplan.plan("Uzza", 1, {}, {}, {})
        self.assertEqual({}, reagentplan.inbound_slots([unjudged]))
        self.assertEqual({}, reagentplan.inbound_slots([]))
        self.assertEqual({}, reagentplan.inbound_slots(None))

    def test_the_reserve_is_capped(self):
        shorts = tuple(
            reagentplan.Short(
                reagentplan.Reagent(n, "r%d" % n, 1),
                reagentplan.Stock(bank=5),
                reagentplan.BANK,
                "Uzza",
                "",
            )
            for n in range(40)
        )
        plan = reagentplan.Plan("Uzza", 1, True, 0, shorts)
        self.assertEqual(
            {"Uzza": reagentplan.INBOUND_CAP}, reagentplan.inbound_slots([plan])
        )


class TheItemPlanMakesRoomForTheFeedFirst(unittest.TestCase):
    TAILOR = (TAILORING, 145, 225)

    def _bags(self):
        """Four stacks of the tailor's own stock and one stack of food."""
        thread = stack(
            entry=2321, name="Fine Thread", item_class=7, subclass=5, sell=25, count=20
        )
        dye = stack(
            entry=6260, name="Blue Dye", item_class=7, subclass=11, sell=12, count=10
        )
        bolt = stack(
            entry=4305,
            name="Bolt of Silk Cloth",
            item_class=7,
            subclass=5,
            sell=500,
            count=5,
        )
        silk = stack(
            entry=4306, name="Silk Cloth", item_class=7, subclass=5, sell=60, count=8
        )
        food = stack(
            entry=4540,
            name="Tough Hunk of Bread",
            item_class=0,
            subclass=5,
            sell=5,
            count=4,
        )
        return [thread, dye, bolt, silk], food

    def _ctx(self, inbound):
        return itemplan.Context(fire_gear=frozenset(), inbound=inbound)

    def _routes(self, inbound, slots=15):
        stock, food = self._bags()
        tailor = member(skills=[self.TAILOR], carried_slots=slots)
        ctx = self._ctx(inbound) if inbound is not None else None
        by_key, _ = decide([*stock, food], [tailor], ctx)
        return {s.name: by_key[s.key].route for s in [*stock, food]}

    def test_without_a_fetch_coming_nothing_is_cleared_at_ten_free(self):
        got = self._routes(None)
        self.assertEqual({itemplan.KEEP_CARRY}, set(got.values()))

    def test_a_fetch_coming_clears_room_for_it_before_anything_lands(self):
        got = self._routes({"Ana": 1})
        kept = [n for n, r in got.items() if r == itemplan.KEEP_CARRY]
        # 15 slots, a target of 12 free plus the 1 coming: two stacks stay.
        self.assertEqual(2, len(kept))

    def test_a_non_reagent_stack_leaves_before_the_trade_stock_does(self):
        got = self._routes({"Ana": 1})
        self.assertNotEqual(itemplan.KEEP_CARRY, got["Tough Hunk of Bread"])
        self.assertEqual(itemplan.KEEP_CARRY, got["Bolt of Silk Cloth"])

    def test_the_cheapest_stock_leaves_next(self):
        got = self._routes({"Ana": 1})
        self.assertEqual(itemplan.KEEP_CARRY, got["Fine Thread"])
        self.assertNotEqual(itemplan.KEEP_CARRY, got["Blue Dye"])

    def test_a_member_with_no_fetch_coming_is_not_cleared(self):
        _stock, food = self._bags()
        other = [
            dataclasses.replace(food, holder="Bo", entry=4540 + n, index=n)
            for n in range(3)
        ]
        bo = member("Bo", cls=DRUID, carried_slots=13)
        by_key, _ = decide(
            other, [bo, member(skills=[self.TAILOR])], self._ctx({"Ana": 3})
        )
        for s in other:
            self.assertEqual(itemplan.KEEP_CARRY, by_key[s.key].route)

    def test_the_room_asked_for_is_capped(self):
        a = self._routes({"Ana": 500})
        b = self._routes({"Ana": itemplan.INBOUND_CAP})
        self.assertEqual(a, b)

    def test_a_reagent_stack_goes_to_its_crafter_not_to_the_bank(self):
        cloth = stack(
            holder="Bo",
            entry=4306,
            name="Silk Cloth",
            item_class=7,
            subclass=5,
            sell=60,
            count=20,
        )
        bo = member("Bo", cls=DRUID)
        tailor = member("Ana", skills=[self.TAILOR])
        by_key, _ = decide([cloth], [bo, tailor])
        d = by_key[cloth.key]
        self.assertEqual((d.route, d.target), (itemplan.GIVE, "Ana"))


class TheBankFetchesOnlyAfterRoomIsMade(unittest.TestCase):
    SKILLS = {"Uzza": {"alchemy": 52, "herbalism": 70}}

    def _row(self, **kw):
        base = dict(
            holder="Uzza",
            level=60,
            item_guid=1,
            count=34,
            name="Empty Vial",
            quality=1,
            sell_price=1,
            required_level=0,
            bonding=0,
            item_class=7,
            container_slots=0,
            bag=0,
            slot=39,
            entry=EMPTY_VIAL,
        )
        base.update(kw)
        return base

    def _plan(self, wants, planned=None, free=0):
        members = bank.members_from_rows([self._row()], ["Uzza"])
        members = [dataclasses.replace(m, bag_free=free) for m in members]
        storage = bank.storage_from(self.SKILLS, craft_wants=wants)
        family = bank.family_from_skills(self.SKILLS)
        return bank.plan(members, family, storage=storage, planned_deposits=planned)

    def test_with_full_bags_and_no_room_made_the_vial_stays_banked(self):
        plan = self._plan({"Uzza": frozenset({EMPTY_VIAL})})
        self.assertEqual([], [m for m in plan.moves if m.verb == bank.WITHDRAW])
        self.assertTrue(any("no room" in n for n in plan.notes))

    def test_a_deposit_the_item_plan_makes_gives_the_fetch_its_slot(self):
        plan = self._plan({"Uzza": frozenset({EMPTY_VIAL})}, {"Uzza": 1})
        self.assertEqual([1], [m.guid for m in plan.moves if m.verb == bank.WITHDRAW])

    def test_room_made_is_only_counted_for_a_crafters_own_fetch(self):
        plan = self._plan({}, {"Uzza": 3})
        self.assertEqual([], [m for m in plan.moves if m.verb == bank.WITHDRAW])

    def test_the_merged_plan_deposits_before_it_withdraws(self):
        fetch = bank.Move("Uzza", bank.WITHDRAW, 1, "Empty Vial", 34, "craft")
        junk = bank.Move("Uzza", bank.DEPOSIT, 2, "Junk", 1, "plan")
        merged = itemplan_route.merge(
            bank.Plan(moves=(fetch,)), itemplan_route.Routed((junk,), ())
        )
        self.assertEqual([bank.DEPOSIT, bank.WITHDRAW], [m.verb for m in merged.moves])

    def test_a_guild_deposit_is_not_room_in_the_bags_for_the_fetch(self):
        guild = bank.Move("Uzza", bank.DEPOSIT, 3, "Ore", 1, "plan", bank.GUILD, 1)
        self.assertEqual({}, itemplan_route.personal_room([guild]))
        personal = bank.Move("Uzza", bank.DEPOSIT, 2, "Junk", 1, "plan")
        self.assertEqual({"Uzza": 1}, itemplan_route.personal_room([guild, personal]))


class TheCallersAreWired(unittest.TestCase):
    def test_the_item_plan_reads_the_standing_reagent_plans(self):
        body = _body("_itemplan_reads")
        self.assertIn("inbound=", body)
        self.assertIn("reagentplan.inbound_slots", body)

    def test_the_shadow_context_carries_the_reserve(self):
        extras = itemplan_shadow.Extras(inbound={"Uzza": 2})
        ctx = itemplan_shadow._context(extras, {})
        self.assertEqual({"Uzza": 2}, dict(ctx.inbound))
        bare = itemplan_shadow._context(itemplan_shadow.Extras(), {})
        self.assertEqual({}, dict(bare.inbound))

    def test_the_bank_pass_plans_the_deposits_first_and_hands_their_room_on(self):
        body = _body("_plan_bank")
        self.assertIn("planned_deposits=", body)
        self.assertLess(body.index("_itemplan_bank_routes"), body.index("bank.plan("))


if __name__ == "__main__":
    unittest.main()
