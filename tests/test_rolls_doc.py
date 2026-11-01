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
import json
import re
import unittest

ROLLS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "ROLLS.md"


def _named_locations(text):
    """Each path, pin key and field the step's location bullets name."""
    step = text.split("**Bump the source pins only**", 1)[1]
    bullets = step.split("source locations move:", 1)[1].split("Check `git status", 1)[0]
    tokens = re.findall(r"`([^`]+)`", bullets)
    return [t for t in tokens if t.endswith("_SHA") or t == '"dev"' or t.endswith((".env", ".py", "/"))]


def _pin_gaps(text, declared):
    """The locations the step names that the declared pins omit."""
    return [name for name in _named_locations(text) if name not in declared]


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

    def test_roll_lock_check_precedes_pre_roll_review(self):
        command = "python3 .github/scripts/wow_bridge_ship.py --check-lock"
        self.assertIn(command, self.text)
        self.assertIn("30-minute", self.text)
        self.assertIn("merged bridge ship", self.text)
        self.assertIn("worldserver pin", self.text)
        self.assertIn("numbered roll", self.text)
        self.assertIn("wait", self.text.lower())
        self.assertLess(
            self.text.index(command), self.text.index("### Pre-roll adversarial review")
        )

    def test_the_ship_and_proof_helpers_are_named(self):
        # #1288: the deploy repo has helpers for the ship (repin and PR body),
        # the proof (when a merge went live, a windowed log report) and the
        # module patch drift guard. An agent with no memory only uses what this
        # file names, so the hand copy-paste path must not come back.
        for helper in ("wow_bridge_ship.py", "live_since.py", "realm-logs.sh report"):
            with self.subTest(helper=helper):
                self.assertTrue(
                    helper in self.text, f"ROLLS.md does not name: {helper!r}"
                )
        bridge_ship = self.text.split("### 1a.", 1)[1].split("### 1b.", 1)[0]
        for kept in ("build.yml", "Pre-roll adversarial review"):
            with self.subTest(kept=kept):
                self.assertTrue(kept in bridge_ship, f"ROLLS.md 1a lost: {kept!r}")

    def test_roll_source_pins_cover_every_location_in_step_two(self):
        blocks = re.findall(r"```loom-roll-pins\s*\n(.*?)\n\s*```", self.text, re.S)
        self.assertEqual(len(blocks), 1, "ROLLS.md must contain exactly one pin block")
        pins = json.loads(blocks[0])
        self.assertIn("deployment_repo", pins)
        self.assertIn("build_workflow", pins)
        sources = pins["sources"]
        declared = json.dumps(sources)
        self.assertEqual(_pin_gaps(self.text, declared), [])

    def test_a_location_dropped_from_the_block_is_a_gap(self):
        named = _named_locations(self.text)
        self.assertIn("AC_OVERSEER_SHA", named)
        self.assertIn(".github/scripts/wow_promotion_drift.py", named)
        self.assertEqual(
            _pin_gaps(self.text, " ".join(set(named) - {"AC_CORE_SHA"})),
            ["AC_CORE_SHA"],
        )


if __name__ == "__main__":
    unittest.main()
