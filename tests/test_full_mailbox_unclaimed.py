"""A full mailbox is treated like a post waiting: nothing more is sent to it.

wow-dev 2026-10-04: 46 of 47 guild material posts in a day bounced off Grug,
"recipient mailbox is full", because he held 113 letters already emptied but
never deleted and only an unopened post counted as waiting.
"""

import pathlib
import unittest

import guildjobs

ROOT = pathlib.Path(__file__).resolve().parents[1]


class AFullMailboxIsWaiting(unittest.TestCase):
    def test_the_read_counts_full_mailboxes(self):
        source = (ROOT / "bridge.py").read_text(encoding="utf-8")
        sql = source[source.index("_JOB_UNCLAIMED_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertIn("HAVING COUNT(*) >= %s", sql)
        self.assertIn("guildjobs.MAILBOX_FULL_LETTERS", source)

    def test_the_cap_sits_under_the_core_inbox_limit(self):
        self.assertLess(guildjobs.MAILBOX_FULL_LETTERS, 100)

    def test_a_waiting_master_gets_no_bank_post(self):
        got = guildjobs.bank_masters({"Cave": "Grug"}, {"Cave"}, {"Grug"})
        self.assertEqual({"Cave": ""}, got)


if __name__ == "__main__":
    unittest.main()
