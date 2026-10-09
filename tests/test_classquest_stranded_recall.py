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

    def test_the_plan_lets_a_recall_through_a_fight_and_nothing_else(self):
        # The step was chosen in a fight (#689) and then dropped by the plan's
        # own combat refusal: the live log said 'Brug is in combat' (2026-10-08).
        recall = guildjobs.stranded_recall_step(knight(in_combat=True), STALLS)
        other = guildjobs.hearth_step(knight(in_combat=True))
        self.assertEqual(
            guildjobs._step_refusal(knight(in_combat=True), set(), {}, 6, recall), ""
        )
        self.assertIn(
            "in combat",
            guildjobs._step_refusal(knight(in_combat=True), set(), {}, 6, other),
        )
        self.assertIn(
            "in combat", guildjobs._step_refusal(knight(in_combat=True), set(), {}, 6)
        )

    def test_a_recall_still_waits_for_the_other_refusals(self):
        recall = guildjobs.stranded_recall_step(knight(), STALLS)
        self.assertIn(
            "already on another",
            guildjobs._step_refusal(knight(), {"Brug"}, {}, 6, recall),
        )

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


class TheAskingAgain(unittest.TestCase):
    """A stranded knight fights almost without a pause (2026-10-08)."""

    def test_the_row_is_recognised(self):
        self.assertTrue(guildjobs.is_recall_row("recall"))
        self.assertTrue(guildjobs.is_recall_row(" recall "))
        self.assertFalse(guildjobs.is_recall_row("use"))

    def test_a_fight_a_move_or_a_cast_that_never_started_is_asked_again(self):
        for status, detail in (
            ("error", "character is in combat"),
            ("error", "character is moving"),
            ("unchanged", "the cast never started and the character never left"),
            ("error", "character is already casting"),
        ):
            with self.subTest(detail):
                self.assertTrue(guildjobs.recall_again(status, detail))

    def test_a_cast_that_went_through_or_any_other_refusal_ends_the_asking(self):
        self.assertFalse(guildjobs.recall_again("applied", ""))
        self.assertFalse(guildjobs.recall_again("delivered", ""))
        self.assertFalse(
            guildjobs.recall_again("error", "character carries a hearthstone; use it")
        )
        self.assertFalse(
            guildjobs.recall_again(
                "error", "home is where the character already stands"
            )
        )
        self.assertFalse(guildjobs.recall_again("", ""))


class TheBridgeAsksAgain(unittest.TestCase):
    """`Bridge._recall_row` driven with the row writes and answers stubbed."""

    ROW = guildjobs.guildcorps.Row("hearth", "recall", "", "guildjobs:stranded:Brug")
    STEP = guildjobs.guildcorps.Step("Brug", "recall", 0, "goes home", rows=(ROW,))

    def drive(self, answers):
        import asyncio
        from unittest import mock

        from test_guildsocial_bridge import bridge

        asked, slept = [], []
        queue = list(answers)

        def insert(holder, row):
            asked.append(row.command)
            return len(asked)

        async def answer(row_id, seconds):
            return queue.pop(0) if queue else {}

        async def nap(seconds):
            slept.append(seconds)

        this = type("B", (), {"_await_corps_answer": staticmethod(answer)})()
        with (
            mock.patch.object(bridge, "_insert_corps_row", insert),
            mock.patch.object(bridge.asyncio, "sleep", nap),
        ):
            went = asyncio.run(bridge.Bridge._recall_row(this, self.STEP, self.ROW))
        return went, asked, slept

    def test_a_fight_then_a_gap_asks_twice_and_goes_home(self):
        went, asked, slept = self.drive(
            [
                {"status": "error", "detail": "the character is in combat"},
                {"status": "applied", "detail": "went home"},
            ]
        )
        self.assertTrue(went)
        self.assertEqual(asked, ["recall", "recall"])
        self.assertEqual(slept, [guildjobs.RECALL_ASK_SECONDS])

    def test_an_answer_that_will_not_change_is_asked_once(self):
        went, asked, slept = self.drive(
            [
                {
                    "status": "error",
                    "detail": "home is where the character already stands",
                }
            ]
        )
        self.assertFalse(went)
        self.assertEqual(len(asked), 1)
        self.assertEqual(slept, [])

    def test_a_stubborn_fight_stops_at_the_attempt_cap(self):
        fight = {"status": "error", "detail": "the character is in combat"}
        went, asked, _ = self.drive([fight] * 50)
        self.assertFalse(went)
        self.assertEqual(len(asked), guildjobs.RECALL_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
