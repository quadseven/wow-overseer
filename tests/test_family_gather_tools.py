"""The family supply pass buys a Mining Pick or a Skinning Knife (ticket 2267).

Item facts: Mining Pick 2901 (BuyPrice 81) and Skinning Knife 7005 (BuyPrice
82), the rows guildjobs.TOOLS already carries; the tests state them here.
"""

import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import craft_rhythm
import craft_supply
import guildcorps
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


class GatherToolNeed(unittest.TestCase):
    def need(self, trades, held=(), at=()):
        return craft_supply.gather_tool_need(
            "Og",
            frozenset(trades),
            frozenset(held),
            town(*at),
            guildjobs.TOOLS,
            guildjobs.TOOL_ENTRIES,
        )

    def test_a_miner_away_from_a_pick_counter_needs_a_pick(self):
        self.assertEqual(
            self.need({MINING}), craft_supply.Need("Og", PICK, "Mining Pick")
        )

    def test_a_skinner_away_from_a_knife_counter_needs_a_knife(self):
        self.assertEqual(
            self.need({SKINNING}), craft_supply.Need("Og", KNIFE, "Skinning Knife")
        )

    def test_no_need_at_a_stocking_counter(self):
        self.assertIsNone(self.need({MINING}, at=(PICK,)))

    def test_no_need_when_the_tool_is_held(self):
        self.assertIsNone(self.need({MINING}, held={PICK}))

    def test_no_need_without_the_trade(self):
        self.assertIsNone(self.need(set()))


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


class BridgeBuyer(unittest.TestCase):
    def run_pass(
        self,
        trades,
        held=None,
        purses=None,
        slots=None,
        at=(PICK, KNIFE),
        pending=False,
    ):
        written = []
        log = Mock()

        def insert(errand):
            if pending:
                return 0, "purchase already pending"
            written.append(errand)
            return len(written), "tool purchase queued"

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
            _insert_gather_tool_errand=insert,
        )
        buyer = load("_buy_gather_tools", ns)
        queued, self.needs = asyncio.run(buyer(SimpleNamespace(), ["Og"]))
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

    def test_no_vendor_returns_the_need_for_the_walk(self):
        self.run_pass({"Og": {MINING}}, at=())
        self.assertEqual(self.needs, [craft_supply.Need("Og", PICK, "Mining Pick")])

    def test_a_stocking_counter_returns_no_need(self):
        self.run_pass({"Og": {MINING}})
        self.assertEqual(self.needs, [])

    def test_a_pending_buy_gets_no_second_row_and_the_log_says_so_once(self):
        queued, written, lines = self.run_pass({"Og": {MINING}}, pending=True)
        self.assertEqual((queued, written), (0, []))
        self.assertEqual(len(lines), 1)
        self.assertIn("already pending", lines[0])

    def test_no_pending_buy_inserts_one_row(self):
        queued, written, _ = self.run_pass({"Og": {MINING}})
        self.assertEqual((queued, len(written)), (1, 1))


class PendingCursor:
    """SQL boundary double for the tool writer: pending state is the database's."""

    def __init__(self, pending=False):
        self.pending = pending
        self.inserts = []
        self.calls = []
        self.result = None
        self.lastrowid = 88

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if sql.startswith("SELECT id FROM overseer_command"):
            self.result = {"id": 71} if self.pending else None
        elif "FOR UPDATE" in sql:
            self.result = {"name": "Og"}
        elif sql.startswith("INSERT INTO overseer_command"):
            self.inserts.append(params)
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def cursor(self):
        return self


class ToolWriter(unittest.TestCase):
    def write(self, cursor):
        ns = dict(_connect=lambda: cursor)
        load("_buy_pending", ns)
        writer = load("_insert_gather_tool_errand", ns)
        errand, _ = craft_supply.gather_tool_errand(
            "Og",
            frozenset({MINING}),
            frozenset(),
            1000,
            3,
            town(PICK),
            guildjobs.TOOLS,
            guildjobs.TOOL_ENTRIES,
        )
        return writer(errand)

    def test_a_pending_row_for_the_entry_blocks_a_second(self):
        cursor = PendingCursor(pending=True)
        self.assertEqual(self.write(cursor), (0, "purchase already pending"))
        self.assertEqual(cursor.inserts, [])

    def test_no_pending_row_inserts_one(self):
        cursor = PendingCursor()
        row_id, _ = self.write(cursor)
        self.assertEqual(row_id, 88)
        self.assertEqual(cursor.inserts, [("Og", "entry:2901 count:1 max:81")])
        pending_sql, pending_params = next(
            c for c in cursor.calls if c[0].startswith("SELECT id")
        )
        self.assertIn("'pending', 'claimed', 'verifying'", pending_sql)
        self.assertIn("entry:2901 ", str(pending_params))


class SupplyPassWiring(unittest.IsolatedAsyncioTestCase):
    def namespace(self, mode="quest"):
        return dict(
            asyncio=asyncio,
            craft_rhythm=craft_rhythm,
            craft_supply=craft_supply,
            guildcorps=guildcorps,
            _names_of=lambda cohort: ["Og"],
            _standing_jobs=lambda family: {"Og": mode},
            _standin_out=lambda: set(),
            _fetch_standing_crafts=lambda names: {},
            log=Mock(),
        )

    def owner(self, needs):
        return SimpleNamespace(
            _dark_iron_once=AsyncMock(),
            _buy_blacksmith_hammers=AsyncMock(return_value=(0, [])),
            _buy_gather_tools=AsyncMock(return_value=(1, needs)),
            _walk_for_hammers=AsyncMock(),
            _walk_for_reagents=AsyncMock(),
        )

    async def test_the_pass_calls_the_tool_buyer_on_a_gather_job(self):
        run = load("_craft_supply_once", self.namespace())
        owner = self.owner([])
        await run(owner, None)
        owner._buy_gather_tools.assert_awaited_once_with(["Og"])

    async def test_the_tool_needs_reach_the_walk(self):
        need = craft_supply.Need("Og", PICK, "Mining Pick")
        run = load("_craft_supply_once", self.namespace())
        owner = self.owner([need])
        await run(owner, None)
        self.assertIn(need, owner._walk_for_hammers.await_args.args[0])

    async def test_a_job_the_pass_does_not_act_on_never_buys_tools(self):
        run = load("_craft_supply_once", self.namespace(mode="dungeon:zulfarrak"))
        owner = self.owner([])
        await run(owner, None)
        owner._buy_gather_tools.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
