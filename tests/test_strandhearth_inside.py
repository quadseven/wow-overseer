"""A member left alone inside an instance goes home by its own stone (#1261).

Measured on the dev realm: a family's walk out of a dungeon failed, every member
but one hearthed out, and that one stood alone inside the instance for hours
while the family intent row read it as `following|another map`. The strand
hearth never saw it, because it acts only on `walking back to the leader` with a
distance, and a member on another map has neither. Here the member is read by
where it is: on a dungeon map, with the leader on another, for as long as a
stranded follower is given. The names and numbers are invented.
"""

import pathlib
import unittest

import hearthcast as hc
import situation
import strandhearth as sh

INSTANCE = 229
STATE = "Oj|following|0\nJrog|following|another map\nJork|following|4605"
LEADER_AT = {"map_id": 1, "pos_x": -619.0, "pos_y": -4252.0}
BIND = situation.Point(1, -619.0, -4252.0, 24.0)
DUNGEONS = frozenset({INSTANCE, 109})


def observe(watch, now, maps, states=STATE, leader_map=1, lent=()):
    return sh.observe_inside(
        watch,
        "Jug",
        sh.parse_members_state(states),
        maps,
        leader_map,
        DUNGEONS,
        now,
        lent=lent,
    )


class ObserveInside(unittest.TestCase):
    def test_not_before_the_window(self):
        watch = {}
        maps = {"Jrog": INSTANCE}
        self.assertEqual(observe(watch, 0.0, maps), [])
        self.assertEqual(observe(watch, sh.INSIDE_SECONDS - 1, maps), [])

    def test_stranded_after_the_window(self):
        watch = {}
        maps = {"Jrog": INSTANCE}
        observe(watch, 0.0, maps)
        self.assertEqual(observe(watch, sh.INSIDE_SECONDS, maps), ["Jrog"])

    def test_the_window_is_ten_minutes(self):
        self.assertEqual(sh.INSIDE_SECONDS, 600.0)

    def test_a_member_outside_an_instance_is_not_stranded_by_this(self):
        # Jork is 4605 yards off on an ordinary map: the walk-back rule's, not this.
        watch = {}
        maps = {"Jork": 1}
        observe(watch, 0.0, maps)
        self.assertEqual(observe(watch, 9999.0, maps), [])

    def test_leaving_the_instance_resets_the_clock(self):
        watch = {}
        observe(watch, 0.0, {"Jrog": INSTANCE})
        observe(watch, 300.0, {"Jrog": 1})
        observe(watch, 400.0, {"Jrog": INSTANCE})
        self.assertEqual(observe(watch, 400.0 + 599, {"Jrog": INSTANCE}), [])

    def test_a_leader_inside_the_same_instance_means_the_run_is_on(self):
        watch = {}
        maps = {"Jrog": INSTANCE}
        observe(watch, 0.0, maps, leader_map=INSTANCE)
        self.assertEqual(observe(watch, 9999.0, maps, leader_map=INSTANCE), [])

    def test_a_leader_in_another_instance_is_not_a_leader_outside(self):
        watch = {}
        maps = {"Jrog": INSTANCE}
        observe(watch, 0.0, maps, leader_map=109)
        self.assertEqual(observe(watch, 9999.0, maps, leader_map=109), [])

    def test_a_member_lent_to_a_guild_run_is_left_alone(self):
        watch = {}
        maps = {"Jrog": INSTANCE}
        observe(watch, 0.0, maps, lent={"Jrog"})
        self.assertEqual(observe(watch, 9999.0, maps, lent={"Jrog"}), [])

    def test_an_unread_map_is_not_a_reading(self):
        watch = {}
        observe(watch, 0.0, {})
        self.assertEqual(observe(watch, 9999.0, {}), [])

    def test_a_member_that_left_the_row_is_forgotten(self):
        watch = {}
        observe(watch, 0.0, {"Jrog": INSTANCE})
        observe(watch, 10.0, {"Jrog": INSTANCE}, states="Oj|following|0")
        self.assertEqual(watch, {})


class WhyNotInside(unittest.TestCase):
    def member(self, **kw):
        base = dict(
            name="Jrog",
            bind=BIND,
            alive=True,
            stone=True,
            cooldown=0.0,
        )
        base.update(kw)
        return hc.Member(**base)

    def test_a_stone_bound_on_the_leaders_map_is_the_way_out(self):
        self.assertEqual(sh.why_not_inside(self.member(), LEADER_AT), "")

    def test_a_stone_bound_elsewhere_is_not(self):
        other = situation.Point(0, 0.0, 0.0, 0.0)
        self.assertEqual(
            sh.why_not_inside(self.member(bind=other), LEADER_AT), hc.BOUND_ELSEWHERE
        )

    def test_no_distance_rule_applies(self):
        # The member's own distance to the leader is across maps, so the
        # "not much farther" test of the walk-back rule has nothing to compare.
        far = situation.Point(1, 5000.0, 5000.0, 0.0)
        self.assertEqual(sh.why_not_inside(self.member(bind=far), LEADER_AT), "")

    def test_a_dead_member_is_refused(self):
        self.assertEqual(
            sh.why_not_inside(self.member(alive=False), LEADER_AT), hc.DEAD
        )


class BridgeReadsIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
            encoding="utf-8"
        )
        a = text.index("    async def _hearth_stranded_followers(")
        cls.body = text[a : text.index("    async def _trades_for_every_family(", a)]

    def test_it_reads_the_map_each_member_stands_on_and_the_guild_runs(self):
        self.assertIn("strandhearth.observe_inside(", self.body)
        self.assertIn("_guild_run_members_out", self.body)
        self.assertIn("lent=lent", self.body)
        self.assertIn("dungeonpath.PORTAL_MAPS", self.body)

    def test_an_inside_member_is_judged_by_the_inside_rule_not_the_distance_rule(self):
        inside = self.body.index("strandhearth.why_not_inside(")
        walk = self.body.index("strandhearth.why_not(")
        self.assertLess(inside, walk)
        self.assertIn("if member.name in inside:", self.body)

    def test_it_writes_the_same_hearth_row_with_the_same_source(self):
        self.assertGreaterEqual(self.body.count("_insert_hearth, member.name"), 2)


if __name__ == "__main__":
    unittest.main()
