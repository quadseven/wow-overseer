"""docs/ROLLS.md follows the operator ruling of 2026-10-20 (#1285).

ROLLS.md is the procedure agents follow for every hand roll and bridge ship.
Until 2026-10-20 it held a ready roll for an hourly window, for zero family
members inside an instance and for up to 60 minutes of guild runs, and agents
titled their pin PRs "HOLD for window" because of it. The operator removed
those waits: a roll or ship goes out as soon as it is ready, and families and
guild runs restart their runs.

These tests keep the old waits from coming back in a later edit, and keep the
safety checks that still gate a roll in the file.
"""

import pathlib
import unittest

ROLLS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "ROLLS.md"


class RollsDocTest(unittest.TestCase):
    def setUp(self):
        self.text = ROLLS.read_text(encoding="utf-8")

    def test_the_old_waits_are_gone(self):
        for old in (
            "At most one worldserver roll per hour",
            "Never roll while a family member is inside an instance",
            "ONLY inside the window",
            "A bridge ship needs families out of instances",
        ):
            with self.subTest(old=old):
                self.assertFalse(old in self.text, f"ROLLS.md still says: {old!r}")

    def test_the_safety_checks_stay(self):
        for kept in (
            "Pre-roll adversarial review",
            "Rollback",
            "drift check",
            "2026-10-20",
        ):
            with self.subTest(kept=kept):
                self.assertTrue(kept in self.text, f"ROLLS.md lost: {kept!r}")


if __name__ == "__main__":
    unittest.main()
