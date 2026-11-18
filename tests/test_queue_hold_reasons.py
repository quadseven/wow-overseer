"""A queue step that is held says which hold held it, once per ten minutes.

Measured on the dev realm: a family's queue entries sat `queued` for over an
hour while the bridge logged nothing about that family's queue at all, because
every hold in the family's queue step returns without a word. The cause could
not be read from the log. `campaignqueue.HoldLog` is the rate limit (once per
family per hold per ten minutes); the last class reads bridge.py as text to
pin that every silent return names its hold.
"""

import pathlib
import re
import unittest

import campaignqueue

HERE = pathlib.Path(__file__).resolve().parent.parent


class HoldLogTest(unittest.TestCase):
    def test_first_sight_is_said(self):
        log = campaignqueue.HoldLog()
        self.assertTrue(log.due("Jug", "mid-run", 1000.0))

    def test_same_hold_inside_ten_minutes_is_quiet(self):
        log = campaignqueue.HoldLog()
        self.assertTrue(log.due("Jug", "mid-run", 1000.0))
        self.assertFalse(log.due("Jug", "mid-run", 1000.0 + 599))

    def test_same_hold_after_ten_minutes_is_said_again(self):
        log = campaignqueue.HoldLog()
        log.due("Jug", "mid-run", 1000.0)
        self.assertTrue(log.due("Jug", "mid-run", 1000.0 + 600))

    def test_a_quiet_read_does_not_push_the_clock_out(self):
        log = campaignqueue.HoldLog()
        log.due("Jug", "mid-run", 0.0)
        log.due("Jug", "mid-run", 500.0)
        self.assertTrue(log.due("Jug", "mid-run", 600.0))

    def test_other_family_and_other_hold_are_independent(self):
        log = campaignqueue.HoldLog()
        log.due("Jug", "mid-run", 0.0)
        self.assertTrue(log.due("Tug", "mid-run", 1.0))
        self.assertTrue(log.due("Jug", "gear hold", 1.0))

    def test_the_window_is_ten_minutes(self):
        self.assertEqual(campaignqueue.HOLD_LOG_SECONDS, 600)


class BridgeNamesEveryHoldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (HERE / "bridge.py").read_text(encoding="utf-8")

    def _body(self, start, end):
        a = self.text.index(start)
        return self.text[a:self.text.index(end, a)]

    def test_the_family_step_names_each_early_return(self):
        body = self._body("    async def _campaign_queue_family_once(",
                          "    async def _family_lent_hold(")
        for hold in ("lent to a guild run", "queue hold", "family held"):
            self.assertIn('self._say_queue_hold(key, "%s"' % hold, body, hold)

    def test_each_queue_hold_names_itself(self):
        body = self._body("    async def _queue_holds(", "    async def _stall_breaker(")
        for hold in ("stall breaker", "dungeon pace", "gear hold"):
            self.assertIn('self._say_queue_hold(key, "%s"' % hold, body, hold)

    def test_pace_names_the_mid_run_return(self):
        body = self._body("    async def _dungeon_pace(", "    async def _leave_town_when_done(")
        self.assertIn('self._say_queue_hold(key, "mid-run"', body)

    def test_the_helper_uses_the_rate_limit(self):
        body = self._body("    def _say_queue_hold(", "\n    async def ")
        self.assertIn("campaignqueue.HoldLog", self.text)
        self.assertIn(".due(", body)
        self.assertIn("log.info(", body)


if __name__ == "__main__":
    unittest.main()
