"""The mail walk budget counts mail walks and nothing else (#2136).

Measured on the dev realm: the grounded-walker hearthstone rows are written
with the source `guildwalk:ground`, and the day's walk count read every row
whose source starts `guildwalk:`. Fifty hearthstone rows a day spent the 30 and
the 6 mailbox walks a day many times over, so no gear route ever got a walk
and 330 of 336 routes sat at "the daily limit is spent" while the mailbox
walks themselves numbered none. These tests run the real counting function
against a fake command log.
"""

import unittest
from unittest import mock

import bridge
import guildroute


class _Log:
    """A command log that answers the walk count the way the database would."""

    def __init__(self, rows):
        self.rows = rows  # (kind, source) pairs, all inside the last day
        self.sql = ""
        self.args = ()

    def connect(self):
        log = self

        class Cursor:
            def execute(self, sql, args=()):
                log.sql, log.args = sql, tuple(args)

            def fetchone(self):
                sql = log.sql
                prefix = log.args[0][:-1] if log.args else ""
                mail_only = "kind = 'mail'" in sql or "mail" in log.args[1:]
                n = sum(
                    1 for kind, source in log.rows
                    if source.startswith(prefix) and (not mail_only or kind == "mail")
                )
                return {"n": n}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return Cursor()

        return Conn()


class TheWalkBudgetIsNotSpentByHearthstones(unittest.TestCase):
    def count(self, rows):
        log = _Log(rows)
        with mock.patch.object(bridge, "_connect", log.connect):
            return bridge._route_walks_today()

    def test_hearthstone_rows_are_not_mailbox_walks(self):
        hearths = [("hearth", guildroute.GROUND_HEARTH_SOURCE)] * 52
        self.assertEqual(0, self.count(hearths))

    def test_a_mailbox_walk_row_is_counted(self):
        rows = [("mail", "guildwalk:12")] * 3 + [("hearth", "guildwalk:ground")] * 40
        self.assertEqual(3, self.count(rows))

    def test_the_budget_is_not_spent_by_hearths(self):
        spent = guildroute.runs_today([], 0.0, posted=self.count(
            [("hearth", guildroute.GROUND_HEARTH_SOURCE)] * 52))
        plan_budget = max(0, 30 - spent)
        self.assertEqual(30, plan_budget)


if __name__ == "__main__":
    unittest.main()
