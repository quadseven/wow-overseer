"""Item Plan shadow logs expose the quote evidence behind route decisions."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan_shadow as shadow  # noqa: E402


class Capture:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *args):
        self.lines.append(fmt % args)

    def exception(self, fmt, *args):
        self.lines.append("EXC " + fmt % args)


class PriceEvidenceTest(unittest.TestCase):
    def test_shadow_logs_qualifying_quote_and_the_3_4x_near_miss(self):
        rows = [
            {
                "holder": "Member",
                "item_guid": 101,
                "entry": 1001,
                "name": "Worth listing",
                "quality": 1,
                "count": 1,
                "sell_price": 10_000,
                "item_class": 15,
                "bag_family": 0,
                "quest_item": False,
                "reagent": False,
                "profession_needed": False,
            },
            {
                "holder": "Member",
                "item_guid": 102,
                "entry": 1002,
                "name": "Below listing floor",
                "quality": 1,
                "count": 1,
                "sell_price": 10_000,
                "item_class": 15,
                "bag_family": 0,
                "quest_item": False,
                "reagent": False,
                "profession_needed": False,
            },
        ]
        templates = {
            entry: {
                "item_class": 15,
                "subclass": 0,
                "bonding": 0,
                "inventory_type": 0,
                "item_level": 1,
                "req_level": 0,
                "required_skill_rank": 0,
                "container_slots": 0,
                "fire_res": 0,
                "stats": {},
            }
            for entry in (1001, 1002)
        }
        extras = shadow.Extras(
            open_quest_items={"Member": frozenset()},
            market={1001: (60_000, 1), 1002: (34_000, 1)},
            templates=templates,
            instance_soulbound={101: False, 102: False},
            fire_gear=frozenset(),
        )
        capture = Capture()

        shadow.reset()
        shadow.run(
            ["Member"],
            "Family",
            rows,
            {"Member": 10},
            environ={"ITEMPLAN_SHADOW": "on"},
            logger=capture,
            extras=extras,
            state={},
            clock=lambda: 0,
        )

        evidence = [
            line
            for line in capture.lines
            if line.startswith("itemplan: price evidence ")
        ]
        self.assertEqual(len(evidence), 2, capture.lines)
        self.assertTrue(
            any(
                "Worth listing" in line
                and "quote 60000" in line
                and "vendor 10000" in line
                and "6.00x" in line
                and "net 57000 (5.70x vendor)" in line
                and "requires net >= 4x vendor and gain >= 5000" in line
                and "route AUCTION" in line
                for line in evidence
            ),
            evidence,
        )
        self.assertTrue(
            any(
                "Below listing floor" in line
                and "quote 34000" in line
                and "vendor 10000" in line
                and "3.40x" in line
                and "net 32300 (3.23x vendor)" in line
                and "requires net >= 4x vendor and gain >= 5000" in line
                and "route BANK_PERSONAL" in line
                for line in evidence
            ),
            evidence,
        )


if __name__ == "__main__":
    unittest.main()
