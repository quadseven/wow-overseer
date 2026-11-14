"""The shared retry gate (retrygate.py): a refused step is not asked at full rate.

The rows below are synthetic, shaped like the command log's own: a walk
refused every two minutes as standing outside the classic world, a shop walk
refused in combat many times in a row, a vendor walk refused for the other
side's ground, and craft casts that came back "character is moving" or
`unchanged`.
"""

import json
import pathlib
import re
import unittest

import retrygate

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")

OUTSIDE = "character stands in Outland or Northrend, outside the classic world"


def row(status, age, reason="", **flags):
    result = {"outcome": "refused" if status == "error" else "x", "reason": reason}
    result.update(flags)
    return {"status": status, "age": age, "result": json.dumps(result)}


def combat(age):
    return row("error", age, "character is in combat", retryable=True, transient=True)


def other_side(age):
    return row(
        "error",
        age,
        "the way to the nearest vendor crosses the other side's ground",
        retryable=False,
        transient=False,
    )


class ReadingARow(unittest.TestCase):
    def test_the_module_flags_are_read(self):
        t = retrygate.tried(combat(3))
        self.assertTrue(t.failed)
        self.assertEqual(t.reason, "character is in combat")
        self.assertFalse(retrygate.permanent(t))

    def test_retryable_false_or_retry_false_is_permanent(self):
        self.assertTrue(retrygate.permanent(retrygate.tried(other_side(1))))
        crossing = row("error", 1, "no transport the module knows sails", retry=False)
        self.assertTrue(retrygate.permanent(retrygate.tried(crossing)))

    def test_the_classic_gate_is_permanent_though_the_module_says_retryable(self):
        outside = row("error", 1, OUTSIDE, retryable=True, transient=False)
        self.assertTrue(retrygate.permanent(retrygate.tried(outside)))

    def test_later_and_unknown_are_transient(self):
        moving = row("error", 1, "character is moving", retry="later")
        self.assertFalse(retrygate.permanent(retrygate.tried(moving)))
        self.assertFalse(retrygate.permanent(retrygate.tried(row("error", 1, "?"))))

    def test_unchanged_counts_as_a_failure_and_pending_does_not(self):
        nothing = row(
            "unchanged",
            1,
            "the cast went out and it cost the character nothing",
            retry="later",
        )
        self.assertTrue(retrygate.tried(nothing).failed)
        self.assertFalse(retrygate.tried({"status": "pending", "age": 0}).failed)
        self.assertFalse(retrygate.tried({"status": "applied", "age": 0}).failed)

    def test_a_result_that_is_not_json_is_a_transient_failure(self):
        t = retrygate.tried({"status": "error", "age": 2, "result": "boom"})
        self.assertTrue(t.failed)
        self.assertFalse(retrygate.permanent(t))


class TransientRefusalsBackOff(unittest.TestCase):
    def test_one_fresh_failure_waits_the_base(self):
        hold = retrygate.hold([combat(1)])
        self.assertIsNotNone(hold)
        self.assertEqual(hold.kind, retrygate.BACKOFF)
        self.assertEqual(hold.failures, 1)
        self.assertEqual(hold.minutes_left, retrygate.BASE_MINUTES - 1)

    def test_the_wait_doubles_with_each_failure_in_a_row(self):
        rows = [combat(2), combat(9), combat(20)]
        hold = retrygate.hold(rows)
        self.assertEqual(hold.failures, 3)
        self.assertEqual(hold.minutes_left, retrygate.BASE_MINUTES * 4 - 2)

    def test_a_wait_that_has_passed_holds_nothing(self):
        self.assertIsNone(retrygate.hold([combat(retrygate.BASE_MINUTES)]))
        rows = [combat(retrygate.BASE_MINUTES * 2), combat(60)]
        self.assertIsNone(retrygate.hold(rows))

    def test_a_success_ends_the_run(self):
        rows = [combat(1), {"status": "applied", "age": 3}, combat(5), combat(9)]
        self.assertEqual(retrygate.hold(rows).failures, 1)
        self.assertIsNone(
            retrygate.hold([{"status": "delivered", "age": 0}, combat(1)])
        )

    def test_it_gives_up_after_n_and_holds_the_long_wait(self):
        """A shop walk refused "in combat" many times in a row."""
        rows = [combat(1 + 3 * i) for i in range(73)]
        hold = retrygate.hold(rows)
        self.assertEqual(hold.kind, retrygate.GAVE_UP)
        self.assertEqual(hold.failures, retrygate.GIVE_UP_AFTER)
        self.assertEqual(hold.minutes_left, retrygate.GIVE_UP_MINUTES - 1)

    def test_rows_arrive_in_any_order(self):
        rows = [combat(20), combat(2), combat(9)]
        self.assertEqual(
            retrygate.hold(rows).minutes_left, retrygate.BASE_MINUTES * 4 - 2
        )

    def test_the_moving_cast_backs_off_and_unchanged_casts_give_up(self):
        """Casts refused "moving" are not asked again at once, and a
        craft whose rows keep coming back `unchanged` stops after a few."""
        moving = [row("error", 1, "character is moving", retry="later")]
        self.assertEqual(retrygate.hold(moving).kind, retrygate.BACKOFF)
        nothing = [
            row(
                "unchanged",
                1 + 15 * i,
                "the cast went out and it cost the character nothing",
            )
            for i in range(retrygate.GIVE_UP_AFTER)
        ]
        self.assertEqual(retrygate.hold(nothing).kind, retrygate.GAVE_UP)


class AMisShapedAgeIsNotACrash(unittest.TestCase):
    def test_a_non_numeric_age_reads_as_just_now(self):
        for age in ("2024-01-01 00:00:00", object(), None, ""):
            t = retrygate.tried({"status": "error", "age": age})
            self.assertEqual(t.age_minutes, 0)
        self.assertEqual(
            retrygate.hold([{"status": "error", "age": "x"}]).kind, retrygate.BACKOFF
        )


class PermanentRefusalsStop(unittest.TestCase):
    def test_an_outside_walk_is_asked_a_few_times_a_day_not_hundreds(self):
        """A walk asked every cycle and always refused outside the classic world."""
        rows = [
            row("error", 2 * i, OUTSIDE, retryable=True, transient=False)
            for i in range(1, 700)
        ]
        hold = retrygate.hold(rows)
        self.assertEqual(hold.kind, retrygate.PERMANENT)
        self.assertEqual(hold.minutes_left, retrygate.PERMANENT_MINUTES - 2)
        # Replayed over a day at the planner's two minute cycle, the gate lets
        # through one ask per PERMANENT_MINUTES.
        asked, history = 0, []
        for minute in range(0, 24 * 60, 2):
            aged = [dict(r, age=minute - r["at"]) for r in history]
            if retrygate.hold(aged) is None:
                asked += 1
                history.insert(
                    0,
                    {
                        "status": "error",
                        "at": minute,
                        "result": json.dumps({"reason": OUTSIDE}),
                    },
                )
        self.assertLessEqual(asked, 24 * 60 // retrygate.PERMANENT_MINUTES + 1)
        self.assertLess(asked, 50)

    def test_the_other_sides_ground_stops_the_loop_at_once(self):
        hold = retrygate.hold([other_side(4)])
        self.assertEqual(hold.kind, retrygate.PERMANENT)
        self.assertEqual(hold.failures, 1)

    def test_the_newest_reason_decides(self):
        rows = [combat(1), other_side(30)]
        self.assertEqual(retrygate.hold(rows).kind, retrygate.BACKOFF)


class TheWalkCap(unittest.TestCase):
    """(d) The hourly far walk cap is hit by retries of the same failing walk.
    A failing walk now waits 5, 10, 20, 40 minutes and then gives up, so it
    asks at most GIVE_UP_AFTER times before the long wait, not every cycle."""

    def test_a_failing_walk_asks_at_most_a_handful_of_times_an_hour(self):
        asked, history = 0, []
        lethal = json.dumps(
            {
                "reason": "the road to the spawn crosses ground far above its level",
                "retryable": True,
                "transient": False,
            }
        )
        for minute in range(0, 60, 2):
            aged = [dict(r, age=minute - r["at"]) for r in history]
            if retrygate.hold(aged) is None:
                asked += 1
                history.insert(0, {"status": "error", "at": minute, "result": lethal})
        self.assertLessEqual(asked, 4)


class TheLine(unittest.TestCase):
    def test_the_line_names_the_member_the_step_and_why(self):
        hold = retrygate.hold([other_side(4)])
        line = hold.line("Walker", "guildjobs:room-walk:Walker")
        self.assertIn("Walker", line)
        self.assertIn("guildjobs:room-walk:Walker", line)
        self.assertIn("other side's ground", line)
        self.assertIn("stops", line)
        self.assertEqual(
            hold.key("Walker", "guildjobs:room-walk:Walker"),
            (
                "Walker",
                "guildjobs:room-walk:Walker",
                retrygate.PERMANENT,
                "the way to the nearest vendor crosses the other side's ground",
            ),
        )

    def test_a_backoff_line_says_how_many_and_how_long(self):
        line = retrygate.hold([combat(1), combat(6)]).line(
            "Shopper", "guildcorps:shop-walk:6260"
        )
        self.assertIn("2 refusal(s) in a row", line)
        self.assertIn("in combat", line)


class TheBridgeAsksTheGate(unittest.TestCase):
    """Both step runners, the guild jobs' (with the questers') and the corps'
    (with the raid supply's), ask the gate before they write a step's first
    row, through one helper."""

    def body(self, name):
        start = BRIDGE.index("def %s(" % name)
        ends = [
            e
            for e in (
                BRIDGE.find("\n    async def ", start + 1),
                BRIDGE.find("\n    def ", start + 1),
                BRIDGE.find("\ndef ", start + 1),
            )
            if e > 0
        ]
        return BRIDGE[start : min(ends)]

    def test_each_runner_asks_before_its_first_write(self):
        for runner, prefix in (
            ("_run_job_step", "guild jobs"),
            ("_run_corps_step", "guild corps"),
        ):
            body = self.body(runner)
            asked = body.index('await self._retry_held("%s", step)' % prefix)
            self.assertLess(asked, body.index("_insert_corps_row"), runner)

    def test_the_helper_reads_the_step_s_own_rows_and_logs_once_per_state(self):
        helper = self.body("_retry_held")
        self.assertIn("retrygate.first_source(step)", helper)
        self.assertIn("_retry_rows", helper)
        self.assertIn("retrygate.hold(", helper)
        self.assertIn("hold.key(", helper)
        read = self.body("_retry_rows")
        self.assertIn("_RETRY_ROWS_SQL", read)
        sql = re.search(r"_RETRY_ROWS_SQL = \((.*?)\n\)", BRIDGE, re.S).group(1)
        self.assertIn("WHERE source = %s AND target_name = %s", sql)
        self.assertIn("ORDER BY id DESC LIMIT %s", sql)

    def test_the_first_source_is_the_walk_s_then_the_first_row_s(self):
        class R:
            def __init__(self, source):
                self.source = source

        class S:
            def __init__(self, walk, rows):
                self.walk, self.rows = walk, rows

        self.assertEqual(retrygate.first_source(S(R("a-walk"), (R("b"),))), "a-walk")
        self.assertEqual(retrygate.first_source(S(None, (R("b"), R("c")))), "b")
        self.assertEqual(retrygate.first_source(S(None, ())), "")


if __name__ == "__main__":
    unittest.main()
