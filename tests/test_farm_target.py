"""Per-member farm targets and the individual gate on the farm pass (#2498)."""

import pathlib
import unittest

import farmjob
import individual

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = {individual.ENV: "Grug"}


class TheMemberTargetIsItsOwn(unittest.TestCase):
    def test_a_miner_is_sent_mining(self):
        self.assertEqual(
            farmjob.target_for({"mining": 28, "blacksmithing": 23}), "farm:mining"
        )

    def test_a_herbalist_is_sent_herbalism(self):
        self.assertEqual(
            farmjob.target_for({"herbalism": 199, "alchemy": 84}), "farm:herbalism"
        )

    def test_a_member_with_two_gathering_trades_takes_the_lower(self):
        self.assertEqual(
            farmjob.target_for({"mining": 150, "herbalism": 20}), "farm:herbalism"
        )

    def test_a_trade_with_nothing_left_to_give_is_passed_over(self):
        self.assertEqual(
            farmjob.target_for({"mining": 900, "herbalism": 20}), "farm:herbalism"
        )
        self.assertEqual(farmjob.target_for({"mining": 900}), "")

    def test_a_member_with_no_gathering_trade_has_no_target(self):
        self.assertEqual(farmjob.target_for({"skinning": 14, "leatherworking": 57}), "")
        self.assertEqual(farmjob.target_for({"tailoring": 155}), "")
        self.assertEqual(farmjob.target_for(None), "")


class TheFarmPassJudgesTheLeadersGroup(unittest.TestCase):
    JOBS = {"Grug": "farm:mining", "Ugga": "farm:herbalism", "Og": "quest"}

    def test_an_individual_family_keeps_the_leaders_farm_group(self):
        got = individual.farm_cohort(self.JOBS, "Grug", "Grug", environ=ENV)
        self.assertEqual(got, {"Grug": "farm:mining"})

    def test_without_a_farming_leader_the_first_group_by_name_is_kept(self):
        got = individual.farm_cohort(self.JOBS, "Og", "Grug", environ=ENV)
        self.assertEqual(got, {"Grug": "farm:mining"})

    def test_members_sharing_the_leaders_job_stay_together(self):
        jobs_ = {"Grug": "farm:mining", "Grog": "farm:mining", "Ugga": "farm:herbalism"}
        got = individual.farm_cohort(jobs_, "Grug", "Grug", environ=ENV)
        self.assertEqual(got, {"Grug": "farm:mining", "Grog": "farm:mining"})

    def test_a_linked_family_keeps_the_old_rule(self):
        jobs_ = dict(self.JOBS, Og="dungeon")
        self.assertEqual(
            individual.farm_cohort(jobs_, "Grug", "Grug", environ=ENV), jobs_
        )

    def test_a_family_not_named_keeps_the_old_rule(self):
        self.assertEqual(
            individual.farm_cohort(self.JOBS, "Grug", "Grug", environ={}), self.JOBS
        )

    def test_no_farm_job_at_all_leaves_the_rows_alone(self):
        rows = {"Grug": "quest", "Og": "craft"}
        self.assertEqual(
            individual.farm_cohort(rows, "Grug", "Grug", environ=ENV), rows
        )


class TheBridgeAsksTheGate(unittest.TestCase):
    def test_farm_job_now_uses_the_individual_gate_before_the_split_check(self):
        text = (ROOT / "bridge.py").read_text(encoding="utf-8")
        start = text.index("    async def _farm_job_now(")
        body = text[start : text.index("    async def _farm_state_for(")]
        self.assertIn("individual.farm_cohort(", body)
        self.assertLess(
            body.index("individual.farm_cohort("), body.index("is split across jobs")
        )


if __name__ == "__main__":
    unittest.main()
