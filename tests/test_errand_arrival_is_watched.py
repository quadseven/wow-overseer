"""The errand sees the leader arrive instead of sampling it (#1261, #1983).

The worldserver completes a ground aim at the arrival and returns the leader to
its quest drive within seconds. The pass reads positions every 30 seconds, so
the arrival fell between reads and the errand sat in GO for its whole bound.
"""

import asyncio
import pathlib
import unittest

import townerrand as te

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
HUB = {"map_id": 0, "x": 1784.7, "y": -729.1}


def at(x, y):
    return {"map_id": 0, "pos_x": x, "pos_y": y}


def watch(reads):
    """Run the bridge's watch against scripted position reads.

    Returns (arrived, sleeps). A read of None repeats the last one.
    """
    body = BRIDGE[BRIDGE.index("    async def _town_errand_watch_arrival(") :]
    body = body[: body.index("    async def _aim_stranded_bag_pressure_members(")]
    reads = list(reads)
    sleeps = []

    def fetch(_names):
        row = reads.pop(0) if len(reads) > 1 else reads[0]
        return {"Zug": row}

    async def nosleep(seconds):
        sleeps.append(seconds)

    ns = {"asyncio": asyncio, "townerrand": te}
    ns.update(_fetch_fresh_positions=fetch, _nosleep=nosleep)
    exec("class B:\n" + body.replace("asyncio.sleep(", "_nosleep("), ns)
    arrived = asyncio.run(ns["B"]()._town_errand_watch_arrival(HUB, "Zug"))
    return arrived, sleeps


class TheWatch(unittest.TestCase):
    def test_a_leader_near_the_hub_is_watched_and_far_is_not(self):
        self.assertTrue(te.watching_arrival(HUB, at(1900.0, -700.0)))
        self.assertFalse(te.watching_arrival(HUB, at(2974.0, -2675.0)))
        self.assertFalse(te.watching_arrival(HUB, None))

    def test_the_watch_is_bounded_to_one_pass(self):
        self.assertLessEqual(te.ARRIVAL_WATCH_SECONDS, 30.0)
        self.assertGreater(te.ARRIVAL_POLL_SECONDS, 0)


class TheBridgeWatches(unittest.TestCase):
    def test_a_leader_seen_at_the_hub_between_passes_is_arrived(self):
        arrived, sleeps = watch(
            [at(1900.0, -700.0), at(1820.0, -720.0), at(1790.0, -730.0)]
        )
        self.assertTrue(arrived)
        self.assertEqual(2, len(sleeps))

    def test_a_leader_far_away_is_not_waited_for(self):
        arrived, sleeps = watch([at(2974.0, -2675.0)])
        self.assertFalse(arrived)
        self.assertEqual([], sleeps)

    def test_a_leader_that_never_arrives_stops_after_the_bound(self):
        arrived, sleeps = watch([at(1900.0, -700.0)])
        self.assertFalse(arrived)
        self.assertEqual(
            int(te.ARRIVAL_WATCH_SECONDS / te.ARRIVAL_POLL_SECONDS), len(sleeps)
        )

    def test_the_pass_asks_the_watch_in_the_go_phase_only(self):
        once = BRIDGE[BRIDGE.index("    async def _town_errand_once(") :]
        once = once[: once.index("    async def _town_errand_watch_arrival(")]
        self.assertIn("state.phase == townerrand.GO and not leader_at_hub", once)
        self.assertIn("_town_errand_watch_arrival", once)
        self.assertIn("await watch(hub, leader)", once)


if __name__ == "__main__":
    unittest.main()
