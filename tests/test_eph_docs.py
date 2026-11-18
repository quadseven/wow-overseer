"""docs/EPHEMERAL.md meets the ticket's docs criterion and claims only what ships."""

import pathlib
import re
import unittest

PAGE = (
    pathlib.Path(__file__).resolve().parent.parent / "docs" / "EPHEMERAL.md"
).read_text(encoding="utf-8")


class EphemeralDocsTest(unittest.TestCase):
    def test_says_how_to_request_a_run(self):
        self.assertIn("## Requesting a proving run", PAGE)
        self.assertRegex(PAGE, r"## Runner: submit, dispatch, collect")

    def test_says_to_stop_a_dispatcher_with_stop_never_a_pattern_kill(self):
        self.assertIn("dispatch --stop", PAGE)
        self.assertIn("--owner", PAGE)
        self.assertRegex(PAGE, r"(?i)never `?pkill")

    def test_describes_the_judge_and_its_three_verdicts(self):
        self.assertIn("## Judge:", PAGE)
        for word in ("PASS", "FAIL", "INVALID", "eph-result-<run-id>"):
            self.assertIn(word, PAGE)
        self.assertNotRegex(PAGE, r"no judge")

    def test_documents_every_log_bound_the_lint_accepts(self):
        from ephemeral import lint

        for key in lint.LOG_EXACT_KEYS + lint.LOG_RANGE_KEYS:
            self.assertIn("`{%s: N" % key, PAGE, key)

    def test_says_what_a_run_can_and_cannot_prove(self):
        self.assertIn("## What a run can and cannot prove", PAGE)
        self.assertIn("It cannot prove", PAGE)

    def test_says_how_it_complements_fidelity_and_liveproof(self):
        self.assertRegex(
            PAGE, r"## How it complements fidelity \(#2281\) and liveproof \(#2125\)"
        )

    def test_states_what_does_not_ship(self):
        self.assertIn("Not shipped", PAGE)
        self.assertRegex(PAGE, r"has not\s+been run end to end")

    def test_does_not_claim_a_world_refuses_anything_yet(self):
        self.assertNotRegex(PAGE, r"a world refuses")
        self.assertNotRegex(PAGE, r"(?i)vacuous pass is impossible")

    def test_no_merge_markers_and_paths_are_under_data(self):
        self.assertNotRegex(PAGE, r"(?m)^(<<<<<<<|=======|>>>>>>>)")
        self.assertNotRegex(PAGE, r"(?<!data/)decrees/(anchors|<name>|\*)")
        self.assertNotIn(
            "ephemeral/config.example.env",
            PAGE.replace("data/ephemeral/config.example.env", ""),
        )

    def test_no_em_dash(self):
        self.assertNotIn(chr(0x2014), PAGE)
        self.assertIsNone(
            re.search(
                r"[A-Za-z0-9]+#\d+",
                PAGE.replace("#2343", "").replace("#2281", "").replace("#2125", ""),
            )
        )


if __name__ == "__main__":
    unittest.main()
