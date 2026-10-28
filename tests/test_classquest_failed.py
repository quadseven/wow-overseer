"""A class quest the member failed is dropped and taken again (#781).

The Affray (1719) is a timed quest (quest_template TimeAllowed 600, ten
minutes from the take), so a warrior that does not beat the challengers and
Big Will in time fails it, and a failed quest (status 5) stays in the log.

The book read the log as `status IN (1, 3)`, so a failed quest read as never
taken, and the planner sent the member to take it again. The core refuses that
take while the failed quest holds its log slot, so the warrior was sent back to
Klannoc Macleod pass after pass and never got further.

A failed class quest is now an ABANDON, the same one-row step a quest whose
StartItem was lost already is: the member drops it, the next pass sends it to
take it again, and the timer starts anew beside the grate. The abandon hold
(classquest.ABANDON_HOLD_MINUTES) keeps a quest failed again from being dropped
in a loop.
"""

import unittest

from test_classquest import class_plan, class_steps
from test_classquest_unblock import GRATE, affray_book, member

import classquest
import guildjobs

AFFRAY = 1719
# QUEST_STATUS_FAILED, as character_queststatus carries it.
FAILED = 5


def failed(**over):
    over.setdefault("quest_log", {AFFRAY: FAILED})
    return member(**over)


class TheFailedAffray(unittest.TestCase):
    def test_a_failed_affray_is_dropped_not_taken_again(self):
        move, blocked = classquest.next_move(affray_book([GRATE]), failed())
        self.assertEqual(blocked, [])
        self.assertEqual((move.kind, move.quest), (classquest.ABANDON, AFFRAY))
        self.assertIsNone(move.spot)
        self.assertIn("failed", move.said)
        self.assertIn("The Affray", move.said)

    def test_the_step_is_one_abandon_row_and_no_walk(self):
        steps = class_steps(class_plan([failed()], b=affray_book([GRATE])))
        self.assertEqual(len(steps), 1)
        self.assertIsNone(steps[0].walk)
        self.assertEqual(
            [(r.kind, r.command) for r in steps[0].rows],
            [("quest", "abandon quest:%d" % AFFRAY)],
        )

    def test_once_dropped_the_take_walks_to_klannoc(self):
        move, _blocked = classquest.next_move(affray_book([GRATE]), member())
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, AFFRAY))
        self.assertEqual(move.spot.name, "Klannoc Macleod")

    def test_a_quest_failed_again_lately_is_not_dropped_in_a_loop(self):
        m = failed()
        move, _ = classquest.next_move(affray_book([GRATE]), m)
        recent = guildjobs.recent_from_rows(
            [
                {
                    "target_name": m.name,
                    "command": "abandon quest:%d" % AFFRAY,
                    "source": guildjobs.source_for(classquest.ACTION, m.name),
                    "status": "delivered",
                    "age": 30,
                    "result": "",
                }
            ]
        )
        step, _said, note = guildjobs._abandon_step(m, move, recent, "")
        self.assertIsNone(step)
        self.assertIn("dropped lately", note)

    def test_an_incomplete_affray_is_still_worked_on_the_grate(self):
        move, _ = classquest.next_move(
            affray_book([GRATE]),
            member(quest_log={AFFRAY: classquest.STATUS_INCOMPLETE}),
        )
        self.assertEqual((move.kind, move.spot.guid), (classquest.HUNT, 13575))


class TheLogRead(unittest.TestCase):
    def test_the_failed_status_is_the_cores(self):
        self.assertEqual(getattr(classquest, "STATUS_FAILED", None), FAILED)

    def test_the_log_read_keeps_a_failed_quest(self):
        self.assertIn("status IN (1, 3, 5)", classquest.LOG_SQL)


if __name__ == "__main__":
    unittest.main()
