"""What a person actually does with a bag full of adventuring, item by item.

Nobody sells everything. A person picks up a green, looks at it, and routes it:
wear it, hand it to somebody it suits better, put it in the post to the auction
house, break it down for dust, or walk it to a vendor. Which of those are even
AVAILABLE is decided by facts about the item and about the family, and getting
that gate wrong is how a bot vendors a rare or lists a soulbound item forever.

THE ONE RULE THAT DECIDES THE OPTION SET IS BINDING.

    Soulbound  -> vendor or disenchant. It cannot be auctioned or traded, ever,
                  and a plan that tries has simply not read the item.
    Bind on equip -> auction, disenchant, vendor, or hand to a sibling. All four
                  are open, so this is where judgement is actually needed.

MEASURED ON THE DEV FAMILY, 2026-09-04, and the measurements are why several
branches below refuse rather than act:

    Grug  Mining 3/75, Blacksmithing 1/75
    Ugga  Herbalism 119/150, Alchemy 1/75
    Og    Enchanting 1/75, Tailoring 1/75
    Grog  Inscription 1/75
    Bork  Skinning 2/75, Leatherworking 1/75

Og is the family enchanter at skill ONE. Disenchanting is therefore not a real
route for this family yet, however attractive it looks in a design document,
and the honest thing for the rule to do is say so per item rather than emit
disenchant orders that fail in the world. Og is also the tailor at skill one,
which is worth holding in mind next to the seventy-nine Linen Cloth the family
is carrying for him.

WHAT THIS MODULE REFUSES TO INVENT. It does not carry a table of disenchant
skill thresholds by item level, because that is game data this repository can
read from the core and I would be guessing at it. The caller supplies
`disenchant_skill_required`, and `None` means unknown, which means refuse. Same
for auction value: an unknown price is not a reason to gamble, it is a reason to
take the vendor price that is known.

FAIL CLOSED, EVERYWHERE. The defect this module is written against is a sale
rule whose safety flags defaulted to False, so an item nobody had classified was
approved for sale. Every unknown here resolves to KEEP. Keeping a vendor trinket
costs one slot; selling a quest item or a sibling's upgrade costs the run.

A TRADE TOOL IS NOT LOOT AND HAS NO LEVEL TO OUTGROW (infra#3709). A Mining
Pick is not a weapon somebody is growing out of, and 25 Empty Vials are not
trinkets; they are what a profession runs on, and selling them back to the
vendor that sold them is a lap the family pays for and never leaves. The long
note above PROFESSION_BAGS is where that whole rule and its measurements live,
and `profession_keeps` is the half of it the junk-sale path reads.

PURE MODULE: no MySQL, no core, no auction house, no browser.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The routes an item can take. KEEP is the safe default and the refusal answer.
KEEP = "keep"
VENDOR = "vendor"
AUCTION = "auction"
DISENCHANT = "disenchant"
GIVE = "give"
# The bank is the answer to "I will want this, just not for twenty levels".
# It is not a disposal: nothing is lost, it simply stops costing a bag slot.
# Measured 2026-09-04, every member had elsewhere=0, so the family has never
# banked anything at all while carrying seventy-nine Linen Cloth for a tailor
# at skill one. That is precisely the pile a person walks to a bank.
BANK = "bank"

# Every route this module can name. The default for `available`, so a caller
# that only wants the theoretical answer still gets it.
ALL_ROUTES = frozenset({KEEP, VENDOR, AUCTION, DISENCHANT, GIVE, BANK})

# The routes that can actually happen, re-measured 2026-09-08 (infra#3449).
#
# REACHABILITY AND EXECUTABILITY ARE DIFFERENT FACTS, and conflating them is
# why this module has never been safe to wire. `Family.auction_reachable` asks
# whether this character could walk to an auctioneer today; `available` asks
# whether anything in this system can carry the verdict out at all. A route
# needs BOTH, and only the second is a fact about the deployment.
#
# WHAT CHANGED SINCE THE 2026-09-05 NOTE THIS REPLACES, all of it verified
# against the checked-out module and the live realm rather than remembered:
#
#   VENDOR      ships, and has written 13,919 rows.
#   GIVE        ships, and has written 137 rows.
#   BANK        NOW HAS A WRITER. The old note here said it did not; it was
#               right when written and has been wrong since bridge._bank_once
#               landed, and the realm holds 42 kind='bank' rows. BANK stays
#               out of this set anyway, because bank.py reaches its own
#               verdicts against ALL_ROUTES and does not read this one.
#               THE GUILD BANK IS A DIFFERENT PLACE AND IS NOT REACHABLE,
#               which matters because the shared pile is what an owner
#               actually asks for - a personal bank is private, so nothing in
#               it can be claimed by a sibling or disenchanted by Og. The
#               mechanism is complete on both sides: `guildbank
#               .format_item_deposit` renders `bank deposit-item guid:<n>`
#               byte-identically to what GuildVerb::BankDepositItem parses,
#               and DoGuild calls Guild::SwapItemsWithInventory against tab
#               GUILD_BANK_DEPOSIT_TAB_V1 = 0. What is missing is the tab
#               itself: measured 2026-09-13, all 21 guilds on this realm have
#               ZERO rows in `guild_bank_tab` and BankMoney 0, the family's
#               own guild ("Cave", guildid 23) included. SwapItemsWithInventory
#               is void and silently no-ops when the tab is not purchased, so
#               every deposit would come back on DoGuild's own witness check
#               as "the core did not move the item". That is infra#3713, it is
#               somebody else's change tonight, and until it lands a deposit
#               policy here would write rows that cannot land.
#   AUCTION     the executor is NOT a draft. mod-overseer#208 merged as
#               DoAuction (mod_overseer.cpp:24389): it builds a real
#               CMSG_AUCTION_SELL_ITEM, calls HandleAuctionSellItem, and
#               refuses to report success unless it can read the listing back
#               out of the house. It stays out of this set for two other
#               reasons, both facts about THIS process: nothing here writes a
#               kind='auction' row, and ECONOMY_ERRANDS is ("vendor",
#               "banker", "repair", "guild banker") - re-read 2026-09-13, the
#               fourth keyword landed with infra#3704 and this comment used to
#               name only three - so STILL no pass can put a character within
#               the INTERACTION_DISTANCE of an auctioneer that DoAuction's
#               FindAuctioneerInReach requires. AuctionVerb::List also wants a
#               `bid:` and a `buyout:` in copper and refuses below the deposit
#               it charges, and this module's own rule is that an unknown
#               price is a reason to take the sure thing rather than gamble -
#               so listing needs a price source as well as a travel keyword.
#   MAIL        same shape: mod-overseer#219 merged as DoMail, no writer here,
#               and nothing in this repository knows where a mailbox is.
#   DISENCHANT  NO MECHANISM AT ALL, which is a different and worse answer
#               than the "shipped but uncalled" pattern every other route
#               here has. Re-verified 2026-09-13 against the deployed
#               submodule at production/docker/azerothcore-playerbots/
#               mod-overseer: `grep -ri disenchant` over all 149 source files
#               returns ZERO hits - no verb, no handler, no parser, no doc.
#               `overseer_command.kind` is an ENUM of 20 values (this comment
#               said 18 and was written before `cast` and `guild` landed; the
#               live list is in 2026_09_11_00_overseer_guild.sql:149) and
#               'disenchant' is in none of them, so such a row cannot even be
#               inserted. NO PYTHON CALLER CAN FIX THIS ONE - it needs the C++
#               verb, the loot-window resolve and the ENUM migration that
#               quadseven/mod-overseer#444 (DriveDisenchant) already scopes,
#               and that issue also reserves the disenchant-vs-vendor rule for
#               THIS file once there are measured numbers to pick it with. So
#               the honest thing here is to keep computing the verdict and
#               keep it out of EXECUTABLE_TODAY, not to build a planner for a
#               verb that does not exist. Og, the family enchanter, is skill
#               1 of 75, which would cover 38 of the 155 carried greens.
#
# Turning a route on is adding its name here, which is the point of a set
# rather than five more booleans on Family.
EXECUTABLE_TODAY = frozenset({KEEP, VENDOR, GIVE})


# WHAT THE FAMILY-FIT GATE ANSWERED ABOUT ONE ITEM (infra#3449).
#
# `decide` used to hold every tradable green forever, on the stated grounds
# that it might be somebody's upgrade and that vendoring it "would throw away
# the difference". Both halves of that were honest while unmeasured, and both
# have now been measured, which is what makes it safe to let one go:
#
#   THE FIRST HALF IS ANSWERED. gear.claimant asks the holder and all four
#   siblings whether they would wear it. UNASKED is still the default and
#   still keeps everything, so nothing changes for a caller that has not put
#   the question.
#
#   THE SECOND HALF IS SMALLER THAN IT LOOKED. On this realm, on 2026-09-08,
#   the auction house's own listings price a green weapon or armour piece in
#   the family's item-level band (20-40) at 2.2 to 2.9 times its vendor
#   price - BELOW the AUCTION_BEATS_VENDOR_BY multiple this module already
#   picked as the bar for a listing worth its deposit and its wait. The whole
#   pile of gear nobody will wear is worth 0.77 gold against the 800 gold the
#   five already carry, while two of the five sit at 100% of their bag slots.
#   The difference being thrown away is real and it is a rounding error; the
#   bag slot is the thing actually at stake.
FIT_UNASKED = "unasked"    # nobody put the question. Keeps, as before.
FIT_HOLDER = "holder"      # the one carrying it would wear it. Keeps.
FIT_SIBLING = "sibling"    # somebody else would wear it. Hands it over.
FIT_NOBODY = "nobody"      # asked, and the answer was no. Disposal is open.
FIT_UNJUDGEABLE = "?"      # the gate ran and could not tell. Keeps.


# ---------------------------------------------------------------------------
# A RECIPE HAS A CLAIMANT TOO, AND IT IS NOT THE ONE `gear.claimant` ANSWERS
# ABOUT (infra#3731, and the owner's own words: "if others want it they can
# claim it").
#
# `gear.claimant` asks who would WEAR a thing, by slot and item level. That is
# the right question for a green and a meaningless one for a Pattern: a recipe
# goes in no slot, so `gear.claimant` refuses it as UNJUDGEABLE (gear.py:632,
# `item_class not in (WEAPON, ARMOR)`) and `decide` keeps it forever. The
# mirror question - who could LEARN this - has an exact answer in the item's
# own `RequiredSkill`, and nothing in this repository was asking it.
#
# MEASURED ON THE LIVE REALM, 2026-09-13, reading character_inventory joined to
# item_template rather than a wiki. The family carries 15 class-9 recipes and
# THIRTEEN OF THEM ARE IN THE WRONG BAG:
#
#     Grog  Pattern: Heavy Woolen Cloak      RequiredSkill 197 tailoring    -> Og
#     Grog  Plans: Frost Tiger Blade         164 blacksmithing              -> Grug
#     Grog  Recipe: Elixir of Giant Growth   171 alchemy                    -> Ugga
#     Grog  Schematic: EZ-Thro Dynamite      202 engineering                -> Grog
#     Grug  Pattern: White Leather Jerkin    165 leatherworking             -> Bork
#     Grug  Recipe: Elixir of Minor Agility  171 alchemy                    -> Ugga
#     Og    Pattern: Dark Leather Tunic      165 leatherworking             -> Bork
#     Og    Plans: Copper Chain Vest         164 blacksmithing              -> Grug
#     Og    Plans: Green Iron Boots          164 blacksmithing              -> Grug
#     Og    Plans: Silvered Bronze Breastpl. 164 blacksmithing              -> Grug
#     Ugga  Pattern: Gray Woolen Robe        197 tailoring                  -> Og
#     Ugga  Pattern: Hands of Darkness       197 tailoring                  -> Og
#     Grug/Og  Manual: Strong Anti-Venom x3  129 first aid                  -> anyone
#
# EVERY ONE IS FREELY TRADABLE: `item_template.bonding = 0` and
# `item_instance.flags & 1 = 0` on all fifteen, checked per copy rather than
# per template, because a bind-on-equip green somebody wore once is bound
# while its template still says otherwise (see bag_pressure.item_binding).
# So the hand-off this opens needs no new verb at all - GIVE has shipped since
# infra#2597 and has written 137 rows.
#
# AND NOTHING WAS EVER GOING TO REACH THEM. Both halves of the economy pass
# skip a recipe for a different reason, which is why this sat invisible:
# `_SURPLUS_GEAR_SQL` selects `it.class IN (2, 4)`, so `decide` was never asked;
# `sellable` requires `quality <= 1` and every recipe above is Quality 2, so the
# junk half refused them too. They are not mis-routed, they are UNROUTED - the
# literal "so much crap in their bags" the owner is looking at.
#
# THE SKILL RANK IS DELIBERATELY NOT CHECKED HERE. Grug is Blacksmithing 1 and
# Plans: Green Iron Boots wants 145, so he cannot learn it today - and handing
# it to him anyway is still right, because he is the only character who will
# EVER be able to. The alternative is holding it in Og's bag until Grug reaches
# 145, which is the bag slot the owner is complaining about, spent on an item
# that can only become more useful where it is going. `character_spell` never
# receives runtime-granted spells (measured today), so "has he already learned
# it" is a question this deployment cannot answer at all; the assigned trade is
# the fact that can be read, and it is the one used.
LEARNER_UNASKED = "unasked"   # nobody put the question. Keeps, as before.
LEARNER_HOLDER = "holder"     # the trade is the holder's own. Keeps.
LEARNER_NOBODY = "nobody"     # no member is assigned the trade. Keeps or banks.
# Anything else is a NAME: the family member whose assigned trade this teaches.

# `item_template.class` 9 is RECIPE - every Pattern, Plans, Recipe, Schematic,
# Manual and Formula. Read off acore_world.item_template on 2026-09-13 by
# sampling what the family actually carries, the same way PROFESSION_BAGS
# above was derived, and not from a wiki.
RECIPE_CLASS = 9

# Binding, which decides which routes exist at all.
BIND_NONE = "none"          # freely tradable and auctionable
BIND_ON_EQUIP = "boe"       # auctionable until somebody wears it
BIND_ON_PICKUP = "soulbound"  # vendor or dust, nothing else

# How much better an auction has to be than the vendor price before it is worth
# the walk to a mailbox and the wait for a buyer. A green that beats the vendor
# by a few copper is not worth a listing slot; one worth several times the
# vendor price is. This is a judgement, not a game constant, which is why it is
# named and overridable rather than buried in an expression.
AUCTION_BEATS_VENDOR_BY = 4

# How much of one reagent the family keeps before the rest is surplus. One
# number, named once: `Family.reagent_keep` below and `profession_keeps` are
# the same judgement about the same pile, and two spellings of it could only
# ever disagree.
REAGENT_KEEP = 40


# ---------------------------------------------------------------------------
# TRADE STOCK IS NOT ADVENTURING LOOT (infra#3709)
#
# WHAT THE FAMILY WAS DOING. Measured on the live realm 2026-09-13: Grug sold
# a Mining Pick and a Blacksmith Hammer eight times over eighteen hours, eight
# DISTINCT `item_instance.guid` each, so every one was a fresh copy bought and
# re-sold rather than a refused row re-queued. Ugga bought 25 Empty Vials for
# 100 copper and sold them back for 25 copper ten minutes later, four laps in
# under half an hour. Bork sold his Skinning Knife four times. Every one of
# those is the tool or the stock that profession cannot work without, which is
# why three of the five made no profession progress at all.
#
# WHY NOTHING STOPPED IT. All four are Quality 1, and the only profession
# protection on the junk path was `materials.REAGENTS` - six material NAMES,
# none of them a tool. Quality 1 is also below the `Quality >= 2` floor of the
# gear query, so `decide` was never even asked about them; see the note on
# `trade_tool` for the half of this that is about the gear path.
#
# WHY `BagFamily` AND NOT A LIST OF ITEM IDS. The world already sorts every
# trade good into a profession's bag, and that is a fact about the item rather
# than a fact somebody remembered - the same reason towntrip.py counts food by
# `spellcategory_1` instead of by name. A list of the four ids above would be
# tomorrow's identical bug with different numbers the moment the family gains a
# recipe. Every bit below was read off acore_world.item_template on 2026-09-13
# by sampling what actually carries it, not from a wiki:
#
#     8     leatherworking   Light Hide, Light Armor Kit, Medium Armor Kit
#     16    inscription      Scroll of Strength, Ace of Beasts
#     32    herbalism        Silverleaf, Mageroyal, Adder's Tongue
#     64    enchanting       Copper Rod, Runed Copper Rod, Abyss Crystal
#     128   engineering      Flask of Oil, Rough Blasting Powder, Rough Dynamite
#     512   jewelcrafting    Malachite, Tigerseye, Moss Agate
#     1024  mining           Adamantite Bar, Tunnel Pick, Gouging Pick
#
# DELIBERATELY ABSENT: 1 and 2 (arrows and bullets), 4 (soul shards), 256
# (the keyring), 2048 (soulbound equipment), 4096 (vanity pets), 8192
# (currency tokens), 16384 (quest items). None of those is a trade's stock and
# treating them as one would quietly pin a thousand arrows in a bag for ever.
#
# AND WHY THE BAG IS A BACKSTOP AND NEVER THE PROFESSION ANSWER. Empty Vial
# (3371) carries bit 16, which is INSCRIPTION - the one primary, with
# jewelcrafting, that `professions.UNASSIGNED` says nobody in this family
# works. Reading the bit as the item's trade would therefore sell Ugga's vials,
# which is the exact bug this section exists to fix. The craft tables are the
# authoritative claim (`craft_supply` buys 3371 for Alchemy recipes that
# `craft.RECIPES` names, and Ugga is the assigned alchemist); the bag is what
# answers for everything those tables have not reached yet. `profession_keeps`
# consults them in that order for that reason.
#
# BLACKSMITHING, TAILORING, ALCHEMY, COOKING AND FIRST AID HAVE NO BAG OF
# THEIR OWN in 3.3.5, and skinning shares leatherworking's - which is the
# other half of why the craft tables must come first. Bork happens to hold
# both skinning and leatherworking so his knife is covered either way; a
# family with a bare skinner would need the tables to say so.
PROFESSION_BAGS = {
    "leatherworking": 8,
    "inscription": 16,
    "herbalism": 32,
    "enchanting": 64,
    "engineering": 128,
    "jewelcrafting": 512,
    "mining": 1024,
}

# Any profession's bag at all, for the question that does not care which.
ANY_PROFESSION_BAG = 0
for _bit in PROFESSION_BAGS.values():
    ANY_PROFESSION_BAG |= _bit
del _bit

# `item_template.class` 2 is WEAPON, and a trade tool is always one: a Mining
# Pick, a Blacksmith Hammer, a Skinning Knife and an Arclight Spanner are all
# class 2 with a profession bag, and on this world image those are the ONLY
# class-2 items carrying one besides the picks and skinners that double as real
# weapons - which are tools too, and keeping them is right.
#
# ARMOUR IS EXCLUDED ON PURPOSE, and it is not a detail: 105 of the class-4
# rows carry bit 128, because every engineering goggle is bagged as engineering
# supplies. Those are worn, they are outgrown like any other helm, and calling
# them tools would pin a head slot's worth of obsolete goggles in a bag for
# ever - a bag-pressure regression handed out by the rule meant to protect
# professions.
TOOL_CLASS = 2


@dataclass(frozen=True)
class Item:
    """One stack, described by what the caller could actually determine.

    Every field that could make this item dangerous to part with defaults to
    the DANGEROUS answer, so an item nobody classified is kept rather than
    sold. `known` is the master switch: an item the caller could not look up at
    all must not be routed anywhere.
    """
    name: str
    quality: int = 0
    known: bool = False
    binding: str = BIND_ON_PICKUP
    quest_item: bool = True
    equipment: bool = False          # armour or a weapon, so disenchantable
    required_level: int = 0
    sell_price: int = 0
    auction_value: int | None = None
    reagent_for: str | None = None   # the profession that uses it, if any
    disenchant_skill_required: int | None = None
    # The two `item_template` columns the trade-tool gate reads. Both default
    # to 0, which is "not a tool", so a caller that has not looked them up
    # gets exactly the behaviour this module had before the gate existed -
    # and 0 is also what the world itself writes for ordinary loot.
    item_class: int = 0
    bag_family: int = 0
    # `item_template.RequiredSkill`, the skill line a recipe teaches into. 0 is
    # "no skill gate", which every ordinary green and every vendor trinket
    # carries, so a caller that has not looked it up gets exactly the behaviour
    # this module had before the recipe gate existed.
    required_skill: int = 0


@dataclass(frozen=True)
class Family:
    """What the family can actually do today, not what it could in principle."""
    enchanting_skill: int = 0
    # profession -> the skill somebody in the family actually has
    professions: dict = field(default_factory=dict)
    # How much of a reagent the family keeps before the rest is surplus.
    reagent_keep: int = REAGENT_KEEP
    vendor_reachable: bool = False
    auction_reachable: bool = False
    # A guild bank would be the shared version of this and does not exist:
    # there is no guild, and while travel to a petitioner and to a guild
    # banker both work, buying a charter, collecting signatures, registering
    # and depositing are all unwritten. So this means the PERSONAL bank.
    bank_reachable: bool = False


@dataclass(frozen=True)
class Verdict:
    route: str
    why: str


def _is_tool(item_class: int, bag_family: int) -> bool:
    """The trade-tool test over the two raw columns, spelled ONCE.

    `decide` reads it off an `Item` and `profession_keeps` reads it off a
    world row, and those two paths sell the same pick out of the same bag.
    A second spelling of this predicate is a second answer that can disagree,
    which is the failure this module already refuses everywhere else.
    """
    return bool(item_class == TOOL_CLASS and bag_family & ANY_PROFESSION_BAG)


def trade_tool(item) -> bool:
    """Is this a profession's TOOL rather than a weapon (infra#3709)?

    A weapon the world sorts into a profession's bag is not a weapon: nobody
    swings a Mining Pick, and nobody equips a Blacksmith Hammer for its two
    damage. See the PROFESSION_BAGS block above for where every bit came from
    and why armour is excluded.
    """
    return _is_tool(item.item_class, item.bag_family)


def recipe(item) -> bool:
    """Is this a recipe that teaches into a named skill line?

    BOTH HALVES ARE REQUIRED. Class 9 alone is not enough: a handful of class-9
    rows on this world image carry `RequiredSkill = 0`, which means the item
    gates on nothing and so names no claimant. Those are left to every other
    rule in this module exactly as they were, because "a recipe for nobody in
    particular" is not a hand-off, it is ordinary goods.
    """
    return bool(int(item.item_class) == RECIPE_CLASS
                and int(item.required_skill) > 0)


def outgrown(item, character_level, margin=10):
    """Is this the "old green" a person would clear out?

    Old means the character has moved far enough past it that it will never be
    worn again. The margin exists because an item a level or two behind is
    still a candidate for an alt or a sibling, and clearing those out is how a
    family throws away the upgrade it was about to hand somebody.

    A TRADE TOOL IS NEVER OUTGROWN, AT ANY LEVEL, and the bug that prompted
    saying so is the whole of infra#3709. `RequiredLevel 1` on a Mining Pick
    is not a claim that it stops being useful at 11; it is the world saying
    the item has no level gate worth writing down. Levelling retires a green
    breastplate because a better breastplate exists; nothing whatsoever
    replaces the pick, and the character who sells it simply stops mining.
    """
    if trade_tool(item):
        return False
    if not item.equipment or item.required_level <= 0:
        return False
    return item.required_level + margin <= character_level


def _can_disenchant(item, family):
    """Only real equipment, only uncommon or better, only with the skill.

    The skill threshold is the caller's to supply from the core. Unknown means
    no: emitting a disenchant the world will refuse just burns a turn and looks
    like the bot is stuck.
    """
    if not item.equipment or item.quality < 2:
        return False
    needed = item.disenchant_skill_required
    if needed is None:
        return False
    return family.enchanting_skill >= needed


def _auction_is_worth_it(item, family, multiple=AUCTION_BEATS_VENDOR_BY,
                         available=ALL_ROUTES):
    """Worth a listing slot and the wait, and legal to list at all."""
    if AUCTION not in available:
        return False          # no executor: a listing verdict would sit forever
    if not family.auction_reachable:
        return False
    if item.binding == BIND_ON_PICKUP:
        return False          # the whole point: soulbound cannot be listed
    if item.auction_value is None:
        return False          # unknown price is a reason to take the sure thing
    return item.auction_value >= max(1, item.sell_price) * multiple


def decide(item, family, character_level=1, upgrade_for_sibling=False,
           reagent_held=0, available=ALL_ROUTES, family_fit=FIT_UNASKED,
           learner=LEARNER_UNASKED):
    """One item, one route, with the reason attached.

    Order matters and is the argument: every refusal is checked before every
    disposal, so a bug in the disposal ranking can waste value but cannot
    destroy something irreplaceable.

    `available` is the set of routes this system can actually carry out, and
    it is an argument rather than a constant so that it is testable and so
    that turning on the auction executor is a one-line change at the caller.
    It defaults to every route, which is the theoretical answer; a caller
    writing rows into the world is expected to pass EXECUTABLE_TODAY. A route
    that is not available is not an error, it simply is not offered, and the
    item falls through to the next honest option and finally to KEEP.

    `family_fit` is what gear.claimant answered about this item, and it
    defaults to FIT_UNASKED so that a caller who never asked gets exactly the
    behaviour this module had before the gate existed. Only FIT_NOBODY - the
    gate ran, and neither the holder nor any sibling would wear it - opens
    anything up. FIT_HOLDER and FIT_UNJUDGEABLE both KEEP, and they are
    checked before every disposal for the usual reason: a wrong KEEP costs a
    bag slot and a wrong sale costs the item.

    FIT_NOBODY ALSO RETIRES THE `outgrown` LEVEL MARGIN, but only for a piece
    the holder has already reached the required level of. The margin is a
    proxy for the question the gate answers directly, and the branch below
    says why in full.

    `learner` is the recipe half of the same idea and defaults to
    LEARNER_UNASKED for the same reason: a caller who never asked gets exactly
    the behaviour this module had before the gate existed. It is the answer to
    "who in this family could ever learn this", which is a different question
    from `family_fit`'s "who would wear this" and has a different source - the
    item's own RequiredSkill against the assigned trade table, rather than
    slots and item levels. Only a NAME moves anything; both LEARNER_HOLDER and
    LEARNER_NOBODY keep, and an item that is not a recipe ignores it entirely.
    """
    if not item.known:
        return Verdict(KEEP, "nothing is known about %s, and an unclassified "
                             "item is kept rather than risked" % item.name)
    if item.quest_item:
        return Verdict(KEEP, "%s is a quest item" % item.name)
    if trade_tool(item):
        # BESIDE THE QUEST-ITEM REFUSAL BECAUSE IT IS THE SAME KIND OF FACT:
        # this is not adventuring loot, so none of the loot questions below
        # apply to it. It sits ABOVE the family-fit gate on purpose as well.
        # `gear.claimant` judges pieces by the slot they go in, so it answers
        # FIT_NOBODY about a pick - correctly, since nobody would WEAR one -
        # and FIT_NOBODY is precisely what retires the level margin and opens
        # the disposal branches at the bottom of this function. A gate that
        # was never asked about tools must not be allowed to sell them.
        #
        # UNCONDITIONAL, AND NOT GATED ON WHO WORKS THE TRADE. `decide` is
        # handed one item and the family's skills, not the roster, and a
        # second rule here that read the permission differently from
        # `profession_keeps` would be the "two answers that can disagree"
        # this module already refuses elsewhere. A tool nobody works costs one
        # bag slot and sixteen copper; the miner who lost his pick stops
        # mining, which is what this cost three characters.
        return Verdict(KEEP, "%s is a trade tool, and a tool has no level to "
                             "outgrow" % item.name)
    if recipe(item) and learner != LEARNER_UNASKED:
        # ABOVE THE FAMILY-FIT GATE, AND THE WHOLE BRANCH IS DEAD BELOW IT.
        # This is not a preference about ordering, it is the only position
        # that works: `gear.claimant` answers UNJUDGEABLE about every class-9
        # row (it judges by slot, and a Pattern goes in no slot), which
        # `bag_pressure.family_fits` translates to FIT_UNJUDGEABLE, which
        # returns KEEP three lines below. A recipe branch written under that
        # gate could never once have fired.
        #
        # IT SITS BESIDE THE TRADE-TOOL REFUSAL FOR THE SAME REASON THAT ONE
        # GIVES: a recipe is not adventuring loot, so none of the loot
        # questions underneath - outgrown, binding, the auction multiple -
        # are about it at all.
        if learner == LEARNER_HOLDER:
            return Verdict(KEEP, "%s teaches the trade its holder already "
                                 "works" % item.name)
        if learner == LEARNER_NOBODY:
            # The same judgement, and deliberately the same words, as the
            # reagent branch below makes about a material for a profession
            # nobody has taken: the family may still take it, so the item is
            # not surplus, it is early. `professions.UNASSIGNED` keeps
            # inscription and jewelcrafting open on purpose for a future
            # guild recruit, and this is the pile that would be waiting.
            if family.bank_reachable and BANK in available:
                return Verdict(BANK, "%s teaches a trade nobody is assigned - "
                                     "the bank keeps it without spending a bag "
                                     "slot on a profession the family may "
                                     "still take" % item.name)
            return Verdict(KEEP, "%s teaches a trade nobody is assigned - "
                                 "keeping it rather than selling the family "
                                 "out of a profession it has not started yet"
                                 % item.name)
        if GIVE not in available:
            return Verdict(KEEP, "%s is %s's trade to learn, and no handover "
                                 "route is open to it" % (item.name, learner))
        # CLAIM BEATS EVERY DISPOSAL, which is what the owner asked for out
        # loud. Reaching this point means the gate ran, named a member, and
        # that member is not the holder - so the item has an owner inside the
        # family and disposing of it would be selling the family its own
        # recipe back later at a vendor's mark-up.
        return Verdict(GIVE, "%s teaches %s's own trade, and it is sitting in "
                             "somebody else's bag" % (item.name, learner))
    if family_fit == FIT_HOLDER:
        # Soulbound or not, the character carrying it would wear it. This sits
        # ABOVE the `outgrown` level test on purpose: required level plus a
        # margin is a proxy for "still wanted", and this is the real answer,
        # so it must not be reachable only when the proxy happens to agree.
        return Verdict(KEEP, "%s is an upgrade for the character already "
                             "carrying it" % item.name)
    if family_fit == FIT_UNJUDGEABLE:
        return Verdict(KEEP, "nothing here can judge whether anybody would "
                             "wear %s, and an unjudged item is kept rather "
                             "than risked" % item.name)
    if upgrade_for_sibling or family_fit == FIT_SIBLING:
        # Deferred to the sibling-upgrade gate rather than re-decided here;
        # two modules answering "is this better" is how they drift apart.
        if GIVE not in available:
            return Verdict(KEEP, "%s suits somebody in the family better, and "
                                 "no handover route is open to it" % item.name)
        return Verdict(GIVE, "%s suits somebody in the family better than what "
                             "they are wearing" % item.name)

    if item.reagent_for:
        needed = family.professions.get(item.reagent_for)
        if needed is None:
            if family.bank_reachable and BANK in available:
                return Verdict(BANK, "%s feeds %s, which nobody has yet - the "
                                     "bank keeps it without spending a bag slot "
                                     "on a profession the family may still take"
                                     % (item.name, item.reagent_for))
            return Verdict(KEEP, "%s feeds %s, which nobody has yet - keeping "
                                 "it rather than selling the family into a "
                                 "profession it cannot start"
                                 % (item.name, item.reagent_for))
        if reagent_held <= family.reagent_keep:
            return Verdict(KEEP, "%s feeds %s and the family holds %d of the "
                                 "%d it keeps"
                                 % (item.name, item.reagent_for, reagent_held,
                                    family.reagent_keep))
        # Surplus beyond what the profession can use is ordinary goods, and
        # cloth and ore are exactly what sells on the auction house.
        if _auction_is_worth_it(item, family, available=available):
            return Verdict(AUCTION, "%s is %d past the %d of %s the family "
                                    "keeps, and it is worth more listed"
                                    % (item.name, reagent_held - family.reagent_keep,
                                       family.reagent_keep, item.reagent_for))
        if VENDOR in available and family.vendor_reachable and item.sell_price > 0:
            return Verdict(VENDOR, "%s is surplus to %s"
                                   % (item.name, item.reagent_for))
        if family.bank_reachable and BANK in available:
            return Verdict(BANK, "%s is surplus with no buyer in reach, and the "
                                 "bank costs nothing to use" % item.name)
        return Verdict(KEEP, "%s is surplus but there is nowhere to take it"
                             % item.name)

    if item.quality == 0:
        if VENDOR in available and family.vendor_reachable and item.sell_price > 0:
            return Verdict(VENDOR, "%s is junk" % item.name)
        return Verdict(KEEP, "%s is junk but no vendor is reachable" % item.name)

    if item.equipment and not outgrown(item, character_level):
        # THE LEVEL MARGIN IS A PROXY FOR THE QUESTION THE GATE HAS ALREADY
        # ANSWERED, and a proxy must not overrule the measurement (infra#3464).
        #
        # `outgrown` asks "has this character moved far enough past the
        # required level that it will never be worn again", which is a guess at
        # "would anybody wear this". FIT_NOBODY is that same question, put to
        # the holder soulbound-blind and to all four siblings by the one
        # opinion that also decides hand-offs, and answered no. Letting the
        # guess win over the answer is why a green that nobody in the family
        # can use sits in a bag until the character out-levels it by ten, and
        # then keeps sitting there because nothing looks at it again.
        #
        # THE ARGUMENT THAT MAKES THIS SAFE IS THAT GEAR ONLY IMPROVES. Item
        # level is fixed on the item; every character's equipped item level
        # only ever goes up, because nothing in this system takes gear off
        # anybody. So a piece that beats nobody's slot today beats nobody's
        # slot at any level after today, and re-asking later cannot change the
        # answer to yes.
        #
        # THE ONE CASE THAT ARGUMENT DOES NOT COVER IS A PIECE NOBODY HAS
        # REACHED YET, and it is excluded rather than reasoned about.
        # `gear.is_upgrade_for` refuses a character below the required level
        # with "requires level N", so a level-30 robe carried by a level-24
        # priest answers NOBODY for a reason that is temporary and that levelling
        # retires. Requiring the holder to have reached the level keeps every
        # one of those, which is the fail-closed direction and the same one the
        # rest of this module takes: a wrong KEEP costs a bag slot, a wrong sale
        # costs the item.
        if family_fit != FIT_NOBODY or item.required_level > character_level:
            return Verdict(KEEP, "%s is still close enough to level to be worn"
                                 % item.name)

    # An old green. This is the branch the whole module exists for, and
    # binding decides which routes are even open.
    if _auction_is_worth_it(item, family, available=available):
        return Verdict(AUCTION, "%s is bind-on-equip and worth more listed "
                                "than vendored" % item.name)
    if DISENCHANT in available and _can_disenchant(item, family):
        return Verdict(DISENCHANT, "%s cannot be listed or is not worth "
                                   "listing, and the family can break it down"
                                   % item.name)
    if (item.binding != BIND_ON_PICKUP and AUCTION not in available
            and family_fit != FIT_NOBODY):
        # A tradable green is the auction's item and, if somebody in the
        # family should be wearing it, the family-fit gate's item. Vendoring
        # it merely because no listing route is BUILT YET throws the
        # difference away permanently, and it is a decision nobody can take
        # back. Waiting costs one bag slot.
        #
        # FIT_NOBODY is what retires that wait, one item at a time: the gate
        # has asked all five and none would wear it, so the "somebody should
        # be wearing it" half is answered, and the measurement above the
        # FIT_* constants prices the "throw the difference away" half at 2.2
        # to 2.9 times a vendor value of 0.77 gold across the whole pile.
        # Waiting then no longer costs one bag slot for a while; it costs the
        # slot indefinitely, for a green nobody will wear and no pass in this
        # process can list.
        return Verdict(KEEP, "%s is still tradable and nothing here can list "
                             "or hand it on yet, so vendoring it now would "
                             "throw away the difference" % item.name)
    if VENDOR in available and family.vendor_reachable and item.sell_price > 0:
        return Verdict(VENDOR, "%s is outgrown, and vendoring is the only "
                               "route open to it" % item.name)
    return Verdict(KEEP, "%s has no route open to it right now" % item.name)


def learners(rows, holders_by_skill) -> dict:
    """`item_guid -> LEARNER_*`, the recipe half of the family-fit gate.

    `rows` are world rows carrying `item_guid`, `holder`, `item_class` and
    `required_skill`. `holders_by_skill` maps a skill line id to the ONE family
    member assigned that trade, and the caller builds it - from
    `professions.ROSTER` put through `goals.SKILL_IDS` - for the same reason
    `profession_keeps` takes `worked` and `named` rather than importing the
    roster: this module is a judgement about items and must not also become the
    place that knows who the family is. Two spellings of the roster is two
    answers that can disagree.

    A ROW THIS CANNOT READ IS ABSENT FROM THE RESULT, not defaulted, and a guid
    that is absent is LEARNER_UNASKED at the point of use - which keeps the
    item. That is the right answer for every way this comes back short: an
    older world image without the column, a row with no holder, a class-9 entry
    that gates on no skill. It is also why this returns only what it positively
    decided, exactly as `bag_pressure.family_fits` does.

    ONE MEMBER PER TRADE, because `professions.ROSTER` assigns one. If a future
    roster gives two characters the same trade the caller's mapping collapses
    them to one name and this hands the recipe to that one, which is a choice
    about WHO and never about WHETHER - the same distinction `family_gifts`
    draws between `gear.claims` and `gear.plan`.
    """
    by_skill = {}
    for skill, who in dict(holders_by_skill or {}).items():
        try:
            skill_id = int(skill)
        except (TypeError, ValueError):
            continue
        who = str(who or "").strip()
        if skill_id > 0 and who:
            by_skill[skill_id] = who

    out = {}
    for row in rows:
        try:
            guid = int(row["item_guid"])
            holder = str(row["holder"]).strip()
            item_class = int(row.get("item_class", 0) or 0)
            required_skill = int(row.get("required_skill", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if guid <= 0 or not holder:
            continue
        if item_class != RECIPE_CLASS or required_skill <= 0:
            continue
        who = by_skill.get(required_skill)
        if isinstance(who, (tuple, list)):
            who = next((str(candidate).strip() for candidate in who
                        if str(candidate).strip()), "")
        if not who:
            out[guid] = LEARNER_NOBODY
        elif who == holder:
            out[guid] = LEARNER_HOLDER
        else:
            out[guid] = who
    return out


def learner_options(rows, holders_by_skill) -> dict:
    """`item_guid -> (master, backups...)` for recipe hand-off planning.

    The first name is the designated profession master. Remaining names are
    explicit backups supplied by the caller in priority order. Keeping the
    ordering in the input lets the profession roster decide policy while this
    module only validates recipe rows and preserves the safe refusal for an
    unassigned skill.
    """
    by_skill = {}
    for skill, candidates in dict(holders_by_skill or {}).items():
        try:
            skill_id = int(skill)
        except (TypeError, ValueError):
            continue
        if isinstance(candidates, str):
            candidates = (candidates,)
        names = []
        for candidate in candidates or ():
            name = str(candidate or "").strip()
            if name and name not in names:
                names.append(name)
        if skill_id > 0 and names:
            by_skill[skill_id] = tuple(names)

    out = {}
    for row in rows:
        try:
            guid = int(row["item_guid"])
            holder = str(row["holder"]).strip()
            item_class = int(row.get("item_class", 0) or 0)
            required_skill = int(row.get("required_skill", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if guid <= 0 or not holder or item_class != RECIPE_CLASS:
            continue
        if required_skill <= 0:
            continue
        candidates = by_skill.get(required_skill, ())
        out[guid] = tuple(candidates) if candidates else (LEARNER_NOBODY,)
    return out


def _trade_of(entry: int, bag_family: int, worked, named) -> str:
    """Which of the family's OWN trades this entry's stock feeds, or ''.

    THE CRAFT TABLES ARE ASKED FIRST AND THE BAG SECOND, and the order is the
    fix rather than tidiness. `named` is what the family's own recipes buy,
    which is a claim somebody verified against the world; the bag is a sorting
    hint that is right about ore and wrong about vials. Empty Vial carries
    inscription's bit and is bought for Alchemy, so asking the bag first would
    sell exactly the stack infra#3709 is about.
    """
    for trade in named.get(entry, ()):
        if trade in worked:
            return trade
    for trade, bit in sorted(PROFESSION_BAGS.items()):
        if trade in worked and bag_family & bit:
            return trade
    return ""


def profession_keeps(rows, worked=(), named=None, reagent_keep=REAGENT_KEEP):
    """The carried stacks no vendor pass may offer, keyed by item guid.

    Returns `item_guid -> why`, and a guid that is absent is simply not
    protected BY THIS RULE - every other refusal the sale path already makes
    still applies on top. Rows this cannot describe are skipped rather than
    guessed at, which leaves them exactly as unprotected as they were before
    this function existed; the fail-closed direction for a MISSING protection
    is the one that changes nothing, not one that pins an unreadable bag.

    `rows` are world rows carrying `item_guid`, `entry`, `item_class`,
    `bag_family`, `count` and `name`. `worked` is the trades the family is
    ASSIGNED - the declared end state from `professions.assigned`, not the
    skills anybody has today, because a character walking to a trainer must
    not have his pick sold out from under him on the way. `named` maps an item
    entry to the trades whose recipes buy it, derived by the caller from the
    craft tables rather than restated here.

    TOOLS ARE KEPT WHOLE AND REAGENTS ARE KEPT BY COUNT, which is the one
    judgement in this function and the brief asked for it out loud.
    A tool is a single item that a profession cannot work without and that
    nothing ever replaces, so there is no quantity at which a second Mining
    Pick becomes surplus - it is kept, always. 25 Empty Vials is STOCK, and a
    rule that kept every reagent for ever would hand back the bag-pressure
    problem the vendor pass exists to solve, so stock is kept up to
    `reagent_keep` and the surplus above it stays sellable.

    AND THE SURPLUS IS COUNTED IN WHOLE STACKS, LARGEST FIRST, WITH AT LEAST
    ONE STACK ALWAYS KEPT. This is the part that stops the fix re-creating the
    bug. An entry-wide "held > keep, so sell it" cliff - the shape `decide`'s
    own reagent branch takes for a caller that supplies `reagent_held` - drops
    the family to ZERO the moment they gather past the line, `craft_supply`
    re-buys, and the lap starts again one number higher. Protecting stacks
    until the next one would cross the line leaves the held count just under
    it instead, which is a fixed point: 3x20 vials with a keep of 40 offers
    one stack and then offers nothing more. A single stack of 60 is kept
    entire, because selling it would empty the shelf.
    """
    worked = {str(trade).strip().lower() for trade in worked
              if str(trade).strip()}
    named = named or {}
    stacks: dict = {}
    for row in rows:
        try:
            guid = int(row["item_guid"])
            entry = int(row["entry"])
            count = int(row.get("count", 0))
            fact = (int(row.get("item_class", 0)), int(row.get("bag_family", 0)))
        except (KeyError, TypeError, ValueError):
            continue
        if guid <= 0 or count <= 0:
            continue
        stacks.setdefault(entry, []).append(
            (count, guid, str(row.get("name", "")), fact))

    keeps: dict = {}
    for entry, held in stacks.items():
        item_class, bag_family = held[0][3]
        if _is_tool(item_class, bag_family):
            for _, guid, name, _fact in held:
                keeps[guid] = ("%s is a trade tool, and a tool has no level "
                               "to outgrow" % name)
            continue
        trade = _trade_of(entry, bag_family, worked, named)
        if not trade:
            continue
        kept = 0
        # Largest stack first, so the surplus that stays sellable is the
        # leftovers rather than the shelf.
        for count, guid, name, _fact in sorted(held, reverse=True):
            if kept and kept + count > reagent_keep:
                continue
            kept += count
            keeps[guid] = ("%s feeds %s, and the family keeps up to %d of it"
                           % (name, trade, reagent_keep))
    return keeps
