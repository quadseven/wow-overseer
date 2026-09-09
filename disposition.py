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
#   AUCTION     the executor is NOT a draft. mod-overseer#208 merged as
#               DoAuction (mod_overseer.cpp:24389): it builds a real
#               CMSG_AUCTION_SELL_ITEM, calls HandleAuctionSellItem, and
#               refuses to report success unless it can read the listing back
#               out of the house. It stays out of this set for two other
#               reasons, both facts about THIS process: nothing here writes a
#               kind='auction' row, and ECONOMY_ERRANDS is ("vendor",
#               "banker", "repair"), so no pass can put a character within the
#               5.5 yards of an auctioneer that DoAuction requires.
#   MAIL        same shape: mod-overseer#219 merged as DoMail, no writer here,
#               and nothing in this repository knows where a mailbox is.
#   DISENCHANT  no executor, and `overseer_command.kind` is an ENUM of 18
#               values that does not contain 'disenchant', so such a row
#               cannot even be inserted. Og, the family enchanter, is skill
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


@dataclass(frozen=True)
class Family:
    """What the family can actually do today, not what it could in principle."""
    enchanting_skill: int = 0
    # profession -> the skill somebody in the family actually has
    professions: dict = field(default_factory=dict)
    # How much of a reagent the family keeps before the rest is surplus.
    reagent_keep: int = 40
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


def outgrown(item, character_level, margin=10):
    """Is this the "old green" a person would clear out?

    Old means the character has moved far enough past it that it will never be
    worn again. The margin exists because an item a level or two behind is
    still a candidate for an alt or a sibling, and clearing those out is how a
    family throws away the upgrade it was about to hand somebody.
    """
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
           reagent_held=0, available=ALL_ROUTES, family_fit=FIT_UNASKED):
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
    """
    if not item.known:
        return Verdict(KEEP, "nothing is known about %s, and an unclassified "
                             "item is kept rather than risked" % item.name)
    if item.quest_item:
        return Verdict(KEEP, "%s is a quest item" % item.name)
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
