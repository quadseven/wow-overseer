"""A raid door recalls a member's errand of its own (Refs #1261).

A family ordered into a raid walks to the door on a `raid:<keyword>` job. The
stall breaker returned at once for a raid head, and the door verdict only read
families on a dungeon job, so the recall that hands a member's economy errand
back (#2280) never ran for a raid. The member's errand held the leader's walk
to the door: the dungeon run's walk ended, a town trip or a walk back for the
member took over, and the door walk began again, with nothing to end it.
"""

import ast
import unittest

import dungeonstall as stall
import test_errand_recall_loop as loop

RAID_HEAD = {"id": 9, "keyword": "ubrs", "status": "active"}


class RaidWorld(loop.World):
    def namespace(self, strict=False):
        ns = super().namespace(strict)
        ns["_jobs_of"] = lambda names: {n: "raid:ubrs" for n in names}
        ns["raidrun"] = __import__("raidrun")
        return ns

    def judge(self, ns):
        return ns["_door_wedge"](dict(RAID_HEAD), ["Zug", "Oz"], "Zug")


class ARaidDoorRecallsAMembersErrand(unittest.TestCase):
    def test_the_errand_is_handed_back_after_the_recall_bound(self):
        world = RaidWorld()
        ns = world.namespace()
        world.aims["Oz"] = "vendor"
        self.assertIsNone(world.judge(ns))
        self.assertEqual([], world.released)
        world.clock[0] += stall.RECALL_SECONDS
        self.assertIsNone(world.judge(ns))
        self.assertEqual([("Oz", "vendor")], world.released)

    def test_a_raid_door_is_never_left_however_long_the_errand_runs(self):
        world = RaidWorld()
        ns = world.namespace()
        world.aims["Oz"] = "vendor"
        for _ in range(3 * stall.HOLD_SECONDS // 60):
            world.clock[0] += 60
            self.assertIsNone(world.judge(ns))
            world.aims["Oz"] = "vendor"

    def test_the_recall_is_not_repeated_inside_the_cooldown(self):
        world = RaidWorld()
        ns = world.namespace()
        world.aims["Oz"] = "vendor"
        world.judge(ns)
        world.clock[0] += stall.RECALL_SECONDS
        world.judge(ns)
        world.clock[0] += 30
        self.assertFalse(world.ask(ns, "bank", "banker"))
        self.assertEqual([], world.writes)

    def test_the_breaker_asks_the_door_verdict_for_a_raid_head(self):
        fn = loop.FUNCTIONS["_stall_breaker"]
        first = next(
            n
            for n in fn.body
            if isinstance(n, ast.If) and "is_raid" in ast.unparse(n.test)
        )
        self.assertIn("_door_wedge", ast.unparse(first))


if __name__ == "__main__":
    unittest.main()
