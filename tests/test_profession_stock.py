"""The family's own tools and stock are not vendor goods (infra#3709).

MEASURED ON THE LIVE REALM, 2026-09-13, and every column below was read out of
`acore_world.item_template` rather than off a wiki:

    entry  name                class  subclass  Quality  RequiredLevel  BagFamily
    2901   Mining Pick             2        14        1              1       1024
    5956   Blacksmith Hammer       2        14        1              1       1152
    7005   Skinning Knife          2        14        1              1          8
    6219   Arclight Spanner        2        14        1              0        128
    3371   Empty Vial              7        11        1              0         16

Grug sold the pick and the hammer eight times each over eighteen hours, eight
DISTINCT `item_instance.guid` apiece, so every repeat was a fresh copy bought
and re-sold. Bork sold his Skinning Knife four times. `craft_supply` bought
Ugga 25 Empty Vials for 100 copper and the economy sold them back for 25 ten
minutes later, four laps in half an hour. Three of the five made no profession
progress at all, which is the whole of the user-visible symptom.

WHERE THE SALE ACTUALLY CAME FROM, WHICH IS NOT WHERE THE ISSUE SAID. All five
are Quality 1, and `_SURPLUS_GEAR_SQL` selects `Quality >= 2` - so `decide`
was never asked about any of them. They reached the merchant through
`bag_pressure.sellable`, whose only profession protection was
`materials.REAGENTS`: six material NAMES, not one of them a tool. Both halves
are covered below, because a pass that answered differently about the same
pick depending on its quality would be the next bug.

THE STATES THE REALM IS NOT IN ARE THE POINT OF MOST OF THIS FILE. A dry run
against today's bags cannot exercise a reagent past the keep line, a tool
nobody works, an inscription bag, or an uncommon trade tool, and every one of
those is a way this rule could be wrong.
"""
import pathlib
import unittest

import bag_pressure
import disposition
from disposition import (BIND_NONE, BIND_ON_EQUIP, BIND_ON_PICKUP, FIT_NOBODY,
                         KEEP, VENDOR, Family, Item, decide, outgrown,
                         profession_keeps, trade_tool)

# The family as `professions.assigned` declares it, which is the permission
# this gate reads: the END STATE the roster is walking them towards, not the
# skills anybody happens to hold today.
WORKED = ("mining", "blacksmithing", "skinning", "leatherworking", "tailoring",
          "enchanting", "herbalism", "alchemy", "engineering")

# What `craft.RECIPES` joined to `craft_supply.REAGENT`/`REAGENTS` says, as
# bridge derives it. Only the entries this file uses.
NAMED = {3371: ("alchemy",), 2320: ("tailoring", "leatherworking")}

TOWN = Family(vendor_reachable=True)


def row(entry, name, item_class, bag_family, guid, count=1):
    """One carried stack, exactly as _VENDOR_ITEMS_SQL now returns it."""
    return {"holder": "Grug", "item_guid": guid, "count": count,
            "entry": entry, "name": name, "quality": 1, "sell_price": 16,
            "item_class": item_class, "bag_family": bag_family,
            "quest_item": 0, "reagent": 0}


PICK = row(2901, "Mining Pick", 2, 1024, 9001)
HAMMER = row(5956, "Blacksmith Hammer", 2, 1152, 9002)
KNIFE = row(7005, "Skinning Knife", 2, 8, 9003)
SPANNER = row(6219, "Arclight Spanner", 2, 128, 9004)
VIALS = row(3371, "Empty Vial", 7, 16, 9005, count=25)


class TheLapTheFamilyWasStuckIn(unittest.TestCase):
    """The four entries the issue measured, with their real live columns."""

    def test_every_tool_the_family_sold_is_now_held_back(self):
        keeps = profession_keeps([PICK, HAMMER, KNIFE, SPANNER],
                                 worked=WORKED, named=NAMED)
        self.assertEqual(sorted(keeps), [9001, 9002, 9003, 9004])

    def test_the_vials_craft_supply_buys_are_held_back(self):
        keeps = profession_keeps([VIALS], worked=WORKED, named=NAMED)
        self.assertIn(9005, keeps)

    def test_the_reason_says_which_trade_and_not_merely_that_it_refused(self):
        keeps = profession_keeps([PICK, VIALS], worked=WORKED, named=NAMED)
        self.assertIn("tool", keeps[9001])
        self.assertIn("alchemy", keeps[9005])


class TheBagIsABackstopAndNeverTheProfessionAnswer(unittest.TestCase):
    """Empty Vial's own bag bit is INSCRIPTION, which nobody here works.

    This is the single reason the craft tables are consulted first, and it is
    a state a dry run against today's realm cannot show, because today both
    sources happen to agree for everything else.
    """

    def test_the_vial_bit_really_is_the_one_nobody_works(self):
        self.assertEqual(VIALS["bag_family"],
                         disposition.PROFESSION_BAGS["inscription"])
        self.assertNotIn("inscription", WORKED)

    def test_the_bag_alone_would_have_sold_the_alchemists_vials(self):
        """No craft-table claim, so only the bag speaks - and it says sell."""
        self.assertEqual(profession_keeps([VIALS], worked=WORKED, named={}), {})

    def test_the_craft_table_claim_is_what_keeps_them(self):
        self.assertIn(9005, profession_keeps([VIALS], worked=WORKED,
                                             named=NAMED))

    def test_a_trade_nobody_works_does_not_protect_its_stock(self):
        """A gem is jewelcrafting's, and professions.UNASSIGNED says so."""
        gem = row(774, "Malachite", 7, 512, 9010, count=5)
        self.assertEqual(profession_keeps([gem], worked=WORKED, named=NAMED), {})

    def test_one_entry_claimed_by_two_trades_needs_only_one_worked(self):
        thread = row(2320, "Coarse Thread", 7, 8, 9011, count=5)
        self.assertIn(9011, profession_keeps([thread], worked=("tailoring",),
                                             named=NAMED))


class AToolIsKeptWhateverAnybodyWorks(unittest.TestCase):
    """The permission gates the STOCK, deliberately not the TOOL.

    A tool nobody works costs one bag slot and sixteen copper. A miner whose
    pick was sold stops mining, which is what this cost three characters.
    """

    def test_a_pick_survives_a_family_with_no_trades_at_all(self):
        self.assertIn(9001, profession_keeps([PICK], worked=(), named={}))

    def test_a_pick_survives_a_family_that_works_something_else(self):
        self.assertIn(9001, profession_keeps([PICK], worked=("alchemy",),
                                             named={}))


class OnlyABagThatNamesATradeCounts(unittest.TestCase):
    """Arrows, keys, pets, tokens and quest items are bag-sorted too."""

    def test_the_bits_that_are_not_trades_protect_nothing(self):
        for bit, what in ((1, "Razor Arrow"), (2, "Accurate Slugs"),
                          (4, "Soul Shard"), (256, "Small Brass Key"),
                          (2048, "soulbound"), (4096, "Cat Carrier"),
                          (8192, "Mark of Honor"), (16384, "quest")):
            with self.subTest(bit=bit):
                other = row(1, what, 7, bit, 9020)
                self.assertEqual(
                    profession_keeps([other], worked=WORKED, named={}), {})

    def test_an_unbagged_grey_is_untouched(self):
        junk = row(2, "Broken Fang", 7, 0, 9021)
        self.assertEqual(profession_keeps([junk], worked=WORKED, named={}), {})

    def test_arrows_are_not_a_tool_even_though_a_quiver_sorts_them(self):
        """Bork carries 1,000 Razor Arrows, BagFamily 1. Class 2 alone must
        not make something a tool or the ammo pile is pinned for ever."""
        self.assertFalse(trade_tool(Item(name="Razor Arrow", item_class=2,
                                         bag_family=1)))


class ArmourIsNotATool(unittest.TestCase):
    """105 class-4 rows carry engineering's bit, because every goggle does.

    Calling those tools would pin a head slot's worth of obsolete goggles in
    a bag for ever - the bag-pressure regression handed out by the rule meant
    to protect professions.
    """

    def test_engineering_goggles_are_not_a_tool(self):
        goggles = Item(name="Bright-Eye Goggles", item_class=4, bag_family=128)
        self.assertFalse(trade_tool(goggles))

    def test_bagged_armour_is_still_offered_to_the_vendor(self):
        worn_out = Item(name="Bright-Eye Goggles", quality=2, known=True,
                        binding=BIND_ON_PICKUP, quest_item=False,
                        equipment=True, required_level=25, sell_price=400,
                        item_class=4, bag_family=128)
        self.assertEqual(
            decide(worn_out, TOWN, character_level=47,
                   available=disposition.EXECUTABLE_TODAY,
                   family_fit=FIT_NOBODY).route, VENDOR)


class StockIsKeptByCountAndToolsAreKeptWhole(unittest.TestCase):
    """The one judgement in the rule, and the brief asked for it out loud."""

    def test_a_second_pick_is_kept_too_because_a_tool_has_no_surplus(self):
        spare = row(2901, "Mining Pick", 2, 1024, 9030)
        keeps = profession_keeps([PICK, spare], worked=WORKED, named=NAMED)
        self.assertEqual(sorted(keeps), [9001, 9030])

    def test_stock_past_the_keep_line_stays_sellable(self):
        stacks = [row(3371, "Empty Vial", 7, 16, 9040 + n, count=20)
                  for n in range(3)]
        keeps = profession_keeps(stacks, worked=WORKED, named=NAMED)
        self.assertEqual(len(keeps), 2)

    def test_the_surplus_offered_is_the_leftovers_and_not_the_shelf(self):
        """Largest first, so what stays sellable is the small stack."""
        stacks = [row(3371, "Empty Vial", 7, 16, 9050, count=30),
                  row(3371, "Empty Vial", 7, 16, 9051, count=5),
                  row(3371, "Empty Vial", 7, 16, 9052, count=20)]
        keeps = profession_keeps(stacks, worked=WORKED, named=NAMED)
        self.assertEqual(sorted(keeps), [9050, 9051])

    def test_the_keep_line_is_one_number_shared_with_the_family_default(self):
        self.assertEqual(Family().reagent_keep, disposition.REAGENT_KEEP)


class TheFixCannotRecreateTheLap(unittest.TestCase):
    """An entry-wide "held > keep, so sell it" cliff drops the family to ZERO
    the moment they gather past the line, `craft_supply` re-buys, and the lap
    starts again one number higher. These are the two shapes that would."""

    def test_one_oversized_stack_is_kept_entire(self):
        big = row(3371, "Empty Vial", 7, 16, 9060, count=60)
        self.assertIn(9060, profession_keeps([big], worked=WORKED,
                                             named=NAMED))

    def test_selling_the_surplus_reaches_a_fixed_point(self):
        """Sell what this rule offers, ask again, and nothing more is offered.

        Three 20-stacks against a keep of 40: one stack goes, and the second
        pass must then hold both survivors rather than shaving another.
        """
        stacks = [row(3371, "Empty Vial", 7, 16, 9070 + n, count=20)
                  for n in range(3)]
        keeps = profession_keeps(stacks, worked=WORKED, named=NAMED)
        left = [s for s in stacks if s["item_guid"] in keeps]
        self.assertEqual(len(left), 2)
        again = profession_keeps(left, worked=WORKED, named=NAMED)
        self.assertEqual(sorted(again), sorted(s["item_guid"] for s in left))


class ARowNobodyCanReadChangesNothing(unittest.TestCase):
    """The fail-closed direction for a MISSING protection is the one that
    changes nothing, not one that pins an unreadable bag."""

    def test_a_row_without_the_new_columns_is_simply_unprotected(self):
        old = {"item_guid": 9080, "entry": 2901, "count": 1,
               "name": "Mining Pick"}
        self.assertEqual(profession_keeps([old], worked=WORKED, named=NAMED),
                         {})

    def test_unparseable_rows_do_not_take_the_readable_ones_with_them(self):
        broken = dict(PICK, count="lots")
        keeps = profession_keeps([broken, KNIFE], worked=WORKED, named=NAMED)
        self.assertEqual(sorted(keeps), [9003])

    def test_an_empty_stack_or_a_dead_guid_is_skipped(self):
        for bad in (dict(PICK, count=0), dict(PICK, item_guid=0)):
            with self.subTest(bad=bad):
                self.assertEqual(
                    profession_keeps([bad], worked=WORKED, named=NAMED), {})


class TheSaleGateActuallyReadsIt(unittest.TestCase):
    """Proving the control flow reaches the code, not merely that it is right.

    `profession_keeps` decides nothing on its own: `bag_pressure.sellable`
    refuses a `profession_needed` row, and bridge is what joins the two. Both
    directions are asserted so a seam that stopped being wired would fail
    here rather than on the realm.
    """

    def test_a_tool_is_sellable_until_the_gate_marks_it(self):
        before = bag_pressure.vendor_candidates([dict(PICK,
                                                      profession_needed=False)])
        self.assertEqual(len(before), 1)

    def test_and_is_not_once_the_gate_has(self):
        keeps = profession_keeps([PICK], worked=WORKED, named=NAMED)
        marked = dict(PICK, profession_needed=PICK["item_guid"] in keeps)
        self.assertEqual(bag_pressure.vendor_candidates([marked]), ())

    def test_the_whole_measured_lap_stops(self):
        """Every stack the issue measured, through the real selection."""
        rows = [PICK, HAMMER, KNIFE, VIALS]
        keeps = profession_keeps(rows, worked=WORKED, named=NAMED)
        marked = [dict(r, profession_needed=r["item_guid"] in keeps)
                  for r in rows]
        self.assertEqual(bag_pressure.vendor_candidates(marked), ())
        unmarked = [dict(r, profession_needed=False) for r in rows]
        self.assertEqual(len(bag_pressure.vendor_candidates(unmarked)), 4)


class TheGearHalfAnswersTheSameWay(unittest.TestCase):
    """Quality 1 keeps every tool the family owns today below the gear
    query's `Quality >= 2` floor, so this half cannot fire on the realm as it
    stands - said plainly rather than implied. It is not hypothetical: Finkle's
    Skinner (class 2, BagFamily 8) and Brann's Trusty Pick (class 2, BagFamily
    1024) are real uncommon-or-better trade tools on this world, and one pass
    must not answer differently about the same pick because of its colour.
    """

    def _skinner(self, **kw):
        base = dict(name="Finkle's Skinner", quality=4, known=True,
                    binding=BIND_ON_EQUIP, quest_item=False, equipment=True,
                    required_level=1, sell_price=6000, item_class=2,
                    bag_family=8)
        base.update(kw)
        return Item(**base)

    def test_a_trade_tool_is_never_outgrown(self):
        self.assertFalse(outgrown(self._skinner(), character_level=80))

    def test_the_catch_all_cannot_reach_it_even_at_fit_nobody(self):
        """FIT_NOBODY is what retires the level margin and opens the disposal
        branches, and `gear.claimant` answers NOBODY about every tool -
        correctly, since nobody would WEAR one."""
        verdict = decide(self._skinner(binding=BIND_ON_PICKUP), TOWN,
                         character_level=80,
                         available=disposition.EXECUTABLE_TODAY,
                         family_fit=FIT_NOBODY)
        self.assertEqual(verdict.route, KEEP)
        self.assertIn("trade tool", verdict.why)

    def test_an_ordinary_weapon_is_untouched_by_any_of_this(self):
        sword = Item(name="Rusty Shortsword", quality=2, known=True,
                     binding=BIND_NONE, quest_item=False, equipment=True,
                     required_level=15, sell_price=100, item_class=2,
                     bag_family=0)
        self.assertTrue(outgrown(sword, character_level=47))
        self.assertEqual(
            decide(sword, TOWN, character_level=47,
                   available=disposition.EXECUTABLE_TODAY,
                   family_fit=FIT_NOBODY).route, VENDOR)

    def test_the_adapter_hands_the_columns_over(self):
        """gear_candidates builds the Item; without these two the gate above
        is a rule nothing can ever reach."""
        tool_row = {"holder": "Bork", "level": 60, "item_guid": 9090,
                    "entry": 7005, "count": 1, "instance_flags": 0,
                    "name": "Finkle's Skinner", "quality": 4, "sell_price": 6000,
                    "required_level": 1, "bonding": 2, "item_class": 2,
                    "bag_family": 8}
        offered = bag_pressure.gear_candidates(
            [tool_row], TOWN, available=disposition.EXECUTABLE_TODAY,
            fits={9090: FIT_NOBODY})
        self.assertEqual(offered, ())
        bagless = bag_pressure.gear_candidates(
            [dict(tool_row, bag_family=0)], TOWN,
            available=disposition.EXECUTABLE_TODAY, fits={9090: FIT_NOBODY})
        self.assertEqual(len(bagless), 1)


class TheBridgeAsksForWhatTheGateNeeds(unittest.TestCase):
    """The seam, read as text: bridge.py imports discord and cannot import."""

    def setUp(self):
        self.src = (pathlib.Path(__file__).resolve().parents[1]
                    / "bridge.py").read_text(encoding="utf-8")

    def test_the_sale_query_carries_the_trade_columns(self):
        block = self.src[self.src.index("_VENDOR_ITEMS_SQL = ("):
                         self.src.index("_SURPLUS_GEAR_SQL = (")]
        for column in ("ii.itemEntry AS entry", "it.class AS item_class",
                       "it.BagFamily AS bag_family"):
            self.assertIn(column, block)

    def test_the_gear_query_carries_the_bag_too(self):
        block = self.src[self.src.index("_SURPLUS_GEAR_SQL = ("):
                         self.src.index("def _fetch_surplus_gear(")]
        self.assertIn("it.BagFamily AS bag_family", block)

    def test_the_permission_read_is_the_declared_roster(self):
        """professions.assigned, not the skills anybody holds today: a miner
        walking to a trainer must not have his pick sold on the journey."""
        block = self.src[self.src.index("def _fetch_vendor_items("):]
        self.assertIn("professions.assigned(name)", block)
        self.assertIn("disposition.profession_keeps(", block)
