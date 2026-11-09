"""GET /api/v2/guildbank: a family guild's bank, tab by tab, read-only.

Run at the route seam against the in-memory realm reader, which raises on any
statement it was not given, so what the handler reads is checked too.
"""

import pathlib
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import apiv2
    import realmread
    from apiv2 import guildbank
    from test_apiv2_guilds import FAMILIES

GUILD_ROW = {"guildid": 7, "name": "Cave"}
TABS = [
    {"tab_id": 1, "tab_name": "Bags", "tab_icon": "x"},
    {"tab_id": 0, "tab_name": "Gear", "tab_icon": "y"},
]


def item(tab, slot, entry, name, count=1):
    return {
        "tab_id": tab,
        "slot_id": slot,
        "entry": entry,
        "count": count,
        "item_name": name,
        "quality": 4,
        "displayid": 1,
        "item_class": 4,
        "item_subclass": 1,
    }


class Ctx:
    def __init__(self, found=(GUILD_ROW,), tabs=TABS, items=()):
        self.read = realmread.Memory(
            {
                guildbank.GUILD_SQL: list(found),
                guildbank.TABS_SQL: list(tabs),
                guildbank.ITEMS_SQL: list(items),
            }
        )
        self.server = types.SimpleNamespace(CLIENT_ICONS={1: "icon"})
        self.families = FAMILIES


def get(ctx, guild="cave"):
    return apiv2.handle("/api/v2/guildbank", {"guild": [guild]}, ctx)


class TheGuildBank(unittest.TestCase):
    def test_route_is_registered(self):
        self.assertIn("/api/v2/guildbank", apiv2.ROUTES)

    def test_items_per_tab_with_counts_and_names(self):
        status, out = get(
            Ctx(items=[item(0, 3, 100, "Sword", 1), item(1, 0, 200, "Linen Cloth", 20)])
        )
        self.assertEqual(status, 200)
        self.assertEqual(out["guild"], "Cave")
        self.assertEqual([t["tab"] for t in out["tabs"]], [0, 1])
        gear, bags = out["tabs"]
        self.assertEqual(gear["name"], "Gear")
        self.assertEqual(gear["items"][0]["slot"], 3)
        self.assertEqual(gear["items"][0]["name"], "Sword")
        self.assertEqual(gear["items"][0]["entry"], 100)
        self.assertEqual(bags["items"][0]["count"], 20)
        self.assertEqual(out["item_total"], 2)
        self.assertFalse(out["truncated"])

    def test_an_empty_tab_reads_as_empty_not_an_error(self):
        status, out = get(Ctx(items=[item(0, 3, 100, "Sword")]))
        self.assertEqual(status, 200)
        self.assertEqual(out["tabs"][1]["items"], [])
        self.assertEqual(out["tabs"][1]["used"], 0)

    def test_a_guild_with_no_tabs_reads_as_empty(self):
        status, out = get(Ctx(tabs=[]))
        self.assertEqual((status, out["tabs"]), (200, []))

    def test_no_character_fields_are_sent(self):
        _, out = get(Ctx(items=[item(0, 0, 1, "A")]))
        keys = set(out["tabs"][0]["items"][0])
        self.assertFalse(keys & {"guid", "item_guid", "owner", "creator"})

    def test_the_response_is_capped(self):
        rows = [
            item(0, i % 98, 1000 + i, "I%d" % i) for i in range(guildbank.MAX_ITEMS + 1)
        ]
        _, out = get(Ctx(items=rows))
        self.assertTrue(out["truncated"])
        self.assertEqual(out["item_total"], guildbank.MAX_ITEMS)

    def test_queries_are_bound_and_limited(self):
        ctx = Ctx()
        get(ctx)
        for sql, params in ctx.read.asked:
            self.assertNotIn("Cave", sql)
            self.assertIsNotNone(params)
        self.assertIn("LIMIT", guildbank.ITEMS_SQL)

    def test_a_guild_outside_the_set_is_404(self):
        self.assertEqual(get(Ctx(), "adventurer union")[0], 404)

    def test_a_missing_guild_param_is_400(self):
        self.assertEqual(apiv2.handle("/api/v2/guildbank", {}, Ctx())[0], 400)

    def test_nothing_writes(self):
        for sql in (guildbank.GUILD_SQL, guildbank.TABS_SQL, guildbank.ITEMS_SQL):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"))


if __name__ == "__main__":
    unittest.main()
