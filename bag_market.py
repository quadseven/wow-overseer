"""Buy a bigger bag for a member whose bag positions are all full.

MEASURED ON THE DEV REALM, 2026-09-23. The first family is level 60 and wears
four bags each, but small ones: worn slots were Grug 54, Bork 50, Og 50,
Grog 34 and Ugga 30, and Ugga's smallest bag is a 6-slot pouch. The second
family (levels 22 to 25) wears nineteen 6-slot pouches and one 8-slot bag
between five members. Every bag the bag pass had ever bought was a 6-slot
pouch, because `bag_pressure.bag_purchases` buys only for an EMPTY position,
and every position was already full. Nothing ever replaced a small bag.

The auction house held 12-slot general bags at the same time: Sturdy Lunchbox
and Large Knapsack in the Alliance house for 6,878 to 9,748 copper, Mageweave
Bags in the Horde house for 4,267. The first family carried 116 gold
between them. So the money was there, and so were the bags.

WHAT THIS MODULE DECIDES. For each member with no empty bag position, the
largest general bag it can buy within a spending rule, replacing the smallest
bag it wears. It decides nothing about how the bag is bought or put on:

    auction house   `auction.buy_command`, a kind='auction' row. The bag
                    arrives by mail, the mail pass collects it, and
                    `bag_upgrade.self_equips` puts it on.
    vendor          the kind='buy' town-trip row `bag_pressure.BagPurchase`
                    already writes, then the same `e` equip row.

The equip verb is mod-playerbots' `e`: with every position full it swaps the
new bag for the smallest worn one and the core moves that bag's items into
the new one (`bag_upgrade.self_equips` states the conditions). The displaced
bag is then carried, no larger than any worn bag, and
`bag_pressure.bag_candidates` sells it.

THE SPENDING RULE, IN FOUR PARTS.

  1. A family share. One pass spends at most `UPGRADE_SHARE_PERCENT` of the
     gold the family carries between them.
  2. A repair reserve. Each buyer keeps `UPGRADE_RESERVE_PER_LEVEL` copper per
     level in the purse after the purchase.
  3. A price per slot. A bag costing more than `MAX_COPPER_PER_SLOT` for each
     slot it adds is refused however rich the family is, except a vendor's
     bag for a member at the bag floor (`cap_yields`).
  4. Only the buyer's own purse. The guild bank is never drawn on: the only
     guild-money verb this bridge uses is a deposit (`guildbank.py`), and
     mod-overseer's withdraw verb needs a rank-permission read this bridge
     does not have.

PURE MODULE, the same seam as bag_upgrade.py and bag_pressure.py: rows in,
decisions out, no MySQL.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import auction
import bag_pressure
import classic
import travel
from bag_upgrade import Bag, Member, safe_self_equip_spares

AUCTION = "auction"
VENDOR = "vendor"

# At most this share of the family's carried gold goes on bags in one pass.
# A judgement: a quarter leaves three quarters for training, repairs and
# reagents, and one pass buys at most one bag per member anyway. Measured on
# the first family, a quarter of 116 gold is 29 gold against the 4.3 gold a
# 12-slot bag for all five costs, so the share binds only on a poor family.
UPGRADE_SHARE_PERCENT = 25

# Copper kept per level after an upgrade: 1.8 gold at level 60, 66 silver at
# level 22. Three times `bag_pressure.BAG_RESERVE_PER_LEVEL`, because a bag
# in an empty position is a loss every minute it is missing, while an upgrade
# can wait for the next pass.
UPGRADE_RESERVE_PER_LEVEL = 300

# The most a bag may cost for each slot it adds. Measured on the dev realm:
# the Alliance house's 12-slot bags over an 8-slot bag cost 1,720 to 2,437
# copper a slot, and the vendor's Huge Brown Sack (100,000 copper) over the
# same bag costs 25,000. The cap buys the first and refuses the second.
MAX_COPPER_PER_SLOT = 2500

# A bag that adds fewer slots than this is not worth the swap.
MIN_UPGRADE_GAIN = 2


# THE SLOT CAP GIVES WAY AT THE BAG FLOOR, FOR A VENDOR'S BAG ONLY.
#
# Measured on the dev realm, 2026-10-19: a family was held more than four
# hours on "Bork, Grog at the bag floor and no town pass has made room". Grog
# had 3 free slots, wore an 8-slot bag as its smallest, and carried 12.8 gold
# at level 43; the family carried about 80 gold between them. Every vendor
# bag that beats an 8-slot one costs more than the cap: the Heavy Brown Bag
# (10 slots, 20,000 copper) is 10,000 a slot added and the Huge Brown Sack
# (12 slots, 100,000 copper) is 25,000. So no vendor upgrade was ever bought
# for a member already wearing 8-slot bags, however long the hold lasted.
#
# The cap is a value judgement for a member with room to spare, where the
# house's cheaper 12-slot bags are worth waiting for. At the floor the wait
# is the hold itself, so a vendor's bag the reserve and the family share
# allow is bought there and then. An auction listing keeps the cap: it
# arrives by mail, and a member at the floor may have no room to collect it.


def cap_yields(free_slots) -> bool:
    """Does the per-slot cap give way for this member (see above)?

    Yes when the member's free bag slots are a real reading at or below
    `bag_pressure.TOWN_RUN_FREE_SLOTS`, the line the family is held on.
    An unknown reading (None, negative, not an int) fails closed.
    """
    return (
        isinstance(free_slots, int)
        and not isinstance(free_slots, bool)
        and 0 <= free_slots <= bag_pressure.TOWN_RUN_FREE_SLOTS
    )


@dataclass(frozen=True)
class Listing:
    """One general bag for sale: an auction listing, or a vendor's stock.

    `key` is the auction id for an auction listing and the item entry for a
    vendor's. An auction listing is sold once; a vendor's stock is not used
    up. `unique` is item_template.maxcount above zero, and such a bag cannot
    be bought by somebody who already owns one.
    """

    source: str
    key: int
    entry: int
    name: str
    slots: int
    price: int
    unique: bool = False


@dataclass(frozen=True)
class Purse:
    """What one member carries and the level its reserve is measured at."""

    level: int
    money: int


@dataclass(frozen=True)
class Upgrade:
    """One bag to buy, and the worn bag it will replace."""

    buyer: str
    listing: Listing
    replaces: int
    gain: int
    why: str

    @property
    def command(self) -> str:
        """The row text the listing's source takes."""
        if self.listing.source == AUCTION:
            return auction.buy_command(self.listing.key)
        return "entry:%d count:1 max:%d" % (self.listing.entry, self.listing.price)

    @property
    def equip_command(self) -> str:
        """The playerbot equip verb, the one `bag_upgrade.SelfEquip` uses."""
        return "e Hitem:%d:0" % self.listing.entry

    @property
    def price(self) -> int:
        return self.listing.price


def smallest_worn(member: Member) -> int | None:
    """The smallest bag this member wears, or None when an upgrade is not the move.

    None for an empty bag position: `bag_pressure.bag_purchases` fills that
    first, and the equip verb puts a new bag into the empty position rather
    than in place of a small one.
    """
    if not member.worn or len(member.worn) < member.positions:
        return None
    return min(bag.slots for bag in member.worn)


def on_the_way(member: Member, mailed=()) -> int:
    """The size of a bigger bag this member already has coming, or 0.

    A carried empty general bag larger than the smallest worn one is put on by
    `bag_upgrade.self_equips`; a larger general bag in the mail is collected by
    the mail pass first. Buying another would buy the same room twice.
    `mailed` is the ContainerSlots of each general bag in this member's mail.
    """
    size = smallest_worn(member)
    if size is None:
        return 0
    sizes = [bag.slots for bag, _target in safe_self_equip_spares(member)]
    sizes.extend(int(slots) for slots in mailed if int(slots) > size)
    return max(sizes, default=0)


def family_budget(purses: dict, share: int = UPGRADE_SHARE_PERCENT) -> int:
    """The copper one pass may spend on bags for the whole family."""
    total = sum(max(0, int(p.money)) for p in purses.values())
    return total * max(0, int(share)) // 100


def spendable(purse: Purse, reserve_per_level: int = UPGRADE_RESERVE_PER_LEVEL) -> int:
    """What one buyer may spend and still keep its repair reserve."""
    return max(0, int(purse.money) - reserve_per_level * max(1, int(purse.level)))


def _order(members):
    """Smallest worn bag first, then the least room in all, then the name."""
    return sorted(
        members,
        key=lambda m: (smallest_worn(m), sum(b.slots for b in m.worn), m.name),
    )


@dataclass(frozen=True)
class Rule:
    """The spending rule's numbers, so tests can bend one at a time."""

    share: int = UPGRADE_SHARE_PERCENT
    reserve_per_level: int = UPGRADE_RESERVE_PER_LEVEL
    max_per_slot: int = MAX_COPPER_PER_SLOT
    min_gain: int = MIN_UPGRADE_GAIN


@dataclass(frozen=True)
class _Shopper:
    """One member's side of a pass: what it wears, owns, may spend and reach."""

    name: str
    size: int
    owned: frozenset
    allowance: int
    room: int
    reach: frozenset | None
    at_floor: bool = False


def _offered(listing: Listing, who: _Shopper, taken: set, rule: Rule) -> bool:
    """Could this member buy this bag at all, price aside?"""
    if listing.slots - who.size < rule.min_gain or listing.price <= 0:
        return False
    if not classic.item_ok(listing.entry):
        return False  # an Outland or Northrend bag: outside the classic ruleset
    if listing.unique and listing.entry in who.owned:
        return False
    if listing.source == AUCTION:
        # In every buyer's reach, sold once, and delivered by mail.
        return listing.key not in taken
    if who.reach is not None and listing.entry not in who.reach:
        return False
    return who.room >= 1


def _slot_cap_applies(listing: Listing, who: _Shopper) -> bool:
    return not (listing.source == VENDOR and who.at_floor)


def _affordable(listing: Listing, who: _Shopper, rule: Rule) -> bool:
    if listing.price > who.allowance:
        return False
    if not _slot_cap_applies(listing, who):
        return True
    gain = listing.slots - who.size
    return listing.price <= gain * rule.max_per_slot


def _best(listings, who: _Shopper, taken: set, rule: Rule):
    """(the bag to buy or None, whether any bigger bag was on offer)."""
    offered = [x for x in listings if _offered(x, who, taken, rule)]
    choices = [x for x in offered if _affordable(x, who, rule)]
    if not choices:
        return None, bool(offered)
    return min(choices, key=lambda x: (-x.slots, x.price, x.source, x.key)), True


def _refusal(who: _Shopper, purse: Purse, budget: int, rule: Rule) -> str:
    return (
        "%s cannot buy a bag bigger than its %d-slot one: %d copper may be "
        "spent (%d in the purse, %d kept back at level %d, %d left of the "
        "family's share), at most %d a slot%s"
        % (
            who.name,
            who.size,
            who.allowance,
            purse.money,
            rule.reserve_per_level * max(1, purse.level),
            purse.level,
            budget,
            rule.max_per_slot,
            " (no cap on a vendor's bag at the bag floor)" if who.at_floor else "",
        )
    )


def _shopper(member: Member, purse: Purse, budget: int, reach, free_slots, rule):
    owned = {bag.entry for bag in member.worn + member.carried if bag.entry}
    return _Shopper(
        name=member.name,
        size=smallest_worn(member),
        owned=frozenset(owned),
        allowance=min(spendable(purse, rule.reserve_per_level), budget),
        room=int((free_slots or {}).get(member.name, 0)),
        reach=None if reach is None else frozenset(reach.get(member.name, ())),
        at_floor=cap_yields((free_slots or {}).get(member.name)),
    )


def plan_upgrades(
    members,
    purses: dict,
    listings,
    *,
    mailed=None,
    reach=None,
    free_slots=None,
    rule: Rule = Rule(),
) -> tuple:
    """The best affordable upgrade per member, and a note for each refusal.

    One bag per member per pass; the next pass sees the bag this one bought.
    The member with the smallest worn bag chooses first. Each member takes the
    LARGEST bag its purse and the family share allow, the cheapest of that
    size, and an auction listing goes to one buyer only. Returns
    (upgrades, notes).

    `reach` maps a buyer to the entries its vendors stock; a vendor listing
    is only offered to a buyer who can reach it. `free_slots` maps a buyer to
    its free bag slots, and a vendor purchase needs one to land in; an
    auction purchase goes to the mail and does not. A buyer at the bag floor
    (`cap_yields`) is not held to the per-slot cap for a vendor's bag.
    """
    mailed = mailed or {}
    budget = family_budget(purses, rule.share)
    taken: set = set()
    upgrades: list = []
    notes: list = []
    for member in _order(m for m in members if smallest_worn(m) is not None):
        coming = on_the_way(member, mailed.get(member.name, ()))
        purse = purses.get(member.name)
        if coming or purse is None:
            notes.append(
                "%s already has a %d-slot bag coming" % (member.name, coming)
                if coming
                else "%s has no purse reading, so buys nothing" % member.name
            )
            continue
        who = _shopper(member, purse, budget, reach, free_slots, rule)
        listing, bigger = _best(listings, who, taken, rule)
        if listing is None:
            if bigger:
                notes.append(_refusal(who, purse, budget, rule))
            continue
        budget -= listing.price
        if listing.source == AUCTION:
            taken.add(listing.key)
        upgrades.append(
            Upgrade(
                buyer=member.name,
                listing=listing,
                replaces=who.size,
                gain=listing.slots - who.size,
                why="%s (%d slots) replaces a %d-slot bag for %d copper of %d "
                "spendable%s"
                % (
                    listing.name,
                    listing.slots,
                    who.size,
                    listing.price,
                    who.allowance,
                    "; the slot cap gives way at the bag floor (%d free)" % who.room
                    if not _slot_cap_applies(listing, who)
                    else "",
                ),
            )
        )
    return tuple(upgrades), tuple(notes)


def after(members, upgrades) -> list:
    """The members as they will be once every upgrade is worn.

    The new bag replaces the smallest worn one, which is the bag the equip
    verb swaps out. Used to report what a plan promises, and by a replay to
    run the next pass against the bags the last one bought.
    """
    by_buyer = {u.buyer: u for u in upgrades}
    out = []
    for member in members:
        upgrade = by_buyer.get(member.name)
        if upgrade is None:
            out.append(member)
            continue
        worn = list(member.worn)
        smallest = min(range(len(worn)), key=lambda i: (worn[i].slots, -i))
        worn[smallest] = Bag(
            upgrade.listing.name,
            upgrade.listing.slots,
            entry=upgrade.listing.entry,
        )
        out.append(replace(member, worn=tuple(worn)))
    return out


def worn_slots(members) -> dict:
    """name -> the slots of every bag it wears."""
    return {m.name: sum(bag.slots for bag in m.worn) for m in members}


def report(upgrades, budget: int) -> str:
    """One line for the log, whatever the plan."""
    if not upgrades:
        return "bag upgrade: nothing to buy within a %d copper budget" % budget
    spend = sum(u.price for u in upgrades)
    return "bag upgrade: %d purchase(s), %d copper of a %d copper budget - %s" % (
        len(upgrades),
        spend,
        budget,
        "; ".join(
            "%s +%d (%s, %s)" % (u.buyer, u.gain, u.listing.name, u.listing.source)
            for u in upgrades
        ),
    )


# ---------------------------------------------------------------------------
# WALKING TO A VENDOR FOR A BIGGER BAG (#1218)
#
# Measured on the dev realm, 2026-10-19: the health endpoint read Bork and
# Ugga stuck following Grug for 4.3 hours on "Bork, Grog at the bag floor and
# no town pass has made room". Grog, one of the two members the hold names,
# held 3 free slots, wore an 8-slot bag as its smallest and carried 12.8 gold
# at level 43: past the slot cap since the floor yields it, an upgrade it can
# afford, yet no town pass ever walked it to a bag vendor. `_vendor_bag_upgrades`
# buys only for a member already standing at a vendor that stocks bags, and
# `bag_pressure.bag_vendor_trip` walks only members with an empty bag
# position, so a member whose positions are all full never reaches the counter
# its upgrade is sold at. The walk below is that trip's other half: the
# nearest vendor on the leader's map at which at least one full-position
# member at the floor can afford a bigger bag, judged by the same
# `plan_upgrades` (purse, reserve, family share, and the cap that yields at
# the floor) against what that vendor stocks.


def _standing_map(standing: dict, name: str) -> int | None:
    """The map `name` stands on, or None when it cannot be read."""
    spot = (standing or {}).get(name)
    if spot is None or spot.map_id is None:
        return None
    try:
        return int(spot.map_id)
    except (TypeError, ValueError):
        return None


def _upgrade_walkers(members, free_slots) -> tuple:
    """Full-position members at the floor with room for a bag to land in, by
    name. An empty position belongs to `bag_pressure.bag_purchases` and its
    walk; a member with no free slot has nowhere for a vendor's bag to land
    in, so neither trip is for it."""
    walkers = []
    for member in sorted(members or (), key=lambda m: m.name):
        if smallest_worn(member) is None:
            continue
        free = (free_slots or {}).get(member.name)
        if not cap_yields(free) or int(free) < 1:
            continue
        walkers.append(member)
    return tuple(walkers)


def _upgrade_vendors(vendors, map_id: int, max_yards: float) -> list:
    """Stocking vendors on the leader's map within the cap, nearest first."""
    return sorted(
        (
            v
            for v in (vendors or ())
            if int(v.map_id) == map_id and float(v.yards) <= max_yards and v.offers
        ),
        key=lambda v: (float(v.yards), int(v.entry)),
    )


def upgrade_vendor_trip(
    members,
    purses: dict,
    vendors,
    *,
    free_slots=None,
    mailed=None,
    leader: str,
    standing: dict,
    in_run: bool = False,
    max_yards: float = bag_pressure.BAG_VENDOR_MAX_YARDS,
) -> bag_pressure.BagTrip:
    """Where to walk the family so a full member can buy a bigger bag.

    `members` wear every position full or not; only the full ones at the bag
    floor (`cap_yields`) with a free slot for the purchase to land in walk.
    `vendors` are `bag_pressure.BagVendor` measured from the leader. The
    nearest vendor within `max_yards` on the leader's map at which
    `plan_upgrades` serves at least one walker, judged against what that
    vendor stocks, is chosen; ties go to the lower entry. Never over
    something more important, the same bar as `bag_pressure.bag_vendor_trip`.
    """
    blocked = bag_pressure.trip_blocked(leader, standing, in_run)
    if blocked:
        return bag_pressure.BagTrip(why_not=blocked)
    map_id = int(standing[leader].map_id)
    walkers = [
        w
        for w in _upgrade_walkers(members, free_slots)
        if _standing_map(standing, w.name) == map_id
    ]
    if not walkers:
        return bag_pressure.BagTrip(
            why_not="nobody on %s's map wants a bigger bag and has a free "
            "slot for one to land in" % leader
        )
    usable = _upgrade_vendors(vendors, map_id, max_yards)
    if not usable:
        return bag_pressure.BagTrip(
            why_not="no vendor within %d yards of %s on map %d stocks a bag"
            % (int(max_yards), leader, map_id)
        )
    for vendor in usable:
        entries = frozenset(int(o.entry) for o in vendor.offers)
        listings = [
            Listing(
                source=VENDOR,
                key=int(o.entry),
                entry=int(o.entry),
                name=o.name,
                slots=int(o.slots),
                price=int(o.price),
            )
            for o in vendor.offers
        ]
        reach = {w.name: entries for w in walkers}
        upgrades, _notes = plan_upgrades(
            walkers,
            purses or {},
            listings,
            mailed=mailed,
            reach=reach,
            free_slots=free_slots,
        )
        served = tuple(u.buyer for u in upgrades)
        if not served:
            continue
        if float(vendor.yards) <= bag_pressure.BAG_VENDOR_HERE_YARDS:
            return bag_pressure.BagTrip(
                vendor=vendor,
                buyers=served,
                why_not="%s already stands at %s; the upgrade "
                "waits for the buyers to reach the counter"
                % (leader, vendor.name or "an unnamed creature (%d)" % vendor.entry),
            )
        target = travel.resolve(str(int(vendor.entry)))
        if not target or len(target) > travel.COLUMN_WIDTH:
            return bag_pressure.BagTrip(
                why_not="vendor entry %r cannot be named in travel_npc"
                % (vendor.entry,)
            )
        return bag_pressure.BagTrip(target=target, vendor=vendor, buyers=served)
    return bag_pressure.BagTrip(
        why_not="nobody at the floor can spare a bigger bag within %d yards"
        % int(max_yards)
    )


# ---------------------------------------------------------------------------
# THE SELL PATH MUST GET THE TRAVELLER BEFORE A DISCOVERY WALK
#
# Measured on the dev realm, 2026-09-23: the auction pass held the leader's
# `auctioneer` aim to list surplus while Ugga had no room for her mail, and
# the town slot handed the column to the flight pass, which walked the leader
# 4,687 yards to learn a taxi node on a 781-second lease. For about thirty
# minutes every other town pass logged "flight has been waiting ... longer
# and takes the slot first". A flight node is learned for ever and can be
# learned next hour; a full bag drops loot now, and a sale is also what pays
# for the bags above.


def discovery_waits(free_slots: dict) -> str:
    """Why a flight discovery walk should wait for the family's bags, or "".

    The same trigger the vendor and auction passes use to claim the traveller
    urgently: a member at or below `bag_pressure.TOWN_RUN_FREE_SLOTS` free.
    """
    if not bag_pressure.family_town_run_needed(free_slots):
        return ""
    low = sorted(
        name
        for name, free in free_slots.items()
        if isinstance(free, int) and 0 <= free <= bag_pressure.TOWN_RUN_FREE_SLOTS
    )
    return "%s at %d or fewer free bag slots, so the sell and bag passes go first" % (
        ", ".join(low),
        bag_pressure.TOWN_RUN_FREE_SLOTS,
    )
