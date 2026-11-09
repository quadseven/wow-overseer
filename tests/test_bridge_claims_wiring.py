"""The bridge acts on the claims.Claims facade, not on its parts (#1950).

The facade answers why a hold exists, when it expires and which release is
legal. These checks pin that the bridge routes its column slots, bag holds and
ground release through the one instance, so those answers are what it acts on.
"""

import pathlib
import re
import unittest

import claims

SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()


class TheBridgeHoldsOneClaims(unittest.TestCase):
    def test_one_claims_instance_is_built(self):
        self.assertEqual(1, len(re.findall(r"claims\.Claims\(", SOURCE)))

    def test_the_column_slots_come_from_slot_for(self):
        self.assertIn("_CLAIMS.slot_for(", SOURCE)
        self.assertNotIn("claims.new_column_slot", SOURCE)
        self.assertNotIn("_cohort_town_slots", SOURCE)

    def test_the_ground_release_is_not_asked_of_the_free_function(self):
        self.assertNotIn("claims.may_release_ground", SOURCE)
        self.assertIn("_CLAIMS.release_ground(", SOURCE)

    def test_the_bag_hold_is_observed_through_the_facade(self):
        for call in ("member_observe(", "member_released(", "member_stuck("):
            self.assertIn("_CLAIMS." + call, SOURCE)
        self.assertNotIn("bag_pressure.bag_hold_progress(", SOURCE)

    def test_the_hold_why_is_logged_on_a_hold_and_a_release(self):
        self.assertIn("progress.why", SOURCE)
        self.assertIn('"bag hold: released for', SOURCE)

    def test_a_refused_release_logs_its_reason(self):
        fleet = claims.Claims()
        ask = dict(
            aim="at:1:1,2,3", pressure=True, in_run=True,
            ground=lambda aim: aim.startswith("at:"),
        )
        with self.assertLogs(claims.log, level="INFO") as caught:
            release = fleet.release_ground(**ask)
        self.assertFalse(release.legal)
        self.assertIn(release.why, caught.output[0])

    def test_a_legal_release_is_not_logged_as_refused(self):
        fleet = claims.Claims()
        with self.assertNoLogs(claims.log, level="INFO"):
            release = fleet.release_ground(
                aim="at:1:1,2,3", pressure=True, in_run=False,
                ground=lambda aim: aim.startswith("at:"),
            )
        self.assertTrue(release.legal)


class NothingInTheFacadeIsLeftUnused(unittest.TestCase):
    def test_every_public_facade_member_has_a_bridge_caller(self):
        for name in (
            "slot_for", "member_observe", "member_released", "member_stuck",
            "member_hold", "member_restore", "member_reset", "release_ground",
        ):
            self.assertIn("_CLAIMS." + name + "(", SOURCE, name)
        for gone in ("want_column", "busy", "freed_knights"):
            self.assertFalse(hasattr(claims.Claims, gone), gone)
        for gone in ("column_expiry", "release_legal"):
            self.assertFalse(hasattr(claims, gone), gone)


if __name__ == "__main__":
    unittest.main()
