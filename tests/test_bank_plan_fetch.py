"""A banked stack the item plan sells is fetched out of the bank (#2603).

`itemplan_vendor` sells carried stacks only and `bank._wanted_back` fetched a
stack only when the bags wanted it, so a banked stack the plan sells could
never leave. The plan now plans the banked stacks too (`banked_plan`), the
sellable ones become `Storage.plan_leaves`, and the bank pass withdraws them
while the holder keeps the plan's floor of free slots.
"""

import pathlib
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from _stub_modules import PYMYSQL, fresh_import  # noqa: E402

import bank  # noqa: E402
import itemplan  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
from test_bank import row  # noqa: E402

NAMES = ["Ugga"]
HELD = {"Ugga": {"herbalism": 10}}


def banked_row(guid, slot, **kw):
    base = dict(
        holder="Ugga",
        item_guid=guid,
        name="Odd Trinket",
        entry=9000 + guid,
        item_class=15,
        quality=1,
        sell_price=40,
        count=1,
        slot=slot,
    )
    base.update(kw)
    return row(**base)


def carried_fill(n):
    return [
        row(
            holder="Ugga",
            item_guid=500 + i,
            name="Pebble %d" % i,
            entry=500 + i,
            slot=23 + i,
            item_class=15,
            quality=1,
        )
        for i in range(n)
    ]


def plan(rows, leaves):
    storage = bank.storage_from(HELD, plan_leaves=leaves)
    return bank.plan(
        bank.members_from_rows(rows, NAMES),
        bank.family_from_skills(HELD),
        storage=storage,
    )


def moves(result):
    return [(m.verb, m.guid) for m in result.moves]


class ABankedStackThePlanSellsComesOut(unittest.TestCase):
    def test_it_is_planned_as_a_withdrawal_when_the_holder_has_room_above_the_floor(
        self,
    ):
        result = plan([banked_row(21, 40)], {21: "the item plan sells it"})
        self.assertEqual([(bank.WITHDRAW, 21)], moves(result))
        self.assertIn("item plan sells", result.moves[0].why)

    def test_a_banked_stack_the_plan_keeps_is_never_withdrawn(self):
        self.assertEqual([], moves(plan([banked_row(21, 40)], {})))

    def test_a_holder_at_the_floor_takes_nothing_out(self):
        # 16 backpack slots, 9 used = 7 free: under the plan's floor of 8.
        rows = carried_fill(9) + [banked_row(21, 40)]
        result = plan(rows, {21: "sold"})
        self.assertEqual([], moves(result))
        self.assertTrue(any("keeps 8 free slots" in n for n in result.notes))

    def test_a_holder_one_slot_over_the_floor_takes_one_out(self):
        rows = carried_fill(7) + [banked_row(21, 40), banked_row(22, 41)]
        result = plan(rows, {21: "sold", 22: "sold"})
        self.assertEqual(1, len(result.moves))

    def test_the_visit_limit_still_bounds_it(self):
        rows = [banked_row(30 + i, 40 + i) for i in range(12)]
        result = plan(rows, {30 + i: "sold" for i in range(12)})
        self.assertEqual(bank.VISIT_LIMIT, len(result.moves))

    def test_the_keeper_rule_does_not_put_a_fetched_stack_back(self):
        """The same stack, now carried and still the plan's: no deposit."""
        rows = [
            row(
                holder="Ugga",
                item_guid=21,
                name="Pattern: Cloak",
                entry=7001,
                item_class=9,
                quality=2,
                slot=23,
                required_skill=197,
                required_rank=200,
            )
        ]
        self.assertEqual([(bank.DEPOSIT, 21)], moves(plan(rows, {})))
        self.assertEqual([], moves(plan(rows, {21: "sold"})))


def decision_for(entry, route, **kw):
    return itemplan.Decision(
        holder="Ugga",
        entry=entry,
        name="Odd Trinket",
        count=1,
        from_loc=itemplan.BANK,
        route=route,
        goal=itemplan.ROOM,
        reason="plan",
        rule="R11",
        key=("Ugga", 2, entry, 0),
        options=(route,),
        **kw,
    )


class OnlyAnUnheldSaleIsFetched(unittest.TestCase):
    def stack(self, entry, item_class=15):
        return types.SimpleNamespace(
            key=("Ugga", 2, entry, 0), item_class=item_class, subclass=0
        )

    def run_case(self, decision, item_class=15):
        stack = self.stack(decision.entry, item_class)
        plan_ = itemplan.Plan((decision,), ())
        return shadow.sold_from_bank(
            plan_, [(stack, {"item_guid": 77, "item_class": item_class})]
        )

    def test_a_plain_vendor_sale_is_fetched(self):
        self.assertEqual(
            [77], list(self.run_case(decision_for(1, itemplan.SELL_VENDOR)))
        )

    def test_a_confirm_sale_waits_for_a_release(self):
        d = decision_for(1, itemplan.SELL_VENDOR, confirm=True)
        self.assertEqual({}, self.run_case(d))

    def test_a_stack_the_plan_keeps_in_the_bank_is_not_fetched(self):
        self.assertEqual({}, self.run_case(decision_for(1, itemplan.BANK_PERSONAL)))

    def test_gear_recipes_and_bags_are_left_to_their_own_passes(self):
        for item_class in (2, 4, 9, 1):
            d = decision_for(1, itemplan.SELL_VENDOR)
            self.assertEqual({}, self.run_case(d, item_class), item_class)

    def test_a_fallback_sale_is_not_fetched(self):
        d = itemplan.Decision(
            holder="Ugga",
            entry=1,
            name="Odd Trinket",
            count=1,
            from_loc=itemplan.BANK,
            route=itemplan.SELL_VENDOR,
            goal=itemplan.ROOM,
            reason="plan",
            rule="R11",
            key=("Ugga", 2, 1, 0),
            options=(itemplan.GUILD_BANK, itemplan.SELL_VENDOR),
            skipped=("GUILD_BANK: guild bank tab is full",),
        )
        self.assertEqual({}, self.run_case(d))

    def test_the_real_banked_plan_sells_junk_and_keeps_a_quest_stack(self):
        rows_ = [
            row(
                holder="Ugga",
                item_guid=31,
                name="Odd Trinket",
                entry=9031,
                item_class=8,
                quality=1,
                sell_price=40,
                slot=40,
            ),
            row(
                holder="Ugga",
                item_guid=32,
                name="Old Letter",
                entry=9032,
                item_class=12,
                quality=1,
                sell_price=40,
                slot=41,
            ),
        ]
        ex = shadow.Extras(
            open_quest_items={"Ugga": frozenset()},
            templates={
                e: {
                    "item_class": c,
                    "subclass": 0,
                    "bonding": 0,
                    "inventory_type": 0,
                    "item_level": 1,
                    "req_level": 0,
                    "required_skill_rank": 0,
                    "container_slots": 0,
                    "fire_res": 0,
                    "stats": {},
                }
                for e, c in ((9031, 8), (9032, 12))
            },
            instance_soulbound={31: False, 32: False},
            fire_gear=frozenset(),
            bank_free={"Ugga": 20},
        )
        plan_, pairs = shadow.banked_plan(NAMES, "Ugga", rows_, [], {"Ugga": 16}, ex)
        self.assertEqual([31], list(shadow.sold_from_bank(plan_, pairs)))
        self.assertTrue(all(d.from_loc == itemplan.BANK for d in plan_.decisions))


def import_bridge():
    discord = types.ModuleType("discord")
    discord.Client = object
    return fresh_import("bridge", discord=discord, pymysql=PYMYSQL)


class TheBridgeFetchesOnlyWhenTheVendorRouteIsOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = import_bridge()

    def setUp(self):
        self.bridge._BANK_LEAVES_CACHE.clear()

    def test_without_the_vendor_route_the_bank_rows_are_not_read(self):
        b = self.bridge
        with (
            mock.patch.dict("os.environ", {"ITEMPLAN_GIVE": "on"}, clear=True),
            mock.patch.object(b, "_banked_rows", side_effect=AssertionError("read")),
            mock.patch.object(b, "_fetch_vendor_items", return_value=[]),
            mock.patch.object(b, "_fetch_free_slots", return_value={}),
            mock.patch.object(b, "_fetch_surplus_gear", return_value=[]),
            mock.patch.object(b, "_fetch_family_equipped", return_value=[]),
            mock.patch.object(b, "_itemplan_reads", return_value=shadow.Extras()),
        ):
            leaves, unread = b._bank_plan_leaves(["Ugga"])
        self.assertEqual(({}, False), (leaves, unread))

    def test_the_banked_sale_joins_the_leaves(self):
        b = self.bridge
        bank_rows = [
            row(
                holder="Ugga",
                item_guid=31,
                name="Odd Trinket",
                entry=9031,
                item_class=8,
                quality=1,
                sell_price=40,
                slot=40,
            ),
        ]
        ex = shadow.Extras(
            open_quest_items={"Ugga": frozenset()},
            templates={
                9031: {
                    "item_class": 8,
                    "subclass": 0,
                    "bonding": 0,
                    "inventory_type": 0,
                    "item_level": 1,
                    "req_level": 0,
                    "required_skill_rank": 0,
                    "container_slots": 0,
                    "fire_res": 0,
                    "stats": {},
                }
            },
            instance_soulbound={31: False},
            fire_gear=frozenset(),
            bank_free={"Ugga": 20},
        )
        with (
            mock.patch.dict("os.environ", {"ITEMPLAN_SELL_VENDOR": "on"}, clear=True),
            mock.patch.object(b, "_fetch_bank_items", return_value=bank_rows),
            mock.patch.object(b, "_fetch_vendor_items", return_value=[]),
            mock.patch.object(b, "_fetch_free_slots", return_value={"Ugga": 16}),
            mock.patch.object(b, "_fetch_surplus_gear", return_value=[]),
            mock.patch.object(b, "_fetch_family_equipped", return_value=[]),
            mock.patch.object(b, "_itemplan_reads", return_value=ex),
        ):
            leaves, unread = b._bank_plan_leaves(["Ugga"])
        self.assertFalse(unread)
        self.assertEqual([31], list(leaves))


if __name__ == "__main__":
    unittest.main()
