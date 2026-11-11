"""The family supply pass buys a Mining Pick or a Skinning Knife (ticket 2267).

Item facts: Mining Pick 2901 (BuyPrice 81) and Skinning Knife 7005 (BuyPrice
82), the rows guildjobs.TOOLS already carries; the tests state them here.
"""

import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import craft_supply
import guildjobs
from towntrip import Town

MINING, SKINNING = guildjobs.MINING, guildjobs.SKINNING
PICK, KNIFE = 2901, 7005
PICK_PRICE = 81
OTHER_MINING_TOOL = 1819  # an entry guildjobs.TOOL_ENTRIES also accepts for Mining


def town(*stocks):
    return Town(repairs=False, stocks=frozenset(stocks), vendor=bool(stocks))


class GatherToolErrand(unittest.TestCase):
    def ask(self, trades, held=(), money=1000, slots=5, at=(PICK, KNIFE)):
        return craft_supply.gather_tool_errand(
            "Og",
            frozenset(trades),
            frozenset(held),
            money,
            slots,
            town(*at),
            guildjobs.TOOLS,
            guildjobs.TOOL_ENTRIES,
        )

    def test_a_miner_with_no_pick_gets_a_pick_order(self):
        errand, note = self.ask({MINING})
        self.assertIsNone(note)
        self.assertEqual(errand.kind, "buy")
        self.assertEqual(errand.member, "Og")
        self.assertEqual(errand.command, "entry:2901 count:1 max:81")

    def test_a_skinner_with_no_knife_gets_a_knife_order(self):
        errand, note = self.ask({SKINNING})
        self.assertIsNone(note)
        self.assertEqual(errand.command, "entry:7005 count:1 max:82")

    def test_a_carried_or_banked_tool_gets_no_order(self):
        self.assertEqual(self.ask({MINING}, held={PICK}), (None, None))
        self.assertEqual(self.ask({SKINNING}, held={KNIFE}), (None, None))

    def test_another_tool_of_the_same_trade_counts_as_held(self):
        self.assertEqual(self.ask({MINING}, held={OTHER_MINING_TOOL}), (None, None))

    def test_no_trade_means_no_order(self):
        self.assertEqual(self.ask(set()), (None, None))

    def test_the_other_trades_tool_does_not_count(self):
        errand, _ = self.ask({MINING}, held={KNIFE})
        self.assertEqual(errand.command, "entry:2901 count:1 max:81")

    def test_no_free_bag_slot_is_a_named_note(self):
        errand, note = self.ask({MINING}, slots=0)
        self.assertIsNone(errand)
        self.assertIn("no free bag slot", note)

    def test_a_short_purse_is_a_named_note(self):
        errand, note = self.ask({MINING}, money=PICK_PRICE - 1)
        self.assertIsNone(errand)
        self.assertIn("cannot afford", note)

    def test_no_vendor_in_reach_is_a_named_note(self):
        errand, note = self.ask({MINING}, at=())
        self.assertIsNone(errand)
        self.assertIn("no reachable vendor", note)

    def test_a_member_short_of_two_tools_gets_one_order_per_pass(self):
        errand, _ = self.ask({MINING, SKINNING})
        self.assertEqual(errand.command, "entry:2901 count:1 max:81")
        errand, _ = self.ask({MINING, SKINNING}, held={PICK})
        self.assertEqual(errand.command, "entry:7005 count:1 max:82")


_TREE = ast.parse((Path(__file__).resolve().parents[1] / "bridge.py").read_text())


def load(name, namespace):
    node = next(
        n
        for n in ast.walk(_TREE)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == name
    )
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"),
        namespace,
    )
    return namespace[name]


class BridgeBuyer(unittest.TestCase):
    def run_pass(self, trades, held=None, purses=None, slots=None, at=(PICK, KNIFE)):
        written = []
        log = Mock()
        ns = dict(
            asyncio=asyncio,
            craft_supply=craft_supply,
            guildjobs=guildjobs,
            log=log,
            _fetch_gather_trades=lambda names: trades,
            _fetch_tool_holdings=lambda names: held or {},
            _fetch_purses=lambda names: purses or {"Og": (20, 1000)},
            _fetch_free_slots=lambda names: slots if slots is not None else {"Og": 3},
            _fetch_town=lambda name: town(*at),
            _insert_town_errand=lambda errand: written.append(errand) or len(written),
        )
        buyer = load("_buy_gather_tools", ns)
        queued = asyncio.run(buyer(SimpleNamespace(), ["Og"]))
        lines = [call.args[0] % call.args[1:] for call in log.info.call_args_list]
        return queued, written, lines

    def test_the_miner_is_sent_a_pick_order(self):
        queued, written, _ = self.run_pass({"Og": {MINING}})
        self.assertEqual(queued, 1)
        self.assertEqual(
            [(e.member, e.kind, e.command) for e in written],
            [("Og", "buy", "entry:2901 count:1 max:81")],
        )

    def test_the_skinner_is_sent_a_knife_order(self):
        _, written, _ = self.run_pass({"Og": {SKINNING}})
        self.assertEqual([e.command for e in written], ["entry:7005 count:1 max:82"])

    def test_a_holder_is_sent_nothing_and_logs_nothing(self):
        queued, written, lines = self.run_pass({"Og": {MINING}}, held={"Og": {PICK}})
        self.assertEqual((queued, written, lines), (0, [], []))

    def test_a_full_bag_logs_its_reason_once(self):
        queued, written, lines = self.run_pass({"Og": {MINING}}, slots={"Og": 0})
        self.assertEqual((queued, written), (0, []))
        self.assertEqual(len(lines), 1)
        self.assertIn("no free bag slot", lines[0])

    def test_a_short_purse_logs_its_reason_once(self):
        queued, written, lines = self.run_pass({"Og": {MINING}}, purses={"Og": (20, 5)})
        self.assertEqual((queued, written), (0, []))
        self.assertEqual(len(lines), 1)
        self.assertIn("cannot afford", lines[0])

    def test_no_vendor_logs_its_reason_once(self):
        _, written, lines = self.run_pass({"Og": {MINING}}, at=())
        self.assertEqual(written, [])
        self.assertEqual(len(lines), 1)
        self.assertIn("no reachable vendor", lines[0])


if __name__ == "__main__":
    unittest.main()
