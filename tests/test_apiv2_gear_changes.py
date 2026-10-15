"""GET /api/v2/gear/changes reads recent loot and equips."""

import datetime
import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import realmread  # noqa: E402
from apiv2 import gear_changes  # noqa: E402

SINCE = datetime.datetime(2026, 10, 15, 12)
EVENTS = [
    {
        "character": "Durga",
        "guild": "Bonkers",
        "kind": "item_equip",
        "item": "Worn Boots",
        "quality": 1,
        "item_level": 5,
        "prior_state": "unknown",
        "at": SINCE + datetime.timedelta(hours=4),
    },
    {
        "character": "Velo",
        "guild": "Bonkers",
        "kind": "item_equip",
        "item": "Wool Gloves",
        "quality": 1,
        "item_level": 4,
        "prior_state": "empty",
        "at": SINCE + datetime.timedelta(hours=3),
    },
    {
        "character": "Mirra",
        "guild": "Cave",
        "kind": "item_equip",
        "item": "Brightwood Staff",
        "quality": 3,
        "item_level": 30,
        "prior_state": "item",
        "prior_item": "Oak Staff",
        "prior_quality": 2,
        "prior_item_level": 20,
        "at": SINCE + datetime.timedelta(hours=2),
    },
    {
        "character": "Tharn",
        "guild": "Cave",
        "kind": "item_loot",
        "item": "Ashwood Bow",
        "quality": 2,
        "item_level": 8,
        "prior_state": "",
        "at": SINCE + datetime.timedelta(hours=1),
    },
]


class TestGearChanges(unittest.TestCase):
    def get(self, query, rows=EVENTS):
        ctx = types.SimpleNamespace(
            read=realmread.Memory({gear_changes.CHANGES_SQL: rows})
        )
        return apiv2.handle("/api/v2/gear/changes", query, ctx)

    def test_loot_and_equip_include_prior_state_and_delta(self):
        code, body = self.get({"since": [SINCE.isoformat()]})
        self.assertEqual(code, 200)
        self.assertEqual(
            [r["kind"] for r in body["changes"]], ["worn", "worn", "worn", "looted"]
        )
        self.assertEqual(body["changes"][2]["replaced"], "Oak Staff")
        self.assertEqual(body["changes"][2]["item_level_change"], 10)
        self.assertEqual(body["changes"][1]["replaced"], "was empty")
        self.assertEqual(body["changes"][0]["replaced"], "not recorded")

    def test_filters_and_cap(self):
        many = [
            dict(EVENTS[-1], at=SINCE + datetime.timedelta(seconds=i))
            for i in range(510)
        ]
        code, body = self.get(
            {"since": [SINCE.isoformat()], "member": ["Tharn"], "guild": ["Cave"]}, many
        )
        self.assertEqual(code, 200)
        self.assertEqual(len(body["changes"]), 500)
        self.assertTrue(
            all(
                r["character"] == "Tharn" and r["guild"] == "Cave"
                for r in body["changes"]
            )
        )
        _, member_rows = self.get(
            {"since": [SINCE.isoformat()], "member": ["Mirra"], "guild": ["Cave"]}
        )
        self.assertEqual([r["character"] for r in member_rows["changes"]], ["Mirra"])
        _, no_rows = self.get(
            {"since": [SINCE.isoformat()], "member": ["Mirra"], "guild": ["Bonkers"]}
        )
        self.assertEqual(no_rows["changes"], [])

    def test_since_is_required_and_route_is_registered(self):
        self.assertIn("/api/v2/gear/changes", apiv2.ROUTES)
        self.assertEqual(self.get({})[0], 400)
