"""Verify hand-kept crafting item IDs against the realm's item_template snapshot.

Snapshot file: tests/craft_items.json

Generating query against the realm world database:
    SELECT entry, name, class, subclass
    FROM acore_world.item_template
    WHERE entry IN (<sorted unique item entries>)
    ORDER BY entry;
"""

from __future__ import annotations

import json
import pathlib
import unittest

import bag_economy
import craft_rhythm
import craft_supply
import guildcorps

SNAPSHOT = pathlib.Path(__file__).resolve().with_name("craft_items.json")
QUEST_ITEM_CLASS = 12


def _load_snapshot() -> dict[str, dict]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


class CraftingItemTablesMatchWorldDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.items = _load_snapshot()

    def _assert_item(self, entry: int, label: str | None = None) -> None:
        key = str(int(entry))
        self.assertIn(key, self.items, f"item {entry} ({label}) missing from snapshot")
        row = self.items[key]
        self.assertNotEqual(
            row["class"],
            QUEST_ITEM_CLASS,
            f"item {entry} ({row['name']}) is a quest item (class 12), not a craft material",
        )
        if label is not None:
            self.assertEqual(
                row["name"],
                label,
                f"item {entry} label mismatch: code has {label!r}, DB has {row['name']!r}",
            )

    def test_craft_rhythm_gathered_matches_snapshot(self) -> None:
        for spell, regs in craft_rhythm.GATHERED.items():
            for r in regs:
                with self.subTest(spell=spell, entry=r.entry):
                    self._assert_item(r.entry, r.label)

    def test_craft_rhythm_bolt_bag_and_disenchant_tables_match_snapshot(self) -> None:
        for spell, (_, bolt) in craft_rhythm.BOLT_FED.items():
            with self.subTest(table="BOLT_FED", spell=spell, entry=bolt.entry):
                self._assert_item(bolt.entry, bolt.label)
        for table_name, table in (
            ("BAG_FEED", craft_rhythm.BAG_FEED),
            ("DISENCHANT_FED", craft_rhythm.DISENCHANT_FED),
        ):
            for spell, regs in table.items():
                for r in regs:
                    with self.subTest(table=table_name, spell=spell, entry=r.entry):
                        self._assert_item(r.entry, r.label)

    def test_craft_supply_tables_match_snapshot(self) -> None:
        for spell, (entry, label, _price) in craft_supply.REAGENT.items():
            with self.subTest(table="REAGENT", spell=spell, entry=entry):
                self._assert_item(entry, label)
        for spell, regs in craft_supply.REAGENTS.items():
            for entry, label, _price, _qty in regs:
                with self.subTest(table="REAGENTS", spell=spell, entry=entry):
                    self._assert_item(entry, label)

    def test_bag_economy_and_guildcorps_tables_match_snapshot(self) -> None:
        for key, bolt in bag_economy.BOLTS.items():
            with self.subTest(table="bag_economy.BOLTS", key=key):
                self._assert_item(bolt.entry, bolt.name)
                self._assert_item(bolt.cloth_entry, bolt.cloth)
        for bag in guildcorps.BAGS:
            with self.subTest(table="guildcorps.BAGS", makes=bag.makes):
                self._assert_item(bag.makes, bag.name)
                for entry, _qty in bag.reagents:
                    self._assert_item(entry)
        for entry, bolt in guildcorps.BOLT_OF.items():
            with self.subTest(table="guildcorps.BOLT_OF", entry=entry):
                self._assert_item(entry, bolt.name)
                for reg, _qty in bolt.reagents:
                    self._assert_item(reg)


if __name__ == "__main__":
    unittest.main()
