"""A class quest hunt kills and loots its objective (classhunt.py).

Until quadseven/mod-overseer#869 a class quest hunt ended at `walk-to-spawn
creature:<spawn id>` and the bot's own grind was supposed to kill and loot: no
tank warrior ever produced a quest drop. `hunt-spawn creature:<entry>` makes the
arrived bot do it. The quest, creature and spawn ids below are the dev realm's
level-10 warrior line (quest 1498: 5 Singed Scale from Thunder Lizard 3130 and
Lightning Hide 3131 in the Barrens), read 2026-10-06.
"""

import ast
import asyncio
import json
import pathlib
import unittest
from unittest import mock

import classhunt
import classquest
import guildjobs
import guildroute
from test_classquest import HIDE, KALIMDOR, LIZARD, class_plan, class_steps, qrow, who
from test_classquest import book as warrior_book
from test_classquest_far_walk import FAR
from test_guildsocial_bridge import bridge


def bridge_text():
    return pathlib.Path(bridge.__file__).read_text(encoding="utf-8")


HUNTING = dict(quest_log={1498: 3}, quests_done=frozenset({1505}))
# Beside the Thunder Lizard spawn (705, -4112): inside the module's reach.
BESIDE = dict(x=706.0, y=-4111.0)
# A few hundred yards off the pack: hunting, but not yet in reach.
NEARBY = dict(x=720.0, y=-4300.0)


def hunters(slots, hunts=None):
    hunts = hunts or classquest.Hunts()
    hunts.slots = slots
    return hunts


def hunt_rows(step):
    return [r for r in step.rows if classhunt.is_hunt_row(r.command)]


class TheRow(unittest.TestCase):
    def test_an_item_objective_names_the_item_and_how_many_are_missing(self):
        quest = warrior_book().quests[1498]
        self.assertEqual(
            classhunt.command(quest, 3130),
            "hunt-spawn creature:3130 item:6486 count:5 max:%d" % classhunt.MAX_SECONDS,
        )
        held = {6486: 2}.get
        self.assertEqual(
            classhunt.command(quest, 3130, lambda i: held(i, 0)),
            "hunt-spawn creature:3130 item:6486 count:3 max:%d" % classhunt.MAX_SECONDS,
        )
        self.assertLessEqual(classhunt.MAX_SECONDS, 600)

    def test_a_count_already_held_still_asks_for_one(self):
        quest = warrior_book().quests[1498]
        self.assertIn("count:1 ", classhunt.command(quest, 3130, lambda i: 9))

    def test_an_older_worldserver_gets_the_row_with_no_item_key(self):
        quest = warrior_book().quests[1498]
        self.assertEqual(
            classhunt.command(quest, 3130, None, item_form=False),
            "hunt-spawn creature:3130 max:%d" % classhunt.MAX_SECONDS,
        )
        row = classhunt.command(quest, 3130)
        self.assertEqual(
            classhunt.plain_form(row),
            "hunt-spawn creature:3130 max:%d" % classhunt.MAX_SECONDS,
        )

    def test_a_single_item_quest_from_one_creature(self):
        rows = [qrow(1678, "Vejrek", sort=-81, classes=1, item1=6799, item_count1=1)]
        b = classquest.build(
            rows,
            [],
            [{"guid": 5, "entry": 6113, "map_id": 1, "x": 1.0, "y": 2.0}],
            [{"item": 6799, "entry": 6113}],
        )
        self.assertEqual(
            classhunt.command(b.quests[1678], 6113),
            "hunt-spawn creature:6113 item:6799 count:1 max:%d" % classhunt.MAX_SECONDS,
        )

    def test_a_kill_objective_asks_for_its_own_kill_count(self):
        quest = warrior_book().quests[1819]
        self.assertEqual(
            classhunt.command(quest, 6390),
            "hunt-spawn creature:6390 count:1 max:%d" % classhunt.MAX_SECONDS,
        )

    def test_the_count_is_held_to_the_modules_ceiling(self):
        rows = [qrow(7, "Cull", npc1=99, npc_count1=500)]
        quest = classquest.build(rows, [], [], []).quests[7]
        self.assertIn("count:%d " % classhunt.MAX_COUNT, classhunt.command(quest, 99))

    def test_no_entry_is_no_row(self):
        quest = warrior_book().quests[1498]
        self.assertEqual(classhunt.command(quest, 0), "")

    def test_only_the_hunt_verb_is_a_hunt_row(self):
        self.assertTrue(classhunt.is_hunt_row("hunt-spawn creature:3130"))
        self.assertFalse(classhunt.is_hunt_row("walk-to-spawn creature:4788"))
        self.assertFalse(classhunt.is_hunt_row(None))


class TheCounters(unittest.TestCase):
    def test_the_quest_is_done_when_the_core_says_complete(self):
        quest = warrior_book().quests[1498]
        self.assertTrue(classhunt.finished(quest, classquest.STATUS_COMPLETE, 0))

    def test_or_when_the_counters_reach_what_it_requires(self):
        quest = warrior_book().quests[1498]
        need = classhunt.wanted(quest)
        self.assertEqual(need, 5)
        self.assertFalse(classhunt.finished(quest, classquest.STATUS_INCOMPLETE, 4))
        self.assertTrue(classhunt.finished(quest, classquest.STATUS_INCOMPLETE, 5))

    def test_an_item_objective_is_done_when_the_bags_hold_the_items(self):
        quest = warrior_book().quests[1498]
        self.assertFalse(classhunt.finished(quest, 3, 0, {6486: 4}))
        self.assertTrue(classhunt.finished(quest, 3, 0, {6486: 5}))

    def test_an_unreadable_counter_is_not_done(self):
        quest = warrior_book().quests[1498]
        self.assertFalse(classhunt.finished(quest, None, None))


def answer(status, detail="", **body):
    return status, detail, json.dumps(body)


class TheAnswer(unittest.TestCase):
    def judge(self, *row):
        return classhunt.judge("Bigzug", *row)

    def test_a_row_still_open_is_running(self):
        for status in ("pending", "claimed", "verifying"):
            self.assertEqual(self.judge(status, "", "{}").state, classhunt.RUNNING)

    def test_done_or_a_timeout_with_kills_is_applied(self):
        got = self.judge(*answer("applied", outcome="done", kills=5, loot_count=5))
        self.assertEqual(got.state, classhunt.DONE)
        self.assertIn("5 kill(s), 5 looted", got.said)

    def test_a_timeout_with_no_kill_changed_nothing(self):
        self.assertEqual(
            self.judge(*answer("unchanged", outcome="timeout")).state,
            classhunt.NOTHING,
        )

    def test_a_refusal_follows_its_retry_word(self):
        for word, state in (
            ("later", classhunt.LATER),
            ("elsewhere", classhunt.ELSEWHERE),
            ("never", classhunt.NEVER),
        ):
            got = self.judge(
                *answer("error", "refused", outcome="refused", reason="x", retry=word)
            )
            self.assertEqual(got.state, state)

    def test_a_refusal_with_no_word_is_asked_again_later(self):
        got = self.judge(*answer("error", "refused", outcome="refused"))
        self.assertEqual(
            (got.state, got.wait), (classhunt.LATER, classhunt.LATER_WAIT_SECONDS)
        )

    def test_a_character_that_left_the_world_is_unreadable(self):
        got = self.judge(*answer("error", "gone", outcome="unreadable"))
        self.assertEqual(got.state, classhunt.UNREADABLE)

    def test_an_older_worldserver_is_unsupported_not_never(self):
        for detail in (
            "unknown job mode 'hunt-spawn'",
            "malformed request: want take quest:<id> or turnin quest:<id>",
        ):
            self.assertEqual(
                self.judge("error", detail, "{}").state, classhunt.UNSUPPORTED
            )

    def test_a_hunt_switched_off_is_unsupported_and_never_gives_the_quest_up(self):
        got = self.judge(
            *answer(
                "error",
                classhunt.DISABLED,
                outcome="refused",
                reason=classhunt.DISABLED,
                retry="never",
            )
        )
        self.assertEqual(got.state, classhunt.UNSUPPORTED)

    def test_the_slots_are_the_ceiling_less_the_rows_open(self):
        self.assertEqual(classhunt.free_slots(1, 4), 3)
        self.assertEqual(classhunt.free_slots(9, 4), 0)
        self.assertIsNone(classhunt.free_slots(None, 4))


class ThePlan(unittest.TestCase):
    def test_an_arrived_member_hunts_the_creature_at_its_pack(self):
        m = who(**HUNTING, **BESIDE)
        (step,) = class_steps(class_plan([m], hunts=hunters(classhunt.Slots(2))))
        (row,) = hunt_rows(step)
        self.assertEqual(row.kind, "job")
        self.assertTrue(row.command.startswith("hunt-spawn creature:3130 "))
        self.assertIsNone(step.walk)
        self.assertEqual(step.key, 1498)
        self.assertEqual(step.spot.spawn, 4788)
        self.assertTrue(row.source.endswith("classquest:Bigzug"))

    def test_the_row_names_the_item_and_what_the_bags_still_lack(self):
        have = (guildjobs.Carried(1, 6486, 2),)
        m = who(**HUNTING, **BESIDE, carried=have)
        (step,) = class_steps(class_plan([m], hunts=hunters(classhunt.Slots(2))))
        self.assertTrue(
            step.rows[0].command.startswith(
                "hunt-spawn creature:3130 item:6486 count:3 "
            )
        )

    def test_a_world_that_rejects_the_item_key_is_given_the_plain_row(self):
        hunts = hunters(classhunt.Slots(2))
        hunts.items = False
        m = who(**HUNTING, **BESIDE)
        (step,) = class_steps(class_plan([m], hunts=hunts))
        self.assertNotIn("item:", step.rows[0].command)

    def test_the_dropped_items_are_read_from_the_bags(self):
        self.assertIn(6486, warrior_book().watch_items())

    def test_a_target_that_does_not_respawn_leaves_the_member_alone_15_minutes(self):
        body = {"outcome": "timeout", "reason": classquest.NO_RESPAWN_REASON}
        row = {
            "target_name": "Bigzug",
            "source": "guildjobs:classquest:Bigzug",
            "status": "unchanged",
            "age": 2,
            "result": json.dumps(body, separators=(",", ":")),
        }
        recent = guildjobs.recent_from_rows([row])
        self.assertEqual(
            guildjobs.class_walk_backoff("Bigzug", recent),
            classquest.NO_RESPAWN_BACKOFF_MINUTES - 2,
        )
        self.assertGreater(classquest.NO_RESPAWN_BACKOFF_MINUTES, 10)

    def test_a_member_off_the_pack_walks_to_it_first(self):
        m = who(**HUNTING, **NEARBY)
        (step,) = class_steps(class_plan([m], hunts=hunters(classhunt.Slots(2))))
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:4788"))
        self.assertEqual(len(hunt_rows(step)), 1)

    def test_a_far_member_walks_then_hunts_in_one_step(self):
        m = who("Far", **FAR, **HUNTING)
        (step,) = class_steps(class_plan([m], hunts=hunters(classhunt.Slots(2))))
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:12197"))
        (row,) = hunt_rows(step)
        self.assertTrue(row.command.startswith("hunt-spawn creature:3131 "))

    def test_with_no_slots_set_the_hunt_is_the_walk_alone(self):
        for hunts in (None, classquest.Hunts()):
            m = who("Far", **FAR, **HUNTING)
            (step,) = class_steps(class_plan([m], hunts=hunts))
            self.assertEqual(hunt_rows(step), [])
            self.assertTrue(
                step.rows[0].command.startswith("walk-to-spawn creature:12197")
            )

    def test_a_member_at_its_pack_with_no_hunt_slot_left_waits(self):
        m = who(**HUNTING, **BESIDE)
        result = class_plan([m], hunts=hunters(classhunt.Slots(0)))
        self.assertEqual(class_steps(result), [])
        self.assertTrue(any("hunt slot" in n for n in result.notes))
        self.assertIn(classquest.MARK, result.lines["Bigzug"])

    def test_a_member_off_the_pack_with_no_hunt_slot_still_walks(self):
        m = who("Far", **FAR, **HUNTING)
        (step,) = class_steps(class_plan([m], hunts=hunters(classhunt.Slots(0))))
        self.assertEqual(hunt_rows(step), [])

    def test_the_plan_writes_no_more_hunts_than_the_slots_and_tanks_go_first(self):
        members = [
            who("Hitter", level=30, tree="Arms", **HUNTING, **BESIDE),
            who("Tank", level=12, tree="Protection", **HUNTING, **BESIDE),
            who("Slasher", level=25, tree="Fury", **HUNTING, **BESIDE),
        ]
        result = class_plan(members, hunts=hunters(classhunt.Slots(1)))
        self.assertEqual(
            [s.holder for s in class_steps(result) if hunt_rows(s)], ["Tank"]
        )

    def test_an_unread_count_holds_nothing_back(self):
        members = [who(n, **HUNTING, **BESIDE) for n in ("Aa", "Bb", "Cc")]
        result = class_plan(members, hunts=hunters(classhunt.Slots(None)))
        self.assertEqual(len([s for s in class_steps(result) if hunt_rows(s)]), 3)

    def test_a_step_the_plan_then_refuses_gives_its_hunt_slot_back(self):
        members = [
            who("Aa", level=20, **HUNTING, **BESIDE),
            who("Bb", level=19, **HUNTING, **BESIDE),
        ]
        result = class_plan(members, hunts=hunters(classhunt.Slots(1)), busy={"Aa"})
        self.assertEqual([s.holder for s in class_steps(result)], ["Bb"])
        self.assertEqual(len(hunt_rows(class_steps(result)[0])), 1)

    def test_a_hunt_just_written_is_not_asked_again_at_once(self):
        m = who(**HUNTING, **BESIDE)
        recent = (guildjobs.Recent("Bigzug", classquest.ACTION, 3),)
        result = class_plan([m], recent=recent, hunts=hunters(classhunt.Slots(2)))
        self.assertEqual(class_steps(result), [])

    def test_a_finished_objective_is_handed_in_not_hunted(self):
        m = who(quest_log={1498: 1}, quests_done=frozenset({1505}), **BESIDE)
        (step,) = class_steps(class_plan([m], hunts=hunters(classhunt.Slots(2))))
        self.assertEqual(hunt_rows(step), [])
        self.assertEqual(step.rows[0].command, "turnin quest:1498")


# --- the bridge follows the row ----------------------------------------------------


class _Bridge:
    """The Bridge methods that follow a hunt, with the reads and writes stubbed."""

    def __init__(self, answers, states=()):
        self._class_book = warrior_book()
        self._class_hunts = classquest.Hunts()
        self._class_hunt_unsupported_until = 0.0
        self.rows, self.ended, self.slept = [], [], []
        self.answers = list(answers)
        self.states = list(states) or [INCOMPLETE]


for _name in ("_class_hunt_row", "_follow_class_hunt", "_slow_respawn", "_hunt_left"):
    setattr(_Bridge, _name, getattr(bridge.Bridge, _name))

STEP = guildjobs.guildcorps.Step(
    "Bigzug",
    classquest.ACTION,
    1498,
    "hunts",
    rows=(),
    spot=guildjobs.Spot("creature", 4788, KALIMDOR, 705.0, -4112.0, "Lizard"),
)
ROW = guildjobs.guildcorps.Row(
    "job", "hunt-spawn creature:3130 max:480", "", "guildjobs:classquest:Bigzug"
)
RUNNING = ("verifying", "", "{}")
INCOMPLETE = (classquest.STATUS_INCOMPLETE, 2, {})
COMPLETE = (classquest.STATUS_COMPLETE, 5, {})


def run(this):
    ids = iter(range(100, 200))

    def insert(holder, row):
        this.rows.append((holder, row.command))
        return next(ids)

    def read(row_id):
        got = this.answers.pop(0) if len(this.answers) > 1 else this.answers[0]
        return (
            None
            if got is None
            else dict(zip(("status", "detail", "result"), got, strict=True))
        )

    def state(name, quest, items=()):
        return this.states.pop(0) if len(this.states) > 1 else this.states[0]

    async def nap(seconds):
        this.slept.append(seconds)

    stubs = dict(
        _insert_corps_row=insert,
        _command_answer=read,
        _class_hunt_state=state,
        _end_hunt_row=this.ended.append,
    )
    with (
        mock.patch.multiple(bridge, **stubs),
        mock.patch.object(bridge.asyncio, "sleep", nap),
    ):
        return asyncio.run(this._class_hunt_row(STEP, ROW))


def refused(word, reason="no living creature of the entry within reach"):
    return answer("error", "refused", outcome="refused", reason=reason, retry=word)


class TheBridgeFollowsTheHunt(unittest.TestCase):
    def test_the_row_is_ended_the_poll_the_counters_say_the_quest_is_done(self):
        this = _Bridge([RUNNING], states=[INCOMPLETE, INCOMPLETE, COMPLETE])
        self.assertTrue(run(this))
        self.assertEqual(this.rows, [("Bigzug", ROW.command)])
        self.assertEqual(this.ended, [100])
        self.assertEqual(this.slept, [classhunt.POLL_SECONDS] * 3)

    def test_a_row_that_ends_itself_is_not_ended_again(self):
        this = _Bridge(
            [RUNNING, answer("applied", outcome="done", kills=5)],
            states=[INCOMPLETE],
        )
        self.assertFalse(run(this))
        self.assertEqual(this.ended, [])
        self.assertEqual(len(this.rows), 1)

    def test_a_later_refusal_waits_and_asks_again_a_bounded_number_of_times(self):
        this = _Bridge([refused("later")], states=[INCOMPLETE])
        # Three spawns: not a creature to wait out the respawn of.
        this._class_book = warrior_book(
            spawn_rows=[LIZARD, dict(LIZARD, guid=1), dict(LIZARD, guid=2), HIDE]
        )
        self.assertFalse(run(this))
        self.assertEqual(len(this.rows), classhunt.MAX_ATTEMPTS)
        self.assertEqual(
            [s for s in this.slept if s == classhunt.LATER_WAIT_SECONDS],
            [classhunt.LATER_WAIT_SECONDS] * (classhunt.MAX_ATTEMPTS - 1),
        )

    def test_an_elsewhere_refusal_leaves_the_pack_for_the_next_one(self):
        this = _Bridge([refused("elsewhere")], states=[INCOMPLETE])
        self.assertFalse(run(this))
        self.assertEqual(len(this.rows), 1)
        hunt = this._class_hunts.get("Bigzug")
        self.assertEqual(hunt.tried, ((KALIMDOR, 705.0, -4112.0),))
        avoid, _off = this._class_hunts.state("Bigzug", 0.0)
        self.assertEqual(avoid[1498], hunt.tried)

    def test_a_never_refusal_gives_the_quest_up_for_the_cooldown(self):
        this = _Bridge([refused("never", "the character is not a bot")])
        self.assertFalse(run(this))
        self.assertEqual(len(this.rows), 1)
        _avoid, off = this._class_hunts.state("Bigzug", 1.0)
        self.assertEqual(off, frozenset({1498}))

    def test_an_older_worldserver_is_not_hammered_and_the_quest_is_not_given_up(self):
        for detail in ("unknown job mode", classhunt.DISABLED):
            this = _Bridge([("error", detail, "{}")])
            before = bridge.time.monotonic()
            self.assertFalse(run(this))
            self.assertEqual(len(this.rows), 1)
            self.assertGreaterEqual(
                this._class_hunt_unsupported_until,
                before + guildroute.WALK_UNSUPPORTED_SECONDS,
            )
            self.assertIsNone(this._class_hunts.get("Bigzug"))

    def test_the_item_key_an_older_worldserver_rejects_is_asked_again_plain(self):
        bad = answer(
            "error",
            classhunt.MALFORMED,
            outcome="refused",
            reason=classhunt.MALFORMED,
            retry="never",
        )
        this = _Bridge([bad, answer("applied", outcome="done")], states=[INCOMPLETE])
        item_row = guildjobs.guildcorps.Row(
            "job", "hunt-spawn creature:3130 item:6486 count:5 max:480", "", "s"
        )
        global ROW
        before, ROW = ROW, item_row
        try:
            run(this)
        finally:
            ROW = before
        self.assertEqual(
            [r[1] for r in this.rows][:2],
            [item_row.command, "hunt-spawn creature:3130 max:480"],
        )
        self.assertGreater(this._class_hunt_itemless_until, 0.0)
        self.assertIsNone(this._class_hunts.get("Bigzug"))

    def test_nothing_respawning_is_left_alone_not_waited_out_in_the_step(self):
        gone = answer(
            "unchanged",
            "timeout",
            outcome="timeout",
            reason=classquest.NO_RESPAWN_REASON,
            retry="later",
        )
        this = _Bridge([gone])
        self.assertFalse(run(this))
        self.assertEqual(len(this.rows), 1)
        self.assertEqual(this.slept, [classhunt.POLL_SECONDS])

    def test_a_row_that_cannot_be_read_ends_the_follow(self):
        this = _Bridge([None])
        self.assertFalse(run(this))
        self.assertEqual(len(this.rows), 1)


SLOW = dict(LIZARD, respawn=498)
NO_LIVING = classquest.NO_LIVING_REASON


def resting(age, entry=3130, **over):
    return guildjobs.Recent(
        "Bigzug",
        classquest.ACTION,
        age,
        status="error",
        refusal=NO_LIVING,
        retryable=True,
        row_id=700000,
        entry=entry,
        **over,
    )


class TheSlowRespawn(unittest.TestCase):
    """Vejrek (quest 1678, creature 6113): one spawn, respawn 498 seconds. Durg
    killed him; Gronk and Hurk were refused `no living creature` every 75 s."""

    def test_the_wait_is_the_respawn_time_within_five_and_thirty_minutes(self):
        def wait(seconds, spawns=1):
            rows = [dict(LIZARD, guid=g, respawn=seconds) for g in range(spawns)]
            return classquest.slow_respawns(warrior_book(spawn_rows=rows)).get(3130)

        self.assertEqual(wait(498), 9)
        self.assertEqual(wait(60), classquest.RESPAWN_MIN_MINUTES)
        self.assertEqual(wait(0), classquest.RESPAWN_MIN_MINUTES)
        self.assertEqual(wait(7200), classquest.RESPAWN_CAP_MINUTES)
        self.assertEqual(wait(498, spawns=2), 9)
        self.assertIsNone(wait(498, spawns=3))

    def test_the_spawn_query_reads_the_respawn_time(self):
        self.assertIn("spawntimesecs AS respawn", classquest.SPAWNS_SQL)

    def test_the_refusal_is_a_resting_answer_with_no_failure_in_it(self):
        verdict = classhunt.judge("Bigzug", "error", "refused", refused("later")[2])
        self.assertEqual(verdict.state, classhunt.RESTING)
        self.assertEqual(classhunt.entry_of(ROW.command), 3130)

    def test_a_bot_at_a_dead_single_spawn_asks_once_and_waits_in_the_plan(self):
        this = _Bridge([refused("later")], states=[INCOMPLETE])
        this._class_book = warrior_book(spawn_rows=[SLOW, HIDE])
        self.assertFalse(run(this))
        self.assertEqual(len(this.rows), 1)
        self.assertEqual(this.slept, [classhunt.POLL_SECONDS])

    def test_the_member_writes_no_row_and_no_walk_during_the_wait(self):
        hunts = hunters(classhunt.Slots(2))
        b = warrior_book(spawn_rows=[SLOW], loot_rows=[{"item": 6486, "entry": 3130}])
        for pos in (BESIDE, NEARBY):
            m = who(**HUNTING, **pos)
            result = class_plan([m], b, recent=(resting(2),), hunts=hunts)
            self.assertEqual(class_steps(result), [])
            self.assertTrue(any("to respawn" in n for n in result.notes), result.notes)

    def test_the_wait_ends_with_the_respawn_time(self):
        hunts = hunters(classhunt.Slots(2))
        b = warrior_book(spawn_rows=[SLOW], loot_rows=[{"item": 6486, "entry": 3130}])
        m = who(**HUNTING, **BESIDE)
        result = class_plan([m], b, recent=(resting(11),), hunts=hunts)
        (step,) = class_steps(result)
        self.assertEqual(len(hunt_rows(step)), 1)

    def test_a_creature_with_many_spawns_is_not_waited_on(self):
        rows = [dict(LIZARD, guid=g, respawn=498) for g in (1, 2, 3)]
        b = warrior_book(spawn_rows=rows, loot_rows=[{"item": 6486, "entry": 3130}])
        m = who(**HUNTING, **BESIDE)
        result = class_plan(
            [m], b, recent=(resting(0),), hunts=hunters(classhunt.Slots(2))
        )
        self.assertEqual(guildjobs.resting_entries("Bigzug", (resting(0),), b), {})
        self.assertFalse(any("to respawn" in n for n in result.notes))

    def test_the_wait_does_not_run_the_hunt_clock(self):
        hunts = hunters(classhunt.Slots(2))
        b = warrior_book(spawn_rows=[SLOW], loot_rows=[{"item": 6486, "entry": 3130}])
        m = who(**HUNTING, **BESIDE)
        hunts.observe(
            "Bigzug", 1498, 3, guildjobs.Spot("creature", 4788, 1, 705.0, -4112.0), 0.0
        )
        late = classquest.HUNT_STALL_MINUTES * 60 + 5.0
        class_plan([m], b, recent=(resting(2),), hunts=hunts, now=late)
        self.assertEqual(hunts.get("Bigzug").since, late)
        self.assertEqual(hunts.get("Bigzug").tried, ())
        self.assertFalse(guildjobs.failed_class_walks("Bigzug", (resting(2),) * 3))

    def test_another_dropper_is_walked_to_at_once(self):
        hunts = hunters(classhunt.Slots(2))
        b = warrior_book(spawn_rows=[SLOW, HIDE])
        m = who(**HUNTING, **BESIDE)
        result = class_plan([m], b, recent=(resting(2),), hunts=hunts)
        (step,) = class_steps(result)
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:12197"))
        self.assertTrue(
            hunt_rows(step)[0].command.startswith("hunt-spawn creature:3131 ")
        )


class TheBridgeWiring(unittest.TestCase):
    def test_no_hunt_helper_is_shadowed_by_a_later_def_of_the_same_name(self):
        tree = ast.parse(pathlib.Path(bridge.__file__).read_text(encoding="utf-8"))
        names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        for name in ("_class_hunt_state", "_end_hunt_row", "_hunts_open"):
            self.assertEqual(names.count(name), 1, name)
        self.assertNotIn("_class_quest_state(step.holder", bridge_text())

    def test_the_hunt_row_is_followed_before_any_other_job_row(self):
        src = bridge.Bridge._run_job_step.__code__.co_names
        self.assertIn("_class_hunt_row", src)

    def test_the_plan_is_given_the_hunt_slots_the_realm_has_free(self):
        text = bridge_text()
        self.assertIn("classhunt.free_slots(", text)
        self.assertIn("_JOB_HUNTS_OPEN_SQL", text)
        self.assertIn("command LIKE 'hunt-spawn %%'", text)
        self.assertIn("_class_hunt_unsupported_until", text)


if __name__ == "__main__":
    unittest.main()
