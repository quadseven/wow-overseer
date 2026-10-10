"""A class quest that keeps failing yields to levelling, then tries again
(2026-10-10).

Read on the dev realm on 2026-10-10 at 01:00 America/New_York: Diggo, a level
14 Cave hunter in Teldrassil, had been level 14 for 68 hours on a Taming the
Beast loop. Every hour or so the class step walked him to a Webwood Lurker and
asked `use-item-on creature:1998 item:15921`, and the module answered "the
creature is dead", "no such target within reach on this map", "character is in
combat". The stall hold of 2026-10-09 only let a level walk out of an outgrown
zone go first; Diggo had no such walk to make, so the class step kept him, and
no other job (a stood-still hearth, food, gear) was ever asked of him. In 24
hours 43 guild members had three or more class quest rows fail.

The operator's rule: a mandatory class quest that keeps failing must yield to
levelling until it can move. After CLASS_STALL_ROWS failed rows in a row inside
CLASS_STALL_WINDOW_MINUTES the class step steps aside for
CLASS_STALL_HOLD_MINUTES, whatever else the member has to do, and then tries
again. A retry that fails again yields again at once.
"""

import json
import unittest

import classquest
import guildjobs
import standstill
from test_classquest import class_plan, who
from test_classquest_stall_release import failing, stuck, take_failed
from test_guildlevel import world

BARRENS = 17
POST = {"Bigzug": ("take-item mail:7 item:70",)}


def plan(members, recent=(), **kw):
    kw.setdefault("leveling", world())
    return class_plan(members, recent=tuple(recent), **kw)


def step_of(result, name="Bigzug"):
    steps = [s for s in result.steps if s.holder == name]
    return steps[0] if steps else None


def tame_failed(age, reason, name="Bigzug"):
    """Diggo's row: a refusal with "retry":"later" and no "retryable"."""
    body = {
        "outcome": "refused",
        "reason": reason,
        "retry": "later",
        "request": "use-item-on creature:1998 item:15921",
    }
    return guildjobs.recent_from_rows(
        [
            {
                "id": 0,
                "target_name": name,
                "command": "use-item-on creature:1998 item:15921",
                "source": guildjobs.source_for(classquest.ACTION, name),
                "status": "error",
                "age": age,
                "result": json.dumps(body, separators=(",", ":")),
            }
        ]
    )[0]


def fits():
    """The member of test_classquest_stall_release whose zone still fits its
    level, so it has no level walk to make."""
    return stuck(zone_id=BARRENS)


class TheYield(unittest.TestCase):
    def test_a_failing_class_quest_steps_aside_with_no_level_walk_to_make(self):
        result = plan([fits()], failing(10, 40, 70))
        step = step_of(result)
        self.assertTrue(step is None or step.action != classquest.ACTION, step)
        self.assertTrue(
            any("steps aside" in n and "Bigzug" in n for n in result.notes),
            result.notes,
        )

    def test_the_note_counts_the_failures_and_the_minutes_left(self):
        result = plan([fits()], failing(10, 40, 70))
        left = guildjobs.CLASS_STALL_HOLD_MINUTES - 10
        self.assertTrue(
            any("failed 3 times" in n and "%d more minute" % left in n for n in result.notes),
            result.notes,
        )

    def test_the_member_is_not_held_on_the_quest_meanwhile(self):
        result = plan([fits()], failing(10, 40, 70))
        self.assertNotIn("Path of Defense", result.lines.get("Bigzug", ""))

    def test_another_job_runs_in_its_place(self):
        # Post waiting in its mailbox is collected, which the class step used
        # to keep it from.
        result = plan([fits()], failing(10, 40, 70), mail=POST)
        self.assertEqual(step_of(result).action, "collect")

    def test_without_the_yield_the_class_quest_holds_it(self):
        result = plan([fits()], failing(10, 40), mail=POST)
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_a_stand_counted_before_the_failures_still_waits_for_quiet(self):
        # The stood-still hearth keeps its own rule: no row for the member
        # while it stood.
        result = plan(
            [fits()], failing(10, 40, 70), still={"Bigzug": standstill.STILL_MINUTES}
        )
        self.assertIsNone(step_of(result))

    def test_diggos_tame_refusals_count(self):
        recent = (
            tame_failed(1, "no such target within reach on this map"),
            tame_failed(2, "the creature is dead"),
            tame_failed(3, "character is in combat"),
        )
        left, failed = guildjobs.class_stall_hold("Bigzug", recent)
        self.assertEqual(failed, 3)
        self.assertEqual(left, guildjobs.CLASS_STALL_HOLD_MINUTES - 1)
        step = step_of(plan([fits()], recent))
        self.assertTrue(step is None or step.action != classquest.ACTION, step)


class TheRetry(unittest.TestCase):
    def test_after_the_hold_the_class_step_tries_again(self):
        old = guildjobs.CLASS_STALL_HOLD_MINUTES
        result = plan([fits()], failing(old, old + 20, old + 40))
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_a_retry_that_fails_again_yields_again(self):
        old = guildjobs.CLASS_STALL_HOLD_MINUTES
        recent = failing(old + 5, old + 25, old + 45) + (take_failed(5),)
        left, failed = guildjobs.class_stall_hold("Bigzug", recent)
        self.assertEqual((left, failed), (old - 5, 4))
        step = step_of(plan([fits()], recent))
        self.assertTrue(step is None or step.action != classquest.ACTION, step)

    def test_the_window_holds_a_whole_yield_and_its_retry(self):
        self.assertGreater(
            guildjobs.CLASS_STALL_WINDOW_MINUTES,
            guildjobs.CLASS_STALL_HOLD_MINUTES + 120,
        )

    def test_the_yield_is_hours_of_levelling(self):
        self.assertGreaterEqual(guildjobs.CLASS_STALL_HOLD_MINUTES, 180)

    def test_a_member_whose_quest_moves_keeps_it(self):
        recent = failing(10, 40, 70)
        result = plan([fits(), who("Chillmon", quests_done=frozenset({1505}))], recent)
        self.assertEqual(step_of(result, "Chillmon").action, classquest.ACTION)


if __name__ == "__main__":
    unittest.main()
