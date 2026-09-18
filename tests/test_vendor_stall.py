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
    return rest[:match.start() + 1] if match else rest


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

    def test_no_pressure_is_held(self):
        self.assertEqual(self.decide(pressure=False).action, vendor_stall.HOLD)

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

    def test_new_module_is_copied_into_the_image(self):
        dockerfile = (PACKAGE.parent.parent / "docker" / "wow-overseer"
                      / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("_shared/vendor_stall.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
