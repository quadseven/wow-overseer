"""The dungeon quest pass says it walks the family only when the walk is taken.

On wow-dev (2026-09-28) "dungeon quests: Zug's family: walk the family to
dungeon quest giver 3665 to turn in" was logged every minute for an hour
while the town slot answered "gave up '3665' ... does not ask for it again
for 1800s". The family was not walking anywhere.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import campaignqueue  # noqa: E402
import dungeonquests  # noqa: E402


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()
WALK = dungeonquests.Step(
    dungeonquests.GO,
    "walk the family to dungeon quest giver 3665 to turn in",
    hold_planner=True,
    aim=3665,
    giver=3665,
)


class _Pass:
    def __init__(self, granted):
        self.granted = granted

    async def _mid_run(self, names):
        return False

    async def _claim_town_slot(self, claimant, leader, aim, cohort=None):
        return self.granted


def run_pass(granted):
    fam = {"leader": {"name": "Zug"}, "names": ["Zug", "Oz"]}
    rows = [{"status": campaignqueue.QUEUED, "keyword": "ragefire"}]
    with (
        mock.patch.object(bridge, "_dungeonquest_facts", lambda *a: None),
        mock.patch.object(bridge.dungeonquests, "step", lambda facts: WALK),
        mock.patch.object(bridge.log, "info") as info,
    ):
        held = asyncio.run(
            bridge.Bridge._dungeonquest_for_family(
                _Pass(granted), "Zug", fam, rows, "Zug"
            )
        )
    said = [c.args[0] % c.args[1:] for c in info.call_args_list]
    return held, said


class RefusedWalkTest(unittest.TestCase):
    def test_a_refused_walk_is_not_said(self):
        held, said = run_pass(False)
        self.assertFalse(held)
        self.assertFalse([s for s in said if "walk the family" in s], said)

    def test_a_taken_walk_is_said(self):
        held, said = run_pass(True)
        self.assertTrue(held)
        self.assertTrue([s for s in said if "walk the family" in s], said)


if __name__ == "__main__":
    unittest.main()
