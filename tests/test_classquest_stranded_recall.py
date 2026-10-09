"""A death knight stranded below Acherus asks for the hearth recall (2026-10-08).

Brug stood on the ground 266 yards below Acherus, his home, with no hearthstone;
two walks to the giver stopped getting nearer. The module's `hearth recall` casts
the stone's own spell. The bridge asks for it after STRANDED_STALLED_WALKS stalled
walks, once an hour (the hearth cooldown).
"""

import json
import unittest

import classquest
import guildjobs
from test_classquest_use import who

DK = 6
STALL = guildjobs.STALLED_WALK_REASON


def knight(**over):
    base = dict(
        name="Brug",
        class_id=DK,
        level=60,
        map_id=classquest.DEATH_KNIGHT_START_MAP,
    )
    base.update(over)
    return who(**base)


def rows(*specs):
    out = []
    for source, command, age, reason, *status in specs:
        body = {"outcome": "stalled", "reason": reason, "retryable": True}
        out.append(
            {
                "target_name": "Brug",
                "command": command,
                "source": guildjobs.source_for(*source),
                "status": status[0] if status else "unchanged",
                "age": age,
                "result": json.dumps(body, separators=(",", ":")) + "x" * 20,
            }
        )
    return guildjobs.recent_from_rows(out)


WALK = ("classquest-walk", "Brug")
STALLS = rows(
    (WALK, "walk-to-spawn creature:129307 max:20000", 10, STALL),
    (WALK, "walk-to-spawn creature:129307 max:20000", 30, STALL),
)


class TheRecall(unittest.TestCase):
    def test_two_stalled_walks_ask_for_the_recall(self):
        step = guildjobs.stranded_recall_step(knight(), STALLS)
        self.assertEqual(step.action, "hearth")
        self.assertEqual(
            (step.rows[0].kind, step.rows[0].command), ("hearth", "recall")
        )

    def test_one_stalled_walk_does_not(self):
        self.assertIsNone(guildjobs.stranded_recall_step(knight(), STALLS[:1]))

    def test_old_stalls_do_not_count(self):
        old = rows(
            (WALK, "walk-to-spawn creature:1 max:20000", 300, STALL),
            (WALK, "walk-to-spawn creature:1 max:20000", 400, STALL),
        )
        self.assertIsNone(guildjobs.stranded_recall_step(knight(), old))

    def test_only_a_knight_in_its_start_zone_asks(self):
        self.assertIsNone(guildjobs.stranded_recall_step(knight(map_id=0), STALLS))
        self.assertIsNone(guildjobs.stranded_recall_step(knight(class_id=1), STALLS))

    def test_a_recall_within_the_hearth_cooldown_is_not_repeated(self):
        done = STALLS + rows((("hearth", "Brug"), "recall", 20, "", "applied"))
        self.assertIsNone(guildjobs.stranded_recall_step(knight(), done))

    def test_a_refused_recall_does_not_spend_the_cooldown(self):
        # A recall refused for a fight (status error), or one that changed
        # nothing (status unchanged), is asked again at once.
        for status in ("error", "unchanged"):
            with self.subTest(status):
                failed = STALLS + rows(
                    (("hearth", "Brug"), "recall", 5, "character is in combat", status)
                )
                self.assertIsNotNone(guildjobs.stranded_recall_step(knight(), failed))

    def test_a_dead_or_offline_knight_waits(self):
        self.assertIsNone(guildjobs.stranded_recall_step(knight(alive=False), STALLS))
        self.assertIsNone(guildjobs.stranded_recall_step(knight(online=False), STALLS))

    def test_a_fighting_knight_still_asks(self):
        # The module refuses the cast for the fight at no cost; the ask that lands
        # is the one in a gap. A stranded knight is almost always in a fight.
        self.assertIsNotNone(
            guildjobs.stranded_recall_step(knight(in_combat=True), STALLS)
        )

    def test_class_step_asks_for_the_recall_even_in_a_fight(self):
        step, _doing, _note = guildjobs.class_step(
            knight(in_combat=True), object(), STALLS, 5000
        )
        self.assertEqual(
            (step.rows[0].kind, step.rows[0].command), ("hearth", "recall")
        )


if __name__ == "__main__":
    unittest.main()
