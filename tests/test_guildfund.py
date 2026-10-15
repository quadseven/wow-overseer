"""The guild fund: dues refunds and class training letters (#512, #775, #1013).

Pure unit tests against guildfund.py: member refunds, training letters,
shortfall calculation, and the pass line.
"""

from __future__ import annotations

import logging
import unittest

import guildfund

G = guildfund.COPPER_PER_GOLD


class TheGuildFundPass(unittest.TestCase):
    def setUp(self):
        self.master = "Zug"
        self.guild = "Bonkers"

    def test_a_shortfall_is_logged_once_with_the_amount(self):
        """When a guild bank cannot cover a planned refund or training letter,
        the pass line logs the shortfall once with the amount (#1013)."""
        members = [
            guildfund.Member(
                "Funkymon", self.guild, level=20, money=0, training=5 * G, guid=1
            ),
            guildfund.Member(
                "Yamon", self.guild, level=20, money=0, training=0, guid=2
            ),
        ]
        paid = {"Yamon": 10 * G}
        book = guildfund.Ledger()
        # Bank holds 0: cannot cover Yamon's dues refund or Funkymon's training.
        plan = guildfund.plan(self.master, members, bank=0, book=book, paid=paid)
        self.assertGreater(plan.shortfall, 0)

        line = guildfund.pass_line(
            self.guild, bank=0, carried=0, plan_=plan, refunded=book.refunded
        )
        self.assertEqual(1, line.count("shortfall"))
        self.assertIn("shortfall %s" % guildfund.gold(plan.shortfall), line)

        # Logging the pass line logs the shortfall once with the amount.
        with self.assertLogs("wow-overseer", level="INFO") as cm:
            logging.getLogger("wow-overseer").info("%s", line)
        self.assertEqual(1, len(cm.output))
        self.assertIn("shortfall %s" % guildfund.gold(plan.shortfall), cm.output[0])

    def test_shortfall_includes_waiting_refunds_and_training(self):
        """A bank holding 0 reports the full shortfall across refunds and training."""
        members = [
            guildfund.Member(
                "Funkymon", self.guild, level=20, money=0, training=2 * G, guid=1
            ),
            guildfund.Member(
                "Hairspray", self.guild, level=20, money=0, training=3 * G, guid=2
            ),
            guildfund.Member(
                "Yamon", self.guild, level=20, money=0, training=0, guid=3
            ),
        ]
        paid = {"Yamon": 5 * G}
        book = guildfund.Ledger()
        plan = guildfund.plan(self.master, members, bank=0, book=book, paid=paid)

        # Yamon needs min(5g dues, 20^3c reserve = 8000c = 80s) -> 80s refund.
        # Funkymon needs 2g training. Hairspray needs 3g training.
        # Total shortfall = 80s + 2g + 3g = 5g 80s.
        yamon_reserve = guildfund.reserve(0, 20)
        expected_shortfall = min(5 * G, yamon_reserve) + (2 * G) + (3 * G)
        self.assertEqual(expected_shortfall, plan.shortfall)

        line = guildfund.pass_line(
            self.guild, bank=0, carried=0, plan_=plan, refunded=book.refunded
        )
        self.assertIn("shortfall %s" % guildfund.gold(expected_shortfall), line)

    def test_no_shortfall_when_bank_covers_planned_letters(self):
        """A bank with enough funds has 0 shortfall and mentions no shortfall in the pass line."""
        members = [
            guildfund.Member(
                "Funkymon", self.guild, level=20, money=0, training=2 * G, guid=1
            ),
        ]
        paid = {}
        book = guildfund.Ledger()
        # Bank holds 50g: covers Funkymon's 2g training easily.
        plan = guildfund.plan(self.master, members, bank=50 * G, book=book, paid=paid)
        self.assertEqual(0, plan.shortfall)
        self.assertEqual(1, len(plan.letters))
        self.assertEqual(2 * G, plan.letters[0].copper)

        line = guildfund.pass_line(
            self.guild, bank=50 * G, carried=0, plan_=plan, refunded=book.refunded
        )
        self.assertNotIn("shortfall", line)

    def test_partial_shortfall_when_bank_covers_only_some_letters(self):
        """When the bank can only partially cover letters, the unpayable portion is the shortfall."""
        members = [
            guildfund.Member(
                "Yamon", self.guild, level=25, money=0, training=0, guid=1
            ),
        ]
        # Reserve for level 25 is 25^3 = 15_625c = 1g 56s.
        reserve = guildfund.gear_budget(25)
        paid = {"Yamon": 10 * G}
        book = guildfund.Ledger()
        # Bank holds 1g: Yamon needs reserve (15_625c), but bank only has 10_000c.
        plan = guildfund.plan(self.master, members, bank=1 * G, book=book, paid=paid)
        self.assertEqual(1, len(plan.letters))
        self.assertEqual(1 * G, plan.letters[0].copper)
        self.assertEqual(reserve - 1 * G, plan.shortfall)

        line = guildfund.pass_line(
            self.guild, bank=1 * G, carried=0, plan_=plan, refunded=book.refunded
        )
        self.assertIn("shortfall %s" % guildfund.gold(reserve - 1 * G), line)


if __name__ == "__main__":
    unittest.main()
