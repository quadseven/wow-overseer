"""A class quest hunt leaves the spawns the module refused, and the ones too high.

Read on the dev realm on 2026-10-06 (163 class quest walk-to-spawn rows): 43
ended "the first step toward the creature goes over a drop", 32 "character is
held by another verb", 9 "stopped getting nearer the spawn", 8 "died on the way to
the spawn", 5 "the way to the spawn crosses the other side's ground". The same
spawn was sent to again every pass: a refused walk was a retryable row, so only
two failed walks in a row and a half hour of no progress moved a hunt to
another pack, and a member that died on the way was sent back up to the creature
that killed it. These tests hold the plan to the module's own words: a spawn
the module refused, or that a walk did not reach, is left for a while and the
member goes to the next pack; a creature too many levels over the member is
never chosen; a member the module held is asked again after the hold.
"""

import json
import unittest

import classquest
import guildjobs
from test_classquest import (
    HIDE,
    LIZARD,
    book,
    class_plan,
    class_steps,
    who,
)

# The lizard pack (guid 4788) is the nearer one; the hide pack (guid 12197) is
# 213 yards on, past a pack's width.
HUNTER = dict(quest_log={1498: 3}, quests_done=frozenset({1505}))
DROP = "the first step toward the creature goes over a drop"


def walked(name, guid, reason, age, outcome="refused", retryable=False):
    """A recent class quest walk row that the module ended with `reason`."""
    body = {"outcome": outcome, "reason": reason, "retryable": retryable}
    row = {
        "target_name": name,
        "command": "walk-to-spawn creature:%d max:20000" % guid,
        "source": guildjobs.source_for(classquest.ACTION, name),
        "status": "error",
        "age": age,
        "result": json.dumps(body, separators=(",", ":")) + "x" * 40,
    }
    return guildjobs.recent_from_rows([row])[0]


def hunt_target(result):
    steps = class_steps(result)
    if not steps:
        return None
    return int(steps[0].rows[0].command.split("creature:")[1].split()[0])


class TheRows(unittest.TestCase):
    def test_a_walk_row_carries_its_spawn_and_its_reason(self):
        row = walked("Aa", 4788, DROP, 3)
        self.assertEqual((row.spawn, row.reason), (4788, DROP))
        self.assertEqual(row.refusal, DROP)

    def test_a_stall_gives_its_reason_though_it_was_no_refusal(self):
        row = walked("Aa", 4788, "stopped getting nearer the spawn", 3, "stalled", True)
        self.assertEqual(row.reason, "stopped getting nearer the spawn")
        self.assertEqual(row.refusal, "")  # the hunt clock still reads it as before
        self.assertFalse(row.retryable)

    def test_a_row_that_is_no_creature_walk_names_no_spawn(self):
        row = guildjobs.recent_from_rows(
            [
                {
                    "target_name": "Aa",
                    "command": "take quest:1498",
                    "source": guildjobs.source_for(classquest.ACTION, "Aa"),
                    "status": "delivered",
                    "age": 1,
                    "result": "",
                }
            ]
        )[0]
        self.assertEqual((row.spawn, row.reason), (0, ""))


class TheRefusedSpawn(unittest.TestCase):
    def plan(self, recent, members=None):
        return class_plan(members or [who("Aa", **HUNTER)], recent=tuple(recent))

    def test_with_no_refusal_the_nearer_pack_is_hunted(self):
        self.assertEqual(hunt_target(self.plan([])), 4788)

    def test_one_drop_refusal_sends_the_member_to_the_next_pack(self):
        self.assertEqual(hunt_target(self.plan([walked("Aa", 4788, DROP, 20)])), 12197)

    def test_every_word_that_blames_the_spawn_moves_the_hunt_on(self):
        for reason in sorted(classquest.SPAWN_REFUSALS):
            with self.subTest(reason):
                got = hunt_target(self.plan([walked("Aa", 4788, reason, 20)]))
                self.assertEqual(got, 12197)

    def test_the_words_that_blame_the_member_do_not(self):
        for reason in (
            "character is dead",
            "character is in combat",
            "character is held by another verb",
            classquest.REALM_FULL_REASON,
            classquest.BOT_BUDGET_REASON,
            "a walk is already under way for this character",
            "entered combat on the way to the spawn",
        ):
            with self.subTest(reason):
                recent = [walked("Aa", 4788, reason, 600, retryable=True)]
                self.assertEqual(hunt_target(self.plan(recent)), 4788)

    def test_a_refusal_is_remembered_for_a_while_and_then_forgotten(self):
        for age, want in (
            (classquest.SPAWN_REFUSED_MINUTES - 1, 12197),
            (classquest.SPAWN_REFUSED_MINUTES, 4788),
        ):
            self.assertEqual(
                hunt_target(self.plan([walked("Aa", 4788, DROP, age)])), want, age
            )

    def test_it_is_remembered_per_member(self):
        members = [who("Aa", **HUNTER), who("Bb", **HUNTER)]
        result = self.plan([walked("Aa", 4788, DROP, 20)], members)
        by = {s.holder: s for s in class_steps(result)}
        self.assertIn("creature:12197", by["Aa"].rows[0].command)
        self.assertIn("creature:4788", by["Bb"].rows[0].command)

    def test_a_member_who_died_on_the_way_is_not_sent_back_to_that_pack(self):
        died = walked("Aa", 4788, "died on the way to the spawn", 15, "died", True)
        self.assertEqual(hunt_target(self.plan([died])), 12197)

    def test_a_spawn_among_the_pack_leaves_the_whole_pack(self):
        near = dict(LIZARD, guid=4790, x=LIZARD["x"] + 60.0)
        b = book(spawn_rows=[LIZARD, near, HIDE])
        result = class_plan(
            [who("Aa", **HUNTER)], b, recent=(walked("Aa", 4788, DROP, 20),)
        )
        self.assertEqual(hunt_target(result), 12197)

    def test_with_every_pack_refused_the_member_waits_and_says_why(self):
        recent = [walked("Aa", 4788, DROP, 20), walked("Aa", 12197, DROP, 25)]
        result = self.plan(recent)
        self.assertEqual(class_steps(result), [])
        self.assertTrue(any("every pack" in n for n in result.notes), result.notes)
        self.assertEqual([h.move.blocker for h in result.helps], [classquest.STALLED])

    def test_the_refused_walks_are_read_from_the_member_alone(self):
        rows = [walked("Bb", 4788, DROP, 20), walked("Aa", 12197, DROP, 20)]
        self.assertEqual(guildjobs.refused_spawns("Aa", rows), {12197})
        self.assertEqual(guildjobs.refused_spawns("Bb", rows), {4788})


class TheLevel(unittest.TestCase):
    def spawns(self, lizard_level, hide_level):
        return [dict(LIZARD, level=lizard_level), dict(HIDE, level=hide_level)]

    def plan(self, spawns, level, x=1500.0):
        b = book(spawn_rows=spawns)
        m = who("Aa", level=level, x=x, y=-4200.0, **HUNTER)
        return class_plan([m], b)

    def test_the_spawn_query_reads_the_creatures_level(self):
        self.assertIn("ct.maxlevel AS level", classquest.SPAWNS_SQL)
        self.assertEqual(
            book(spawn_rows=self.spawns(10, 30)).quests[1498].fields[0].level, 10
        )

    def test_a_creature_too_far_over_the_member_is_not_chosen(self):
        # The hide pack is the nearer, and thirty is far over fifteen.
        result = self.plan(self.spawns(10, 30), level=15)
        self.assertEqual(hunt_target(result), 4788)

    def test_the_nearer_creature_is_chosen_when_both_are_in_reach(self):
        result = self.plan(self.spawns(10, 17), level=15)
        self.assertEqual(hunt_target(result), 12197)

    def test_the_gap_is_the_modules_lethal_three(self):
        self.assertEqual(classquest.OVERLEVEL_MAX, 3)
        self.assertEqual(hunt_target(self.plan(self.spawns(10, 18), level=15)), 12197)
        self.assertEqual(hunt_target(self.plan(self.spawns(10, 19), level=15)), 4788)

    def test_a_level_the_world_does_not_give_is_no_reason_to_skip(self):
        result = self.plan(self.spawns(0, 0), level=15)
        self.assertEqual(hunt_target(result), 12197)

    def test_when_every_spawn_is_too_high_the_member_waits_and_says_so(self):
        result = self.plan(self.spawns(30, 31), level=15)
        self.assertEqual(class_steps(result), [])
        self.assertTrue(
            any("levels over the member" in n for n in result.notes), result.notes
        )


class TheHold(unittest.TestCase):
    def held(self, age):
        return walked("Aa", 4788, classquest.HELD_REASON, age, retryable=True)

    def test_a_member_the_module_held_is_asked_again_after_the_hold(self):
        m = who("Aa", **HUNTER)
        soon = (self.held(classquest.HELD_BACKOFF_MINUTES - 1),)
        later = (self.held(classquest.HELD_BACKOFF_MINUTES),)
        self.assertEqual(class_steps(class_plan([m], recent=soon)), [])
        self.assertEqual(len(class_steps(class_plan([m], recent=later))), 1)

    def test_the_wait_covers_the_longest_hold_the_module_places(self):
        revival_hold_minutes = 690 / 60.0
        self.assertGreaterEqual(classquest.HELD_BACKOFF_MINUTES, revival_hold_minutes)

    def test_a_hunt_waiting_out_a_hold_does_not_stall_on_the_waiting(self):
        m = who("Aa", **HUNTER)
        hunts = classquest.Hunts()
        for now in (0.0, 1500.0, 3000.0, 4500.0):
            result = class_plan([m], recent=(self.held(1),), hunts=hunts, now=now)
            self.assertEqual(class_steps(result), [])
        self.assertEqual(hunts.get("Aa").tried, ())

    def test_the_note_names_no_far_walk_wall_it_did_not_meet(self):
        result = class_plan([who("Aa", **HUNTER)], recent=(self.held(1),))
        self.assertTrue(any("was refused" in n for n in result.notes), result.notes)
        self.assertFalse(any("far walk" in n for n in result.notes), result.notes)


if __name__ == "__main__":
    unittest.main()
