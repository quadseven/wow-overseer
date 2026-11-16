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
        self.assertRegex(PAGE, r"runner is out of scope")

    def test_says_what_a_run_can_and_cannot_prove(self):
        self.assertIn("## What a run can and cannot prove", PAGE)
        self.assertIn("It cannot prove", PAGE)

    def test_says_how_it_complements_fidelity_and_liveproof(self):
        self.assertRegex(
            PAGE, r"## How it complements fidelity \(#2281\) and liveproof \(#2125\)"
        )

    def test_states_what_does_not_ship(self):
        self.assertIn("Not shipped", PAGE)
        self.assertRegex(PAGE, r"no runner")

    def test_does_not_claim_a_world_refuses_anything_yet(self):
        self.assertNotRegex(PAGE, r"a world refuses")
        self.assertNotRegex(PAGE, r"(?i)vacuous pass is impossible")

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
