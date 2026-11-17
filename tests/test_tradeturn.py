"""A family's trade turn between dungeon runs (#2262, part of #2261).

The pure decision: given the last finished run, the recorded turn, the clock,
the setting and the members' trade values, say whether a turn starts, holds,
ends or is skipped, and why. No database, no clock of its own.
"""

import unittest

import classic  # noqa: E402
import townerrand  # noqa: E402
import tradeturn  # noqa: E402

CAP = classic.MAX_PROFESSION_SKILL
SECONDS = 1200
RUN_END = 5000
NOW = 100000.0
LOW = {"Zug": {"Alchemy": 40}, "Oz": {"Cooking": CAP}}
MAXED = {"Zug": {"Alchemy": CAP}, "Oz": {"Cooking": CAP}}


def decide(
    last=RUN_END,
    turn=None,
    now=NOW,
    seconds=SECONDS,
    trades=LOW,
    mid_run=False,
    elapsed=0.0,
):
    return tradeturn.decide(
        last, turn, now, seconds, trades, mid_run, tradeturn.ON_TRADE, elapsed
    )


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
    def turn(self, started=NOW, over=False, run_ended=RUN_END, counted=0.0):
        return tradeturn.Turn(
            run_ended=run_ended, started=started, over=over, counted=counted
        )

    def test_a_turn_holds_for_its_length(self):
        said = decide(turn=self.turn(counted=300), elapsed=0)
        self.assertEqual(tradeturn.HOLD, said.action)
        self.assertEqual(SECONDS - 300, said.remaining)

    def test_a_turn_past_its_length_ends(self):
        said = decide(turn=self.turn(counted=SECONDS - 30), elapsed=30)
        self.assertEqual(tradeturn.END, said.action)

    def test_a_restart_resumes_the_same_turn_with_its_remaining_time(self):
        recorded = self.turn(counted=1000)
        again = decide(turn=recorded, elapsed=60)
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


class TheTurnCountsOnlyTradeTime(unittest.TestCase):
    TOWN = 600

    def live(self, **kw):
        return tradeturn.Turn(run_ended=RUN_END, started=NOW, **kw)

    def step(self, turn, kind, elapsed, now=NOW):
        return tradeturn.decide(
            RUN_END, turn, now, SECONDS, LOW, False, kind, elapsed, self.TOWN
        )

    def test_passes_off_a_trade_job_do_not_advance_the_counted_time(self):
        turn = self.live()
        for i in range(1, 6):
            said = self.step(turn, tradeturn.OTHER, 100, now=NOW + 100 * i)
            self.assertEqual(tradeturn.HOLD, said.action)
            turn = said.turn
        self.assertEqual(0, turn.counted)
        self.assertEqual(500, turn.off)

    def test_a_turn_spent_wholly_in_a_town_errand_has_not_ended_at_the_setting(self):
        said = self.step(self.live(), tradeturn.TOWN, 599, now=NOW + SECONDS)
        self.assertNotEqual(tradeturn.END, said.action)
        self.assertEqual(0, said.turn.counted)

    def test_the_allowance_spent_in_a_town_errand_releases_it_exactly_once(self):
        said = self.step(self.live(off=550), tradeturn.TOWN, 60)
        self.assertEqual(tradeturn.RELEASE, said.action)
        self.assertEqual(600, said.turn.off)
        self.assertEqual(10, said.turn.counted)
        again = self.step(said.turn, tradeturn.TOWN, 30)
        self.assertEqual(tradeturn.HOLD, again.action)
        self.assertEqual(40, again.turn.counted)

    def test_an_errand_that_left_its_town_run_behind_ends_the_turn(self):
        said = self.step(self.live(off=30), tradeturn.ERRAND_DONE, 30)
        self.assertEqual(tradeturn.END, said.action)
        self.assertTrue(said.turn.over)

    def test_job_kind_reads_a_left_behind_town_run_as_errand_done(self):
        trade = ("craft", "gather")
        kind = lambda job, active, src: tradeturn.job_kind(  # noqa: E731
            job, trade, active, src, "errand", "town run"
        )
        self.assertEqual(tradeturn.ERRAND_DONE, kind("town run", False, "errand"))
        self.assertEqual(tradeturn.TOWN, kind("town run", True, "errand"))
        self.assertEqual(tradeturn.TOWN, kind("town run", False, "other"))
        self.assertEqual(tradeturn.ON_TRADE, kind("craft", False, "errand"))
        self.assertEqual(tradeturn.OTHER, kind("quest", False, "errand"))

    def test_a_real_errand_still_reads_another_job_as_town(self):
        trade = ("craft", "gather")
        kind = tradeturn.job_kind("quest", trade, True, "errand", "errand", "town run")
        self.assertEqual(tradeturn.TOWN, kind)

    def test_the_errand_lock_never_turns_another_job_into_town(self):
        trade = ("craft", "gather")
        for job in ("quest", "dungeon:ragefire"):
            kind = tradeturn.job_kind(
                job, trade, False, "errand", "errand", "town run", True
            )
            self.assertEqual(tradeturn.OTHER, kind, job)
        held = tradeturn.job_kind(
            "town run", trade, False, "errand", "errand", "town run", True
        )
        self.assertEqual(tradeturn.TOWN, held)

    def test_a_dungeon_job_spending_the_allowance_does_not_release(self):
        said = self.step(self.live(off=590), tradeturn.OTHER, 60)
        self.assertEqual(tradeturn.HOLD, said.action)

    def test_a_turn_wholly_on_a_trade_job_ends_at_the_setting(self):
        turn = self.live(counted=SECONDS - 30)
        self.assertEqual(tradeturn.HOLD, self.step(turn, tradeturn.ON_TRADE, 20).action)
        said = self.step(turn, tradeturn.ON_TRADE, 30)
        self.assertEqual(tradeturn.END, said.action)
        self.assertTrue(said.turn.over)

    def test_the_queue_is_never_held_past_the_setting_plus_the_allowance(self):
        # Worst case: a town errand holds the family at every pass, even after
        # the release. Passes arrive every 30 seconds.
        turn, wall, gap = self.live(), 0, 30
        while True:
            wall += gap
            said = self.step(turn, tradeturn.TOWN, gap, now=NOW + wall)
            turn = said.turn
            if said.action == tradeturn.END:
                break
        self.assertLessEqual(wall, SECONDS + self.TOWN + gap)
        self.assertGreater(wall, SECONDS)

    def test_the_wall_bound_holds_when_the_leader_alternates_jobs(self):
        turn, wall, gap, i = self.live(), 0, 45, 0
        kinds = [tradeturn.OTHER, tradeturn.ON_TRADE, tradeturn.TOWN]
        while True:
            wall += gap
            said = self.step(turn, kinds[i % 3], gap, now=NOW + wall)
            i += 1
            turn = said.turn
            if said.action == tradeturn.END:
                break
        self.assertLessEqual(wall, SECONDS + self.TOWN + gap)

    def test_an_allowance_of_zero_releases_at_the_first_town_pass(self):
        said = tradeturn.decide(
            RUN_END, self.live(), NOW, SECONDS, LOW, False, tradeturn.TOWN, 30, 0
        )
        self.assertEqual(tradeturn.RELEASE, said.action)

    def test_the_trade_changes_name_each_trade_below_the_cap(self):
        before = {"Zug": {"Alchemy": 40, "Cooking": CAP}, "Oz": {"Mining": 100}}
        after = {"Zug": {"Alchemy": 55, "Cooking": CAP}, "Oz": {"Mining": 100}}
        self.assertEqual(
            ["Oz Mining 100->100", "Zug Alchemy 40->55"],
            tradeturn.trade_changes(before, after),
        )

    def test_the_allowance_reads_like_the_turn_length(self):
        self.assertEqual(2400, tradeturn.town_seconds(None))
        self.assertEqual(90, tradeturn.town_seconds("90"))
        self.assertEqual(0, tradeturn.town_seconds("-1"))
        self.assertEqual(2400, tradeturn.town_seconds("soon"))


class TheAllowanceOutlastsAnErrandsSale(unittest.TestCase):
    """A turn that frees a family before its errand sold leaves the bags full."""

    def test_an_errand_that_used_its_whole_walk_and_wait_still_sells(self):
        through_the_sale = (
            townerrand.GO_SECONDS
            + townerrand.GATHER_SECONDS
            + townerrand.STEP_SECONDS[townerrand.VENDOR]
        )
        self.assertGreaterEqual(tradeturn.DEFAULT_TOWN_SECONDS, through_the_sale)

    def test_the_allowance_stays_inside_the_campaign_hold_ceiling(self):
        self.assertLessEqual(
            tradeturn.DEFAULT_TOWN_SECONDS, townerrand.HOLD_CEILING_SECONDS
        )


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
