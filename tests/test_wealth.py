"""The Wealth and Bags builder: inventory rows in, purses and bag grids out.

The rules here are the ones that cost something to get wrong, and almost all
of them are rules about NOT lying. A bag drawn as only the things in it hides
the fact that it is full. A vendor total that forgets stack counts is wrong
by a factor of twenty on trade goods. A slot number taken at face value puts
the first item of the backpack in the sixteenth square, because the backpack
starts at 23. An "auctions sold" list that renders empty without a word of
explanation says the family has never sold anything, when what is actually
true is that the table cannot record a completed sale at all.

Every one of those, done the obvious way, produces a panel that looks
entirely plausible and is wrong, which is the exact failure mode the Armory
suite was written against too.

Tickets: quadseven/mod-overseer#88, quadseven/mod-overseer#147.
"""
import pathlib
import unittest

import family
import panel
import wealth

HERE = pathlib.Path(__file__).resolve().parent.parent

# Taken from bonds rather than retyped: WHO the family is belongs there, and
# a second list here is a second answer that can disagree with it.
ROSTER = family.roster()
FIRST, SECOND = ROSTER[0], ROSTER[1]

WARRIOR = 1
POOR, COMMON, UNCOMMON, RARE, EPIC = 0, 1, 2, 3, 4

# The three geographies, read off panel's own ranges so this suite cannot
# drift from the module it is testing.
EQUIPPED_SLOT = 15                     # a weapon slot on the paper doll
BAG_SLOT = panel._BAG_SLOTS.start      # the first carried bag slot
BACKPACK_SLOT = panel._BACKPACK_SLOTS.start
BANK_BAG_SLOT = panel._BANK_BAG_SLOTS.start
BANK_SLOT = panel._BACKPACK_SLOTS.stop  # a bank slot: owned, not carried

GOLD = wealth.COPPER_PER_GOLD


def char(**kw):
    row = {"name": FIRST, "level": 25, "class": WARRIOR, "money": 166 * GOLD}
    row.update(kw)
    return row


def item(bag=0, slot=BACKPACK_SLOT, **kw):
    """One character_inventory row joined to its template, as the adapter sends it."""
    row = {
        "name": FIRST, "bag": bag, "slot": slot, "item_guid": 900 + slot,
        "entry": 1234, "count": 1, "item_name": "Linen Cloth",
        "quality": COMMON, "item_level": 1, "sell_price": 10,
        "class": 7, "subclass": 5, "displayid": 55, "container_slots": 0,
    }
    row.update(kw)
    return row


def bag(slot=BAG_SLOT, guid=7001, slots=6, **kw):
    return item(bag=0, slot=slot, item_guid=guid, entry=805,
                item_name="Small Red Pouch", quality=COMMON, sell_price=100,
                **{"class": 1, "subclass": 0, "displayid": 60,
                   "container_slots": slots, **kw})


def auction(**kw):
    row = {
        "id": 1, "startbid": 5000, "lastbid": 0, "buyoutprice": 20000,
        "deposit": 300, "time": 1770000000, "owner_name": FIRST,
        "buyer_name": None, "entry": 1234, "count": 2,
        "item_name": "Linen Cloth", "quality": COMMON, "item_level": 1,
        "sell_price": 10, "class": 7, "subclass": 5, "displayid": 55,
        "container_slots": 0,
    }
    row.update(kw)
    return row


ICONS = {55: "inv_fabric_linen_01", 60: "inv_misc_bag_09", 61: "inv_sword_04"}


class Coins(unittest.TestCase):
    def test_copper_becomes_three_coins(self):
        self.assertEqual(wealth.coins(1666355),
                         {"gold": 166, "silver": 63, "copper": 55,
                          "total": 1666355, "text": "166g 63s 55c"})

    def test_nothing_is_a_real_answer_rather_than_no_answer(self):
        """A quest item is worth nothing to a vendor and the panel must be
        able to say so. armory.money() returns None for this, which is right
        for a tooltip line it should not draw and wrong for a total."""
        self.assertEqual(wealth.coins(0),
                         {"gold": 0, "silver": 0, "copper": 0, "total": 0,
                          "text": wealth.NOTHING})
        self.assertEqual(wealth.coins(None)["total"], 0)

    def test_the_word_for_an_amount_is_the_modules_and_not_the_pages(self):
        """The page draws money twice: as three coloured spans where there is
        room, and as one string where there is not (a tooltip line, a stat
        note). The second used to be built in JavaScript, which meant the word
        for an empty purse was typed into index.html where nothing tests it."""
        self.assertEqual(wealth.coins(0)["text"], "nothing")
        self.assertEqual(wealth.coins(7)["text"], "7c")
        # Silver whenever gold is, so "1g 0s 4c" reads as one amount rather
        # than as a gold piece and four coppers that lost something between.
        self.assertEqual(wealth.coins(10004)["text"], "1g 0s 4c")
        self.assertEqual(wealth.coins(504)["text"], "5s 4c")

    def test_the_denominations_do_not_carry_into_each_other(self):
        """One silver is a hundred copper and one gold a hundred silver. The
        one bug this arithmetic can have is a factor of a hundred, and it
        would render as a plausible number."""
        self.assertEqual(wealth.coins(99), {"gold": 0, "silver": 0, "copper": 99,
                                            "total": 99, "text": "99c"})
        self.assertEqual(wealth.coins(100)["silver"], 1)
        self.assertEqual(wealth.coins(9999)["gold"], 0)
        self.assertEqual(wealth.coins(10000)["gold"], 1)

    def test_a_negative_purse_reads_as_nothing(self):
        """`characters.money` is unsigned so this cannot come from the world,
        but three negative coins would look like a rendering bug rather than
        like bad data."""
        self.assertEqual(wealth.coins(-500)["total"], 0)


class QualityAndKind(unittest.TestCase):
    def test_every_quality_the_game_has_is_named(self):
        for quality, word in wealth.QUALITY_NAMES.items():
            self.assertEqual(wealth.quality_name(quality), word)

    def test_a_quality_nobody_knows_says_so(self):
        """A LEFT JOIN miss has no quality at all. Reading that as common
        would draw a white border on something that might be an epic."""
        self.assertEqual(wealth.quality_name(None), wealth.UNKNOWN_QUALITY)
        self.assertEqual(wealth.quality_name(99), wealth.UNKNOWN_QUALITY)

    def test_weapons_and_armour_are_named_by_their_subclass(self):
        """'Sword' and 'Mail' are what a player reads. 'Weapon' and 'Armor'
        are what a database reads."""
        self.assertEqual(wealth.item_kind({"class": 2, "subclass": 7}), "Sword")
        self.assertEqual(wealth.item_kind({"class": 4, "subclass": 3}), "Mail")

    def test_everything_else_is_named_by_its_class(self):
        """The subclass of a consumable is finer than anybody needs when the
        question is why a bag is full."""
        self.assertEqual(wealth.item_kind({"class": 7, "subclass": 5}), "Trade Goods")
        self.assertEqual(wealth.item_kind({"class": 12, "subclass": 0}), "Quest")
        self.assertEqual(wealth.item_kind({"class": 1, "subclass": 0}), "Container")

    def test_a_weapon_with_an_unknown_subclass_is_still_a_weapon(self):
        self.assertEqual(wealth.item_kind({"class": 2, "subclass": 99}), "Weapon")
        self.assertEqual(wealth.item_kind({"class": 4, "subclass": 99}), "Armor")

    def test_an_item_the_world_does_not_know_has_no_kind(self):
        self.assertIsNone(wealth.item_kind({"class": None, "subclass": None}))

    def test_a_quality_the_game_does_not_define_is_not_a_quality(self):
        """The counting half of the module has to agree with the naming
        half. Before this, a custom item stamped quality 99 was NAMED
        unknown and COUNTED as better than an epic in the same payload."""
        for quality in wealth.QUALITY_NAMES:
            self.assertEqual(wealth.known_quality(quality), quality)
        self.assertIsNone(wealth.known_quality(99))
        self.assertIsNone(wealth.known_quality(8))
        self.assertIsNone(wealth.known_quality(-1))
        self.assertIsNone(wealth.known_quality(None))

    def test_an_unknown_quality_never_satisfies_a_floor(self):
        """Not even a floor of zero. It might be an epic and it might be a
        vendor shirt, and guessing upward is how a made-up rare gets into
        the family's rare count."""
        self.assertTrue(wealth.at_least(RARE, wealth.NOTABLE_QUALITY))
        self.assertTrue(wealth.at_least(UNCOMMON, wealth.NOTABLE_QUALITY))
        self.assertFalse(wealth.at_least(COMMON, wealth.NOTABLE_QUALITY))
        self.assertFalse(wealth.at_least(99, 0))
        self.assertFalse(wealth.at_least(None, 0))

    def test_an_unnamed_item_says_which_item_it_is(self):
        """A custom or removed item genuinely occupies a slot. Rendering it
        as a blank square would understate how full the bag is."""
        self.assertEqual(wealth.item_name({"item_name": None, "entry": 77}),
                         "Item #77")
        self.assertEqual(wealth.item_name({"item_name": "Linen Cloth", "entry": 77}),
                         "Linen Cloth")


class StackValue(unittest.TestCase):
    def test_a_stack_is_worth_its_count_times_the_unit_price(self):
        """SellPrice is per unit. Twenty linen is twenty times one linen, and
        forgetting that understates a bag by an order of magnitude."""
        self.assertEqual(wealth.stack_value({"sell_price": 10, "count": 20}), 200)

    def test_an_unsellable_item_is_worth_nothing_not_unknown(self):
        """SellPrice 0 is the game saying this cannot be sold at all, which
        is what every quest item and the hearthstone are."""
        self.assertEqual(wealth.stack_value({"sell_price": 0, "count": 5}), 0)
        self.assertEqual(wealth.stack_value({"sell_price": None, "count": 5}), 0)

    def test_a_missing_count_is_one_item_not_none(self):
        self.assertEqual(wealth.stack_value({"sell_price": 7, "count": None}), 7)


class ItemPayload(unittest.TestCase):
    def setUp(self):
        self.payload = wealth.item_payload(
            item(count=20, sell_price=10), ICONS, wealth.CARRIED, "Backpack", 3)

    def test_the_page_gets_the_stack_value_not_the_unit_price(self):
        self.assertEqual(self.payload["sell_price"], 10)
        self.assertEqual(self.payload["value_copper"], 200)
        self.assertEqual(self.payload["value"]["silver"], 2)

    def test_the_icon_comes_from_the_frozen_book_by_display_id(self):
        self.assertEqual(self.payload["icon"], "inv_fabric_linen_01")

    def test_an_item_with_no_known_display_gets_no_icon_rather_than_a_broken_one(self):
        """A blank square reads as a broken picture. The page draws the name
        instead, exactly as the Armory paper doll does."""
        self.assertIsNone(wealth.item_payload(item(displayid=9999), ICONS,
                                              wealth.CARRIED)["icon"])

    def test_the_tooltip_link_is_the_items_own_page(self):
        self.assertEqual(self.payload["wowhead"],
                         "https://www.wowhead.com/wotlk/item=1234")

    def test_where_and_which_container_travel_with_the_item(self):
        self.assertEqual(self.payload["where"], wealth.CARRIED)
        self.assertEqual(self.payload["container"], "Backpack")

    def test_the_position_is_the_index_inside_the_container_not_the_row_number(self):
        """The backpack's sixteen slots are 23 to 38. Drawing an item at its
        raw slot number would put the first one in the twenty-fourth square
        of a sixteen-square grid, which is to say nowhere."""
        self.assertEqual(self.payload["slot"], BACKPACK_SLOT)
        self.assertEqual(self.payload["position"], 3)


class WhereEverythingIs(unittest.TestCase):
    """split_inventory: the geography, worked out against the live database."""

    def test_bag_zero_below_nineteen_is_worn_not_carried(self):
        split = wealth.split_inventory([item(slot=EQUIPPED_SLOT)], ICONS)
        self.assertEqual(len(split["equipped"]), 1)
        self.assertEqual(split["equipped"][0]["where"], wealth.EQUIPPED)
        self.assertEqual(sum(len(c["items"]) for c in split["containers"]), 0)

    def test_a_worn_item_is_labelled_with_the_slot_it_is_worn_in(self):
        split = wealth.split_inventory([item(slot=EQUIPPED_SLOT)], ICONS)
        self.assertEqual(split["equipped"][0]["container"],
                         wealth.EQUIPPED_SLOTS[EQUIPPED_SLOT])

    def test_the_backpack_is_always_there_even_with_nothing_in_it(self):
        """Every character has one and it is sixteen slots. A container list
        that omitted it would report a character as having no room at all
        rather than as having sixteen empty squares."""
        split = wealth.split_inventory([], ICONS)
        self.assertEqual(len(split["containers"]), 1)
        pack = split["containers"][0]
        self.assertEqual(pack["key"], wealth.BACKPACK)
        self.assertEqual(pack["slots"], wealth.BACKPACK_SLOTS)
        self.assertEqual(pack["used"], 0)
        self.assertEqual(pack["free"], wealth.BACKPACK_SLOTS)

    def test_a_bag_slot_becomes_a_container_sized_by_its_template(self):
        split = wealth.split_inventory([bag(slots=8)], ICONS)
        self.assertEqual(len(split["containers"]), 2)
        self.assertEqual(split["containers"][1]["slots"], 8)
        self.assertEqual(split["containers"][1]["name"], "Small Red Pouch")
        self.assertEqual(split["containers"][1]["position"], 1)

    def test_a_bag_carries_its_own_icon_quality_and_link(self):
        """A bag is an item like anything else, and the page draws it as one."""
        pouch = wealth.split_inventory([bag()], ICONS)["containers"][1]
        self.assertEqual(pouch["icon"], "inv_misc_bag_09")
        self.assertEqual(pouch["quality"], COMMON)
        self.assertEqual(pouch["quality_name"], "common")
        self.assertEqual(pouch["wowhead"], "https://www.wowhead.com/wotlk/item=805")

    def test_the_backpack_has_no_item_behind_it(self):
        """It is not an item, so it has no entry, no quality and no page to
        link to - and inventing one would link to something that is not it."""
        pack = wealth.split_inventory([], ICONS)["containers"][0]
        self.assertIsNone(pack["entry"])
        self.assertIsNone(pack["quality"])
        self.assertIsNone(pack["wowhead"])

    def test_an_item_inside_a_bag_lands_in_that_bag(self):
        """`bag` is the item_instance guid of the CONTAINER, not a bag index.
        Reading it as an index would file everything under bag 377158."""
        rows = [bag(guid=7001, slots=6),
                item(bag=7001, slot=2, entry=999, item_name="Copper Ore")]
        split = wealth.split_inventory(rows, ICONS)
        pouch = split["containers"][1]
        self.assertEqual(pouch["used"], 1)
        self.assertEqual(pouch["items"][0]["name"], "Copper Ore")
        self.assertEqual(pouch["items"][0]["container"], "Small Red Pouch")
        self.assertEqual(pouch["items"][0]["position"], 2)

    def test_items_in_a_bag_are_drawn_in_slot_order(self):
        rows = [bag(guid=7001, slots=6),
                item(bag=7001, slot=4, entry=2, item_name="Second"),
                item(bag=7001, slot=1, entry=1, item_name="First")]
        pouch = wealth.split_inventory(rows, ICONS)["containers"][1]
        self.assertEqual([i["name"] for i in pouch["items"]], ["First", "Second"])

    def test_the_backpack_holds_bag_zero_from_twenty_three_up(self):
        rows = [item(slot=BACKPACK_SLOT), item(slot=BACKPACK_SLOT + 1, entry=2)]
        pack = wealth.split_inventory(rows, ICONS)["containers"][0]
        self.assertEqual(pack["used"], 2)
        self.assertEqual([i["position"] for i in pack["items"]], [0, 1])

    def test_the_bank_is_owned_but_not_carried(self):
        """Bank slots, bank bags, the keyring and buyback are real
        possessions this view does not draw. Counting them as carried would
        report a character as out of room who has half a bag free."""
        rows = [item(slot=BANK_SLOT), item(slot=BANK_BAG_SLOT, item_guid=8001)]
        split = wealth.split_inventory(rows, ICONS)
        self.assertEqual(split["elsewhere"], 2)
        self.assertEqual(split["bank_bags"], 1)
        self.assertEqual(len(split["containers"]), 1)

    def test_the_contents_of_a_bank_bag_are_elsewhere_not_lost(self):
        """A row whose container is not carried must still be counted, or the
        panel silently understates what somebody owns."""
        rows = [item(slot=BANK_BAG_SLOT, item_guid=8001),
                item(bag=8001, slot=0, entry=5)]
        split = wealth.split_inventory(rows, ICONS)
        self.assertEqual(split["elsewhere"], 2)

    def test_a_bag_holding_more_than_its_template_allows_never_reads_as_negative(self):
        """The world database and the core disagreeing about a container size
        is a data problem. Minus two free slots looks like a rendering bug."""
        rows = [bag(guid=7001, slots=1),
                item(bag=7001, slot=0, entry=1),
                item(bag=7001, slot=1, entry=2)]
        pouch = wealth.split_inventory(rows, ICONS)["containers"][1]
        self.assertEqual(pouch["used"], 2)
        self.assertEqual(pouch["free"], 0)


class Capacity(unittest.TestCase):
    def test_room_is_the_backpack_plus_every_bag(self):
        rows = [bag(slot=BAG_SLOT, guid=7001, slots=6),
                bag(slot=BAG_SLOT + 1, guid=7002, slots=8),
                item(bag=7001, slot=0, entry=1)]
        cap = wealth.build_capacity(wealth.split_inventory(rows, ICONS)["containers"])
        self.assertEqual(cap["slots"], wealth.BACKPACK_SLOTS + 14)
        self.assertEqual(cap["used"], 1)
        self.assertEqual(cap["free"], wealth.BACKPACK_SLOTS + 13)
        self.assertEqual(cap["bags"], 2)

    def test_the_bag_containers_are_not_counted_as_things_being_carried(self):
        """A bag occupies a bag SLOT, not a bag slot's worth of cargo. Adding
        it to `used` would report four bags as four items nobody can find."""
        rows = [bag(slot=BAG_SLOT, guid=7001, slots=6)]
        cap = wealth.build_capacity(wealth.split_inventory(rows, ICONS)["containers"])
        self.assertEqual(cap["used"], 0)

    def test_empty_bag_slots_are_the_actionable_half_of_a_full_inventory(self):
        """Three empty bag slots is a bag somebody could hand him, which is a
        different fix from selling something."""
        rows = [bag(slot=BAG_SLOT, guid=7001, slots=6)]
        cap = wealth.build_capacity(wealth.split_inventory(rows, ICONS)["containers"])
        self.assertEqual(cap["bag_slots"], wealth.BAG_POSITIONS)
        self.assertEqual(cap["empty_bag_slots"], wealth.BAG_POSITIONS - 1)

    def test_full_is_a_flag_rather_than_a_sum_the_page_has_to_redo(self):
        """A bot with no room can never finish a loot, so this is the one
        state on the view a person acts on, and deciding it here is what
        stops two surfaces disagreeing about who is stuck."""
        rows = [item(slot=BACKPACK_SLOT + n, entry=n)
                for n in range(wealth.BACKPACK_SLOTS)]
        cap = wealth.build_capacity(wealth.split_inventory(rows, ICONS)["containers"])
        self.assertEqual(cap["free"], 0)
        self.assertTrue(cap["full"])

    def test_one_free_slot_is_not_full(self):
        rows = [item(slot=BACKPACK_SLOT + n, entry=n)
                for n in range(wealth.BACKPACK_SLOTS - 1)]
        cap = wealth.build_capacity(wealth.split_inventory(rows, ICONS)["containers"])
        self.assertEqual(cap["free"], 1)
        self.assertFalse(cap["full"])


class Tally(unittest.TestCase):
    def items(self, *specs):
        return [wealth.item_payload(item(**spec), ICONS, wealth.CARRIED)
                for spec in specs]

    def test_stacks_and_units_are_different_numbers_and_both_are_reported(self):
        """One stack of twenty linen is one slot and twenty items. Saying
        '1 item' about it is as wrong as saying '20 slots'."""
        t = wealth.tally(self.items({"count": 20}, {"count": 1, "entry": 2}))
        self.assertEqual(t["items"], 2)
        self.assertEqual(t["units"], 21)

    def test_the_vendor_total_is_the_sum_of_the_stacks(self):
        t = wealth.tally(self.items({"count": 20, "sell_price": 10},
                                    {"count": 1, "sell_price": 1770, "entry": 2}))
        self.assertEqual(t["vendor_copper"], 1970)
        self.assertEqual(t["vendor"], wealth.coins(1970))

    def test_the_quality_breakdown_reads_best_first(self):
        """'One rare, fifteen greens' answers the question. The other order
        makes a person hunt for the number that matters."""
        t = wealth.tally(self.items({"quality": COMMON}, {"quality": RARE, "entry": 2},
                                    {"quality": UNCOMMON, "entry": 3}))
        self.assertEqual([q["quality"] for q in t["by_quality"]],
                         [RARE, UNCOMMON, COMMON])
        self.assertEqual([q["name"] for q in t["by_quality"]],
                         ["rare", "uncommon", "common"])

    def test_an_unknown_quality_is_counted_last_rather_than_dropped(self):
        """A custom item is still in the bag. Dropping it from the breakdown
        would make the counts disagree with the grid beside them."""
        t = wealth.tally(self.items({"quality": None}, {"quality": COMMON, "entry": 2}))
        self.assertEqual(t["by_quality"][-1],
                         {"quality": None, "name": wealth.UNKNOWN_QUALITY,
                          "count": 1, "label": "1 unknown"})

    def test_green_and_better_are_counted_separately_from_rare_and_better(self):
        t = wealth.tally(self.items({"quality": POOR}, {"quality": COMMON, "entry": 2},
                                    {"quality": UNCOMMON, "entry": 3},
                                    {"quality": RARE, "entry": 4},
                                    {"quality": EPIC, "entry": 5}))
        self.assertEqual(t["notable"], 3)
        self.assertEqual(t["rare_or_better"], 2)

    def test_a_quality_outside_the_games_own_range_is_counted_as_unknown(self):
        """Reported by Grug Elder (`type-safety-gap`) and real: the world
        database column is a tinyint and a module is free to write 8 into
        it. Counting it as better than an epic put a fictional rare in the
        family headline while the chip beside it said 'unknown'."""
        t = wealth.tally(self.items({"quality": 99}, {"quality": RARE, "entry": 2}))
        self.assertEqual(t["rare_or_better"], 1)
        self.assertEqual(t["notable"], 1)
        self.assertEqual(t["by_quality"][-1],
                         {"quality": None, "name": wealth.UNKNOWN_QUALITY,
                          "count": 1, "label": "1 unknown"})

    def test_an_empty_list_tallies_to_zero_rather_than_to_nothing(self):
        t = wealth.tally([])
        self.assertEqual(t["items"], 0)
        self.assertEqual(t["vendor"]["total"], 0)
        self.assertEqual(t["by_quality"], [])


class Notable(unittest.TestCase):
    def items(self, *specs):
        return [wealth.item_payload(item(**spec), ICONS, wealth.CARRIED)
                for spec in specs]

    def test_only_green_and_better_are_named(self):
        """A stack of linen is worth more copper than most of the greens they
        haul. The question this list answers is a quality question."""
        picked = wealth.notable_items(self.items(
            {"quality": POOR, "sell_price": 99999},
            {"quality": COMMON, "entry": 2, "sell_price": 99999},
            {"quality": UNCOMMON, "entry": 3, "sell_price": 1}))
        self.assertEqual([i["quality"] for i in picked], [UNCOMMON])

    def test_the_best_comes_first_then_the_most_valuable(self):
        picked = wealth.notable_items(self.items(
            {"quality": UNCOMMON, "entry": 1, "sell_price": 500},
            {"quality": RARE, "entry": 2, "sell_price": 10},
            {"quality": UNCOMMON, "entry": 3, "sell_price": 900}))
        self.assertEqual([i["entry"] for i in picked], [2, 3, 1])

    def test_ties_are_broken_by_name_so_the_list_does_not_reshuffle(self):
        """A list that reorders itself every thirty seconds is a list nobody
        can read on a phone."""
        picked = wealth.notable_items(self.items(
            {"quality": RARE, "entry": 1, "sell_price": 5, "item_name": "Zed"},
            {"quality": RARE, "entry": 2, "sell_price": 5, "item_name": "Abe"}))
        self.assertEqual([i["name"] for i in picked], ["Abe", "Zed"])

    def test_an_item_of_unknown_quality_is_never_promoted_into_the_list(self):
        """It might be an epic and it might be a vendor shirt. Guessing
        upward would put a made-up rare in the family's rare count. A
        quality the game does not define counts as unknown here too, not as
        a very good item."""
        self.assertEqual(wealth.notable_items(self.items({"quality": None})), [])
        self.assertEqual(wealth.notable_items(self.items({"quality": 99})), [])


class WorthNaming(unittest.TestCase):
    def worn(self, quality, entry):
        return wealth.item_payload(item(quality=quality, entry=entry), ICONS,
                                   wealth.EQUIPPED)

    def carried(self, quality, entry):
        return wealth.item_payload(item(quality=quality, entry=entry), ICONS,
                                   wealth.CARRIED)

    def test_a_green_in_a_bag_is_named(self):
        picked = wealth.worth_naming([], [self.carried(UNCOMMON, 1)])
        self.assertEqual([i["entry"] for i in picked], [1])

    def test_a_green_being_worn_is_not_named_twice(self):
        """It is already drawn life size on the paper doll directly above.
        There are a hundred and ten of them across the family, and naming
        every one buries the eleven rares that are the actual finding."""
        self.assertEqual(wealth.worth_naming([self.worn(UNCOMMON, 1)], []), [])

    def test_a_rare_being_worn_still_earns_its_line(self):
        """'Who has the good gear' is a question this list gets asked, and
        the paper doll answers it one character at a time."""
        picked = wealth.worth_naming([self.worn(RARE, 1)], [])
        self.assertEqual([i["entry"] for i in picked], [1])
        self.assertEqual(picked[0]["where"], wealth.EQUIPPED)

    def test_a_worn_epic_is_named_too(self):
        self.assertEqual(len(wealth.worth_naming([self.worn(EPIC, 1)], [])), 1)

    def test_a_common_in_a_bag_is_not_named(self):
        self.assertEqual(wealth.worth_naming([], [self.carried(COMMON, 1)]), [])

    def test_a_worn_item_of_undefined_quality_is_not_mistaken_for_a_rare(self):
        """The worn half has the same floor and must ask the same question,
        or the one list that is meant to surface real rares fills up with
        whatever the world database happened to stamp."""
        self.assertEqual(wealth.worth_naming([self.worn(99, 1)], []), [])

    def test_the_two_sources_end_up_in_one_list_sorted_together(self):
        """A rare in a bag next to a rare on a body is exactly the comparison
        somebody is trying to make, so they cannot be two lists."""
        picked = wealth.worth_naming([self.worn(RARE, 1)],
                                     [self.carried(UNCOMMON, 2)])
        self.assertEqual([i["entry"] for i in picked], [1, 2])


class OneMember(unittest.TestCase):
    def build(self, rows, **kw):
        return wealth.build_member(FIRST, char(**kw), rows, ICONS)

    def test_the_purse_is_the_characters_own_money_column(self):
        m = self.build([], money=1666355)
        self.assertEqual(m["money"]["gold"], 166)

    def test_a_member_with_no_saved_character_still_gets_a_card(self):
        """A family view that quietly drops somebody is the exact failure the
        Armory tab was built to stop, and it is no less a failure here."""
        m = wealth.build_member(FIRST, None, [], ICONS)
        self.assertFalse(m["present"])
        self.assertEqual(m["name"], FIRST)
        self.assertTrue(m["role"])

    def test_carried_counts_the_bags_and_the_backpack_and_not_what_is_worn(self):
        """The money story is what a trip to a vendor is worth. A worn sword
        is not on that trip."""
        rows = [item(slot=EQUIPPED_SLOT, sell_price=1770, entry=1),
                item(slot=BACKPACK_SLOT, sell_price=10, count=20, entry=2)]
        m = self.build(rows)
        self.assertEqual(m["carried"]["items"], 1)
        self.assertEqual(m["carried"]["vendor_copper"], 200)

    def test_held_counts_everything_on_the_character_including_what_is_worn(self):
        """'How many rares has this family got' has one honest denominator,
        and it is not 'the ones that happen to be loose in a bag'."""
        rows = [item(slot=EQUIPPED_SLOT, quality=RARE, entry=1),
                item(slot=BACKPACK_SLOT, quality=RARE, entry=2)]
        m = self.build(rows)
        self.assertEqual(m["held"]["rare_or_better"], 2)
        self.assertEqual(m["carried"]["rare_or_better"], 1)

    def test_the_notable_list_says_whether_a_thing_is_worn_or_carried(self):
        """A rare in a bag is a question ('why is he not wearing it, and can
        somebody else use it'). The same rare on his body is an answer."""
        rows = [item(slot=EQUIPPED_SLOT, quality=RARE, entry=1, item_name="Worn One"),
                item(slot=BACKPACK_SLOT, quality=RARE, entry=2, item_name="Bagged One")]
        by_name = {i["name"]: i for i in self.build(rows)["notable"]}
        self.assertEqual(by_name["Worn One"]["where"], wealth.EQUIPPED)
        self.assertEqual(by_name["Bagged One"]["where"], wealth.CARRIED)

    def test_the_class_and_its_colour_come_from_the_same_table_the_armory_uses(self):
        m = self.build([])
        self.assertEqual(m["class"], "Warrior")
        self.assertEqual(m["class_colour"], wealth.CLASS_COLOURS[WARRIOR])

    def test_what_is_stored_elsewhere_is_reported_rather_than_dropped(self):
        m = self.build([item(slot=BANK_SLOT)])
        self.assertEqual(m["elsewhere"], 1)


class TheWholeFamily(unittest.TestCase):
    def build(self, rows=(), chars=None, auctions=(), guilds=()):
        return wealth.build_wealth(list(chars if chars is not None else [char()]),
                                   list(rows), list(auctions), list(guilds),
                                   ICONS)

    def test_everybody_on_the_roster_gets_a_card_in_roster_order(self):
        p = self.build()
        self.assertEqual([m["name"] for m in p["members"]], ROSTER)
        self.assertEqual(p["expected"], len(ROSTER))

    def test_a_member_with_no_row_is_present_false_rather_than_missing(self):
        p = self.build()
        absent = [m for m in p["members"] if not m["present"]]
        self.assertEqual(len(absent), len(ROSTER) - 1)

    def test_the_family_purse_is_the_sum_of_the_purses(self):
        p = self.build(chars=[char(name=FIRST, money=100 * 10000),
                              char(name=SECOND, money=70 * 10000)])
        self.assertEqual(p["family"]["money"]["gold"], 170)

    def test_the_family_room_is_the_sum_of_the_rooms(self):
        p = self.build(chars=[char(name=FIRST), char(name=SECOND)])
        self.assertEqual(p["family"]["capacity"]["slots"], wealth.BACKPACK_SLOTS * 2)
        self.assertEqual(p["family"]["capacity"]["free"], wealth.BACKPACK_SLOTS * 2)

    def test_who_is_out_of_room_is_a_list_of_names_not_a_count(self):
        """The fix is per character: this one needs a bag, that one needs to
        sell something. A number cannot be acted on."""
        rows = [item(name=FIRST, slot=BACKPACK_SLOT + n, entry=n)
                for n in range(wealth.BACKPACK_SLOTS)]
        p = self.build(rows=rows, chars=[char(name=FIRST), char(name=SECOND)])
        self.assertEqual(p["family"]["full"], [FIRST])

    def test_the_family_rare_count_is_over_everything_they_hold(self):
        rows = [item(name=FIRST, slot=EQUIPPED_SLOT, quality=RARE, entry=1),
                item(name=SECOND, slot=BACKPACK_SLOT, quality=EPIC, entry=2)]
        p = self.build(rows=rows, chars=[char(name=FIRST), char(name=SECOND)])
        self.assertEqual(p["family"]["rare_or_better"], 2)

    def test_the_richest_is_named_because_the_answer_is_a_person(self):
        p = self.build(chars=[char(name=FIRST, money=10), char(name=SECOND, money=99)])
        self.assertEqual(p["family"]["richest"], SECOND)

    def test_an_empty_realm_totals_to_zero_without_naming_anybody(self):
        p = self.build(chars=[])
        self.assertEqual(p["family"]["present"], 0)
        self.assertEqual(p["family"]["money"]["total"], 0)
        self.assertIsNone(p["family"]["richest"])
        self.assertEqual(p["family"]["full"], [])

    def test_rows_are_split_by_name_so_nobody_carries_anybody_elses_bags(self):
        rows = [item(name=FIRST, slot=BACKPACK_SLOT, entry=1),
                item(name=SECOND, slot=BACKPACK_SLOT, entry=2)]
        p = self.build(rows=rows, chars=[char(name=FIRST), char(name=SECOND)])
        by_name = {m["name"]: m for m in p["members"]}
        self.assertEqual(by_name[FIRST]["carried"]["items"], 1)
        self.assertEqual(by_name[SECOND]["carried"]["items"], 1)


class TheAuctionHouse(unittest.TestCase):
    def test_an_empty_table_is_an_empty_auction_house_and_says_so(self):
        """Nobody has wired auction behaviour yet, so this is the CORRECT
        reading. A blank panel and a broken query look identical, which is
        why the payload carries the reason and the ticket."""
        a = wealth.build_auctions([], ICONS)
        self.assertEqual(a["listings"], [])
        self.assertEqual(a["sold"], [])
        self.assertEqual(a["bids"], [])
        self.assertFalse(a["any"])
        self.assertEqual(a["ticket"]["label"], "mod-overseer#147")
        self.assertIn("mod-overseer/issues/147", a["ticket"]["url"])

    def test_completed_sales_are_declared_untracked_rather_than_reported_as_none(self):
        """The core deletes an auction the moment it finishes and mails the
        gold, so there is no sales history in this database. An empty `sold`
        must never be readable as 'nothing has ever sold'."""
        self.assertFalse(wealth.build_auctions([], ICONS)["tracked"])

    def test_their_own_listings_are_theirs(self):
        a = wealth.build_auctions([auction(owner_name=FIRST)], ICONS)
        self.assertEqual(len(a["listings"]), 1)
        self.assertTrue(a["listings"][0]["ours"])
        self.assertTrue(a["any"])

    def test_a_listing_with_a_winning_bidder_is_the_closest_thing_to_sold(self):
        a = wealth.build_auctions(
            [auction(owner_name=FIRST, lastbid=9000, buyer_name="Somebody")], ICONS)
        self.assertEqual(len(a["sold"]), 1)
        self.assertEqual(a["sold"][0]["buyer"], "Somebody")

    def test_a_listing_nobody_has_bid_on_is_listed_but_not_sold(self):
        a = wealth.build_auctions([auction(owner_name=FIRST, lastbid=0)], ICONS)
        self.assertEqual(len(a["listings"]), 1)
        self.assertEqual(a["sold"], [])

    def test_what_they_have_bid_on_is_somebody_elses_auction(self):
        """Their own listing with their own bid on it would be a nonsense,
        and counting it in both lists would double the activity."""
        a = wealth.build_auctions(
            [auction(owner_name="Stranger", buyer_name=FIRST, lastbid=800)], ICONS)
        self.assertEqual(len(a["bids"]), 1)
        self.assertEqual(a["listings"], [])
        self.assertTrue(a["bids"][0]["we_bid"])

    def test_the_prices_are_coins_and_the_expiry_is_left_as_a_timestamp(self):
        """This module has no clock. A pure function that read one to say
        'four hours left' would be untestable for the sake of a phrase the
        page can build itself."""
        row = wealth.auction_payload(
            auction(startbid=5000, lastbid=0, buyoutprice=20000, deposit=300,
                    time=1770000000), {FIRST}, ICONS)
        self.assertEqual(row["start"], wealth.coins(5000))
        self.assertEqual(row["buyout"], wealth.coins(20000))
        self.assertEqual(row["deposit"], wealth.coins(300))
        self.assertFalse(row["has_bid"])
        self.assertEqual(row["expires_at"], 1770000000)

    def test_the_listed_item_is_drawn_the_same_way_a_bagged_one_is(self):
        row = wealth.auction_payload(auction(count=2), {FIRST}, ICONS)
        self.assertEqual(row["item"]["name"], "Linen Cloth")
        self.assertEqual(row["item"]["count"], 2)
        self.assertEqual(row["item"]["icon"], "inv_fabric_linen_01")
        self.assertEqual(row["item"]["wowhead"],
                         "https://www.wowhead.com/wotlk/item=1234")


class TheWordsAroundTheNumbers(unittest.TestCase):
    """A count reads as a word in a sentence and as a digit in a readout.

    Small helpers, and they are tested because they are the difference between
    "One free slot in the whole family" and "1 free slots in the whole
    family" - and the second reads as a bug in the number rather than in the
    grammar, which sends whoever finds it looking for the wrong thing."""

    def test_small_counts_are_words_and_large_ones_are_digits(self):
        self.assertEqual(wealth.spell(0), "no")
        self.assertEqual(wealth.spell(1), "one")
        self.assertEqual(wealth.spell(10), "ten")
        self.assertEqual(wealth.spell(11), "11")
        self.assertEqual(wealth.spell(189), "189")

    def test_one_is_singular_and_everything_else_is_not(self):
        self.assertEqual(wealth.plural(1, "slot"), "slot")
        self.assertEqual(wealth.plural(0, "slot"), "slots")
        self.assertEqual(wealth.plural(2, "slot"), "slots")
        self.assertEqual(wealth.plural(2, "character"), "characters")

    def test_a_lead_is_capitalised_after_it_is_composed_and_not_before(self):
        """The first word of a lead is a COUNT that changes with the data, so
        capitalising the fragment as it is built means one branch says "One"
        and the next says "no"."""
        self.assertEqual(wealth.sentence("one free slot"), "One free slot")
        self.assertEqual(wealth.sentence(""), "")


class TheFinding(unittest.TestCase):
    """The one sentence at the top of the tab, composed from the live payload.

    THE WHOLE REASON IT IS HERE. A sentence typed into index.html would still
    be saying "one free slot in the whole family" on the day somebody hands
    them four bags each, and nothing would ever fail. Every branch below is a
    different thing the family can be doing, and each one has to be reachable
    from the numbers alone."""

    def find(self, present=5, slots=190, used=189, full=(), rares=0,
             richest=FIRST):
        totals = {
            "present": present,
            "money": wealth.coins(0),
            "vendor": wealth.coins(0),
            "capacity": {"slots": slots, "used": used,
                         "free": max(0, slots - used), "bags": 4 * present,
                         "empty_bag_slots": 0},
            "by_quality": [],
            "rare_or_better": rares,
            "richest": richest,
            "full": list(full),
        }
        return wealth.build_finding(totals)

    def test_nobody_saved_is_a_finding_of_its_own_rather_than_a_zero(self):
        """"No free slot anywhere in the family" would be TRUE of an empty
        realm and completely misleading about it."""
        f = self.find(present=0, slots=0, used=0)
        self.assertIn("saved character", f["lead"])
        self.assertEqual(f["tone"], wealth.ALARM)

    def test_five_characters_and_no_slots_is_a_query_that_answered(self):
        """Every character is born with a backpack, so this is a data fault
        rather than a family who own nothing."""
        f = self.find(slots=0, used=0)
        self.assertIn("No bags", f["lead"])
        self.assertEqual(f["tone"], wealth.ALARM)
        self.assertIn("born with a backpack", f["because"])

    def test_one_free_slot_across_the_family_is_the_headline(self):
        """The measured state on the day this landed, and the reason the tab
        exists: 189 of 190, with four of the five unable to loot anything."""
        f = self.find(slots=190, used=189, full=[FIRST, SECOND])
        self.assertEqual(f["lead"], "One free slot in the whole family")
        self.assertEqual(f["detail"], "189 of 190 slots taken.")
        self.assertEqual(f["tone"], wealth.ALARM)
        self.assertIn("never finish a loot", f["because"])

    def test_no_free_slot_at_all_says_so_rather_than_saying_none(self):
        f = self.find(slots=190, used=190, full=[FIRST])
        self.assertEqual(f["lead"], "No free slot anywhere in the family")
        self.assertEqual(f["tone"], wealth.ALARM)

    def test_tight_with_nobody_stuck_yet_is_a_caution_and_not_an_alarm(self):
        """A family with ten slots left and nobody full is tight. A family
        with one slot left and four characters full is a fault being
        reported, and drawing both the same colour would spend the alarm."""
        f = self.find(slots=190, used=180, full=[])
        self.assertEqual(f["tone"], wealth.CAUTION)
        self.assertEqual(f["lead"], "Ten free slots in the whole family")

    def test_the_threshold_is_one_backpack_and_not_a_percentage(self):
        """Five per cent of 190 slots is nine, and nine slots is one quest
        turn-in away from nothing. A backpack is a real unit of room here."""
        self.assertEqual(wealth.FAMILY_TIGHT_SLOTS, wealth.BACKPACK_SLOTS)
        self.assertEqual(self.find(slots=190, used=190 - wealth.BACKPACK_SLOTS)
                         ["tone"], wealth.CAUTION)
        self.assertEqual(self.find(slots=190, used=190 - wealth.BACKPACK_SLOTS - 1)
                         ["tone"], wealth.PLAIN)

    def test_somebody_full_with_room_elsewhere_names_how_many(self):
        f = self.find(slots=190, used=100, full=[FIRST, SECOND])
        self.assertEqual(f["lead"], "Two of the five are out of room")
        self.assertEqual(f["tone"], wealth.ALARM)

    def test_one_person_full_reads_as_one_person(self):
        f = self.find(slots=190, used=100, full=[FIRST])
        self.assertEqual(f["lead"], "One of the five is out of room")

    def test_a_family_with_room_is_allowed_to_be_unremarkable(self):
        """Not every state is a problem, and drawing this one loud would
        teach a reader to stop looking at the top of the tab."""
        f = self.find(slots=190, used=20)
        self.assertEqual(f["tone"], wealth.PLAIN)
        self.assertIn("free slots across the family", f["lead"])

    def test_who_is_out_of_room_is_named_wherever_anybody_is(self):
        f = self.find(slots=190, used=189, full=[FIRST, SECOND])
        self.assertEqual(f["who"], [FIRST, SECOND])
        self.assertIn(FIRST, f["who_label"])
        self.assertIn(SECOND, f["who_label"])
        self.assertIsNone(self.find(slots=190, used=20)["who_label"])

    def test_the_consequence_never_names_a_member_of_the_roster(self):
        """The eight-and-a-half-hour freeze happened to a specific character,
        and naming them in a constant here would be a second roster that can
        disagree with bonds. It says "one of them"."""
        for name in ROSTER:
            self.assertNotIn(name, wealth.FULL_CONSEQUENCE)
            self.assertNotIn(name, wealth.TIGHT_CONSEQUENCE)


class TheStatStrip(unittest.TestCase):
    def strip(self, **kw):
        totals = {
            "present": 5,
            "money": wealth.coins(166 * GOLD),
            "vendor": wealth.coins(150),
            "capacity": {"slots": 190, "used": 189, "free": 1, "bags": 17,
                         "empty_bag_slots": 3},
            "by_quality": [],
            "rare_or_better": 11,
            "richest": FIRST,
            "full": [FIRST],
        }
        totals.update(kw)
        return wealth.build_stats(totals)

    def test_the_same_readings_in_the_same_order_every_poll(self):
        """A strip that drops a reading when it is zero changes shape as the
        data changes, and a reader loses the one thing a strip is good for."""
        labels = [s["label"] for s in self.strip()]
        self.assertEqual(labels, [s["label"] for s in self.strip(
            rare_or_better=0,
            capacity={"slots": 190, "used": 10, "free": 180, "bags": 20,
                      "empty_bag_slots": 0})])
        self.assertEqual(len(labels), 7)

    def test_money_readings_carry_coins_and_not_a_string(self):
        """The page draws money in three colours, so an amount cannot be
        interpolated into a value the way a count can."""
        purse = self.strip()[0]
        self.assertEqual(purse["money"]["gold"], 166)
        self.assertIsNone(purse["value"])

    def test_a_family_with_no_room_left_reads_as_an_alarm(self):
        tight = self.strip(capacity={"slots": 190, "used": 190, "free": 0,
                                     "bags": 20, "empty_bag_slots": 0})
        slots = [s for s in tight if s["label"] == "slots"][0]
        self.assertEqual(slots["tone"], wealth.ALARM)
        self.assertEqual(slots["value"], "190 of 190")

    def test_an_empty_bag_position_is_amber_and_not_red(self):
        """Find him a bag is a different job from sell something, and only
        one of the two is stopping a character playing right now."""
        spare = [s for s in self.strip() if s["label"] == "empty bag positions"][0]
        self.assertEqual(spare["value"], "3")
        self.assertEqual(spare["tone"], wealth.CAUTION)

    def test_rares_are_the_one_reading_drawn_as_good_news(self):
        rares = [s for s in self.strip() if s["label"] == "rare or better"][0]
        self.assertEqual(rares["tone"], wealth.GOOD)
        self.assertEqual(
            [s for s in self.strip(rare_or_better=0)
             if s["label"] == "rare or better"][0]["tone"], wealth.PLAIN)

    def test_the_richest_is_a_person_and_an_empty_realm_is_not(self):
        self.assertEqual(self.strip()[-1]["value"], FIRST)
        self.assertEqual(self.strip(richest=None)[-1]["value"], wealth.NOTHING)


class TheRoomLine(unittest.TestCase):
    def room(self, slots=44, used=40, bags=4, spare=0):
        return wealth.build_room({"slots": slots, "used": used,
                                  "free": max(0, slots - used), "bags": bags,
                                  "bag_slots": wealth.BAG_POSITIONS,
                                  "empty_bag_slots": spare,
                                  "full": used >= slots})

    def test_the_bar_is_a_percentage_of_the_room_that_exists(self):
        self.assertEqual(self.room(slots=44, used=22)["percent"], 50)
        self.assertEqual(self.room(slots=0, used=0)["percent"], 0)

    def test_full_is_an_alarm_and_nearly_full_is_a_caution(self):
        """This used to be a ternary in the page, where no test could reach
        the number in it."""
        self.assertEqual(self.room(slots=44, used=44)["tone"], wealth.ALARM)
        self.assertEqual(self.room(slots=100, used=90)["tone"], wealth.CAUTION)
        self.assertEqual(self.room(slots=100, used=89)["tone"], wealth.PLAIN)
        self.assertEqual(wealth.TIGHT_PERCENT, 90)

    def test_no_room_left_is_said_in_words_rather_than_as_a_zero(self):
        """Zero is a number a reader has to interpret, and this is the state
        the whole tab exists to report."""
        self.assertEqual(self.room(slots=44, used=44)["free_label"],
                         "no room left")
        self.assertEqual(self.room(slots=44, used=44)["free_tone"], wealth.ALARM)
        self.assertEqual(self.room(slots=44, used=40)["free_label"], "4 free")
        self.assertEqual(self.room(slots=44, used=40)["free_tone"], wealth.PLAIN)

    def test_a_character_carrying_no_bags_says_so_rather_than_saying_zero(self):
        self.assertEqual(self.room(bags=0)["bags_label"],
                         "the backpack alone, no bags carried")
        self.assertEqual(self.room(bags=1)["bags_label"],
                         "across 1 bag and the backpack")

    def test_an_empty_bag_position_is_its_own_line_in_amber(self):
        self.assertIsNone(self.room(spare=0)["spare_label"])
        self.assertEqual(self.room(spare=1)["spare_label"], "1 empty bag position")
        self.assertEqual(self.room(spare=2)["spare_label"], "2 empty bag positions")
        self.assertEqual(self.room(spare=2)["spare_tone"], wealth.CAUTION)


class TheWordsOnAnItem(unittest.TestCase):
    def one(self, where=wealth.CARRIED, container="Backpack", **kw):
        return wealth.item_payload(item(**kw), ICONS, where, container, 0)

    def test_a_stack_says_how_many_and_a_single_item_does_not(self):
        """Three copies of `count > 1 ? " x" + count : ""` is three chances
        for one of them to start saying "x1"."""
        self.assertEqual(self.one(count=1)["stack"], "Linen Cloth")
        self.assertEqual(self.one(count=20)["stack"], "Linen Cloth x20")

    def test_where_a_thing_is_is_a_word_and_not_an_inference(self):
        self.assertEqual(self.one(where=wealth.EQUIPPED)["place"],
                         wealth.PLACE_WORN)
        self.assertEqual(self.one(container="Small Red Pouch")["place"],
                         "in Small Red Pouch")

    def test_only_a_bagged_item_is_drawn_in_amber(self):
        """An item on a body is where it belongs; the same item loose in a
        bag is a spare, a mistake, or gold nobody has banked."""
        self.assertEqual(self.one(where=wealth.EQUIPPED)["place_tone"],
                         wealth.PLAIN)
        self.assertEqual(self.one()["place_tone"], wealth.CAUTION)

    def test_the_tooltip_line_says_quality_kind_level_and_price(self):
        tip = self.one(count=20, quality=UNCOMMON, item_level=14,
                       sell_price=10)["tip"]
        self.assertIn("Linen Cloth x20", tip)
        self.assertIn("uncommon", tip)
        self.assertIn("Trade Goods", tip)
        self.assertIn("item level 14", tip)
        self.assertIn("vendor 2s 0c", tip)

    def test_an_unsellable_stack_says_so_rather_than_showing_nothing(self):
        """A SellPrice of 0 is the game saying this cannot be sold at all,
        which is what every quest item is. An empty space where a price
        should be reads as a missing number."""
        self.assertIn("no vendor value", self.one(sell_price=0)["tip"])


class TheContainerLabel(unittest.TestCase):
    def containers(self, rows):
        return wealth.split_inventory(list(rows), ICONS)["containers"]

    def test_a_bag_says_how_full_it_is(self):
        backpack = self.containers([item(slot=BACKPACK_SLOT)])[0]
        self.assertEqual(backpack["room_label"],
                         "1 of %d" % wealth.BACKPACK_SLOTS)
        self.assertFalse(backpack["full"])
        self.assertEqual(backpack["tone"], wealth.PLAIN)

    def test_a_full_bag_is_an_alarm_of_its_own(self):
        rows = [bag(slots=1, guid=7001),
                item(bag=7001, slot=0, entry=9, item_name="Gold Dust")]
        pouch = [c for c in self.containers(rows) if c["key"] != wealth.BACKPACK][0]
        self.assertTrue(pouch["full"])
        self.assertEqual(pouch["tone"], wealth.ALARM)
        self.assertEqual(pouch["room_label"], "1 of 1")

    def test_a_container_of_unknown_size_says_that_rather_than_of_zero(self):
        """ContainerSlots comes through a LEFT JOIN, so a custom or removed
        bag arrives with no size at all - and "1 of 0" reads as a broken
        count rather than as the missing template it is."""
        rows = [bag(slots=0, guid=7001),
                item(bag=7001, slot=0, entry=9, item_name="Gold Dust")]
        pouch = [c for c in self.containers(rows) if c["key"] != wealth.BACKPACK][0]
        self.assertEqual(pouch["room_label"], "1 carried, size unknown")
        self.assertFalse(pouch["full"])


class TheGuildBankThereIsNot(unittest.TestCase):
    """There is no guild, so there is no guild bank - and an empty vault drawn
    on the strength of that is the same mistake the auction panel exists to
    avoid. What is useful is the road to one, and which parts of it the module
    can already drive."""

    def test_no_rows_means_no_guild_and_the_panel_says_it(self):
        bank = wealth.build_guild_bank([])
        self.assertEqual(bank["guilds"], [])
        self.assertEqual(bank["lead"], "There is no guild, so there is no guild bank.")

    def test_a_guild_that_exists_is_named_rather_than_denied(self):
        """Asked of the database rather than assumed, so the sentence stops
        being drawn on the day somebody makes one."""
        bank = wealth.build_guild_bank([{"name": FIRST, "guild_name": "Cave"}])
        self.assertEqual(bank["guilds"], ["Cave"])
        self.assertIn("Cave", bank["lead"])
        self.assertNotIn("no guild", bank["lead"])

    def test_observed_tabs_and_items_are_reported_without_inference(self):
        bank = wealth.build_guild_bank(
            [{"name": FIRST, "guild_name": "Cave"}],
            [{"guild_id": 23, "tab_id": 0, "tab_name": "Raid mats",
              "item_count": 7},
             {"guild_id": 23, "tab_id": 1, "tab_name": "Recipes",
              "item_count": 2}],
        )
        self.assertTrue(bank["bank_observed"])
        self.assertEqual(bank["purchased_tabs"], 2)
        self.assertEqual(bank["stored_items"], 9)
        self.assertEqual(len(bank["tabs"]), 2)
        self.assertIn("2 purchased bank tabs", bank["body"])

    def test_missing_snapshot_is_distinct_from_an_observed_empty_bank(self):
        guild = [{"name": FIRST, "guild_name": "Cave"}]
        unknown = wealth.build_guild_bank(guild)
        empty = wealth.build_guild_bank(guild, [])
        self.assertFalse(unknown["bank_observed"])
        self.assertIsNone(unknown["purchased_tabs"])
        self.assertTrue(empty["bank_observed"])
        self.assertEqual(empty["purchased_tabs"], 0)
        self.assertEqual(empty["stored_items"], 0)

    def test_a_row_with_no_guild_name_is_not_a_guild(self):
        bank = wealth.build_guild_bank([{"name": FIRST, "guild_name": None}])
        self.assertEqual(bank["guilds"], [])

    def test_travel_works_and_everything_after_arriving_does_not(self):
        """Travel is the one part that works: a petitioner and a guild banker
        are both ordinary NPCs, and travel.py can already aim a character at
        an NPC by entry. Everything after arriving is a packet nothing
        sends."""
        bank = wealth.build_guild_bank([])
        works = [s["step"] for s in bank["steps"] if s["state"] == wealth.WORKS]
        missing = [s["step"] for s in bank["steps"] if s["state"] == wealth.MISSING]
        self.assertEqual(works, ["travel to a petitioner",
                                 "travel to a guild banker"])
        self.assertIn("buy a charter", missing)
        self.assertIn("collect the signatures", missing)
        self.assertIn("register the guild", missing)
        self.assertIn("deposit into the guild bank", missing)
        self.assertIn("withdraw from the guild bank", missing)
        self.assertEqual(bank["works"], 2)
        self.assertEqual(bank["missing"], 5)

    def test_every_step_carries_a_word_and_a_tone(self):
        for step in wealth.build_guild_bank([])["steps"]:
            self.assertIn(step["state_label"], ("works", "not written"))
            self.assertIn(step["tone"], (wealth.GOOD, wealth.CAUTION))

    def test_the_blocked_sentence_counts_the_table_rather_than_a_number(self):
        """"Five of the seven" has to come from the table, or the day a sixth
        blocked step is added the sentence quietly starts lying."""
        blocked = wealth.build_guild_bank([])["blocked"]
        self.assertEqual(blocked["before"],
                         "Five of the seven steps are not written, and all of "
                         "them are blocked on ")
        self.assertEqual(blocked["ticket"], wealth.GUILD_TICKET)
        self.assertEqual(blocked["after"], ".")


class TheEmptyAuctionPanel(unittest.TestCase):
    def test_the_reason_it_is_empty_is_a_sentence_the_module_owns(self):
        """A blank panel and a broken query look identical, and the page used
        to hold the words that told them apart."""
        a = wealth.build_auctions([], ICONS)
        self.assertIn("Nothing listed", a["empty"]["lead"])
        self.assertIn("empty auction house rather than an empty panel",
                      a["empty"]["body"])
        self.assertEqual(a["empty"]["why"]["ticket"], wealth.AUCTION_TICKET)
        self.assertIn("lists, buys, bids or sells", a["empty"]["why"]["before"])

    def test_the_caveat_is_true_whether_or_not_there_are_rows(self):
        """The core deletes an auction the moment it completes and mails the
        gold, so `sold` can only ever mean mid-sale."""
        for rows in ([], [auction()]):
            a = wealth.build_auctions(list(rows), ICONS)
            self.assertIn("Completed sales leave no trace", a["caveat"])
            self.assertFalse(a["tracked"])

    def test_the_three_lists_arrive_labelled_and_counted(self):
        a = wealth.build_auctions([auction()], ICONS)
        self.assertEqual([s["label"] for s in a["sections"]],
                         ["listed by the family", "sold, gold in the post",
                          "bid on by the family"])
        self.assertEqual(a["sections"][0]["count"], 1)
        self.assertEqual(a["sections"][1]["count"], 0)
        self.assertEqual(a["sections"][1]["empty"], wealth.NONE)

    def test_a_row_says_whose_it_is_and_what_the_price_means(self):
        """A listing with no bid on it has a STARTING price, not a highest
        one, and drawing the start under "highest bid" would be the panel
        inventing a bidder."""
        mine = wealth.auction_payload(auction(), {FIRST}, ICONS)
        self.assertEqual(mine["who_label"], "listed by " + FIRST)
        self.assertEqual(mine["bid_label"], "starting bid")
        bid_on = wealth.auction_payload(auction(lastbid=9000), {FIRST}, ICONS)
        self.assertEqual(bid_on["bid_label"], "highest bid")

    def test_a_seller_the_world_has_forgotten_is_unknown_not_blank(self):
        """`itemowner` is a guid and the character behind it can have been
        deleted since the auction was posted."""
        theirs = wealth.auction_payload(auction(owner_name=None), set(), ICONS)
        self.assertEqual(theirs["who_label"], "seller unknown")


class TheMemberSentences(unittest.TestCase):
    def build(self, rows=(), **kw):
        return wealth.build_member(FIRST, char(**kw), list(rows), ICONS)

    def test_the_line_under_the_name_is_composed_here(self):
        """A level, a class and a role joined with punctuation of the page's
        own choosing is three views spelling the same line three ways."""
        self.assertIn(" - ", self.build()["who"])
        self.assertTrue(self.build()["who"].startswith("25 "))
        self.assertIn(" - ", wealth.build_member(FIRST, None, [], ICONS)["who"])

    def test_stacks_and_items_are_both_said_because_they_differ(self):
        """A bag holding one stack of twenty linen is one slot and twenty
        things, and a line reporting either alone is wrong about the other."""
        m = self.build([item(slot=BACKPACK_SLOT, count=20)])
        self.assertIn("carrying 1 stack (20 items)", m["holding"]["before"])
        self.assertEqual(m["holding"]["after"], " at a vendor")
        self.assertEqual(m["holding"]["money"], m["carried"]["vendor"])

    def test_what_is_stored_elsewhere_is_a_sentence_or_nothing_at_all(self):
        self.assertIsNone(self.build()["elsewhere_note"])
        note = self.build([item(slot=BANK_SLOT)])["elsewhere_note"]
        self.assertIn("1 more stored elsewhere", note)

    def test_the_notable_note_only_exists_when_there_is_a_list(self):
        self.assertIsNone(self.build()["notable_note"])
        m = self.build([item(slot=BACKPACK_SLOT, quality=RARE)])
        self.assertEqual(m["notable_note"], wealth.NOTABLE_NOTE)

    def test_a_missing_character_gets_the_sentence_and_not_a_blank_card(self):
        m = wealth.build_member(FIRST, None, [], ICONS)
        self.assertEqual(m["absent_note"], wealth.ABSENT_NOTE)

    def test_the_quality_chips_arrive_written_out(self):
        m = self.build([item(slot=BACKPACK_SLOT, quality=RARE)])
        self.assertEqual(m["held"]["by_quality"][0]["label"], "1 rare")


class TheContractWithTheRestOfTheCodebase(unittest.TestCase):
    def test_the_slot_geography_is_panels_and_not_a_second_copy(self):
        """Two modules disagreeing about where the backpack starts would be
        two different answers to 'how full is he', both rendered, neither
        flagged."""
        self.assertEqual(wealth.BACKPACK_SLOTS, len(panel._BACKPACK_SLOTS))
        self.assertEqual(wealth.BAG_POSITIONS, len(panel._BAG_SLOTS))

    def test_the_equipped_bound_is_the_armorys_own_slot_list(self):
        """The paper doll and this view must agree about which rows are worn,
        or an item shows up in both or in neither."""
        self.assertEqual(wealth.EQUIPPED_SLOTS[0], panel._EQUIPMENT_SLOT_NAMES[0])
        self.assertEqual(len(wealth.EQUIPPED_SLOTS), panel._BAG_SLOTS.start)

    def test_the_quality_words_are_the_armorys(self):
        """The page draws both views in the same colours; naming quality 4
        two different things in two modules is how they come apart."""
        self.assertEqual(wealth.QUALITY_NAMES[4], "epic")

    def test_the_module_reads_nothing_and_writes_nothing(self):
        """Same seam rule as map_core, panel, family and armory: rows in,
        payload out. An import of pymysql or os here would put a database in
        the middle of a suite that has none."""
        source = (HERE / "wealth.py").read_text(encoding="utf-8")
        for forbidden in ("import pymysql", "import os", "open("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
