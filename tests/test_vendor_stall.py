import unittest
import pathlib
import re

import vendor_stall

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PACKAGE / "bridge.py"


def _source():
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature):
    source = _source()
    start = source.index(signature)
    rest = source[start:]
    match = re.search(r"\n {0,3}(?:async )?def |\n {0,3}class ", rest[1:])
    return rest[: match.start() + 1] if match else rest


class VendorStallDecisionTests(unittest.TestCase):
    def decide(self, **changes):
        values = dict(
            pressure=True,
            at_counter=False,
            sales_outstanding=0,
            movement_readable=True,
            movement_progressed=False,
            stalled_seconds=vendor_stall.STALL_AFTER_SECONDS,
        )
        values.update(changes)
        return vendor_stall.decide(**values)

    def test_progressing_trip_is_held(self):
        self.assertEqual(
            self.decide(movement_progressed=True).action,
            vendor_stall.HOLD,
        )

    def test_stalled_pressured_trip_is_released(self):
        decision = self.decide()
        self.assertEqual(decision.action, vendor_stall.RELEASE)
        self.assertIn("bounded", decision.reason)

    def test_two_hour_bag_wait_yields_a_progressing_trip(self):
        decision = self.decide(
            movement_progressed=True,
            bag_wait_seconds=vendor_stall.MAX_BAG_WAIT_SECONDS,
        )
        self.assertEqual(decision.action, vendor_stall.YIELD)
        self.assertIn("bag room not freed", decision.reason)

    def test_bag_wait_yield_waits_until_two_hours(self):
        decision = self.decide(
            movement_progressed=True,
            bag_wait_seconds=vendor_stall.MAX_BAG_WAIT_SECONDS - 1,
        )
        self.assertEqual(decision.action, vendor_stall.HOLD)

    def test_no_pressure_is_held(self):
        self.assertEqual(self.decide(pressure=False).action, vendor_stall.HOLD)

    def test_leader_idle_at_counter_with_far_sellers_yields_within_the_wait_trip(self):
        # #1261: the leader reached the vendor, no sale is queued because the
        # sellers are held 3,500+ yards away with their range retries spent.
        held = self.decide(
            at_counter=True,
            bag_wait_seconds=vendor_stall.MAX_IDLE_COUNTER_SECONDS - 1,
        )
        self.assertEqual(held.action, vendor_stall.HOLD)
        yielded = self.decide(
            at_counter=True,
            bag_wait_seconds=vendor_stall.MAX_IDLE_COUNTER_SECONDS,
        )
        self.assertEqual(yielded.action, vendor_stall.YIELD)
        self.assertLessEqual(vendor_stall.MAX_IDLE_COUNTER_SECONDS, 30 * 60)

    def test_far_held_sellers_do_not_keep_the_leader_at_the_counter(self):
        # #1261, driven as the bridge drives it: the sellers stand 3,500 and
        # 5,500 yards from the leader and the module holds them as too far to
        # walk, so they are not watched as a split family, the leader idles at
        # the counter with no sale queued, and the wait trip yields the column.
        names = ("Grug", "Ugga", "Zork")
        rows = {
            "Grug": {"map_id": 1, "pos_x": 0, "pos_y": 0},
            "Ugga": {"map_id": 1, "pos_x": 3500, "pos_y": 0},
            "Zork": {"map_id": 1, "pos_x": 5500, "pos_y": 0},
        }
        states = {"Ugga": "held too far to walk", "Zork": "held too far to walk"}
        watched = vendor_stall.following(names, states)
        self.assertEqual(watched, ("Grug",))
        family = vendor_stall.family_progress(None, rows, watched, 10.0)
        self.assertFalse(family.split)
        everyone = vendor_stall.family_progress(None, rows, names, 10.0)
        self.assertTrue(everyone.split)
        decision = self.decide(
            at_counter=True,
            family_readable=family.readable,
            family_split=family.split,
            bag_wait_seconds=vendor_stall.MAX_IDLE_COUNTER_SECONDS,
        )
        self.assertEqual(decision.action, vendor_stall.YIELD)
        self.assertIn("held sellers rejoin", decision.reason)

    def test_counter_with_sales_outstanding_is_never_yielded(self):
        decision = self.decide(
            at_counter=True,
            sales_outstanding=2,
            bag_wait_seconds=vendor_stall.MAX_BAG_WAIT_SECONDS,
        )
        self.assertEqual(decision.action, vendor_stall.HOLD)

    def test_arrival_at_counter_is_held(self):
        self.assertEqual(self.decide(at_counter=True).action, vendor_stall.HOLD)

    def test_outstanding_sale_is_held(self):
        self.assertEqual(
            self.decide(sales_outstanding=1).action,
            vendor_stall.HOLD,
        )

    def test_unreadable_state_is_held(self):
        self.assertEqual(
            self.decide(movement_readable=False).action,
            vendor_stall.HOLD,
        )

    def test_stall_window_is_bounded(self):
        self.assertEqual(
            self.decide(stalled_seconds=vendor_stall.STALL_AFTER_SECONDS - 1).action,
            vendor_stall.HOLD,
        )

    def test_persistent_split_releases_when_leader_is_still_moving(self):
        decision = self.decide(
            movement_progressed=True,
            family_readable=True,
            family_split=True,
            family_progressed=False,
            family_split_seconds=vendor_stall.STALL_AFTER_SECONDS,
        )
        self.assertEqual(decision.action, vendor_stall.RELEASE)
        self.assertIn("family split", decision.reason)

    def test_split_that_is_regrouping_before_threshold_is_held(self):
        self.assertEqual(
            self.decide(
                movement_progressed=True,
                family_readable=True,
                family_split=True,
                family_progressed=True,
                family_split_seconds=vendor_stall.STALL_AFTER_SECONDS - 1,
            ).action,
            vendor_stall.HOLD,
        )

    def test_unreadable_family_does_not_release_split(self):
        self.assertEqual(
            self.decide(
                movement_progressed=True,
                family_readable=False,
                family_split=True,
                family_progressed=False,
                family_split_seconds=vendor_stall.STALL_AFTER_SECONDS + 1,
            ).action,
            vendor_stall.HOLD,
        )


class MovementTests(unittest.TestCase):
    def test_first_read_is_progress(self):
        result = vendor_stall.progress(None, (0, 1, 2, 3), 10.0)
        self.assertTrue(result.readable)
        self.assertTrue(result.progressed)
        self.assertEqual(result.stalled_seconds, 0.0)

    def test_stationary_reads_accumulate_stall_time(self):
        first = vendor_stall.progress(None, (0, 1, 2, 3), 10.0)
        result = vendor_stall.progress(first.current, (0, 1, 2, 3), 1210.0)
        self.assertFalse(result.progressed)
        self.assertEqual(result.stalled_seconds, 1200.0)

    def test_map_change_counts_as_progress(self):
        first = vendor_stall.progress(None, (0, 1, 2, 3), 10.0)
        result = vendor_stall.progress(first.current, (1, 1, 2, 3), 1210.0)
        self.assertTrue(result.progressed)
        self.assertEqual(result.stalled_seconds, 0.0)

    def test_unreadable_position_does_not_release(self):
        result = vendor_stall.progress(None, None, 10.0)
        self.assertFalse(result.readable)
        self.assertFalse(result.progressed)

    def _rows(self, far=False):
        return {
            "Grug": {"map_id": 0, "pos_x": 0, "pos_y": 0},
            "Ugga": {"map_id": 0, "pos_x": 150 if far else 10, "pos_y": 0},
        }

    def test_family_is_cohesive_within_radius(self):
        result = vendor_stall.family_progress(
            None,
            self._rows(),
            ("Grug", "Ugga"),
            10.0,
        )
        self.assertTrue(result.readable)
        self.assertFalse(result.split)

    def test_family_split_clock_accumulates_when_stationary(self):
        first = vendor_stall.family_progress(
            None,
            self._rows(far=True),
            ("Grug", "Ugga"),
            10.0,
        )
        result = vendor_stall.family_progress(
            first.current,
            self._rows(far=True),
            ("Grug", "Ugga"),
            1210.0,
        )
        self.assertTrue(result.split)
        self.assertFalse(result.progressed)
        self.assertEqual(result.split_seconds, 1200.0)

    def test_family_split_progress_keeps_split_clock(self):
        first = vendor_stall.family_progress(
            None,
            self._rows(far=True),
            ("Grug", "Ugga"),
            10.0,
        )
        result = vendor_stall.family_progress(
            first.current,
            {
                "Grug": {"map_id": 0, "pos_x": 1, "pos_y": 0},
                "Ugga": {"map_id": 0, "pos_x": 151, "pos_y": 0},
            },
            ("Grug", "Ugga"),
            1210.0,
        )
        self.assertTrue(result.progressed)
        self.assertEqual(result.split_seconds, 1200.0)

    def test_family_regrouping_resets_split_clock(self):
        first = vendor_stall.family_progress(
            None,
            self._rows(far=True),
            ("Grug", "Ugga"),
            10.0,
        )
        result = vendor_stall.family_progress(
            first.current,
            {
                "Grug": {"map_id": 0, "pos_x": 0, "pos_y": 0},
                "Ugga": {"map_id": 0, "pos_x": 10, "pos_y": 0},
            },
            ("Grug", "Ugga"),
            1210.0,
        )
        self.assertFalse(result.split)
        self.assertEqual(result.split_seconds, 0.0)

    def test_missing_family_member_is_unreadable(self):
        result = vendor_stall.family_progress(
            None,
            self._rows(),
            ("Grug", "Ugga", "Og"),
            10.0,
        )
        self.assertFalse(result.readable)


class BridgeIntegrationTests(unittest.TestCase):
    def test_snapshot_reader_guards_missing_tables_and_columns(self):
        source = _block("def _fetch_vendor_position(")
        self.assertIn("overseer_snapshot", _source())
        self.assertIn("(1054, 1146)", source)

    def test_recovery_is_before_the_existing_vendor_settlement(self):
        source = _block("    async def _settle_vendor_errand(")
        self.assertIn("vendor_stall.decide(", source)
        self.assertIn('_release_trade_errand, leader, "vendor"', source)
        self.assertIn("stall_seconds", source)
        self.assertIn("free_slots", source)
        self.assertIn("family_progress", source)
        self.assertIn("_fetch_positions, names", source)

    def test_new_module_is_copied_into_the_image(self):
        dockerfile = (PACKAGE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("vendor_stall.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
