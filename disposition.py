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


def _auction_is_worth_it(item, family, multiple=AUCTION_BEATS_VENDOR_BY):
    """Worth a listing slot and the wait, and legal to list at all."""
    if not family.auction_reachable:
        return False
    if item.binding == BIND_ON_PICKUP:
        return False          # the whole point: soulbound cannot be listed
    if item.auction_value is None:
        return False          # unknown price is a reason to take the sure thing
    return item.auction_value >= max(1, item.sell_price) * multiple


def decide(item, family, character_level=1, upgrade_for_sibling=False,
           reagent_held=0):
    """One item, one route, with the reason attached.

    Order matters and is the argument: every refusal is checked before every
    disposal, so a bug in the disposal ranking can waste value but cannot
    destroy something irreplaceable.
    """
    if not item.known:
        return Verdict(KEEP, "nothing is known about %s, and an unclassified "
                             "item is kept rather than risked" % item.name)
    if item.quest_item:
        return Verdict(KEEP, "%s is a quest item" % item.name)
    if upgrade_for_sibling:
        # Deferred to the sibling-upgrade gate rather than re-decided here;
        # two modules answering "is this better" is how they drift apart.
        return Verdict(GIVE, "%s suits somebody in the family better than what "
                             "they are wearing" % item.name)

    if item.reagent_for:
        needed = family.professions.get(item.reagent_for)
        if needed is None:
            if family.bank_reachable:
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
        if _auction_is_worth_it(item, family):
            return Verdict(AUCTION, "%s is %d past the %d of %s the family "
                                    "keeps, and it is worth more listed"
                                    % (item.name, reagent_held - family.reagent_keep,
                                       family.reagent_keep, item.reagent_for))
        if family.vendor_reachable and item.sell_price > 0:
            return Verdict(VENDOR, "%s is surplus to %s"
                                   % (item.name, item.reagent_for))
        if family.bank_reachable:
            return Verdict(BANK, "%s is surplus with no buyer in reach, and the "
                                 "bank costs nothing to use" % item.name)
        return Verdict(KEEP, "%s is surplus but there is nowhere to take it"
                             % item.name)

    if item.quality == 0:
        if family.vendor_reachable and item.sell_price > 0:
            return Verdict(VENDOR, "%s is junk" % item.name)
        return Verdict(KEEP, "%s is junk but no vendor is reachable" % item.name)

    if item.equipment and not outgrown(item, character_level):
        return Verdict(KEEP, "%s is still close enough to level to be worn"
                             % item.name)

    # An old green. This is the branch the whole module exists for, and
    # binding decides which routes are even open.
    if _auction_is_worth_it(item, family):
        return Verdict(AUCTION, "%s is bind-on-equip and worth more listed "
                                "than vendored" % item.name)
    if _can_disenchant(item, family):
        return Verdict(DISENCHANT, "%s cannot be listed or is not worth "
                                   "listing, and the family can break it down"
                                   % item.name)
    if family.vendor_reachable and item.sell_price > 0:
        return Verdict(VENDOR, "%s is outgrown, and vendoring is the only "
                               "route open to it" % item.name)
    return Verdict(KEEP, "%s has no route open to it right now" % item.name)
