"""The data the item plan lacked (#1973): rows in, itemplan-ready values out.

PURE. No MySQL, no HTTP, no clock. Each reader takes rows shaped like the
real tables (a list of dicts) and returns what `itemplan.Context` takes. A
malformed row is skipped and never raises: a row this module cannot read adds
nothing, and the plan then fails closed on whatever that row would have
described. `itemplan_reads` runs the SQL and `itemplan_shadow` feeds the results to the plan.

WHAT EACH READER REUSES, and what it adds.

  quest_needs / open_quest_items. The filter is `bag_pressure.QUEST_NEEDED_SQL`
  and `bankpolicy`'s copy of it: a `character_queststatus` row whose status is
  not 0, joined to `quest_template`, names an item through RequiredItemId1-6,
  ItemDrop1-4 or StartItem. Those two queries answer "is this one stack
  needed" row by row inside a bag query. The plan needs the whole set, so
  QUEST_LOG_SQL and QUEST_TEMPLATE_SQL read the same two tables without the
  bag join, and add RequiredItemCount1-6 (as `classquest._ITEMS` does) so the
  need has a count. ItemDrop and StartItem carry no count in the template and
  count as 1.

  equipped. The paper doll is `armory.EQUIPPED_SLOTS` (slot index to name) and
  the worn bound is `ci.bag = 0 AND ci.slot < 19`, the same bound
  `bankpolicy.WORN_SQL` and `panel._build_inventory` use. EQUIPPED_SQL adds
  the item columns the plan needs and nothing else.

  auction_prices. Two sources, live first. The live source is
  `auctionhouse` joined to `item_instance` for the entry and count (the join
  `bridge._AUCTION_LISTINGS_SQL` documents; LISTINGS_SQL is that query for
  every entry), priced by `auction.Listing.per_unit`. The history source is
  `bankforecast.HISTORY_SQL` priced by `bankforecast.fair_price`. When
  neither has a row for an entry the entry is absent, and `absent_reason`
  says which source was empty. No price is ever made up: `auction.price_candidates`
  falls back to a stack's own vendor-derived fair price, and this module does not.
"""

from __future__ import annotations

import armory
import auction
import bankforecast
import gearscore

# --- item template: binding and gear facts -----------------------------------

ITEM_TEMPLATE_SQL = (
    "SELECT it.entry AS entry, it.class AS item_class, it.subclass AS subclass, "
    "it.bonding AS bonding, it.InventoryType AS inventory_type, "
    "it.ItemLevel AS item_level, it.RequiredLevel AS req_level, "
    "it.RequiredSkillRank AS required_skill_rank, "
    "it.ContainerSlots AS container_slots, "
    "it.DisenchantID AS disenchant_id, "
    "it.RequiredDisenchantSkill AS disenchant_skill, "
    "it.armor AS armor, it.block AS block, it.dmg_min1 AS dmg_min1, "
    "it.dmg_max1 AS dmg_max1, it.delay AS delay, "
    "it.holy_res AS holy_res, it.fire_res AS fire_res, "
    "it.nature_res AS nature_res, it.frost_res AS frost_res, "
    "it.shadow_res AS shadow_res, it.arcane_res AS arcane_res, "
    + ", ".join(
        "it.stat_type%d AS stat_type%d, it.stat_value%d AS stat_value%d" % (n, n, n, n)
        for n in range(1, 11)
    )
    + " "
    "FROM acore_world.item_template it WHERE it.entry IN (%s)"
)

_DISENCHANT_FIELDS = ("disenchant_id", "disenchant_skill")

_TEMPLATE_FIELDS = (
    "item_class",
    "subclass",
    "bonding",
    "inventory_type",
    "item_level",
    "req_level",
    "required_skill_rank",
    "container_slots",
    "fire_res",
)

ITEM_INSTANCE_SQL = (
    "SELECT ii.guid AS item_guid, ii.flags AS instance_flags "
    "FROM item_instance ii WHERE ii.guid IN (%s)"
)


# --- quest log -------------------------------------------------------------

QUEST_LOG_SQL = (
    "SELECT c.name AS member, qs.quest AS quest, qs.status AS status "
    "FROM character_queststatus qs "
    "JOIN characters c ON c.guid = qs.guid "
    "WHERE qs.status <> 0 AND c.name IN (%s)"
)

QUEST_TEMPLATE_SQL = (
    "SELECT qt.ID AS quest, "
    + "".join(
        "qt.RequiredItemId%d AS item%d, qt.RequiredItemCount%d AS item_count%d, "
        % (i, i, i, i)
        for i in range(1, 7)
    )
    + "".join("qt.ItemDrop%d AS drop%d, " % (i, i) for i in range(1, 5))
    + "qt.StartItem AS start_item "
    "FROM acore_world.quest_template qt WHERE qt.ID IN (%s)"
)

QUEST_STATUS_NONE = 0


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def item_templates(rows) -> dict:
    """{entry: {field: int}} from `ITEM_TEMPLATE_SQL` rows.

    Gives the binding of every carried row (the carried query holds none), and
    the inventory type, item level and required level the worn-gear verdict
    needs. A row with a missing or non-numeric field is skipped whole, so an
    entry is either fully known or absent.
    """
    out: dict = {}
    for row in rows or ():
        try:
            entry = _int(row["entry"])
            item = {k: _int(row[k]) for k in _TEMPLATE_FIELDS}
        except (KeyError, TypeError, AttributeError):
            continue
        if entry is None or entry <= 0 or any(v is None for v in item.values()):
            continue
        item["stats"] = gearscore.stats_from_row(row)
        # The core's own breakdown facts (#1978). Optional: a row without them
        # is still read, and the plan falls back to its convention.
        for field in _DISENCHANT_FIELDS:
            value = _int(row.get(field)) if hasattr(row, "get") else None
            if value is not None:
                item[field] = value
        out[entry] = item
    return out


def verdict_rows(stacks, templates, characters) -> list:
    """The `bag_rows` `upgrade_verdicts` takes, for every carried gear stack.

    `stacks` are `itemplan.Stack`s, `templates` is `item_templates`' answer and
    `characters` is name -> (class id, level). A stack with no template or no
    known holder level is left out: no verdict, so the plan's other rules decide.
    """
    out = []
    for s in stacks:
        t = templates.get(s.entry)
        if not s.carried or not s.gear or t is None or s.holder not in characters:
            continue
        out.append(
            {
                "member": s.holder,
                "entry": s.entry,
                "inventory_type": t["inventory_type"],
                "item_level": t["item_level"],
                "req_level": t["req_level"],
                "level": characters[s.holder][1],
            }
        )
    return out


def _template_items(row) -> dict:
    """{item entry: count} one quest template names, or {} when unreadable."""
    out: dict = {}
    for i in range(1, 7):
        entry = _int(row.get("item%d" % i), 0)
        if entry > 0:
            out[entry] = out.get(entry, 0) + max(
                1, _int(row.get("item_count%d" % i), 1)
            )
    extra = [row.get("drop%d" % i) for i in range(1, 5)] + [row.get("start_item")]
    for raw in extra:
        entry = _int(raw, 0)
        if entry > 0:
            out[entry] = max(out.get(entry, 0), 1)
    return out


def quest_needs(quest_rows, template_rows) -> dict:
    """{item entry: count needed} for ONE member's open quests.

    `quest_rows` are that member's `character_queststatus` rows (quest,
    status); `template_rows` are `QUEST_TEMPLATE_SQL` rows. A status of 0 is
    not open. Two open quests that name one item add. A quest with no
    template row, a row with a non-numeric id, or a row that is not a mapping
    is skipped.
    """
    templates: dict = {}
    for row in template_rows or ():
        try:
            quest = _int(row.get("quest"))
            if quest is None:
                continue
            templates[quest] = _template_items(row)
        except AttributeError:
            continue
    needs: dict = {}
    seen: set = set()
    for row in quest_rows or ():
        try:
            quest = _int(row.get("quest"))
            status = _int(row.get("status"))
        except AttributeError:
            continue
        if quest is None or status is None or status == QUEST_STATUS_NONE:
            continue
        if quest in seen:
            continue
        seen.add(quest)
        for entry, count in templates.get(quest, {}).items():
            needs[entry] = needs.get(entry, 0) + count
    return needs


def open_quest_items(quest_rows, template_rows) -> dict:
    """`itemplan.Context.open_quest_items`: {member: frozenset of entries}.

    `quest_rows` are `QUEST_LOG_SQL` rows for every member. A member with
    rows but no named item maps to an empty set (the log was read and nothing
    in it needs an item), which is what frees the leftovers. A member with no
    row at all is absent, and the plan reads an absent member of a non-None
    mapping as an empty log. The caller passes the mapping only when the
    query ran; None keeps every quest-class stack.
    """
    by_member: dict = {}
    for row in quest_rows or ():
        try:
            name = str(row["member"])
        except (KeyError, TypeError):
            continue
        by_member.setdefault(name, []).append(row)
    return {
        name: frozenset(quest_needs(rows, template_rows))
        for name, rows in by_member.items()
    }


# --- equipped gear ---------------------------------------------------------

EQUIPPED_SQL = (  # noqa: S608 - the bound is an int from armory, names stay placeholders
    "SELECT c.name AS member, ci.slot AS slot, ii.itemEntry AS entry, "
    "ii.flags AS instance_flags, "
    "it.name AS name, it.class AS item_class, it.subclass AS subclass, "
    "it.Quality AS quality, it.ItemLevel AS item_level, "
    "it.InventoryType AS inventory_type, it.RequiredLevel AS req_level, "
    "it.RequiredSkillRank AS required_skill_rank, "
    "it.ContainerSlots AS container_slots, it.fire_res AS fire_res, "
    "it.armor AS armor, it.block AS block, it.dmg_min1 AS dmg_min1, "
    "it.dmg_max1 AS dmg_max1, it.delay AS delay, "
    "it.holy_res AS holy_res, it.nature_res AS nature_res, "
    "it.frost_res AS frost_res, it.shadow_res AS shadow_res, "
    "it.arcane_res AS arcane_res, "
    + ", ".join(
        "it.stat_type%d AS stat_type%d, it.stat_value%d AS stat_value%d" % (n, n, n, n)
        for n in range(1, 11)
    )
    + " "
    "FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND ci.bag = 0 AND ci.slot < "
    + str(len(armory.EQUIPPED_SLOTS))
)

_WORN_FIELDS = (
    "entry",
    "item_class",
    "subclass",
    "quality",
    "item_level",
    "inventory_type",
    "req_level",
)


def equipped(rows) -> dict:
    """{member: {slot name: worn item dict}} from `EQUIPPED_SQL` rows.

    A slot outside the paper doll, a missing member or a non-numeric field is
    skipped. A second row for one slot keeps the first (a slot holds one item).
    """
    out: dict = {}
    for row in rows or ():
        try:
            member = str(row["member"])
            slot = _int(row["slot"])
            if not member or slot is None or not 0 <= slot < len(armory.EQUIPPED_SLOTS):
                continue
            item = {k: _int(row[k]) for k in _WORN_FIELDS}
            if any(v is None for v in item.values()) or item["entry"] <= 0:
                continue
            item["name"] = str(row.get("name") or "")
            item["fire_res"] = _int(row.get("fire_res"), 0)
            item["instance_flags"] = _int(row.get("instance_flags"), 0)
            item["stats"] = gearscore.stats_from_row(row)
        except (KeyError, TypeError, AttributeError):
            continue
        out.setdefault(member, {}).setdefault(armory.EQUIPPED_SLOTS[slot], item)
    return out


def worn_entries(worn: dict) -> dict:
    """{member: frozenset of worn entries}: what must never be sold, given or destroyed."""
    return {
        m: frozenset(i["entry"] for i in slots.values()) for m, slots in worn.items()
    }


# InventoryType -> the worn slots it can fill (3.3.5: 13 one-hand, 17 two-hand).
_SLOTS_FOR = {
    1: ("head",),
    2: ("neck",),
    3: ("shoulders",),
    5: ("chest",),
    20: ("chest",),
    6: ("waist",),
    7: ("legs",),
    8: ("feet",),
    9: ("wrists",),
    10: ("hands",),
    11: ("finger 1", "finger 2"),
    12: ("trinket 1", "trinket 2"),
    16: ("back",),
    13: ("main hand", "off hand"),
    21: ("main hand",),
    17: ("main hand",),
    14: ("off hand",),
    22: ("off hand",),
    23: ("off hand",),
    15: ("ranged",),
    25: ("ranged",),
    26: ("ranged",),
}


def upgrade_verdicts(worn: dict, bag_rows, drive=None) -> dict:
    """`itemplan.Context.gear_verdict`: {(member, entry): "wear"}.

    A bag piece is "wear" when its item level beats the worn item in every
    slot it can fill, or fills an empty slot, and its required level is within
    the holder's reach (`req_level` <= `level`, both from the row). This is a
    deliberately blunt signal: it keeps a probable upgrade carried and never
    judges a piece as not better, so a doubtful piece gets no verdict and the
    plan's other rules decide. `bag_rows` carry member, entry, inventory_type,
    item_level, req_level and level; a row missing any is skipped.

    `drive` is `equipscore.drive_verdicts`' answer, {member: {entry:
    verdict}}, for the roster members whose equips the module's gear drive
    makes (#2381). For a member in it, the drive's rule is the authority: a
    piece is "wear" only when the drive would put it on, and item level is not
    asked, so a piece the drive declines is never carried for ever as R4.
    """
    drive = drive or {}
    out: dict = {}
    for row in bag_rows or ():
        try:
            member = str(row["member"])
            entry = int(row["entry"])
            itype = int(row["inventory_type"])
            ilvl = int(row["item_level"])
            req = int(row["req_level"])
            level = int(row["level"])
        except (KeyError, TypeError, ValueError):
            continue
        if member in drive:
            if drive[member].get(entry) == "wear":
                out[(member, entry)] = "wear"
            continue
        slots = _SLOTS_FOR.get(itype)
        if not slots or req > level:
            continue
        mine = worn.get(member)
        if mine is None:
            continue  # worn gear was not read for this member: no verdict
        if any(slot in mine and mine[slot]["entry"] == entry for slot in slots):
            continue
        if all(ilvl > mine.get(slot, {}).get("item_level", 0) for slot in slots):
            out[(member, entry)] = "wear"
    return out


# --- auction prices --------------------------------------------------------

LISTINGS_SQL = (
    "SELECT a.id AS auction_id, a.houseid AS house, a.buyoutprice AS buyout, "
    "ii.itemEntry AS entry, ii.count AS count, it.name AS label "
    "FROM auctionhouse a "
    "JOIN item_instance ii ON ii.guid = a.itemguid "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE a.houseid = %s AND a.buyoutprice > 0"
)

NO_PRICE_SOURCE = (
    "no auction price source: no live buyout listing and no auction history "
    "row was read, so no entry has a price and the plan keeps the vendor price "
    "as its floor"
)


def _listing(row):
    try:
        buyout = int(row["buyout"])
        if buyout <= 0:
            return None
        return auction.Listing(
            auction_id=int(row.get("auction_id") or 0),
            entry=int(row["entry"]),
            count=max(1, int(row.get("count") or 1)),
            buyout=buyout,
            house=int(row.get("house") or 0),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def auction_prices(listing_rows, history_rows=(), house: int = 0) -> dict:
    """`itemplan.Context.market`: {entry: (copper per unit, sample count)}.

    The lowest live buyout per unit when the entry has a live listing (the
    sample count is the number of listings); else the history's fair price
    (`bankforecast.fair_price`; the count is its rows for the entry); else the
    entry is absent. Never invents a price: an entry with no listing and no
    history is not in the result, and an item no one lists does not reach the
    auction route.
    """
    live: dict = {}
    for row in listing_rows or ():
        listing = _listing(row)
        if listing is None:
            continue
        low, n = live.get(listing.entry, (None, 0))
        price = listing.per_unit
        live[listing.entry] = (price if low is None else min(low, price), n + 1)
    out = dict(live)
    history = [r for r in history_rows or () if isinstance(r, dict)]
    for entry in {_int(r.get("item_entry")) for r in history} - set(out) - {None}:
        price, _why = bankforecast.fair_price(history, entry, house)
        if price > 0:
            n = sum(1 for r in history if _int(r.get("item_entry")) == entry)
            out[entry] = (price, n)
    return out


def absent_reason(listing_rows, history_rows=()) -> str:
    """ "" when any price source had rows, else why no entry has a price."""
    if listing_rows or history_rows:
        return ""
    return NO_PRICE_SOURCE


__all__ = [
    "EQUIPPED_SQL",
    "ITEM_INSTANCE_SQL",
    "ITEM_TEMPLATE_SQL",
    "LISTINGS_SQL",
    "NO_PRICE_SOURCE",
    "QUEST_LOG_SQL",
    "QUEST_TEMPLATE_SQL",
    "absent_reason",
    "auction_prices",
    "equipped",
    "item_templates",
    "open_quest_items",
    "quest_needs",
    "upgrade_verdicts",
    "verdict_rows",
    "worn_entries",
]
