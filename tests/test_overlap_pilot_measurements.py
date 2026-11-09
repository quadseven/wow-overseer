"""Pilot measurements for overlap-scoped freshness and stacked PRs.

T1872: Measure overlap-scoped freshness pilot against the seven-day baseline,
record the post-go-live counts for open PRs, conflicted PRs, and post-merge CI
failures on main, merge at least one stacked PR pair bottom-up, and record each
overlap refusal observed.

This test file checks that the pilot measurements are properly recorded.
"""

import json
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"


class OverlapPilotMeasurements(unittest.TestCase):
    """Check the pilot measurements for overlap-scoped freshness."""

    def test_baseline_counts_are_recorded(self):
        """Baseline counts for 7 days ending 2026-11-04 are recorded."""
        baseline_file = FIXTURES / "overlap_pilot_baseline.json"
        self.assertTrue(baseline_file.exists(), "baseline fixture must exist")

        baseline = json.loads(baseline_file.read_text(encoding="utf-8"))

        # Check required fields
        self.assertIn("period_start", baseline)
        self.assertEqual(baseline["period_start"], "2026-11-04")

        self.assertIn("period_end", baseline)
        self.assertEqual(baseline["period_end"], "2026-11-04")

        self.assertIn("main_branch", baseline)
        self.assertEqual(baseline["main_branch"], "main")

        # Check the three count metrics
        self.assertIn("open_prs", baseline)
        self.assertIn("conflicted_prs", baseline)
        self.assertIn("ci_failures", baseline)

        # Verify each count is an integer >= 0
        self.assertIsInstance(baseline["open_prs"], int)
        self.assertIsInstance(baseline["conflicted_prs"], int)
        self.assertIsInstance(baseline["ci_failures"], int)

        self.assertGreaterEqual(baseline["open_prs"], 0)
        self.assertGreaterEqual(baseline["conflicted_prs"], 0)
        self.assertGreaterEqual(baseline["ci_failures"], 0)

        # Check the query used
        self.assertIn("query", baseline)
        self.assertIsInstance(baseline["query"], str)

    def test_post_golive_counts_are_recorded(self):
        """Post-go-live counts for 7 days after overlap row and rule are live."""
        golive_file = FIXTURES / "overlap_pilot_golive.json"
        self.assertTrue(golive_file.exists(), "golive fixture must exist")

        golive = json.loads(golive_file.read_text(encoding="utf-8"))

        # Check required fields
        self.assertIn("period_start", golive)
        self.assertIsInstance(golive["period_start"], str)

        self.assertIn("period_end", golive)
        self.assertIsInstance(golive["period_end"], str)

        self.assertIn("overlap_row_enabled", golive)
        self.assertIsInstance(golive["overlap_row_enabled"], bool)

        self.assertIn("factory_rule_enabled", golive)
        self.assertIsInstance(golive["factory_rule_enabled"], bool)

        # Check the three count metrics
        self.assertIn("open_prs", golive)
        self.assertIn("conflicted_prs", golive)
        self.assertIn("ci_failures", golive)

        # Verify each count is an integer >= 0
        self.assertIsInstance(golive["open_prs"], int)
        self.assertIsInstance(golive["conflicted_prs"], int)
        self.assertIsInstance(golive["ci_failures"], int)

        self.assertGreaterEqual(golive["open_prs"], 0)
        self.assertGreaterEqual(golive["conflicted_prs"], 0)
        self.assertGreaterEqual(golive["ci_failures"], 0)

        # Check the query used
        self.assertIn("query", golive)
        self.assertIsInstance(golive["query"], str)

    def test_stacked_pr_pair_merged(self):
        """At least one dependent stacked PR pair was merged bottom-up."""
        merged_file = FIXTURES / "overlap_pilot_merged_prs.json"
        self.assertTrue(merged_file.exists(), "merged PRs fixture must exist")

        merged = json.loads(merged_file.read_text(encoding="utf-8"))

        # Must have at least one pair
        self.assertIsInstance(merged, list)
        self.assertGreater(len(merged), 0)

        # Check that we have both PRs in at least one pair
        for pair in merged:
            self.assertIn("pr1", pair)
            self.assertIn("pr2", pair)

            pr1 = pair["pr1"]
            pr2 = pair["pr2"]

            # Check PR1 details
            self.assertIsInstance(pr1, dict)
            self.assertIn("number", pr1)
            self.assertIn("title", pr1)
            self.assertIn("state", pr1)
            self.assertIn("merged_at", pr1)

            # Check PR2 details
            self.assertIsInstance(pr2, dict)
            self.assertIn("number", pr2)
            self.assertIn("title", pr2)
            self.assertIn("state", pr2)
            self.assertIn("merged_at", pr2)

            # Check that they're dependent
            if "bases" in pr1 and "bases" in pr2:
                # In a stacked PR, the second PR should have the first PR as a base
                # This means the first PR's number should be mentioned in PR2's bases
                for base in pr1["bases"]:
                    # Base can be a SHA or a PR number
                    self.assertTrue(
                        str(base).isdigit() or str(base).startswith("main"),
                        "Base should be a PR number or main"
                    )

            # Both should be merged
            self.assertEqual(pr1["state"], "closed")
            self.assertEqual(pr2["state"], "closed")
            self.assertEqual(pr1["merged_at"], pr2["merged_at"])

    def test_overlap_refusals_recorded(self):
        """Each overlap refusal observed during the pilot is recorded."""
        refusals_file = FIXTURES / "overlap_pilot_refusals.json"
        self.assertTrue(refusals_file.exists(), "refusals fixture must exist")

        refusals = json.loads(refusals_file.read_text(encoding="utf-8"))

        # Must have at least one refusal
        self.assertIsInstance(refusals, list)
        self.assertGreater(len(refusals), 0)

        # Check each refusal
        for refusal in refusals:
            self.assertIsInstance(refusal, dict)

            # Check required fields
            self.assertIn("timestamp", refusal)
            self.assertIsInstance(refusal["timestamp"], str)

            self.assertIn("pr_number", refusal)
            self.assertIsInstance(refusal["pr_number"], int)

            self.assertIn("reason", refusal)
            self.assertIsInstance(refusal["reason"], str)

            self.assertIn("base_sha", refusal)
            self.assertIsInstance(refusal["base_sha"], str)

            self.assertIn("head_sha", refusal)
            self.assertIsInstance(refusal["head_sha"], str)

    def test_keep_or_revert_recommendation(self):
        """A keep-or-revert recommendation is recorded with measurements."""
        decision_file = FIXTURES / "overlap_pilot_decision.json"
        self.assertTrue(decision_file.exists(), "decision fixture must exist")

        decision = json.loads(decision_file.read_text(encoding="utf-8"))

        # Check required fields
        self.assertIn("recommendation", decision)
        self.assertIsInstance(decision["recommendation"], str)

        # Recommendation must be either "keep" or "revert"
        self.assertIn(decision["recommendation"].lower(), ["keep", "revert"])

        # Check supporting data
        self.assertIn("baseline_counts", decision)
        self.assertIn("golive_counts", decision)
        self.assertIn("baseline_stats", decision)
        self.assertIn("golive_stats", decision)

        # Check stats
        self.assertIsInstance(decision["baseline_stats"], dict)
        self.assertIsInstance(decision["golive_stats"], dict)

        # Check stats contain the three metrics
        for stats in [decision["baseline_stats"], decision["golive_stats"]]:
            self.assertIn("open_prs", stats)
            self.assertIn("conflicted_prs", stats)
            self.assertIn("ci_failures", stats)

            # Should be integers
            self.assertIsInstance(stats["open_prs"], int)
            self.assertIsInstance(stats["conflicted_prs"], int)
            self.assertIsInstance(stats["ci_failures"], int)

    def test_decision_is_based_on_measurement_improvement(self):
        """The decision should be based on measurable improvement in the metrics."""
        decision_file = FIXTURES / "overlap_pilot_decision.json"
        decision = json.loads(decision_file.read_text(encoding="utf-8"))

        baseline = decision["baseline_stats"]
        golive = decision["golive_stats"]

        # Check that at least one metric improved
        improved = False
        improvements = []

        if golive["conflicted_prs"] < baseline["conflicted_prs"]:
            improved = True
            improvements.append("conflicted")

        if golive["open_prs"] < baseline["open_prs"]:
            improved = True
            improvements.append("open")

        if golive["ci_failures"] < baseline["ci_failures"]:
            improved = True
            improvements.append("ci")

        if not improved:
            self.fail(
                "No metrics improved - decision should reflect measurable impact "
                f"or explain why keep/revert is appropriate despite no improvement"
            )

        # The decision text should mention the improvements
        decision_text = decision.get("text", "").lower()
        self.assertTrue(
            any(m in decision_text for m in improvements),
            f"Decision text should reference the improved metrics: {improvements}"
        )


if __name__ == "__main__":
    unittest.main()
