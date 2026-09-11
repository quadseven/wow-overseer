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
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

BANNER = "// --- the item tooltip, on every gear name (infra#3501)"
CSS_BANNER = "/* --- the item tooltip, on every gear name (infra#3501)"
NEXT = "// --- the Decree console (infra#2597)"
NEXT_CSS = "/* --- the Decree console (infra#2597)"
BLOCK = PAGE[PAGE.index(BANNER):PAGE.index(NEXT, PAGE.index(BANNER))]
CSS = PAGE[PAGE.index(CSS_BANNER):PAGE.index(NEXT_CSS, PAGE.index(CSS_BANNER))]
LINES = PAGE[PAGE.index("function itemTipLines"):]
LINES = LINES[:LINES.index("\n}\n")]

BOOK = armory.ItemBook.load(str(HERE))


def template(**over) -> dict:
    """An item_template row shaped the way _ITEM_TEMPLATE_COLUMNS selects it.

    Written out in full rather than as a handful of keys, because the point of
    the widened read is that every one of these columns arrives; a fixture
    carrying four of them would pass while the query selected four.
    """
    row = {
        "entry": 10402, "item_name": "Serpent's Shoulders", "quality": 2,
        "item_level": 24, "required_level": 19, "max_durability": 70,
        "displayid": 5194, "class": 4, "subclass": 2, "inventory_type": 3,
        "armor": 48, "block": 0, "bonding": 1, "itemset": 0,
        "sell_price": 4521, "allowable_class": -1, "description": "",
        "dmg_min1": 0, "dmg_max1": 0, "delay": 0,
        "holy_res": 0, "fire_res": 0, "nature_res": 0, "frost_res": 0,
        "shadow_res": 0, "arcane_res": 0,
    }
    for n in range(1, 11):
        row["stat_type%d" % n] = 0
        row["stat_value%d" % n] = 0
    for n in range(1, 6):
        row["spellid_%d" % n] = 0
        row["spelltrigger_%d" % n] = 0
    row["stat_type1"], row["stat_value1"] = 3, 7     # ITEM_MOD_AGILITY
    row["stat_type2"], row["stat_value2"] = 6, 5     # ITEM_MOD_SPIRIT
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
        self.assertEqual(self.tip["sell_price"],
                         {"gold": 0, "silver": 45, "copper": 21})

    def test_a_weapon_reads_its_damage_its_speed_and_its_dps(self):
        tip = armory.template_tooltip(template(
            entry=6472, item_name="Fang of the Crystal Spider", quality=3,
            inventory_type=13, armor=0, dmg_min1=18, dmg_max1=34, delay=1700,
            subclass=15, **{"class": 2}), BOOK)
        self.assertEqual(tip["damage"]["min"], 18)
        self.assertEqual(tip["damage"]["max"], 34)
        self.assertEqual(tip["damage"]["speed"], 1.7)
        self.assertEqual(tip["damage"]["dps"], 15.3)
        self.assertEqual(tip["kind"], "Dagger")

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
            armory.template_tooltip(template(max_durability=0), BOOK)
            ["durability"])

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
        self.assertIsNone(armory.template_tooltip(
            template(itemset=181), BOOK)["set"])

    def test_a_row_from_a_narrow_read_gets_no_tooltip_at_all(self):
        """Not a tooltip full of nulls. Four queries behind this page selected
        a name, a quality and a level and nothing else; a caller that has not
        been widened must render the name without an affordance."""
        self.assertIsNone(armory.template_tooltip(
            {"entry": 1, "name": "the old shape"}, BOOK))
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
        self.assertEqual(payload["wowhead"],
                         "https://www.wowhead.com/wotlk/item=10402")

    def test_the_chronicle_payload_carries_it_too(self):
        payload = achievements.item_payload(10402, {10402: template()},
                                            BOOK.icons, BOOK)
        self.assertEqual(payload["tooltip"]["slot"], "Shoulder")
        self.assertEqual(payload["quality"], 2)
        self.assertEqual(payload["ilvl"], 24)

    def test_the_chronicle_still_reads_the_world_tables_own_names(self):
        """These rows used to arrive as name/Quality/ItemLevel and now arrive
        aliased. Both spellings are read in one place so a widened query
        cannot quietly blank a name somewhere nobody looked."""
        payload = achievements.item_payload(
            7, {7: {"name": "Old Shape Blade", "Quality": 3, "ItemLevel": 40}},
            BOOK.icons, BOOK)
        self.assertEqual(payload["name"], "Old Shape Blade")
        self.assertEqual(payload["quality"], 3)
        self.assertEqual(payload["ilvl"], 40)
        self.assertIsNone(payload["tooltip"])

    def test_an_item_the_world_no_longer_knows_still_renders(self):
        payload = achievements.item_payload(424242, {}, BOOK.icons, BOOK)
        self.assertEqual(payload["name"], "item 424242")
        self.assertIsNone(payload["tooltip"])

    def test_every_drop_on_the_loot_board_carries_one(self):
        rows = [dict(template(), Entry=700, Item=10402, Chance=18.0,
                     GroupId=0, creature=3654)]
        board = recap.build_lootboard(
            43, "Wailing Caverns",
            [{"entry": 1, "creditEntry": 3654, "name": "Lady Anacondra"}],
            rows, [{"name": "Ugga", "level": 24, "class": 1}], [],
            BOOK.icons, ["Ugga"], None, BOOK)
        drop = board["bosses"][0]["drops"][0]
        self.assertEqual(drop["tooltip"]["slot"], "Shoulder")
        self.assertEqual(drop["entry"], 10402)

    def test_a_board_built_without_a_book_still_builds(self):
        rows = [dict(template(), Entry=700, Item=10402, Chance=18.0,
                     GroupId=0, creature=3654)]
        board = recap.build_lootboard(
            43, "Wailing Caverns",
            [{"entry": 1, "creditEntry": 3654, "name": "Lady Anacondra"}],
            rows, [{"name": "Ugga", "level": 24, "class": 1}], [],
            BOOK.icons, ["Ugga"])
        self.assertIsNone(board["bosses"][0]["drops"][0]["tooltip"])

    def test_the_live_recaps_loot_carries_one(self):
        now = datetime(2026, 9, 10, 19, 30)
        run = {"id": 1, "map_id": 43, "leader_name": "Grug",
               "started_at": now - timedelta(minutes=40),
               "last_progress_at": now - timedelta(minutes=1),
               "ended_at": None, "members": "Ugga"}
        events = [{"kind": "item_equip", "character_name": "Ugga",
                   "subject_id": 10402, "first_seen": now - timedelta(minutes=5),
                   "map": 43, "zone": 718, "detail": "shoulders"}]
        payload = recap.build_recap(
            run_rows=[run], event_rows=events, death_rows=[],
            snapshot_rows=[], instance_rows=[], encounter_rows=[],
            roster=["Ugga"], items={10402: template()}, icons=BOOK.icons,
            book=BOOK, dungeons={43: "Wailing Caverns"}, zones={}, now=now)
        self.assertEqual(payload["loot"][0]["tooltip"]["slot"], "Shoulder")


class TheQueriesBehindItWereWidened(unittest.TestCase):
    """Three reads used to select five columns. A tooltip needs forty."""

    def test_the_column_list_is_still_written_once(self):
        """The armory query, the loot board and both loot lists read the same
        list, so the query and the builder's row contract cannot disagree."""
        self.assertIn("_ITEM_TEMPLATE_COLUMNS = (", SERVER)
        self.assertEqual(SERVER.count("_ITEM_TEMPLATE_COLUMNS = ("), 1)

    def test_the_recap_item_read_uses_it(self):
        sql = SERVER[SERVER.index("_RECAP_ITEMS = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", sql)
        self.assertIn("it.entry", sql)

    def test_the_loot_board_read_uses_it(self):
        sql = SERVER[SERVER.index("_RECAP_LOOT = ("):]
        sql = sql[:sql.index("\n)")]
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", sql)

    def test_the_chronicle_item_read_uses_it(self):
        fetch = SERVER[SERVER.index("def _fetch_achievements"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
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


class ThePanelIsPlacedByCssAndMeasuresNothing(unittest.TestCase):
    """The lesson .acard already wrote down, kept for the second panel.

    A tooltip positioned beside the thing it describes needs a hover branch, a
    pin and a rule for every screen edge it can run off. This one is pinned to
    the viewport, so it cannot be clipped and cannot render off-screen for an
    item at an edge, at any size.
    """

    def test_the_panel_is_outside_every_view(self):
        """It is drawn over whichever tab is open, so it cannot be a child of
        one of them."""
        body = PAGE[PAGE.index("<body>"):PAGE.index("</body>")]
        self.assertIn('<div id="itemtip" hidden>', body)
        for section in ('<section id="chronicle">', '<section id="armory">',
                        '<section id="bags">'):
            block = body[body.index(section):]
            block = block[:block.index("</section>")]
            self.assertNotIn('id="itemtip"', block, section)

    def test_nothing_in_the_block_measures_a_coordinate(self):
        for measured in ("getBoundingClientRect", "window.innerWidth",
                         "innerHeight", "style.left", "style.top",
                         "style.bottom", "offsetWidth"):
            self.assertNotIn(measured, BLOCK, measured)

    def test_the_css_pins_it_to_the_viewport(self):
        self.assertIn("position:fixed", CSS)
        self.assertIn("bottom:0", CSS)
        self.assertIn("max-height:min(70vh", CSS)

    def test_it_scrolls_inside_itself_rather_than_growing(self):
        """A long item must not push its own way out off the bottom. The
        reading scrolls and the two rows under it do not, which is the same
        arrangement .aclose already has."""
        markup = PAGE[PAGE.index('id="itemtipbody"'):]
        self.assertIn('class="adetail"', markup[:markup.index(">")])
        rule = PAGE[PAGE.index("  .adetail {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("overflow-y:auto", rule)

    def test_it_carries_its_own_dark_ground(self):
        """Item quality is a colour in this game and uncommon green on white
        is close to invisible, which is why #armory and #bags each override
        the palette. This panel is a child of the body, so it is inside
        neither and has to say so itself."""
        scope = CSS[CSS.index("#itemtip {"):]
        scope = scope[:scope.index("}")]
        for token in ("--bg:", "--panel:", "--line:", "--text:", "--dim:",
                      "--on-dark:", "--on-dark-dim:", "--on-dark-faint:"):
            self.assertIn(token, scope, token)

    def test_the_way_out_is_a_thumb_sized_row(self):
        rule = CSS[CSS.index("#itemtipout, #itemtipclose {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("min-height:44px", rule)


class TheNameIsNoLongerALink(unittest.TestCase):
    """The whole change, asserted at the one place it is made."""

    def test_the_gear_name_is_a_button(self):
        """An anchor with an href is what raises the browser's own menu on a
        long press, and no amount of cancelling the click takes that away."""
        fn = BLOCK[BLOCK.index("function itemTipName"):]
        fn = fn[:fn.index("\n}\n")]
        self.assertIn('el("button", "iname " + cls, label)', fn)
        self.assertNotIn('createElement("a")', fn)
        self.assertNotIn(".href", fn)

    def test_the_long_press_callout_is_refused_in_css(self):
        rule = CSS[CSS.index("  .iname {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("-webkit-touch-callout:none", rule)
        self.assertIn("touch-action:manipulation", rule)

    def test_a_name_with_nothing_behind_it_is_not_a_control(self):
        """An affordance that opens an empty panel is worse than none."""
        fn = BLOCK[BLOCK.index("function itemTipName"):]
        fn = fn[:fn.index("\n}\n")]
        self.assertIn("if (!item.tooltip) return el(\"span\", cls, label);", fn)

    def test_the_chronicles_loot_line_goes_through_it(self):
        fn = PAGE[PAGE.index("function chrItem"):]
        fn = fn[:fn.index("\n}\n")]
        self.assertIn("itemTipName(", fn)
        self.assertNotIn("a.href", fn)
        self.assertNotIn('a.target = "_blank"', fn)


class TheInteractionIsPredictable(unittest.TestCase):
    """One panel, and three ways to put it away: the same name again, a tap
    outside, and Escape. The same contract the Armory's item card keeps, which
    is why it is copied rather than reinvented."""

    def test_the_same_name_again_closes_it(self):
        self.assertIn("if (tipShown.at === b && tipShown.pinned) closeItemTip();",
                      BLOCK)

    def test_a_tap_outside_closes_it(self):
        self.assertIn('t.closest("#itemtip, .iname")', BLOCK)
        self.assertIn('document.addEventListener("pointerdown"', BLOCK)

    def test_escape_closes_it(self):
        self.assertIn('if (e.key === "Escape") closeItemTip();', BLOCK)

    def test_the_close_row_closes_it(self):
        self.assertIn('tipClose.addEventListener("click", closeItemTip);', BLOCK)

    def test_a_hover_may_not_take_away_a_panel_a_tap_put_up(self):
        """Otherwise moving a mouse across the list on the way to the close
        button takes the panel away under the cursor."""
        self.assertIn("if (tipShown.pinned) return;", BLOCK)

    def test_a_touch_never_takes_the_hover_path(self):
        """A touch that opened the panel on entering would cover the item
        under the thumb that was reaching for it. Both halves of the test are
        needed: the media query says nothing about the gesture in hand on a
        laptop with a touchscreen, and the pointer type says nothing about a
        browser that synthesises a mouse for a tap."""
        self.assertIn('e.pointerType !== "mouse"', BLOCK)
        self.assertIn('matchMedia("(hover: hover) and (pointer: fine)")', BLOCK)

    def test_which_name_is_open_is_the_button_and_not_the_entry(self):
        """The same sword can be on the page twice, worn by two members.
        Keyed by entry, tapping the second would close the first's panel."""
        self.assertIn("openItemTip(b, item", BLOCK)
        self.assertNotIn("item.entry", BLOCK)

    def test_the_control_says_what_it_opens(self):
        self.assertIn('b.setAttribute("aria-controls", "itemtip");', BLOCK)
        self.assertIn('at.setAttribute("aria-expanded", "true");', BLOCK)


class ThereIsOnlyOneRenderer(unittest.TestCase):
    """The Armory's item card already drew every one of these lines. What was
    asked for is that card on every gear name, not a second one beside it."""

    def test_the_armorys_card_draws_through_it(self):
        fn = PAGE[PAGE.index("function renderDetail"):]
        fn = fn[:fn.index("\n}\n")]
        self.assertIn("itemTipLines(c.detail, s.tooltip, renderProvenance(c, s));",
                      fn)

    def test_the_panel_draws_through_the_same_one(self):
        self.assertIn("itemTipLines(tipBody, item.tooltip, null);", BLOCK)

    def test_it_is_declared_exactly_once(self):
        self.assertEqual(PAGE.count("\nfunction itemTipLines("), 1)

    def test_it_draws_every_line_the_game_draws(self):
        for field in ("t.item_level", "t.binding", "t.slot", "t.kind",
                      "t.damage", "t.armor", "t.block", "t.stats",
                      "t.resistances", "t.enchant", "t.durability",
                      "t.classes", "t.requires_level", "t.effects",
                      "t.set.pieces", "t.set.bonuses", "t.flavor",
                      "t.sell_price"):
            self.assertIn(field, LINES, field)

    def test_the_armorys_own_sentence_is_handed_in_and_not_reached_for(self):
        """Where the item was last seen worn is a line only the Armory has: a
        drop on the loot board has nobody to have worn it yet."""
        self.assertIn("if (note) node.appendChild(note);", LINES)
        self.assertNotIn("arm.provenance", LINES)

    def test_nothing_from_a_payload_is_parsed_as_markup(self):
        """Item names come from the world database and are not trusted."""
        for parsed in ("innerHTML", "insertAdjacentHTML"):
            self.assertNotIn(parsed, BLOCK, parsed)
            self.assertNotIn(parsed, LINES, parsed)


class TheWayOutIsStillThere(unittest.TestCase):
    """Somebody who actually wants the full page can still get to it. It is a
    deliberate row inside the panel rather than the default tap."""

    def test_the_address_is_the_modules_and_not_composed_here(self):
        self.assertIn("tipOut.href = item.wowhead;", BLOCK)
        self.assertNotIn("https://", BLOCK)

    def test_it_refuses_the_opener(self):
        markup = PAGE[PAGE.index('id="itemtipout"'):]
        markup = markup[:markup.index(">")]
        self.assertIn('rel="noopener"', markup)
        self.assertIn('target="_blank"', markup)

    def test_no_tooltip_script_is_loaded_from_anywhere(self):
        """The point of building these lines here. wow.zamimg.com declines any
        browser whose Origin it does not recognise, which is why the 3D
        model's data comes through this server; a tooltip that leaned on
        Wowhead's script would be the one part of this page that stops
        working off the tailnet."""
        self.assertNotIn("<script src=", PAGE)
        self.assertNotIn("wowhead.com/widgets", PAGE)
        self.assertNotIn("whTooltips", PAGE)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in ("index.html", "armory.py", "recap.py", "achievements.py",
                     "map_server.py", "tests/test_item_tooltip.py"):
            self.assertNotIn(chr(0x2014),
                             (HERE / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
