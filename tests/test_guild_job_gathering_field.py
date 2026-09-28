"""A guild member's own gathering skills reach gatheraim in the family shape.

On wow-dev (2026-09-28) every guild jobs pass for the Bonkers cohort died with
`AttributeError: 'int' object has no attribute 'items'` in
gatheraim.strongest_gatherers: `_gathering_field` handed gatheraim one member's
{skill: value}, and gatheraim reads {character: {skill: value}}. So as soon as
one natural maintenance member learned mining or herbalism, the whole pass for
its guild raised and no job, trade or post started for anybody in it.

This drives the real `Bridge._gathering_field` with the survey and the danger
reading stubbed, so it fails on the old shape and passes on the new one.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import gatheraim  # noqa: E402
import gatherband  # noqa: E402
import guildjobs  # noqa: E402


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


def miner():
    return guildjobs.Member(
        name="Kurgan",
        guild="Bonkers",
        role=guildjobs.MAINTENANCE,
        level=12,
        class_id=1,
        race=2,
        online=True,
        map_id=1,
        x=1000.0,
        y=-4000.0,
        money=0,
        eligible=True,
        skills={guildjobs.MINING: (1, 75)},
    )


class _Pass:
    """Just the attributes `_gathering_field` reads off the bridge."""

    def __init__(self):
        self.danger_asked = []

    async def _gathering_zone_levels(self, candidates):
        self.danger_asked.extend(candidates)
        return {c.zone_id: 10 for c in candidates}


class GatheringFieldTest(unittest.TestCase):
    def test_a_members_own_skills_choose_a_field_instead_of_raising(self):
        m = miner()
        skills = bridge._guild_gathering_skills(m)
        self.assertEqual(skills, {"mining": 1})
        lock = gatherband.reachable_locks("mining", 1)[0]
        node = gatheraim.Spawn(
            map_id=1, zone_id=14, x=1100.0, y=-4000.0, z=10.0,
            lock_id=lock, name="Copper Vein", guid=4242)
        seen = {}

        def survey(map_id, locks):
            seen["locks"] = locks
            return [node]

        this = _Pass()
        with mock.patch.object(bridge, "_survey_job_nodes", survey):
            spot = asyncio.run(
                bridge.Bridge._gathering_field(this, m, skills, {}))

        self.assertIn(lock, seen["locks"])
        self.assertIsNotNone(spot)
        self.assertEqual(spot.spawn, 4242)
        self.assertEqual(spot.kind, "gameobject")
        self.assertTrue(this.danger_asked)


if __name__ == "__main__":
    unittest.main()
