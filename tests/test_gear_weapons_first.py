"""A weapon first, from the right vendor, paid for by the family.

The dev realm, 2026-09-28: the level 35 mage and priest of the Alliance family
wore no main hand at all. The town errand ran, and it bought the mage a Strong
Fishing Pole, twice, because the planner took a fishing pole for a weapon, the
nearest vendor that sold anybody anything won the walk (the fishing supplier
sixteen yards from the mailbox, not the weaponsmith 128 yards off), and every
piece was capped at a fifth of the purse. The warrior carried 54 gold while the
rogue had 2. Pinned here with the realm's own rows.
"""

import ast
import pathlib
import unittest

import gearup

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

# Ratchet's weapon and fishing stock, read off acore_world on 2026-09-28.
STRONG_FISHING_POLE = dict(
    entry=6365, InventoryType=17, subclass=20, ItemLevel=10, RequiredLevel=5, buyout=902
)
GNARLED_STAFF = dict(
    entry=2030,
    InventoryType=17,
    subclass=10,
    ItemLevel=20,
    RequiredLevel=15,
    buyout=5545,
)
QUARTER_STAFF = dict(
    entry=854,
    InventoryType=17,
    subclass=10,
    ItemLevel=16,
    RequiredLevel=11,
    buyout=3023,
)
SHORT_STAFF = dict(
    entry=2132, InventoryType=17, subclass=10, ItemLevel=4, RequiredLevel=1, buyout=102
)
BLACKSMITH_HAMMER = dict(
    entry=5956, InventoryType=21, subclass=14, ItemLevel=1, RequiredLevel=1, buyout=16
)


def weapon(row, **kw):
    return {"class": 2, "AllowableClass": -1, "id": row["entry"], **row, **kw}


def armor(entry, inv, ilvl, price, sub=1):
    return {
        "entry": entry,
        "id": entry,
        "class": 4,
        "subclass": sub,
        "InventoryType": inv,
        "ItemLevel": ilvl,
        "RequiredLevel": 1,
        "AllowableClass": -1,
        "buyout": price,
    }


def mage(purse=99342, **equipped):
    # Staves (10), wands (19) and fishing (20): the mage's live weapon skills.
    return {
        "class": "mage",
        "level": 35,
        "purse": purse,
        "equipped": dict(equipped),
        "skills": {"weapons": {10, 19, 20}},
    }


def vendor_rows(vendor, name, yards, items):
    return [
        dict(item, vendor=vendor, vendor_name=name, map_id=1, yards=yards)
        for item in items
    ]


class NotGear(unittest.TestCase):
    def test_a_fishing_pole_is_never_bought_for_the_main_hand(self):
        buys = gearup.plan_vendor_buys(
            {"Og": mage()}, {"Og": [weapon(STRONG_FISHING_POLE)]}
        )
        self.assertEqual((), buys)

    def test_a_tool_is_never_bought_for_the_main_hand(self):
        warrior = {
            "class": "warrior",
            "level": 17,
            "purse": 50000,
            "equipped": {},
            "skills": {"weapons": {0, 4, 7, 14}},
        }
        buys = gearup.plan_vendor_buys(
            {"Zug": warrior}, {"Zug": [weapon(BLACKSMITH_HAMMER)]}
        )
        self.assertEqual((), buys)

    def test_a_piece_far_below_the_buyer_is_not_bought(self):
        mask = armor(46860, 1, 1, 5, sub=0)
        self.assertEqual((), gearup.plan_vendor_buys({"Og": mage()}, {"Og": [mask]}))
        buys = gearup.plan_vendor_buys({"Og": mage()}, {"Og": [weapon(SHORT_STAFF)]})
        self.assertEqual((), buys)


class WeaponFirst(unittest.TestCase):
    def test_the_best_staff_goes_in_the_empty_main_hand(self):
        stock = [
            weapon(STRONG_FISHING_POLE),
            weapon(QUARTER_STAFF),
            weapon(GNARLED_STAFF),
        ]
        buys = gearup.plan_vendor_buys({"Og": mage()}, {"Og": stock})
        self.assertEqual([("mainhand", 2030)], [(b.slot, b.entry) for b in buys])

    def test_a_weapon_may_cost_more_than_a_fifth_of_the_purse(self):
        # A green staff at 3 gold on a 10 gold purse: over the per-piece fifth,
        # inside the spendable budget. The empty main hand gets it anyway.
        green = weapon(dict(GNARLED_STAFF, entry=9999, ItemLevel=33, buyout=30000))
        buys = gearup.plan_buys({"Og": mage(purse=100000)}, [green])
        self.assertEqual([("mainhand", 9999)], [(b.slot, b.entry) for b in buys])

    def test_the_weapon_is_bought_before_cheaper_armour_takes_the_budget(self):
        stock = [
            armor(1, 1, 30, 18000),
            armor(2, 5, 30, 18000),
            armor(3, 7, 30, 18000),
            weapon(GNARLED_STAFF, buyout=30000),
        ]
        buys = gearup.plan_buys({"Og": mage(purse=100000)}, stock)
        self.assertEqual("mainhand", buys[0].slot)
        self.assertLessEqual(sum(b.buyout for b in buys), 60000)

    def test_a_shield_tank_is_never_sold_a_two_hander(self):
        tank = dict(
            mage(), **{"class": "warrior", "tank": True, "skills": {"weapons": {10}}}
        )
        buys = gearup.plan_vendor_buys(
            {"Grug": tank}, {"Grug": [weapon(GNARLED_STAFF)]}
        )
        self.assertEqual((), buys)


class TheRightVendor(unittest.TestCase):
    def test_the_weaponsmith_beats_the_fishing_supplier_by_the_mailbox(self):
        rows = (
            vendor_rows(3572, "Zizzek", 16, [weapon(STRONG_FISHING_POLE)])
            + vendor_rows(3658, "Lizzarik", 78, [weapon(QUARTER_STAFF)])
            + vendor_rows(3491, "Ironzar", 128, [weapon(GNARLED_STAFF)])
        )
        trip = gearup.vendor_trip({"Og": mage()}, rows, map_id=1, max_yards=250)
        self.assertEqual(3658, trip.vendor)  # both staves arm him; nearer wins

    def test_a_vendor_that_arms_somebody_beats_one_that_fills_more_slots(self):
        cloth = [armor(10 + i, inv, 25, 500) for i, inv in enumerate((1, 5, 7, 8))]
        rows = vendor_rows(1, "Tailor", 20, cloth) + vendor_rows(
            2, "Weaponsmith", 120, [weapon(GNARLED_STAFF)]
        )
        trip = gearup.vendor_trip({"Og": mage()}, rows, map_id=1, max_yards=250)
        self.assertEqual(2, trip.vendor)

    def test_a_visited_vendor_is_skipped_for_the_next(self):
        cloth = [armor(10, 1, 25, 500)]
        rows = vendor_rows(1, "Tailor", 20, cloth) + vendor_rows(
            2, "Weaponsmith", 120, [weapon(GNARLED_STAFF)]
        )
        trip = gearup.vendor_trip(
            {"Og": mage()}, rows, map_id=1, max_yards=250, skip=frozenset({2})
        )
        self.assertEqual(1, trip.vendor)

    def test_a_member_with_no_weapon_is_worth_a_walk_on_its_own(self):
        full = {
            s: 30
            for s in (
                "head",
                "neck",
                "shoulder",
                "chest",
                "waist",
                "legs",
                "feet",
                "wrist",
                "hands",
                "finger1",
                "finger2",
                "trinket1",
                "trinket2",
                "back",
                "offhand",
                "ranged",
            )
        }
        rows = vendor_rows(2, "Weaponsmith", 120, [weapon(GNARLED_STAFF)])
        trip = gearup.vendor_trip({"Og": mage(**full)}, rows, map_id=1, max_yards=250)
        self.assertEqual(2, trip.vendor)

    def test_stock_of_one_vendor(self):
        rows = vendor_rows(1, "A", 5, [weapon(QUARTER_STAFF)]) + vendor_rows(
            2, "B", 5, [weapon(GNARLED_STAFF)]
        )
        self.assertEqual({854}, gearup.stock_of(rows, 1))


class TheFamilyFundsItsOwn(unittest.TestCase):
    # Live purses and levels, 2026-09-28 01:22Z.
    FACTS = {
        "Grug": {"level": 38, "purse": 540103, "equipped": {"mainhand": 43}},
        "Bork": {"level": 35, "purse": 23904, "equipped": {"head": 38}},
        "Og": {"level": 35, "purse": 99342, "equipped": {"chest": 16}},
        "Grog": {
            "level": 36,
            "purse": 100075,
            "equipped": {
                s: 30
                for s in (
                    "head",
                    "neck",
                    "shoulder",
                    "chest",
                    "waist",
                    "legs",
                    "feet",
                    "wrist",
                    "hands",
                    "finger1",
                    "finger2",
                    "back",
                    "mainhand",
                    "offhand",
                    "ranged",
                )
            },
        },
    }

    def test_the_richest_funds_the_short_members_weaponless_first(self):
        gifts = gearup.plan_funding(self.FACTS)
        self.assertEqual({"Grug"}, {g.donor for g in gifts})
        self.assertEqual(["Bork", "Og"], [g.taker for g in gifts])
        by = {g.taker: g.copper for g in gifts}
        self.assertEqual(gearup.FUND_PURSE_CAP - 23904, by["Bork"])
        self.assertEqual(gearup.FUND_PURSE_CAP - 99342, by["Og"])
        self.assertNotIn("Grog", by)  # two empty slots and a weapon: not short
        self.assertIn("no weapon", gifts[0].why)

    def test_nobody_is_funded_past_the_trial_purse_cap(self):
        # wow-dev 2026-09-28: 105000 copper read back as 100000 with nothing
        # bought; the realm's Trial.MoneyCap took the rest.
        facts = {
            "Grug": {"level": 38, "purse": 540103, "equipped": {"mainhand": 43}},
            "Og": {"level": 35, "purse": 100000, "equipped": {}},
        }
        self.assertEqual((), gearup.plan_funding(facts))

    def test_the_donor_keeps_half_its_purse(self):
        facts = {
            "Rich": {"level": 10, "purse": 100000, "equipped": {}},
            "A": {"level": 40, "purse": 0, "equipped": {}},
            "B": {"level": 40, "purse": 0, "equipped": {}},
        }
        gifts = gearup.plan_funding(facts)
        self.assertEqual(50000, sum(g.copper for g in gifts))

    def test_a_broke_family_sends_nothing(self):
        facts = {
            "Zug": {"level": 17, "purse": 6992, "equipped": {}},
            "Oz": {"level": 14, "purse": 46178, "equipped": {}},
        }
        self.assertEqual((), gearup.plan_funding(facts))

    def test_the_letter_is_gold_only(self):
        gift = gearup.Gift("Grug", "Bork", 81096, "x")
        self.assertEqual(
            "send money:81096 subject:For your gear", gearup.fund_command(gift)
        )


class TheErrandRemembers(unittest.TestCase):
    """The character table trails the world by fifteen minutes."""

    def setUp(self):
        ns = {}
        fn = [
            n
            for n in ast.walk(ast.parse(BRIDGE))
            if isinstance(n, ast.FunctionDef) and n.name == "_town_errand_facts"
        ]
        exec(compile(ast.Module(body=fn, type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102
        self.overlay = ns["_town_errand_facts"]

    def test_a_gift_and_a_bought_slot_are_laid_over_the_stale_read(self):
        facts = {"Og": mage(purse=1000), "Grug": {"purse": 500000, "equipped": {}}}
        out = self.overlay(facts, {"Og": 80000, "Grug": -80000}, {"Og": {"mainhand"}})
        self.assertEqual(81000, out["Og"]["purse"])
        self.assertEqual(420000, out["Grug"]["purse"])
        self.assertIn("mainhand", out["Og"]["equipped"])
        self.assertNotIn("mainhand", facts["Og"]["equipped"])  # not mutated
        buys = gearup.plan_vendor_buys(out, {"Og": [weapon(GNARLED_STAFF)]})
        self.assertEqual((), buys)  # the staff bought at the last vendor holds


if __name__ == "__main__":
    unittest.main()


class ABuyCountsOnlyOnceTheWorldSaysSo(unittest.TestCase):
    """wow-dev 2026-09-28 03:13Z: three buys refused `vendor not in range`
    were counted as bought, so the next vendor never offered the staff."""

    ROWS = [
        gearup.BuyRow("Og", "mainhand", 293261),
        gearup.BuyRow("Ugga", "mainhand", 293262),
        gearup.BuyRow("Bork", "offhand", 293260),
    ]

    def test_refused_for_range_is_not_bought(self):
        refused = {"status": "error", "detail": "vendor not in range"}
        answers = {r.row_id: refused for r in self.ROWS}
        bought, waiting, out_of_reach = gearup.settle_buys(self.ROWS, answers)
        self.assertEqual({}, bought)
        self.assertEqual([], waiting)
        self.assertTrue(out_of_reach)

    def test_delivered_is_bought_and_pending_waits(self):
        answers = {
            293261: {"status": "delivered"},
            293262: {"status": "pending"},
            293260: {"status": "error", "detail": "not enough money"},
        }
        bought, waiting, out_of_reach = gearup.settle_buys(self.ROWS, answers)
        self.assertEqual({"Og": {"mainhand"}}, bought)
        self.assertEqual([self.ROWS[1]], waiting)
        self.assertFalse(out_of_reach)


class TheVendorStepReadsItsRowsBack(unittest.TestCase):
    def setUp(self):
        import asyncio
        import types

        self.asyncio = asyncio
        self.answers = {}
        self.ns = {
            "asyncio": asyncio,
            "gearup": gearup,
            "log": types.SimpleNamespace(info=lambda *a, **k: None),
            "_TOWN_ERRAND_BOUGHT": {},
            "_family_label": lambda cohort: "",
            "_command_answer": lambda row_id: self.answers.get(row_id),
        }
        fn = [
            n
            for n in ast.walk(ast.parse(BRIDGE))
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "_town_errand_vendor_settle"
        ]
        code = compile(ast.Module(body=fn, type_ignores=[]), "bridge.py", "exec")
        exec(code, self.ns)  # noqa: S102 - bridge.py's own source, as in test_townerrand
        self.settle = self.ns["_town_errand_vendor_settle"]

    def run_settle(self, marks, visited):
        return self.asyncio.run(self.settle(None, ["Og", "Ugga"], marks, visited, None))

    def test_a_range_refusal_revisits_the_vendor_once_and_buys_nothing(self):
        rows = [gearup.BuyRow("Og", "mainhand", 1)]
        self.answers = {1: {"status": "error", "detail": "vendor not in range"}}
        visited = set()
        marks = {"written": rows, "at": 3658, "tries": {3658: 1}}
        self.assertTrue(self.run_settle(marks, visited))
        self.assertEqual(set(), visited)
        self.assertEqual({}, self.ns["_TOWN_ERRAND_BOUGHT"].get(("Og", "Ugga"), {}))
        marks = {"written": rows, "at": 3658, "tries": {3658: 2}}
        self.assertTrue(self.run_settle(marks, visited))
        self.assertEqual({3658}, visited)

    def test_an_unanswered_row_holds_the_step(self):
        self.answers = {1: {"status": "pending"}}
        marks = {"written": [gearup.BuyRow("Og", "mainhand", 1)], "at": 3658}
        self.assertFalse(self.run_settle(marks, set()))

    def test_a_delivered_buy_is_remembered(self):
        self.answers = {1: {"status": "delivered"}}
        visited = set()
        marks = {
            "written": [gearup.BuyRow("Og", "mainhand", 1)],
            "at": 3491,
            "tries": {3491: 1},
        }
        self.assertTrue(self.run_settle(marks, visited))
        self.assertEqual({3491}, visited)
        self.assertEqual(
            {"Og": {"mainhand"}}, self.ns["_TOWN_ERRAND_BOUGHT"][("Og", "Ugga")]
        )


class TheOffHandIsForDualWielders(unittest.TestCase):
    MACE = dict(
        entry=852,
        InventoryType=13,
        subclass=4,
        ItemLevel=14,
        RequiredLevel=9,
        buyout=1739,
    )

    def test_a_priest_is_never_sold_a_one_hander_for_her_off_hand(self):
        # wow-dev 2026-09-28 03:51: the level 13 priest bought a Mace for it.
        priest = {
            "class": "priest",
            "level": 13,
            "purse": 42366,
            "equipped": {"mainhand": 12},
            "skills": {"weapons": {4, 10}},
        }
        buys = gearup.plan_vendor_buys({"Uzza": priest}, {"Uzza": [weapon(self.MACE)]})
        self.assertEqual((), buys)

    def test_a_rogue_still_fills_his_off_hand(self):
        rogue = {
            "class": "rogue",
            "level": 35,
            "purse": 23904,
            "equipped": {"mainhand": 30},
            "skills": {"weapons": {4, 15}},
        }
        mace = weapon(dict(self.MACE, ItemLevel=20))
        buys = gearup.plan_vendor_buys({"Bork": rogue}, {"Bork": [mace]})
        self.assertEqual(["offhand"], [b.slot for b in buys])

    def test_a_warrior_dual_wields_from_twenty(self):
        young = {
            "class": "warrior",
            "level": 17,
            "purse": 50000,
            "equipped": {"mainhand": 12},
            "skills": {"weapons": {4}},
        }
        self.assertEqual(
            (), gearup.plan_vendor_buys({"Zug": young}, {"Zug": [weapon(self.MACE)]})
        )
