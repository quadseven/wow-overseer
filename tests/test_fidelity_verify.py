"""The fidelity suite's deriver and verifier (#2281).

Expected claims come from the credited record in the capture, derived by
fidelity/derive.py, which shares no code with the overseer. The verifier
re-derives from the same capture and refuses a fixture whose stored claims
differ. Scenarios are SYNTHETIC machinery tests, not realm captures.
"""

import ast
import copy
import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    from fidelity import derive, fixture, verify
    from test_fidelity_replay import (
        FULL_CLEAR,
        NOT_A_FULL_CLEAR,
        run_row,
        scenario,
    )


class Derive(unittest.TestCase):
    def test_a_run_one_short_is_not_a_clear_whatever_its_outcome_says(self):
        claims = derive.claims(fixture.parse(NOT_A_FULL_CLEAR))
        self.assertEqual(
            claims, {"runs": [{"run": 41, "credited": 18, "of": 19, "clear": False}]}
        )

    def test_every_encounter_credited_on_a_cleared_run_is_a_clear(self):
        claims = derive.claims(fixture.parse(FULL_CLEAR))
        self.assertEqual(
            claims, {"runs": [{"run": 42, "credited": 19, "of": 19, "clear": True}]}
        )

    def test_a_wipe_with_every_encounter_credited_is_no_clear(self):
        doc = scenario([run_row(43, "wiped", 19, 19)], [])
        claims = derive.claims(fixture.parse(doc))
        self.assertFalse(claims["runs"][0]["clear"])

    def test_a_run_with_no_tally_cannot_be_derived(self):
        doc = scenario([run_row(44, "cleared", 0, 19)], [])
        with self.assertRaises(derive.NoCreditedRecord) as caught:
            derive.claims(fixture.parse(doc))
        self.assertIn("run 44", str(caught.exception))

    def test_the_deriver_imports_nothing_from_the_overseer(self):
        tree = ast.parse((HERE / "fidelity" / "derive.py").read_text())
        stdlib = set(sys.stdlib_module_names)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        imported.discard("__future__")
        self.assertEqual(imported - stdlib, set())


class Verify(unittest.TestCase):
    def test_a_fixture_whose_claims_match_its_capture_is_accepted(self):
        self.assertEqual(verify.problems(fixture.parse(NOT_A_FULL_CLEAR)), [])

    def test_a_claim_changed_after_capture_is_refused(self):
        doc = copy.deepcopy(NOT_A_FULL_CLEAR)
        doc["expect"]["runs"][0]["clear"] = True
        problems = verify.problems(fixture.parse(doc))
        self.assertEqual(len(problems), 1)
        self.assertIn("run 41", problems[0])

    def test_a_claim_for_a_run_the_capture_lacks_is_refused(self):
        doc = copy.deepcopy(NOT_A_FULL_CLEAR)
        doc["expect"]["runs"].append(
            {"run": 99, "credited": 19, "of": 19, "clear": True}
        )
        self.assertTrue(verify.problems(fixture.parse(doc)))

    def test_a_capture_with_no_tally_is_refused_not_crashed(self):
        doc = scenario([run_row(44, "cleared", 0, 19)], [])
        problems = verify.problems(fixture.parse(doc))
        self.assertIn("run 44", problems[0])


if __name__ == "__main__":
    unittest.main()
