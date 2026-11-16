"""The decision rule: close only on control 3 of 3 FAIL and treatment 3 of 3 PASS."""

import unittest

from ephemeral import decide

SHA = "f" * 64


def record(control=3, treatment=3, presence=("absent", "present")):
    runs = []
    for n in range(1, max(control, treatment) + 1):
        if n <= control:
            runs.append({"run_id": f"abc123-c{n}", "arm": "control", "n": n})
        if n <= treatment:
            runs.append({"run_id": f"abc123-t{n}", "arm": "treatment", "n": n})
    wanted = {}
    if control:
        wanted["control"] = control
    if treatment:
        wanted["treatment"] = treatment
    pres = {}
    if control:
        pres["control"] = {"state": presence[0], "pin": "p"}
    if treatment:
        pres["treatment"] = {"state": presence[1], "pin": "q"}
    return {"decree_sha256": SHA, "runs": runs, "runs_wanted": wanted, "presence": pres}


def results(rec, **by_arm):
    out = {}
    for r in rec["runs"]:
        v = by_arm.get(r["arm"])
        if isinstance(v, list):
            v = v[r["n"] - 1]
        if v is not None:
            out[r["run_id"]] = {"verdict": v, "decree_sha256": SHA}
    return out


class DecideTest(unittest.TestCase):
    def outcome(self, rec, res):
        return decide.decide(rec, res)["outcome"]

    def test_three_of_three_each_way_is_proven(self):
        rec = record()
        d = decide.decide(rec, results(rec, control="FAIL", treatment="PASS"))
        self.assertEqual(d["outcome"], "proven")
        self.assertIn("p = 1/20", d["statistics"])

    def test_two_of_three_is_not_enough(self):
        rec = record()
        res = results(rec, control="FAIL", treatment=["PASS", "PASS", None])
        self.assertEqual(self.outcome(rec, res), "pending")

    def test_a_valid_treatment_fail_is_disproven(self):
        rec = record()
        res = results(rec, control="FAIL", treatment=["PASS", "FAIL", "PASS"])
        self.assertEqual(self.outcome(rec, res), "disproven")

    def test_treatment_fail_is_disproven_on_the_first_pair_alone(self):
        rec = record()
        res = results(rec, control=["FAIL", None, None], treatment=["FAIL", None, None])
        self.assertEqual(self.outcome(rec, res), "disproven")

    def test_a_passing_control_is_non_discriminating(self):
        rec = record()
        res = results(rec, control=["PASS", None, None], treatment=["PASS", None, None])
        self.assertEqual(self.outcome(rec, res), "non-discriminating")

    def test_a_late_passing_control_is_non_discriminating_never_proven(self):
        rec = record()
        res = results(rec, control=["FAIL", "PASS", "FAIL"], treatment="PASS")
        self.assertEqual(self.outcome(rec, res), "non-discriminating")

    def test_invalid_never_proves(self):
        rec = record()
        res = results(rec, control=["FAIL", "INVALID", "FAIL"], treatment="PASS")
        d = decide.decide(rec, res)
        self.assertEqual(d["outcome"], "unclear")
        self.assertIn("INVALID", d["reason"])

    def test_invalid_first_pair_is_unclear(self):
        rec = record()
        res = results(
            rec, control=["INVALID", None, None], treatment=["PASS", None, None]
        )
        self.assertEqual(self.outcome(rec, res), "unclear")

    def test_treatment_only_pass_is_uncontrolled_and_never_proven(self):
        rec = record(control=0)
        self.assertEqual(
            self.outcome(rec, results(rec, treatment="PASS")), "pass-uncontrolled"
        )

    def test_pass_with_every_control_invalid_is_uncontrolled(self):
        rec = record()
        res = results(rec, control="INVALID", treatment="PASS")
        self.assertEqual(self.outcome(rec, res), "pass-uncontrolled")

    def test_unchecked_fix_presence_cannot_prove_or_disprove(self):
        rec = record(presence=("unchecked", "unchecked"))
        self.assertEqual(
            self.outcome(rec, results(rec, control="FAIL", treatment="PASS")), "unclear"
        )
        self.assertEqual(
            self.outcome(rec, results(rec, control="FAIL", treatment="FAIL")), "unclear"
        )

    def test_a_result_for_another_decree_text_is_invalid(self):
        rec = record()
        res = results(rec, control="FAIL", treatment="PASS")
        res["abc123-t2"]["decree_sha256"] = "0" * 64
        self.assertEqual(self.outcome(rec, res), "unclear")

    def test_no_results_yet_is_pending(self):
        self.assertEqual(self.outcome(record(), {}), "pending")


class FisherTest(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(decide.fisher_p(3, 3, 0, 3), 1 / 20)
        self.assertAlmostEqual(decide.fisher_p(4, 4, 0, 4), 1 / 70)
        self.assertAlmostEqual(decide.fisher_p(5, 5, 0, 5), 1 / 252)

    def test_no_difference_is_one(self):
        self.assertEqual(decide.fisher_p(0, 3, 0, 3), 1.0)


class TickTest(unittest.TestCase):
    BODY = "- [ ] unit tests\n- [ ] Live: the family leaves the bar without a patron dying\n- [x] done\n"

    def test_ticks_the_criterion_and_live_boxes_only(self):
        body, n = decide.tick_boxes(
            self.BODY, "the family leaves the bar without a patron dying"
        )
        self.assertEqual(n, 1)
        self.assertIn("- [ ] unit tests", body)
        self.assertIn("- [x] Live: the family leaves", body)
        self.assertEqual(decide.unticked(body), 1)

    def test_a_body_without_matching_boxes_is_unchanged(self):
        body, n = decide.tick_boxes("- [ ] other\n", "nothing like it")
        self.assertEqual((body, n), ("- [ ] other\n", 0))


class StatisticsDisplayTest(unittest.TestCase):
    def test_a_non_reciprocal_p_prints_as_a_decimal(self):
        line = decide.statistics_line(
            [("control", "FAIL")] * 3
            + [("treatment", "FAIL")] * 2
            + [("treatment", "PASS")] * 2
        )
        self.assertIn("p = 0.", line)
        self.assertNotIn("p = 1/", line)

    def test_a_tiny_exact_reciprocal_still_prints_as_one_over_n(self):
        line = decide.statistics_line(
            [("control", "FAIL")] * 20 + [("treatment", "PASS")] * 20
        )
        self.assertIn("p = 1/137846528820", line)


class ExactlyThreeTest(unittest.TestCase):
    def test_one_of_one_each_way_never_proves(self):
        rec = record(control=1, treatment=1)
        d = decide.decide(rec, results(rec, control="FAIL", treatment="PASS"))
        self.assertEqual(d["outcome"], "underpowered")
        self.assertNotEqual(d["outcome"], "proven")

    def test_two_of_two_and_four_of_four_do_not_prove_either(self):
        for n in (2, 4):
            rec = record(control=n, treatment=n)
            d = decide.decide(rec, results(rec, control="FAIL", treatment="PASS"))
            self.assertEqual(d["outcome"], "underpowered", n)

    def test_uneven_arms_do_not_prove(self):
        rec = record(control=3, treatment=2)
        d = decide.decide(rec, results(rec, control="FAIL", treatment="PASS"))
        self.assertEqual(d["outcome"], "underpowered")

    def test_a_small_decree_still_disproves_on_a_treatment_fail(self):
        rec = record(control=1, treatment=1)
        d = decide.decide(rec, results(rec, control="FAIL", treatment="FAIL"))
        self.assertEqual(d["outcome"], "disproven")


if __name__ == "__main__":
    unittest.main()
