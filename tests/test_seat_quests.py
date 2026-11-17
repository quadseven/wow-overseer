"""A raid seat takes the quests its quest items name (#2648).

The seams driven: `seatquests.relieve` for what the seat may take,
`guildjobs.plan` for the step it is sent on, and the bridge's own read and
pass (`_read_seat_quests`, `_seat_untaken_quests`) over a fake database.
"""

from __future__ import annotations

import pathlib
import unittest
from unittest import mock

import guildjobs
import seatquests
from test_guild_seat_bags import SEAT, seat
from test_guild_seat_bags import member as _member  # noqa: F401
from test_guildjobs import only_step, plan
from test_guildsocial_bridge import bridge

ITEM = 5001
QUEST = 700
GIVER = guildjobs.Spot(
    kind="creature",
    spawn=4242,
    map_id=0,
    x=-9100.0,
    y=120.0,
    name="Questgiver",
    near=12,
)
FAR_GIVER = guildjobs.Spot(
    kind="creature", spawn=4243, map_id=1, x=10.0, y=10.0, name="Faraway"
)


def quest_row(quest=QUEST, **over):
    row = {
        "ID": quest,
        "LogTitle": "Quest %d" % quest,
        "QuestLevel": 40,
        "MinLevel": 30,
        "AllowableRaces": 0,
        "Flags": 0,
        "StartItem": 0,
        "RequiredItemId1": ITEM,
        "MaxLevel": 0,
        "AllowableClasses": 0,
        "PrevQuestID": 0,
        "NextQuestID": 0,
        "ExclusiveGroup": 0,
    }
    row.update(over)
    return row


def ready_seat(**over):
    # Trades at their ceiling: no trainer rung comes before the quest rung.
    skills = {guildjobs.FIRST_AID: (300, 300), guildjobs.COOKING: (300, 300)}
    base = dict(free_slots=30, rewarded=frozenset(), skills=skills)
    base.update(over)
    return seat(**base)


def read_with(rows=None, givers=None, carried=None):
    rows = (quest_row(),) if rows is None else tuple(rows)
    return lambda names: seatquests.Read(
        rows=rows,
        carried={SEAT: {ITEM}} if carried is None else carried,
        givers={QUEST: (GIVER,)} if givers is None else givers,
    )


def relieve(members, read, now=0.0, memo=None, environ=None):
    return seatquests.relieve(members, read, now, memo or seatquests.Memo(), environ)


class WhatTheSeatMayTake(unittest.TestCase):
    def test_a_takable_quest_its_item_names_is_put_on_the_seat(self):
        (out,), lines = relieve([ready_seat()], read_with())
        self.assertEqual([u.quest_id for u in out.untaken], [QUEST])
        self.assertEqual(out.untaken[0].givers, (GIVER,))
        self.assertEqual(len(lines), 1)
        self.assertIn(SEAT, lines[0])
        self.assertIn("1 items covered, 1 takable, 1 with a giver, 0 closed", lines[0])

    def test_a_seat_whose_read_now_finds_nothing_loses_its_old_list(self):
        old = ready_seat(
            untaken=(seatquests.questuntaken.Untaken(QUEST, "", (), (GIVER,), True),)
        )
        (out,), _ = relieve([old], read_with(rows=[quest_row(MinLevel=61)]))
        self.assertEqual(out.untaken, ())

    def test_a_quest_in_the_log_or_rewarded_is_not_untaken(self):
        held = ready_seat(quest_log={QUEST: 1})
        done = ready_seat(rewarded=frozenset({QUEST}))
        for m in (held, done):
            (out,), _ = relieve([m], read_with())
            self.assertEqual(out.untaken, (), m.quest_log)

    def test_a_quest_the_seat_is_too_low_for_or_a_race_shuts_out_is_left(self):
        for over in ({"MinLevel": 61}, {"AllowableRaces": 2}, {"PrevQuestID": 9}):
            (out,), _ = relieve([ready_seat()], read_with([quest_row(**over)]))
            self.assertEqual(out.untaken, (), over)

    def test_a_quest_far_above_the_seat_is_left(self):
        rows = [quest_row(QuestLevel=60 + seatquests.LEVEL_REACH + 1, MinLevel=0)]
        (out,), _ = relieve([ready_seat(level=60)], read_with(rows))
        self.assertEqual(out.untaken, ())

    def test_a_quest_with_no_giver_and_no_start_item_is_left(self):
        (out,), _ = relieve([ready_seat()], read_with(givers={}))
        self.assertEqual(out.untaken, ())

    def test_a_quest_the_carried_item_starts_needs_no_giver(self):
        rows = [quest_row(StartItem=ITEM, RequiredItemId1=0)]
        (out,), _ = relieve([ready_seat()], read_with(rows, givers={}))
        self.assertTrue(out.untaken[0].by_item)

    def test_a_seat_whose_rewards_are_unread_is_never_sent(self):
        (out,), _ = relieve([ready_seat(rewarded=None)], read_with())
        self.assertEqual(out.untaken, ())

    def test_only_an_approved_seat_online_and_walking_alone(self):
        for over in ({"online": False}, {"alive": False}, {"follows": True}):
            (out,), _ = relieve([ready_seat(**over)], read_with())
            self.assertEqual(out.untaken, (), over)

    def test_a_failed_read_leaves_the_members_as_they_were(self):
        (out,), lines = relieve([ready_seat()], lambda names: None)
        self.assertEqual((out.untaken, lines), ((), ()))

    def test_the_switch_off_reads_nothing(self):
        reads = []
        env = {seatquests.ENV: "off"}
        (out,), _ = relieve([ready_seat()], lambda n: reads.append(n), environ=env)
        self.assertEqual((out.untaken, reads), ((), []))

    def test_a_seat_read_lately_is_not_read_again(self):
        memo = seatquests.Memo()
        reads = []

        def read(names):
            reads.append(names)
            return read_with()(names)

        relieve([ready_seat()], read, 0.0, memo)
        (out,), _ = relieve([ready_seat()], read, 60.0, memo)
        self.assertEqual(len(reads), 1)
        self.assertEqual([u.quest_id for u in out.untaken], [QUEST])
        relieve([ready_seat()], read, seatquests.REFRESH_SECONDS + 1, memo)
        self.assertEqual(len(reads), 2)


def sent(**over):
    (m,), _ = relieve([ready_seat(**over)], read_with())
    return m


class TheStepTheSeatIsSentOn(unittest.TestCase):
    def setUp(self):
        # The profession errand comes first for a seat that lacks its trade;
        # these tests are about the rung after it.
        nothing = {
            "_profession_first": lambda *a, **k: (None, ""),
            "_train_step": lambda *a, **k: (None, ""),
            "_learn_step": lambda *a, **k: None,
        }
        for name, answer in nothing.items():
            patch = mock.patch.object(guildjobs, name, answer)
            patch.start()
            self.addCleanup(patch.stop)

    def step(self, m, recent=()):
        return only_step(plan([m], recent=tuple(recent)), SEAT)

    def test_a_seat_away_from_the_giver_walks_there_then_takes_the_quest(self):
        step = self.step(sent())
        self.assertEqual(step.action, guildjobs.UNTAKEN_ACTION)
        self.assertEqual(step.key, QUEST)
        self.assertIn("walk-to-spawn creature:4242", step.walk.command)
        self.assertEqual([r.command for r in step.rows], ["take quest:%d" % QUEST])

    def test_a_seat_at_the_giver_takes_without_a_walk(self):
        step = self.step(sent(x=GIVER.x + 3, y=GIVER.y))
        self.assertIsNone(step.walk)
        self.assertEqual([r.command for r in step.rows], ["take quest:%d" % QUEST])

    def test_a_giver_on_another_map_sends_nobody(self):
        (m,), _ = relieve([ready_seat()], read_with(givers={QUEST: (FAR_GIVER,)}))
        step = self.step(m)
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.UNTAKEN_ACTION)

    def test_a_quest_asked_lately_is_not_asked_again_even_when_refused(self):
        recent = guildjobs.Recent(
            name=SEAT,
            action=guildjobs.UNTAKEN_ACTION,
            age_minutes=guildjobs.UNTAKEN_PAUSE_MINUTES + 5,
            status="failed",
            command="take quest:%d" % QUEST,
        )
        step = self.step(sent(), [recent])
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.UNTAKEN_ACTION)

    def test_the_quest_is_asked_again_after_the_cooldown(self):
        recent = guildjobs.Recent(
            name=SEAT,
            action=guildjobs.UNTAKEN_ACTION,
            age_minutes=guildjobs.UNTAKEN_COOLDOWN_MINUTES + 1,
            status="failed",
            command="take quest:%d" % QUEST,
        )
        self.assertEqual(self.step(sent(), [recent]).action, guildjobs.UNTAKEN_ACTION)

    def test_a_step_under_way_holds_the_next(self):
        recent = guildjobs.Recent(
            name=SEAT,
            action=guildjobs.UNTAKEN_ACTION,
            age_minutes=1,
            status="pending",
            command="walk-to-spawn creature:4242",
            walk=True,
        )
        step = self.step(sent(), [recent])
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.UNTAKEN_ACTION)

    def test_a_quest_taken_lately_is_not_taken_again(self):
        step = self.step(sent(recently_taken=frozenset({QUEST})))
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.UNTAKEN_ACTION)


class FakeCursor:
    def __init__(self, log):
        self.log = log
        self.result = []

    def execute(self, sql, params=()):
        self.log.append(sql)
        if "FROM characters c" in sql:
            self.result = [{"name": SEAT, "entry": ITEM}]
        elif "creature_queststarter" in sql:
            self.result = [
                {
                    "quest": QUEST,
                    "spawn": 4242,
                    "map_id": 0,
                    "x": -9100.0,
                    "y": 120.0,
                    "name": "Questgiver",
                }
            ]
        elif "quest_template t" in sql:
            self.result = [quest_row()]
        else:
            self.result = []

    def fetchall(self):
        return list(self.result)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self.log)


class TheBridgePass(unittest.TestCase):
    def setUp(self):
        nothing = {
            "_profession_first": lambda *a, **k: (None, ""),
            "_train_step": lambda *a, **k: (None, ""),
            "_learn_step": lambda *a, **k: None,
        }
        for name, answer in nothing.items():
            patch = mock.patch.object(guildjobs, name, answer)
            patch.start()
            self.addCleanup(patch.stop)
        self.sql = []
        patch = mock.patch.object(bridge, "_connect", lambda: FakeConn(self.sql))
        patch.start()
        self.addCleanup(patch.stop)
        memo = mock.patch.object(bridge, "_SEAT_QUEST_MEMO", seatquests.Memo())
        memo.start()
        self.addCleanup(memo.stop)

    def test_the_bridge_read_names_the_item_the_quest_and_the_giver(self):
        got = bridge._read_seat_quests([SEAT])
        self.assertEqual(got.carried, {SEAT: {ITEM}})
        self.assertEqual([r["ID"] for r in got.rows], [QUEST])
        self.assertEqual(got.givers[QUEST][0].spawn, 4242)
        self.assertEqual(got.givers[QUEST][0].near, int(guildjobs.UNTAKEN_NEAR))
        self.assertEqual(len(self.sql), 3)

    def test_a_seat_with_no_quest_items_reads_no_quests(self):
        with mock.patch.object(
            FakeCursor,
            "execute",
            lambda self, sql, params=(): setattr(self, "result", []),
        ):
            got = bridge._read_seat_quests([SEAT])
        self.assertEqual((got.rows, got.carried), ((), {}))

    def test_a_database_error_is_a_failed_read(self):
        class Boom:
            def __enter__(self):
                raise OSError("down")

            def __exit__(self, *args):
                return False

        with mock.patch.object(bridge, "_connect", lambda: Boom()):
            self.assertIsNone(bridge._read_seat_quests([SEAT]))

    def test_the_pass_puts_the_quest_on_the_seat_and_the_plan_sends_it(self):
        (m,), lines = bridge._seat_untaken_quests([ready_seat()])
        self.assertEqual([u.quest_id for u in m.untaken], [QUEST])
        self.assertTrue(lines)
        step = only_step(plan([m]), SEAT)
        self.assertEqual((step.action, step.key), (guildjobs.UNTAKEN_ACTION, QUEST))
        self.assertEqual(step.rows[0].command, "take quest:%d" % QUEST)

    def test_a_pass_that_fails_carries_on_with_the_members(self):
        with mock.patch.object(seatquests, "relieve", side_effect=RuntimeError("x")):
            out, lines = bridge._seat_untaken_quests([ready_seat()])
        self.assertEqual(([m.name for m in out], lines), ([SEAT], ()))

    def test_the_guild_job_pass_asks_before_the_plan(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        start = text.index("async def _start_guild_job_pass")
        end = text.index("plan = await self._plan_guild_jobs", start)
        self.assertIn("_seat_untaken_quests", text[start:end])


if __name__ == "__main__":
    unittest.main()
