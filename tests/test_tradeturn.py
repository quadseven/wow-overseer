"""A family's trade turn between dungeon runs (#2262, part of #2261).

The pure decision: given the last finished run, the recorded turn, the clock,
the setting and the members' trade values, say whether a turn starts, holds,
ends or is skipped, and why. No database, no clock of its own.
"""

import unittest

import classic  # noqa: E402
import tradeturn  # noqa: E402

CAP = classic.MAX_PROFESSION_SKILL
SECONDS = 1200
RUN_END = 5000
NOW = 100000.0
LOW = {"Zug": {"Alchemy": 40}, "Oz": {"Cooking": CAP}}
MAXED = {"Zug": {"Alchemy": CAP}, "Oz": {"Cooking": CAP}}


def decide(
    last=RUN_END, turn=None, now=NOW, seconds=SECONDS, trades=LOW, mid_run=False
):
    return tradeturn.decide(last, turn, now, seconds, trades, mid_run)


class TheTurnStarts(unittest.TestCase):
    def test_a_finished_run_with_a_trade_below_the_cap_starts_a_turn(self):
        said = decide()
        self.assertEqual(tradeturn.START, said.action)
        self.assertIn("Alchemy", said.reason)

    def test_no_run_has_finished_so_nothing_happens(self):
        self.assertEqual(tradeturn.NONE, decide(last=None).action)

    def test_a_run_in_progress_is_never_interrupted(self):
        said = decide(mid_run=True)
        self.assertEqual(tradeturn.NONE, said.action)
        self.assertIn("in progress", said.reason)

    def test_every_trade_at_the_cap_skips_with_its_reason(self):
        said = decide(trades=MAXED)
        self.assertEqual(tradeturn.SKIP, said.action)
        self.assertIn("cap", said.reason)

    def test_a_family_with_no_trades_skips(self):
        self.assertEqual(tradeturn.SKIP, decide(trades={"Zug": {}}).action)

    def test_a_setting_of_zero_skips_with_its_reason(self):
        said = decide(seconds=0)
        self.assertEqual(tradeturn.SKIP, said.action)
        self.assertIn("TRADE_TURN_SECONDS", said.reason)


class TheTurnRuns(unittest.TestCase):
    def turn(self, started=NOW, over=False, run_ended=RUN_END):
        return tradeturn.Turn(run_ended=run_ended, started=started, over=over)

    def test_a_turn_holds_for_its_length(self):
        said = decide(turn=self.turn(started=NOW - 300))
        self.assertEqual(tradeturn.HOLD, said.action)
        self.assertEqual(SECONDS - 300, said.remaining)

    def test_a_turn_past_its_length_ends(self):
        said = decide(turn=self.turn(started=NOW - SECONDS))
        self.assertEqual(tradeturn.END, said.action)

    def test_a_restart_resumes_the_same_turn_with_its_remaining_time(self):
        recorded = self.turn(started=NOW - 1000)
        again = decide(turn=recorded, now=NOW + 60)
        self.assertEqual(tradeturn.HOLD, again.action)
        self.assertEqual(SECONDS - 1060, again.remaining)

    def test_a_turn_is_judged_by_itself_not_by_a_later_run_row(self):
        """A run row that flips to ended during the turn does not start a
        second one."""
        said = decide(last=RUN_END + 5, turn=self.turn(started=NOW - 10))
        self.assertEqual(tradeturn.HOLD, said.action)

    def test_a_turn_over_a_zero_setting_ends(self):
        said = decide(turn=self.turn(started=NOW - 10), seconds=0)
        self.assertEqual(tradeturn.END, said.action)

    def test_a_second_turn_waits_for_another_run_to_end(self):
        done = self.turn(started=NOW - 5000, over=True)
        self.assertEqual(tradeturn.NONE, decide(turn=done).action)

    def test_another_run_ending_allows_the_next_turn(self):
        done = self.turn(started=NOW - 5000, over=True)
        said = decide(last=RUN_END + 700, turn=done)
        self.assertEqual(tradeturn.START, said.action)

    def test_a_skipped_run_is_recorded_over_and_is_not_skipped_again(self):
        skipped = self.turn(over=True)
        self.assertEqual(tradeturn.NONE, decide(turn=skipped, trades=MAXED).action)


class TheSetting(unittest.TestCase):
    def test_the_default_is_twenty_minutes(self):
        self.assertEqual(1200, tradeturn.seconds(None))
        self.assertEqual(1200, tradeturn.seconds(""))

    def test_zero_turns_the_rule_off(self):
        self.assertEqual(0, tradeturn.seconds("0"))

    def test_a_value_is_read_as_whole_seconds(self):
        self.assertEqual(600, tradeturn.seconds("600"))

    def test_junk_or_a_negative_value_falls_back_safely(self):
        self.assertEqual(1200, tradeturn.seconds("soon"))
        self.assertEqual(0, tradeturn.seconds("-5"))


class TheLowTrades(unittest.TestCase):
    def test_names_each_member_and_trade_below_the_cap(self):
        low = tradeturn.below_cap(
            {"Zug": {"Alchemy": 40, "Cooking": CAP}, "Oz": {"Mining": 299}}
        )
        self.assertEqual([("Oz", "Mining", 299), ("Zug", "Alchemy", 40)], low)


if __name__ == "__main__":
    unittest.main()
