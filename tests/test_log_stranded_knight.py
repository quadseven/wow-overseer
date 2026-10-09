"""The bridge says what it decided for a stranded death knight, every pass (2026-10-08).

Cave's Brug went 35 minutes after a hearth recall with no step and nothing in
the log said why. bridge.py is read as text by the tests, as for the other
bridge-only seams.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


class TheStrandedLine(unittest.TestCase):
    def body(self):
        return BRIDGE.split("def _log_stranded_knights", 1)[1].split("\n    def ", 1)[0]

    def test_the_plan_log_calls_it(self):
        called = BRIDGE.split("def _log_guild_job_plan", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("self._log_stranded_knights(members, plan)", called)

    def test_the_plan_log_names_a_stranded_knight(self):
        body = self.body()
        self.assertIn("classquest.DEATH_KNIGHT_START_MAP", body)
        self.assertIn("guild jobs: stranded %s", body)

    def test_it_says_the_plan_line_the_steps_and_the_notes(self):
        body = self.body()
        for word in ("plan.lines.get(m.name", "plan.steps", "plan.notes", "free slots"):
            self.assertIn(word, body)


if __name__ == "__main__":
    unittest.main()
