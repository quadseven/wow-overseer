"""The work order store: request an order, keep it between passes (#1487).

THE STATEMENTS RUN FOR REAL. Every test drives workorderstore.py's own SQL
against an in-memory SQLite table with the same columns as CREATE_SQL, through
a cursor that speaks the bridge's dialect: `%s` placeholders and rows as dicts
(pymysql's DictCursor). What is pinned is what the statements do, including
the guards in their WHERE clauses, not how they are spelled.

A "pass" here is what the bridge's guild pass will do with the store: read the
open orders, plan them with workorders.plan, and save the assignments.
"""

import ast
import dataclasses
import pathlib
import sqlite3
import unittest

import goals
import raidsupply
import workorders
import workorderstore

ALCHEMY = goals.SKILL_IDS["alchemy"]
HERBALISM = goals.SKILL_IDS["herbalism"]

# CREATE_SQL's columns in SQLite's words. ColumnsTest keeps the two in step.
SQLITE_CREATE = (
    "CREATE TABLE overseer_work_order ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " kind TEXT NOT NULL,"
    " item TEXT NOT NULL,"
    " quantity INTEGER NOT NULL DEFAULT 0,"
    " zone TEXT NOT NULL DEFAULT '',"
    " requested_by TEXT NOT NULL DEFAULT '',"
    " status TEXT NOT NULL DEFAULT 'requested',"
    " assigned_to TEXT NOT NULL DEFAULT '',"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " assigned_at TIMESTAMP NULL DEFAULT NULL,"
    " completed_at TIMESTAMP NULL DEFAULT NULL)"
)
COLUMNS = (
    "id",
    "kind",
    "item",
    "quantity",
    "zone",
    "requested_by",
    "status",
    "assigned_to",
    "created_at",
    "assigned_at",
    "completed_at",
)


class DictCursor:
    """A DB-API cursor over SQLite that takes `%s` and returns dict rows."""

    def __init__(self, conn):
        self._cur = conn.cursor()

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("%s", "?"), tuple(params))
        return self._cur.rowcount

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else dict(row)

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid


def _store():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(SQLITE_CREATE)
    return DictCursor(conn)


def _member(name, level=40, skills=None):
    return workorders.WorkMember(
        name=name, level=level, online=True, skills=skills or {}
    )


def _pass(cur, members):
    """One bridge pass: read the open orders, plan them, save the plan."""
    plan = workorders.plan(workorderstore.open_orders(cur), members)
    workorderstore.save_plan(cur, plan)
    return plan


class RequestTest(unittest.TestCase):
    def test_a_consumable_order_reads_back_with_its_quantity_and_status(self):
        cur = _store()
        order_id = workorderstore.request(
            cur, workorders.consumable("Greater Fire Protection Potion", 96)
        )
        got = workorderstore.get(cur, order_id)
        self.assertEqual(got.kind, workorders.CONSUMABLE)
        self.assertEqual(got.item, "Greater Fire Protection Potion")
        self.assertEqual(got.quantity, 96)
        self.assertEqual(got.status, workorders.REQUESTED)
        self.assertEqual(got.assigned_to, "")
        self.assertEqual(got.order_id, order_id)

    def test_a_farming_order_reads_back_with_its_item_and_zone(self):
        cur = _store()
        order_id = workorderstore.request(
            cur, workorders.farming("Firebloom", "Searing Gorge")
        )
        got = workorderstore.get(cur, order_id)
        self.assertEqual(got.kind, workorders.FARMING)
        self.assertEqual(got.item, "Firebloom")
        self.assertEqual(got.zone, "Searing Gorge")
        self.assertEqual(got.status, workorders.REQUESTED)

    def test_an_unknown_id_reads_back_as_none(self):
        self.assertIsNone(workorderstore.get(_store(), 404))

    def test_asking_again_for_an_open_order_keeps_the_one_already_held(self):
        cur = _store()
        first = workorderstore.request(
            cur, workorders.consumable("Greater Fire Protection Potion", 96)
        )
        again = workorderstore.request(
            cur, workorders.consumable("greater fire protection potion", 40)
        )
        self.assertEqual(again, first)
        self.assertEqual(len(workorderstore.open_orders(cur)), 1)
        self.assertEqual(workorderstore.get(cur, first).quantity, 96)

    def test_a_completed_order_does_not_block_a_new_request(self):
        cur = _store()
        first = workorderstore.request(
            cur, workorders.farming("Firebloom", "Searing Gorge")
        )
        _pass(cur, [_member("Ugga", skills={HERBALISM: 250})])
        self.assertTrue(workorderstore.report(cur, first, "Ugga"))
        second = workorderstore.request(
            cur, workorders.farming("Firebloom", "Searing Gorge")
        )
        self.assertNotEqual(second, first)

    def test_an_order_with_no_quantity_or_no_zone_is_refused(self):
        with self.assertRaises(ValueError):
            workorders.consumable("Greater Fire Protection Potion", 0)
        with self.assertRaises(ValueError):
            workorders.farming("Firebloom", " ")
        with self.assertRaises(ValueError):
            workorders.consumable(" ", 5)


class AssigneeAcrossPassesTest(unittest.TestCase):
    def test_an_assigned_order_keeps_its_assignee_across_two_passes(self):
        cur = _store()
        order_id = workorderstore.request(
            cur, workorders.consumable("Greater Fire Protection Potion", 96)
        )
        first = _pass(cur, [_member("Zug", level=50, skills={ALCHEMY: 300})])
        self.assertEqual([a.taker for a in first.assignments], ["Zug"])

        # Next pass a lower-level alchemist is online, who would go first
        # for a requested order. The held order is not handed to her.
        second = _pass(
            cur,
            [
                _member("Zug", level=50, skills={ALCHEMY: 300}),
                _member("Ugga", level=20, skills={ALCHEMY: 120}),
            ],
        )
        self.assertEqual(second.assignments, ())
        got = workorderstore.get(cur, order_id)
        self.assertEqual(got.status, workorders.ASSIGNED)
        self.assertEqual(got.assigned_to, "Zug")

    def test_the_store_refuses_to_reassign_an_assigned_order(self):
        cur = _store()
        order_id = workorderstore.request(
            cur, workorders.consumable("Greater Fire Protection Potion", 96)
        )
        _pass(cur, [_member("Zug", skills={ALCHEMY: 300})])
        held = workorderstore.get(cur, order_id)
        forged = workorders.WorkOrderPlan(
            (
                workorders.WorkAssignment(
                    dataclasses.replace(held, assigned_to="Ugga"), "Ugga"
                ),
            )
        )
        self.assertEqual(workorderstore.save_plan(cur, forged), 0)
        self.assertEqual(workorderstore.get(cur, order_id).assigned_to, "Zug")

    def test_a_standing_order_with_no_id_is_not_saved(self):
        cur = _store()
        plan = workorders.plan(
            workorders.STANDING_ORDERS,
            [
                workorders.WorkMember(
                    "Og", 58, True, {goals.SKILL_IDS["tailoring"]: 300}
                )
            ],
        )
        self.assertEqual(len(plan.assignments), 1)
        self.assertEqual(workorderstore.save_plan(cur, plan), 0)
        self.assertEqual(workorderstore.open_orders(cur), [])


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.cur = _store()
        self.order_id = workorderstore.request(
            self.cur, workorders.farming("Firebloom", "Searing Gorge")
        )
        _pass(self.cur, [_member("Ugga", skills={HERBALISM: 250})])

    def test_the_assignees_report_completes_the_order(self):
        self.assertTrue(workorderstore.report(self.cur, self.order_id, "Ugga"))
        got = workorderstore.get(self.cur, self.order_id)
        self.assertEqual(got.status, workorders.COMPLETE)
        self.assertEqual(got.assigned_to, "Ugga")
        self.assertEqual(workorderstore.open_orders(self.cur), [])

    def test_a_report_from_anyone_else_is_refused(self):
        self.assertFalse(workorderstore.report(self.cur, self.order_id, "Zug"))
        got = workorderstore.get(self.cur, self.order_id)
        self.assertEqual(got.status, workorders.ASSIGNED)
        self.assertEqual(got.assigned_to, "Ugga")

    def test_a_report_on_a_requested_order_is_refused(self):
        other = workorderstore.request(
            self.cur, workorders.consumable("Greater Fire Protection Potion", 96)
        )
        self.assertFalse(workorderstore.report(self.cur, other, ""))
        self.assertEqual(
            workorderstore.get(self.cur, other).status, workorders.REQUESTED
        )

    def test_a_second_report_changes_nothing(self):
        self.assertTrue(workorderstore.report(self.cur, self.order_id, "Ugga"))
        self.assertFalse(workorderstore.report(self.cur, self.order_id, "Ugga"))


class RaidSupplyIntakeTest(unittest.TestCase):
    """The raid night's measured fire potion gap is the first intake."""

    def _line(self, want, have):
        return raidsupply.Line(
            raidsupply.GREATER_FIRE_PROTECTION,
            "Greater Fire Protection Potion",
            want,
            have,
            raidsupply.BUY,
            "",
        )

    def test_the_greater_fire_protection_shortfall_becomes_a_consumable_order(self):
        order = raidsupply.fire_potion_order([self._line(96, 10)])
        self.assertEqual(order.kind, workorders.CONSUMABLE)
        self.assertEqual(order.item, "Greater Fire Protection Potion")
        self.assertEqual(order.quantity, 86)
        self.assertEqual(order.requested_by, raidsupply.SOURCE)
        self.assertEqual(order.status, workorders.REQUESTED)

    def test_no_shortfall_asks_for_nothing(self):
        self.assertIsNone(raidsupply.fire_potion_order([self._line(96, 96)]))
        self.assertIsNone(raidsupply.fire_potion_order([]))

    def test_the_intake_order_goes_into_the_store_once(self):
        cur = _store()
        order = raidsupply.fire_potion_order([self._line(96, 0)])
        first = workorderstore.request(cur, order)
        self.assertEqual(workorderstore.request(cur, order), first)
        self.assertEqual(workorderstore.get(cur, first).quantity, 96)


class ReconcileTest(unittest.TestCase):
    """The held order follows the measured shortfall and closes at none (#1873)."""

    ITEM = "Greater Fire Protection Potion"

    def _held(self, cur, quantity=96):
        return workorderstore.request(
            cur, workorders.consumable(self.ITEM, quantity, requested_by="raidsupply")
        )

    def test_a_smaller_shortfall_updates_the_held_order(self):
        cur = _store()
        held = self._held(cur)
        self.assertEqual(
            workorderstore.reconcile(cur, workorders.CONSUMABLE, self.ITEM, 40), 1
        )
        order = workorderstore.get(cur, held)
        self.assertEqual(order.quantity, 40)
        self.assertEqual(order.status, workorders.REQUESTED)

    def test_an_assigned_order_keeps_its_assignee_while_its_quantity_moves(self):
        cur = _store()
        held = self._held(cur)
        _pass(cur, [_member("Ugga", skills={ALCHEMY: 300})])
        workorderstore.reconcile(cur, workorders.CONSUMABLE, self.ITEM.lower(), 12)
        order = workorderstore.get(cur, held)
        self.assertEqual(
            (order.quantity, order.status, order.assigned_to),
            (12, workorders.ASSIGNED, "Ugga"),
        )

    def test_no_shortfall_completes_the_held_order(self):
        cur = _store()
        held = self._held(cur)
        _pass(cur, [_member("Ugga", skills={ALCHEMY: 300})])
        self.assertEqual(
            workorderstore.reconcile(cur, workorders.CONSUMABLE, self.ITEM, 0), 1
        )
        self.assertEqual(workorderstore.get(cur, held).status, workorders.COMPLETE)
        self.assertEqual(workorderstore.open_orders(cur), [])
        self.assertNotEqual(self._held(cur, 30), held)

    def test_nothing_held_moves_nothing_and_adds_nothing(self):
        cur = _store()
        self.assertEqual(
            workorderstore.reconcile(cur, workorders.CONSUMABLE, self.ITEM, 0), 0
        )
        self.assertEqual(
            workorderstore.reconcile(cur, workorders.CONSUMABLE, self.ITEM, 9), 0
        )
        self.assertEqual(workorderstore.open_orders(cur), [])

    def test_a_completed_order_is_not_reopened_or_resized(self):
        cur = _store()
        held = self._held(cur)
        workorderstore.reconcile(cur, workorders.CONSUMABLE, self.ITEM, 0)
        workorderstore.reconcile(cur, workorders.CONSUMABLE, self.ITEM, 50)
        order = workorderstore.get(cur, held)
        self.assertEqual((order.status, order.quantity), (workorders.COMPLETE, 96))

    def test_the_settle_statements_carry_their_status_guard(self):
        for sql in (workorderstore.RESIZE_SQL, workorderstore.SETTLE_SQL):
            self.assertIn("status IN ('requested', 'assigned')", sql)


class ColumnsTest(unittest.TestCase):
    """CREATE_SQL, the SQLite copy above and the read all name one column set."""

    def test_create_sql_names_every_column(self):
        for column in COLUMNS:
            self.assertIn(" %s " % column, workorderstore.CREATE_SQL)

    def test_create_sql_is_the_bridge_owned_table_shape(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS overseer_work_order", workorderstore.CREATE_SQL
        )
        self.assertIn("COLLATE=utf8mb4_0900_ai_ci", workorderstore.CREATE_SQL)
        self.assertEqual(workorderstore.TABLE, "overseer_work_order")


class StartUpTest(unittest.TestCase):
    """The bridge creates the table at start-up, beside the order record."""

    def test_the_order_store_ensure_creates_the_work_order_table(self):
        path = pathlib.Path(__file__).resolve().parent.parent / "bridge.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        (node,) = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_ensure_order_store"
        ]
        body = ast.get_source_segment(source, node)
        self.assertIn("cur.execute(workorderstore.CREATE_SQL)", body)
        self.assertIn("import workorderstore\n", source)


if __name__ == "__main__":
    unittest.main()
