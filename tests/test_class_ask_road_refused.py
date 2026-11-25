"""An asker whose road to the objective was refused for good is not offered the
same quest again until the road changes (#2071).

Measured 2026-11-17: a warlock's walk to Surena Caledon was refused "the road to
the spawn crosses ground far above its level", its ask was given up at once, and
the same member asked again after every cooldown (twice in three hours) with the
same refused road under it. Ten askers repeated this for one quest. The ask is
now held back until the member's level or map is not the one that was refused.
"""

import dataclasses
import time
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import classparty
    import guildroute
    from test_class_party_retry_line import _RetryBridge, _run
    from test_classask import friends
    from test_classask_party_forms import helps_read
    from test_classparty import a_run
    from test_guildsocial import NOW
    from test_guildsocial_bridge import bridge

ROAD = guildroute.WalkAnswer(
    guildroute.ENDED,
    "Bigzug cannot walk to the Lizard: the road to the spawn crosses ground far "
    "above its level",
)
STALL = guildroute.WalkAnswer(
    guildroute.ENDED,
    "Bigzug cannot walk to the Lizard: stopped getting nearer the spawn",
)


def post_pass(board, helps=None):
    facts = {"asks": [], "answers": [], "now": NOW, "busy": set(), "family": set()}
    quest_pass, _h, _n, _p, _e = bridge._class_ask_pass(
        facts,
        friends(),
        {},
        {},
        helps_read() if helps is None else helps,
        board,
        None,
        # Long past the give-up cooldown. The board stamps its cooldown on the
        # host's monotonic clock, which counts from boot, so a fixed number is
        # only "past" on a host up for less than that many seconds.
        time.monotonic() + 7 * 86400.0,
    )
    return quest_pass


def refused_board():
    this = _RetryBridge([], {"Bigzug": [ROAD]})
    run = a_run(meeting=True)
    run.level, run.map_id = 20, 1
    _run(this, run)
    return this._class_board


class AnAskerWhoseRoadIsRefusedForGood(unittest.TestCase):
    def test_a_member_asks_when_nothing_was_refused(self):
        self.assertEqual(len(post_pass(classparty.Board()).posts), 1)

    def test_the_board_remembers_the_refused_road(self):
        self.assertTrue(refused_board().road_refused(helps_read()))

    def test_it_does_not_ask_again_at_the_same_level_and_map(self):
        self.assertEqual(post_pass(refused_board()).posts, ())

    def test_a_short_refusal_does_not_hold_the_asker_back(self):
        this = _RetryBridge([], {"Bigzug": [STALL]})
        run = a_run(meeting=True)
        run.level, run.map_id = 20, 1
        _run(this, run)
        self.assertEqual(len(post_pass(this._class_board).posts), 1)

    def test_a_new_level_asks_again(self):
        (help_,) = helps_read()
        higher = dataclasses.replace(help_, level=help_.level + 1)
        self.assertEqual(len(post_pass(refused_board(), [higher]).posts), 1)

    def test_a_new_map_asks_again(self):
        (help_,) = helps_read()
        moved = dataclasses.replace(help_, map_id=0)
        self.assertEqual(len(post_pass(refused_board(), [moved]).posts), 1)

    def test_another_quest_is_not_held_back(self):
        board = refused_board()
        (help_,) = helps_read()
        move = dataclasses.replace(help_.move, quest=help_.move.quest + 1)
        other = dataclasses.replace(help_, move=move)
        self.assertEqual(board.road_refused([other]), set())


if __name__ == "__main__":
    unittest.main()
