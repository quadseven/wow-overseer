"""The work order passes run off the event loop and follow the shortfall (#1873).

OFF THE LOOP. `_log_work_orders` and `_request_fire_potion_order` open a DB
connection and block on it. Called straight from the async guild pass or the
async raid supply pass, a slow store stalls every other pass of the bridge up
to the read timeout. Both go through `asyncio.to_thread`, the way the passes'
other reads do; the AST checks below fail on a direct call.

THE SHORTFALL. The raid supply pass hands every guild's lines to one call, and
the store's one open fire potion order is held at the night's whole shortfall:
resized while short, completed when nothing is short.
"""

import ast
import contextlib
import pathlib
import unittest
from unittest import mock

import raidsupply
import workorders
import workorderstore
from test_workorders_store import _store

BRIDGE = pathlib.Path(__file__).resolve().parent.parent / "bridge.py"
SOURCE = BRIDGE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
POTION = "Greater Fire Protection Potion"


def _function(name):
    (node,) = [
        n
        for n in ast.walk(TREE)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    ]
    return node


def _is_to_thread(call):
    f = call.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "to_thread"
        and isinstance(f.value, ast.Name)
        and f.value.id == "asyncio"
    )


def _dispatches(node, target):
    """(awaited to_thread dispatches of `target`, direct calls of `target`)."""
    threaded, direct = 0, 0
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        if _is_to_thread(n):
            first = n.args[0] if n.args else None
            if isinstance(first, ast.Name) and first.id == target:
                threaded += 1
        elif isinstance(n.func, ast.Name) and n.func.id == target:
            direct += 1
    return threaded, direct


def _line(want, have):
    return raidsupply.Line(
        raidsupply.GREATER_FIRE_PROTECTION, POTION, want, have, raidsupply.BUY, ""
    )


class OffTheLoopTest(unittest.TestCase):
    def test_the_guild_pass_plans_work_orders_in_a_thread(self):
        self.assertEqual(
            _dispatches(_function("_guild_share_once"), "_log_work_orders"), (1, 0)
        )

    def test_the_raid_supply_pass_requests_the_fire_potion_in_a_thread(self):
        self.assertEqual(
            _dispatches(_function("_raid_supply_once"), "_request_fire_potion_order"),
            (1, 0),
        )

    def test_no_async_function_calls_either_one_on_the_loop(self):
        for node in ast.walk(TREE):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for target in ("_log_work_orders", "_request_fire_potion_order"):
                self.assertEqual(
                    _dispatches(node, target)[1], 0, "%s in %s" % (target, node.name)
                )


class ShortfallTest(unittest.TestCase):
    """`_request_fire_potion_order` against the real statements on SQLite."""

    def setUp(self):
        from test_guildsocial_bridge import bridge

        self.bridge = bridge
        self.cur = _store()

    def _connect(self):
        cur = self.cur

        @contextlib.contextmanager
        def cursor():
            yield cur

        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.side_effect = cursor
        return conn

    def _run(self, lines):
        with mock.patch.object(self.bridge, "_connect", self._connect):
            self.bridge._request_fire_potion_order(lines)
        return workorderstore.open_orders(self.cur)

    def test_every_guilds_shortfall_is_held_on_one_order(self):
        (held,) = self._run([_line(48, 8), _line(48, 18)])
        self.assertEqual((held.item, held.quantity), (POTION, 70))
        self.assertEqual(held.requested_by, raidsupply.SOURCE)

    def test_a_smaller_shortfall_next_pass_resizes_the_order(self):
        (first,) = self._run([_line(96, 0)])
        (held,) = self._run([_line(96, 60)])
        self.assertEqual((held.order_id, held.quantity), (first.order_id, 36))

    def test_no_shortfall_completes_the_held_order(self):
        (first,) = self._run([_line(96, 0)])
        self.assertEqual(self._run([_line(96, 96), _line(48, 50)]), [])
        self.assertEqual(
            workorderstore.get(self.cur, first.order_id).status, workorders.COMPLETE
        )

    def test_a_night_with_no_fire_potion_line_completes_it_too(self):
        self._run([_line(96, 0)])
        self.assertEqual(self._run([]), [])

    def test_a_store_outage_is_logged_and_does_not_escape(self):
        def down():
            raise self.bridge.pymysql.err.MySQLError("store unavailable")

        with (
            mock.patch.object(self.bridge, "_connect", down),
            self.assertLogs(self.bridge.log, "ERROR") as seen,
        ):
            self.bridge._request_fire_potion_order([_line(96, 0)])
        self.assertIn(
            "workorders: fire potion shortfall could not be stored",
            seen.records[0].getMessage(),
        )


if __name__ == "__main__":
    unittest.main()
