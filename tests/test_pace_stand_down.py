"""A run the pace itself stood down is not an attempt the door failed (#2334).

The measured cases are the two step-downs of 2026-11-11 and 2026-11-12 on the
dev realm. In each, the third run of the record was one the pace's own
`order_held` row had ended a few minutes after opening it, so the record read
"3 fought, 0 cleared" and the family was stepped off Blackrock Depths.
"""

import pathlib
import unittest
from datetime import datetime, timedelta

import dungeonpace as pace
import dungeonstall

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

BRD = pace.campaignplan.BY_KEYWORD["blackrock-depths"].map_id


def at(day, clock):
    return datetime.fromisoformat("2026-11-%s %s" % (day, clock))


def ledger(outcome, started, ended, map_id=BRD):
    return {
        "map_id": map_id,
        "outcome": outcome,
        "started_at": started,
        "ended_at": ended,
    }


# Grug's family, since the step back to the door at 2026-11-11 21:37Z.
GRUG = [
    ledger("emptied", at("11", "21:53:12"), at("12", "00:00:11")),
    ledger("split_failed", at("12", "00:41:24"), at("12", "01:46:42")),
    ledger("stalled", at("12", "01:46:49"), at("12", "01:47:47")),
    ledger("emptied", at("12", "03:01:42"), at("12", "04:48:54")),
    ledger("left", at("12", "05:53:07"), at("12", "07:51:35")),
]
GRUG_STOOD_DOWN = [at("12", "07:46:51")]

# Zug's family, before the step-down of 2026-11-11 01:25Z.
ZUG = [
    ledger("stalled", at("10", "19:12:10"), at("10", "20:21:26")),
    ledger("left", at("10", "23:16:53"), at("10", "23:23:26")),
    ledger("stalled", at("10", "23:34:06"), at("11", "01:24:08")),
]
ZUG_STOOD_DOWN = [at("10", "23:17:32")]


class ARunThePaceStoodDownIsNotTheDoorsFailure(unittest.TestCase):
    def test_grugs_three_runs_read_three_uncleared_without_the_stand_down(self):
        v = pace.viability(GRUG, BRD)
        self.assertEqual(3, v.fought)
        self.assertEqual(3, v.uncleared_streak)
        self.assertTrue(v.hard)

    def test_the_run_the_order_held_ended_does_not_count(self):
        v = pace.viability(GRUG, BRD, stood_down=GRUG_STOOD_DOWN)
        self.assertEqual(2, v.fought)
        self.assertEqual(2, v.uncleared_streak)
        self.assertFalse(v.hard)
        self.assertTrue(v.clearable)

    def test_the_other_family_reads_the_same(self):
        self.assertTrue(pace.viability(ZUG, BRD).hard)
        v = pace.viability(ZUG, BRD, stood_down=ZUG_STOOD_DOWN)
        self.assertEqual(2, v.fought)
        self.assertEqual(2, v.uncleared_streak)
        self.assertFalse(v.hard)

    def test_the_measured_record_no_longer_steps_the_door_down(self):
        v = pace.viability(GRUG, BRD, stood_down=GRUG_STOOD_DOWN)
        head = {
            "keyword": "blackrock-depths",
            "status": "active",
            "source": "web:overseer",
        }
        facts = pace.Facts(
            family="Grug",
            head=head,
            door="blackrock-depths",
            door_row=head,
            record=v,
            members=(),
            gates=(),
            notes=(),
            open=None,
            changed="",
            done=0,
            cands=(),
        )
        self.assertNotEqual(pace.STEP_DOWN, pace.decide(facts).kind)


class TheEdgesOfTheStandDown(unittest.TestCase):
    def test_a_run_that_ended_before_the_row_still_counts(self):
        late = [at("12", "07:52:00")]
        v = pace.viability(GRUG, BRD, stood_down=late)
        self.assertEqual(3, v.uncleared_streak)

    def test_a_run_that_ended_after_the_hold_window_still_counts(self):
        early = [at("12", "07:51:35") - timedelta(seconds=pace.STAND_DOWN_SECONDS + 1)]
        v = pace.viability(GRUG, BRD, stood_down=early)
        self.assertEqual(3, v.uncleared_streak)

    def test_a_run_that_ended_inside_the_window_edge_does_not_count(self):
        edge = [at("12", "07:51:35") - timedelta(seconds=pace.STAND_DOWN_SECONDS)]
        v = pace.viability(GRUG, BRD, stood_down=edge)
        self.assertEqual(2, v.uncleared_streak)

    def test_a_run_with_no_end_time_counts_as_before(self):
        open_run = dict(GRUG[-1], ended_at=None)
        v = pace.viability(GRUG[:-1] + [open_run], BRD, stood_down=GRUG_STOOD_DOWN)
        self.assertEqual(3, v.uncleared_streak)

    def test_only_a_left_run_is_hidden(self):
        # A stand-down books the run it ends `left`. What the door did, a wipe
        # or a stall that closed inside the window, still counts.
        for outcome in ("wipe", "stalled", "emptied", "complete"):
            run = ledger(outcome, at("12", "07:00:00"), at("12", "07:50:00"))
            v = pace.viability([run], BRD, stood_down=GRUG_STOOD_DOWN)
            self.assertEqual(1, v.fought, outcome)

    def test_no_stand_down_changes_nothing(self):
        for rows in (None, (), []):
            self.assertEqual(
                pace.viability(GRUG, BRD), pace.viability(GRUG, BRD, stood_down=rows)
            )


class TheRowsTheBridgeReads(unittest.TestCase):
    ROWS = [
        {
            "decision": "order_held",
            "door": "blackrock-depths",
            "created_at": at("12", "07:46:51"),
        },
        {
            "decision": "order_held",
            "door": "sunken-temple",
            "created_at": at("12", "09:00:00"),
        },
        {
            "decision": "step_down",
            "door": "blackrock-depths",
            "created_at": at("12", "09:57:24"),
        },
        {"decision": "order_held", "door": "blackrock-depths", "created_at": None},
    ]

    def test_only_the_order_held_rows_of_the_door_are_taken(self):
        self.assertEqual((at("12", "07:46:51"),), pace.stand_downs(self.ROWS, BRD))

    def test_a_door_with_no_map_takes_nothing(self):
        self.assertEqual((), pace.stand_downs(self.ROWS, 0))

    def test_the_decision_is_the_one_the_stall_pass_writes(self):
        self.assertEqual(dungeonstall.ORDER_DECISION, pace.STAND_DOWN_DECISION)

    def test_the_bridge_reads_the_rows_and_hands_them_to_the_record(self):
        body = BRIDGE[BRIDGE.index("def _pace_reads(") :]
        self.assertIn("dungeonpace.STAND_DOWN_SQL", body)
        self.assertIn('"stood_down"', body)
        facts = BRIDGE[BRIDGE.index("    async def _pace_facts(") :]
        self.assertIn(
            'stood_down=dungeonpace.stand_downs(reads["stood_down"], _pace_map(head_kw))',
            facts,
        )

    def test_the_read_is_bounded_to_the_pace_window(self):
        self.assertIn("overseer_dungeon_pace", pace.STAND_DOWN_SQL)
        self.assertIn("order_held", pace.STAND_DOWN_SQL)
        self.assertIn("INTERVAL %s HOUR", pace.STAND_DOWN_SQL)


if __name__ == "__main__":
    unittest.main()
