"""Fishing can resume for eligible members when other bags are tight (#3053)."""

import asyncio
import unittest
from unittest.mock import AsyncMock

import jev_activity as activity
from test_jev_activity import FakeFamily, FakeJev, _bridge, _family


class FishingFamily(FakeFamily):
    def reads(self, names, leader):
        return {
            **super().reads(names, leader),
            "pole_holders": {"Zug", "Oz", "Uzza", "Zrog"},
            "fishing": [
                {"name": "Zug", "value": 25, "max": 75},
                {"name": "Oz", "value": 48, "max": 75},
                {"name": "Uzza", "value": 49, "max": 75},
                {"name": "Zork", "value": 4, "max": 75},
                {"name": "Zrog", "value": 75, "max": 75},
            ],
        }


class FishingJobResumes(unittest.TestCase):
    def test_due_break_sends_the_eligible_member_when_other_bags_are_tight(self):
        world = FishingFamily(
            {"Zug": 0, "Oz": 7, "Uzza": 12, "Zork": 13, "Zrog": 14}, job="quest"
        )
        fam = _family()
        fam["leader"]["job"] = "quest"
        bridge, _ = _bridge(world, lambda *_: (503, b""))
        bridge._activity_can = AsyncMock(return_value=(False, False))

        asyncio.run(bridge._activity_for("Zug", fam, [], True, activity.policy({})))

        self.assertEqual([("Uzza", "fish", activity.SOURCE)], world.jobs)

        _, kind, fishers = bridge._activity_restore["Zug"]
        bridge._activity_restore["Zug"] = (0.0, kind, fishers)
        world.jobs.clear()

        asyncio.run(bridge._activity_for("Zug", fam, [], True, activity.policy({})))

        self.assertEqual([("Uzza", "quest", activity.SOURCE)], world.jobs)

    def test_another_family_still_needs_room_in_every_bag(self):
        world = FishingFamily({"Zug": 0, "Uzza": 12}, job="quest")
        fam = _family()
        fam["leader"]["job"] = "quest"
        bridge, _ = _bridge(world, lambda *_: (503, b""))

        asyncio.run(bridge._activity_for("Zug", fam, [], False, activity.policy({})))

        self.assertEqual(1, len(world.records))
        self.assertEqual([], world.jobs)

    def test_restart_releases_an_orphaned_follower_and_preserves_a_manual_order(self):
        world = FishingFamily({"Zug": 0, "Uzza": 12, "Zrog": 14}, job="quest")
        world.standing = {"Uzza": "fish", "Zrog": "fish"}
        world.job_sources = {"Uzza": activity.SOURCE, "Zrog": "discord"}
        fam = _family()
        fam["leader"]["job"] = "quest"
        bridge, _ = _bridge(world, FakeJev())

        asyncio.run(bridge._activity_for("Zug", fam, [], False, activity.policy({})))

        self.assertEqual([("Uzza", "quest", activity.SOURCE)], world.jobs)
        self.assertEqual("fish", world.standing["Zrog"])
