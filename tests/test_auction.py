"""auction.py - what it buys, what it refuses to pay, and which house it reads.

EVERY FIXTURE BELOW IS A ROW MEASURED ON THE LIVE REALM on 2026-09-13, not an
invented number, the same discipline test_towntrip.py's own docstring states
and holds its fixtures to: "a threshold tested only against numbers chosen to
make it fire proves nothing."

The ten live listings of the three reagents the family is short of, read from
`auctionhouse` joined to `item_instance` and `item_template`:

    id      item                   house count buyout  per unit
    117766  Peacebloom             2     5     2880    576
    117768  Peacebloom             2     1      632    632
    117765  Peacebloom             6     1      639    639
    117760  Peacebloom             6     10    6700    670
    117764  Peacebloom             6     5     3550    710
    116856  Rough Stone            6     20    2820    141
    116859  Rough Stone            2     15    2565    171
    116858  Rough Stone            7     20    3520    176
    116853  Rough Stone            2     1      180    180
    116679  Ruined Leather Scraps  6     5     1605    321

and the purses, also measured: Grug 1,663,413 copper, Grog 1,782,663, Bork
1,557,501, Og 1,690,879, Ugga 1,718,394.

THE HOUSE SPLIT IS THE POINT OF HALF THIS SUITE. `AllowTwoSide.Interaction.Auction`
is 0 on this realm, so the three houses are disjoint pools and `DoAuction` shops
in exactly the one its auctioneer's faction serves. The family is ALLIANCE
(races 1, 3 and 7 - Human, Dwarf, Gnome, behind five orcish-sounding names), so
houseid 6 is invisible to them for ever. That is why
`test_bork_cannot_buy_his_reagent_from_a_neutral_counter` exists: his reagent
has exactly one listing on the whole realm and it is in the Horde house.
"""

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import auction  # noqa: E402
import travel  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "mod-overseer/src/overseer_decisions.cpp"
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"
BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _listing(auction_id, entry, label, count, buyout, house):
    return auction.Listing(
        auction_id=auction_id,
        entry=entry,
        label=label,
        count=count,
        buyout=buyout,
        house=house,
    )


# The ten measured listings, in the order the table above lists them.
LIVE = [
    _listing(117766, 2447, "Peacebloom", 5, 2880, 2),
    _listing(117768, 2447, "Peacebloom", 1, 632, 2),
    _listing(117765, 2447, "Peacebloom", 1, 639, 6),
    _listing(117760, 2447, "Peacebloom", 10, 6700, 6),
    _listing(117764, 2447, "Peacebloom", 5, 3550, 6),
    _listing(116856, 2835, "Rough Stone", 20, 2820, 6),
    _listing(116859, 2835, "Rough Stone", 15, 2565, 2),
    _listing(116858, 2835, "Rough Stone", 20, 3520, 7),
    _listing(116853, 2835, "Rough Stone", 1, 180, 2),
    _listing(116679, 2934, "Ruined Leather Scraps", 5, 1605, 6),
]

PURSES = {
    "Grug": 1663413,
    "Grog": 1782663,
    "Bork": 1557501,
    "Og": 1690879,
    "Ugga": 1718394,
}

SLOTS = {name: 8 for name in PURSES}


class CommandGrammarTest(unittest.TestCase):
    """The rendered command must be what the deployed parser accepts."""

    def test_the_buy_command_is_the_documented_shape(self):
        self.assertEqual(auction.buy_command(116856), "buy auction:116856")

    def test_a_zero_auction_id_is_refused_rather_than_rendered(self):
        # ParseAuctionRequest rejects a zero id by name, because the core reads
        # it as a malformed packet and returns silently.
        with self.assertRaises(ValueError):
            auction.buy_command(0)

    def test_a_negative_auction_id_is_refused(self):
        with self.assertRaises(ValueError):
            auction.buy_command(-1)

    def test_the_parser_accepts_the_verb_this_module_writes(self):
        """Read ParseAuctionRequest's own source and pin the grammar.

        The same structural discipline test_travel_npc.py applies to the travel
        keywords: two copies of a vocabulary that must agree, compared by a
        test rather than by a comment asking somebody to remember.
        """
        source = DECISIONS.read_text(encoding="utf-8", errors="ignore")
        self.assertIn('words[0] == "buy"', source)
        # `auction:` is the key a buy carries, and it is accepted for every
        # verb that is not List.
        self.assertIn('key == "auction" && verb != AuctionVerb::List', source)

    def test_a_buy_needs_exactly_the_auction_key_and_no_other(self):
        """`complete` for Buy is `sawAuction` alone - no bid, no buyout."""
        source = DECISIONS.read_text(encoding="utf-8", errors="ignore")
        # The Buy and Cancel arms share a completeness rule of `sawAuction`.
        self.assertRegex(
            source,
            r"case AuctionVerb::Buy:\s*\n\s*case AuctionVerb::Cancel:\s*\n\s*"
            r"complete = sawAuction;",
        )
        # Which is why this module never renders a bid on a buy: a `buy`
        # carrying `bid:` is refused as malformed rather than interpreted.
        self.assertNotIn("bid:", auction.buy_command(1))


class HouseTest(unittest.TestCase):
    """Which pool a character is shopping in, and why it is not their own."""

    def test_the_three_house_ids(self):
        """2 Alliance, 6 Horde, 7 Blackwater/neutral.

        Disputed during review, so it is worth recording where this comes
        from. The core's own `enum class AuctionHouseId : uint8 { Alliance = 2,
        Horde = 6, Neutral = 7 }` at the pinned AC_CORE_SHA, corroborated by
        the realm's own AuctionHouse.dbc (record 7 is "Blackwater Auction
        House" at a 25 percent deposit against 5 for the other two), by the
        schema default of 7, and by the deposits actually charged (house 7
        averages 1,084 copper against 275 and 221).
        """
        self.assertEqual(auction.HOUSE_ALLIANCE, 2)
        self.assertEqual(auction.HOUSE_HORDE, 6)
        self.assertEqual(auction.HOUSE_NEUTRAL, 7)

    def test_the_module_iterates_the_same_three_houses(self):
        # mod_overseer.cpp's own WrongHouse sweep names all three, which is
        # the C++ side of the same vocabulary.
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        self.assertIn(
            "{AuctionHouseId::Alliance, AuctionHouseId::Horde, "
            "AuctionHouseId::Neutral}",
            source,
        )

    def test_the_family_is_alliance(self):
        # Measured races: Grug/Ugga/Og 1 (Human), Grog 3 (Dwarf), Bork 7
        # (Gnome). The names are not evidence and another pass had the same
        # mistake corrected in it today.
        for race in (1, 3, 7):
            self.assertEqual(auction.team_of(race), "alliance")

    def test_a_neutral_auctioneer_serves_the_neutral_house(self):
        # 474 is Gadgetzan/Steamwheedle, which is Beardo (entry 8661), the
        # nearest auctioneer to the family at about 1,731 yards.
        self.assertEqual(
            auction.reachable_house("alliance", 474), auction.HOUSE_NEUTRAL
        )

    def test_the_same_neutral_counter_serves_a_horde_character_too(self):
        # The goblin house is open to both sides, so the team does not enter
        # into it. This is not a hole in the fail-closed rule below.
        self.assertEqual(auction.reachable_house("horde", 474), auction.HOUSE_NEUTRAL)

    def test_a_faction_auctioneer_serves_that_faction_house(self):
        # 12 is Stormwind, 55 Ironforge, 80 Darnassus.
        for faction in (12, 55, 80):
            self.assertEqual(
                auction.reachable_house("alliance", faction),
                auction.HOUSE_ALLIANCE,
            )

    def test_an_unknown_team_at_a_faction_counter_fails_closed(self):
        self.assertEqual(auction.reachable_house("", 12), 0)

    def test_map_without_an_auctioneer_is_not_a_trip_target(self):
        self.assertFalse(auction.auctioneer_map_available(1, {0, 530}))

    def test_map_with_an_auctioneer_remains_eligible(self):
        self.assertTrue(auction.auctioneer_map_available(0, {0, 530}))

    def test_unknown_map_fails_closed(self):
        self.assertFalse(auction.auctioneer_map_available(None, {0}))

    def test_house_zero_keeps_no_listing_at_all(self):
        # Which is what makes failing closed actually close: an unknown team
        # buys nothing rather than buying from a pool it may not reach.
        self.assertEqual(auction.usable(LIVE, 2835, 0), [])

    def test_every_neutral_faction_is_one_a_real_auctioneer_carries(self):
        # The set is an enumeration of what is actually spawned, because the
        # reaction that really decides this lives in FactionTemplate.dbc, which
        # is not in the database. 120 Booty Bay, 474 Gadgetzan, 534/714
        # Dalaran, 855 Everlook.
        self.assertEqual(
            auction.NEUTRAL_AUCTIONEER_FACTIONS,
            frozenset({120, 474, 534, 714, 855}),
        )


class UsableTest(unittest.TestCase):
    def test_only_this_house_survives(self):
        got = auction.usable(LIVE, 2835, auction.HOUSE_NEUTRAL)
        self.assertEqual([item.auction_id for item in got], [116858])

    def test_the_alliance_house_has_its_own_two(self):
        got = auction.usable(LIVE, 2835, auction.HOUSE_ALLIANCE)
        # Cheapest per unit first: 171 (id 116859) before 180 (id 116853).
        self.assertEqual([item.auction_id for item in got], [116859, 116853])

    def test_a_listing_with_no_buyout_is_dropped(self):
        # A bid buys nothing, and DoAuction refuses one by name (NoBuyout).
        bid_only = _listing(1, 2835, "Rough Stone", 20, 0, 7)
        self.assertEqual(auction.usable([bid_only], 2835, 7), [])

    def test_an_empty_stack_is_dropped(self):
        self.assertEqual(
            auction.usable([_listing(1, 2835, "Rough Stone", 0, 500, 7)], 2835, 7),
            [],
        )

    def test_ties_break_on_auction_id_so_the_answer_is_stable(self):
        a = _listing(20, 2835, "Rough Stone", 1, 100, 7)
        b = _listing(10, 2835, "Rough Stone", 1, 100, 7)
        self.assertEqual(
            [x.auction_id for x in auction.usable([a, b], 2835, 7)], [10, 20]
        )


class PerUnitTest(unittest.TestCase):
    def test_a_stack_and_a_single_at_the_same_price_rank_the_same(self):
        stack = _listing(1, 2835, "Rough Stone", 20, 2820, 6)
        single = _listing(2, 2835, "Rough Stone", 1, 141, 6)
        self.assertEqual(stack.per_unit, single.per_unit)
        self.assertEqual(stack.per_unit, 141)

    def test_rounding_is_up_so_a_ceiling_is_never_passed_by_a_remainder(self):
        # 101 copper over 2 items is 50.5 each; a ceiling of 50 must refuse it.
        odd = _listing(1, 2835, "Rough Stone", 2, 101, 7)
        self.assertEqual(odd.per_unit, 51)

    def test_a_zero_count_never_divides_by_zero(self):
        self.assertEqual(_listing(1, 2835, "x", 0, 100, 7).per_unit, 100)


class CeilingTest(unittest.TestCase):
    def test_the_ceiling_is_a_multiple_of_the_cheapest_not_the_median(self):
        alliance = auction.usable(LIVE, 2835, auction.HOUSE_ALLIANCE)
        # Cheapest reachable per unit is 171, so the bar is 342. The median of
        # those two listings is 175.5, which would have been a different and
        # much tighter answer.
        self.assertEqual(auction.ceiling_for(alliance), 342)

    def test_an_empty_market_admits_nothing(self):
        self.assertEqual(auction.ceiling_for([]), 0)

    def test_the_multiple_clears_the_sellers_own_measured_spread(self):
        """The seller's variation caps any one item's spread at 1.4706.

        `BuyoutVariationReducePercent = 0.15` and `AddPercent = 0.25` give
        1.25/0.85, and a survey of the thirty most-listed items found every one
        between 1.31 and 1.47. The multiple has to sit above that so an
        ordinary listing is never refused, and below the mispricings it exists
        to catch.
        """
        self.assertGreater(auction.OUTLIER_MULTIPLE, 1.4706)

    def test_a_legitimate_listing_at_the_top_of_the_band_still_passes(self):
        cheap = _listing(1, 2835, "Rough Stone", 1, 100, 7)
        dear = _listing(2, 2835, "Rough Stone", 1, 147, 7)
        market = auction.usable([cheap, dear], 2835, 7)
        self.assertLessEqual(dear.per_unit, auction.ceiling_for(market))


class ShortfallTest(unittest.TestCase):
    """The arithmetic that stops the pass buying the same reagent for ever."""

    def test_the_mail_counts_as_already_bought(self):
        # 20 casts of a one-per-cast reagent. Nothing carried, twenty in the
        # mail: the shortfall is zero, so the pass does not buy it again.
        self.assertEqual(auction.short_of(1, carried=0, in_mail=20), 0)

    def test_without_the_mail_the_shortfall_would_never_fall(self):
        # This is the runaway, stated as a test: a purchase does not touch the
        # bags, so bags-only would still read a full shortfall next cycle.
        self.assertEqual(auction.short_of(1, carried=0, in_mail=0), 20)

    def test_a_multi_reagent_cast_scales_the_target(self):
        # Light Leather consumes 3 Ruined Leather Scraps per cast.
        self.assertEqual(auction.short_of(3, carried=0, in_mail=0), 60)

    def test_being_stocked_is_zero_and_never_negative(self):
        self.assertEqual(auction.short_of(1, carried=500, in_mail=0), 0)

    def test_bags_and_mail_add_rather_than_either_winning(self):
        self.assertEqual(auction.short_of(1, carried=8, in_mail=7), 5)


class GatheredTableTest(unittest.TestCase):
    """The reagent table, against what the roster is actually set to craft."""

    def test_every_family_craft_spell_is_covered(self):
        # Measured overseer_roster.craft_spell for the five.
        for spell_id in (2660, 2881, 2330, 3918, 2963):
            self.assertIn(spell_id, auction.GATHERED)

    def test_the_reagents_are_the_ones_spell_dbc_names(self):
        # Read from the realm's own Spell.dbc, md5-verified against the running
        # worldserver, at the 3.3.5a Reagent field offsets.
        def shape(spell_id):
            return tuple(
                (r.entry, r.label, r.per_cast) for r in auction.GATHERED[spell_id]
            )

        self.assertEqual(shape(2660), ((2835, "Rough Stone", 1),))
        self.assertEqual(shape(3918), ((2835, "Rough Stone", 1),))
        self.assertEqual(shape(2881), ((2934, "Ruined Leather Scraps", 3),))
        self.assertEqual(shape(2963), ((2589, "Linen Cloth", 2),))

    def test_the_table_is_craft_rhythms_and_not_a_second_copy(self):
        """One table, because two passes must agree about what "short" means.

        This module authored its own and deleted it: the two were built
        independently from the same Spell.dbc and agreed exactly, which is a
        good sign about both and a terrible reason to keep them both. If they
        ever diverged, `craft_rhythm` would send the family gathering for a
        reagent this pass had decided to buy, or the reverse.
        """
        import craft_rhythm

        self.assertIs(auction.GATHERED, craft_rhythm.GATHERED)

    def test_the_vendor_bought_reagent_is_deliberately_absent(self):
        """Minor Healing Potion also needs an Empty Vial, and craft_supply
        already buys it for 20 copper at unlimited stock.

        Two passes buying the same reagent would be two passes spending twice,
        and the vendor one is cheaper and needs no mailbox.
        """
        entries = {r.entry for r in auction.GATHERED[2330]}
        self.assertEqual(entries, {2447, 765})
        self.assertNotIn(3371, entries)

    def test_no_entry_here_is_one_craft_supply_already_buys(self):
        import craft_supply

        vendor_bought = {entry for entry, _l, _p in craft_supply.REAGENT.values()}
        for reagents in auction.GATHERED.values():
            for reagent in reagents:
                self.assertNotIn(
                    reagent.entry,
                    vendor_bought,
                    "%s (%d) is bought from a vendor by craft_supply already"
                    % (reagent.label, reagent.entry),
                )


class RhythmInteractionTest(unittest.TestCase):
    """The pass must not go dark exactly when it is needed (infra#3734)."""

    def test_the_pass_does_not_gate_on_the_crafting_job(self):
        """`craft_rhythm` moves the family to MODE_GATHER the moment any of
        them is short, which is precisely when there is something to buy.

        Reading `_fetch_craft_spells` here - which filters `job = 'craft'` -
        would make this pass dark on every cycle that mattered and green on
        every cycle with nothing to do: a dry run that is true and meaningless.
        """
        body = BRIDGE.read_text(encoding="utf-8", errors="ignore")
        start = body.index("async def _auction_once(")
        end = body.index("async def _auction_loop(")
        pass_body = body[start:end]
        self.assertIn("to_thread(_fetch_standing_crafts, names)", pass_body)
        # The CALL, not the prose: both readers are named in the comments
        # explaining why one was chosen over the other.
        self.assertFalse(
            "to_thread(_fetch_craft_spells" in pass_body,
            "the auction pass calls the job='craft'-filtered reader, so it "
            "goes dark exactly when craft_rhythm sends the family gathering",
        )

    def test_the_standing_craft_reader_does_not_filter_on_job(self):
        body = BRIDGE.read_text(encoding="utf-8", errors="ignore")
        start = body.index("def _fetch_standing_crafts(")
        end = body.index("def _fetch_item_counts(")
        reader = body[start:end]
        # The SQL, not the docstring, which necessarily quotes the filter it
        # is explaining the absence of.
        sql = reader[reader.index("cur.execute(") :]
        self.assertIn("r.craft_spell > 0", sql)
        self.assertFalse(
            "job = 'craft'" in sql,
            "the standing-craft reader filters on the crafting job, which is "
            "the one thing it exists not to do",
        )

    def test_gathering_mode_is_not_a_reason_to_stop_shopping(self):
        # The two passes answer different questions and both can be true at
        # once: go and gather this, AND buy it if it is cheap on the way.
        import craft_rhythm

        self.assertEqual(craft_rhythm.MODE_GATHER, "quest")
        self.assertNotEqual(craft_rhythm.MODE_GATHER, craft_rhythm.MODE_CRAFT)


class WantedTest(unittest.TestCase):
    def test_a_two_reagent_recipe_raises_two_needs(self):
        needs = auction.wanted(2330, carried={}, in_mail={})
        self.assertEqual(sorted(n.entry for n in needs), [765, 2447])

    def test_a_reagent_already_held_raises_no_need(self):
        # Ugga carries 7 Silverleaf and 0 Peacebloom, measured.
        needs = auction.wanted(2330, carried={765: 700}, in_mail={})
        self.assertEqual([n.entry for n in needs], [2447])

    def test_an_unknown_craft_spell_raises_nothing(self):
        self.assertEqual(auction.wanted(999999, {}, {}), [])


class PlanBuysTest(unittest.TestCase):
    """The whole decision, against the measured market."""

    def test_grug_buys_the_one_rough_stone_stack_at_a_neutral_counter(self):
        needs = [auction.Need("Grug", 2835, "Rough Stone", 20)]
        buys, _notes = auction.plan_buys(
            needs,
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual([b.auction_id for b in buys], [116858])
        self.assertEqual(buys[0].spend, 3520)
        self.assertEqual(buys[0].command, "buy auction:116858")

    def test_the_cheaper_horde_stack_is_never_reached_from_a_neutral_counter(self):
        # 116856 is 141/unit against the neutral house's 176, and it is in a
        # pool this family can never shop in.
        needs = [auction.Need("Grug", 2835, "Rough Stone", 20)]
        buys, _notes = auction.plan_buys(
            needs,
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertNotIn(116856, [b.auction_id for b in buys])

    def test_cheapest_first_within_the_reachable_house(self):
        needs = [auction.Need("Grug", 2835, "Rough Stone", 20)]
        buys, _notes = auction.plan_buys(
            needs,
            LIVE,
            auction.HOUSE_ALLIANCE,
            PURSES,
            free_slots=SLOTS,
        )
        # 171/unit before 180/unit, and the 15-stack alone does not cover 20,
        # so the single is taken as well.
        self.assertEqual([b.auction_id for b in buys], [116859, 116853])

    def test_bork_cannot_buy_his_reagent_from_a_neutral_counter(self):
        """The only Ruined Leather Scraps listing on the realm is Horde-side.

        This is the case that must produce a SENTENCE rather than a row: a
        queued buy for it could only ever come back `wrong auction house`,
        for ever, from any counter this family can reach.
        """
        needs = [auction.Need("Bork", 2934, "Ruined Leather Scraps", 60)]
        buys, notes = auction.plan_buys(
            needs,
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual(buys, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("Ruined Leather Scraps", notes[0])
        self.assertIn("Bork", notes[0])

    def test_one_unbuyable_reagent_does_not_stop_the_others(self):
        needs = [
            auction.Need("Bork", 2934, "Ruined Leather Scraps", 60),
            auction.Need("Grug", 2835, "Rough Stone", 20),
        ]
        buys, notes = auction.plan_buys(
            needs,
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual([b.shopper for b in buys], ["Grug"])
        self.assertTrue(any("Bork" in note for note in notes))

    def test_the_spend_cap_holds_when_the_market_defeats_the_ceiling(self):
        """A market of ONE listing defeats layers 1 and 2 by construction.

        The cheapest listing is also the only listing, so the multiple is
        measured against itself and any price passes it. This is the live case,
        not a theoretical one - Rough Stone has exactly one reachable listing -
        and the absolute cap is the only thing standing between the family and
        the most expensive item on the realm.
        """
        absurd = [_listing(999, 2835, "Rough Stone", 1, 5_187_000, 7)]
        buys, notes = auction.plan_buys(
            [auction.Need("Grug", 2835, "Rough Stone", 20)],
            absurd,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual(buys, [])
        self.assertTrue(any("beyond" in note for note in notes))

    def test_the_cap_binds_even_though_the_character_could_afford_it(self):
        # Grug carries 1,663,413 copper, so HasEnoughMoney would pass and
        # DoAuction would execute the row. Nothing in the C++ stops this.
        self.assertGreater(PURSES["Grug"], 100_000)
        pricey = [_listing(1, 2835, "Rough Stone", 1, 100_000, 7)]
        buys, _notes = auction.plan_buys(
            [auction.Need("Grug", 2835, "Rough Stone", 20)],
            pricey,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual(buys, [])

    def test_the_outlier_multiple_refuses_a_mispriced_listing(self):
        market = [
            _listing(1, 2835, "Rough Stone", 1, 170, 7),
            _listing(2, 2835, "Rough Stone", 1, 900, 7),
        ]
        buys, _notes = auction.plan_buys(
            [auction.Need("Grug", 2835, "Rough Stone", 20)],
            market,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual([b.auction_id for b in buys], [1])

    def test_a_poor_character_is_capped_by_its_purse_not_the_allowance(self):
        buys, notes = auction.plan_buys(
            [auction.Need("Skint", 2835, "Rough Stone", 20)],
            LIVE,
            auction.HOUSE_NEUTRAL,
            {"Skint": 5},
            free_slots={"Skint": 8},
        )
        self.assertEqual(buys, [])
        self.assertTrue(notes)

    def test_no_free_slot_means_no_purchase(self):
        buys, notes = auction.plan_buys(
            [auction.Need("Grug", 2835, "Rough Stone", 20)],
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots={"Grug": 0},
        )
        self.assertEqual(buys, [])
        self.assertTrue(any("bag slot" in note for note in notes))

    def test_one_auction_is_never_sold_to_two_characters(self):
        needs = [
            auction.Need("Grug", 2835, "Rough Stone", 20),
            auction.Need("Grog", 2835, "Rough Stone", 20),
        ]
        buys, _notes = auction.plan_buys(
            needs,
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        ids = [b.auction_id for b in buys]
        self.assertEqual(len(ids), len(set(ids)))

    def test_one_character_cannot_exceed_the_cap_across_two_reagents(self):
        """The cap accumulates within a character, not just within one need.

        Raised in review: `_auction_once` tallies `spent` only for its log line,
        so if the cap were enforced per NEED rather than per CHARACTER, a
        character short of two reagents could spend twice the allowance in one
        pass. It is not - `plan_buys` is called once per shopper with ALL of
        that shopper's needs and carries a running `spent` across them - and
        this is the test that says so rather than the argument.
        """
        market = [
            _listing(1, 2835, "Rough Stone", 20, 15_000, 7),
            _listing(2, 2447, "Peacebloom", 20, 15_000, 7),
        ]
        needs = [
            auction.Need("Ugga", 2835, "Rough Stone", 20),
            auction.Need("Ugga", 2447, "Peacebloom", 20),
        ]
        buys, _notes = auction.plan_buys(
            needs,
            market,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        # Each is affordable alone (15,000 < 20,000) and together they are not.
        self.assertEqual(len(buys), 1)
        self.assertLessEqual(sum(b.spend for b in buys), auction.SPEND_CAP_COPPER)

    def test_two_characters_are_never_queued_against_one_auction(self):
        """One auction is one stack; the second row could only ever be
        refused `AuctionNotFound`."""
        market = [_listing(1, 2835, "Rough Stone", 20, 500, 7)]
        needs = [
            auction.Need("Grug", 2835, "Rough Stone", 20),
            auction.Need("Grog", 2835, "Rough Stone", 20),
        ]
        buys, _notes = auction.plan_buys(
            needs,
            market,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual(len(buys), 1)

    def test_bag_slots_are_spent_across_a_characters_own_needs(self):
        market = [
            _listing(1, 2835, "Rough Stone", 20, 500, 7),
            _listing(2, 2447, "Peacebloom", 20, 500, 7),
        ]
        needs = [
            auction.Need("Ugga", 2835, "Rough Stone", 20),
            auction.Need("Ugga", 2447, "Peacebloom", 20),
        ]
        buys, notes = auction.plan_buys(
            needs,
            market,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots={"Ugga": 1},
        )
        self.assertEqual(len(buys), 1)
        self.assertTrue(any("bag slot" in note for note in notes))

    def test_the_spend_cap_is_per_character_not_per_family(self):
        # Two characters each get their own allowance; one's spending must not
        # ration the other's.
        market = [
            _listing(1, 2835, "Rough Stone", 20, 15_000, 7),
            _listing(2, 2835, "Rough Stone", 20, 15_000, 7),
        ]
        needs = [
            auction.Need("Grug", 2835, "Rough Stone", 20),
            auction.Need("Grog", 2835, "Rough Stone", 20),
        ]
        buys, _notes = auction.plan_buys(
            needs,
            market,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual(sorted(b.shopper for b in buys), ["Grog", "Grug"])

    def test_a_satisfied_need_buys_nothing(self):
        buys, notes = auction.plan_buys(
            [auction.Need("Grug", 2835, "Rough Stone", 0)],
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        self.assertEqual(buys, [])
        self.assertEqual(notes, [])

    def test_an_empty_pass_is_not_an_error(self):
        self.assertEqual(
            auction.plan_buys([], LIVE, 7, PURSES, free_slots=SLOTS), ([], [])
        )

    def test_every_refusal_carries_a_whole_sentence_naming_the_shopper(self):
        needs = [auction.Need("Bork", 2934, "Ruined Leather Scraps", 60)]
        _buys, notes = auction.plan_buys(
            needs,
            LIVE,
            auction.HOUSE_NEUTRAL,
            PURSES,
            free_slots=SLOTS,
        )
        for note in notes:
            self.assertIn("Bork", note)
            self.assertGreater(len(note), 40)


class SalePlannerTest(unittest.TestCase):
    def test_listing_command_matches_mod_grammar(self):
        self.assertEqual(
            auction.list_command(44, 800, 1000),
            "list guid:44 bid:800 buyout:1000 hours:12",
        )

    def test_rare_is_never_listed(self):
        rows = [
            {
                "holder": "Bork",
                "item_guid": 1,
                "entry": 2,
                "quality": 3,
                "market_price": 1000,
            }
        ]
        self.assertEqual(auction.plan_sales(rows), ())

    def test_claimed_upgrade_is_never_listed(self):
        rows = [
            {
                "holder": "Bork",
                "item_guid": 1,
                "entry": 2,
                "quality": 2,
                "market_price": 1000,
                "recipient": "Og",
            }
        ]
        self.assertEqual(auction.plan_sales(rows), ())

    def test_surplus_boe_gets_a_bounded_price(self):
        rows = [
            {
                "holder": "Bork",
                "item_guid": 1,
                "entry": 2,
                "quality": 2,
                "sell_price": 100,
                "market_price": 500,
            }
        ]
        (sale,) = auction.plan_sales(rows)
        self.assertEqual((sale.bid, sale.buyout), (400, 500))


class VocabularyTest(unittest.TestCase):
    """The keyword this module aims with, across its three copies."""

    def test_the_role_is_read_from_travel_rather_than_spelled(self):
        self.assertEqual(auction.AUCTIONEER_ROLE, "auctioneer")
        self.assertIn(auction.AUCTIONEER_ROLE, travel.ROLES)

    def test_the_bridge_carries_it_as_an_economy_errand(self):
        """infra#3712's auctioneer half.

        Without this, `_retaskable_from` answers () for an auctioneer aim and
        `_write_trade_errand` takes its OTHER branch - the unconditional one
        that also writes learn_skill/unlearn_skill/unlearn_max - so writing the
        aim would silently zero an outstanding trainer errand. And
        `_release_trade_errand` guards on the same tuple, so the errand could
        never be handed back.
        """
        body = BRIDGE.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"^ECONOMY_ERRANDS = \((.*?)\)$", body, re.M)
        self.assertIsNotNone(match, "ECONOMY_ERRANDS is not a flat tuple any more")
        self.assertIn('"auctioneer"', match.group(1))

    def test_the_cpp_counter_role_knows_the_same_keyword(self):
        """The other side of the mirror infra#3712 says nothing compares.

        mod-overseer#402 added `auctioneer` to CounterRoleForAim; this asserts
        it is still there, because it is what takes the counter hold that keeps
        a character at the auctioneer while the rows run.
        """
        source = DECISIONS.read_text(encoding="utf-8", errors="ignore")
        self.assertRegex(
            source,
            r'if \(aim == "auctioneer"\)\s*\n\s*return CounterRole::Auctioneer;',
        )

    def test_the_travel_role_maps_to_the_auctioneer_npcflag(self):
        self.assertEqual(travel.ROLES["auctioneer"], "UNIT_NPC_FLAG_AUCTIONEER")


class ExecutorContractTest(unittest.TestCase):
    """Facts about DoAuction this module's design depends on."""

    def test_a_bought_item_arrives_by_mail_and_not_in_the_bags(self):
        """The fact that makes this pass a buyer and not a supplier.

        If this note ever stops being true the collection half stops being
        necessary, and this test is what would say so.
        """
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        self.assertIn('describe("bought", "", "the item arrives by mail', source)

    def test_the_executor_enforces_no_price_ceiling_of_its_own(self):
        """Nothing but HasEnoughMoney stands between a row and the purse.

        This is why the ceiling in auction.py is the only one there is. If a
        budget is ever added on the C++ side this test should be revisited
        rather than deleted.
        """
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        start = source.index("static char const* DoAuction(")
        # To the end of the function, found by its own closing log line rather
        # than by a character count that silently truncates past the buy
        # branch - which is exactly what an earlier draft of this test did.
        end = source.index('describe("bid", "", "");', start)
        body = source[start:end]
        self.assertIn(
            "HasEnoughMoney(price)",
            body,
            "DoAuction no longer gates the buy on the purse alone",
        )
        for invented in ("priceCeiling", "spendLimit", "maxSpend", "goldGuard"):
            self.assertNotIn(
                invented,
                body,
                "the executor grew a %s; auction.py's ceiling may now be "
                "redundant or in conflict" % invented,
            )

    def test_the_range_refusal_comes_before_the_house_is_ever_consulted(self):
        """Why a live 'auctioneer not in range' says nothing about the house.

        A test row that came back NotInRange exited before
        `GetAuctionsMap(auctioneer->GetFaction())` ran, so it carries no
        evidence at all about whether its auction id was in a reachable pool.
        Reading it as evidence is how the house mapping gets inverted.
        """
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        not_in_range = source.index("refuse(R::NotInRange)")
        picks_house = source.index("GetAuctionsMap(auctioneer->GetFaction())")
        wrong_house = source.index("refuse(R::WrongHouse)")
        self.assertLess(not_in_range, picks_house)
        self.assertLess(picks_house, wrong_house)


if __name__ == "__main__":
    unittest.main()
