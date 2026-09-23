"""The virtual game client over the Watch streams (vclient.py, /api/client/*).

Three layers, the same three every view here is tested at:

- the builder, with rows shaped like the live realm's: where each slot goes,
  what an empty slot and an unknown bag size do, the guild bank's tabs, and
  who the social frame lists;
- the endpoints, driven through the Handler with the socket and the database
  amputated: a name off the rosters never reaches SQL, both families answer,
  nothing but GET is routed, and a tooltip is built once per item entry;
- the page, read as text: every tile gets the bar, no family is named in the
  overlay's code, and the quest log's family comes from the server.
"""

import io
import json
import logging
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402  (must follow the pymysql stub)
import vclient  # noqa: E402

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text()
SERVER = (HERE / "map_server.py").read_text()

ICONS = {6418: "inv_misc_rune_01", 7383: "inv_fabric_linen_01", 8271: "inv_misc_bag_09"}
FAMILIES = [
    ("Grug", ["Grug", "Bork", "Grog", "Og", "Ugga"]),
    ("Zug", ["Zug", "Oz", "Uzza", "Zork", "Zrog"]),
]


def row(bag, slot, entry, name, guid, count=1, quality=1, display=0, size=0):
    return {
        "bag": bag,
        "slot": slot,
        "item_guid": guid,
        "entry": entry,
        "count": count,
        "item_name": name,
        "quality": quality,
        "displayid": display,
        "container_slots": size,
    }


# Shaped like a real character: a pouch in the first bag slot with two
# things in it, a hearthstone and linen in the backpack, a bank slot, a bank
# bag with an item inside, and a sword worn (which neither frame draws).
ROWS = [
    row(0, 15, 2488, "Gladius", 900, quality=2),
    row(0, 19, 4496, "Small Brown Pouch", 100, display=8271, size=6),
    row(0, 23, 6948, "Hearthstone", 101, display=6418),
    row(0, 24, 2589, "Linen Cloth", 102, count=20, display=7383),
    row(100, 2, 17056, "Light Feather", 103, count=3),
    row(100, 5, 4693, "Ceremonial Leather Belt", 104),
    row(0, 39, 774, "Malachite", 105, count=5, quality=2),
    row(0, 67, 4496, "Small Brown Pouch", 106, display=8271, size=6),
    row(106, 0, 2589, "Linen Cloth", 107, count=7, display=7383),
]


class TheBagsFrame(unittest.TestCase):
    def setUp(self):
        self.p = vclient.build_inventory(ROWS, ICONS, vclient.BAGS, money=21496)

    def test_the_backpack_then_each_bag_every_slot_drawn(self):
        sizes = [(c["name"], len(c["cells"])) for c in self.p["containers"]]
        self.assertEqual(sizes, [("Backpack", 16), ("Small Brown Pouch", 6)])
        self.assertEqual(self.p["total"], 22)
        self.assertEqual(self.p["used"], 4)
        self.assertEqual(self.p["free"], 18)

    def test_an_item_sits_at_its_own_position_and_the_rest_are_empty(self):
        pouch = self.p["containers"][1]["cells"]
        self.assertIsNone(pouch[0])
        self.assertEqual(pouch[2]["name"], "Light Feather")
        self.assertEqual(pouch[2]["count"], 3)
        self.assertEqual(pouch[5]["entry"], 4693)

    def test_worn_bank_and_bank_bag_items_are_not_in_the_bags(self):
        names = {c["name"] for b in self.p["containers"] for c in b["cells"] if c}
        self.assertNotIn("Gladius", names)
        self.assertNotIn("Malachite", names)
        self.assertEqual(
            sum(
                c["count"]
                for b in self.p["containers"]
                for c in b["cells"]
                if c and c["name"] == "Linen Cloth"
            ),
            20,
        )

    def test_icon_or_initials_and_the_purse(self):
        first = self.p["containers"][0]["cells"][0]
        self.assertEqual(first["icon"], "inv_misc_rune_01")
        self.assertEqual(first["letters"], "He")
        self.assertEqual(self.p["containers"][1]["cells"][5]["icon"], None)
        self.assertEqual(self.p["containers"][1]["cells"][5]["letters"], "CL")
        self.assertEqual(self.p["money"], {"gold": 2, "silver": 14, "copper": 96})

    def test_the_bag_bar_shows_all_four_slots_filled_or_not(self):
        slots = self.p["bag_slots"]
        self.assertEqual([s["position"] for s in slots], [1, 2, 3, 4])
        self.assertEqual(slots[0]["bag"]["name"], "Small Brown Pouch")
        self.assertIsNone(slots[1]["bag"])

    def test_a_bag_of_unknown_size_grows_to_hold_what_is_in_it(self):
        rows = [row(0, 19, 1, None, 50), row(50, 3, 2589, "Linen Cloth", 51)]
        p = vclient.build_inventory(rows, {}, vclient.BAGS)
        bag = p["containers"][1]
        self.assertEqual(len(bag["cells"]), 4)
        self.assertEqual(bag["cells"][3]["name"], "Linen Cloth")
        self.assertEqual(bag["name"], "Bag #1")


class TheBankFrame(unittest.TestCase):
    def test_the_bank_and_its_bags_and_nothing_carried(self):
        p = vclient.build_inventory(ROWS, ICONS, vclient.BANK)
        self.assertEqual([len(c["cells"]) for c in p["containers"]], [28, 6])
        self.assertEqual(p["containers"][0]["cells"][0]["name"], "Malachite")
        self.assertEqual(p["containers"][1]["cells"][0]["count"], 7)
        self.assertEqual(len(p["bag_slots"]), 7)
        self.assertEqual((p["used"], p["total"]), (2, 34))
        self.assertIsNone(p["note"])

    def test_an_empty_bank_says_why(self):
        p = vclient.build_inventory([], ICONS, vclient.BANK)
        self.assertEqual(p["free"], 28)
        self.assertEqual(p["note"], vclient.EMPTY_BANK_NOTE)


class TheGuildBankFrame(unittest.TestCase):
    def test_no_guild_and_no_tab_each_say_so(self):
        self.assertEqual(
            vclient.build_guild_bank(None, [], [], ICONS)["note"], vclient.NO_GUILD_NOTE
        )
        guild = {"guild_id": 24, "guild_name": "Bonkers", "bank_money": 0}
        p = vclient.build_guild_bank(guild, [], [], ICONS)
        self.assertEqual(p["note"], vclient.NO_TABS_NOTE)
        self.assertEqual(p["guild"], "Bonkers")

    def test_each_tab_is_ninety_eight_slots_with_items_placed(self):
        guild = {"guild_id": 23, "guild_name": "Cave", "bank_money": 8046728}
        tabs = [
            {"tab_id": 1, "tab_name": "", "tab_icon": ""},
            {"tab_id": 0, "tab_name": "Mats", "tab_icon": "inv_misc_bag_09"},
        ]
        items = [
            {
                "tab_id": 0,
                "slot_id": 13,
                "entry": 2589,
                "count": 20,
                "item_name": "Linen Cloth",
                "quality": 1,
                "displayid": 7383,
            },
            {
                "tab_id": 1,
                "slot_id": 97,
                "entry": 6948,
                "count": 1,
                "item_name": "Hearthstone",
                "quality": 1,
                "displayid": 6418,
            },
            {
                "tab_id": 5,
                "slot_id": 0,
                "entry": 1,
                "count": 1,
                "item_name": "Stray",
                "quality": 0,
                "displayid": 0,
            },
        ]
        p = vclient.build_guild_bank(guild, tabs, items, ICONS)
        self.assertEqual([t["name"] for t in p["tabs"]], ["Mats", "Tab 2"])
        self.assertTrue(all(len(t["cells"]) == 98 for t in p["tabs"]))
        self.assertEqual(p["tabs"][0]["cells"][13]["count"], 20)
        self.assertEqual(p["tabs"][1]["cells"][97]["name"], "Hearthstone")
        self.assertEqual([t["used"] for t in p["tabs"]], [1, 1])
        self.assertEqual(p["money"]["gold"], 804)
        self.assertEqual(p["columns"], 14)


class TheSocialFrame(unittest.TestCase):
    def test_family_in_roster_order_guild_and_friends_online_first(self):
        names = FAMILIES[1][1]
        fam = [
            {"name": "Oz", "level": 24, "class": 8, "race": 8, "online": 1},
            {"name": "Zug", "level": 25, "class": 1, "race": 2, "online": 0},
        ]
        guild = {"guild_id": 24, "guild_name": "Bonkers", "bank_money": 0}
        roster = [
            {
                "name": "Adalok",
                "level": 60,
                "class": 4,
                "race": 5,
                "online": 0,
                "rank": 4,
                "rank_name": "Initiate",
            },
            {
                "name": "Zug",
                "level": 25,
                "class": 1,
                "race": 2,
                "online": 1,
                "rank": 0,
                "rank_name": "Guild Master",
            },
        ]
        social = [
            {
                "name": "Oz",
                "level": 24,
                "class": 8,
                "race": 8,
                "online": 1,
                "flags": 1,
                "note": "brother",
            },
            {
                "name": "Pest",
                "level": 10,
                "class": 1,
                "race": 2,
                "online": 0,
                "flags": 2,
                "note": "",
            },
        ]
        p = vclient.build_social("Zug", "Zug", names, fam, guild, roster, social)
        self.assertEqual([m["name"] for m in p["family"]["members"]], names)
        self.assertEqual(p["family"]["key"], "Zug")
        self.assertEqual(p["family"]["members"][0]["line"], "Level 25 Orc Warrior")
        self.assertEqual(p["family"]["members"][2]["line"], "not on this realm")
        self.assertEqual([m["name"] for m in p["guild"]["members"]], ["Zug", "Adalok"])
        self.assertEqual(p["guild"]["members"][0]["rank"], "Guild Master")
        self.assertEqual((p["guild"]["online"], p["guild"]["total"]), (1, 2))
        self.assertEqual([f["name"] for f in p["friends"]], ["Oz"])
        self.assertEqual(p["friends"][0]["note"], "brother")
        self.assertEqual(p["ignored"], ["Pest"])

    def test_no_guild_and_no_friends_say_so(self):
        p = vclient.build_social("Og", "Grug", ["Og"], [], None, [], [])
        self.assertEqual(p["guild"]["note"], vclient.NO_GUILD_NOTE)
        self.assertEqual(p["friends_note"], vclient.NO_FRIENDS_NOTE)


class TheTooltipCache(unittest.TestCase):
    def test_built_once_per_entry_and_bounded(self):
        calls = []
        cache = vclient.TooltipCache(limit=2)

        def build(entry):
            calls.append(entry)
            return {"entry": entry}

        cache.get(1, build)
        cache.get(1, build)
        cache.get(2, build)
        cache.get(3, build)
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(len(cache), 2)
        cache.get(1, build)
        self.assertEqual(calls, [1, 2, 3, 1])

    def test_a_missing_item_is_not_kept(self):
        cache = vclient.TooltipCache()
        self.assertIsNone(cache.get(9, lambda e: None))
        self.assertEqual(len(cache), 0)

    def test_the_bag_book_covers_what_a_bag_holds(self):
        """A hearthstone is not equippable, so the Armory's book has neither
        its icon nor its Use: line. The widened book has both."""
        book = map_server.CLIENT_BOOK
        self.assertNotIn(6418, map_server.ITEMS.icons)
        self.assertEqual(book.icons[6418], "inv_misc_rune_01")
        self.assertIn("Returns you to", book.spells[8690])
        tip = vclient.item_tooltip(
            {
                "entry": 6948,
                "item_name": "Hearthstone",
                "quality": 1,
                "item_level": 1,
                "required_level": 0,
                "displayid": 6418,
                "bonding": 1,
                "spellid_1": 8690,
                "spelltrigger_1": 0,
            },
            book,
        )
        self.assertEqual(tip["icon"], "inv_misc_rune_01")
        self.assertEqual(tip["tooltip"]["binding"], "Binds when picked up")
        self.assertTrue(tip["tooltip"]["effects"][0].startswith("Use: Returns you to"))


class FakeHandler(map_server.Handler):
    def __init__(self, path):
        self.path = path
        self.rfile = io.BytesIO(b"")
        self.headers = {}
        self.sent = []

    def _send(self, code, ctype, body, cache_control="no-store"):
        self.sent.append((code, ctype, body))

    @property
    def code(self):
        return self.sent[-1][0]

    @property
    def payload(self):
        return json.loads(self.sent[-1][2])


def get(path):
    h = FakeHandler(path)
    h.do_GET()
    return h


@mock.patch.object(map_server, "_fetch_family_groups", return_value=FAMILIES)
class TheEndpoints(unittest.TestCase):
    def test_both_families_answer_every_frame(self, _groups):
        inv = {"rows": ROWS, "money": 100}
        gb = {"guild": None, "tab_rows": [], "item_rows": []}
        soc = {"family_rows": [], "guild": None, "guild_rows": [], "social_rows": []}
        with (
            mock.patch.object(map_server, "_fetch_client_inventory", return_value=inv),
            mock.patch.object(map_server, "_fetch_client_guild_bank", return_value=gb),
            mock.patch.object(
                map_server, "_fetch_client_social", return_value=soc
            ) as s,
        ):
            for key, names in FAMILIES:
                for name in (names[0], names[-1]):
                    for frame in ("bags", "bank", "guildbank", "social"):
                        h = get("/api/client/%s?name=%s" % (frame, name))
                        self.assertEqual(h.code, 200, (frame, name))
                        self.assertEqual(h.payload["family_key"], key)
                        self.assertEqual(h.payload["name"], name)
            social = get("/api/client/social?name=Zrog").payload
            self.assertEqual(social["family"]["key"], "Zug")
            # The family handed to the read is the one the roster names.
            self.assertEqual(s.call_args.args, ("Zrog", FAMILIES[1][1]))

    def test_a_name_off_the_rosters_never_reaches_sql(self, _groups):
        with mock.patch.object(map_server, "_fetch_client_inventory") as inv:
            for bad in ("Stranger", "x", "Grug'--", ""):
                h = get("/api/client/bags?name=" + bad)
                self.assertEqual(h.code, 404, bad)
            inv.assert_not_called()

    def test_a_dead_database_is_a_503_and_a_bug_is_a_500(self, _groups):
        """Only a database or network fault reads as an unreachable world; a
        builder's own bug is a 500, so it is not dressed as an outage."""

        class Down(Exception):
            pass

        stub = types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=Down))
        with mock.patch.object(map_server, "pymysql", stub):
            for fault, code in (
                (Down("gone"), 503),
                (OSError("reset"), 503),
                (KeyError("slot"), 500),
            ):
                with mock.patch.object(
                    map_server, "_fetch_client_inventory", side_effect=fault
                ):
                    self.assertEqual(get("/api/client/bags?name=Zug").code, code)

    def test_an_item_is_read_once_and_a_bad_entry_never_reaches_sql(self, _groups):
        tpl = {
            "entry": 2589,
            "item_name": "Linen Cloth",
            "quality": 1,
            "item_level": 5,
            "required_level": 0,
            "displayid": 7383,
            "sell_price": 13,
        }
        with (
            mock.patch.object(map_server, "CLIENT_TOOLTIPS", vclient.TooltipCache()),
            mock.patch.object(
                map_server, "_fetch_client_item", return_value=tpl
            ) as fetch,
        ):
            a = get("/api/client/item?entry=2589")
            b = get("/api/client/item?entry=2589")
            self.assertEqual((a.code, b.code), (200, 200))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(a.payload["tooltip"]["name"], "Linen Cloth")
            self.assertEqual(a.payload["tooltip"]["sell_price"]["copper"], 13)
            for bad in ("abc", "-1", "0", "99999999", ""):
                self.assertEqual(get("/api/client/item?entry=" + bad).code, 400, bad)
            self.assertEqual(fetch.call_count, 1)
        with (
            mock.patch.object(map_server, "CLIENT_TOOLTIPS", vclient.TooltipCache()),
            mock.patch.object(map_server, "_fetch_client_item", return_value=None),
        ):
            self.assertEqual(get("/api/client/item?entry=5").code, 404)


class TheEndpointsAreReadOnly(unittest.TestCase):
    def test_every_client_route_is_a_get(self):
        client = [
            r for r in map_server.Handler.GET_ROUTES if r.startswith("/api/client/")
        ]
        self.assertEqual(
            sorted(client),
            [
                "/api/client/bags",
                "/api/client/bank",
                "/api/client/guildbank",
                "/api/client/item",
                "/api/client/social",
            ],
        )
        self.assertFalse(
            [r for r in map_server.Handler.POST_ROUTES if r.startswith("/api/client")]
        )

    def test_no_client_query_writes(self):
        block = SERVER[SERVER.index("# --- the virtual game client over the Watch") :]
        block = block[: block.index("class Handler(")]
        for verb in ("INSERT", "UPDATE ", "DELETE", "REPLACE", "commit("):
            self.assertNotIn(verb, block, verb)


def overlay():
    js = PAGE[PAGE.index("// --- the virtual game client (vclient.py)") :]
    return js[: js.index("</script>")]


class TheOverlayHandlesBothFamilies(unittest.TestCase):
    def test_every_wall_tile_gets_the_bar(self):
        slot = PAGE[PAGE.index("function wallSlot(name) {") :]
        slot = slot[: slot.index("\n}")]
        self.assertIn("shot.appendChild(vclientBar(name));", slot)

    def test_no_family_or_character_is_named_in_the_overlay(self):
        code = overlay()
        for _key, names in FAMILIES:
            for name in names:
                self.assertNotRegex(code, r'["\']%s["\']' % name, name)
        for guild in ("Cave", "Bonkers"):
            self.assertNotIn(guild, code)

    def test_the_quest_log_family_is_the_servers(self):
        code = overlay()
        self.assertIn(
            'u("/api/questlog?family=") + encodeURIComponent(s.family.key)', code
        )
        self.assertIn("s.family.members.map(", code)

    def test_six_frames_draggable_closable_and_escape(self):
        code = overlay()
        for kind in ("bags", "bank", "guildbank", "character", "social", "quests"):
            self.assertIn('kind: "%s"' % kind, code)
        self.assertIn('if (e.key !== "Escape") return;', code)
        self.assertIn("setPointerCapture", code)
        self.assertIn('x.addEventListener("click", () => vcClose(kind));', code)

    def test_read_only_lazy_and_no_markup(self):
        code = overlay()
        self.assertNotIn("POST", code)
        self.assertNotIn("innerHTML", code)
        self.assertNotIn("setInterval", code)
        self.assertNotIn("https://", code)
        # Every same-origin URL through the mount helper.
        self.assertIn('u("/api/client/bags?name=")', code)

    def test_an_icon_falls_back_to_the_items_initials(self):
        code = overlay()
        self.assertIn('iconImg(item.icon, "", letters)', code)
        self.assertIn("item.letters", code)


if __name__ == "__main__":
    unittest.main()
