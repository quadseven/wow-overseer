"""A gathering walk yields to full bags and stays near the leader (#170).

Measured on wow-dev 2026-09-22 18:30-18:36 UTC: the gather drive aimed Grug
(level 60, Winterspring, 3 of 64 bag slots free) at copper in The Barrens,
8208 yards away. The aim held the travel column on a 450 second lease, the
module refused his vendor trip 33 times in five minutes, and the guild bank
and craft passes queued behind it. In the same day a share refused for
eligibility was re-sent every hour.
"""

import json
import pathlib
import re
import unittest

import bag_pressure
import gatheraim
import questshare

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

COPPER = 38  # mining, band 0
PEACEBLOOM = 29  # herbalism, band 0
EARTHROOT = 30  # herbalism, band 15
LIVE_SKILLS = {
    "Grug": {"mining": 8},
    "Grog": {"mining": 1},
    "Ugga": {"herbalism": 134},
    "Bork": {"skinning": 12},
}
WINTERSPRING = (6700.0, -4500.0)  # where the leader stood, map 1


def spawn(zone, lock, x=0.0, y=0.0, map_id=1):
    return gatheraim.Spawn(map_id=map_id, zone_id=zone, x=x, y=y, z=0.0, lock_id=lock)


class FullBagsComeFirst(unittest.TestCase):
    def test_the_measured_leader_blocks_the_walk(self):
        """Grug at 3 free slots of 64: the vendor trip's own trigger."""
        why = gatheraim.bags_block_gathering({"Grug": 3, "Ugga": 20})
        self.assertIn("Grug", why)
        self.assertIn("yields the travel column", why)

    def test_room_for_everybody_lets_it_go(self):
        self.assertEqual(gatheraim.bags_block_gathering({"Grug": 4, "Ugga": 20}), "")

    def test_an_unreadable_family_does_not_walk(self):
        self.assertTrue(gatheraim.bags_block_gathering({}))
        self.assertTrue(gatheraim.bags_block_gathering({"Grug": None}))

    def test_the_trigger_is_the_vendor_trips_own(self):
        """Two numbers for "cannot loot" would leave a gap in which neither
        the walk nor the vendor trip moves."""
        self.assertEqual(
            gatheraim.GATHER_MIN_FREE_SLOTS, bag_pressure.TOWN_RUN_FREE_SLOTS
        )


class TheFieldIsNearTheLeader(unittest.TestCase):
    def choose(self, rows, levels, family_level=60, origin=WINTERSPRING):
        return gatheraim.choose(
            skills=LIVE_SKILLS,
            standing_on=1,
            spawns=rows,
            family_level=family_level,
            zone_levels=levels,
            origin=origin,
        )

    def test_the_barrens_from_winterspring_is_refused(self):
        barrens = [spawn(17, COPPER, x=-1175.1, y=-2532.8) for _ in range(194)]
        got = self.choose(barrens, {17: 25})
        self.assertIsNone(got.chosen)
        self.assertIn("within %d yards" % int(gatheraim.MAX_YARDS), got.refused)
        self.assertIn("nearest is 8", got.refused)

    def test_without_an_origin_the_old_ranking_still_answers(self):
        barrens = [spawn(17, COPPER, x=-1175.1, y=-2532.8) for _ in range(5)]
        got = self.choose(barrens, {17: 25}, origin=None)
        self.assertEqual(got.chosen.zone_id, 17)

    def test_a_near_thin_field_beats_a_far_dense_one(self):
        near = [spawn(618, COPPER, x=6900.0, y=-4500.0)] * 3
        far = [spawn(16, COPPER, x=6700.0, y=-2000.0)] * 40
        got = self.choose(near + far, {618: 58, 16: 58})
        self.assertEqual(got.chosen.zone_id, 618)

    def test_some_gatherers_band_counts_not_only_the_weakest(self):
        """No copper near the leader, but Ugga's herbalism opens Earthroot."""
        herbs = [spawn(618, EARTHROOT, x=6800.0, y=-4400.0)] * 4
        got = self.choose(herbs, {618: 58})
        self.assertEqual(got.chosen.zone_id, 618)
        self.assertEqual(got.chosen.skill_name, "herbalism")

    def test_a_zone_far_below_the_family_loses_to_one_near_its_level(self):
        low = [spawn(141, COPPER, x=6750.0, y=-4500.0)] * 30
        level = [spawn(618, PEACEBLOOM, x=7500.0, y=-4500.0)] * 3
        got = self.choose(low + level, {141: 12, 618: 58})
        self.assertEqual(got.chosen.zone_id, 618)

    def test_a_low_zone_is_still_taken_when_it_is_the_only_one(self):
        low = [spawn(141, COPPER, x=6750.0, y=-4500.0)] * 30
        got = self.choose(low, {141: 12})
        self.assertEqual(got.chosen.zone_id, 141)


class AnIneligibleShareBacksOff(unittest.TestCase):
    KEY = ("Bork", "Ugga", "quest:4861")

    def test_one_eligibility_refusal_holds_the_share(self):
        result = json.dumps(
            {
                "outcome": "refused",
                "reason": "taker is not eligible (level, race, class, "
                "prerequisite or exclusive group)",
            }
        )
        rows = [(*self.KEY, "error", result, 60)]
        self.assertEqual(questshare.backed_off(rows, 60, 168), frozenset({self.KEY}))


def _statements(signature: str) -> str:
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    body = rest[: match.start() + 1] if match else rest
    if body.count('"""') >= 2:
        body = body.split('"""', 2)[2]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


class TheBridgeWiresIt(unittest.TestCase):
    def test_full_bags_are_asked_before_the_slot(self):
        body = _statements("    async def _walk_to_gather_field(")
        self.assertIn("gatheraim.bags_block_gathering(", body)
        self.assertLess(
            body.index("bags_block_gathering"), body.index("_claim_town_slot(")
        )
        self.assertLess(
            body.index("await self._yield_gather_aim("),
            body.index("_claim_town_slot("),
        )

    def test_only_the_gather_passes_own_aim_is_handed_back(self):
        body = _statements("    async def _yield_gather_aim(")
        self.assertIn("holder.claimant != GATHER_CLAIMANT", body)
        self.assertIn("column != holder.aim", body)
        self.assertIn("_release_trade_errand, holder.character, holder.aim", body)

    def test_the_destination_is_measured_from_the_leader(self):
        body = _statements("    async def _gather_destination(")
        self.assertIn("gatheraim.near_fields(", body)
        self.assertIn("origin=origin", body)
        self.assertIn("gatheraim.strongest_gatherers(skills)", body)


if __name__ == "__main__":
    unittest.main()
