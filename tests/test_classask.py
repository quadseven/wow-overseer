"""A class quest that needs help is asked for, answered, and kept out of the
dungeon passes while it is (classask.py), and a hunt that stalls moves on.

The class quests and spawns are the fixtures of test_classquest.py (rows read
from acore_world on 2026-10-06). The group quest here is the shape of a
paladin's level-12 elite chain: a suggested group of 3 and an objective
creature, handed to the pass as a quest row.
"""

import asyncio
import datetime
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import classask  # noqa: E402
import classparty  # noqa: E402
import classquest  # noqa: E402
import guildjobs  # noqa: E402
import guildrun  # noqa: E402
import guildsocial as gs  # noqa: E402
from test_classquest import (  # noqa: E402
    HIDE,
    LIZARD,
    book,
    class_plan,
    class_steps,
    givers,
    qrow,
    who,
)
from test_guildsocial import NOW, ask, mate, yes  # noqa: E402
from test_guildsocial_bridge import _Self, bridge, facts  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

MIN = 60.0
STALL = classquest.HUNT_STALL_MINUTES * MIN


def hunter(**over):
    base = dict(
        quest_log={1498: 3},
        quests_done=frozenset({1505}),
        x=720.0,
        y=-4100.0,
        quest_progress={1498: 0},
    )
    base.update(over)
    return who(**base)


def pack(n):
    """A third and fourth pack of the objective, far from the other two."""
    return dict(LIZARD, guid=9000 + n, x=1500.0 + 400 * n, y=-4500.0)


def three_packs():
    return book(spawn_rows=[LIZARD, HIDE, pack(1), pack(2)])


def group_book():
    """One quest the member holds that wants a group of 3."""
    rows = [qrow(2000, "Group Job", reward=8121, grp=3, npc1=3130, npc_count1=1)]
    return classquest.build(
        quest_rows=rows, giver_rows=givers(), spawn_rows=[LIZARD], loot_rows=[]
    )


def asker(name="Bigzug", **over):
    base = dict(quest_log={2000: 3})
    base.update(over)
    return who(name, **base)


class TheHuntClock(unittest.TestCase):
    def plan(self, member, hunts, now, b=None, **kw):
        return class_plan([member], b=b, hunts=hunts, now=now, **kw)

    def test_a_hunt_with_no_progress_is_sent_to_another_pack(self):
        hunts = classquest.Hunts()
        m = hunter()
        first = self.plan(m, hunts, 0.0)
        self.assertEqual(first.steps, ())
        self.assertIn(classquest.MARK, first.lines["Bigzug"])
        later = self.plan(m, hunts, STALL + 1)
        steps = class_steps(later)
        self.assertEqual(len(steps), 1)
        self.assertTrue(
            steps[0].rows[0].command.startswith("walk-to-spawn creature:12197")
        )

    def test_progress_restarts_the_clock(self):
        hunts = classquest.Hunts()
        self.plan(hunter(), hunts, 0.0)
        self.plan(hunter(quest_progress={1498: 2}), hunts, STALL - 5 * MIN)
        held = self.plan(hunter(quest_progress={1498: 2}), hunts, STALL + 5 * MIN)
        self.assertEqual(held.steps, ())
        self.assertIn(classquest.MARK, held.lines["Bigzug"])

    def test_a_walk_that_keeps_failing_is_a_stall_at_once(self):
        hunts = classquest.Hunts()
        recent = (
            guildjobs.Recent("Bigzug", classquest.ACTION, 12, status="error"),
            guildjobs.Recent("Bigzug", classquest.ACTION, 30, status="unchanged"),
        )
        steps = class_steps(self.plan(hunter(), hunts, 0.0, recent=recent))
        self.assertTrue(
            steps[0].rows[0].command.startswith("walk-to-spawn creature:12197")
        )

    def test_without_a_clock_a_hunt_never_stalls(self):
        held = class_plan([hunter()])
        self.assertEqual(held.steps, ())

    def test_every_pack_tried_gives_the_quest_up_for_a_while(self):
        b, hunts, t = three_packs(), classquest.Hunts(), 0.0
        m = hunter()
        self.plan(m, hunts, t, b=b)
        for _ in range(classquest.MAX_REROLLS + 1):
            t += STALL + 1
            result = self.plan(m, hunts, t, b=b)
        self.assertEqual(result.steps, ())
        self.assertNotIn(classquest.MARK, result.lines["Bigzug"])
        self.assertEqual(guildjobs.class_held(result.lines), set())
        self.assertTrue(any("stalled" in n for n in result.notes))
        self.assertEqual([h.move.quest for h in result.helps], [1498])
        # Held off for GIVE_UP_MINUTES, then it hunts afresh.
        soon = self.plan(m, hunts, t + 60 * MIN, b=b)
        self.assertNotIn(classquest.MARK, soon.lines["Bigzug"])
        after = self.plan(m, hunts, t + classquest.GIVE_UP_MINUTES * MIN + 1, b=b)
        self.assertIn(classquest.MARK, after.lines["Bigzug"])

    def test_a_field_with_no_other_pack_is_a_stall_not_a_wait(self):
        hunts = classquest.Hunts()
        m = hunter()
        self.plan(m, hunts, 0.0)
        self.plan(m, hunts, STALL + 1)
        result = self.plan(hunter(x=918.0, y=-4269.0), hunts, 2 * STALL + 2)
        self.assertNotIn(classquest.MARK, result.lines["Bigzug"])
        self.assertEqual([h.move.blocker for h in result.helps], ["stalled"])

    def test_the_numbers_are_those_of_the_step_conventions(self):
        farm = guildjobs.COOLDOWN_MINUTES["farm"]
        self.assertLess(classquest.HUNT_STALL_MINUTES, farm)
        self.assertGreater(
            classquest.HUNT_STALL_MINUTES, guildjobs.COOLDOWN_MINUTES["craft"]
        )
        self.assertEqual(classquest.GIVE_UP_MINUTES, 120)


class TheClock(unittest.TestCase):
    """No clock value is a sentinel: a monotonic clock may start at 0."""

    def spot(self):
        return classquest.Spawn(1, 3130, 1, 705.0, -4112.0, "Lizard")

    def test_an_unset_hold_off_is_none_not_zero(self):
        self.assertIsNone(classquest.Hunt(1498, 0, 0.0).until)

    def test_a_give_up_at_clock_zero_still_holds_off(self):
        hunts = classquest.Hunts()
        spot = self.spot()
        hunts.observe("Bigzug", 1498, 0, spot, 0.0)
        # A hold-off that ends at exactly 0.0 is set until then, not unset.
        hunts._by["Bigzug"] = classquest.Hunt(1498, 0, -10.0, (), 0.0)
        avoid, off = hunts.state("Bigzug", -1.0)
        self.assertEqual(off, frozenset({1498}))
        avoid, off = hunts.state("Bigzug", 0.0)
        self.assertEqual(off, frozenset())

    def test_a_hold_off_set_from_a_small_clock_lapses_on_time(self):
        hunts = classquest.Hunts()
        spot = self.spot()
        t = 0.0
        for _ in range(classquest.MAX_REROLLS + 1):
            verdict = hunts.observe("Bigzug", 1498, 0, spot, t, failed=True)
        self.assertEqual(verdict, classquest.GIVE_UP)
        self.assertEqual(hunts.state("Bigzug", 1.0)[1], frozenset({1498}))
        later = classquest.GIVE_UP_MINUTES * 60.0 + 1
        self.assertEqual(hunts.state("Bigzug", later)[1], frozenset())


class TheRolesNeeded(unittest.TestCase):
    """roles_needed is a tuple of seats (guildsocial.roles_of), so a one-seat
    ask wants one helper and "dps,dps" two."""

    def wanted(self, roles):
        out = pass_(helps_of("Bigzug"), friends(), asks=[qask(1, roles_needed=roles)])
        return len(out.replies)

    def test_one_dps_ask_draws_one_answer(self):
        self.assertEqual(self.wanted("dps"), 1)

    def test_two_dps_ask_draws_two_answers(self):
        self.assertEqual(self.wanted("dps,dps"), 2)


class TheHelps(unittest.TestCase):
    def test_a_group_quest_with_no_other_move_is_a_help_for_two(self):
        result = class_plan([asker()], b=group_book())
        self.assertEqual(len(result.helps), 1)
        h = result.helps[0]
        self.assertEqual((h.member, h.move.quest, h.move.want), ("Bigzug", 2000, 2))
        self.assertEqual(h.move.spot.entry, 3130)

    def test_a_member_with_a_quest_it_can_do_asks_for_nothing(self):
        self.assertEqual(class_plan([hunter()]).helps, ())

    def test_an_elite_objective_asks_for_two(self):
        rows = [qrow(2001, "Elite Job", reward=8121, npc1=3130, npc_count1=1)]
        b = classquest.build(
            quest_rows=rows,
            giver_rows=givers(),
            spawn_rows=[dict(LIZARD, rank=1)],
            loot_rows=[],
        )
        result = class_plan([asker(quest_log={2001: 3})], b=b)
        self.assertEqual(result.helps[0].move.want, classquest.ELITE_HELPERS)


def helps_of(*names, b=None):
    members = [asker(n, x=-282.0 + i) for i, n in enumerate(names)]
    return list(class_plan(members, b=b or group_book()).helps)


def mates(*specs):
    return [mate(n, lvl, 1, guild=g, at=at, map_id=m) for n, lvl, g, at, m in specs]


NEAR = (-282.0, -4164.0)
CAVE = "Bonkers"


def friends():
    return mates(
        ("Bigzug", 20, CAVE, NEAR, 1),
        ("Chill", 19, CAVE, (-250.0, -4150.0), 1),
        ("Dread", 21, CAVE, (-300.0, -4100.0), 1),
        ("Ghoul", 22, CAVE, (-100.0, -4000.0), 1),
    )


def pass_(helps, mates_, held=None, asks=(), answers=(), now=NOW):
    return classask.plan_pass(helps, mates_, held or {}, list(asks), list(answers), now)


def qask(id_, asker_="Bigzug", **kw):
    kw.setdefault("kind", "quest")
    kw.setdefault("target", "quest:2000")
    kw.setdefault("target_label", "Group Job")
    kw.setdefault("roles_needed", "dps,dps")
    kw.setdefault("guild", CAVE)
    return ask(id_, asker_, **kw)


class TheAsk(unittest.TestCase):
    def test_a_member_with_a_group_quest_asks_in_guild_chat(self):
        out = pass_(helps_of("Bigzug"), friends())
        self.assertEqual(len(out.posts), 1)
        post = out.posts[0]
        self.assertEqual(
            (post.kind, post.asker, post.target, post.roles_needed),
            ("quest", "Bigzug", "quest:2000", "dps,dps"),
        )
        self.assertIn("Group Job", post.said)
        self.assertTrue(post.said.isascii())
        self.assertLessEqual(len(post.said), 255)

    def test_a_stalled_hunt_asks_for_company(self):
        h = classquest.Help(
            "Bigzug",
            CAVE,
            20,
            1,
            classquest.Move(
                classquest.BLOCKED,
                1498,
                1,
                None,
                "x",
                classquest.STALLED,
                "",
                1,
                "Path of Defense",
            ),
        )
        post = pass_([h], friends()).posts[0]
        self.assertEqual(post.roles_needed, "dps")
        self.assertIn("Path of Defense", post.said)

    def test_one_open_ask_per_member_and_a_cooldown_after_one_ran_out(self):
        live = qask(1)
        self.assertEqual(pass_(helps_of("Bigzug"), friends(), asks=[live]).posts, ())
        gone = qask(
            2,
            state="expired",
            created_at=NOW - datetime.timedelta(minutes=5),
            expires_at=NOW - datetime.timedelta(minutes=1),
        )
        self.assertEqual(pass_(helps_of("Bigzug"), friends(), asks=[gone]).posts, ())
        old = qask(
            3,
            state="expired",
            created_at=NOW - datetime.timedelta(minutes=40),
            expires_at=NOW - datetime.timedelta(minutes=30),
        )
        self.assertEqual(len(pass_(helps_of("Bigzug"), friends(), asks=[old]).posts), 1)

    def test_a_member_that_is_not_free_does_not_ask(self):
        held = {"Bigzug": "in combat"}
        self.assertEqual(pass_(helps_of("Bigzug"), friends(), held=held).posts, ())

    def test_the_dungeon_asks_are_not_read_as_quest_asks(self):
        dungeon = ask(1, "Bigzug", guild=CAVE)
        out = pass_(helps_of("Bigzug"), friends(), asks=[dungeon])
        self.assertEqual(len(out.posts), 1)


class TheAnswer(unittest.TestCase):
    def replies(self, mates_=None, held=None, **kw):
        out = pass_(helps_of("Bigzug"), mates_ or friends(), held, asks=[qask(1)], **kw)
        return out.replies

    def test_free_guildmates_nearby_answer_up_to_what_the_quest_wants(self):
        replies = self.replies()
        self.assertEqual([r.member for r in replies], ["Chill", "Dread"])
        for r in replies:
            self.assertEqual((r.stance, r.role, r.ask_id), (gs.HELPS, gs.DPS, 1))
            self.assertIn("Bigzug", r.said)

    def test_another_guild_another_continent_or_far_in_level_do_not(self):
        crowd = mates(
            ("Bigzug", 20, CAVE, NEAR, 1),
            ("Other", 20, "Cave", NEAR, 1),
            ("Away", 20, CAVE, NEAR, 0),
            ("Low", 8, CAVE, NEAR, 1),
            ("Busy", 20, CAVE, NEAR, 1),
        )
        self.assertEqual(self.replies(crowd, {"Busy": "on a guild job"}), ())

    def test_a_member_answers_one_ask(self):
        said = [yes(1, 1, "Chill", "dps", "help")]
        out = pass_(helps_of("Bigzug"), friends(), asks=[qask(1)], answers=said)
        self.assertEqual([r.member for r in out.replies], ["Dread"])

    def test_a_full_ask_is_marked_filled_and_its_party_is_formed_next(self):
        answers = [yes(1, 1, "Chill", "dps", "help"), yes(2, 1, "Dread", "dps", "help")]
        out = pass_(helps_of("Bigzug"), friends(), asks=[qask(1)], answers=answers)
        self.assertEqual(out.filled, (1,))
        self.assertEqual(out.replies, ())
        self.assertTrue(any("party is formed" in n for n in out.notes))

    def test_a_full_ask_on_a_worldserver_with_no_party_verbs_says_so(self):
        answers = [yes(1, 1, "Chill", "dps", "help"), yes(2, 1, "Dread", "dps", "help")]
        out = classask.plan_pass(
            helps_of("Bigzug"), friends(), {}, [qask(1)], answers, NOW, seats=False
        )
        self.assertTrue(any("does not seat a party" in n for n in out.notes))

    def test_a_full_ask_with_its_party_up_says_nothing_more(self):
        answers = [yes(1, 1, "Chill", "dps", "help"), yes(2, 1, "Dread", "dps", "help")]
        out = classask.plan_pass(
            helps_of("Bigzug"), friends(), {}, [qask(1)], answers, NOW, partied={1}
        )
        self.assertEqual(out.notes, ())

    def test_an_answerer_out_of_seating_range_does_not_answer(self):
        far = mates(
            ("Bigzug", 20, CAVE, NEAR, 1),
            ("Near", 20, CAVE, (-250.0, -4150.0), 1),
            ("Far", 20, CAVE, (NEAR[0] + classask.SEAT_RANGE_YARDS + 5, NEAR[1]), 1),
        )
        out = pass_(helps_of("Bigzug"), far, asks=[qask(1)])
        self.assertEqual([r.member for r in out.replies], ["Near"])

    def test_a_member_the_module_refused_for_this_ask_does_not_answer_it_again(self):
        out = classask.plan_pass(
            helps_of("Bigzug"),
            friends(),
            {},
            [qask(1)],
            [],
            NOW,
            refused={1: frozenset({"Chill"})},
        )
        self.assertEqual([r.member for r in out.replies], ["Dread"])
        other = classask.plan_pass(
            helps_of("Bigzug"),
            friends(),
            {},
            [qask(1)],
            [],
            NOW,
            refused={2: frozenset({"Chill"})},
        )
        self.assertEqual([r.member for r in other.replies], ["Chill", "Dread"])

    def test_an_asker_that_gave_up_lately_does_not_ask_again(self):
        out = classask.plan_pass(
            helps_of("Bigzug"), friends(), {}, [], [], NOW, cooling={"Bigzug"}
        )
        self.assertEqual(out.posts, ())

    def test_a_yes_from_a_member_no_longer_free_is_withdrawn(self):
        answers = [yes(1, 1, "Chill", "dps", "help")]
        out = pass_(
            helps_of("Bigzug"),
            friends(),
            {"Chill": "offline"},
            asks=[qask(1)],
            answers=answers,
        )
        self.assertEqual(out.withdraw, (1,))


class TheEnd(unittest.TestCase):
    def test_an_ask_past_its_time_expires(self):
        late = qask(1, expires_at=NOW - datetime.timedelta(minutes=1))
        out = pass_(helps_of("Bigzug"), friends(), asks=[late])
        self.assertEqual([e[0] for e in out.expire], [1])

    def test_an_ask_whose_quest_is_done_is_cancelled(self):
        out = pass_([], friends(), asks=[qask(1)])
        self.assertEqual(out.cancel, (1,))

    def test_an_ask_whose_asker_left_is_cancelled(self):
        out = pass_(
            helps_of("Bigzug"), friends(), {"Bigzug": "offline"}, asks=[qask(1)]
        )
        self.assertEqual(out.cancel, (1,))


class TheHold(unittest.TestCase):
    """Dungeon passes leave alone the members of a class quest party that is up,
    and only while its row is live. The long hold of an answered ask is gone."""

    def party(self):
        return classparty.PartyRun(
            1, "Bigzug", ("Chill", "Dread"), 2000, "Group Job", None
        )

    def test_the_leader_and_the_helpers_of_a_live_party_are_held(self):
        self.assertEqual(
            classask.held_names([self.party()]), {"Bigzug", "Chill", "Dread"}
        )

    def test_an_answered_ask_with_no_party_holds_nobody(self):
        self.assertEqual(classask.held_names([]), set())
        board = classparty.Board()
        self.assertEqual(board.names(), set())

    def test_the_hold_ends_at_once_with_the_party(self):
        board = classparty.Board()
        run = self.party()
        board.begin(run)
        self.assertEqual(board.names(), {"Bigzug", "Chill", "Dread"})
        board.end(run, 0.0, done=False)
        self.assertEqual(board.names(), set())


class TheDungeonPasses(unittest.TestCase):
    """The class quest comes before the dungeon in every pass that forms one."""

    def social(self, helps=(), asks=(), answers=()):
        this = _Self()
        this._class_helps = tuple(helps)
        this._class_board = classparty.Board()
        this._class_book = None
        this.started = []
        this._begin_class_parties = this.started.extend
        data = facts()
        data["asks"] = list(data["asks"]) + list(asks)
        data["answers"] = list(data["answers"]) + list(answers)
        written = []

        def write(social):
            written.append(social)
            return 41 if social.form else 0

        with mock.patch.multiple(
            bridge,
            _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
            _guild_runs_in_flight=lambda: 0,
            _fetch_guild_social_facts=lambda bounds: data,
            _write_guild_social=write,
            _guild_social_names=lambda: set(),
        ):
            asyncio.run(bridge.Bridge._guild_social_once(this))
        self.last = this
        return written[0]

    def social_with(self, **kw):
        out = self.social(**kw)
        return out, self.last

    def group_help(self, member="Auren"):
        spot = classquest.Spawn(9, 3130, 0, -11100.0, 1600.0, "Lizard")
        return classquest.Help(
            member,
            "Cave",
            20,
            0,
            classquest.Move(
                classquest.BLOCKED,
                2000,
                1,
                spot,
                "x",
                classquest.GROUP,
                "",
                1,
                "Group Job",
            ),
        )

    def test_a_member_in_a_party_about_to_form_is_not_seated_in_a_dungeon(self):
        quest_ask = qask(50, "Auren", guild="Cave", roles_needed="dps")
        answered = yes(60, 50, "Zappy", "dps", "help")
        out, this = self.social_with(
            helps=[self.group_help()], asks=[quest_ask], answers=[answered]
        )
        self.assertIsNone(out.form)
        self.assertIn(3, out.withdraw)
        self.assertEqual([r.names() for r in this.started], [("Auren", "Zappy")])

    def test_an_answered_ask_with_no_objective_to_walk_to_holds_nobody(self):
        quest_ask = qask(50, "Auren", guild="Cave", roles_needed="dps")
        answered = yes(60, 50, "Zappy", "dps", "help")
        out, this = self.social_with(asks=[quest_ask], answers=[answered])
        self.assertEqual(this.started, [])
        self.assertIsNotNone(out.form)

    def test_the_dungeon_ask_still_forms_with_no_quest_ask(self):
        self.assertIsNotNone(self.social().form)

    def test_a_member_with_an_unanswered_quest_ask_is_not_held(self):
        quest_ask = qask(50, "Zappy", guild="Cave", roles_needed="dps")
        self.assertIsNotNone(self.social(asks=[quest_ask]).form)

    def test_the_quest_asks_ride_the_one_writer(self):
        h = classquest.Help(
            "Idle",
            "Cave",
            20,
            0,
            classquest.Move(
                classquest.BLOCKED,
                2000,
                1,
                None,
                "x",
                classquest.GROUP,
                "",
                2,
                "Group Job",
            ),
        )
        out = self.social(helps=[h])
        self.assertEqual([p.kind for p in out.posts], ["quest"])
        self.assertEqual(out.posts[0].asker, "Idle")

    def test_the_old_coordinator_does_not_pick_a_member_on_a_class_quest(self):
        seen = {}

        def free_members(rows, busy, resting, family, benched=frozenset()):
            seen["busy"] = set(busy)
            return [], {}

        this = _Self()
        this._classquest_held = {"Zappy"}
        this._class_board = classparty.Board()
        this._class_board.begin(
            classparty.PartyRun(1, "Locky", ("Idle",), 2000, "Group Job", None)
        )
        data = facts()
        with (
            mock.patch.multiple(
                bridge,
                _guild_runs_in_flight=lambda: 0,
                _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
                _fetch_guild_run_facts=lambda bounds: data,
            ),
            mock.patch.object(guildrun, "free_members", free_members),
        ):
            asyncio.run(bridge.Bridge._guild_run_once(this))
        self.assertGreaterEqual(seen["busy"], {"Zappy", "Locky", "Idle"})


class TheWiring(unittest.TestCase):
    def test_the_image_carries_the_module(self):
        self.assertIn("classask.py", DOCKERFILE)

    def test_the_bridge_keeps_the_hunt_clock_and_hands_it_to_the_plan(self):
        self.assertIn("hunts=self._class_hunts, now=time.time()", BRIDGE)
        self.assertIn("self._class_helps = plan.helps", BRIDGE)

    def test_the_dungeon_ask_pass_reads_only_dungeon_asks(self):
        self.assertIn("a.kind == guildsocial.KIND_DUNGEON", BRIDGE)

    def test_the_progress_is_read_with_the_log(self):
        self.assertIn("mobcount1", classquest.LOG_SQL)
        self.assertIn("itemcount6", classquest.LOG_SQL)


if __name__ == "__main__":
    unittest.main()
