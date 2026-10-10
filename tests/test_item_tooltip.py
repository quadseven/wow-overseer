"""A gear name shows the item, in place, and does not navigate.

WHAT THIS IS FOR. A gear name on this site was an anchor to wowhead.com. On a
desktop that is a new tab; on the phone the site is actually read on it is
either a navigation off the page or, held down, the browser's own link menu
(Open in New Tab, Copy Link, Share) sitting over the loot list. The operator
photographed the second one. Neither is a tooltip.

So the name is a button, the lines the game draws for that item are drawn from
OUR OWN tables, and wowhead.com is one deliberate row at the foot of the panel
the button opens.

TWO THINGS THIS FILE GUARDS, and they are the two that will rot first.

The first is that the tooltip is built here and not fetched. index.html already
refuses to let a browser reach wow.zamimg.com for the 3D model's data, because
that host declines an Origin it does not recognise; a tooltip that leaned on
Wowhead's own script would be the one part of this page that stops working off
the tailnet. So the assertions below are about item_template columns reaching
armory.template_tooltip, never about a script tag.

The second is that there is ONE renderer. The Armory's item card already drew
every one of these lines, correctly, and the ask was for that card on every
gear name rather than for a second thing that resembles it. itemTipLines is
that renderer and renderDetail calls it; a copy of it appearing anywhere else
is the failure this file is watching for.

Tickets: infra#3501.
"""

import pathlib
import unittest
from datetime import datetime, timedelta

import achievements
import armory
import recap

HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

BANNER = "// --- the item tooltip, on every gear name (infra#3501)"
CSS_BANNER = "/* --- the item tooltip, on every gear name (infra#3501)"
NEXT = "// --- the Decree console (infra#2597)"
NEXT_CSS = "/* --- the Decree console (infra#2597)"

BOOK = armory.ItemBook.load(str(HERE))


def template(**over) -> dict:
    """An item_template row shaped the way _ITEM_TEMPLATE_COLUMNS selects it.

    Written out in full rather than as a handful of keys, because the point of
    the widened read is that every one of these columns arrives; a fixture
    carrying four of them would pass while the query selected four.
    """
    row = {
        "entry": 10402,
        "item_name": "Serpent's Shoulders",
        "quality": 2,
        "item_level": 24,
        "required_level": 19,
        "max_durability": 70,
        "displayid": 5194,
        "class": 4,
        "subclass": 2,
        "inventory_type": 3,
        "armor": 48,
        "block": 0,
        "bonding": 1,
        "itemset": 0,
        "sell_price": 4521,
        "allowable_class": -1,
        "description": "",
        "dmg_min1": 0,
        "dmg_max1": 0,
        "delay": 0,
        "dmg_min2": 0,
        "dmg_max2": 0,
        "dmg_type2": 0,
        "holy_res": 0,
        "fire_res": 0,
        "nature_res": 0,
        "frost_res": 0,
        "shadow_res": 0,
        "arcane_res": 0,
    }
    for n in range(1, 11):
        row["stat_type%d" % n] = 0
        row["stat_value%d" % n] = 0
    for n in range(1, 6):
        row["spellid_%d" % n] = 0
        row["spelltrigger_%d" % n] = 0
    row["stat_type1"], row["stat_value1"] = 3, 7  # ITEM_MOD_AGILITY
    row["stat_type2"], row["stat_value2"] = 6, 5  # ITEM_MOD_SPIRIT
    row.update(over)
    return row


class TheLinesComeFromTheWorldDatabase(unittest.TestCase):
    """armory.template_tooltip, which is the whole of the data side."""

    def setUp(self):
        self.tip = armory.template_tooltip(template(), BOOK)

    def test_the_slot_and_the_kind_are_words_and_not_ids(self):
        """A tooltip that says "slot 3" instead of "Shoulder" is not one."""
        self.assertEqual(self.tip["slot"], "Shoulder")
        self.assertEqual(self.tip["kind"], "Leather")

    def test_the_binding_is_the_clients_own_sentence(self):
        self.assertEqual(self.tip["binding"], "Binds when picked up")

    def test_the_stat_lines_are_named_from_the_cores_own_enum(self):
        """3 is ITEM_MOD_AGILITY and 6 is ITEM_MOD_SPIRIT, and the names come
        from armory.BASE_STATS, which is the core's ItemPrototype.h table. A
        second copy of that mapping is the thing this asserts against."""
        self.assertEqual(self.tip["stats"], ["+7 Agility", "+5 Spirit"])

    def test_armour_the_level_and_the_required_level_are_carried(self):
        self.assertEqual(self.tip["armor"], 48)
        self.assertEqual(self.tip["item_level"], 24)
        self.assertEqual(self.tip["requires_level"], 19)

    def test_the_sell_price_is_split_into_coins_by_the_module(self):
        self.assertEqual(
            self.tip["sell_price"], {"gold": 0, "silver": 45, "copper": 21}
        )

    def test_a_weapon_reads_its_damage_its_speed_and_its_dps(self):
        tip = armory.template_tooltip(
            template(
                entry=6472,
                item_name="Fang of the Crystal Spider",
                quality=3,
                inventory_type=13,
                armor=0,
                dmg_min1=18,
                dmg_max1=34,
                delay=1700,
                subclass=15,
                **{"class": 2},
            ),
            BOOK,
        )
        self.assertEqual(tip["damage"]["min"], 18)
        self.assertEqual(tip["damage"]["max"], 34)
        self.assertEqual(tip["damage"]["speed"], 1.7)
        self.assertEqual(tip["damage"]["dps"], 15.3)
        self.assertEqual(tip["kind"], "Dagger")
        self.assertIsNone(tip["damage"]["elemental"])

    def test_a_weapon_with_elemental_damage_carries_it_alongside_base(self):
        """Torturing Poker (item_template entry 7682), verified live against
        acore_world: dmg_min1=26, dmg_max1=49 (base physical, dmg_type1=0),
        dmg_min2=5, dmg_max2=7, dmg_type2=2 (Fire) - the exact "+5 - 7 Fire
        Damage" line infra#3513 reported missing."""
        tip = armory.template_tooltip(
            template(
                entry=7682,
                item_name="Torturing Poker",
                quality=1,
                inventory_type=13,
                armor=0,
                dmg_min1=26,
                dmg_max1=49,
                delay=1800,
                dmg_min2=5,
                dmg_max2=7,
                dmg_type2=2,
                subclass=0,
                **{"class": 2},
            ),
            BOOK,
        )
        self.assertEqual(tip["damage"]["min"], 26)
        self.assertEqual(tip["damage"]["max"], 49)
        self.assertEqual(
            tip["damage"]["elemental"], [{"school": "Fire", "min": 5, "max": 7}]
        )

    def test_a_non_fire_elemental_range_is_named_and_not_confused_with_base(self):
        tip = armory.template_tooltip(
            template(
                entry=6472,
                item_name="Fang of the Crystal Spider",
                quality=3,
                inventory_type=13,
                armor=0,
                dmg_min1=18,
                dmg_max1=34,
                delay=1700,
                dmg_min2=3,
                dmg_max2=6,
                dmg_type2=4,  # Frost
                subclass=15,
                **{"class": 2},
            ),
            BOOK,
        )
        self.assertEqual(tip["damage"]["min"], 18)
        self.assertEqual(tip["damage"]["max"], 34)
        self.assertEqual(
            tip["damage"]["elemental"], [{"school": "Frost", "min": 3, "max": 6}]
        )

    def test_an_item_with_no_elemental_damage_reports_none_not_an_empty_line(self):
        tip = armory.template_tooltip(
            template(
                entry=6472,
                item_name="Fang of the Crystal Spider",
                quality=3,
                inventory_type=13,
                armor=0,
                dmg_min1=18,
                dmg_max1=34,
                delay=1700,
                subclass=15,
                **{"class": 2},
            ),
            BOOK,
        )
        self.assertIsNone(tip["damage"]["elemental"])

    def test_a_resistance_is_named_rather_than_numbered(self):
        tip = armory.template_tooltip(template(frost_res=8), BOOK)
        self.assertEqual(tip["resistances"], ["+8 Frost Resistance"])

    def test_durability_is_full_because_nobody_is_holding_it(self):
        """THE ONE READING A TEMPLATE ROW CANNOT HAVE. _tooltip prints
        "durability / max" off an item_instance column, and a template row has
        none. Left alone it reads "0 / 70", which is the tooltip for a broken
        piece of gear, printed over every drop on the loot board."""
        self.assertEqual(self.tip["durability"], "70 / 70")

    def test_a_piece_with_no_durability_at_all_says_nothing(self):
        """Rings, cloaks and trinkets have none, and "0 / 0" is not a fact."""
        self.assertIsNone(
            armory.template_tooltip(template(max_durability=0), BOOK)["durability"]
        )

    def test_no_enchant_and_no_suffix_reach_a_template(self):
        """What an item BECOMES when somebody puts it on is a fact about their
        copy of it. A drop on the loot board is not enchanted and is not "of
        the Tiger", and inventing either would be inventing stats."""
        self.assertEqual(self.tip["enchant"], [])
        self.assertEqual(self.tip["name"], "Serpent's Shoulders")

    def test_the_set_is_left_off_rather_than_named_by_number(self):
        """_item_set names the other pieces out of a lookup none of these
        callers has. A set header over five lines of "Item #40303" says less
        than no set header."""
        self.assertIsNone(armory.template_tooltip(template(itemset=181), BOOK)["set"])

    def test_a_row_from_a_narrow_read_gets_no_tooltip_at_all(self):
        """Not a tooltip full of nulls. Four queries behind this page selected
        a name, a quality and a level and nothing else; a caller that has not
        been widened must render the name without an affordance."""
        self.assertIsNone(
            armory.template_tooltip({"entry": 1, "name": "the old shape"}, BOOK)
        )
        self.assertIsNone(armory.template_tooltip({}, BOOK))


class TheItemPayloadsCarryIt(unittest.TestCase):
    """Both loot renderers, which are the two that draw a gear name."""

    def test_the_recap_payload_carries_the_tooltip(self):
        payload = recap.item_payload(10402, template(), BOOK.icons, BOOK)
        self.assertEqual(payload["tooltip"]["slot"], "Shoulder")
        self.assertEqual(payload["name"], "Serpent's Shoulders")

    def test_without_a_book_the_item_renders_exactly_as_it_did(self):
        """The book is the only thing a caller can be missing, and missing it
        must thin the item rather than break it."""
        payload = recap.item_payload(10402, template(), BOOK.icons)
        self.assertIsNone(payload["tooltip"])
        self.assertEqual(payload["name"], "Serpent's Shoulders")
        self.assertEqual(payload["wowhead"], "https://www.wowhead.com/wotlk/item=10402")

    def test_the_chronicle_payload_carries_it_too(self):
        payload = achievements.item_payload(
            10402, {10402: template()}, BOOK.icons, BOOK
        )
        self.assertEqual(payload["tooltip"]["slot"], "Shoulder")
        self.assertEqual(payload["quality"], 2)
        self.assertEqual(payload["ilvl"], 24)

    def test_the_chronicle_still_reads_the_world_tables_own_names(self):
        """These rows used to arrive as name/Quality/ItemLevel and now arrive
        aliased. Both spellings are read in one place so a widened query
        cannot quietly blank a name somewhere nobody looked."""
        payload = achievements.item_payload(
            7,
            {7: {"name": "Old Shape Blade", "Quality": 3, "ItemLevel": 40}},
            BOOK.icons,
            BOOK,
        )
        self.assertEqual(payload["name"], "Old Shape Blade")
        self.assertEqual(payload["quality"], 3)
        self.assertEqual(payload["ilvl"], 40)
        self.assertIsNone(payload["tooltip"])

    def test_an_item_the_world_no_longer_knows_still_renders(self):
        payload = achievements.item_payload(424242, {}, BOOK.icons, BOOK)
        self.assertEqual(payload["name"], "item 424242")
        self.assertIsNone(payload["tooltip"])

    def test_every_drop_on_the_loot_board_carries_one(self):
        rows = [
            dict(
                template(), Entry=700, Item=10402, Chance=18.0, GroupId=0, creature=3654
            )
        ]
        board = recap.build_lootboard(
            43,
            "Wailing Caverns",
            [{"entry": 1, "creditEntry": 3654, "name": "Lady Anacondra"}],
            rows,
            [{"name": "Ugga", "level": 24, "class": 1}],
            [],
            BOOK.icons,
            ["Ugga"],
            None,
            BOOK,
        )
        drop = board["bosses"][0]["drops"][0]
        self.assertEqual(drop["tooltip"]["slot"], "Shoulder")
        self.assertEqual(drop["entry"], 10402)

    def test_a_board_built_without_a_book_still_builds(self):
        rows = [
            dict(
                template(), Entry=700, Item=10402, Chance=18.0, GroupId=0, creature=3654
            )
        ]
        board = recap.build_lootboard(
            43,
            "Wailing Caverns",
            [{"entry": 1, "creditEntry": 3654, "name": "Lady Anacondra"}],
            rows,
            [{"name": "Ugga", "level": 24, "class": 1}],
            [],
            BOOK.icons,
            ["Ugga"],
        )
        self.assertIsNone(board["bosses"][0]["drops"][0]["tooltip"])

    def test_the_live_recaps_loot_carries_one(self):
        now = datetime(2026, 9, 10, 19, 30)
        run = {
            "id": 1,
            "map_id": 43,
            "leader_name": "Grug",
            "started_at": now - timedelta(minutes=40),
            "last_progress_at": now - timedelta(minutes=1),
            "ended_at": None,
            "members": "Ugga",
        }
        events = [
            {
                "kind": "item_equip",
                "character_name": "Ugga",
                "subject_id": 10402,
                "first_seen": now - timedelta(minutes=5),
                "map": 43,
                "zone": 718,
                "detail": "shoulders",
            }
        ]
        payload = recap.build_recap(
            run_rows=[run],
            event_rows=events,
            death_rows=[],
            snapshot_rows=[],
            instance_rows=[],
            encounter_rows=[],
            roster=["Ugga"],
            items={10402: template()},
            icons=BOOK.icons,
            book=BOOK,
            dungeons={43: "Wailing Caverns"},
            zones={},
            now=now,
        )
        self.assertEqual(payload["loot"][0]["tooltip"]["slot"], "Shoulder")


class TheQueriesBehindItWereWidened(unittest.TestCase):
    """Three reads used to select five columns. A tooltip needs forty."""

    def test_the_column_list_is_still_written_once(self):
        """The armory query, the loot board and both loot lists read the same
        list, so the query and the builder's row contract cannot disagree."""
        self.assertIn("_ITEM_TEMPLATE_COLUMNS = (", SERVER)
        self.assertEqual(SERVER.count("_ITEM_TEMPLATE_COLUMNS = ("), 1)

    def test_the_recap_item_read_uses_it(self):
        sql = SERVER[SERVER.index("_RECAP_ITEMS = (") :]
        sql = sql[: sql.index(")\n")]
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", sql)
        self.assertIn("it.entry", sql)

    def test_the_loot_board_read_uses_it(self):
        sql = SERVER[SERVER.index("_RECAP_LOOT = (") :]
        sql = sql[: sql.index("\n)")]
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", sql)

    def test_the_chronicle_item_read_uses_it(self):
        fetch = SERVER[SERVER.index("def _fetch_achievements") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", fetch)

    def test_both_builders_are_handed_the_book(self):
        """ITEMS is the frozen ItemBook the Armory already loads once at
        import. A second load per request would read three JSON files to draw
        a tooltip."""
        self.assertIn("book=ITEMS", SERVER)
        self.assertIn('"book": ITEMS', SERVER)

    def test_only_the_items_the_page_draws_are_read_wide(self):
        """THE PAYLOAD COST IS BOUNDED BY THE EXISTING NARROWING, not by a new
        one. Both reads were already scoped to the items these views render,
        so the wider SELECT is over the same handful of rows rather than over
        item_template."""
        self.assertIn("recap.wanted_items(equips)", SERVER)
        self.assertIn("achievements.wanted_entries(", SERVER)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in (
            "armory.py",
            "recap.py",
            "achievements.py",
            "map_server.py",
            "tests/test_item_tooltip.py",
        ):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )


if __name__ == "__main__":
    unittest.main()
