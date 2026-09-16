"""What to buy off the auction house for a starving craft errand, and what
never to pay for it.

WHY THIS EXISTS (infra#3731's reagent half). All five of the family are sitting
on a craft errand they cannot cast, because none of them holds the material
their own recipe consumes. Measured on the live realm 2026-09-13, every one of
them blocked on exactly one reagent:

    character  craft_spell  recipe                  short of
    Grug       2660         Rough Sharpening Stone  Rough Stone (0 of 1/cast)
    Grog       3918         Rough Blasting Powder   Rough Stone (0 of 1/cast)
    Bork       2881         Light Leather           Ruined Leather Scraps (0 of 3)
    Ugga       2330         Minor Healing Potion    Peacebloom (0 of 1/cast)
    Og         2963         Bolt of Linen Cloth     Linen Cloth (1 of 2/cast)

`DriveCraft`'s reagent pre-filter skips a character with no reagents SILENTLY,
which is infra#3696's point: a correct errand with no materials looks exactly
like a character with nothing to do.

None of those five reagents is vendor-bought, which is why `craft_supply.py`
cannot answer this. That module buys vials, thread and dye, and its own
docstring draws the boundary on purpose: Moss Agate was deliberately kept out
of it because it carries zero `npc_vendor` rows and is a GATHERED item, and
"`REAGENT` must never carry an `entry` that `town.stocks` can never contain".
Checked again here against `npc_vendor` rather than inherited: Rough Stone and
Ruined Leather Scraps have no vendor anywhere on this world at all.

BUYING AND GATHERING ARE NOT ALTERNATIVES, AND THIS MODULE IS NOT infra#3696's
RIVAL. That issue is answered: `craft_rhythm` ships the alternation, sending
the family out to gather the moment any of them is short and back to the anvil
once they are stocked. That is the right steady state - three of the five carry
the gathering profession that produces their own reagent (Grug Mining, Bork
Skinning, Ugga Herbalism) and a character that feeds itself needs nobody's
gold.

What this adds is that the same shortfall is often closable for a few silver on
the way. The entire live supply of Rough Stone on the whole house costs 9,085
copper against the 155 to 178 gold each of the five is carrying, and the
gathering trip taken before the alternation existed ended in two deaths on a
level 61 elite. So the two compose rather than compete, and the one thing this
module must not do is make itself conditional on the crafting mode: the family
is sent OUT to gather precisely when there is something worth buying, so a pass
that only ran during `job='craft'` would be dark on every cycle that mattered.
`bridge._auction_once` reads `craft_spell`, which is the standing errand, and
never `job`, which is the current mode.

THE MECHANISM WAS ALREADY DEPLOYED AND HAD NEVER HAD A CALLER. `DoAuction`
(mod_overseer.cpp) has dispatched `kind='auction'` since mod-overseer#208, the
ENUM on `overseer_command.kind` has carried `'auction'` since
2026_09_04_03_overseer_auction.sql, and nothing in this process has ever
inserted one. `disposition.py` has carried a comment saying exactly that for
just as long. This module and `bridge._auction_once` are that missing caller.

THE GRAMMAR IS READ OFF THE DEPLOYED PARSER, NOT COPIED FROM AN EXAMPLE.
`OverseerDecisions::ParseAuctionRequest` splits on runs of spaces and tabs,
takes one of exactly four verbs in `words[0]`, and requires every remaining
token to be `key:value` with a decimal value fitting a uint32. For `buy` the
one accepted key is `auction:`; it is required, it may not repeat, and no
other key may appear - a `buy` carrying a `bid:` is refused as malformed
rather than interpreted. So the whole command is `buy auction:<auctionhouse.id>`,
which `buy_command` renders and `tests/test_auction.py` pins against the
parser's own source text.

WHY BUYOUT AND NEVER A BID, although `DoAuction` implements both. A bid does
not buy anything: it locks the money for up to 48 hours, can be outbid, and
comes back by mail if it is. What this pass is for is putting a reagent in a
character's hands, and only a buyout does that. A listing with no buyout is
therefore not a cheap opportunity but an unusable one, and it is dropped
before the ceiling is consulted - `DoAuction` refuses it by name (`NoBuyout`)
anyway.

------------------------------------------------------------------------------
THE THREE HOUSES ARE SEGREGATED, WHICH IS THE FACT THAT SHAPES EVERYTHING
------------------------------------------------------------------------------

This was NOT known when this work was scoped and it changes what is buyable.
The live `worldserver.conf` carries `AllowTwoSide.Interaction.Auction = 0`, so
the core keeps three disjoint auction pools, and `DoAuction` picks which one a
character is shopping in from the AUCTIONEER, never from the player:

    AuctionHouseObject* house = sAuctionMgr->GetAuctionsMap(auctioneer->GetFaction());

An auction id that exists in a different pool is refused `WrongHouse` after the
whole family has walked to the counter, which is a long way to go to be told
no. So a plan that does not filter by house is a plan that mostly fails.

`auctionhouse.houseid` holds which pool, and the mapping is 2 = Alliance,
6 = Horde, 7 = Blackwater (the neutral goblin house). This is worth four lines
of evidence rather than one, because it was disputed during review and getting
it backwards would queue rows that can only ever be refused:

  1. THE CORE'S OWN ENUM, at the SHA this realm pins (`AC_CORE_SHA` in
     UPSTREAM-PINS.env), `AuctionHouseMgr.h`:
         enum class AuctionHouseId : uint8 { Alliance = 2, Horde = 6, Neutral = 7 };
  2. THE REALM'S OWN `AuctionHouse.dbc`, the file the live worldserver loaded.
     Record 6 is "Horde Auction House" (faction 2); record 7 is "Blackwater
     Auction House" (faction 369) at a 25 percent deposit and 15 percent
     consignment against 5 and 5 for the other two - the goblin house's
     well-known higher cut.
  3. THE SCHEMA DEFAULT. `auctionhouse.houseid` is `tinyint unsigned NOT NULL
     DEFAULT '7'`, which is AzerothCore defaulting to neutral.
  4. THE DEPOSIT ACTUALLY CHARGED. Live rows average 1,084 copper of deposit in
     house 7 against 275 and 221 in houses 2 and 6 - the 5x rate showing
     straight through.

The database cannot answer it: `acore_world.auctionhouse_dbc` exists and holds
zero rows, the same empty shell `skillline_dbc` is.

AND A LIVE `"auctioneer not in range"` IS NOT EVIDENCE ABOUT ANY OF THIS, which
is the trap that made it disputable. That refusal returns at mod_overseer.cpp
:33076, and the house is not resolved until :33086 nor the auction looked up
until :33182, so such a row never reached the house comparison at all. Sharper
still: `describe()` emits its `auctioneer` block only `if (facts.haveAuctioneer)`
and that flag is set at :33077, AFTER the return - so a `NotInRange` result
structurally cannot name an auctioneer, and one that does not is saying the
character was not at a counter, not that the house matched. The row that would
actually settle a house question is a `wrong auction house` refusal, which
carries `auction:{"house":N}` explicitly.

THE FAMILY IS ALLIANCE (races Human, Dwarf, Gnome), so houseid 6 is invisible
to them permanently, and that is not a detail. Of the ten live listings of the
three reagents this module would most like to buy:

    Rough Stone (2835)            house 2: 16 units   house 7: 20 units   house 6: 20
    Peacebloom (2447)             house 2:  6 units   house 7:  0         house 6: 16
    Ruined Leather Scraps (2934)  house 2:  0         house 7:  0         house 6:  5

Bork's reagent has exactly one listing on the entire realm and it is Horde
side. No walk, no price and no amount of money will buy it. `plan_buys` says
so in a sentence rather than queueing a row that can only ever be refused.

AND WHICH HOUSE IS REACHABLE DEPENDS ON WHICH AUCTIONEER THEY WALK TO, not on
who they are: an Alliance character at a goblin auctioneer is shopping in the
neutral house, and the same character in Darnassus is shopping in the Alliance
one. `reachable_house` answers that from the auctioneer actually in reach, and
the bridge asks it only about a character that has arrived - the same
"nothing is planned until they have arrived" discipline `_towntrip_once`
already states, which is what lets this module hold no state and survive a
restart.

------------------------------------------------------------------------------
THE PRICE CEILING, WHICH IS THE ONE REAL DECISION IN THIS FILE
------------------------------------------------------------------------------

NOTHING ELSE ENFORCES ONE. Checked by reading the deployed executor rather than
assumed: `DoAuction` tests `player->HasEnoughMoney(price)` and
`price > MAX_MONEY_AMOUNT`, and that is all. `MAX_MONEY_AMOUNT` is the core's
integer ceiling (about 214,748 gold), not a policy, and its refusal literal
"price above the money cap" is the only string in the whole auction path that
even sounds like a budget. There is no per-row cap, no per-character budget, no
config key, and no comparison against any reference price anywhere in the C++.
A row asking a character to pay every copper it owns for one listing would be
executed. Whatever ceiling exists is the one written here.

WHY THE OBVIOUS CEILING IS THE WRONG ONE, AND IT IS WORTH SAYING FIRST BECAUSE
IT IS WHAT A READER WILL REACH FOR. `disposition.py` already carries a
vendor-price multiple, `AUCTION_BEATS_VENDOR_BY = 4`, and measured the house
pricing greens in the family's band at 2.2 to 2.9 times their vendor price.
That is sound for GEAR and useless here. Measured across this house:

    item                   vendor SellPrice   auction price per unit   ratio
    Rough Stone                        2            141 to 180         70x to 90x
    Peacebloom                        10            576 to 710         58x to 71x
    Ruined Leather Scraps              7                   321         46x

and realm-wide the same ratio spans four orders of magnitude - Wildvine
averages 3,881 times its vendor SellPrice while Greater Mystic Essence sits at
0.30 times its BuyPrice. A ceiling of "N times the vendor price" would refuse
every trade good on the house forever, and it would do it QUIETLY: the pass
would report "nothing affordable" every cycle and look exactly like a working
pass in an empty market.

The reason is that these prices are not organic. One character owns 100 percent
of the 2,247 live listings - the mod-ahbot seller - and its live config prices a
trade good off a FLOOR CONSTANT (`PriceMinimumCenterBase.TradeGood = 850`,
`UseItemSellPriceIfHigher = true`) rather than off the item's own value, which
is why a herb worth ten copper to a vendor lists near seven hundred. Vendor
price never enters the calculation for anything cheap.

SO THE CEILING IS ANCHORED ON THE ITEM'S OWN MARKET, AND THEN BOUNDED
ABSOLUTELY. Three layers, because no single one is trustworthy alone and the
cheap ones are what actually stop a catastrophe:

  1. CHEAPEST PER UNIT FIRST. `plan_buys` sorts every reachable listing for an
     item by its own per-unit price and takes them in that order. This is not
     an optimisation, it is most of the protection: an expensive listing is
     only ever reached once every cheaper one is taken.

  2. A MULTIPLE OF THE CHEAPEST LISTING (`OUTLIER_MULTIPLE`). The cheapest live
     listing IS the going rate, so a listing far above it is not a price but an
     outlier, and the answer to an outlier is to wait rather than to pay it.
     The multiple is chosen against a measured invariant rather than picked:
     the seller's own `BuyoutVariationReducePercent = 0.15` and
     `BuyoutVariationAddPercent = 0.25` cap any single item's spread at
     1.25 / 0.85 = 1.4706, and a survey of the thirty most-listed items on the
     house found every one of them between 1.31 and 1.47, never above. So two
     is comfortably clear of any legitimate listing of the same item while
     still refusing anything genuinely mispriced. It is scale-free, which is
     the point of a multiple of a live price rather than a number of copper:
     it behaves the same on a one-copper reagent and a fifty-gold one, and it
     does not go stale as the roster levels. `AUCTION_BEATS_VENDOR_BY` is
     deliberately NOT reused - it answers a different question, and borrowing a
     constant because the number looks right is how two unrelated decisions end
     up locked together.

  3. AN ABSOLUTE PER-CHARACTER, PER-PASS SPEND CAP (`SPEND_CAP_COPPER`). Layers
     1 and 2 are both derived FROM the market, so a market with one listing in
     it defeats both: the cheapest listing is also the only listing, the
     multiple is measured against itself, and any price passes. That is not
     theoretical - Rough Stone has exactly one reachable listing in the neutral
     house right now, so the one-listing case is the live case. This layer does
     not care what the market says, and it is what bounds the worst case to
     something a person watching the log can undo.

WHY THE CAP IS PER PASS AND NOT PER PURCHASE. A per-purchase cap bounds one
mistake and not a hundred of them, and this pass runs on a timer. Capping the
pass caps the cycle, and because every pass re-reads the world, a cap that is
too small is self-correcting - it just takes another ten minutes - while a cap
that is too large is not.

WHAT THE CEILING IS NOT PROTECTING AGAINST, SAID PLAINLY, because it is the
obvious worry with a plan built from a database read. A stale price is not a
risk here. An auction's buyout is fixed when it is listed and never changes,
and this module names a specific `auctionhouse.id`, so the price read is the
price charged. If the listing is bought by somebody else or expires between the
read and the row, `DoAuction` refuses it by name (`AuctionNotFound`) and
nothing is spent. The failure mode of a stale read is a wasted row, not an
overpayment.

------------------------------------------------------------------------------
AND THE PART THAT IS NOT BUILT HERE, SAID PLAINLY
------------------------------------------------------------------------------

A BOUGHT ITEM ARRIVES BY MAIL, NOT IN THE BAGS. The executor says so on its own
success path: `describe("bought", "", "the item arrives by mail
(AuctionHouseMgr::SendAuctionWonMail); the mailbox is not read here")`. There
is no bag-space check anywhere in `DoAuction` because nothing lands in a bag.

So this pass BUYS and does not FEED. `DriveCraft` reads the bags, and a reagent
in the mailbox is not in the bags. Collecting it needs a character standing at
a mailbox, and a mailbox on this world is a GAMEOBJECT: counted against the
live database, zero of 7,788 flagged creature templates carry
`UNIT_NPC_FLAG_MAILBOX`, so `travel_npc='innkeeper'` does not reach one and
mod-overseer's own creature-mailbox sweep is dead code here. That makes
collection a ground aim, a second counter and a second release - the shape
`_guild_bank_once` already has for the Guild Vault - and it is its own issue
rather than more of this one.

WHAT THAT MEANS FOR THIS PASS, WITHOUT DRESSING IT UP: until the collection
pass lands, this module puts reagents in the mailbox and the family still
cannot cast. That is a real limitation, it is why this does not close
infra#3696 or infra#3731, and it is why the spend cap above matters more than
it would if the goods went straight into a bag. The mail keeps them for thirty
days, so nothing is lost, but nothing is crafted either.

COUNTING WHAT IS ALREADY IN THE MAIL IS NOT A REFINEMENT, IT IS A CORRECTNESS
REQUIREMENT, AND IT IS THE WHOLE REASON THIS PASS IS SAFE TO SHIP AHEAD OF THE
COLLECTION ONE. `short_of` takes both what a character carries and what is
already in its mail. A purchase leaves the bags untouched, so a shortfall
computed from bags alone would still be the full shortfall next cycle, and the
pass would buy the same reagent again every ten minutes until the house was
empty or the purse was. The spend cap bounds how fast that happens; counting
the mail is what stops it happening at all.

AND "WHAT THIS CHARACTER HOLDS" IS READ THROUGH `character_inventory`, NEVER
THROUGH `item_instance.owner_guid`. That was measured rather than assumed: all
469 live mail attachments keep a fully populated `item_instance` row with
`owner_guid` set, and none of them has a `character_inventory` row, so an
owner-keyed count silently includes the mailbox. It over-counts on a second
ground too - three family items are owned but in neither the bags, the mail nor
the house, stale rows nobody can use - and on a third, rarer one: one letter in
flight still has `owner_guid` pointing at the SENDER, so an owner-keyed read
can attribute an item to the wrong character entirely. Ugga reads 54 items by
owner and 48 by inventory. The bags and the mail are therefore counted
SEPARATELY, by two queries that mean two different things, rather than by one
that quietly means both.
"""

from __future__ import annotations

from dataclasses import dataclass

import craft_rhythm
import travel

# The auctioneer role keyword, READ FROM travel.ROLES rather than spelled here
# - the same reasoning craft_supply.VENDOR_ROLE and trainjob.TRAINER_ROLE give
# for their own. A second spelling of a keyword is a second thing to get wrong,
# and a rename in travel.py becomes an ImportError at startup instead of an
# errand that resolves to nothing six hours later. It matters more here than
# usual: this exact string is also the one `bridge.ECONOMY_ERRANDS` carries and
# the one mod-overseer's `CounterRoleForAim` matches WHOLE, and infra#3712 is
# the standing issue about those copies having already drifted once.
AUCTIONEER_ROLE = next(role for role in travel.ROLES if role == "auctioneer")

# ---------------------------------------------------------------------------
# THE COMMAND GRAMMAR. Rendered rather than spelled at the call site, the same
# reasoning `guildbank.format_item_deposit` gives for its own: the parser on
# the other side is strict (one required key, no repeats, no other key
# accepted, decimal digits only) and a second spelling is a second thing to get
# wrong. tests/test_auction.py reads ParseAuctionRequest's own source text and
# asserts this rendering is what it accepts.

AUCTION_KIND = "auction"


def buy_command(auction_id: int) -> str:
    """The `buy auction:<id>` text `ParseAuctionRequest` accepts.

    Refuses a non-positive id rather than rendering one, the same way
    `travel.resolve` refuses creature entry 0: `ParseAuctionRequest` rejects a
    zero auction id by name, because the core reads a zero id as a malformed
    packet and returns silently, so writing one would be a row whose only
    possible answer is a refusal.
    """
    if not isinstance(auction_id, int) or auction_id <= 0:
        raise ValueError("auction id must be a positive integer")
    return f"buy auction:{auction_id}"


def list_command(item_guid: int, bid: int, buyout: int, hours: int = 12) -> str:
    """Render the pinned mod's safe auction-list request."""
    if not all(isinstance(value, int) for value in
               (item_guid, bid, buyout, hours)):
        raise ValueError("auction values must be integers")
    if item_guid <= 0 or bid <= 0 or buyout < bid or hours not in (12, 24, 48):
        raise ValueError("invalid auction listing")
    return (f"list guid:{item_guid} bid:{bid} buyout:{buyout} "
            f"hours:{hours}")


# ---------------------------------------------------------------------------
# THE HOUSES. Read from the realm's own AuctionHouse.dbc - see the module
# docstring for why the database cannot answer this (auctionhouse_dbc exists
# and holds zero rows) and for the two independent corroborations.

HOUSE_ALLIANCE = 2
HOUSE_HORDE = 6
HOUSE_NEUTRAL = 7

# Which house a character of each team shops in at an auctioneer of their OWN
# side. The neutral house is reached from a neutral auctioneer by either team,
# which is what `reachable_house` below encodes.
TEAM_HOUSE = {"alliance": HOUSE_ALLIANCE, "horde": HOUSE_HORDE}

# The races on each side, so a caller can name a team from `characters.race`
# without a second copy of this list. Verified against the live roster: the
# family is races 1, 3 and 7, all Alliance.
ALLIANCE_RACES = frozenset({1, 3, 4, 7, 11})
HORDE_RACES = frozenset({2, 5, 6, 8, 10})

# The factions an auctioneer carries when it serves the NEUTRAL house, read
# from every creature_template on this world with the auctioneer npcflag (42 of
# them) rather than from a guide. 474 Gadgetzan, 120 Booty Bay and 855 Everlook
# are the Steamwheedle goblin towns; 534 and 714 are the pair in Dalaran. The
# reaction that really decides this lives in FactionTemplate.dbc, which is not
# in the database - the same limit craft_supply.py already documents for vendor
# factions - so this is an enumeration of what is actually spawned, pinned by a
# test, and `DoAuction` remains the authority that can still refuse.
NEUTRAL_AUCTIONEER_FACTIONS = frozenset({120, 474, 534, 714, 855})


def team_of(race: int) -> str:
    """"alliance", "horde", or "" for a race this module does not know."""
    if int(race) in ALLIANCE_RACES:
        return "alliance"
    if int(race) in HORDE_RACES:
        return "horde"
    return ""


def reachable_house(team: str, auctioneer_faction: int) -> int:
    """Which `auctionhouse.houseid` a character of `team` shops in, standing at
    an auctioneer of `auctioneer_faction`. 0 when it cannot be said.

    ONE HOUSE, NOT A SET, because `DoAuction` shops in exactly one: it asks
    `GetAuctionsMap(auctioneer->GetFaction())` and any auction id outside that
    pool is refused `WrongHouse`. Returning a set would invite a caller to
    queue rows from two pools on one trip, and one of the two would always
    fail.

    AN UNKNOWN TEAM STILL REACHES THE NEUTRAL HOUSE, and that is correct
    rather than a hole: the goblin house is open to both sides, so which side
    the character is on does not enter into it. It is only the FACTION houses
    that need the team, and there an unknown one answers 0, which fails CLOSED
    - `usable` keeps no listing for house 0, so a character whose race this
    module cannot place buys nothing rather than buying from a pool it may not
    be able to reach.
    """
    if int(auctioneer_faction) in NEUTRAL_AUCTIONEER_FACTIONS:
        return HOUSE_NEUTRAL
    return TEAM_HOUSE.get(str(team or "").lower(), 0)


# ---------------------------------------------------------------------------
# WHAT EACH RECIPE CONSUMES THAT NOBODY SELLS - AND IT IS `craft_rhythm`'s
# TABLE, NOT A SECOND ONE.
#
# This module authored its own copy first and then deleted it, which is worth
# recording because the two were built independently from the same authority
# and agreed exactly - same entries, same labels, same per-cast counts for all
# five of the family's recipes. That is a good sign about both and a terrible
# reason to keep them both. `craft_rhythm.GATHERED` is broader (it covers every
# recipe in `craft.RECIPES`, not just the five currently assigned) and it is
# already load-bearing for the gather/craft alternation, so a second copy here
# would be a table that could drift from the one deciding when to gather - and
# these two passes must agree about what "short" means or they will fight.
#
# The reason a table exists at all, rather than a query: `acore_world.spell_dbc`
# is present and populated (4,492 rows with real Reagent_1..8 columns) but ZERO
# of those rows carry a reagent, and `spell_reagents`/`spell_template` do not
# exist. There is no query on this world that answers what a recipe consumes.
# The values come from the realm's own `Spell.dbc`, md5-verified against the
# running worldserver.
#
# WHAT THIS MODULE ADDS ON TOP, AND WHY IT IS NOT A SECOND TABLE. `GATHERED`
# answers "what does this recipe eat that a vendor will not sell", which is
# exactly the set worth buying at auction, so the filtering is already done:
# a recipe's vendor-bought half is deliberately absent from it (that is
# `craft_supply`'s business and is already bought on its own pass), which is
# why Minor Healing Potion's Empty Vial does not appear and must not. Two
# passes buying the same reagent would be two passes spending twice.
GATHERED = craft_rhythm.GATHERED


# ---------------------------------------------------------------------------
# THE CEILING. See the module docstring for the argument behind each number.

# How many times the cheapest live per-unit price a listing may cost before it
# is an outlier rather than a price. Two, against a seller whose own configured
# variation caps any one item's spread at 1.4706 and whose thirty most-listed
# items were measured between 1.31 and 1.47.
OUTLIER_MULTIPLE = 2

# The most one character may spend on this errand in one pass, in copper. Two
# gold against the 155 to 178 gold each of the five carries, so a completely
# defeated ceiling costs a little over one per cent of one purse in a cycle - a
# number a person reading the log can undo. It is deliberately far above what
# the errand actually costs (every reachable listing of every reagent in this
# table totals well under a gold today) so that the cap is a backstop and not a
# rationing rule: a cap that binds in ordinary use would be silently deciding
# how much crafting happens, which is not what it is for.
SPEND_CAP_COPPER = 20_000

# How many casts' worth of a reagent to buy in one trip. Larger than
# craft_supply's `CASTS_PER_TRIP` of 5, because these are the cheap gathered
# goods a skill grind eats continuously rather than a vial consumed once per
# potion, and stocking five casts of a recipe that needs seventy-five skill-ups
# is a trip taken fifteen times. Small enough to be one bag slot for anything
# that stacks to twenty - which all six of the reagents above do - and small
# enough that the pass running again in ten minutes is a perfectly good way to
# get the rest.
CASTS_PER_TRIP = 20


@dataclass(frozen=True)
class Listing:
    """One live auction, as this side reads it out of `auctionhouse`.

    `buyout` and `count` are the WHOLE STACK's buyout price in copper and the
    number of items in it, and `per_unit` derives the comparable number rather
    than storing a second copy. A stack of twenty at 2,820 copper and a single
    at 141 are the same price and must rank as the same price; a stored
    per-unit field would let a caller build one that disagreed with its own
    stack.

    NEITHER `entry` NOR `count` COMES FROM `auctionhouse`, and that is worth
    saying because the obvious query is wrong. That table has ten columns and
    holds neither: no `item_template` column, no `itemcount` column. The item
    entry is `item_instance.itemEntry` and the stack size is
    `item_instance.count`, joined through `auctionhouse.itemguid`, which is
    UNIQUE and one-to-one.
    """

    auction_id: int
    entry: int
    label: str = ""
    count: int = 1
    buyout: int = 0
    house: int = 0

    @property
    def per_unit(self) -> int:
        """Copper per item, rounded UP.

        Up rather than down so a ceiling is never passed by a rounding error: a
        stack whose true per-unit price is a fraction over the bar should be
        refused by it, not admitted by it.
        """
        count = max(1, int(self.count))
        return -(-int(self.buyout) // count)


@dataclass(frozen=True)
class Need:
    """One character's outstanding reagent, and how many are missing.

    `short` is the shortfall AFTER counting both the bags and the mail - see
    `short_of`, and the module docstring for why leaving the mail out is a
    runaway rather than an inaccuracy.
    """

    shopper: str
    entry: int
    label: str = ""
    short: int = 0


@dataclass(frozen=True)
class Buy:
    """One `kind='auction'` row, ready to insert.

    `spend` is what this row will actually cost, so a caller can total a pass
    without re-deriving it, and `why` is the sentence the log carries.
    """

    shopper: str
    auction_id: int
    entry: int
    label: str = ""
    count: int = 0
    spend: int = 0
    why: str = ""

    @property
    def command(self) -> str:
        return buy_command(self.auction_id)


@dataclass(frozen=True)
class SaleCandidate:
    """A carried item that may be listed after recipient claims are settled."""

    holder: str
    item_guid: int
    entry: int
    label: str = ""
    quality: int = 0
    binding: str = "boe"
    quest_item: bool = False
    recipient: str = ""
    sell_price: int = 0
    market_price: int = 0


@dataclass(frozen=True)
class Sale:
    """One safe auction listing decision."""

    candidate: SaleCandidate
    bid: int
    buyout: int
    hours: int = 12

    @property
    def command(self) -> str:
        return list_command(self.candidate.item_guid, self.bid,
                            self.buyout, self.hours)


def plan_sales(rows, *, max_items: int = 10, hours: int = 12) -> tuple:
    """List safe surplus BoEs, refusing rares and claimed upgrades.

    Recipient claims must already be decided by the gear/recipe planners. A
    non-empty ``recipient`` therefore blocks listing, as does soulbinding,
    quest status, an unknown market price, or rare-and-better quality.
    """
    if hours not in (12, 24, 48) or max_items <= 0:
        return ()
    out = []
    for row in rows or ():
        try:
            item = SaleCandidate(
                holder=str(row["holder"]).strip(),
                item_guid=int(row["item_guid"]), entry=int(row["entry"]),
                label=str(row.get("label", "")), quality=int(row["quality"]),
                binding=str(row.get("binding", "boe")).lower(),
                quest_item=bool(row.get("quest_item", False)),
                recipient=str(row.get("recipient", "")).strip(),
                sell_price=int(row.get("sell_price", 0)),
                market_price=int(row.get("market_price", 0)),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if (item.item_guid <= 0 or not item.holder or item.entry <= 0
                or item.quality >= 3 or item.binding == "soulbound"
                or item.quest_item or item.recipient
                or item.market_price <= 0):
            continue
        buyout = max(item.market_price, item.sell_price * 4, 1)
        bid = max(1, buyout * 80 // 100)
        out.append(Sale(item, bid, buyout, hours))
    return tuple(sorted(out, key=lambda sale: (sale.buyout,
                                                sale.candidate.item_guid))[:max_items])


def wanted(craft_spell: int, carried: dict, in_mail: dict,
           casts: int = CASTS_PER_TRIP) -> list:
    """Every gathered reagent this character's craft errand is short of.

    `carried` and `in_mail` are `{item entry: count}`, read by two separate
    queries that mean two different things - see the module docstring for why
    one `owner_guid` query that quietly means both is wrong.

    Returns a list so a recipe naming two gathered reagents (Minor Healing
    Potion needs Peacebloom AND Silverleaf) produces two needs rather than
    one, the same plural shape `craft_supply.craft_reagent_needs` returns and
    for the same reason: nothing says one house has both.
    """
    needs = []
    for reagent in GATHERED.get(int(craft_spell or 0), ()):
        short = short_of(reagent.per_cast,
                         (carried or {}).get(reagent.entry, 0),
                         (in_mail or {}).get(reagent.entry, 0), casts)
        if short > 0:
            needs.append(Need(shopper="", entry=reagent.entry,
                              label=reagent.label, short=short))
    return needs


def short_of(need_per_cast: int, carried: int, in_mail: int,
             casts: int = CASTS_PER_TRIP) -> int:
    """How many more of a reagent to buy, counting the mail as already bought.

    Returns 0 rather than a negative number when the character is stocked, so a
    caller can treat any positive answer as "buy this much".

    THE MAIL IS COUNTED AND THE BAGS ALONE ARE NOT ENOUGH. A purchase does not
    touch the bags, so a shortfall computed from `carried` alone does not fall
    when the pass succeeds, and the pass would re-buy the same reagent every
    cycle for as long as the house had one to sell. That is the single most
    expensive mistake available to this module, and it is arithmetic rather
    than policy, which is why it lives here where a test can hold it.
    """
    per_cast = max(1, int(need_per_cast or 1))
    target = per_cast * max(1, int(casts))
    held = max(0, int(carried or 0)) + max(0, int(in_mail or 0))
    return max(0, target - held)


def usable(listings, entry: int, house: int) -> list:
    """The listings that could actually be bought for `entry` at this house,
    cheapest per unit first.

    Drops, for stated reasons rather than silently:
      - a listing for a different item entry, which is a caller error;
      - a listing with no buyout, because a bid does not buy anything and
        `DoAuction` refuses one by name anyway;
      - an empty stack, which would make `per_unit` meaningless;
      - a listing in any other house, because `DoAuction` shops in exactly the
        one its auctioneer serves and refuses the rest as `WrongHouse`. A
        `house` of 0 keeps nothing, which is how an unknown team fails closed.

    Sorted by `(per_unit, auction_id)` rather than by price alone, so two
    listings at an identical price never make the answer depend on the row
    order MySQL happened to return - the same tie-break `craft_supply._usable`
    applies to its own shortlist, for the same reason.
    """
    wanted_entry = int(entry)
    pool = int(house)
    keep = [
        listing for listing in (listings or ())
        if int(listing.entry) == wanted_entry
        and int(listing.buyout) > 0
        and int(listing.count) > 0
        and pool > 0
        and int(listing.house) == pool
    ]
    return sorted(keep, key=lambda item: (item.per_unit, int(item.auction_id)))


def ceiling_for(listings, multiple: int = OUTLIER_MULTIPLE) -> int:
    """The most this pass will pay per unit, given what is on the house.

    `listings` must already be `usable` output for ONE item. Returns 0 for an
    empty market, which no listing can pass, so an unreadable or empty read
    buys nothing rather than buying anything.

    THE ANCHOR IS THE CHEAPEST LISTING AND NOT THE MEDIAN, which is the choice
    worth defending. A median is the better description of a market and the
    worse basis for a ceiling: half the listings sit above it by construction,
    so a median-anchored ceiling routinely admits prices the cheapest-first
    rule was never going to reach anyway, and on a thin market of two listings
    the median is just the expensive one. The cheapest listing is the price
    actually available, and this pass is buying, not appraising.
    """
    prices = [listing.per_unit for listing in (listings or ())]
    if not prices:
        return 0
    return min(prices) * max(1, int(multiple))


@dataclass(frozen=True)
class _Attempt:
    """What one need's walk down its own market produced.

    A record rather than a tuple of six because every field is a number and a
    positional return of six numbers is a bug waiting for somebody to reorder
    it. `refused_price` and `refused_budget` are kept APART rather than summed:
    "everything on the house is priced like an outlier" and "this character
    cannot afford what is there" are different situations with different
    answers - one waits for a restock, the other waits for the purse - and a
    single count of refusals cannot tell a reader which happened.
    """

    buys: tuple = ()
    bought: int = 0
    spend: int = 0
    refused_price: int = 0
    refused_budget: int = 0
    slots_left: int = 0
    out_of_slots: bool = False


def _take_cheapest(need: "Need", market, bar: int, budget: int, slots,
                   taken: set) -> "_Attempt":
    """Take listings for one need, cheapest first, until it is met or refused.

    LIFTED OUT OF `plan_buys` rather than left inline, and the reason is the
    one infra#3717 already recorded for `_settle_vendor_errand`: the
    complexity number is the same fact as "one question with one answer belongs
    in one place", stated as a measurement. This is the question "given a
    market, a ceiling and a budget, what does this one character take", and it
    is entirely separable from "which needs are there and what do their
    refusals read like".

    `taken` IS MUTATED AND THAT IS DELIBERATE. It is the set of auction ids
    already claimed this pass, shared across every need and every shopper,
    because one auction is one stack: two characters short of the same reagent
    must not both be queued against the same id, since the second row could
    only ever come back `AuctionNotFound`.

    `slots` IS None WHEN THE CALLER IS NOT COUNTING BAG SLOTS, which the pure
    tests use when the question they are asking is not about bags. Otherwise it
    is the number of free slots left, and it is returned rather than mutated so
    the caller owns the bookkeeping.
    """
    buys: list = []
    bought = 0
    spend = 0
    refused_price = 0
    refused_budget = 0
    left = 0 if slots is None else int(slots)
    out_of_slots = False
    wanted_units = int(need.short)
    label = need.label or ("item %d" % int(need.entry))

    for listing in market:
        if wanted_units <= 0:
            break
        if int(listing.auction_id) in taken:
            continue
        if listing.per_unit > bar:
            refused_price += 1
            continue
        price = int(listing.buyout)
        if price > budget - spend:
            refused_budget += 1
            continue
        if slots is not None and left <= 0:
            # ONE FREE SLOT PER PURCHASE, checked even though `DoAuction` never
            # looks at the bags. The item arrives by mail, so the slot is
            # needed at COLLECTION time - `DoMail`'s take-item refuses with "no
            # room in the bags" - and buying into a character with nowhere to
            # put it just moves the failure somewhere harder to read.
            out_of_slots = True
            break
        if slots is not None:
            left -= 1
        taken.add(int(listing.auction_id))
        spend += price
        wanted_units -= int(listing.count)
        bought += int(listing.count)
        buys.append(
            Buy(
                shopper=need.shopper,
                auction_id=int(listing.auction_id),
                entry=int(need.entry),
                label=label,
                count=int(listing.count),
                spend=price,
                why=(
                    "%s is short %d %s; this stack of %d costs %d copper (%d "
                    "each, against a ceiling of %d and %d left to spend)"
                    % (need.shopper, int(need.short), label, int(listing.count),
                       price, listing.per_unit, bar, budget - spend)
                ),
            )
        )

    return _Attempt(
        buys=tuple(buys), bought=bought, spend=spend,
        refused_price=refused_price, refused_budget=refused_budget,
        slots_left=left, out_of_slots=out_of_slots,
    )


def plan_buys(needs, listings, house: int, purses, free_slots=None,
              cap: int = SPEND_CAP_COPPER) -> tuple:
    """Every auction worth buying this pass, and a sentence for each refusal.

    `needs` is one `Need` per (character, reagent) shortfall, `listings` is
    every live `Listing` read off the house, `house` is the pool the shoppers
    are standing in (see `reachable_house`), `purses` is `{name: copper}` and
    `free_slots` is `{name: slots}`. Returns `(buys, notes)` - the same
    two-outcome shape `craft_supply.craft_reagent_errands` returns, so a caller
    logs a refusal exactly like every other town refusal.

    THE SPEND CAP IS PER CHARACTER AND ACCUMULATES ACROSS THEIR OWN NEEDS, not
    across the family: one character's expensive reagent must not ration
    another's cheap one, and the purses are separate anyway. Within one
    character the running total is real, so a second reagent sees what the
    first already committed.

    A NEED THAT CANNOT BE MET IS NOT A REFUSAL OF THE PASS. Each one produces
    its own note and the loop carries on, the same way `craft_reagent_errands`
    handles a recipe whose second reagent is unavailable: one unbuyable reagent
    must not stop the other four characters being supplied. That is not a
    theoretical case here - Bork's Ruined Leather Scraps has one listing on the
    realm and it is in a house he can never reach.
    """
    buys: list = []
    notes: list = []
    spent: dict = {}
    taken: set = set()
    slots_left = dict(free_slots or {})

    for need in sorted(needs or (), key=lambda n: (str(n.shopper), int(n.entry))):
        if int(need.short) <= 0:
            continue
        shopper = str(need.shopper)
        label = need.label or ("item %d" % int(need.entry))
        market = usable(listings, int(need.entry), house)
        if not market:
            notes.append(
                "nothing in auction house %d sells %s (%d) with a buyout, so "
                "%s cannot be supplied from where the family is standing"
                % (int(house), label, int(need.entry), shopper)
            )
            continue

        bar = ceiling_for(market)
        purse = int((purses or {}).get(shopper, 0) or 0)
        allowance = min(int(cap), purse)
        took = _take_cheapest(
            need, market, bar,
            budget=allowance - spent.get(shopper, 0),
            slots=None if free_slots is None else int(slots_left.get(shopper, 0)),
            taken=taken,
        )

        buys.extend(took.buys)
        spent[shopper] = spent.get(shopper, 0) + took.spend
        if free_slots is not None:
            slots_left[shopper] = took.slots_left

        if took.out_of_slots:
            notes.append(
                "%s has no free bag slot for %s, so it is not bought - a "
                "bought stack has to land somewhere when the mail is collected"
                % (shopper, label)
            )
        if took.bought == 0:
            notes.append(
                "%s needs %d %s and none of the %d reachable listing(s) could "
                "be taken (%d priced above the %d copper per-unit ceiling, %d "
                "beyond the %d copper this pass may spend)"
                % (shopper, int(need.short), label, len(market),
                   took.refused_price, bar, took.refused_budget, allowance)
            )
        elif took.bought < int(need.short):
            notes.append(
                "%s bought %d of the %d %s it needs; the rest is priced above "
                "the ceiling, beyond this pass's allowance, or simply not "
                "listed yet" % (shopper, took.bought, int(need.short), label)
            )

    return buys, notes
