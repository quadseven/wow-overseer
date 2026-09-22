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

  3. THERE IS NO GUILD, SO THERE IS NO GUILD BANK, and drawing an empty vault
     on the strength of that is the same mistake as drawing a blank auction
     panel. What is worth a reader's time is the ROAD to one: travel to a
     petitioner and to a guild banker both work, and buying a charter,
     collecting signatures, registering, depositing and withdrawing are not
     written (infra#2831). Whether a guild exists is asked of the database
     rather than assumed, so the sentence stops being drawn the day one does.

Same seam rule as map_core, panel, family and armory (infra#2597): the HTTP
adapter fetches rows and does nothing else. Every judgement here - what
counts as carried, what "full" means, which items are worth naming, what the
auction table can and cannot honestly say - lives in this module where the
stdlib suite can reach it without a database.

AND SO DOES EVERY WORD ON THE PAGE. The redesign made Bags its own tab, and
the rewrite that came with it moved the last of the judgement out of
index.html: the headline finding, the labels on the stat strip, when a bag
meter turns amber, the word for an empty purse, and the reason each empty
panel is empty were all composed in JavaScript, where no test could reach
them. They are composed here now, from the payload they describe, and the
page turns a `tone` into a class name and draws what it is handed. The rule
of thumb that keeps it that way: if a string would be read by a person, it is
built in this module; if it is a class name or a pixel, it is the page's.

Tickets: quadseven/mod-overseer#88, quadseven/mod-overseer#147, infra#2597,
infra#2831.
"""
from __future__ import annotations

import armory
import bagfate
import bonds
import family
from armory import (
    ARMOR_SUBCLASSES, CLASS_COLOURS, EQUIPPED_SLOTS, ITEM_CLASS_ARMOR,
    ITEM_CLASS_WEAPON, QUALITY_NAMES, UNKNOWN_QUALITY, WEAPON_SUBCLASSES,
)
from core import _ALLIANCE_RACES, _HORDE_RACES
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

# What the notable list calls a worn item. Its opposite is not a constant: an
# item that is not worn is named by the container it sits in, which is the
# more useful half of the answer. See place_tone() for why one of the two is
# drawn in amber and the other is not.
PLACE_WORN = "worn"

# --- how loud a fact is drawn ----------------------------------------------
# THE PAGE PICKS NO COLOURS. A full bag is vermilion and an empty bag position
# is amber because those two facts mean different things and want different
# fixes - sell something, versus find him a bag - and which of those a number
# is is a judgement about the data, not about the stylesheet. So everything
# this module composes carries the tone it should be drawn in, and index.html
# turns a tone into a class name and does nothing else with it (infra#2597).
ALARM = "alarm"       # vermilion: this is stopping a character from playing
CAUTION = "caution"   # amber: worth acting on, and nobody is stuck yet
GOOD = "good"         # green: worth noticing, nothing to do
PLAIN = ""            # a fact with no verdict attached

# The word for an empty purse, an unsellable stack and a section with no rows
# in it. One word, in one place, because "nothing" and "none" and "0c" drawn
# on the same card for the same condition is how a panel starts looking like
# three different panels.
NOTHING = "nothing"
NONE = "none"

# A COUNT READS AS A WORD IN A SENTENCE AND AS A DIGIT IN A READOUT. "One free
# slot in the whole family" is the finding; "1 of 190" is the number under it,
# and the number is set in the mono face precisely so it can be scanned rather
# than read. Anything past ten is a digit in both, because nobody reads "one
# hundred and eighty-nine" faster than they read 189.
NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten")


def spell(count: int) -> str:
    """A small count as the word for it, so a sentence reads as a sentence."""
    if 0 <= count < len(NUMBER_WORDS):
        return NUMBER_WORDS[count]
    return str(count)


def plural(count: int, one: str, many: str | None = None) -> str:
    """'1 bag', '3 bags', and the irregulars spelled out where they occur.

    Worth a function rather than an inline ternary for one reason: a sentence
    that says "1 bags" reads as a bug in the number, not in the grammar, and
    somebody goes looking for the wrong thing.
    """
    return one if count == 1 else (many if many is not None else one + "s")


def sentence(text: str) -> str:
    """First letter up.

    Capitalised at the END of composition on purpose. A lead reads "one free
    slot in the whole family", and the first word is a COUNT that changes with
    the data; capitalising the fragment as it is built means one branch says
    "One" and the next says "no", which is exactly the sort of difference
    nobody notices in review.
    """
    return text[:1].upper() + text[1:]


def coins(copper: int | None) -> dict:
    """Copper -> the three coins, ALWAYS a dict, and the words for them.

    armory.money() returns None for nothing, which is right for a tooltip
    line that should not be drawn at all. Here nothing is a real answer -
    "this stack is worth nothing to a vendor" is exactly what a quest item
    is - so zero renders as zero and the page decides whether to draw it.

    A negative purse is not a state `characters.money` can hold (it is an
    unsigned column), so a negative reads as zero rather than as three
    negative coins that would look like a rendering bug.

    `text` IS PART OF THE ANSWER, not a convenience. The page draws money in
    three coloured spans when it has room and as one string when it does not
    (a tooltip line, a stat note), and the second form used to be built in
    JavaScript - which meant the word for an empty purse was typed into
    index.html, where nothing tests it and it can disagree with this module
    about whether zero copper is "nothing", "0c" or a blank space.
    """
    total = int(copper or 0)
    if total < 0:
        total = 0
    gold = total // COPPER_PER_GOLD
    silver = total // COPPER_PER_SILVER % SILVER_PER_GOLD
    remainder = total % COPPER_PER_SILVER
    bits = []
    if gold:
        bits.append("%dg" % gold)
    # Silver is drawn whenever gold is, so "1g 0s 4c" reads as one amount
    # rather than as a gold piece and four coppers that lost something.
    if gold or silver:
        bits.append("%ds" % silver)
    bits.append("%dc" % remainder)
    return {
        "gold": gold,
        "silver": silver,
        "copper": remainder,
        "total": total,
        "text": " ".join(bits) if total else NOTHING,
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


def stack_label(payload: dict) -> str:
    """'Linen Cloth', or 'Linen Cloth x20'.

    One place decides whether a stack count is drawn and how, because the same
    name is written on a bag square, in the notable list and on an auction
    row, and three copies of `count > 1 ? " x" + count : ""` is three chances
    for one of them to start saying "x1".
    """
    count = payload["count"]
    return payload["name"] + (" x%d" % count if count > 1 else "")


def place_label(where: str, container: str | None) -> str | None:
    """'worn', or 'in Backpack'. The half of the notable list that is a verdict.

    "Why is that rare sitting in a bag" is the question this list gets scanned
    for, so WHERE a thing is has to be a word on the row rather than something
    the reader infers from a colour. The container's name comes from the
    container, so the label under a bag and the label on a notable item inside
    it can never disagree about what that bag is called.
    """
    if where == EQUIPPED:
        return PLACE_WORN
    return "in %s" % container if container else None


def place_tone(where: str, container: str | None) -> str:
    """A bagged item is drawn in amber and a worn one is not.

    Not decoration. An item being WORN is an item where it belongs; the same
    item loose in a bag is a spare, a mistake, or gold nobody has banked. Only
    one of those two states is worth an eye, so only one of them is coloured.
    """
    if where == EQUIPPED:
        return PLAIN
    return CAUTION if container else PLAIN


def item_tip(payload: dict) -> str:
    """The lines the game's own tooltip would carry, as one string.

    A real tooltip card is the Armory's, and it is built from stats this view
    does not fetch; borrowing it would mean fetching every carried item's
    stats in order to draw a bag grid, which is a hundred times the data for
    a picture. So the page hangs this on a title attribute instead - and it is
    composed HERE because "no vendor value" is a sentence about what a
    SellPrice of 0 means, which is the same judgement stack_value() makes.
    """
    facts = [payload["quality_name"]]
    if payload["kind"]:
        facts.append(payload["kind"])
    if payload["item_level"]:
        facts.append("item level %d" % payload["item_level"])
    worth = ("vendor " + payload["value"]["text"] if payload["sell_price"]
             else "no vendor value")
    return "%s (%s) %s" % (payload["stack"], ", ".join(facts), worth)


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
    payload = {
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
    payload["stack"] = stack_label(payload)
    payload["place"] = place_label(where, container)
    payload["place_tone"] = place_tone(where, container)
    payload["tip"] = item_tip(payload)
    return payload


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
    # The RAW rows behind `equipped` and every container's items, for
    # bagfate: the gear check wants template columns the page never draws.
    worn_rows: list[dict] = []
    carried_rows: list[dict] = []
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
            worn_rows.append(row)
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
            carried_rows.append(row)
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
        carried_rows.append(row)
        bag["items"].append(item_payload(row, icons, CARRIED, bag["name"], row["slot"]))

    for bag in containers:
        bag["items"].sort(key=lambda i: i["position"])
        bag["used"] = len(bag["items"])
        # A bag holding more than its template says it can is a template the
        # world database and the core disagree about. Never report negative
        # free space: it reads as a rendering bug rather than as the data
        # problem it is, and the used count already says what is true.
        bag["free"] = max(0, bag["slots"] - bag["used"])
        bag["full"] = bag["slots"] > 0 and bag["used"] >= bag["slots"]
        bag["tone"] = ALARM if bag["full"] else PLAIN
        # A CONTAINER OF UNKNOWN SIZE SAYS SO. ContainerSlots comes from the
        # world database through a LEFT JOIN, so a custom or removed bag
        # arrives with no size at all - and "3 of 0" reads as a broken count
        # rather than as the missing template it is. The grid has nothing to
        # draw in that case either; the items still land in the spill row the
        # page keeps for exactly this.
        bag["room_label"] = ("%d of %d" % (bag["used"], bag["slots"])
                             if bag["slots"]
                             else "%d carried, size unknown" % bag["used"])
    return {"equipped": equipped, "containers": containers, "elsewhere": elsewhere,
            "bank_bags": len(bank_bags),
            "worn_rows": worn_rows, "carried_rows": carried_rows}


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


# NINETY PER CENT, AND IT USED TO LIVE IN THE PAGE. The bar under each purse
# went amber near the top of its range and red at it, and that ternary was
# written in JavaScript where no test could reach it: the threshold that
# decides whether a person is warned about a bag is a judgement about bags.
# Ninety rather than eighty because at these levels a single dungeon run is
# four or five slots, and a warning that fires with a fifth of the bag still
# empty is a warning that gets ignored on the day it is true.
TIGHT_PERCENT = 90

# The sentence that turns an empty bag position from a number into a job.
SPARE_NOTE = ("An empty bag position is a bag somebody could hand him, which "
              "is a different fix from selling something.")

# What the notable list is, said once above it rather than guessed at.
NOTABLE_NOTE = "green or better in a bag, rares anywhere"

# A member with no `characters` row. Still a card, still a sentence: a family
# view that quietly drops somebody is the exact failure the Armory tab was
# built to stop, and a card stripped to a name is how a missing character
# stops being noticed.
ABSENT_NOTE = "no saved character - deleted, or never made."


def money_sentence(before: str, money: dict, after: str = "") -> dict:
    """A sentence with an amount of money in the middle of it.

    The page draws money as three coloured spans, so an amount cannot simply
    be interpolated into a string the way a count can. The words either side
    of it still belong here, so they travel as the two halves they are and
    index.html appends the coins between them.
    """
    return {"before": before, "money": money, "after": after}


def build_room(capacity: dict) -> dict:
    """How full one character is, as the words and the tone to draw them in.

    THE BAR IS THE POINT OF THE CARD. Everything else here is a number that
    can wait; this is the one that stops a character playing, so it carries a
    percentage for the bar, a tone for its colour, and the three phrases that
    say the same thing for a reader who cannot see the colour at all.
    """
    slots, used, free = capacity["slots"], capacity["used"], capacity["free"]
    percent = round(used * 100 / slots) if slots else 0
    if capacity["full"]:
        tone = ALARM
    elif percent >= TIGHT_PERCENT:
        tone = CAUTION
    else:
        tone = PLAIN
    bags = capacity["bags"]
    spare = capacity["empty_bag_slots"]
    return {
        "percent": percent,
        "tone": tone,
        "used_label": "%d of %d slots used" % (used, slots),
        # "no room left" rather than "0 free". Zero is a number a reader has
        # to interpret, and this is the state the whole view exists to report.
        "free_label": "%d free" % free if free else "no room left",
        "free_tone": PLAIN if free else ALARM,
        "bags_label": ("across %d %s and the backpack"
                       % (bags, plural(bags, "bag")) if bags
                       else "the backpack alone, no bags carried"),
        "spare_label": ("%d empty bag %s" % (spare, plural(spare, "position"))
                        if spare else None),
        "spare_tone": CAUTION if spare else PLAIN,
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
    by_quality = [{"quality": q, "name": quality_name(q), "count": n,
                   "label": "%d %s" % (n, quality_name(q))}
                  for q, n in sorted(counts.items(), reverse=True)]
    if unknown:
        by_quality.append({"quality": None, "name": UNKNOWN_QUALITY,
                           "count": unknown,
                           "label": "%d %s" % (unknown, UNKNOWN_QUALITY)})
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
                 icons: dict[int, str], claims: dict[int, str] | None = None,
                 managed: bool = True, split: dict | None = None) -> dict:
    """One member's purse, containers and holdings.

    A member with no `characters` row still gets an entry. A family view that
    quietly drops somebody is the exact failure the Armory tab was built to
    stop, and it is no less a failure here.
    """
    # bonds knows one family. A Horde member has no bond and no family role,
    # which is not an error: its line says level and class, and nothing more.
    bond = bonds.FAMILY.get(name)
    if char_row is None:
        klass = bond.char_class.title() if bond else "unknown class"
        return {
            "name": name,
            "role": bond.role if bond else None,
            "class": klass,
            "present": False,
            "who": "%s - %s" % (klass, bond.role) if bond else klass,
            "absent_note": ABSENT_NOTE,
        }
    # Handed in when the caller has already split these rows (build_wealth
    # does, for the gear check), so the piles and the tallies read one split.
    if split is None:
        split = split_inventory(inventory_rows, icons)
    carried = [i for bag in split["containers"] for i in bag["items"]]
    held = split["equipped"] + carried
    class_id = char_row.get("class")
    race = char_row.get("race")
    member = {
        "name": char_row["name"],
        "role": bond.role if bond else None,
        "present": True,
        "faction": ("alliance" if race in _ALLIANCE_RACES
                    else "horde" if race in _HORDE_RACES else "neutral"),
        "guild": char_row.get("guild"),
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
    member["who"] = ("%s %s - %s" % (char_row.get("level"), member["class"],
                                     member["role"]) if member["role"]
                     else "%s %s" % (char_row.get("level"), member["class"]))
    member["room"] = build_room(member["capacity"])
    stacks, units = member["carried"]["items"], member["carried"]["units"]
    # STACKS AND ITEMS ARE DIFFERENT NUMBERS AND BOTH ARE SAID. A bag holding
    # one stack of twenty linen is one slot and twenty things, and a line
    # that reports either number alone is wrong about the other one.
    member["holding"] = money_sentence(
        "carrying %d %s (%d items), worth "
        % (stacks, plural(stacks, "stack"), units),
        member["carried"]["vendor"], " at a vendor")
    member["elsewhere_note"] = (
        "%d more stored elsewhere (bank, keyring), not drawn here"
        % member["elsewhere"] if member["elsewhere"] else None)
    member["notable_note"] = NOTABLE_NOTE if member["notable"] else None
    # WHERE IT IS ALL GOING (#88): each carried stack in one pile, and what
    # stops the piles that go nowhere. bagfate says why these are the
    # pipeline's own rules rather than a second opinion.
    member["fates"] = bagfate.build_fates(
        member["name"], split["carried_rows"], claims or {},
        member["capacity"]["free"], managed)
    return member


# --- the finding this view opens with --------------------------------------
# THE PAGE OPENS WITH A SENTENCE, NOT A CHART. The first cut of the Bags view
# opened with a strip of numbers, and a strip of numbers is something a reader
# has to interpret before it can tell them anything: "189/190" is only alarming
# once you have worked out that the second number is the first one plus one.
# So the top of the view is one composed finding, and everything under it is
# the evidence for it.
#
# EVERY WORD OF IT IS BUILT HERE, from the live payload, because the finding is
# a verdict. The day the family buys four bags each it has to start saying
# something else on its own, and a sentence typed into index.html would go on
# saying "one free slot in the whole family" until somebody noticed.

# What a full inventory actually does, which is the half nobody guesses. This
# is not "your bags are full", it is "this character has stopped questing":
# `LootObject::IsLootPossible` never asks whether the bot has room, so the loot
# can never complete, the loot goal outranks questing, and the character stands
# there re-trying it (infra#2800). Deliberately not naming which of them it was
# measured on: who it happened to is in bonds, and a name typed into a sentence
# here is a second roster that can disagree with the first one.
FULL_CONSEQUENCE = (
    "A bot with no room can never finish a loot, so the loot goal preempts "
    "questing forever: that is how one of them held a single position to "
    "within 0.1 yard for eight and a half hours.")
TIGHT_CONSEQUENCE = (
    "One good drop takes the last of it, and a character with no room stops "
    "questing rather than skipping the loot it cannot carry.")
ROOMY_CONSEQUENCE = (
    "Nobody is about to stall on a loot they have no room for, which is the "
    "one thing a full bag does to a character on this realm.")
NO_CHARACTERS = (
    "Purses and bags are read off saved characters, so there is nothing here "
    "to be full or empty.")
NO_BAGS = (
    "Every character is born with a backpack, so a family with no slots at "
    "all is a query that answered, not a family that owns nothing.")

# UNDER ONE BACKPACK OF ROOM LEFT, ACROSS ALL FIVE, is where this stops being
# comfortable. A PERCENTAGE was the obvious rule and it is the wrong one: five
# per cent of 190 slots is nine slots, and nine slots is one quest turn-in away
# from nothing. A backpack is a real unit of room on this realm, so the
# threshold is one of them - taken from panel's own range rather than typed as
# a number, so it moves if the backpack ever does.
FAMILY_TIGHT_SLOTS = BACKPACK_SLOTS


def build_finding(totals: dict) -> dict:
    """The one sentence at the top of the view, and how loudly to draw it.

    Six states, and THE ORDER THEY ARE TESTED IN IS THE FINDING. "One free
    slot in the whole family" outranks "four of the five are out of room" even
    though both are true at the same moment, because the first is the more
    surprising fact and the reader has half a second. Two of the six are about
    the data rather than about the family, and they come first for the same
    reason: "no free slot anywhere" is TRUE of an empty realm and completely
    misleading about it.
    """
    cap = totals["capacity"]
    slots, used, free = cap["slots"], cap["used"], cap["free"]
    full = totals["full"]
    present = totals["present"]
    who = ("out of room: " + ", ".join(full)) if full else None
    if not present:
        return {"lead": "Nobody has a saved character",
                "detail": "Not one of the roster has a row in the world's "
                          "character table.",
                "because": NO_CHARACTERS, "tone": ALARM, "who": [],
                "who_label": None}
    if not slots:
        return {"lead": "No bags and no backpack",
                "detail": "%s saved %s, and not one carried slot between them."
                          % (sentence(spell(present)),
                             plural(present, "character")),
                "because": NO_BAGS, "tone": ALARM, "who": [], "who_label": None}
    if free == 0:
        lead, tone, because = ("No free slot anywhere in the family", ALARM,
                               FULL_CONSEQUENCE)
    elif free <= FAMILY_TIGHT_SLOTS:
        # Alarm rather than caution when somebody is ALREADY stuck: a family
        # with ten slots left and nobody full is tight, and a family with one
        # slot left and four characters full is a fault being reported.
        lead = "%s free %s in the whole family" % (spell(free),
                                                   plural(free, "slot"))
        tone = ALARM if full else CAUTION
        because = FULL_CONSEQUENCE if full else TIGHT_CONSEQUENCE
    elif full:
        lead = "%s of the %s %s out of room" % (
            spell(len(full)), spell(present), "is" if len(full) == 1 else "are")
        tone, because = ALARM, FULL_CONSEQUENCE
    else:
        lead = "%s free %s across the family" % (spell(free),
                                                 plural(free, "slot"))
        tone, because = PLAIN, ROOMY_CONSEQUENCE
    return {
        "lead": sentence(lead),
        "detail": "%d of %d slots taken." % (used, slots),
        "because": because,
        "tone": tone,
        "who": list(full),
        "who_label": who,
    }


def stat(label: str, value: str | None = None, money: dict | None = None,
         note: str | None = None, tone: str = PLAIN) -> dict:
    """One reading in the strip under the finding.

    Either a `value` (a string, already counted and pluralised here) or an
    amount of `money` the page draws in the three coins, never both.
    """
    return {"label": label, "value": value, "money": money, "note": note,
            "tone": tone}


def build_stats(totals: dict) -> list[dict]:
    """The strip under the finding: the same seven readings, always.

    ALWAYS SEVEN, INCLUDING THE ZEROES. A strip that drops a reading when it
    is zero changes shape as the data changes, so the reader loses the one
    thing a strip is good for - knowing where to look without reading. "0
    empty bag positions" is also a fact worth having on the screen: it is
    half of the answer to "so is this a bag problem or a selling problem".
    """
    cap = totals["capacity"]
    present, free, used = totals["present"], cap["free"], cap["slots"]
    spare, rares = cap["empty_bag_slots"], totals["rare_or_better"]
    positions = present * BAG_POSITIONS
    stats = [
        stat("purse", money=totals["money"],
             note="across %d %s" % (present, plural(present, "purse"))),
        stat("carried goods", money=totals["vendor"],
             note="what a vendor would pay"),
        stat("slots", value="%d of %d" % (cap["used"], used), note="taken",
             tone=ALARM if not free else
             (CAUTION if free <= FAMILY_TIGHT_SLOTS else PLAIN)),
        stat("bags", value="%d of %d" % (cap["bags"], positions),
             note="bag positions filled",
             tone=CAUTION if spare else PLAIN),
        stat("empty bag positions", value=str(spare),
             note="waiting for a bag", tone=CAUTION if spare else PLAIN),
        stat("rare or better", value=str(rares), note="worn or carried",
             tone=GOOD if rares else PLAIN),
    ]
    # Named rather than merely counted, and last because it is the one reading
    # here that nobody has to act on.
    stats.append(stat("richest", value=totals["richest"] or NOTHING,
                      note="the biggest purse"))
    return stats


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
    totals = {
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
    totals["finding"] = build_finding(totals)
    totals["stats"] = build_stats(totals)
    totals["spare_note"] = (SPARE_NOTE if totals["capacity"]["empty_bag_slots"]
                            else None)
    return totals


def auction_payload(row: dict, roster: set[str], icons: dict[int, str]) -> dict:
    """One `auctionhouse` row, as the page draws it.

    `time` is the expiry as a unix timestamp and is passed through rather
    than turned into "4 hours left" here: this module has no clock, and a
    pure function that reads one would be untestable for the sake of a
    phrase the page can build itself.
    """
    owner, buyer = row.get("owner_name"), row.get("buyer_name")
    item = item_payload(dict(row, slot=0), icons, CARRIED, None)
    ours = owner in roster
    has_bid = bool(row.get("lastbid"))
    return {
        "id": row["id"],
        "item": item,
        "owner": owner,
        "buyer": buyer,
        "ours": ours,
        "we_bid": buyer in roster,
        # WHOSE AUCTION THIS IS, in words. `ours` is a boolean the page would
        # otherwise have to turn into a sentence, and "seller unknown" is a
        # real state: `itemowner` is a guid and the character behind it can
        # have been deleted since the auction was posted.
        "who_label": ("listed by %s" % owner if ours
                      else "seller %s" % (owner or "unknown")),
        # A listing with no bid on it has a STARTING price, not a highest
        # one, and drawing the start under the word "highest bid" would be
        # this panel inventing a bidder.
        "bid_label": "highest bid" if has_bid else "starting bid",
        "buyout_label": "buyout" if row.get("buyoutprice") else None,
        "winner_label": "winning: %s" % buyer if buyer else None,
        # The date itself is formatted by the page in the reader's own locale.
        # This module has no clock, and a pure function that read one would be
        # untestable for the sake of a phrase.
        "expires_label": "expires" if row.get("time") else None,
        # startbid is what it was listed at, lastbid the highest bid so far
        # (0 when nobody has bid), buyout 0 when there is no buyout price.
        "start": coins(row.get("startbid")),
        "bid": coins(row.get("lastbid")),
        "buyout": coins(row.get("buyoutprice")),
        "deposit": coins(row.get("deposit")),
        "has_bid": has_bid,
        "expires_at": row.get("time"),
    }


def linked_sentence(before: str, ticket: dict, after: str = ".") -> dict:
    """A sentence with a ticket link in the middle of it.

    The same shape as money_sentence and for the same reason: the page has to
    build an anchor, so the sentence arrives as the two halves either side of
    it. Both halves are words, so both halves are here - a panel that says
    "is still open" needs the module that knows what is still open to have
    written it.
    """
    return {"before": before, "ticket": ticket, "after": after}


# THE EMPTY STATE IS THE PANEL. Nothing in the module lists, buys, bids or
# sells (quadseven/mod-overseer#147), so an empty auction house is the CORRECT
# reading of the table - and a blank box and a broken query look identical. So
# the panel says which of the two it is, in as many words, and names the open
# ticket rather than leaving a reader to wonder whether anybody knows.
AUCTION_EMPTY_LEAD = "Nothing listed, nothing sold, nothing bid on."
AUCTION_EMPTY_BODY = (
    "The auction house table holds no row belonging to any of them, and that "
    "is an empty auction house rather than an empty panel.")
# The second thing the table structurally cannot say, and it does not go away
# the day the family starts trading: the core DELETES an auction the moment it
# completes and mails the gold to the seller, so `sold` can only ever mean
# "mid-sale" and an empty one can never honestly read as "nothing has ever
# sold".
AUCTION_CAVEAT = (
    "Completed sales leave no trace to read: the core deletes an auction the "
    "moment it finishes and mails the gold, so this table can only ever show "
    "live auctions.")


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
    sold = [r for r in listings if r["has_bid"]]
    bids = [r for r in rows if r["we_bid"] and not r["ours"]]
    return {
        "listings": listings,
        "sold": sold,
        "bids": bids,
        "any": bool(rows),
        # The three lists as the page draws them, labels included, so adding a
        # fourth is a change here rather than a change in two places.
        "sections": [
            {"label": "listed by the family", "rows": listings,
             "count": len(listings), "empty": NONE},
            {"label": "sold, gold in the post", "rows": sold,
             "count": len(sold), "empty": NONE},
            {"label": "bid on by the family", "rows": bids,
             "count": len(bids), "empty": NONE},
        ],
        "empty": {
            "lead": AUCTION_EMPTY_LEAD,
            "body": AUCTION_EMPTY_BODY,
            "why": linked_sentence(
                "No part of the module lists, buys, bids or sells anything "
                "yet: ", AUCTION_TICKET, " is still open."),
        },
        "caveat": AUCTION_CAVEAT,
        # The page's empty state hangs off this: completed sales are not
        # recorded anywhere in acore_characters, so "no sales" here means
        # "nothing is mid-sale", never "nothing has ever sold".
        "tracked": False,
        "ticket": AUCTION_TICKET,
    }


# --- the guild bank there is not (infra#2831) ------------------------------
# THERE IS NO GUILD, SO THERE IS NO GUILD BANK, and an empty vault drawn on the
# strength of that would be the same mistake the auction panel exists to avoid:
# a blank box and a broken query look identical. What is actually useful to a
# reader is not the empty vault, it is the ROAD to one - which parts of it the
# module can already drive and which are not written - because that is the
# difference between "wait for a guild" and "somebody has to build this".
#
# THE STEPS ARE A CAPABILITY TABLE, NOT A QUERY. Travel is the one part that
# works: a petitioner and a guild banker are both ordinary NPCs, and travel.py
# can already aim a character at an NPC by entry. Everything after arriving is
# a packet nothing sends.
GUILD_TICKET = {
    "label": "infra#2831",
    "url": "https://github.com/quadseven/infra/issues/2831",
}
WORKS = "works"
MISSING = "missing"
GUILD_STEP_WORDS = {WORKS: "works", MISSING: "not written"}
GUILD_STEP_TONES = {WORKS: GOOD, MISSING: CAUTION}
# In the order somebody would actually do them, so the list reads as a road
# rather than as a feature matrix. The two that work come first because that
# is where the road runs out, and a reader should be able to see how far.
GUILD_STEPS = (
    ("travel to a petitioner", WORKS),
    ("travel to a guild banker", WORKS),
    ("buy a charter", MISSING),
    ("collect the signatures", MISSING),
    ("register the guild", MISSING),
    ("deposit into the guild bank", MISSING),
    ("withdraw from the guild bank", MISSING),
)
NO_GUILD_LEAD = "There is no guild, so there is no guild bank."
NO_GUILD_BODY = ("Rather than draw an empty vault, here is what stands "
                 "between the family and one.")
# A guild appearing is not a thing this panel can be trusted to have kept up
# with, so it says so rather than guessing at what is in the bank.
GUILD_BODY = ("The bank's own tabs are not read here yet, so this is still "
              "the road rather than the contents.")


def build_guild_bank(guild_rows: list[dict],
                     guild_bank_rows: list[dict] | None = None,
                     guild_bank_right_rows: list[dict] | None = None) -> dict:
    """Which guild the family is in, if any, and what stands in front of one.

    `guild_rows` is whatever `guild_member` joined to `guild` returns for the
    roster: no rows means nobody is in a guild, which is the live answer today
    and is checked rather than assumed. A hardcoded "there is no guild" would
    go on being drawn on the day somebody makes one.
    """
    guilds = sorted({row["guild_name"] for row in guild_rows
                     if row.get("guild_name")})
    observed = guild_bank_rows is not None
    rights_observed = guild_bank_right_rows is not None
    tabs = list(guild_bank_rows or [])
    rights = list(guild_bank_right_rows or [])
    tab_count = len(tabs)
    item_count = 0
    for row in tabs:
        try:
            item_count += max(0, int(row.get("item_count", 0)))
        except (AttributeError, TypeError, ValueError):
            # A malformed adapter row must not turn a read-only status panel
            # into a 503 or manufacture a count.
            continue
    deposit_rank_ids = set()
    for row in rights:
        try:
            if (int(row.get("tab_id")) == 0
                    and int(row.get("rights", 0)) & 3 == 3):
                deposit_rank_ids.add(int(row["rank_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    steps = [{"step": step, "state": state,
              "state_label": GUILD_STEP_WORDS[state],
              "tone": GUILD_STEP_TONES[state]} for step, state in GUILD_STEPS]
    missing = [s for s in steps if s["state"] == MISSING]
    if guilds:
        lead = "The family is in %s." % ", ".join(guilds)
        body = GUILD_BODY
        if observed:
            body = ("The guild has %d purchased bank tab%s holding %d stored "
                    "item%s."
                    % (tab_count, "" if tab_count == 1 else "s", item_count,
                       "" if item_count == 1 else "s"))
            if rights_observed:
                body += " Deposit rights are recorded for %d rank%s." % (
                    len(deposit_rank_ids),
                    "" if len(deposit_rank_ids) == 1 else "s")
    else:
        lead, body = NO_GUILD_LEAD, NO_GUILD_BODY
    return {
        "guilds": guilds,
        "bank_observed": observed,
        "purchased_tabs": tab_count if observed else None,
        "stored_items": item_count if observed else None,
        "rights_observed": rights_observed,
        "deposit_rank_ids": sorted(deposit_rank_ids) if rights_observed else None,
        "tabs": tabs if observed else [],
        "lead": lead,
        "body": body,
        "steps": steps,
        "works": len(steps) - len(missing),
        "missing": len(missing),
        "blocked": linked_sentence(
            "%s of the %s steps are not written, and all of them are "
            "blocked on " % (sentence(spell(len(missing))), spell(len(steps))),
            GUILD_TICKET, "."),
    }


# --- what the page calls each block ----------------------------------------
# The three-part section rule wants an index and a label, and both are words on
# a screen. They live here for the same reason every other word on this view
# does: index.html draws what it is given and names nothing itself.
SECTION_HEADERS = {
    "cards": {"index": "01", "label": "purses and bags"},
    "auction": {"index": "02", "label": "auction house"},
    "guild": {"index": "03", "label": "guild bank"},
}

# These numbers are a SAVE, and nobody can tell by looking. The core writes
# money and bags on its own timer, so gold spent five minutes ago is still
# here - and a reader who sells a sword, sees no change and concludes the page
# is broken is a reader the page lied to.
SAVED_NOTE = ("Purses, bags and auctions as the world last saved them, on the "
              "same timer as the gear in the Armory.")


def _claims_by_family(chars: dict, splits: dict, families) -> dict[int, str]:
    """gear.claims over each family on its own, as the pipeline's hand-offs
    run: a Horde relative is not an Alliance one."""
    claims: dict[int, str] = {}
    for _key, names in families:
        present = [n for n in names
                   if n in splits and chars[n].get("class") is not None]
        if not present:
            continue
        claims.update(bagfate.family_claims(
            {n: splits[n]["carried_rows"] for n in present},
            {n: splits[n]["worn_rows"] for n in present},
            {n: (chars[n]["class"], chars[n].get("level") or 1) for n in present}))
    return claims


def build_wealth(char_rows: list[dict], inventory_rows: list[dict],
                 auction_rows: list[dict], guild_rows: list[dict],
                 icons: dict[int, str],
                 guild_bank_rows: list[dict] | None = None,
                 guild_bank_right_rows: list[dict] | None = None,
                 families: list[tuple[str, list[str]]] | None = None) -> dict:
    """Every member's purse and bags, the family total, the auction house,
    and the guild bank there is not.

    The row lists arrive keyed by character name, unfiltered, exactly as
    build_armory takes them; splitting them per member is this module's job
    so the adapter stays a handful of queries and no logic.
    """
    chars = {r["name"]: r for r in char_rows}
    inventory: dict[str, list[dict]] = {}
    for row in inventory_rows:
        inventory.setdefault(row["name"], []).append(row)
    if families is None:
        families = [("", family.roster())]
    guild_of = {r["name"]: r.get("guild_name") for r in guild_rows}
    for name, row in chars.items():
        row.setdefault("guild", guild_of.get(name))
    splits = {name: split_inventory(inventory.get(name, []), icons)
              for _key, names in families for name in names if name in chars}
    claims = _claims_by_family(chars, splits, families)
    # A character the economy passes do not cover gets one sentence instead
    # of piles. The passes cover the persona family (bonds), which is the
    # roster they are configured with; #150 is widening that.
    members = [build_member(name, chars.get(name), inventory.get(name, []), icons,
                            claims=claims, managed=name in bonds.FAMILY,
                            split=splits.get(name))
               for _key, names in families for name in names]
    # BOTH FAMILIES, Alliance on the left and Horde on the right, by the
    # Armory's own rule for which side a family is on (armory.family_sides),
    # so the two tabs cannot put a family on different sides.
    by_name = {m["name"]: m for m in members}
    sides = armory.family_sides(
        [(key, [by_name[n] for n in names]) for key, names in families])
    for side in sides:
        side.pop("members")
    return {
        "members": members,
        "sides": sides,
        "family": build_family(members),
        "auctions": build_auctions(auction_rows, icons),
        "guild_bank": build_guild_bank(
            guild_rows, guild_bank_rows, guild_bank_right_rows),
        "sections": SECTION_HEADERS,
        "saved_note": SAVED_NOTE,
        "expected": len(members),
    }
