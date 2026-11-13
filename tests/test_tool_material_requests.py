"""Tool events use the existing hammer buyer without repeat purchase rows."""

import ast
import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import craft
import craft_rhythm
import craft_supply
import individual
import towntrip


def row(**changes):
    value = dict(
        id=11,
        occurrences=1,
        character_name="Smith",
        subject_id=2666,
        item_guid=5956,
        detail="need 1x Blacksmith Hammer (a tool, kept in the bank)",
        age=0,
    )
    value.update(changes)
    return value


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


class ToolRequest(unittest.TestCase):
    def test_actual_module_row_is_a_tool_and_not_a_reagent(self):
        request = craft_rhythm.tool_request(row())
        self.assertEqual(
            (request.character, request.recipe, request.entry), ("Smith", 2666, 5956)
        )
        self.assertEqual((request.event_id, request.occurrence), (11, 1))
        self.assertIsNone(craft_rhythm.material_request(row()))

    def test_malformed_and_reagent_rows_are_not_tools(self):
        for changes in (
            {"detail": "short 1x Copper Bar (needs 1, has 0)"},
            {"item_guid": 0},
            {"character_name": ""},
            {"id": 0},
            {"subject_id": 0},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(craft_rhythm.tool_request(row(**changes)))


class HammerWriter(unittest.TestCase):
    def test_repeated_request_uses_one_pending_purchase(self):
        requests = [craft_rhythm.tool_request(row())]
        written = []

        def insert(errand, recipe):
            if written:
                return 0, "purchase already pending"
            written.append((errand, recipe))
            return 71, "hammer purchase queued"

        ns = dict(
            asyncio=asyncio,
            craft=craft,
            craft_supply=craft_supply,
            craft_rhythm=craft_rhythm,
            time=time,
            log=logging.getLogger(__name__),
            _fetch_tool_requests=lambda names: requests,
            _fetch_hammer_holders=lambda names: set(),
            _fetch_free_slots=lambda names: {"Smith": 1},
            _fetch_town=lambda name: towntrip.Town(
                repairs=False, stocks=frozenset({5956}), vendor=True
            ),
            _insert_hammer_errand=insert,
            _insert_town_errand=Mock(return_value=71),
        )
        buyer = load("_buy_blacksmith_hammers", ns)
        owner = SimpleNamespace(_tool_requests={})
        owner._tool_request_note = lambda *args, **kwargs: None
        current = load("_current_tool_requests", ns)
        owner._current_tool_requests = lambda spells, names: current(
            owner, spells, names
        )
        asyncio.run(buyer(owner, {"Smith": (2666, 10000)}))
        asyncio.run(buyer(owner, {"Smith": (2666, 10000)}))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0][0].member, "Smith")
        ns["_insert_town_errand"].assert_not_called()


class PurchaseCursor:
    """Small SQL boundary double; ownership and pending state survive restarts."""

    def __init__(self, *, job="craft", recipe=2666, owned=False, pending=False):
        self.standing = {"craft_spell": recipe, "job": job}
        self.owned = owned
        self.pending = pending
        self.lastrowid = 71
        self.calls = []
        self.result = None
        self.inserts = 0

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "FOR UPDATE" in sql:
            self.result = self.standing
        elif "character_inventory" in sql:
            self.result = {"guid": 101} if self.owned else None
        elif sql.startswith("SELECT id FROM overseer_command"):
            self.result = {"id": 71} if self.pending else None
        elif sql.startswith("INSERT INTO overseer_command"):
            self.inserts += 1
            self.pending = True
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PurchaseConnection:
    def __init__(self, cursor):
        self.cur = cursor
        self.events = []

    def cursor(self):
        return self.cur

    def begin(self):
        self.events.append("begin")

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def purchase(cursor):
    connection = PurchaseConnection(cursor)
    ns = dict(craft=craft, craft_rhythm=craft_rhythm, _connect=lambda: connection)
    load("_hammer_purchase", ns)
    load("_buy_pending", ns)
    writer = load("_insert_hammer_errand", ns)
    errand, _ = craft_supply.hammer_errand(
        "Smith",
        2666,
        False,
        10000,
        1,
        towntrip.Town(repairs=False, stocks=frozenset({5956}), vendor=True),
    )
    return writer, errand, connection


class TransactionalHammerWriter(unittest.TestCase):
    def test_restart_with_pending_buy_cannot_insert_another(self):
        cursor = PurchaseCursor()
        writer, errand, connection = purchase(cursor)
        self.assertEqual(writer(errand, 2666), (71, "hammer purchase queued"))
        writer, errand, restarted = purchase(cursor)
        self.assertEqual(writer(errand, 2666), (0, "purchase already pending"))
        self.assertEqual(cursor.inserts, 1)
        self.assertEqual(connection.events, ["begin", "commit"])
        self.assertEqual(restarted.events, ["begin", "commit"])
        self.assertIn("FOR UPDATE", cursor.calls[0][0])
        pending_sql = next(sql for sql, _ in cursor.calls if "status IN" in sql)
        self.assertIn("'pending', 'claimed', 'verifying'", pending_sql)

    def test_completed_purchase_owned_in_bags_or_bank_is_not_bought_again(self):
        cursor = PurchaseCursor(owned=True)
        writer, errand, _ = purchase(cursor)
        self.assertEqual(writer(errand, 2666), (0, "hammer already owned"))
        self.assertEqual(cursor.inserts, 0)
        inventory_sql = cursor.calls[1][0]
        self.assertIn("character_inventory", inventory_sql)
        self.assertNotIn("slot", inventory_sql)

    def test_changed_job_or_recipe_refuses_before_inventory_or_command_write(self):
        for changes in ({"job": "dungeon:zulfarrak"}, {"recipe": 3337}):
            with self.subTest(changes=changes):
                cursor = PurchaseCursor(**changes)
                writer, errand, _ = purchase(cursor)
                self.assertEqual(
                    writer(errand, 2666), (0, "standing recipe or job changed")
                )
                self.assertEqual(len(cursor.calls), 1)
                self.assertEqual(cursor.inserts, 0)

    def test_failed_purchase_can_retry_when_no_command_remains_active(self):
        cursor = PurchaseCursor(pending=True)
        writer, errand, _ = purchase(cursor)
        self.assertEqual(writer(errand, 2666)[0], 0)
        cursor.pending = False
        self.assertEqual(writer(errand, 2666)[0], 71)

    def test_database_failure_rolls_back_and_propagates(self):
        cursor = PurchaseCursor()
        cursor.execute = Mock(side_effect=RuntimeError("database unavailable"))
        writer, errand, connection = purchase(cursor)
        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            writer(errand, 2666)
        self.assertEqual(connection.events, ["begin", "rollback"])


class EventDrivenHammerPass(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = [craft_rhythm.tool_request(row())]
        self.town = towntrip.Town(repairs=False, stocks=frozenset(), vendor=False)
        self.holders = set()
        self.cursor = PurchaseCursor()
        writer, _, _ = purchase(self.cursor)
        self.logger = Mock()
        self.namespace = dict(
            asyncio=asyncio,
            craft=craft,
            craft_supply=craft_supply,
            craft_rhythm=craft_rhythm,
            time=time,
            log=self.logger,
            _fetch_tool_requests=lambda names: self.requests,
            _fetch_hammer_holders=lambda names: self.holders,
            _fetch_free_slots=lambda names: {"Smith": 1},
            _fetch_town=lambda name: self.town,
            _insert_hammer_errand=writer,
        )
        self.buyer = load("_buy_blacksmith_hammers", self.namespace)
        self.note = load("_tool_request_note", self.namespace)
        current = load("_current_tool_requests", self.namespace)
        self.owner = SimpleNamespace(_tool_requests={})
        self.owner._current_tool_requests = lambda spells, names: current(
            self.owner, spells, names
        )
        self.owner._tool_request_note = lambda *args, **kw: self.note(
            self.owner, *args, **kw
        )

    async def run_pass(self, spells=None):
        return await self.buyer(self.owner, spells or {"Smith": (2666, 10000)})

    async def test_vendor_arrival_retries_without_repeating_refusal(self):
        for _ in range(2):
            queued, needs = await self.run_pass()
            self.assertEqual(queued, 0)
            self.assertEqual([need.entry for need in needs], [5956])
        self.assertEqual(self.logger.info.call_count, 1)
        self.town = towntrip.Town(repairs=False, stocks=frozenset({5956}), vendor=True)
        self.assertEqual((await self.run_pass())[0], 1)
        self.assertEqual(self.logger.info.call_count, 2)
        self.assertEqual((await self.run_pass())[0], 0)
        self.assertEqual(self.cursor.inserts, 1)
        self.assertEqual(self.logger.info.call_count, 2)

    async def test_restored_diagnostic_and_new_occurrence(self):
        await self.run_pass()
        saved = {
            key: craft_rhythm.route_memo(value, 1000)
            for key, value in self.owner._tool_requests.items()
        }
        self.owner._tool_requests = {
            key: craft_rhythm.route_from_memo(value, 1000)
            for key, value in saved.items()
        }
        await self.run_pass()
        self.assertEqual(self.logger.info.call_count, 1)
        self.requests = [craft_rhythm.tool_request(row(occurrences=2))]
        await self.run_pass()
        self.assertEqual(self.logger.info.call_count, 2)

    async def test_owned_tool_handles_event_without_purchase_or_walk(self):
        self.holders.add("Smith")
        self.assertEqual(await self.run_pass(), (0, []))
        self.assertEqual(self.cursor.inserts, 0)
        self.assertTrue(self.owner._tool_requests["11:1"].closed)

    async def test_stale_recipe_does_not_restore_cleared_craft(self):
        self.assertEqual(await self.run_pass({"Smith": (3337, 10000)}), (0, []))
        self.assertEqual(self.cursor.inserts, 0)
        self.assertIn("no longer matches", self.owner._tool_requests["11:1"].why)

    async def test_cleared_recipe_event_is_refused_once(self):
        for _ in range(2):
            self.assertEqual(await self.buyer(self.owner, {}, ["Smith"]), (0, []))
        self.assertEqual(self.cursor.inserts, 0)
        self.assertEqual(self.logger.info.call_count, 1)
        self.assertFalse(self.owner._tool_requests["11:1"].closed)

    async def test_job_change_before_write_is_not_marked_handled(self):
        self.town = towntrip.Town(repairs=False, stocks=frozenset({5956}), vendor=True)
        self.cursor.standing["job"] = "dungeon:zulfarrak"
        self.assertEqual((await self.run_pass())[0], 0)
        self.assertFalse(self.owner._tool_requests["11:1"].closed)
        self.assertEqual(self.cursor.inserts, 0)


class EventReader(unittest.TestCase):
    def test_actual_tool_row_is_read_without_reagent_misrouting_or_warning(self):
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchall.return_value = [row()]
        connection = PurchaseConnection(cursor)
        logger = Mock()
        ns = dict(
            craft_rhythm=craft_rhythm,
            _connect=lambda: connection,
            _MATERIAL_REQUEST_SQL="SELECT * WHERE name IN (%s)",
            log=logger,
            pymysql=SimpleNamespace(err=SimpleNamespace(MySQLError=RuntimeError)),
        )
        reader = load("_fetch_material_requests", ns)
        self.assertEqual(reader(["Smith"]), [])
        requests = reader(["Smith"], tools=True)
        self.assertEqual([request.entry for request in requests], [5956])
        self.assertEqual(requests[0].event_id, 11)
        logger.warning.assert_not_called()


class FamilyModeGuard(unittest.IsolatedAsyncioTestCase):
    async def test_dungeon_mode_never_reaches_tool_reader_or_buyer(self):
        reader = Mock()
        ns = dict(
            asyncio=asyncio,
            craft_rhythm=craft_rhythm,
            craft_supply=craft_supply,
            _names_of=lambda cohort: ["Smith"],
            individual=individual,
            _standing_jobs=lambda family: {"Smith": "dungeon:zulfarrak"},
            _standin_out=lambda: set(),
            _fetch_standing_crafts=reader,
            log=Mock(),
        )
        run = load("_craft_supply_once", ns)
        owner = SimpleNamespace(
            _dark_iron_once=AsyncMock(), _buy_blacksmith_hammers=AsyncMock()
        )
        await run(owner, None)
        reader.assert_not_called()
        owner._buy_blacksmith_hammers.assert_not_awaited()
