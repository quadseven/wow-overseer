"""A pack is left only for true unreachability, and never for good.

Read on the dev realm on 2026-10-06: the three Orc warriors that owe quest 1498
(Path of Defense, Defensive Stance and Taunt) were all held by "every pack of
its objective was tried". The memory behind that read rows that said nothing
about the ground: walks refused by a drop guard since fixed, a hunt of Bigzug
that killed 12 lizards and looted none because the bags were full, hunts that
found no living creature yet. These tests are built from the rows the three
warriors really have (ids, ages and the head of each result as they were read).
"""

import json
import unittest
from unittest import mock

import classquest
import guildjobs
from test_classquest import HIDE, LIZARD, book, class_plan, class_steps, who

HUNTER = dict(quest_log={1498: 3}, quests_done=frozenset({1505}))
PACK_A = dict(LIZARD, guid=12214)
PACK_B = dict(HIDE, guid=12222)
STALL = "stopped getting nearer the spawn"
DIED = "died on the way to the spawn"
DROP = "the first step toward the creature goes over a drop"


def row(rid, name, command, status, age, body, source="classquest"):
    return {
        "id": rid,
        "target_name": name,
        "command": command,
        "source": "guildjobs:%s:%s" % (source, name),
        "status": status,
        "age": age,
        "result": json.dumps(body, separators=(",", ":")),
    }


def walk(rid, name, guid, status, age, outcome, reason, retryable=True):
    body = {"outcome": outcome, "reason": reason, "retryable": retryable}
    return row(
        rid,
        name,
        "walk-to-spawn creature:%d max:20000" % guid,
        status,
        age,
        body,
        "classquest-walk",
    )


def hunt(rid, name, status, age, outcome, reason, kills, loot, retry="later"):
    body = {"outcome": outcome, "reason": reason, "retry": retry}
    body.update(entry=3130, count=5, item=6486, kills=kills, pulls=27, loot_count=loot)
    return row(
        rid,
        name,
        "hunt-spawn creature:3130 item:6486 count:5 max:480",
        status,
        age,
        body,
    )


def recent(*rows):
    return guildjobs.recent_from_rows(rows)


def target(result):
    steps = class_steps(result)
    if not steps:
        return None
    return int(steps[0].rows[0].command.split("creature:")[1].split()[0])


def two_packs():
    return book(spawn_rows=[PACK_A, PACK_B])


def plan(rows, name="Aa", hunts=None, now=0.0):
    return class_plan(
        [who(name, **HUNTER)], two_packs(), recent=rows, hunts=hunts, now=now
    )


# The warriors' real rows, as read at 2026-10-07 00:30 New York (ages in minutes).
BIGZUG = (
    walk(628340, "Bigzug", 12214, "unchanged", 67, "stalled", STALL),
    hunt(
        627877,
        "Bigzug",
        "error",
        78,
        "refused",
        "no living creature of the entry within reach",
        0,
        0,
    ),
    hunt(
        627816,
        "Bigzug",
        "error",
        80,
        "refused",
        "no living creature of the entry within reach",
        0,
        0,
    ),
    hunt(
        627761,
        "Bigzug",
        "error",
        81,
        "refused",
        "no living creature of the entry within reach",
        0,
        0,
    ),
    walk(627686, "Bigzug", 12222, "applied", 82, "arrived", ""),
    hunt(627232, "Bigzug", "applied", 93, "timeout", "the clock ran out", 12, 0),
    walk(625683, "Bigzug", 12214, "error", 128, "refused", DROP),
    walk(625061, "Bigzug", 12222, "error", 144, "refused", DROP),
)
DREADLOX = (
    walk(630390, "Dreadlox", 12214, "unchanged", 22, "stalled", STALL),
    walk(622714, "Dreadlox", 12222, "unchanged", 196, "stalled", STALL),
)
CHILLMON = (
    walk(
        625064,
        "Chillmon",
        12214,
        "unchanged",
        144,
        "timed_out",
        "did not reach the spawn in time",
    ),
    walk(619251, "Chillmon", 12222, "error", 276, "died", DIED),
    walk(
        615717,
        "Chillmon",
        12214,
        "error",
        356,
        "refused",
        guildjobs.classquest.HELD_REASON,
    ),
)


class TheEpoch(unittest.TestCase):
    def test_every_row_read_on_2026_10_06_is_older_than_the_epoch(self):
        for rows in (BIGZUG, DREADLOX, CHILLMON):
            for r in recent(*rows):
                self.assertLessEqual(r.row_id, classquest.TRIED_EPOCH)

    def test_the_epoch_unblocks_the_warriors_the_moment_it_deploys(self):
        # Dreadlox stalled at 12214 22 minutes ago and Bigzug 67 minutes ago;
        # with the packs also left for the hunt rows they were held on both.
        self.assertEqual(guildjobs.refused_marks("Dreadlox", recent(*DREADLOX)), {})
        self.assertEqual(guildjobs.refused_marks("Bigzug", recent(*BIGZUG)), {})
        self.assertFalse(guildjobs.failed_class_walks("Bigzug", recent(*BIGZUG)))

    def test_a_row_after_the_epoch_counts(self):
        late = walk(
            classquest.TRIED_EPOCH + 1, "Aa", 12214, "unchanged", 5, "stalled", STALL
        )
        self.assertEqual(guildjobs.refused_marks("Aa", recent(late)), {12214: 5})

    def test_a_row_with_no_id_counts(self):
        late = walk(0, "Aa", 12214, "unchanged", 5, "stalled", STALL)
        self.assertEqual(guildjobs.refused_marks("Aa", recent(late)), {12214: 5})


@mock.patch.object(classquest, "TRIED_EPOCH", 0)
class TheEvidence(unittest.TestCase):
    """The epoch is off: what the rows themselves say."""

    def test_bigzugs_hunt_rows_are_no_failed_walks(self):
        self.assertFalse(guildjobs.failed_class_walks("Bigzug", recent(*BIGZUG)))

    def test_bigzug_is_never_stalled_while_his_hunt_kills(self):
        # His hunts ended on the clock with kills and no loot; the kills keep
        # the pack and the hunt clock off the packs (the hunt row is 15 minutes
        # old at every pass here).
        fresh = (
            hunt(
                627232, "Bigzug", "applied", 15, "timeout", "the clock ran out", 12, 0
            ),
        )
        hunts = classquest.Hunts()
        for now in (0.0, 1900.0, 3800.0, 5700.0):
            result = plan(recent(*BIGZUG[1:5], *fresh), "Bigzug", hunts, now)
            self.assertEqual(result.helps, ())
            self.assertIsNotNone(target(result), now)

    def test_a_timeout_that_killed_is_no_mark_on_the_pack(self):
        rows = recent(
            hunt(627232, "Aa", "applied", 10, "timeout", "the clock ran out", 12, 0)
        )
        self.assertEqual(guildjobs.refused_marks("Aa", rows), {})
        self.assertEqual(target(plan(rows)), 12214)

    def test_the_words_that_are_not_the_ground_are_no_evidence(self):
        for reason in (
            classquest.HELD_REASON,
            "character is dead",
            "character is in combat",
            classquest.REALM_FULL_REASON,
            classquest.BOT_BUDGET_REASON,
            "did not reach the spawn in time",
        ):
            with self.subTest(reason):
                rows = recent(walk(1, "Aa", 12214, "error", 5, "refused", reason))
                self.assertEqual(guildjobs.refused_marks("Aa", rows), {})

    def test_a_hunt_that_killed_clears_the_mark_of_its_creature(self):
        rows = recent(
            walk(10, "Aa", 12214, "unchanged", 25, "stalled", STALL),
            hunt(11, "Aa", "applied", 10, "timeout", "the clock ran out", 4, 0),
        )
        self.assertEqual(target(plan(rows)), 12214)
        older = recent(
            hunt(9, "Aa", "applied", 40, "timeout", "the clock ran out", 4, 0),
            walk(10, "Aa", 12214, "unchanged", 25, "stalled", STALL),
        )
        self.assertEqual(target(plan(older)), 12222)

    def test_a_hunt_that_killed_clears_the_hunt_clock_marks(self):
        hunts = classquest.Hunts()
        m = who("Aa", **HUNTER)
        hunts.observe(
            "Aa", 1498, 0, classquest.Spawn(12214, 3130, 1, 705.0, -4112.0), 0.0, True
        )
        self.assertTrue(hunts.get("Aa").tried)
        hunts.productive("Aa", 100.0)
        self.assertEqual(hunts.get("Aa").tried, ())
        self.assertEqual(hunts.state(m.name, 101.0), ({1498: ()}, frozenset()))


@mock.patch.object(classquest, "TRIED_EPOCH", 0)
class TheHold(unittest.TestCase):
    def test_a_stall_and_a_death_are_left_for_thirty_minutes(self):
        for reason, outcome in ((STALL, "stalled"), (DIED, "died")):
            for age, want in ((29, 12222), (30, 12214)):
                rows = recent(walk(1, "Aa", 12214, "unchanged", age, outcome, reason))
                self.assertEqual(target(plan(rows)), want, (reason, age))

    def test_a_drop_is_still_left_for_two_hours(self):
        rows = recent(walk(1, "Aa", 12214, "error", 119, "refused", DROP))
        self.assertEqual(target(plan(rows)), 12222)

    def test_with_every_pack_left_the_oldest_is_asked_again_after_thirty(self):
        rows = recent(
            walk(1, "Aa", 12214, "error", 100, "refused", DROP),
            walk(2, "Aa", 12222, "error", 40, "refused", DROP),
        )
        self.assertEqual(target(plan(rows)), 12214)
        self.assertEqual(plan(rows).helps, ())

    def test_with_every_pack_left_and_none_old_the_member_waits(self):
        rows = recent(
            walk(1, "Aa", 12214, "error", 10, "refused", DROP),
            walk(2, "Aa", 12222, "error", 29, "refused", DROP),
        )
        result = plan(rows)
        self.assertIsNone(target(result))
        self.assertEqual([h.move.blocker for h in result.helps], [classquest.STALLED])


@mock.patch.object(classquest, "TRIED_EPOCH", 0)
class TheRoom(unittest.TestCase):
    def test_kills_and_no_loot_leave_the_pack_and_the_room_step_runs(self):
        # Bigzug's hunt 627232: 12 kills, no loot, bags full. The pack is no
        # mark, so the plan still wants it, and with no free slot the make-room
        # step goes first.
        rows = recent(
            hunt(627232, "Aa", "applied", 5, "timeout", "the clock ran out", 12, 0)
        )
        b = two_packs()
        m = who("Aa", free_slots=0, **HUNTER)
        avoid, off = guildjobs.class_avoid(m, b, rows)
        self.assertEqual((avoid, off), ({}, frozenset()))
        move, _ = classquest.next_move(b, m, avoid, off)
        self.assertEqual(move.kind, classquest.HUNT)
        got = guildjobs.class_room_step(m, move, b, rows, 20000)
        self.assertIsNotNone(got)
        self.assertEqual(
            got[2],
            "Aa has no room for its class quest and nothing it may sell, mail or destroy",
        )


@mock.patch.object(classquest, "TRIED_EPOCH", 0)
class TheUnknownQuest(unittest.TestCase):
    def test_a_marked_quest_the_book_lacks_is_left_as_it_was(self):
        rows = recent(walk(1, "Aa", 12214, "unchanged", 5, "stalled", STALL))
        m = who("Aa", **HUNTER)
        with mock.patch.object(
            classquest, "marked_places", return_value={9999: ((1, 705.0, -4112.0, 5),)}
        ):
            avoid, _off = guildjobs.class_avoid(m, two_packs(), rows)
        self.assertEqual(avoid, {9999: ((1, 705.0, -4112.0),)})


if __name__ == "__main__":
    unittest.main()
