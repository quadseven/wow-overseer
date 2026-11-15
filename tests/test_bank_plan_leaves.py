"""The keeper rule stores nothing the item plan sells, gives or lists (#2604).

Two modules answered "does this stack belong in a bank" and disagreed: the
keeper rule banked recipes nobody can learn, gems nobody cuts and uncommon
goods with no ceiling, while the item plan said the same stacks should go to a
vendor, a member or the house. `bank.Storage.plan_leaves` is the plan's word,
read through `itemplan_shadow.leaving`, and the keeper rule defers to it.
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
from test_itemplan_shadow import fixture  # noqa: E402

NAMES = ["Ugga", "Zug", "Bork"]
HELD = {"Ugga": {"herbalism": 10}}
RECIPE = 7001
GEM = 7002
BLUE = 7003


def guild(items=10):
    return {
        "purchased_tabs": 1,
        "deposit_rank_ids": [0],
        "member_ranks": {"Ugga": 0, "Zug": 0, "Bork": 0},
        "tab_items": {0: items},
    }


def rows():
    return [
        # A recipe for a trade nobody in the family has: the keeper rule stores it.
        row(
            holder="Ugga",
            item_guid=11,
            name="Pattern: Cloak",
            entry=RECIPE,
            item_class=9,
            quality=2,
            count=1,
            slot=23,
            required_skill=197,
            required_rank=200,
        ),
        row(
            holder="Ugga",
            item_guid=12,
            name="Moss Agate",
            entry=GEM,
            item_class=3,
            quality=2,
            count=5,
            slot=24,
        ),
        row(
            holder="Ugga",
            item_guid=13,
            name="Odd Green Thing",
            entry=BLUE,
            item_class=15,
            quality=2,
            count=1,
            slot=25,
        ),
    ]


def plan(leaves=None, unread=False, with_guild=True):
    storage = bank.storage_from(
        HELD,
        guild=guild() if with_guild else None,
        plan_leaves=leaves,
        plan_unread=unread,
    )
    return bank.plan(
        bank.members_from_rows(rows(), NAMES),
        bank.family_from_skills(HELD),
        storage=storage,
    )


def banked(result):
    return sorted({m.guid for m in result.moves} | {m.guid for m in result.guild})


class WhatThePlanSellsIsNotBanked(unittest.TestCase):
    def test_without_the_plan_the_keeper_rule_stores_all_three(self):
        self.assertEqual([11, 12, 13], banked(plan()))

    def test_a_recipe_gem_and_uncommon_the_plan_routes_away_are_not_deposited(self):
        leaves = {
            11: "the item plan routes Pattern: Cloak to SELL_VENDOR",
            12: "the item plan routes Moss Agate to GIVE",
            13: "the item plan routes Odd Green Thing to AUCTION",
        }
        self.assertEqual([], banked(plan(leaves)))

    def test_only_the_stack_the_plan_routes_away_is_held_back(self):
        self.assertEqual([11, 13], banked(plan({12: "sold"})))

    def test_a_stack_the_plan_banks_is_still_deposited_to_the_tab_it_names(self):
        result = plan({11: "sold"})
        gem = [m for m in result.guild if m.guid == 12]
        self.assertEqual(1, len(gem))
        self.assertEqual(0, gem[0].tab)
        self.assertEqual(bank.GUILD, gem[0].to)

    def test_the_storage_reason_is_empty_for_a_stack_the_plan_leaves(self):
        storage = bank.storage_from(HELD, plan_leaves={12: "sold"})
        members = bank.members_from_rows(rows(), NAMES)
        by_guid = {h.guid: h for m in members for h in m.carried}
        self.assertEqual("", bank.storage_reason(by_guid[12], storage))
        self.assertNotEqual("", bank.storage_reason(by_guid[11], storage))


class APlanThatCouldNotBeReadStoresNothingNew(unittest.TestCase):
    def test_an_unread_plan_deposits_nothing_on_the_keeper_rule(self):
        self.assertEqual([], banked(plan(unread=True)))

    def test_an_unread_plan_still_stores_what_a_policy_placement_settled(self):
        placed = types.SimpleNamespace(
            why="raid supply", tab=None, to="personal", kind="supply"
        )
        storage = bank.storage_from(HELD, policy={12: placed}, plan_unread=True)
        result = bank.plan(
            bank.members_from_rows(rows(), NAMES),
            bank.family_from_skills(HELD),
            storage=storage,
        )
        self.assertEqual([12], banked(result))

    def test_an_unread_plan_never_fetches_a_banked_stack_back(self):
        """Fail closed on the deposit side only: a banked recipe nobody can
        learn stays where it is, it is not hauled out because the plan failed."""
        banked_rows = [
            row(
                holder="Ugga",
                item_guid=21,
                name="Pattern: Cloak",
                entry=RECIPE,
                item_class=9,
                quality=2,
                slot=40,
                required_skill=197,
                required_rank=200,
            )
        ]
        storage = bank.storage_from(HELD, plan_unread=True)
        result = bank.plan(
            bank.members_from_rows(banked_rows, NAMES),
            bank.family_from_skills(HELD),
            storage=storage,
        )
        self.assertEqual((), result.moves)


def decision(
    route,
    key=(),
    *,
    entry=1,
    options=None,
    skipped=(),
    reason="plan",
    target="",
    stuck=False,
    name="Thing",
):
    return itemplan.Decision(
        holder="Ana",
        entry=entry,
        name=name,
        count=1,
        from_loc=itemplan.CARRIED_BAG,
        route=route,
        goal=itemplan.ROOM,
        reason=reason,
        rule="R11",
        target=target,
        key=key,
        options=tuple(options if options is not None else (route,)),
        skipped=tuple(skipped),
        stuck=stuck,
    )


def templates():
    return {
        entry: {
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
        for entry, c in ((2589, 7), (4540, 0), (9999, 15), (7777, 4))
    }


def extras():
    return shadow.Extras(
        open_quest_items={"Ana": frozenset()},
        templates=templates(),
        instance_soulbound={1: False, 2: False, 3: False, 4: False},
        fire_gear=frozenset(),
    )


class OnlyARouteSomethingCarriesOutCounts(unittest.TestCase):
    def pairs(self, *decisions):
        plan_ = itemplan.Plan(tuple(decisions), ())
        stack_rows = [
            (types.SimpleNamespace(key=d.key), {"item_guid": 100 + i})
            for i, d in enumerate(decisions)
        ]
        return plan_, stack_rows

    def test_switches_name_the_routes(self):
        self.assertEqual(frozenset(), shadow.carried_out_routes({}))
        self.assertEqual(
            frozenset({itemplan.SELL_VENDOR, itemplan.GIVE, itemplan.AUCTION}),
            shadow.carried_out_routes(
                {
                    "ITEMPLAN_SELL_VENDOR": "on",
                    "ITEMPLAN_GIVE": "1",
                    "ITEMPLAN_AUCTION": "true",
                }
            ),
        )

    def test_a_route_with_no_executor_leaves_nothing(self):
        plan_, pairs = self.pairs(decision(itemplan.SELL_VENDOR, key=("a",)))
        self.assertEqual({}, shadow.leaving(plan_, pairs, frozenset()))

    def test_the_first_choice_sale_is_named_by_guid(self):
        plan_, pairs = self.pairs(decision(itemplan.SELL_VENDOR, key=("a",)))
        got = shadow.leaving(plan_, pairs, {itemplan.SELL_VENDOR})
        self.assertEqual([100], list(got))
        self.assertIn("SELL_VENDOR", got[100])

    def test_a_fallback_sale_is_not_the_plans_answer(self):
        plan_, pairs = self.pairs(
            decision(
                itemplan.SELL_VENDOR,
                key=("a",),
                options=(itemplan.GUILD_BANK, itemplan.SELL_VENDOR),
                skipped=("GUILD_BANK: guild bank tab is full",),
            )
        )
        self.assertEqual({}, shadow.leaving(plan_, pairs, {itemplan.SELL_VENDOR}))

    def test_a_stuck_or_unplaced_stack_is_not_a_leaving(self):
        plan_, pairs = self.pairs(
            decision(itemplan.SELL_VENDOR, key=("a",), stuck=True),
            decision(
                itemplan.SELL_VENDOR,
                key=("b",),
                reason=itemplan.NO_ROOM + ": nothing had room",
            ),
        )
        self.assertEqual({}, shadow.leaving(plan_, pairs, {itemplan.SELL_VENDOR}))

    def test_a_gift_counts_only_for_a_family_taker(self):
        plan_, pairs = self.pairs(
            decision(itemplan.GIVE, key=("a",), target="Zug"),
            decision(itemplan.GIVE, key=("b",), target="Stranger"),
        )
        got = shadow.leaving(plan_, pairs, {itemplan.GIVE}, ["Ana", "Zug"])
        self.assertEqual([100], list(got))

    def test_a_bank_route_is_never_a_leaving(self):
        plan_, pairs = self.pairs(
            decision(itemplan.BANK_PERSONAL, key=("a",)),
            decision(itemplan.GUILD_BANK, key=("b",)),
        )
        routes = {itemplan.SELL_VENDOR, itemplan.GIVE, itemplan.AUCTION}
        self.assertEqual({}, shadow.leaving(plan_, pairs, routes))

    def test_the_real_plan_sells_surplus_cloth_and_a_spare_green(self):
        rows_, gear, worn, free = fixture()
        ex = extras()
        report = shadow.shadow(
            ["Ana"], "Fam", rows_, free, gear_rows=gear, worn_rows=worn, extras=ex
        )
        stacks = shadow.build_stacks(rows_, gear, ex.templates, ex.instance_soulbound)
        got = shadow.leaving(
            report.plan,
            list(zip(stacks, rows_, strict=True)),
            {itemplan.SELL_VENDOR},
            ["Ana"],
        )
        self.assertEqual([1, 4], sorted(got))


def import_bridge():
    discord = types.ModuleType("discord")
    discord.Client = object
    return fresh_import("bridge", discord=discord, pymysql=PYMYSQL)


class TheBridgeReadsThePlanForTheBank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = import_bridge()

    def setUp(self):
        self.bridge._BANK_LEAVES_CACHE.clear()

    def test_with_every_executor_off_the_plan_is_not_consulted(self):
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(
                self.bridge, "_fetch_vendor_items", side_effect=AssertionError("read")
            ),
        ):
            self.assertEqual(({}, False), self.bridge._bank_plan_leaves(["Ana"]))

    def test_a_plan_that_cannot_be_read_is_unread(self):
        with (
            mock.patch.dict("os.environ", {"ITEMPLAN_SELL_VENDOR": "on"}, clear=True),
            mock.patch.object(
                self.bridge, "_fetch_vendor_items", side_effect=OSError("down")
            ),
        ):
            self.assertEqual(({}, True), self.bridge._bank_plan_leaves(["Ana"]))

    def test_the_plan_names_the_stack_it_sells(self):
        rows_, gear, worn, free = fixture()
        b = self.bridge
        with (
            mock.patch.dict("os.environ", {"ITEMPLAN_SELL_VENDOR": "on"}, clear=True),
            mock.patch.object(b, "_fetch_vendor_items", return_value=rows_),
            mock.patch.object(b, "_fetch_free_slots", return_value=free),
            mock.patch.object(b, "_fetch_surplus_gear", return_value=gear),
            mock.patch.object(b, "_fetch_family_equipped", return_value=worn),
            mock.patch.object(b, "_itemplan_reads", return_value=extras()),
        ):
            leaves, unread = b._bank_plan_leaves(["Ana"])
        self.assertFalse(unread)
        self.assertEqual([1, 4], sorted(leaves))

    def test_the_bank_plan_hands_the_answer_to_the_storage(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        body = src[src.index("def _plan_bank(") : src.index("def _bank_forecast(")]
        self.assertIn("plan_leaves, plan_unread = _bank_plan_leaves(names)", body)
        self.assertIn("plan_leaves=plan_leaves, plan_unread=plan_unread", body)


if __name__ == "__main__":
    unittest.main()
