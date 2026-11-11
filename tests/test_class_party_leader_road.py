"""An asker whose own road to the objective is refused for good gives its ask
up at once, instead of walking helper after helper to a meeting it cannot
reach."""

import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import classparty
    import guildroute
    from test_class_party_retry_line import _RetryBridge, _run
    from test_classparty import a_run

ROAD = guildroute.WalkAnswer(
    guildroute.ENDED,
    "Bigzug cannot walk to the Lizard: the road to the spawn crosses ground far "
    "above its level",
)
STALL = guildroute.WalkAnswer(
    guildroute.ENDED,
    "Bigzug cannot walk to the Lizard: stopped getting nearer the spawn",
)


def _leader_walks(this):
    return [
        r for r in this.rows if r[0] == "Bigzug" and r[2].startswith(classparty.MEET)
    ]


class TheLeaderWhoseRoadIsRefusedForGood(unittest.TestCase):
    def test_the_ask_is_given_up_after_one_failed_meeting(self):
        this = _RetryBridge([], {"Bigzug": [ROAD]})
        _run(this, a_run(meeting=True))
        self.assertEqual(this.settled, [(1, False, True)])
        self.assertTrue(this._class_board.exhausted(1))

    def test_a_short_refusal_still_leaves_the_ask_its_other_tries(self):
        this = _RetryBridge([], {"Bigzug": [STALL]})
        _run(this, a_run(meeting=True))
        self.assertEqual(this.settled, [(1, False, False)])
        self.assertFalse(this._class_board.exhausted(1))

    def test_only_the_leaders_own_walk_counts(self):
        run = a_run(meeting=True)
        run.walks["Chill"] = "the road to the spawn crosses ground far above its level"
        self.assertFalse(classparty.leader_road_refused(run))
        run.walks["Bigzug"] = "the ground toward the spawn does not hold"
        self.assertTrue(classparty.leader_road_refused(run))
