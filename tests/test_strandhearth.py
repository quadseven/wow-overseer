"""A follower that cannot close on its held leader goes home by its own stone (#1261).

The module holds a leader still while a member walks back to it, for up to 1200s,
and that hold outranks the leader's errand. A member stuck in a lava pocket, or
refused every bearing 9,500 yards away, never arrives, so the family's errand
never starts. Pinned here: who counts as stranded, and when a stone is the exit.
The members and numbers are invented.
"""

import unittest

import hearthcast as hc
import situation
import strandhearth as sh

STATE = (
    "Oz|walking back to the leader|1180\nUzza|following|0\n"
    "Zrog|walking back to the leader|9521"
)
LEADER = {"map_id": 0, "pos_x": -7689.0, "pos_y": -1761.0}
BIND = situation.Point(0, -6651.0, -2150.0, 245.0)


class Parse(unittest.TestCase):
    def test_reads_member_state_and_yards(self):
        got = sh.parse_members_state(STATE)
        self.assertEqual(got["Oz"], ("walking back to the leader", 1180.0))
        self.assertEqual(got["Uzza"], ("following", 0.0))

    def test_a_row_without_a_number_has_no_yards(self):
        got = sh.parse_members_state("Uzza|following|another map\nbad")
        self.assertEqual(got["Uzza"], ("following", None))
        self.assertNotIn("bad", got)

    def test_empty(self):
        self.assertEqual(sh.parse_members_state(None), {})


class Observe(unittest.TestCase):
    def test_not_stranded_before_the_window(self):
        watch = {}
        states = sh.parse_members_state(STATE)
        self.assertEqual(sh.observe(watch, "Zug", states, 0.0), [])
        self.assertEqual(sh.observe(watch, "Zug", states, sh.STRAND_SECONDS - 1), [])

    def test_stranded_after_the_window_without_closing(self):
        watch = {}
        states = sh.parse_members_state(STATE)
        sh.observe(watch, "Zug", states, 0.0)
        self.assertEqual(
            sh.observe(watch, "Zug", states, sh.STRAND_SECONDS), ["Oz", "Zrog"]
        )

    def test_closing_five_yards_restarts_the_clock(self):
        watch = {}
        sh.observe(watch, "Zug", sh.parse_members_state(STATE), 0.0)
        nearer = STATE.replace("1180", "1170")
        sh.observe(watch, "Zug", sh.parse_members_state(nearer), 500.0)
        self.assertEqual(
            sh.observe(watch, "Zug", sh.parse_members_state(nearer), 700.0), ["Zrog"]
        )

    def test_a_few_yards_is_not_closing(self):
        watch = {}
        sh.observe(watch, "Zug", sh.parse_members_state(STATE), 0.0)
        jitter = STATE.replace("1180", "1177")
        got = sh.observe(
            watch, "Zug", sh.parse_members_state(jitter), sh.STRAND_SECONDS + 1
        )
        self.assertIn("Oz", got)

    def test_a_member_that_rejoined_is_forgotten(self):
        watch = {}
        sh.observe(watch, "Zug", sh.parse_members_state(STATE), 0.0)
        rejoined = STATE.replace("walking back to the leader|1180", "following|3")
        sh.observe(watch, "Zug", sh.parse_members_state(rejoined), 100.0)
        self.assertNotIn(("Zug", "Oz"), watch)

    def test_a_near_member_is_never_stranded(self):
        watch = {}
        near = "Oz|walking back to the leader|120"
        sh.observe(watch, "Zug", sh.parse_members_state(near), 0.0)
        self.assertEqual(
            sh.observe(watch, "Zug", sh.parse_members_state(near), 9999.0), []
        )


def able(**over):
    facts = {"stone": True, "cooldown": 0.0, "alive": True}
    facts.update(over)
    return hc.Member(
        name="Oz",
        at={"map_id": 0, "pos_x": -7636.0, "pos_y": -759.0},
        bind=BIND,
        **facts,
    )


class Exit(unittest.TestCase):
    def test_stone_lands_nearer_the_leader(self):
        self.assertEqual(sh.why_not(able(), LEADER, 1180.0), "")

    def test_no_stone_dead_cooldown_or_unread_hold(self):
        self.assertEqual(sh.why_not(able(stone=False), LEADER, 1180.0), hc.NO_STONE)
        self.assertEqual(sh.why_not(able(alive=False), LEADER, 1180.0), hc.DEAD)
        self.assertEqual(
            sh.why_not(able(cooldown=60.0), LEADER, 1180.0), hc.ON_COOLDOWN
        )
        self.assertEqual(sh.why_not(able(stone=None), LEADER, 1180.0), hc.STONE_UNREAD)

    def test_a_bind_on_another_map_is_no_exit(self):
        far = hc.Member(
            name="Oz",
            at={"map_id": 0, "pos_x": 0.0, "pos_y": 0.0},
            bind=situation.Point(1, 0.0, 0.0, 0.0),
            stone=True,
            cooldown=0.0,
            alive=True,
        )
        self.assertEqual(sh.why_not(far, LEADER, 1180.0), hc.BOUND_ELSEWHERE)

    def test_a_bind_much_farther_than_the_member_is_no_exit(self):
        self.assertEqual(sh.why_not(able(), LEADER, 700.0), sh.NO_NEARER)

    def test_no_bind_is_no_exit(self):
        m = hc.Member(
            name="Oz", at=None, bind=None, stone=True, cooldown=0.0, alive=True
        )
        self.assertEqual(sh.why_not(m, LEADER, 1180.0), hc.BOUND_ELSEWHERE)


if __name__ == "__main__":
    unittest.main()


class Wiring(unittest.TestCase):
    """The bridge calls the pass from the every-family economy cycle."""

    def test_pass_is_called_and_shipped(self):
        import pathlib

        here = pathlib.Path(__file__).resolve().parents[1]
        bridge = (here / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("await self._hearth_stranded_followers()", bridge)
        self.assertIn("strandhearth.observe(watch, leader, states, now)", bridge)
        self.assertIn(
            "strandhearth.py", (here / "Dockerfile").read_text(encoding="utf-8")
        )
