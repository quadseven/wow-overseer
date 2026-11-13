"""A letter the holder's mailbox has not loaded is not read as waiting (#2402).

Measured on the dev realm 2026-11-13: eight letters written into `mail` while
their holders were online came back `no mail with that id` on every take. The
town errand's mail step planned them every pass and ran its whole window, and
counted as bought gear they started a fresh errand after each restart. The
bridge's one mail read now leaves such a letter out until its holder logs in
again, so every pass that plans from it (the mail pass, the passing take, the
town errand, the gear count, the guild jobs) stops asking for it.
"""

import contextlib
import unittest
from unittest import mock

from test_guildsocial_bridge import bridge


class FakeCursor:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []
        self._rows = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        self._rows = self.results.pop(0) if self.results else []

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def letter(holder, mail_id, item):
    return {
        "holder": holder,
        "mail_id": mail_id,
        "money": 0,
        "cod": 0,
        "delivered": 1,
        "expire_time": 9,
        "item_guid": item,
        "holder_level": 60,
        "inventory_type": 5,
        "required_level": 50,
    }


def refusal(holder, mail_id, item, refused, logout):
    return {
        "holder": holder,
        "command": "take-item mail:%d item:%d" % (mail_id, item),
        "refused": refused,
        "logout_time": logout,
    }


@contextlib.contextmanager
def world(*results):
    cursor = FakeCursor(results)
    with mock.patch.object(bridge, "_connect", lambda: FakeConnection(cursor)):
        yield cursor


class TheMailReadLeavesOutUnloadedLetters(unittest.TestCase):
    def test_a_letter_refused_since_the_last_logout_is_left_out(self):
        mail = [letter("Uzza", 900004, 200000009), letter("Uzza", 12, 77)]
        refused = [refusal("Uzza", 900004, 200000009, 2000, 1000)]
        with world(mail, refused):
            rows = bridge._fetch_mail(["Uzza"])
        self.assertEqual([r["mail_id"] for r in rows], [12])

    def test_after_a_relog_the_letter_is_read_again(self):
        mail = [letter("Uzza", 900004, 200000009)]
        refused = [refusal("Uzza", 900004, 200000009, 2000, 3000)]
        with world(mail, refused):
            rows = bridge._fetch_mail(["Uzza"])
        self.assertEqual([r["mail_id"] for r in rows], [900004])

    def test_the_refusal_read_asks_only_for_these_holders(self):
        with world([letter("Uzza", 900004, 1)], []) as cursor:
            bridge._fetch_mail(["Uzza", "Zork"])
        sql, args = cursor.executed[1]
        self.assertIn("overseer_command", sql)
        self.assertEqual(list(args)[:2], ["Uzza", "Zork"])
        self.assertIn("%" + "no mail with that id" + "%", list(args))

    def test_an_empty_mailbox_asks_nothing_more(self):
        with world([]) as cursor:
            self.assertEqual(bridge._fetch_mail(["Uzza"]), [])
        self.assertEqual(len(cursor.executed), 1)

    def test_a_failed_refusal_read_keeps_every_letter(self):
        cursor = FakeCursor([[letter("Uzza", 900004, 1)]])
        real = cursor.execute

        def execute(sql, args=None):
            if "overseer_command" in sql:
                raise bridge.pymysql.err.MySQLError(1146, "no table")
            return real(sql, args)

        cursor.execute = execute
        with mock.patch.object(bridge, "_connect", lambda: FakeConnection(cursor)):
            rows = bridge._fetch_mail(["Uzza"])
        self.assertEqual([r["mail_id"] for r in rows], [900004])
