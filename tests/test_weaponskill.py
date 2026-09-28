"""A weapon carried without its skill is learned at a weapon master (#399).

The dev realm, 2026-09-28: the level 35 mage carried a Silithid Ripper (a
one-handed sword) with no Swords skill and wore no main hand; the level 38
warrior carried a Ravenwood Bow with no Bows skill and an empty ranged slot.
"""

import ast
import pathlib
import unittest

import weaponskill as ws

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")

FACTS = {
    "Og": {"class": "mage", "level": 35, "equipped": {"chest": 16, "offhand": 22},
           "skills": {"weapons": {10, 19, 20}}},
    "Grug": {"class": "warrior", "level": 38,
             "equipped": {"mainhand": 43, "offhand": 13},
             "skills": {"weapons": {0, 4, 7, 14}}},
    "Ugga": {"class": "priest", "level": 35, "equipped": {"chest": 33},
             "skills": {"weapons": {4, 10, 19, 20}}},
}  # fmt: skip


def bag(name, entry, label, sub, inv, ilvl, rl):
    return {"name": name, "entry": entry, "label": label, "subclass": sub,
            "InventoryType": inv, "ItemLevel": ilvl, "RequiredLevel": rl,
            "AllowableClass": -1}  # fmt: skip


BAGS = [
    bag("Og", 11, "Silithid Ripper", 7, 13, 36, 31),
    bag("Og", 12, "Battlefell Sabre", 7, 21, 62, 57),  # too high a level
    bag("Grug", 21, "Ravenwood Bow", 2, 15, 32, 27),
    bag("Grug", 22, "Warlord's Axe", 0, 13, 58, 53),  # too high, and held
    bag("Ugga", 31, "Gutwrencher", 15, 13, 47, 42),  # too high
    bag("Ugga", 32, "A Sword", 7, 13, 30, 25),  # a priest cannot learn swords
]

MASTERS = [
    {"entry": 11867, "name": "Woo Ping", "faction": 12, "map_id": 0, "x": 1.0,
     "y": 1.0, "yards": 900.0, "spell": 201},
    {"entry": 11870, "name": "Archibald", "faction": 68, "map_id": 0, "x": 5.0,
     "y": 5.0, "yards": 300.0, "spell": 201},
    {"entry": 11865, "name": "Buliwyf Stonehand", "faction": 55, "map_id": 0,
     "x": 9.0, "y": 9.0, "yards": 500.0, "spell": 266},
]  # fmt: skip


class Needs(unittest.TestCase):
    def test_the_mage_needs_swords_and_the_warrior_bows(self):
        got = {
            (n.name, n.skill, n.spell, n.entry, n.slot) for n in ws.needs(FACTS, BAGS)
        }
        self.assertEqual(
            {("Og", 43, 201, 11, "mainhand"), ("Grug", 45, 264, 21, "ranged")}, got
        )

    def test_a_worn_better_weapon_needs_nothing(self):
        facts = dict(FACTS, Og=dict(FACTS["Og"], equipped={"mainhand": 40}))
        self.assertNotIn("Og", {n.name for n in ws.needs(facts, BAGS)})

    def test_commands(self):
        need = ws.needs(FACTS, BAGS)[1]
        self.assertEqual("train-weapon skill:43", need.train_command)
        self.assertEqual("e Hitem:11:0", need.equip_command)


class TheMaster(unittest.TestCase):
    def test_own_side_on_the_map_only(self):
        got = ws.choose_master(MASTERS, {201}, "alliance", 0)
        self.assertEqual(11867, got["entry"])  # Archibald is the Horde's
        self.assertEqual({}, ws.choose_master(MASTERS, {201}, "alliance", 1))
        self.assertEqual(11870, ws.choose_master(MASTERS, {201}, "horde", 0)["entry"])

    def test_in_reach(self):
        master = {"map_id": 0, "x": 0.0, "y": 0.0}
        self.assertTrue(ws.in_reach(master, {"map_id": 0, "pos_x": 5, "pos_y": 5}))
        self.assertFalse(ws.in_reach(master, {"map_id": 0, "pos_x": 9, "pos_y": 0}))
        self.assertFalse(ws.in_reach(master, {"map_id": 1, "pos_x": 0, "pos_y": 0}))


class TheBridge(unittest.TestCase):
    def test_the_loop_runs_and_the_module_ships(self):
        self.assertEqual(2, BRIDGE.count("self._weapon_skill_loop,"))
        self.assertIn(
            "weaponskill.py", (ROOT / "Dockerfile").read_text(encoding="utf-8")
        )
        names = {
            n.name
            for n in ast.walk(ast.parse(BRIDGE))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for fn in (
            "_weapon_skill_once",
            "_fetch_bag_weapons",
            "_fetch_weapon_masters",
            "_insert_weapon_train",
            "_weapon_trains_applied",
            "_insert_weapon_equip",
        ):
            self.assertIn(fn, names)

    def test_the_row_is_the_verb_the_module_reads(self):
        self.assertIn("VALUES (%s, %s, 'cast', %s, %s)", BRIDGE)


if __name__ == "__main__":
    unittest.main()
