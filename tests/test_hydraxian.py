import unittest
from pathlib import Path

import hydraxian

BRIDGE = (Path(__file__).resolve().parents[1] / "bridge.py").read_text(encoding="utf-8")


class HydraxianQuestTests(unittest.TestCase):
    def test_take_is_per_member_only_at_the_real_giver_and_never_a_gate(self):
        facts = hydraxian.Facts(
            members=(
                hydraxian.Member("MemberA", 60, 1, 1, 2849.59, -7297.15, 20.3987),
                hydraxian.Member("MemberB", 60, 1, 1, 2850.0, -7297.0, 20.4),
            ),
            quests=(
                hydraxian.Quest(6821, 55, 0, 6805, 13278, 13278),
                hydraxian.Quest(6824, 55, 0, 6823, 13278, 13278),
            ),
            rewarded={"MemberA": {6805}, "MemberB": set()},
            statuses={"MemberA": {}, "MemberB": {}},
            givers={13278: (1, 2849.59, -7297.15, 20.3987)},
        )

        step = hydraxian.step(facts)

        self.assertEqual(step.rows, (("MemberA", "take quest:6821"),))
        self.assertFalse(step.hold_planner)
        self.assertIsNone(step.aim)

    def test_item_started_quest_is_never_fabricated_from_a_missing_npc(self):
        facts = hydraxian.Facts(
            members=(
                hydraxian.Member("MemberA", 60, 1, 1, 2849.59, -7297.15, 20.3987),
            ),
            quests=(hydraxian.Quest(6804, 55, 0, 0, 0, 13278),),
            statuses={"MemberA": {}},
            givers={13278: (1, 2849.59, -7297.15, 20.3987)},
        )

        self.assertEqual(hydraxian.step(facts).rows, ())

    def test_a_completed_quest_is_turned_in_only_for_a_member_at_the_ender(self):
        facts = hydraxian.Facts(
            members=(
                hydraxian.Member("MemberA", 60, 1, 1, 2849.59, -7297.15, 20.3987),
                hydraxian.Member("MemberB", 60, 1, 530, 0, 0, 0),
            ),
            quests=(hydraxian.Quest(6824, 55, 0, 6823, 13278, 13278),),
            statuses={
                "MemberA": {6824: hydraxian.STATUS_COMPLETE},
                "MemberB": {6824: hydraxian.STATUS_COMPLETE},
            },
            givers={13278: (1, 2849.59, -7297.15, 20.3987)},
        )

        self.assertEqual(
            hydraxian.step(facts).rows,
            (("MemberA", "turnin quest:6824"),),
        )


class BridgeWiringTests(unittest.TestCase):
    def test_optional_quest_pass_runs_before_the_planner_without_holding_it(self):
        body = BRIDGE[BRIDGE.index("    async def _plan_campaigns(") :]
        body = body[: body.index("    async def _plan_campaign(")]
        self.assertLess(
            body.index("await self._hydraxian_pass(fams)"),
            body.index("if not campaignplan.enabled():"),
        )
        self.assertIn(
            "for name, command in step.rows:",
            BRIDGE[BRIDGE.index("    async def _hydraxian_pass(") :],
        )


if __name__ == "__main__":
    unittest.main()
