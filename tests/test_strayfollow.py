"""A guild member led off by a stranger's bot leaves that group (strayfollow.py).

Synthetic rows shaped like the dev realm's: guild members grouped as followers
of random bots that are in no guild, some on another continent from their
leader, every errand of theirs held because a follower walks with its group.
"""

import pathlib
import unittest

import strayfollow as sf

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")


def follower(name="Chop", **kw):
    base = dict(
        name=name,
        guild="Cave",
        map_id=530,
        x=0.0,
        y=0.0,
        in_combat=False,
        leader="Stranger",
        leader_guild="",
        leader_roster=False,
        leader_online=True,
        leader_map=0,
        leader_x=0.0,
        leader_y=0.0,
    )
    base.update(kw)
    return sf.Follower(**base)


def row(**kw):
    base = dict(
        name="Chop",
        guild="Cave",
        map_id=530,
        pos_x=1.0,
        pos_y=2.0,
        in_combat=0,
        leader="Stranger",
        leader_guild=None,
        leader_roster=0,
        leader_online=1,
        leader_map=0,
        leader_x=5.0,
        leader_y=6.0,
    )
    base.update(kw)
    return base


class WhoIsAStray(unittest.TestCase):
    def test_a_leader_in_no_guild_and_off_the_roster_is_a_stranger(self):
        self.assertTrue(sf.stranger(follower(), {"Cave", "Bonkers"}))

    def test_a_guildmate_or_a_roster_leader_is_not(self):
        guilds = {"Cave", "Bonkers"}
        self.assertFalse(sf.stranger(follower(leader_guild="Cave"), guilds))
        self.assertFalse(sf.stranger(follower(leader_guild="Bonkers"), guilds))
        self.assertFalse(sf.stranger(follower(leader_roster=True), guilds))

    def test_apart_names_the_other_map_offline_and_range(self):
        self.assertIn("another map", sf.apart(follower()))
        self.assertIn("offline", sf.apart(follower(leader_online=False)))
        far = follower(map_id=0, leader_x=sf.RANGE_YARDS + 1)
        self.assertIn("yards", sf.apart(far))
        near = follower(map_id=0, leader_x=10.0)
        self.assertEqual(sf.apart(near), "")


class TheClock(unittest.TestCase):
    def test_apart_time_starts_when_first_seen_and_resets_when_together(self):
        apart = follower()
        together = follower(name="Near", map_id=0, leader_x=5.0)
        since = sf.track({}, [apart, together], 100.0)
        self.assertEqual(since, {"Chop": 100.0})
        since = sf.track(since, [apart], 140.0)
        self.assertEqual(since, {"Chop": 100.0})
        # Together again, or no longer grouped: the clock is dropped.
        self.assertEqual(sf.track(since, [follower(map_id=0, leader_x=1.0)], 150.0), {})
        self.assertEqual(sf.track(since, [], 150.0), {})


class ThePlan(unittest.TestCase):
    GUILDS = frozenset({"Cave", "Bonkers"})

    def plan(self, followers, since, now, recent=None):
        return sf.plan(followers, since, now, recent or {}, self.GUILDS)

    def test_a_stray_apart_past_the_threshold_leaves(self):
        f = follower()
        rows, lines = self.plan([f], {"Chop": 0.0}, sf.STRAY_MINUTES * 60.0)
        self.assertEqual([(r.name, r.command) for r in rows], [("Chop", "leave-group")])
        self.assertEqual(rows[0].source, "strayfollow:Chop")
        self.assertEqual(len(lines), 1)
        self.assertIn("Chop leaves the group of Stranger", lines[0])
        self.assertIn("another map", lines[0])

    def test_not_before_the_threshold(self):
        rows, _ = self.plan([follower()], {"Chop": 0.0}, sf.STRAY_MINUTES * 60.0 - 1)
        self.assertEqual(rows, ())

    def test_never_a_guildmate_s_or_the_family_s_group(self):
        for f in (follower(leader_guild="Cave"), follower(leader_roster=True)):
            rows, _ = self.plan([f], {"Chop": 0.0}, 10**6)
            self.assertEqual(rows, ())

    def test_not_in_a_fight_and_not_twice_within_the_cooldown(self):
        rows, _ = self.plan([follower(in_combat=True)], {"Chop": 0.0}, 10**6)
        self.assertEqual(rows, ())
        rows, _ = self.plan(
            [follower()], {"Chop": 0.0}, 10**6, {"Chop": sf.COOLDOWN_MINUTES - 1}
        )
        self.assertEqual(rows, ())
        rows, _ = self.plan(
            [follower()], {"Chop": 0.0}, 10**6, {"Chop": sf.COOLDOWN_MINUTES}
        )
        self.assertEqual(len(rows), 1)

    def test_a_pass_writes_at_most_a_few(self):
        many = [follower(name="M%d" % i) for i in range(10)]
        since = {f.name: 0.0 for f in many}
        rows, _ = self.plan(many, since, 10**6)
        self.assertEqual(len(rows), sf.LEAVES_PER_PASS)


class FromRows(unittest.TestCase):
    def test_rows_become_followers(self):
        (f,) = sf.followers_from_rows([row()])
        self.assertEqual(f.name, "Chop")
        self.assertEqual(f.leader_guild, "")
        self.assertFalse(f.leader_roster)
        self.assertEqual((f.x, f.y, f.leader_x, f.leader_y), (1.0, 2.0, 5.0, 6.0))

    def test_an_offline_leader_has_no_position(self):
        (f,) = sf.followers_from_rows(
            [row(leader_online=0, leader_map=None, leader_x=None, leader_y=None)]
        )
        self.assertFalse(f.leader_online)
        self.assertIn("offline", sf.apart(f))


class TheBridgePass(unittest.TestCase):
    def test_the_pass_is_declared_and_writes_through_the_guild_kind(self):
        self.assertIn('_Pass("_stray_follow_loop")', BRIDGE)
        start = BRIDGE.index("async def _stray_follow_loop(")
        body = BRIDGE[start : BRIDGE.index("\n    async def ", start + 1)]
        self.assertIn("strayfollow.plan(", body)
        self.assertIn("_insert_guild, r.name, r.command, r.source", body)
        self.assertIn('log.info("stray followers: %s (row %d)"', body)
        sql = BRIDGE.split("_STRAY_FOLLOWERS_SQL = (", 1)[1][:1500]
        self.assertIn("s.group_leader", sql)
        self.assertIn("overseer_roster", sql)


if __name__ == "__main__":
    unittest.main()
