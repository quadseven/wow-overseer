"""A stall judged by the stall clock before #1809 is not held (#1731, #1779).

Measured on the dev realm 2026-11-06 to 2026-11-07: the bridge memo held
"its objectives did not move for 2 hours of play" for An Unwelcome Guest
(quest 34) and The Totem of Infliction (quest 101) for five Alliance
questers. The memo is rewritten every pass, so it never expired, and each
share from a party member put the quest back for an immediate drop, while
no quester found either quest stalled once after #1809 went live.
"""

import unittest
from unittest import mock

import questers
from test_guildsocial_bridge import bridge

OLD = {
    "34": questers.STALLED,
    "101": questers.STALLED_UNSOURCED,
    "35": questers.UNSUPPORTED_OBJECTIVE,
    "77": questers.ENDER_MISSING,
}


def memos(by_name):
    def read(kind):
        if kind == bridge.QUESTER_BROKEN_MEMO:
            return {name: (value, 0.0) for name, value in by_name.items()}
        return {}

    return read


class AStallJudgedByTheOldClock(unittest.TestCase):
    def test_is_not_held_after_a_restart(self):
        with mock.patch.object(bridge, "_memo_read", memos({"Durga": OLD})):
            _clock, broken = bridge._quester_memos()
        self.assertNotIn(34, broken["Durga"])
        self.assertNotIn(101, broken["Durga"])

    def test_a_world_fact_stays_held(self):
        with mock.patch.object(bridge, "_memo_read", memos({"Durga": OLD})):
            _clock, broken = bridge._quester_memos()
        self.assertEqual(questers.UNSUPPORTED_OBJECTIVE, broken["Durga"][35])
        self.assertEqual(questers.ENDER_MISSING, broken["Durga"][77])

    def test_the_drop_is_said(self):
        with (
            mock.patch.object(bridge, "_memo_read", memos({"Durga": OLD})),
            self.assertLogs(bridge.log, "INFO") as said,
        ):
            bridge._quester_memos()
        self.assertTrue(
            any("Durga no longer holds 2 stall(s)" in line for line in said.output),
            said.output,
        )


class AStallJudgedByTheCurrentClock(unittest.TestCase):
    def test_is_still_held(self):
        value = dict(OLD)
        value[bridge.QUESTER_STALL_CLOCK_KEY] = bridge.QUESTER_STALL_CLOCK
        with mock.patch.object(bridge, "_memo_read", memos({"Velo": value})):
            _clock, broken = bridge._quester_memos()
        self.assertEqual(questers.STALLED, broken["Velo"][34])
        self.assertEqual(questers.STALLED_UNSOURCED, broken["Velo"][101])
        self.assertNotIn(bridge.QUESTER_STALL_CLOCK_KEY, broken["Velo"])

    def test_every_memo_written_now_says_which_clock(self):
        written = []
        with mock.patch.object(bridge, "_memo_upsert", lambda *a: written.append(a)):
            bridge._quester_memos_write(questers.Clock(), {"Velo": {34: "x"}}, 1.0)
        (row,) = [w for w in written if w[0] == bridge.QUESTER_BROKEN_MEMO]
        self.assertEqual(
            bridge.QUESTER_STALL_CLOCK, row[2][bridge.QUESTER_STALL_CLOCK_KEY]
        )
        self.assertEqual("x", row[2]["34"])

    def test_a_written_memo_reads_back_whole(self):
        written = []
        with mock.patch.object(bridge, "_memo_upsert", lambda *a: written.append(a)):
            bridge._quester_memos_write(
                questers.Clock(), {"Velo": {34: questers.STALLED}}, 1.0
            )
        (row,) = [w for w in written if w[0] == bridge.QUESTER_BROKEN_MEMO]
        with mock.patch.object(bridge, "_memo_read", memos({"Velo": row[2]})):
            _clock, broken = bridge._quester_memos()
        self.assertEqual({34: questers.STALLED}, broken["Velo"])


if __name__ == "__main__":
    unittest.main()
