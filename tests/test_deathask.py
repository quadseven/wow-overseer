"""A death looper with a guildmate in reach is asked for in guild chat (#2277).

WHY THIS EXISTS. The death-loop pool never drains: the escape step works per
member, and a looper who escapes alone returns to the same content at the
same strength and loops again. Slice 1 of the help route named the offer in
the escape's log line; slice 2 piece 1 taught the ask table the deathloop
kind. This piece is the planner at the bridge social pass: for a looper the
planning pass already flagged, when guildjobs.loop_mates finds a guildmate
in reach, it posts one ask of the deathloop kind (target naming the loop
place, reason naming that mate, one helper wanted), under the same caps and
cooldown the class quest asks use, so a repeated pass cannot spam the guild.
"""

import datetime
import unittest

import deathask
import deathloop
import guildsocial as gs
from test_guildsocial import NOW, mate

HILLSBRAD = 267
NEAR = (-711.0, -515.0)


def loop_of(name="Looper", level=26):
    return deathloop.Loop(
        name=name,
        zone=HILLSBRAD,
        map_id=0,
        deaths=7,
        killer="Hillsbrad Farmer",
        level=level,
        first_age=3000,
        last_age=120,
    )


def ask(id_, asker, **kw):
    row = {
        "id": id_,
        "guild": "Cave",
        "asker": asker,
        "kind": "deathloop",
        "target": "deathloop:%d" % HILLSBRAD,
        "target_label": "Hillsbrad Foothills",
        "roles_needed": "dps",
        "reason": "",
        "said": "",
        "created_at": NOW - datetime.timedelta(minutes=2),
        "expires_at": NOW + datetime.timedelta(minutes=8),
        "state": "open",
        "run_id": None,
    }
    row.update(kw)
    return gs.ask_from_row(row)


def looper_and_mate():
    return mate("Looper", 26, 1, at=NEAR, zone_id=HILLSBRAD), mate(
        "Helper", 28, 2, at=NEAR, zone_id=HILLSBRAD
    )


class DeathLoopAsks(unittest.TestCase):
    def test_a_looper_with_a_mate_in_reach_gets_one_deathloop_post(self):
        looper, helper = looper_and_mate()
        found = deathask.plan_pass({"Looper": loop_of()}, [looper, helper], [], NOW)
        self.assertEqual(len(found.posts), 1)
        post = found.posts[0]
        self.assertEqual(post.kind, gs.KIND_DEATHLOOP)
        self.assertEqual(post.asker, "Looper")
        self.assertEqual(post.guild, "Cave")
        self.assertIn("Hillsbrad", post.target_label)
        self.assertIn("Helper", post.reason)
        self.assertIn("Hillsbrad", post.said)
        self.assertEqual(post.roles_needed, "dps")

    def test_a_looper_with_no_mate_in_reach_gets_no_post(self):
        looper, _helper = looper_and_mate()
        far = mate("Distant", 28, 2, at=(90000.0, 90000.0), zone_id=HILLSBRAD)
        found = deathask.plan_pass({"Looper": loop_of()}, [looper, far], [], NOW)
        self.assertEqual(found.posts, ())

    def test_a_recent_closed_deathloop_ask_suppresses_a_repeat(self):
        looper, helper = looper_and_mate()
        closed = ask(
            7,
            "Looper",
            state="expired",
            created_at=NOW - datetime.timedelta(minutes=5),
        )
        found = deathask.plan_pass(
            {"Looper": loop_of()}, [looper, helper], [closed], NOW
        )
        self.assertEqual(found.posts, ())

    def test_a_live_deathloop_ask_suppresses_a_second_post(self):
        looper, helper = looper_and_mate()
        live = ask(9, "Looper")
        found = deathask.plan_pass({"Looper": loop_of()}, [looper, helper], [live], NOW)
        self.assertEqual(found.posts, ())

    def test_an_old_closed_ask_does_not_suppress_a_new_one(self):
        looper, helper = looper_and_mate()
        old = ask(
            11,
            "Looper",
            state="expired",
            created_at=NOW - datetime.timedelta(hours=3),
        )
        found = deathask.plan_pass({"Looper": loop_of()}, [looper, helper], [old], NOW)
        self.assertEqual(len(found.posts), 1)

    def test_an_open_ask_past_its_expiry_is_expired(self):
        looper, helper = looper_and_mate()
        stale = ask(9, "Looper", expires_at=NOW - datetime.timedelta(minutes=1))
        found = deathask.plan_pass(
            {"Looper": loop_of()}, [looper, helper], [stale], NOW
        )
        self.assertEqual(found.expire, ((9, "Looper", ""),))
        self.assertEqual(found.posts, ())

    def test_a_live_ask_not_past_its_expiry_is_not_expired(self):
        looper, helper = looper_and_mate()
        live = ask(9, "Looper")
        found = deathask.plan_pass({"Looper": loop_of()}, [looper, helper], [live], NOW)
        self.assertEqual(found.expire, ())

    def test_a_recovered_loopers_ask_is_expired(self):
        looper, helper = looper_and_mate()
        live = ask(9, "Looper")
        found = deathask.plan_pass({}, [looper, helper], [live], NOW)
        self.assertEqual(found.expire, ((9, "Looper", ""),))
        self.assertEqual(found.posts, ())

    def test_the_empty_pool_expires_every_live_ask(self):
        rows = [ask(9, "Looper"), ask(10, "Other")]
        found = deathask.plan_pass({}, [], rows, NOW)
        self.assertEqual(found.expire, ((9, "Looper", ""), (10, "Other", "")))
        self.assertEqual(found.posts, ())

    def test_expired_asks_free_the_guild_open_cap(self):
        looper, helper = looper_and_mate()
        stale = [
            ask(i, name, expires_at=NOW - datetime.timedelta(minutes=1))
            for i, name in enumerate(("Alpha", "Bravo", "Charlie"), start=1)
        ]
        loops = {name: loop_of(name) for name in ("Alpha", "Bravo", "Charlie")}
        loops["Looper"] = loop_of()
        found = deathask.plan_pass(loops, [looper, helper], stale, NOW)
        self.assertEqual(len(found.expire), 3)
        self.assertEqual([p.asker for p in found.posts], ["Looper"])

    def test_the_switch_is_off_until_the_answer_side_exists(self):
        self.assertFalse(deathask.enabled({}))
        self.assertTrue(deathask.enabled({"DEATH_ASK": "on"}))
        self.assertFalse(deathask.enabled({"DEATH_ASK": "off"}))

    def test_a_held_looper_is_not_asked_for(self):
        looper, helper = looper_and_mate()
        found = deathask.plan_pass(
            {"Looper": loop_of()},
            [looper, helper],
            [],
            NOW,
            held={"Looper": "on a guild job"},
        )
        self.assertEqual(found.posts, ())


if __name__ == "__main__":
    unittest.main()
