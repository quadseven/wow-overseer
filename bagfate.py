"""Where each thing in a character's bags is going, and what is stopping it.

WHY THIS EXISTS. The operator looked at the Bags tab and saw bags "still full
of garbage", and asked why nothing was sold, handed to a guildmate who needs
it, auctioned or disenchanted. The tab could not answer: it showed what was
carried and what it was worth, and nothing about what the pipeline meant to
do with any of it. Measured on the dev realm on 2026-09-22, the pipeline's
own planners routed 8 of the Alliance family's 259 carried stacks, all of
them one character's, and the rest were kept - most of them by a rule that
has never been told what to do with them.

So each carried stack is put in ONE of a small number of piles, and every
pile says three things: what it is, where the pipeline sends it, and - when
it goes nowhere - the reason and the open ticket for that reason.

THIS IS THE PIPELINE'S OPINION, NOT A NEW ONE. The piles are read off the
same facts and the same rules the bridge uses:

  junk        `bag_pressure.sellable`'s own test: quality 0 or 1, a vendor
              price, not a quest item, not a trade good. It is sold on the
              next vendor trip, and a trip starts only when somebody is at
              or under `bag_pressure.TOWN_RUN_FREE_SLOTS` free slots.
  gear        `gear.claims`, through bag_pressure (its one adapter): the
              one opinion the sell, give and auction passes all consult,
              run over the holder's own family: a piece the holder would
              wear, a piece for a named relative,
              a piece nobody would wear, and a piece it cannot judge.
  quests      bag_pressure.QUEST_NEEDED_SQL, the vendor pass's own test:
              a quest-class stack no quest in the holder's log needs is
              ordinary goods, and junk when it has a price (#144).
  the rest    by item class, because the pipeline routes them by class
              too: recipes are kept for the holder's trade, gems have no
              route at all.

WHAT IT DOES NOT CLAIM. It does not know which sales `item_plan` is holding
back, or what a guildmate is short of: those are the bridge's live state and
this runs in the map server. Where that matters the blocker says so rather
than guessing.

Pure: rows and names in, piles out. Tickets: #88 (the epic), #144-#152.
"""

from __future__ import annotations

import bag_pressure
import disposition

# Item classes, as item_template.class stores them.
CONSUMABLE, CONTAINER, WEAPON, GEM, ARMOR = 0, 1, 2, 3, 4
REAGENT, TRADE_GOODS, RECIPE, QUEST, MISC = 5, 7, 9, 12, 15
GEAR_CLASSES = frozenset({WEAPON, ARMOR})
BIND_ON_EQUIP = 2
RARE = 3

# Tones, the same four words wealth.py gives every other verdict.
ALARM, CAUTION, GOOD, PLAIN = "alarm", "caution", "good", ""

REPO = "https://github.com/quadseven/wow-overseer/issues/"


def _ticket(number: int) -> dict:
    return {"label": "#%d" % number, "url": REPO + str(number)}


# Every pile's words, in the order the page lists them: the ones that move
# first, then the ones stuck for a reason somebody can fix, then the ones
# kept on purpose.
JUNK = "junk"
FOR_HOLDER = "for_holder"
FOR_RELATIVE = "for_relative"
AUCTION = "auction"
VENDOR_GEAR = "vendor_gear"
DUST = "dust"
UNJUDGED = "unjudged"
QUESTS = "quest"
LEFTOVERS = "quest_leftover"
RECIPES = "recipe"
GEMS = "gem"
MISC_PILE = "misc"
TRADE = "trade"
CONSUMABLES = "consumable"
BAGS = "bag"
TOOLS = "tool"
OTHER = "other"

PILES = {
    JUNK: (
        "junk",
        "sold at the next vendor trip, unless an earlier refusal "
        "for want of a vendor is still holding it (up to a day)",
        GOOD,
        149,
    ),
    FOR_RELATIVE: (
        "gear for {who}",
        "handed over by the family gear pass once {who} is close by with a free slot",
        GOOD,
        None,
    ),
    AUCTION: (
        "gear nobody in the family would wear, still tradable",
        "listed when the leader reaches an auctioneer, which the "
        "shared travel slot rarely allows",
        CAUTION,
        148,
    ),
    VENDOR_GEAR: (
        "plain gear nobody in the family would wear",
        "sold at the next vendor trip, unless an earlier refusal "
        "is still holding it (up to a day)",
        GOOD,
        149,
    ),
    FOR_HOLDER: (
        "upgrades for {who}, carried and not worn",
        "kept - nothing puts on a carried upgrade",
        ALARM,
        146,
    ),
    DUST: (
        "green or better gear nobody would wear, and bound",
        "kept - there is no way to disenchant it, in the family or "
        "through a guild enchanter",
        ALARM,
        147,
    ),
    GEMS: (
        "gems",
        "kept - not sold, not shared with a guildmate, not auctioned",
        ALARM,
        148,
    ),
    QUESTS: (
        "quest items an open quest still needs",
        "kept for the quest",
        PLAIN,
        None,
    ),
    LEFTOVERS: (
        "quest leftovers no vendor will buy",
        "kept - nothing destroys an item that has no sale price",
        CAUTION,
        144,
    ),
    RECIPES: (
        "recipes",
        "kept for the holder's own trade, even when the skill it needs is far off",
        CAUTION,
        145,
    ),
    UNJUDGED: (
        "gear the family check cannot judge (rings, trinkets, relics)",
        "kept - not offered to a guildmate either",
        CAUTION,
        148,
    ),
    MISC_PILE: (
        "lockboxes and other oddments",
        "kept - no pass routes them",
        CAUTION,
        148,
    ),
    TRADE: (
        "trade goods and reagents",
        "kept for a family trade, or shared with a guildmate who needs them",
        PLAIN,
        None,
    ),
    TOOLS: ("trade tools", "kept for the family's trades, never sold", PLAIN, None),
    CONSUMABLES: ("consumables", "kept to be used", PLAIN, None),
    BAGS: ("spare bags", "equipped by the bag pass, or sold as a spare", PLAIN, None),
    OTHER: ("other", "kept", PLAIN, None),
}
ORDER = (
    JUNK,
    FOR_RELATIVE,
    AUCTION,
    VENDOR_GEAR,
    FOR_HOLDER,
    DUST,
    GEMS,
    LEFTOVERS,
    QUESTS,
    RECIPES,
    UNJUDGED,
    MISC_PILE,
    TRADE,
    TOOLS,
    CONSUMABLES,
    BAGS,
    OTHER,
)

# What a character no pass manages says, instead of a verdict per pile: the
# piles would describe a pipeline that never looks at these bags.
UNMANAGED = {
    "text": "No bag or economy pass looks at this character yet: nothing here "
    "is sold, given, banked or auctioned, and nothing buys a bag.",
    "tone": ALARM,
    "ticket": _ticket(150),
}
# The junk pile's condition, when it is the thing in the way.
TRIP_WAIT = (
    "no vendor trip until somebody is down to %d free slots"
    % bag_pressure.TOWN_RUN_FREE_SLOTS
)
HEADING = "where it is going"
NOTE = (
    "Each carried stack in one pile. A pile that goes nowhere says why, "
    "and links the open ticket for it."
)


# Classes whose pile does not depend on anything but the class.
_BY_CLASS = {RECIPE: RECIPES, CONTAINER: BAGS, TRADE_GOODS: TRADE, REAGENT: TRADE}
# What is left over once junk is ruled out, by class.
_KEPT_BY_CLASS = {GEM: GEMS, MISC: MISC_PILE, CONSUMABLE: CONSUMABLES}


def _junk(quality, price: int) -> bool:
    """bag_pressure.sellable's price-and-quality half: 0 or 1, and a price."""
    return quality is not None and quality <= 1 and price > 0


def _gear_pile(
    row: dict, claimant: str | None, holder: str, quality, price: int
) -> tuple[str, str]:
    """A weapon or armour piece, by what gear.claims said about it."""
    if claimant is None or claimant == bag_pressure.CLAIM_UNJUDGEABLE:
        return (JUNK, "") if quality == 0 and price > 0 else (UNJUDGED, "")
    if claimant == holder:
        return FOR_HOLDER, holder
    if claimant != bag_pressure.CLAIM_NOBODY:
        return FOR_RELATIVE, claimant
    if quality is not None and quality <= 1:
        return (VENDOR_GEAR, "") if price > 0 else (OTHER, "")
    soulbound = bool(int(row.get("instance_flags") or 0) & 0x1)
    tradable = not soulbound and row.get("bonding") == BIND_ON_EQUIP
    return (AUCTION, "") if tradable and quality < RARE else (DUST, "")


def _quest_pile(row: dict, quality, price: int) -> tuple[str, str]:
    """A quest-class stack, by whether a quest in the holder's log needs it.

    That is bag_pressure.QUEST_NEEDED_SQL's answer, the vendor pass's own. A
    row that does not carry the answer is treated as needed: the fail-closed
    reading, as the vendor's.
    """
    if row.get("quest_needed", True):
        return QUESTS, ""
    return (JUNK, "") if _junk(quality, price) else (LEFTOVERS, "")


def pile_of(row: dict, claimant: str | None, holder: str) -> tuple[str, str]:
    """One carried row -> (pile key, who it is for, or "").

    `claimant` is gear.claims' answer for this row's guid, or None when the
    row was never asked (not gear, or gear the gear rows could not describe).
    """
    item_class = row.get("class")
    quality = row.get("quality")
    price = int(row.get("sell_price") or 0)
    if item_class == QUEST:
        return _quest_pile(row, quality, price)
    if item_class in _BY_CLASS:
        return _BY_CLASS[item_class], ""
    # A Mining Pick is a weapon to the gear check and a tool to the pipeline,
    # which never sells one (disposition.trade_tool); the pipeline wins.
    if disposition.trade_tool(
        disposition.Item(
            name="",
            item_class=item_class or 0,
            bag_family=int(row.get("bag_family") or 0),
        )
    ):
        return TOOLS, ""
    if item_class in GEAR_CLASSES:
        return _gear_pile(row, claimant, holder, quality, price)
    if item_class != GEM and _junk(quality, price):
        return JUNK, ""
    return _KEPT_BY_CLASS.get(item_class, OTHER), ""


def family_claims(
    carried: dict[str, list[dict]],
    equipped: dict[str, list[dict]],
    levels: dict[str, tuple[int, int]],
) -> dict[int, str]:
    """item guid -> gear.claims' answer, over ONE family's carried gear.

    `carried` and `equipped` are raw inventory rows by holder; `levels` is
    name -> (class id, level). Run per family, because the pipeline hands
    gear on within a family and a Horde relative is not an Alliance one.
    """
    names = list(levels)
    worn_rows = []
    for name, (class_id, level) in levels.items():
        worn_rows.append({"name": name, "class_id": class_id, "level": level})
        for r in equipped.get(name, []):
            worn_rows.append(
                {
                    "name": name,
                    "class_id": class_id,
                    "level": level,
                    "inventory_type": r.get("inventory_type"),
                    "item_level": r.get("item_level"),
                }
            )
    gear_rows = []
    for name, rows in carried.items():
        for r in rows:
            if r.get("class") not in GEAR_CLASSES:
                continue
            gear_rows.append(
                {
                    "holder": name,
                    "item_guid": r.get("item_guid"),
                    "entry": r.get("entry"),
                    "name": r.get("item_name") or "",
                    "quality": r.get("quality"),
                    "item_level": r.get("item_level"),
                    "required_level": r.get("required_level"),
                    "allowable_class": r.get("allowable_class"),
                    "inventory_type": r.get("inventory_type"),
                    "item_class": r.get("class"),
                    "instance_flags": r.get("instance_flags"),
                    "item_subclass": r.get("subclass"),
                }
            )
    return bag_pressure.family_claimants(gear_rows, worn_rows, names)


def build_fates(
    holder: str,
    carried_rows: list[dict],
    claims: dict[int, str],
    free_slots: int | None,
    managed: bool,
) -> dict:
    """One character's piles, in the page's order, with every word composed."""
    if not managed:
        return {"heading": HEADING, "note": NOTE, "unmanaged": UNMANAGED, "piles": []}
    piles: dict[tuple[str, str], dict] = {}
    for row in carried_rows:
        key, who = pile_of(row, claims.get(int(row.get("item_guid") or 0)), holder)
        pile = piles.setdefault(
            (key, who), {"key": key, "who": who, "stacks": 0, "items": []}
        )
        pile["stacks"] += 1
        name = row.get("item_name") or "item %s" % row.get("entry")
        if name not in pile["items"]:
            pile["items"].append(name)
    out = []
    for key, who in sorted(piles, key=lambda k: (ORDER.index(k[0]), k[1])):
        pile = piles[(key, who)]
        label, route, tone, ticket = PILES[key]
        blocker = None
        if (
            key == JUNK
            and free_slots is not None
            and free_slots > bag_pressure.TOWN_RUN_FREE_SLOTS
        ):
            # Moving, but not yet: the trip waits for the bags to fill.
            blocker = TRIP_WAIT
            tone = CAUTION
        out.append(
            {
                "key": key,
                "label": label.format(who=who),
                "count": "%d stack%s"
                % (pile["stacks"], "" if pile["stacks"] == 1 else "s"),
                "stacks": pile["stacks"],
                "route": route.format(who=who),
                "blocker": blocker,
                "tone": tone,
                "ticket": _ticket(ticket) if ticket else None,
                # A handful of names, so a pile is recognisable without opening
                # the bag grid; the grid has the rest.
                "examples": ", ".join(pile["items"][:4])
                + (
                    " and %d more" % (len(pile["items"]) - 4)
                    if len(pile["items"]) > 4
                    else ""
                ),
            }
        )
    return {"heading": HEADING, "note": NOTE, "unmanaged": None, "piles": out}
