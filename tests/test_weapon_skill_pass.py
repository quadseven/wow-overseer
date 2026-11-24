"""Characterization tests for the weapon-skill pass (#1753).

The pass now lives in `weaponskill.WeaponSkillPass` and reaches the Bridge only
through the `_BridgeLike` Protocol. These tests drive `run_once` through a fake
adapter for three cases: equip what was trained, train a member standing in
reach of the weapon master, and walk the leader to the master.
"""

import asyncio
import unittest

import townerrand
import weaponskill


class FakeBridge:
    """A fake adapter implementing the weaponskill `_BridgeLike` Protocol."""

    def __init__(self):
        self._town_errand_locks = {}
        self.names = ["Eggo"]
        self.leader = "Eggo"
        self.facts = {}
        self.bags = []
        self.positions = {}
        self.masters = []
        self.applied_trains = []
        self.equip_written = []
        self.train_written = []
        self.claimed = None
        self.crossed = None

    def family_of(self, cohort=None):
        return list(self.names), self.leader

    def fetch_gearup_facts(self, names):
        return self.facts

    def fetch_bag_weapons(self, names):
        return self.bags

    def town_errand_state(self, key):
        return townerrand.State()

    async def _town_errand_yield_for_weapon(self, state, names, leader,
                                            slot, label):
        return True

    def _cohort_town_slot(self, cohort=None):
        return object()

    def _town_errand_lock(self, names):
        return asyncio.Lock()

    async def _mid_run(self, names):
        return False

    def fetch_positions(self, names):
        return self.positions

    def fetch_teams(self, names):
        return {name: "horde" for name in names}

    def fetch_weapon_masters(self, at, spells, also_maps):
        return list(self.masters)

    def fetch_weapon_crossings(self, names):
        return ()

    def fetch_weapon_trains_applied(self, names):
        return list(self.applied_trains)

    def insert_weapon_equip(self, row):
        self.equip_written.append(row)
        return 1

    def weapon_train_asked(self, need):
        return False

    def insert_weapon_train(self, need):
        self.train_written.append(need)
        return 1

    async def _claim_town_slot(self, claimant, character, target, urgent,
                               cohort):
        self.claimed = (claimant, character, target, urgent, cohort)
        return True

    async def _class_cross_row(self, step, row):
        self.crossed = step


MAGE = 8
SWORDS = 43

MASTER = {
    "entry": 11870,
    "name": "Archibald",
    "faction": 68,
    "map_id": 0,
    "x": 0.0,
    "y": 0.0,
    "yards": 3.0,
    "spell": 201,
    "cost": 1000,
}


def bag(entry=5191, label="A Gladius", subclass=7, inventory_type=13,
        item_level=24, required_level=20):
    return {
        "name": "Eggo",
        "entry": entry,
        "label": label,
        "subclass": subclass,
        "InventoryType": inventory_type,
        "ItemLevel": item_level,
        "RequiredLevel": required_level,
        "AllowableClass": -1,
    }


def facts(mage=True, equipped=None, skills=None):
    return {
        "Eggo": {
            "class": "mage" if mage else "warrior",
            "level": 35,
            "equipped": equipped or {},
            "skills": {"weapons": skills or set()},
        }
    }


class WeaponSkillPassCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = FakeBridge()
        self.pass_ = weaponskill.WeaponSkillPass(self.bridge)

    async def test_equip_what_was_trained(self):
        """An applied train row is turned into an equip row."""
        self.bridge.applied_trains = [
            {"name": "Eggo", "skill": "43", "entry": "5191",
             "item_name": "A Gladius"},
        ]
        # No carried weapon need, so after equipping the pass has nothing else.
        self.bridge.bags = []
        await self.pass_.run_once(None)
        self.assertEqual(1, len(self.bridge.equip_written))
        self.assertEqual("Eggo", self.bridge.equip_written[0]["name"])

    async def test_train_a_member_in_reach_of_the_master(self):
        """A member at the master buys the skill with its own gold."""
        self.bridge.facts = facts()
        self.bridge.bags = [bag()]
        self.bridge.positions = {
            "Eggo": {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0},
        }
        self.bridge.masters = [MASTER]
        await self.pass_.run_once(None)
        self.assertEqual(1, len(self.bridge.train_written))
        self.assertEqual("Eggo", self.bridge.train_written[0].name)
        self.assertEqual(SWORDS, self.bridge.train_written[0].skill)

    async def test_walk_the_leader_to_the_master(self):
        """A member out of reach is aimed at the weapon master."""
        self.bridge.facts = facts()
        self.bridge.bags = [bag()]
        self.bridge.positions = {
            "Eggo": {"map_id": 0, "pos_x": 100.0, "pos_y": 100.0},
        }
        self.bridge.masters = [MASTER]
        await self.pass_.run_once(None)
        self.assertEqual(0, len(self.bridge.train_written))
        self.assertIsNotNone(self.bridge.claimed)
        claimant, character, target, urgent, cohort = self.bridge.claimed
        self.assertEqual("weapon master", claimant)
        self.assertEqual("Eggo", character)
        self.assertEqual("11870", target)
        self.assertTrue(urgent)
        self.assertIsNone(cohort)


if __name__ == "__main__":
    unittest.main()
