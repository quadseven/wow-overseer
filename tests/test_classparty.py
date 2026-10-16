"""A filled class quest ask forms a party, walks it to the objective and ends it
(classparty.py, and the bridge's _run_class_party that follows the rows).

The rows are quadseven/mod-overseer#866's: `party-up` (kind guild), `party-walk`
(kind job) and `party-disband` (kind guild), their answers read as the module
words them.
"""

import asyncio
import datetime
import json
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import classask  # noqa: E402
import classparty  # noqa: E402
import classquest  # noqa: E402
import guildroute  # noqa: E402
import guildsocial as gs  # noqa: E402
from test_classask import (  # noqa: E402
    CAVE,
    NEAR,
    friends,
    helps_of,
    mates,
    qask,
)
from test_classquest import LIZARD, givers, qrow  # noqa: E402
from test_guildsocial import NOW, yes  # noqa: E402
from test_guildsocial_bridge import bridge  # noqa: E402

SPOT = classquest.Spawn(9, 3130, 1, -240.0, -4100.0, "Lizard")


def answer(status, why="", phase="", detail=""):
    body = {}
    if phase:
        body["phase"] = phase
    if why:
        body["why"] = why
    return {"status": status, "detail": detail, "result": json.dumps(body)}


FORMED = answer("applied", phase="formed")


class TheUpAnswer(unittest.TestCase):
    def judge(self, status, why="", phase="", detail=""):
        row = answer(status, why, phase, detail)
        return classparty.judge_up(
            "Bigzug", row["status"], row["detail"], row["result"]
        )

    def test_a_formed_party(self):
        self.assertEqual(self.judge("applied", phase="formed").state, classparty.FORMED)

    def test_applied_without_a_formed_party_is_not_trusted(self):
        self.assertEqual(self.judge("applied").state, classparty.BAD)

    def test_a_row_not_yet_answered_is_waited_on(self):
        for status in ("pending", "claimed", "verifying", ""):
            self.assertEqual(self.judge(status).state, classparty.WAITING)

    def test_a_refusal_names_a_helper(self):
        got = self.judge("error", "'Chill': a helper is in combat", "refused")
        self.assertEqual((got.state, got.name), (classparty.HELPER, "Chill"))
        got = self.judge("error", "'Dread' could not join the party", "refused")
        self.assertEqual((got.state, got.name), (classparty.HELPER, "Dread"))

    def test_a_refusal_naming_the_leader_waits(self):
        for why in (
            "the leader is in combat",
            "the leader is already in a party",
            "the leader leads a family campaign",
            "the realm already has 4 quest parties (Overseer.PartyWalk.MaxParties)",
            "the core would not form a party under the leader",
        ):
            self.assertEqual(
                self.judge("error", why, "refused").state, classparty.LEADER, why
            )

    def test_a_malformed_row_is_neither_a_helper_nor_the_leader(self):
        why = "a name in the row is not a character name"
        self.assertEqual(self.judge("error", why, "refused").state, classparty.BAD)

    def test_a_worldserver_before_the_verbs_is_unsupported(self):
        detail = "malformed request: want take quest:<id> or turnin quest:<id>"
        self.assertEqual(
            self.judge("error", detail=detail).state, classparty.UNSUPPORTED
        )
        self.assertEqual(
            self.judge("error", "Overseer.PartyWalk.Enable is off", "refused").state,
            classparty.UNSUPPORTED,
        )

    def test_a_refusal_with_no_words_is_bad_not_a_crash(self):
        self.assertEqual(self.judge("error").state, classparty.BAD)
        self.assertEqual(
            classparty.judge_up("B", "error", "x", "not json").state, classparty.BAD
        )

    def test_the_walk_of_an_old_worldserver_is_told_from_any_other_ending(self):
        self.assertTrue(
            classparty.walk_unsupported("A cannot walk to x: malformed request: y")
        )
        self.assertTrue(classparty.walk_unsupported("unknown job mode"))
        self.assertFalse(
            classparty.walk_unsupported(
                "A cannot walk to x: the character leads no quest party"
            )
        )


class TheCommands(unittest.TestCase):
    def test_party_up_names_one_to_four_helpers(self):
        self.assertEqual(
            classparty.up_command(("Chill", "Dread")), "party-up Chill Dread"
        )

    def test_party_walk_names_the_spawn_and_the_far_cap_only_when_far(self):
        self.assertEqual(
            classparty.walk_command(SPOT, 20000.0), "party-walk creature:9 max:20000"
        )
        self.assertEqual(
            classparty.walk_command(SPOT, guildroute.TRAINER_WALK_YARDS),
            "party-walk creature:9",
        )

    def test_the_rows_are_the_modules_verbs(self):
        self.assertEqual(
            (classparty.UP, classparty.WALK, classparty.DISBAND),
            ("party-up", "party-walk", "party-disband"),
        )
        self.assertEqual(classparty.SOURCE, "classask")

    def test_the_quest_log_is_read_as_the_planner_reads_it(self):
        self.assertEqual(classparty.quest_state(1), classparty.COMPLETE)
        self.assertEqual(classparty.quest_state(3), classparty.INCOMPLETE)
        self.assertEqual(classparty.quest_state(None), classparty.GONE)
        self.assertTrue(classparty.objective_done(classparty.GONE))
        self.assertFalse(classparty.objective_done(classparty.INCOMPLETE))


class TheBoard(unittest.TestCase):
    def run_(self, ask_id=1, formed=True):
        run = classparty.PartyRun(ask_id, "Bigzug", ("Chill",), 2000, "Group Job", SPOT)
        if formed:
            run.form(100.0)
        return run

    def test_a_party_holds_until_it_ends(self):
        board, run = classparty.Board(), self.run_()
        board.begin(run)
        self.assertEqual(board.names(), {"Bigzug", "Chill"})
        self.assertEqual(board.partied_asks(), {1})
        board.end(run, 200.0, done=True)
        self.assertEqual(board.names(), set())
        self.assertEqual(board.cooling(200.0), set())

    def test_a_party_that_formed_and_did_not_finish_cools_its_leader(self):
        board, run = classparty.Board(), self.run_()
        board.begin(run)
        board.end(run, 200.0, done=False)
        self.assertEqual(board.cooling(200.0), {"Bigzug"})
        later = 200.0 + classparty.ENDED_COOLDOWN_MINUTES * 60 + 1
        self.assertEqual(board.cooling(later), set())

    def test_a_party_that_never_formed_cools_nobody(self):
        board, run = classparty.Board(), self.run_(formed=False)
        board.begin(run)
        board.end(run, 200.0, done=False)
        self.assertEqual(board.cooling(200.0), set())

    def test_the_failures_of_an_ask_run_out_at_the_limit(self):
        board = classparty.Board()
        for n in range(1, classparty.MAX_FAILURES + 1):
            self.assertFalse(board.exhausted(1))
            self.assertEqual(board.fail(1), n)
        self.assertTrue(board.exhausted(1))
        self.assertFalse(board.exhausted(2))

    def test_the_helpers_a_refusal_named_are_kept_per_ask(self):
        board = classparty.Board()
        board.refuse(1, "Chill")
        self.assertEqual(board.refused(), {1: frozenset({"Chill"})})

    def test_what_is_kept_for_an_ask_that_is_over_is_forgotten(self):
        board = classparty.Board()
        board.refuse(1, "Chill")
        board.fail(1)
        board.refuse(2, "Dread")
        board.prune([2])
        self.assertEqual(board.refused(), {2: frozenset({"Dread"})})
        self.assertEqual(board.failures(1), 0)

    def test_an_ask_with_its_party_up_keeps_what_was_kept(self):
        board, run = classparty.Board(), self.run_()
        board.begin(run)
        board.fail(1)
        board.prune([])
        self.assertEqual(board.failures(1), 1)

    def test_an_old_worldserver_is_not_asked_again_for_the_window(self):
        board = classparty.Board()
        self.assertTrue(board.seats(0.0))
        board.mark_unsupported(10.0)
        self.assertFalse(board.seats(11.0))
        self.assertTrue(board.seats(10.0 + guildroute.WALK_UNSUPPORTED_SECONDS))

    def test_the_party_clock_leaves_its_time(self):
        run = self.run_()
        self.assertEqual(run.left(100.0), classparty.PARTY_SECONDS)
        self.assertLess(run.left(100.0 + classparty.PARTY_SECONDS), 1)
        self.assertLess(classparty.PARTY_SECONDS, 1800)

    def test_a_helper_is_found_whatever_the_case(self):
        self.assertEqual(self.run_().helper_named("CHILL"), "Chill")
        self.assertEqual(self.run_().helper_named("Nobody"), "")


def free_of(mates_, held=()):
    return {m.name: m for m in mates_ if m.name not in held}


def old_ask(id_, **kw):
    return qask(id_, **kw)


class ThePartiesToForm(unittest.TestCase):
    def plan(self, asks, answers, board=None, mates_=None, helps=None, held=None, **kw):
        mates_ = mates_ or friends()
        helps = helps if helps is not None else helps_of("Bigzug")
        board = board or classparty.Board()
        held = held or {}
        quest_pass = classask.plan_pass(
            helps, mates_, held, asks, answers, NOW, partied=board.partied_asks()
        )
        return classparty.plan_starts(
            asks,
            answers,
            quest_pass,
            helps,
            free_of(mates_, held),
            board,
            NOW,
            0.0,
            **kw,
        )

    FULL = [yes(1, 1, "Chill", "dps", "help"), yes(2, 1, "Dread", "dps", "help")]

    def aged(self):
        return qask(1, created_at=NOW - datetime.timedelta(minutes=5))

    def test_a_full_ask_forms_a_party_of_its_answerers_under_the_asker(self):
        (run,) = self.plan([qask(1)], self.FULL)
        self.assertEqual((run.leader, run.helpers), ("Bigzug", ("Chill", "Dread")))
        self.assertEqual((run.ask_id, run.quest, run.title), (1, 2000, "Group Job"))
        self.assertEqual(run.answers, {"Chill": 1, "Dread": 2})
        self.assertEqual(run.spot.entry, 3130)
        self.assertIsNone(run.formed_at)

    def test_an_ask_with_some_yes_waits_for_the_rest_then_goes_without(self):
        one = [yes(1, 1, "Chill", "dps", "help")]
        young = qask(1, created_at=NOW - datetime.timedelta(minutes=1))
        self.assertEqual(self.plan([young], one), ())
        patient = qask(
            1,
            created_at=NOW
            - datetime.timedelta(minutes=classparty.PARTIAL_WAIT_MINUTES),
        )
        (run,) = self.plan([patient], one)
        self.assertEqual(run.helpers, ("Chill",))

    def test_an_ask_nobody_answered_forms_nothing(self):
        old = qask(1, created_at=NOW - datetime.timedelta(minutes=9))
        self.assertEqual(self.plan([old], []), ())

    def test_at_most_four_helpers(self):
        many = mates(
            ("Bigzug", 20, CAVE, NEAR, 1),
            *[("H%d" % i, 20, CAVE, (NEAR[0] + i, NEAR[1]), 1) for i in range(6)],
        )
        answers = [yes(i + 1, 1, "H%d" % i, "dps", "help") for i in range(6)]
        (run,) = self.plan(
            [qask(1, roles_needed="dps,dps,dps,dps,dps")], answers, mates_=many
        )
        self.assertEqual(len(run.helpers), classparty.MAX_HELPERS)

    def test_a_yes_taken_back_this_pass_is_not_seated(self):
        gone = {"Chill": "offline"}
        (run,) = self.plan([self.aged()], self.FULL, held=gone, mates_=friends())
        self.assertEqual(run.helpers, ("Dread",))

    def test_an_ask_that_ends_this_pass_forms_nothing(self):
        late = qask(1, expires_at=NOW - datetime.timedelta(minutes=1))
        self.assertEqual(self.plan([late], self.FULL), ())

    def test_an_asker_with_a_party_already_forms_no_second(self):
        board = classparty.Board()
        board.begin(
            classparty.PartyRun(1, "Bigzug", ("Chill", "Dread"), 2000, "x", SPOT)
        )
        self.assertEqual(self.plan([qask(1)], self.FULL, board=board), ())

    def test_a_member_in_another_party_is_not_seated_twice(self):
        board = classparty.Board()
        board.begin(classparty.PartyRun(9, "Ghoul", ("Chill",), 7, "x", SPOT))
        (run,) = self.plan([self.aged()], self.FULL, board=board)
        self.assertEqual(run.helpers, ("Dread",))

    def test_an_ask_given_up_forms_nothing(self):
        board = classparty.Board()
        for _ in range(classparty.MAX_FAILURES):
            board.fail(1)
        self.assertEqual(self.plan([qask(1)], self.FULL, board=board), ())

    def test_an_old_worldserver_forms_nothing_and_keeps_todays_behaviour(self):
        board = classparty.Board()
        board.mark_unsupported(0.0)
        self.assertEqual(self.plan([qask(1)], self.FULL, board=board), ())

    def test_a_quest_with_no_objective_spawn_forms_nothing(self):
        helps = helps_of("Bigzug")
        blind = [
            classquest.Help(
                h.member,
                h.guild,
                h.level,
                h.map_id,
                h.move.__class__(
                    h.move.kind,
                    h.move.quest,
                    h.move.klass,
                    None,
                    h.move.said,
                    h.move.blocker,
                    h.move.why,
                    h.move.want,
                    h.move.title,
                ),
            )
            for h in helps
        ]
        self.assertEqual(self.plan([qask(1)], self.FULL, helps=blind), ())

    def test_an_asker_that_is_not_free_forms_nothing(self):
        busy = {"Bigzug": "offline"}
        self.assertEqual(self.plan([qask(1)], self.FULL, held=busy), ())

    def test_an_asker_whose_quest_changed_forms_nothing(self):
        self.assertEqual(self.plan([qask(1, target="quest:77")], self.FULL), ())

    def test_a_dungeon_ask_forms_no_quest_party(self):
        self.assertEqual(self.plan([qask(1, kind="dungeon")], self.FULL), ())


class TheObjective(unittest.TestCase):
    def stalled_book(self):
        rows = [qrow(2000, "Hunt Job", reward=8121, npc1=3130, npc_count1=3)]
        return classquest.build(
            quest_rows=rows,
            giver_rows=givers(),
            spawn_rows=[LIZARD, dict(LIZARD, guid=9001, x=900.0, y=-4300.0)],
            loot_rows=[],
        )

    def move(self, blocker, spot=None):
        return classquest.Move(
            classquest.BLOCKED, 2000, 1, spot, "x", blocker, "", 1, "Hunt Job"
        )

    def at(self):
        return types.SimpleNamespace(map_id=1, x=720.0, y=-4100.0)

    def test_a_group_quest_goes_to_its_own_densest_pack(self):
        move = self.move(classquest.GROUP, SPOT)
        self.assertIs(classquest.objective_spot(None, move, self.at()), SPOT)

    def test_a_stalled_hunt_goes_back_to_the_objective_it_gave_up(self):
        b = self.stalled_book()
        got = classquest.objective_spot(b, self.move(classquest.STALLED), self.at())
        self.assertEqual(got.entry, 3130)
        self.assertEqual(got.map_id, 1)

    def test_a_use_that_changed_nothing_has_no_spot_to_walk_a_party_to(self):
        b = self.stalled_book()
        move = self.move(classquest.USE_STALLED)
        self.assertIsNone(classquest.objective_spot(b, move, self.at()))

    def test_a_stalled_hunt_with_no_book_has_none(self):
        self.assertIsNone(
            classquest.objective_spot(None, self.move(classquest.STALLED), self.at())
        )

    def test_a_stalled_party_start_takes_its_spot_from_the_book(self):
        b = self.stalled_book()
        stalled = classquest.Help("Bigzug", CAVE, 20, 1, self.move(classquest.STALLED))
        answers = [yes(1, 1, "Chill", "dps", "help")]
        mates_ = friends()
        one = qask(1, roles_needed="dps")
        quest_pass = classask.plan_pass([stalled], mates_, {}, [one], answers, NOW)
        (run,) = classparty.plan_starts(
            [one],
            answers,
            quest_pass,
            [stalled],
            free_of(mates_),
            classparty.Board(),
            NOW,
            0.0,
            b,
        )
        self.assertEqual(run.spot.entry, 3130)


class TheFreedomOfAPartyToItsAsk(unittest.TestCase):
    def test_a_party_member_the_core_reads_as_grouped_is_still_free_to_its_ask(self):
        board = classparty.Board()
        board.begin(classparty.PartyRun(1, "Bigzug", ("Chill",), 2000, "x", SPOT))
        held = {
            "Bigzug": "already in a group",
            "Chill": "in combat",
            "Dread": "already in a group",
            "Ghoul": "offline",
        }
        self.assertEqual(
            classparty.ask_held(held, board),
            {"Dread": "already in a group", "Ghoul": "offline"},
        )

    def test_a_party_member_who_is_dead_or_gone_still_ends_the_ask(self):
        board = classparty.Board()
        board.begin(classparty.PartyRun(1, "Bigzug", ("Chill",), 2000, "x", SPOT))
        held = classparty.ask_held(
            {"Chill": "dead", "Bigzug": "inside an instance"}, board
        )
        self.assertEqual(held, {"Chill": "dead", "Bigzug": "inside an instance"})

    def test_an_ask_with_its_party_up_does_not_run_out_by_its_own_clock(self):
        late = qask(1, expires_at=NOW - datetime.timedelta(minutes=1))
        answers = [yes(1, 1, "Chill", "dps", "help"), yes(2, 1, "Dread", "dps", "help")]
        out = classask.plan_pass(
            helps_of("Bigzug"), friends(), {}, [late], answers, NOW, partied={1}
        )
        self.assertEqual(out.expire, ())
        self.assertEqual(out.cancel, ())

    def test_the_same_ask_with_no_party_runs_out(self):
        late = qask(1, expires_at=NOW - datetime.timedelta(minutes=1))
        out = classask.plan_pass(helps_of("Bigzug"), friends(), {}, [late], [], NOW)
        self.assertEqual([e[0] for e in out.expire], [1])

    def test_a_party_member_that_went_missing_cancels_the_ask(self):
        board = classparty.Board()
        board.begin(classparty.PartyRun(1, "Bigzug", ("Chill",), 2000, "x", SPOT))
        held = classparty.ask_held({"Bigzug": "offline"}, board)
        out = classask.plan_pass(
            helps_of("Bigzug"), friends(), held, [qask(1)], [], NOW, partied={1}
        )
        self.assertEqual(out.cancel, (1,))


# --- the bridge follows the rows ------------------------------------------------------


class _Bridge:
    """The Bridge methods that follow a party, with the writes and reads stubbed."""

    def __init__(
        self, answers, walk=None, states=(), ask_live=True, meet=None, stands=None
    ):
        self._class_board = classparty.Board()
        self._guild_run_names = set()
        self.rows = []
        self.commands = {}
        self.stand_reads = []
        self.held_meeting = []
        self.held_up = []
        self.meet = dict(meet or {})
        self.stands = list(stands or ())
        self.settled = []
        self.withdrawn = []
        self.slept = []
        self.queue = list(answers)
        self.walk_answer = walk or guildroute.WalkAnswer(guildroute.ARRIVED, "arrived")
        self.states = list(states) or [classparty.COMPLETE]
        self.ask_live = ask_live

    def _guild_walk_cap(self):
        return 20000.0

    async def _await_corps_answer(self, row_id, seconds):
        if self.commands.get(row_id, "").startswith(classparty.UP):
            self.held_up.append(self._class_board.names())
        return self.queue.pop(0) if self.queue else None

    async def _follow_guild_walk(self, label, holder, row_id, cap, insert, goal):
        if not self.commands.get(row_id, "").startswith(classparty.MEET):
            return self.walk_answer, row_id
        self.held_meeting.append(self._class_board.names())
        got = self.meet.get(holder, guildroute.WalkAnswer(guildroute.ARRIVED, "here"))
        if got == HANG:
            await asyncio.Event().wait()
        return got, row_id


for _name in (
    "_run_class_party",
    "_class_party_meet",
    "_class_party_meet_walks",
    "_class_party_meet_walk",
    "_class_party_meet_seen",
    "_class_party_form",
    "_class_party_work",
    "_class_party_watch",
    "_class_party_disband_row",
    "_class_party_close",
    "_begin_class_parties",
    "_guild_busy_run_names",
):
    setattr(_Bridge, _name, getattr(bridge.Bridge, _name))


HANG = "hang"
# Where the snapshot shows a member standing at the objective (SPOT's map).
THERE = (1, -240.0, -4100.0)


def drive(this, run, **patches):
    ids = iter(range(100, 200))
    lock = __import__("threading").Lock()

    def insert(holder, row):
        with lock:
            this.rows.append((holder, row.kind, row.command, row.source))
            row_id = next(ids)
            this.commands[row_id] = row.command
            return row_id

    def stands(names):
        this.stand_reads.append(len(this.rows))
        if this.stands:
            return this.stands.pop(0) if len(this.stands) > 1 else this.stands[0]
        return {n: THERE for n in names}

    async def nap(seconds):
        this.slept.append(seconds)

    def state(name, quest):
        return this.states.pop(0) if len(this.states) > 1 else this.states[0]

    stubs = dict(
        _insert_corps_row=insert,
        _class_party_quest_state=state,
        _class_party_ask_live=lambda ask_id: this.ask_live,
        _class_party_withdraw=this.withdrawn.append,
        _class_party_settle=lambda r, formed, gave_up, done=False: this.settled.append(
            (r.ask_id, formed, gave_up)
        ),
        _class_party_stands=stands,
        CORPS_ROW_FOLLOW_SECONDS=1.0,
    )
    stubs.update(patches)
    this._class_board.begin(run)
    with (
        mock.patch.multiple(bridge, **stubs),
        mock.patch.object(bridge.asyncio, "sleep", nap),
    ):
        asyncio.run(this._run_class_party(run))


def a_run(meeting=False):
    """A run of Bigzug's ask 1 with Chill and Dread; by default one whose
    members have already met at the objective."""
    return classparty.PartyRun(
        1,
        "Bigzug",
        ("Chill", "Dread"),
        2000,
        "Group Job",
        SPOT,
        {"Chill": 11, "Dread": 12},
        meeting=meeting,
    )


class TheBridgeFollowsTheParty(unittest.TestCase):
    def test_a_formed_party_walks_waits_for_the_quest_and_is_disbanded(self):
        this = _Bridge(
            [FORMED, answer("applied", phase="ended")],
            states=[classparty.INCOMPLETE, classparty.INCOMPLETE, classparty.COMPLETE],
        )
        drive(this, a_run())
        self.assertEqual(
            this.rows,
            [
                ("Bigzug", "guild", "party-up Chill Dread", "classask"),
                ("Bigzug", "job", "party-walk creature:9 max:20000", "classask"),
                ("Bigzug", "guild", "party-disband", "classask"),
            ],
        )
        self.assertEqual(this.settled, [(1, True, False)])
        self.assertEqual(this._class_board.names(), set())
        self.assertEqual(this._class_board.cooling(0.0), set())
        self.assertEqual(this.slept, [classparty.WATCH_SECONDS] * 2)

    def test_the_members_are_held_only_while_the_party_row_is_live(self):
        this = _Bridge([FORMED, answer("applied", phase="ended")])
        seen = []
        original = this._class_board.end

        def end(run, now, done):
            seen.append(this._class_board.names())
            original(run, now, done)

        this._class_board.end = end
        drive(this, a_run())
        self.assertEqual(seen, [{"Bigzug", "Chill", "Dread"}])
        self.assertEqual(this._class_board.names(), set())

    def test_a_helper_refusal_takes_the_yes_back_and_asks_for_another_helper(self):
        refused = answer(
            "error", "'Chill': a helper is in combat", "refused", "refused: see result"
        )
        this = _Bridge([refused])
        drive(this, a_run())
        self.assertEqual(
            [r[1:3] for r in this.rows], [("guild", "party-up Chill Dread")]
        )
        self.assertEqual(this.withdrawn, [11])
        self.assertEqual(this._class_board.refused(), {1: frozenset({"Chill"})})
        self.assertEqual(this._class_board.failures(1), 1)
        self.assertEqual(this.settled, [(1, False, False)])
        self.assertEqual(this._class_board.names(), set())

    def test_the_refused_helper_is_not_picked_for_the_ask_again(self):
        this = _Bridge([answer("error", "'Chill': a helper is too far", "refused")])
        drive(this, a_run())
        out = classask.plan_pass(
            helps_of("Bigzug"),
            friends(),
            {},
            [qask(1)],
            [yes(2, 1, "Dread", "dps", "help")],
            NOW,
            refused=this._class_board.refused(),
        )
        self.assertEqual([r.member for r in out.replies], ["Ghoul"])
        wider = mates(
            ("Bigzug", 20, CAVE, NEAR, 1),
            ("Chill", 19, CAVE, (-250.0, -4150.0), 1),
            ("Dread", 21, CAVE, (-300.0, -4100.0), 1),
            ("Eld", 22, CAVE, (-290.0, -4120.0), 1),
        )
        again = classask.plan_pass(
            helps_of("Bigzug"),
            wider,
            {},
            [qask(1)],
            [yes(2, 1, "Dread", "dps", "help")],
            NOW,
            refused=this._class_board.refused(),
        )
        self.assertEqual([r.member for r in again.replies], ["Eld"])

    def test_a_leader_refusal_waits_and_writes_the_row_again(self):
        busy = answer(
            "error", "the leader is in combat", "refused", "refused: see result"
        )
        this = _Bridge([busy, FORMED, answer("applied", phase="ended")])
        drive(this, a_run())
        ups = [r for r in this.rows if r[2].startswith("party-up")]
        self.assertEqual(len(ups), 2)
        self.assertIn(classparty.LEADER_WAIT_SECONDS, this.slept)
        self.assertEqual(this.settled, [(1, True, False)])

    def test_failures_give_the_ask_up_and_cool_its_asker(self):
        busy = answer(
            "error", "the leader is in combat", "refused", "refused: see result"
        )
        this = _Bridge([busy] * 5)
        drive(this, a_run())
        ups = [r for r in this.rows if r[2].startswith("party-up")]
        self.assertEqual(len(ups), classparty.MAX_FAILURES)
        self.assertEqual(this.settled, [(1, False, True)])
        self.assertEqual(this._class_board.cooling(0.0), {"Bigzug"})
        self.assertEqual(this._class_board.names(), set())
        self.assertFalse([r for r in this.rows if r[2] == "party-disband"])

    def test_a_worldserver_before_the_verbs_keeps_todays_behaviour(self):
        old = answer("error", detail="malformed request: want take quest:<id>")
        this = _Bridge([old])
        drive(this, a_run())
        self.assertEqual([r[2] for r in this.rows], ["party-up Chill Dread"])
        self.assertFalse(this._class_board.seats(1.0))
        self.assertEqual(this._class_board.failures(1), 0)
        self.assertEqual(this.settled, [(1, False, False)])
        self.assertEqual(this._class_board.names(), set())

    def test_an_unanswered_row_is_followed_by_a_disband_so_no_party_is_orphaned(self):
        this = _Bridge([None, answer("unchanged", phase="none")])
        drive(this, a_run())
        self.assertEqual(
            [r[2] for r in this.rows], ["party-up Chill Dread", "party-disband"]
        )
        self.assertEqual(this._class_board.failures(1), 1)

    def test_a_walk_that_does_not_arrive_ends_and_disbands_the_party(self):
        lost = guildroute.WalkAnswer(guildroute.ENDED, "Bigzug cannot walk: no path")
        this = _Bridge([FORMED, answer("applied", phase="ended")], walk=lost)
        drive(this, a_run())
        self.assertEqual(
            [r[2] for r in this.rows],
            [
                "party-up Chill Dread",
                "party-walk creature:9 max:20000",
                "party-disband",
            ],
        )
        self.assertEqual(this.settled, [(1, True, False)])
        self.assertEqual(this._class_board.cooling(0.0), {"Bigzug"})

    def test_a_walk_the_old_worldserver_does_not_know_marks_it_unsupported(self):
        lost = guildroute.WalkAnswer(
            guildroute.ENDED, "Bigzug cannot walk to x: malformed request: y"
        )
        this = _Bridge([FORMED, answer("applied", phase="ended")], walk=lost)
        drive(this, a_run())
        self.assertFalse(this._class_board.seats(1.0))

    def test_an_ask_that_ran_out_disbands_the_party(self):
        this = _Bridge(
            [FORMED, answer("applied", phase="ended")],
            states=[classparty.INCOMPLETE],
            ask_live=False,
        )
        drive(this, a_run())
        self.assertEqual(this.rows[-1][2], "party-disband")
        self.assertEqual(this.settled, [(1, True, False)])
        self.assertEqual(this._class_board.cooling(0.0), {"Bigzug"})

    def test_a_party_that_is_out_of_time_is_disbanded(self):
        this = _Bridge(
            [FORMED, answer("applied", phase="ended")], states=[classparty.INCOMPLETE]
        )
        with mock.patch.object(classparty.PartyRun, "left", lambda self, now: -1.0):
            drive(this, a_run())
        self.assertEqual(this.rows[-1][2], "party-disband")

    def test_a_handed_in_quest_is_done(self):
        this = _Bridge(
            [FORMED, answer("applied", phase="ended")], states=[classparty.GONE]
        )
        drive(this, a_run())
        self.assertEqual(this._class_board.cooling(0.0), set())

    def test_a_failure_in_the_flow_still_frees_the_members(self):
        this = _Bridge([FORMED])

        def boom(name, quest):
            raise RuntimeError("database gone")

        drive(this, a_run(), _class_party_quest_state=boom)
        self.assertEqual(this._class_board.names(), set())
        self.assertEqual(this.rows[-1][2], "party-disband")

    def test_the_parties_are_begun_on_the_board_and_run_as_tasks(self):
        this = _Bridge([FORMED, answer("applied", phase="ended")])
        this._class_party_tasks = set()
        run = a_run()

        async def go():
            this._begin_class_parties([run])
            self.assertEqual(this._class_board.names(), {"Bigzug", "Chill", "Dread"})
            await asyncio.gather(*this._class_party_tasks)

        ids = iter(range(100, 200))
        stubs = dict(
            _insert_corps_row=lambda holder, row: next(ids),
            _class_party_quest_state=lambda n, q: classparty.COMPLETE,
            _class_party_ask_live=lambda i: True,
            _class_party_withdraw=lambda i: None,
            _class_party_settle=lambda r, f, g, done=False: None,
        )
        with mock.patch.multiple(bridge, **stubs):
            asyncio.run(go())
        self.assertEqual(this._class_board.names(), set())
        self.assertEqual(this._class_party_tasks, set())


LOST = guildroute.WalkAnswer(guildroute.ENDED, "cannot walk to Lizard: no path")


def cut_off():
    """A meeting clock short enough to cut off a walk that never ends. Patched on
    the classparty the bridge reads: importing the bridge under a patched
    sys.modules can leave the tests holding another copy of the module."""
    return mock.patch.object(bridge.classparty, "MEET_SECONDS", 0.05)


def at(yards, map_id=1):
    """A snapshot position `yards` east of THERE."""
    return (map_id, THERE[1] + yards, THERE[2])


class TheMeeting(unittest.TestCase):
    """classparty.judge_meeting: who met the leader at the objective."""

    def test_far_meeting_walk_gets_the_far_walk_follow_window(self):
        self.assertEqual(classparty.MEET_SECONDS, 2110.0)

    def judge(self, arrived, stands):
        return classparty.judge_meeting(a_run(meeting=True), arrived, stands)

    ALL = {"Bigzug", "Chill", "Dread"}

    def test_everyone_beside_the_leader_meets(self):
        got = self.judge(self.ALL, {"Bigzug": THERE, "Chill": at(40), "Dread": at(89)})
        self.assertEqual((got.met, got.lost, got.unseen), (True, (), ()))

    def test_a_helper_beyond_seating_range_or_on_another_map_is_lost(self):
        got = self.judge(
            self.ALL, {"Bigzug": THERE, "Chill": at(120), "Dread": at(0, map_id=0)}
        )
        self.assertFalse(got.met)
        self.assertEqual(got.lost, ("Chill", "Dread"))
        self.assertIn("no helper met Bigzug", got.why)

    def test_a_helper_whose_walk_did_not_arrive_is_lost_wherever_it_stands(self):
        got = self.judge({"Bigzug", "Dread"}, {n: THERE for n in self.ALL})
        self.assertEqual((got.met, got.lost, got.unseen), (True, ("Chill",), ()))

    def test_a_helper_the_snapshot_does_not_show_is_unseen(self):
        got = self.judge(self.ALL, {"Bigzug": THERE, "Dread": THERE})
        self.assertEqual(
            (got.met, got.lost, got.unseen), (True, ("Chill",), ("Chill",))
        )

    def test_a_leader_that_did_not_arrive_fails_the_meeting_and_bars_nobody_more(self):
        got = self.judge({"Chill", "Dread"}, {n: THERE for n in self.ALL})
        self.assertEqual((got.met, got.lost), (False, ()))
        self.assertIn("Bigzug did not reach Lizard", got.why)

    def test_a_leader_the_snapshot_does_not_show_fails_the_meeting(self):
        got = self.judge(self.ALL, {"Chill": THERE, "Dread": THERE})
        self.assertEqual((got.met, got.lost, got.unseen), (False, (), ("Bigzug",)))

    def test_the_walk_and_the_line(self):
        self.assertEqual(
            classparty.meet_command(SPOT, 20000.0), "walk-to-spawn creature:9 max:20000"
        )
        self.assertEqual(
            classparty.meet_command(SPOT, guildroute.TRAINER_WALK_YARDS),
            "walk-to-spawn creature:9",
        )
        self.assertEqual(
            classparty.meet_line(a_run()),
            "class party: Chill, Dread meet Bigzug at Lizard for Group Job",
        )

    def test_a_planned_party_starts_by_meeting(self):
        self.assertTrue(classparty.PartyRun(1, "B", ("C",), 2000, "x", SPOT).meeting)
        run = a_run(meeting=True)
        run.drop(("Chill",))
        run.met()
        self.assertEqual((run.helpers, run.answers), (("Dread",), {"Dread": 12}))
        self.assertFalse(run.meeting)


def meet_rows(this, names):
    """The meeting walks `this` wrote, by name (they are written at once)."""
    meet = classparty.meet_command(SPOT, 20000.0)
    got = sorted(r[:3] for r in this.rows if r[2].startswith(classparty.MEET))
    return got == sorted((n, "job", meet) for n in names)


class TheBridgeMeetsAtTheObjective(unittest.TestCase):
    def test_far_helpers_meet_at_the_objective_before_party_up(self):
        across = mates(
            ("Bigzug", 20, CAVE, NEAR, 1),
            ("Far", 20, CAVE, (NEAR[0] + 800.0, NEAR[1]), 1),
        )
        one = qask(1, roles_needed="dps")
        asked = classask.plan_pass(helps_of("Bigzug"), across, {}, [one], [], NOW)
        self.assertEqual([r.member for r in asked.replies], ["Far"])
        answers = [yes(5, 1, "Far", "dps", "help")]
        quest_pass = classask.plan_pass(
            helps_of("Bigzug"), across, {}, [one], answers, NOW
        )
        (run,) = classparty.plan_starts(
            [one],
            answers,
            quest_pass,
            helps_of("Bigzug"),
            free_of(across),
            classparty.Board(),
            NOW,
            0.0,
        )
        self.assertTrue(run.meeting)
        walking = {"Bigzug": THERE, "Far": at(800)}
        beside = {"Bigzug": THERE, "Far": at(40)}
        this = _Bridge(
            [FORMED, answer("applied", phase="ended")], stands=[walking, beside]
        )
        drive(this, run)
        meet = classparty.meet_command(run.spot, 20000.0)
        self.assertEqual(
            sorted(r[:3] for r in this.rows[:2]),
            [("Bigzug", "job", meet), ("Far", "job", meet)],
        )
        self.assertEqual(
            [r[2] for r in this.rows[2:]],
            [
                "party-up Far",
                classparty.walk_command(run.spot, 20000.0),
                "party-disband",
            ],
        )
        # Two reads of the snapshot, both after the walks and before party-up.
        self.assertEqual(this.stand_reads, [2, 2])
        self.assertIn(classparty.MEET_READ_SECONDS, this.slept)
        self.assertEqual(this.withdrawn, [])
        self.assertEqual(this.settled, [(1, True, False)])

    def test_no_party_up_while_a_helper_never_stands_beside_the_leader(self):
        this = _Bridge(
            [FORMED], stands=[{"Bigzug": THERE, "Chill": at(800), "Dread": at(500)}]
        )
        drive(this, a_run(meeting=True))
        self.assertTrue(meet_rows(this, ("Bigzug", "Chill", "Dread")))
        self.assertFalse([r for r in this.rows if r[2].startswith("party-")])
        self.assertEqual(len(this.stand_reads), classparty.MEET_READS)
        self.assertEqual(sorted(this.withdrawn), [11, 12])
        self.assertEqual(this._class_board.failures(1), 1)
        self.assertEqual(this.settled, [(1, False, False)])

    def test_a_helper_whose_walk_fails_is_withdrawn_and_barred(self):
        this = _Bridge([FORMED, answer("applied", phase="ended")], meet={"Chill": LOST})
        run = a_run(meeting=True)
        drive(this, run)
        self.assertTrue(meet_rows(this, ("Bigzug", "Chill", "Dread")))
        self.assertEqual(
            [r[2] for r in this.rows[3:]],
            ["party-up Dread", "party-walk creature:9 max:20000", "party-disband"],
        )
        self.assertEqual(this.withdrawn, [11])
        self.assertEqual(this._class_board.refused(), {1: frozenset({"Chill"})})
        self.assertEqual((run.helpers, run.answers), (("Dread",), {"Dread": 12}))
        self.assertEqual(this._class_board.failures(1), 0)
        self.assertEqual(this.settled, [(1, True, False)])
        again = classask.plan_pass(
            helps_of("Bigzug"),
            friends(),
            {},
            [qask(1)],
            [yes(12, 1, "Dread", "dps", "help")],
            NOW,
            refused=this._class_board.refused(),
        )
        self.assertNotIn("Chill", [r.member for r in again.replies])

    def test_a_helper_the_clock_cuts_off_is_withdrawn_like_one_whose_walk_failed(self):
        this = _Bridge([FORMED, answer("applied", phase="ended")], meet={"Dread": HANG})
        with cut_off():
            drive(this, a_run(meeting=True))
        self.assertEqual(this.withdrawn, [12])
        self.assertEqual(this._class_board.refused(), {1: frozenset({"Dread"})})
        self.assertIn("party-up Chill", [r[2] for r in this.rows])

    def test_a_leader_that_does_not_arrive_fails_the_meeting(self):
        for how in (LOST, HANG):
            with self.subTest(how=how):
                this = _Bridge([FORMED], meet={"Bigzug": how})
                with cut_off():
                    drive(this, a_run(meeting=True))
                self.assertTrue(meet_rows(this, ("Bigzug", "Chill", "Dread")))
                self.assertFalse([r for r in this.rows if r[2].startswith("party-")])
                self.assertEqual(this.stand_reads, [])
                self.assertEqual(this.withdrawn, [])
                self.assertEqual(this._class_board.refused(), {})
                self.assertEqual(this._class_board.failures(1), 1)
                self.assertEqual(this._class_board.cooling(0.0), set())
                self.assertEqual(this.settled, [(1, False, False)])

    def test_every_helper_lost_fails_the_meeting(self):
        this = _Bridge([FORMED], meet={"Chill": LOST, "Dread": LOST})
        drive(this, a_run(meeting=True))
        self.assertFalse([r for r in this.rows if r[2].startswith("party-")])
        self.assertEqual(sorted(this.withdrawn), [11, 12])
        self.assertEqual(this._class_board.failures(1), 1)

    def test_a_meeting_walk_that_raises_loses_only_its_member(self):
        this = _Bridge([FORMED, answer("applied", phase="ended")])
        ids = iter(range(100, 200))

        def insert(holder, row):
            if holder == "Chill":
                raise RuntimeError("database gone")
            row_id = next(ids)
            this.rows.append((holder, row.kind, row.command, row.source))
            this.commands[row_id] = row.command
            return row_id

        with self.assertLogs(bridge.log, "ERROR"):
            drive(this, a_run(meeting=True), _insert_corps_row=insert)
        self.assertEqual(this.withdrawn, [11])
        self.assertIn("party-up Dread", [r[2] for r in this.rows])

    def test_a_meeting_walk_the_old_worldserver_does_not_know_marks_it_unsupported(
        self,
    ):
        old = guildroute.WalkAnswer(guildroute.ENDED, "x: malformed request: y")
        this = _Bridge([FORMED], meet={"Bigzug": old})
        drive(this, a_run(meeting=True))
        self.assertFalse(this._class_board.seats(1.0))

    def test_answerers_are_held_only_while_travelling_or_in_the_party(self):
        this = _Bridge([FORMED, answer("applied", phase="ended")], meet={"Chill": LOST})
        drive(this, a_run(meeting=True))
        everyone = {"Bigzug", "Chill", "Dread"}
        self.assertEqual(this.held_meeting, [everyone] * 3)
        # Chill's meeting failed: it is free while the party goes on without it.
        self.assertEqual(this.held_up, [{"Bigzug", "Dread"}])
        self.assertEqual(bridge._class_party_names(this), set())
        self.assertEqual(this._guild_busy_run_names(), set())

        failed = _Bridge([FORMED], meet={"Bigzug": LOST})
        drive(failed, a_run(meeting=True))
        self.assertEqual(failed.held_meeting, [everyone] * 3)
        self.assertEqual(failed.held_up, [])
        self.assertEqual(classask.held_names(failed._class_board.runs()), set())
        self.assertEqual(failed._guild_busy_run_names(), set())

    def test_class_party_on_board_is_busy_for_guild_jobs(self):
        this = _Bridge([FORMED, answer("applied", phase="ended")])
        run = a_run(meeting=True)
        this._class_board.begin(run)
        self.assertEqual(
            this._guild_busy_run_names(), {"Bigzug", "Chill", "Dread"}
        )


class TheWiring(unittest.TestCase):
    def test_the_image_carries_the_module(self):
        dockerfile = (
            __import__("pathlib").Path(__file__).resolve().parents[1] / "Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertIn("classparty.py", dockerfile)

    def test_the_rows_are_written_as_the_modules_kinds(self):
        source = (
            __import__("pathlib").Path(__file__).resolve().parents[1] / "bridge.py"
        ).read_text(encoding="utf-8")
        self.assertIn('guildcorps.Row("guild", classparty.up_command', source)
        self.assertIn('guildcorps.Row("job", classparty.walk_command', source)
        self.assertIn('guildcorps.Row("guild", classparty.DISBAND', source)
        self.assertIn('guildcorps.Row("job", classparty.meet_command', source)
        self.assertIn("asyncio.to_thread(_class_party_stands", source)

    def test_the_old_twenty_minute_hold_is_gone(self):
        self.assertFalse(hasattr(bridge, "_quest_ask_holders"))
        self.assertEqual(gs.ASK_MINUTES + gs.FILLED_GRACE_MINUTES, 20)


if __name__ == "__main__":
    unittest.main()
