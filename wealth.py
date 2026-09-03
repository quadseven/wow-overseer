"""Pure builder for the Wealth and Bags view: what the five own, and what it is worth.

WHY THIS EXISTS. The Armory tab answers "what is he WEARING". Nothing on any
surface has ever answered "what is he CARRYING", and that second question is
where two live defects hide.

  1. THE BAGS ARE FULL. Measured against the live realm on the day this
     landed: Grug 44/44, Ugga 46/46, Bork 22/22, Og 30/30, Grog 47/48. One
     free slot across the whole family. That is the same condition #2800 was
     opened for (a bot with no room can never finish a loot, so `open loot`
     at relevance 8.0 preempts questing forever, and Grug held one position
     to within 0.1 yard for eight and a half hours), and until this view
     there was no way to see it without writing SQL by hand. A number nobody
     can see is a number nobody checks, which is the whole reason the Armory
     tab exists too (infra#3096).

  2. NOBODY SELLS ANYTHING. They hold roughly 140 to 170 gold each and about
     a gold and a half of vendor goods apiece, and eleven rare items across
     the five - three of them sitting in bags rather than worn. Nothing in
     the module lists, buys, bids or sells (quadseven/mod-overseer#147 is the
     open ticket for auction behaviour), so `acore_characters.auctionhouse`
     is empty and will stay empty until somebody wires it. This view says
     that out loud rather than drawing a blank panel, because a blank panel
     and "the auction house is broken" look identical.

WHAT A SLOT MEANS, worked out against the live database rather than assumed.
`character_inventory` is (guid, bag, slot, item), where `item` is the
item_instance guid and `bag` is the item_instance guid OF THE CONTAINER, not
a bag index. So:

  bag = 0, slot 0..18    the paper doll (panel._EQUIPMENT_SLOT_NAMES)
  bag = 0, slot 19..22   the four carried bag slots; `item` here is the guid
                         that the container's own contents name in THEIR
                         `bag` column
  bag = 0, slot 23..38   the built-in sixteen-slot backpack
  bag = 0, slot 39..     bank, bank bags, keyring, buyback: owned, not carried
  bag != 0               inside the container whose item guid that is

panel.py already pinned those ranges down for the map's character panel, so
they are imported from there rather than retyped: two modules disagreeing
about where the backpack starts would be two different answers to "how full
is he", both rendered, neither flagged.

Same seam rule as map_core, panel, family and armory (infra#2597): the HTTP
adapter fetches rows and does nothing else. Every judgement here - what
counts as carried, what "full" means, which items are worth naming, what the
auction table can and cannot honestly say - lives in this module where the
stdlib suite can reach it without a database.

Tickets: quadseven/mod-overseer#88, quadseven/mod-overseer#147.
"""
from __future__ import annotations

import bonds
import family
from armory import (
    ARMOR_SUBCLASSES, CLASS_COLOURS, EQUIPPED_SLOTS, ITEM_CLASS_ARMOR,
    ITEM_CLASS_WEAPON, QUALITY_NAMES, UNKNOWN_QUALITY, WEAPON_SUBCLASSES,
)
from panel import _BACKPACK_SLOTS, _BAG_SLOTS, _BANK_BAG_SLOTS, _CLASS_NAMES

# The coin. Named rather than spelled 10000 three times, because the one bug
# this arithmetic can have is a factor of a hundred and it would look right.
COPPER_PER_SILVER = 100
SILVER_PER_GOLD = 100
COPPER_PER_GOLD = COPPER_PER_SILVER * SILVER_PER_GOLD

# The backpack every character is born with, and the four slots a bag can go
# in. Both derived from panel's ranges so there is exactly one place that
# decides where the backpack starts and how many bags a character may carry.
BACKPACK_SLOTS = len(_BACKPACK_SLOTS)
BAG_POSITIONS = len(_BAG_SLOTS)
BACKPACK = "backpack"
BACKPACK_NAME = "Backpack"

# Green and better. "Notable" is not a synonym for "valuable": a stack of
# linen is worth more copper than most of the greens they are hauling, and
# the question this list answers is "is somebody carrying something they
# should be wearing, banking or selling", which is a QUALITY question.
NOTABLE_QUALITY = 2
RARE_QUALITY = 3

# item_template.class, for everything that is not a weapon or a piece of
# armour (those two get their subclass word, which is the more useful one:
# "Sword" beats "Weapon"). 3.3.5a ItemClass, from the core's ItemPrototype.h.
ITEM_CLASSES = {
    0: "Consumable", 1: "Container", 2: "Weapon", 3: "Gem", 4: "Armor",
    5: "Reagent", 6: "Projectile", 7: "Trade Goods", 8: "Generic",
    9: "Recipe", 10: "Money", 11: "Quiver", 12: "Quest", 13: "Key",
    14: "Permanent", 15: "Miscellaneous", 16: "Glyph",
}

# The tooltip host. achievements.py builds the same URL for the same reason;
# it is two lines and a constant, and importing one tab's renderer into
# another to share a string would couple two features that have nothing else
# in common.
WOWHEAD = "https://www.wowhead.com/wotlk/item=%d"

# The open ticket behind the empty auction panel. Carried in the PAYLOAD
# rather than typed into the page for the same reason the wowhead links are:
# index.html holds itself to naming exactly two outside hosts (the icon CDN
# and the model viewer), and the reason a panel is empty belongs with the
# module that knows the reason, not with the code that draws it.
AUCTION_TICKET = {
    "label": "mod-overseer#147",
    "url": "https://github.com/quadseven/mod-overseer/issues/147",
}

# Where an item is, as one word the page can group by. Equipped items are in
# `character_inventory` exactly like carried ones and they are part of what
# the family HOLDS, so they are counted; they are marked so the bag grid can
# leave them out and the notable list can say "he is wearing it".
EQUIPPED = "equipped"
CARRIED = "carried"
ELSEWHERE = "elsewhere"


def coins(copper: int | None) -> dict:
    """Copper -> the three coins, ALWAYS a dict.

    armory.money() returns None for nothing, which is right for a tooltip
    line that should not be drawn at all. Here nothing is a real answer -
    "this stack is worth nothing to a vendor" is exactly what a quest item
    is - so zero renders as zero and the page decides whether to draw it.

    A negative purse is not a state `characters.money` can hold (it is an
    unsigned column), so a negative reads as zero rather than as three
    negative coins that would look like a rendering bug.
    """
    total = int(copper or 0)
    if total < 0:
        total = 0
    return {
        "gold": total // COPPER_PER_GOLD,
        "silver": total // COPPER_PER_SILVER % SILVER_PER_GOLD,
        "copper": total % COPPER_PER_SILVER,
        "total": total,
    }


def quality_name(quality: int | None) -> str:
    """The word the game itself uses for a quality, or 'unknown'."""
    if quality is None:
        return UNKNOWN_QUALITY
    return QUALITY_NAMES.get(quality, UNKNOWN_QUALITY)


def known_quality(quality: int | None) -> int | None:
    """The quality, or None when it is not one the game defines.

    EVERYTHING THAT COUNTS QUALITIES HAS TO ASK THIS, and the first cut of
    this module did not. quality_name() already answers "unknown" for
    anything outside 0..7, but the tallies compared the raw number, so a
    custom item stamped quality 99 was NAMED unknown in the breakdown and
    COUNTED as better than an epic in `rare_or_better` on the same card -
    two numbers drawn side by side, disagreeing, and the wrong one was the
    headline. The world database is a tinyint and a module is free to write
    8 into it, so this is reachable, not theoretical.

    Found by Grug Elder on the pull request (rule `type-safety-gap`).
    """
    return quality if quality in QUALITY_NAMES else None


def at_least(quality: int | None, minimum: int) -> bool:
    """Is this a quality the game defines, and is it at least `minimum`?

    Both halves, and the second is not enough on its own: an unknown
    quality must never satisfy a floor, not even a floor of zero. It might
    be an epic and it might be a vendor shirt, and guessing upward is how a
    made-up rare gets into the family's rare count.
    """
    known = known_quality(quality)
    return known is not None and known >= minimum


def item_kind(row: dict) -> str | None:
    """'Sword', 'Cloth', 'Trade Goods': the word a person sorts a bag by.

    Weapons and armour get their SUBCLASS, because "Sword" and "Mail" are
    what a player actually reads; everything else gets its class, because
    the subclass of a consumable ("Potion", "Elixir") is finer than anybody
    needs when the question is "why is my bag full".
    """
    item_class, subclass = row.get("class"), row.get("subclass")
    if item_class == ITEM_CLASS_ARMOR:
        return ARMOR_SUBCLASSES.get(subclass) or ITEM_CLASSES[ITEM_CLASS_ARMOR]
    if item_class == ITEM_CLASS_WEAPON:
        return WEAPON_SUBCLASSES.get(subclass) or ITEM_CLASSES[ITEM_CLASS_WEAPON]
    return ITEM_CLASSES.get(item_class)


def item_name(row: dict) -> str:
    """The item's name, or which item it is when the world does not know it.

    A LEFT JOIN miss on acore_world.item_template is a custom or removed
    item. It is genuinely in the bag and it genuinely occupies a slot, so it
    must not render as an empty square: panel and armory both say which item
    instead, and so does this.
    """
    name = row.get("item_name")
    return name if name is not None else "Item #%d" % row["entry"]


def stack_value(row: dict) -> int:
    """What a vendor pays for the WHOLE stack in this slot.

    SellPrice is per unit and twenty linen is twenty times one linen. A
    SellPrice of 0 is not missing data: it is the game saying this item
    cannot be sold at all, which is what every quest item and the hearthstone
    are, and it is why the vendor total is so much smaller than the pile of
    items suggests.
    """
    return int(row.get("sell_price") or 0) * int(row.get("count") or 1)


def item_payload(row: dict, icons: dict[int, str], where: str,
                 container: str | None = None, position: int | None = None) -> dict:
    """One inventory row, as the page draws it.

    `where` is EQUIPPED, CARRIED or ELSEWHERE and `container` is the name of
    the bag it sits in, so one flat list of items can be grouped, filtered
    and counted without the page re-deriving any of it.

    `slot` is the raw database slot and `position` is the index INSIDE the
    container, which for the backpack is not the same number: its sixteen
    slots are 23 to 38 in `character_inventory`. The page draws a bag as a
    grid of every position it has, full or not, so it needs the index and
    not the row number; keeping both means neither has to be re-derived by
    somebody who does not know that the backpack starts at 23.
    """
    quality = row.get("quality")
    count = int(row.get("count") or 1)
    value = stack_value(row)
    return {
        "slot": row["slot"],
        "entry": row["entry"],
        "name": item_name(row),
        "quality": quality,
        "quality_name": quality_name(quality),
        # The icon is the DISPLAY's, and a display the frozen book does not
        # know (a custom item) gets none: the page draws the name instead of
        # a broken picture, exactly as the Armory's paper doll does.
        "icon": icons.get(row.get("displayid") or 0),
        "item_level": row.get("item_level"),
        "count": count,
        "kind": item_kind(row),
        "sell_price": int(row.get("sell_price") or 0),
        "value": coins(value),
        "value_copper": value,
        "where": where,
        "container": container,
        "position": position,
        "wowhead": WOWHEAD % row["entry"],
    }


def _container(key: str, position: int, slots: int, name: str,
               row: dict | None, icons: dict[int, str]) -> dict:
    """One place items can be: the backpack, or a bag in one of the four slots."""
    return {
        "key": key,
        "position": position,
        "name": name,
        "slots": slots,
        "items": [],
        # The bag itself is an item, so it has a quality, an icon and a
        # wowhead page like anything else. The backpack is not an item and
        # has none of those, which is why they are all optional.
        "entry": row["entry"] if row else None,
        "quality": row.get("quality") if row else None,
        "quality_name": quality_name(row.get("quality")) if row else None,
        "icon": icons.get(row.get("displayid") or 0) if row else None,
        "wowhead": WOWHEAD % row["entry"] if row else None,
    }


def split_inventory(rows: list[dict], icons: dict[int, str]) -> dict:
    """One character's character_inventory rows -> where everything actually is.

    Returns equipped items, the containers in the order they hang off the
    character (backpack first, then bag slots one to four), and a count of
    what is owned but not carried. The containers are built BEFORE their
    contents are placed because a row inside a bag names its container by
    the container's own item guid, which is only known once the bag slot has
    been read.
    """
    equipped: list[dict] = []
    containers: list[dict] = []
    by_guid: dict[int, dict] = {}
    bank_bags: set[int] = set()
    inside: list[dict] = []
    elsewhere = 0

    backpack = _container(BACKPACK, 0, BACKPACK_SLOTS, BACKPACK_NAME, None, icons)
    containers.append(backpack)

    for row in sorted(rows, key=lambda r: (r["bag"], r["slot"])):
        if row["bag"] != 0:
            inside.append(row)
            continue
        slot = row["slot"]
        if slot < len(EQUIPPED_SLOTS):
            equipped.append(item_payload(row, icons, EQUIPPED, EQUIPPED_SLOTS[slot],
                                         slot))
        elif slot in _BAG_SLOTS:
            position = slot - _BAG_SLOTS.start + 1
            bag = _container("bag%d" % position, position,
                             int(row.get("container_slots") or 0),
                             item_name(row), row, icons)
            containers.append(bag)
            by_guid[row["item_guid"]] = bag
        elif slot in _BACKPACK_SLOTS:
            backpack["items"].append(
                item_payload(row, icons, CARRIED, BACKPACK_NAME,
                             slot - _BACKPACK_SLOTS.start))
        elif slot in _BANK_BAG_SLOTS:
            # The bank bag itself is furniture, not cargo. Its guid is kept
            # so its CONTENTS land in the elsewhere count rather than being
            # mistaken for a carried bag nobody can find.
            bank_bags.add(row["item_guid"])
            elsewhere += 1
        else:
            # Bank slots, keyring, buyback: real possessions this view does
            # not draw. Counted so the page never silently understates what
            # somebody owns.
            elsewhere += 1

    for row in inside:
        bag = by_guid.get(row["bag"])
        if bag is None:
            elsewhere += 1   # inside a bank bag, or a container not carried
            continue
        bag["items"].append(item_payload(row, icons, CARRIED, bag["name"], row["slot"]))

    for bag in containers:
        bag["items"].sort(key=lambda i: i["position"])
        bag["used"] = len(bag["items"])
        # A bag holding more than its template says it can is a template the
        # world database and the core disagree about. Never report negative
        # free space: it reads as a rendering bug rather than as the data
        # problem it is, and the used count already says what is true.
        bag["free"] = max(0, bag["slots"] - bag["used"])
    return {"equipped": equipped, "containers": containers, "elsewhere": elsewhere,
            "bank_bags": len(bank_bags)}


def build_capacity(containers: list[dict]) -> dict:
    """How much room there is, how much is left, and how many bags there are.

    `empty_bag_slots` is the actionable half of a full inventory: three empty
    bag slots on a character with nothing to put in them is a different
    problem from four full bags, and the two want different answers (find him
    a bag, versus sell something).
    """
    bags = [c for c in containers if c["key"] != BACKPACK]
    slots = sum(c["slots"] for c in containers)
    used = sum(c["used"] for c in containers)
    return {
        "slots": slots,
        "used": used,
        "free": max(0, slots - used),
        "bags": len(bags),
        "bag_slots": BAG_POSITIONS,
        "empty_bag_slots": max(0, BAG_POSITIONS - len(bags)),
        "full": used >= slots,
    }


def tally(items: list[dict]) -> dict:
    """Vendor value and a quality breakdown over any list of item payloads.

    The breakdown is ordered best first, which is the order a person reads
    it in: "one rare, fifteen greens" answers the question, "fifteen greens,
    one rare" makes them look for the number that matters.
    """
    counts: dict[int, int] = {}
    unknown = 0
    value = 0
    stacked = 0
    for item in items:
        quality = known_quality(item["quality"])
        if quality is None:
            unknown += 1
        else:
            counts[quality] = counts.get(quality, 0) + 1
        value += item["value_copper"]
        stacked += item["count"]
    by_quality = [{"quality": q, "name": quality_name(q), "count": n}
                  for q, n in sorted(counts.items(), reverse=True)]
    if unknown:
        by_quality.append({"quality": None, "name": UNKNOWN_QUALITY, "count": unknown})
    return {
        "items": len(items),
        # Stacks are the slot count; `units` is what is actually in them. A
        # bag holding one stack of twenty linen is one slot and twenty items,
        # and saying "1 item" about it is as wrong as saying "20 slots".
        "units": stacked,
        "vendor": coins(value),
        "vendor_copper": value,
        "by_quality": by_quality,
        "notable": sum(n for q, n in counts.items() if q >= NOTABLE_QUALITY),
        "rare_or_better": sum(n for q, n in counts.items() if q >= RARE_QUALITY),
    }


def notable_items(items: list[dict], minimum: int = NOTABLE_QUALITY) -> list[dict]:
    """Green and better, best first, then most valuable first.

    Ties broken by name so the list is stable poll to poll: a list that
    reshuffles itself every thirty seconds is a list nobody can read on a
    phone.
    """
    picked = [i for i in items if at_least(i["quality"], minimum)]
    picked.sort(key=lambda i: (-i["quality"], -i["value_copper"], i["name"]))
    return picked


def worth_naming(equipped: list[dict], carried: list[dict]) -> list[dict]:
    """The items that earn a line of their own, best first.

    Green or better in a BAG, plus rare or better anywhere. Not simply
    "green or better anywhere", which was the first cut and produced a list
    of twenty-nine items per character on the live realm: at these levels a
    worn green is ordinary, there are a hundred and ten of them across the
    five, and every one is already drawn life size on the paper doll
    directly above this view. Naming them all buried the eleven rares, which
    are the actual finding.

    A worn RARE still earns its line. "Who has the good gear" is a question
    this list gets asked, and the paper doll answers it one character at a
    time; and a rare in a bag next to a rare on a body is exactly the
    comparison somebody is trying to make.
    """
    notable_worn = [i for i in equipped if at_least(i["quality"], RARE_QUALITY)]
    return notable_items(carried + notable_worn)


def build_member(name: str, char_row: dict | None, inventory_rows: list[dict],
                 icons: dict[int, str]) -> dict:
    """One member's purse, containers and holdings.

    A member with no `characters` row still gets an entry. A family view that
    quietly drops somebody is the exact failure the Armory tab was built to
    stop, and it is no less a failure here.
    """
    bond = bonds.FAMILY[name]
    if char_row is None:
        return {
            "name": name,
            "role": bond.role,
            "class": bond.char_class.title(),
            "present": False,
        }
    split = split_inventory(inventory_rows, icons)
    carried = [i for bag in split["containers"] for i in bag["items"]]
    held = split["equipped"] + carried
    class_id = char_row.get("class")
    return {
        "name": char_row["name"],
        "role": bond.role,
        "present": True,
        "level": char_row.get("level"),
        "class": _CLASS_NAMES.get(class_id, "class %s" % class_id),
        "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
        "money": coins(char_row.get("money")),
        "containers": split["containers"],
        "capacity": build_capacity(split["containers"]),
        # Two tallies on purpose. `carried` is the money story - what a trip
        # to a vendor is worth and what is clogging the bags. `held` is the
        # inventory story - everything the character owns on their person,
        # worn included, which is the only honest denominator for "how many
        # rares does this family have".
        "carried": tally(carried),
        "held": tally(held),
        "notable": worth_naming(split["equipped"], carried),
        "elsewhere": split["elsewhere"],
    }


def build_family(members: list[dict]) -> dict:
    """The five added up, plus the one line that says whether this is a problem."""
    present = [m for m in members if m["present"]]
    money = sum(m["money"]["total"] for m in present)
    vendor = sum(m["carried"]["vendor_copper"] for m in present)
    slots = sum(m["capacity"]["slots"] for m in present)
    used = sum(m["capacity"]["used"] for m in present)
    counts: dict[int, int] = {}
    for member in present:
        for entry in member["held"]["by_quality"]:
            if entry["quality"] is None:
                continue
            counts[entry["quality"]] = counts.get(entry["quality"], 0) + entry["count"]
    richest = max(present, key=lambda m: m["money"]["total"], default=None)
    return {
        "present": len(present),
        "money": coins(money),
        "vendor": coins(vendor),
        "capacity": {
            "slots": slots, "used": used, "free": max(0, slots - used),
            "bags": sum(m["capacity"]["bags"] for m in present),
            "empty_bag_slots": sum(m["capacity"]["empty_bag_slots"] for m in present),
        },
        "by_quality": [{"quality": q, "name": quality_name(q), "count": n}
                       for q, n in sorted(counts.items(), reverse=True)],
        "rare_or_better": sum(n for q, n in counts.items() if q >= RARE_QUALITY),
        # Named rather than merely counted: "who has money" is a question
        # with an answer, and the answer is a person.
        "richest": richest["name"] if richest else None,
        # WHO IS OUT OF ROOM. The headline finding the day this landed, and
        # the one thing on this view that a person can act on within the
        # hour. A list, not a count, because the fix is per character.
        "full": [m["name"] for m in present if m["capacity"]["full"]],
    }


def auction_payload(row: dict, roster: set[str], icons: dict[int, str]) -> dict:
    """One `auctionhouse` row, as the page draws it.

    `time` is the expiry as a unix timestamp and is passed through rather
    than turned into "4 hours left" here: this module has no clock, and a
    pure function that reads one would be untestable for the sake of a
    phrase the page can build itself.
    """
    owner, buyer = row.get("owner_name"), row.get("buyer_name")
    item = item_payload(dict(row, slot=0), icons, CARRIED, None)
    return {
        "id": row["id"],
        "item": item,
        "owner": owner,
        "buyer": buyer,
        "ours": owner in roster,
        "we_bid": buyer in roster,
        # startbid is what it was listed at, lastbid the highest bid so far
        # (0 when nobody has bid), buyout 0 when there is no buyout price.
        "start": coins(row.get("startbid")),
        "bid": coins(row.get("lastbid")),
        "buyout": coins(row.get("buyoutprice")),
        "deposit": coins(row.get("deposit")),
        "has_bid": bool(row.get("lastbid")),
        "expires_at": row.get("time"),
    }


def build_auctions(auction_rows: list[dict], icons: dict[int, str]) -> dict:
    """The family's auction house activity, and what the table cannot say.

    THREE LISTS, AND ONE OF THEM IS A HALF-TRUTH THAT SAYS SO. `auctionhouse`
    holds LIVE auctions only: the core deletes the row the moment an auction
    completes and mails the gold to the seller, so there is no sales history
    in this database to read and none is invented here. `sold` is therefore
    the closest honest thing the table holds - their own listings that
    already have a winning bidder, money in flight - and `tracked` is False
    to tell the page to say so rather than let an empty list read as "nothing
    has ever sold".

    As of this landing nothing in the module lists, bids or buys anything
    (quadseven/mod-overseer#147), so all three lists are empty on the live
    realm. That is a fact about the module, not a failure of this query, and
    the page is expected to say which.
    """
    roster = set(family.roster())
    rows = [auction_payload(r, roster, icons) for r in auction_rows]
    listings = [r for r in rows if r["ours"]]
    return {
        "listings": listings,
        "sold": [r for r in listings if r["has_bid"]],
        "bids": [r for r in rows if r["we_bid"] and not r["ours"]],
        "any": bool(rows),
        # The page's empty state hangs off this: completed sales are not
        # recorded anywhere in acore_characters, so "no sales" here means
        # "nothing is mid-sale", never "nothing has ever sold".
        "tracked": False,
        "ticket": AUCTION_TICKET,
    }


def build_wealth(char_rows: list[dict], inventory_rows: list[dict],
                 auction_rows: list[dict], icons: dict[int, str]) -> dict:
    """Every member's purse and bags, the family total, and the auction house.

    The row lists arrive keyed by character name, unfiltered, exactly as
    build_armory takes them; splitting them per member is this module's job
    so the adapter stays a handful of queries and no logic.
    """
    chars = {r["name"]: r for r in char_rows}
    inventory: dict[str, list[dict]] = {}
    for row in inventory_rows:
        inventory.setdefault(row["name"], []).append(row)
    members = [build_member(name, chars.get(name), inventory.get(name, []), icons)
               for name in family.roster()]
    return {
        "members": members,
        "family": build_family(members),
        "auctions": build_auctions(auction_rows, icons),
        "expected": len(members),
    }
