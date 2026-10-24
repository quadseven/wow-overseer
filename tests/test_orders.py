"""The orders module: send, follow and supports over both adapters (#736)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import orders


class FakeMySqlError(Exception):
    pass


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.lastrowid = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        self.db.calls.append((sql, args))
        if self.db.raises:
            raise FakeMySqlError(self.db.raises, "boom")
        if sql.startswith("INSERT"):
            self.lastrowid = self.db.next_id
        self._fetch = self.db.fetch

    def fetchone(self):
        return self._fetch


class FakeDb:
    def __init__(self, fetch=None, raises=0, next_id=7):
        self.calls = []
        self.fetch = fetch
        self.raises = raises
        self.next_id = next_id

    def __call__(self):
        return FakeConn(self)


class FakeConn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self.db)


class SendTests(unittest.TestCase):
    def test_memory_send_returns_ids_and_stores_the_row(self):
        store = orders.MemoryStore()
        a = orders.send(store, orders.Order("Brug", "use", "t", kind="hearth"))
        b = orders.send(store, orders.Order("Brug", "co +x", "t"))
        self.assertEqual((a, b), (1, 2))
        self.assertEqual(store.read(a)["kind"], "hearth")
        self.assertEqual(store.read(a)["status"], "pending")

    def test_memory_send_refuses_an_unknown_verb_with_zero(self):
        store = orders.MemoryStore(kinds={"chat"})
        self.assertEqual(
            orders.send(store, orders.Order("Brug", "x", "t", kind="guild")), 0
        )
        self.assertEqual(store.rows, {})

    def test_mysql_send_writes_only_the_columns_given(self):
        db = FakeDb()
        row_id = orders.send(
            orders.MySqlStore(db),
            orders.Order("Brug", "use", "src", kind="hearth"),
        )
        self.assertEqual(row_id, 7)
        sql, args = db.calls[0]
        self.assertEqual(
            sql,
            "INSERT INTO overseer_command (target_name, command, kind, source) VALUES (%s, %s, %s, %s)",
        )
        self.assertEqual(args, ("Brug", "use", "hearth", "src"))

    def test_mysql_send_includes_target_arg_and_channel(self):
        db = FakeDb()
        orders.send(
            orders.MySqlStore(db),
            orders.Order(
                "Brug", "invite", "s", kind="guild", target_arg="Ugga", channel="say"
            ),
        )
        sql, args = db.calls[0]
        self.assertIn("kind, target_arg, channel, source", sql)
        self.assertEqual(args, ("Brug", "invite", "guild", "Ugga", "say", "s"))

    def test_mysql_send_returns_zero_when_the_realm_lacks_the_machinery(self):
        for code in orders.MISSING_MACHINERY:
            db = FakeDb(raises=code)
            self.assertEqual(
                orders.send(
                    orders.MySqlStore(db), orders.Order("B", "c", "s", kind="guild")
                ),
                0,
            )

    def test_mysql_send_raises_other_errors(self):
        with self.assertRaises(FakeMySqlError):
            orders.send(
                orders.MySqlStore(FakeDb(raises=1205)), orders.Order("B", "c", "s")
            )


class SupportsTests(unittest.TestCase):
    def test_parse_enum(self):
        self.assertEqual(orders.parse_enum("enum('a','b','c')"), frozenset("abc"))
        self.assertIsNone(orders.parse_enum("varchar(20)"))

    def test_mysql_reads_the_enum_once(self):
        db = FakeDb(fetch={"Type": "enum('chat','gm','hearth')"})
        store = orders.MySqlStore(db)
        self.assertTrue(orders.supports(store, "hearth"))
        self.assertFalse(orders.supports(store, "guild"))
        self.assertEqual(len(db.calls), 1)

    def test_plain_command_is_always_supported(self):
        self.assertTrue(orders.supports(orders.MemoryStore(kinds=set()), ""))

    def test_unreadable_enum_answers_true(self):
        self.assertTrue(
            orders.supports(orders.MySqlStore(FakeDb(raises=1146)), "guild")
        )
        self.assertTrue(orders.supports(orders.MemoryStore(), "anything"))

    def test_memory_kinds_gate_supports(self):
        store = orders.MemoryStore(kinds={"chat"})
        self.assertTrue(orders.supports(store, "chat"))
        self.assertFalse(orders.supports(store, "gm"))


class FollowTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def run_follow(self, store, row_id, judge, deadline, poll=1.0):
        return orders.follow(
            store,
            row_id,
            judge,
            deadline,
            poll=poll,
            sleep=self.sleep,
            clock=self.clock,
        )

    def test_returns_as_soon_as_the_judge_says_final(self):
        store = orders.MemoryStore()
        rid = store.insert(orders.Order("B", "c", "s"))
        calls = []

        def judge(row):
            calls.append(row["status"])
            if len(calls) == 2:
                store.answer(rid, "applied")
            return orders.settled(row)

        ans = self.run_follow(store, rid, judge, 10)
        self.assertTrue(ans.final)
        self.assertEqual(ans.value, "applied")
        self.assertEqual(len(self.sleeps), 3)

    def test_waits_before_the_first_read(self):
        store = orders.MemoryStore()
        rid = store.insert(orders.Order("B", "c", "s"))
        store.answer(rid, "applied")
        self.run_follow(store, rid, orders.settled, 5)
        self.assertEqual(self.sleeps, [1.0])

    def test_gives_up_at_the_deadline_with_the_last_answer(self):
        store = orders.MemoryStore()
        rid = store.insert(orders.Order("B", "c", "s"))
        ans = self.run_follow(store, rid, orders.settled, 3)
        self.assertFalse(ans.final)
        self.assertEqual(ans.value, "pending")
        self.assertEqual(len(self.sleeps), 3)

    def test_unreadable_row_ends_the_follow(self):
        ans = self.run_follow(orders.MemoryStore(), 99, orders.settled, 5)
        self.assertTrue(ans.final)
        self.assertIsNone(ans.value)

    def test_zero_deadline_never_reads(self):
        store = orders.MemoryStore()
        ans = self.run_follow(store, 1, orders.settled, 0)
        self.assertEqual((ans.value, ans.final, self.sleeps), (None, False, []))

    def test_mysql_follow_reads_through_the_adapter(self):
        db = FakeDb(
            fetch={"target_name": "B", "status": "applied", "detail": "", "result": ""}
        )
        ans = self.run_follow(orders.MySqlStore(db), 5, orders.settled, 5)
        self.assertEqual((ans.value, ans.final), ("applied", True))
        self.assertEqual(db.calls[0][1], (5,))


class BridgeWiringTests(unittest.TestCase):
    def test_hearth_writer_goes_through_orders(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "bridge.py")).read()
        start = src.index("def _insert_hearth(")
        body = src[start : src.index("\ndef ", start + 10)]
        self.assertIn("orders.send(", body)
        self.assertNotIn("INSERT INTO overseer_command", body)
        self.assertIn('kind="hearth"', body)
        self.assertIn('command="use"', body)

    def test_no_order_in_the_bridge_names_a_grant_verb(self):
        """test_natural_only reads INSERT literals; an order built for
        orders.send has none, so the same rule is checked on the Order call."""
        import re

        sys.path.insert(0, os.path.dirname(__file__))
        import test_natural_only as nat

        src = open(os.path.join(os.path.dirname(__file__), "..", "bridge.py")).read()
        found = re.findall(r"orders\.Order\([^)]*?command=\"([^\"]*)\"", src)
        self.assertTrue(found, "the scan found no orders.Order call to check")
        for lit in found:
            self.assertNotIn(nat._command_verb(lit), nat.GRANT_VERBS, lit)


if __name__ == "__main__":
    unittest.main()
