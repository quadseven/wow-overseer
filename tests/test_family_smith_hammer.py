"""A smith with no craft standing is sold a Blacksmith Hammer (ticket 2269).

The hammer buy was keyed on the standing craft, so a smith whose family was
out gathering was never offered one. It now keys on the trade held, through
the same buyer that sells the Mining Pick and the Skinning Knife.

Item facts: Blacksmith Hammer 5956, BuyPrice 18, the row
craft_supply.BLACKSMITH_HAMMER already carries; stated here on purpose.
"""

import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import craft
import craft_supply
import familytools
import guildjobs
from towntrip import Town

SMITHING, MINING = guildjobs.BLACKSMITHING, guildjobs.MINING
HAMMER, HAMMER_PRICE, PICK = 5956, 18, 2901
HAMMER_CRAFT = next(
    r.spell_id for r in craft.known_recipes() if r.tool == craft.BLACKSMITH_HAMMER
)
NO_TOOL_CRAFT = next(r.spell_id for r in craft.known_recipes() if not r.tool)

_TREE = ast.parse((Path(__file__).resolve().parents[1] / "bridge.py").read_text())


def load(name, namespace):
    node = next(
        n
        for n in ast.walk(_TREE)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"),
        namespace,
    )
    return namespace[name]


def town(*stocks):
    return Town(repairs=False, stocks=frozenset(stocks), vendor=bool(stocks))


class TheTables(unittest.TestCase):
    def test_the_hammer_is_the_smiths_tool_at_its_vendor_price(self):
        self.assertEqual(
            familytools.TOOLS[SMITHING], (HAMMER, "Blacksmith Hammer", HAMMER_PRICE)
        )
        self.assertEqual(familytools.TOOL_ENTRIES[SMITHING], frozenset({HAMMER}))

    def test_the_gathering_rows_are_the_guild_jobs_rows(self):
        for skill, row in guildjobs.TOOLS.items():
            self.assertEqual(familytools.TOOLS[skill], row)
            self.assertEqual(
                familytools.TOOL_ENTRIES[skill], guildjobs.TOOL_ENTRIES[skill]
            )

    def test_every_tool_has_its_entries(self):
        self.assertEqual(set(familytools.TOOLS), set(familytools.TOOL_ENTRIES))
        for skill, (entry, _label, _price) in familytools.TOOLS.items():
            self.assertIn(entry, familytools.TOOL_ENTRIES[skill])


class TradesOwed(unittest.TestCase):
    def test_a_smith_with_no_craft_standing_is_judged(self):
        self.assertEqual(
            familytools.trades_owed({"Grug": {SMITHING}}, {}), {"Grug": {SMITHING}}
        )
        self.assertEqual(
            familytools.trades_owed({"Grug": {SMITHING}}, {"Grug": (0, 500)}),
            {"Grug": {SMITHING}},
        )

    def test_a_smith_whose_standing_craft_needs_the_hammer_is_left_out(self):
        self.assertEqual(
            familytools.trades_owed(
                {"Grug": {SMITHING}}, {"Grug": (HAMMER_CRAFT, 500)}
            ),
            {},
        )

    def test_that_smith_keeps_its_other_trade(self):
        got = familytools.trades_owed(
            {"Grug": {SMITHING, MINING}}, {"Grug": (HAMMER_CRAFT, 500)}
        )
        self.assertEqual(got, {"Grug": {MINING}})

    def test_a_standing_craft_with_no_tool_does_not_excuse_the_hammer(self):
        got = familytools.trades_owed(
            {"Grug": {SMITHING}}, {"Grug": (NO_TOOL_CRAFT, 500)}
        )
        self.assertEqual(got, {"Grug": {SMITHING}})

    def test_another_members_standing_craft_changes_nothing(self):
        got = familytools.trades_owed({"Grug": {SMITHING}}, {"Og": (HAMMER_CRAFT, 500)})
        self.assertEqual(got, {"Grug": {SMITHING}})

    def test_nothing_in_is_nothing_out(self):
        self.assertEqual(familytools.trades_owed({}, None), {})
        self.assertEqual(familytools.trades_owed(None, None), {})


class TheBuyer(unittest.TestCase):
    """bridge._buy_gather_tools driven, with the database boundary doubled."""

    def run_pass(self, trades, held=None, spells=None, at=(HAMMER, PICK), money=1000):
        written = []
        self.asked = {}

        def holdings(names):
            self.asked["holdings"] = sorted(names)
            return held or {}

        def insert(errand):
            written.append(errand)
            return len(written), "tool purchase queued"

        ns = dict(
            asyncio=asyncio,
            craft_supply=craft_supply,
            familytools=familytools,
            log=Mock(),
            _fetch_gather_trades=lambda names: trades,
            _fetch_tool_holdings=holdings,
            _fetch_purses=lambda names: {n: (20, money) for n in names},
            _fetch_free_slots=lambda names: {n: 3 for n in names},
            _fetch_town=lambda name: town(*at),
            _insert_gather_tool_errand=insert,
        )
        buyer = load("_buy_gather_tools", ns)
        queued, needs = asyncio.run(buyer(SimpleNamespace(), sorted(trades), spells))
        return queued, written, needs

    def test_a_smith_with_no_hammer_and_no_craft_standing_gets_a_hammer_order(self):
        queued, written, needs = self.run_pass({"Grug": {SMITHING}}, spells={})
        self.assertEqual(queued, 1)
        self.assertEqual(
            [(e.member, e.kind, e.command) for e in written],
            [("Grug", "buy", "entry:5956 count:1 max:18")],
        )
        self.assertEqual(needs, [])

    def test_a_smith_who_carries_or_banks_a_hammer_gets_none(self):
        queued, written, needs = self.run_pass(
            {"Grug": {SMITHING}}, held={"Grug": {HAMMER}}, spells={}
        )
        self.assertEqual((queued, written, needs), (0, [], []))

    def test_a_smith_away_from_a_hammer_counter_is_a_need_for_the_walk(self):
        _queued, written, needs = self.run_pass({"Grug": {SMITHING}}, at=())
        self.assertEqual(written, [])
        self.assertEqual(
            needs, [craft_supply.Need("Grug", HAMMER, "Blacksmith Hammer")]
        )

    def test_a_smith_who_cannot_afford_it_gets_no_order(self):
        queued, written, _ = self.run_pass({"Grug": {SMITHING}}, money=HAMMER_PRICE - 1)
        self.assertEqual((queued, written), (0, []))

    def test_a_standing_hammer_craft_is_left_to_the_standing_craft_buyer(self):
        queued, written, needs = self.run_pass(
            {"Grug": {SMITHING}}, spells={"Grug": (HAMMER_CRAFT, 500)}
        )
        self.assertEqual((queued, written, needs), (0, [], []))
        self.assertNotIn("holdings", self.asked)

    def test_a_pick_does_not_count_as_a_hammer(self):
        _queued, written, _ = self.run_pass(
            {"Grug": {SMITHING}}, held={"Grug": {PICK}}, spells={}
        )
        self.assertEqual([e.command for e in written], ["entry:5956 count:1 max:18"])


class TheReads(unittest.TestCase):
    """The two reads ask for the smith's trade and the hammer's entry."""

    class Cursor:
        def __init__(self, rows):
            self.rows, self.calls = rows, []

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchall(self):
            return self.rows

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def test_the_trades_read_asks_for_blacksmithing(self):
        cursor = self.Cursor([{"name": "Grug", "skill": SMITHING}])
        ns = dict(familytools=familytools, _connect=lambda: cursor)
        got = load("_fetch_gather_trades", ns)(["Grug"])
        self.assertEqual(got, {"Grug": {SMITHING}})
        self.assertIn(SMITHING, cursor.calls[0][1])

    def test_the_holdings_read_asks_for_the_hammer(self):
        cursor = self.Cursor([{"name": "Grug", "entry": HAMMER}])
        ns = dict(familytools=familytools, _connect=lambda: cursor)
        got = load("_fetch_tool_holdings", ns)(["Grug"])
        self.assertEqual(got, {"Grug": {HAMMER}})
        self.assertIn(HAMMER, cursor.calls[0][1])


class TheSupplyPass(unittest.IsolatedAsyncioTestCase):
    async def test_the_pass_hands_the_buyer_its_standing_crafts(self):
        import craft_rhythm
        import guildcorps
        import individual
        from unittest.mock import AsyncMock

        spells = {"Grug": (NO_TOOL_CRAFT, 500)}
        ns = dict(
            asyncio=asyncio,
            craft_rhythm=craft_rhythm,
            craft_supply=craft_supply,
            guildcorps=guildcorps,
            individual=individual,
            _names_of=lambda cohort: ["Grug"],
            _individual_family=lambda cohort=None: None,
            _standing_jobs=lambda family: {"Grug": "quest"},
            _standin_out=lambda: set(),
            _fetch_standing_crafts=lambda names: spells,
            log=Mock(),
        )
        owner = SimpleNamespace(
            _dark_iron_once=AsyncMock(),
            _buy_blacksmith_hammers=AsyncMock(return_value=(0, [])),
            _buy_gather_tools=AsyncMock(return_value=(0, [])),
            _buy_fishing_poles=AsyncMock(return_value=(0, 0)),
            _walk_for_hammers=AsyncMock(),
            _walk_for_reagents=AsyncMock(),
        )
        await load("_craft_supply_once", ns)(owner, None)
        owner._buy_gather_tools.assert_awaited_once_with(["Grug"], spells)


if __name__ == "__main__":
    unittest.main()
