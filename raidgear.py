"""Pre-raid readiness for raid seats (#542, decision #532 point 5).

A raider's seat depends on how close what it wears is to its spec's pre-raid
best in slot, not on item level. The score is gearupgrades': the share of the
spec's scored slots that sit at or near the pre-raid best by gearscore. This
module only reads it for the raid code, so the lineup, the readiness card and
the bridge's seat writer all rank raiders the same way.

PURE except for the SQL constants: rows in, a share out. A raider with no
worn rows read, or a class with no gear lists, has no share (None). Seat order
treats None as zero; the readiness card says "not read" instead of guessing.

WHAT IS SCORED. The worn item's template stats only. The raid read has no
enchant or random-suffix tables, so a worn enchant is not counted here though
the upgrade tracker page counts it; the share can read a little lower than
the tracker's.
"""

from __future__ import annotations

import armory
import gearscore
import gearupgrades
import raidlineup
import raidroles

# THE SEAT THRESHOLD. A raider is seat-ready when at least this share of its
# scored slots are at or near pre-raid best in slot. Half is a convention,
# like the item level floor it replaces: players raid Molten Core while still
# collecting pre-raid pieces, so the bar is "most of the way", not "done".
# Printed beside every number it judges so it can be disagreed with.
READY_SHARE = 0.5

_STAT_COLUMNS = (
    "it.armor, it.block, it.dmg_min1, it.dmg_max1, it.delay, "
    "it.holy_res, it.nature_res, it.frost_res, it.shadow_res, it.arcane_res, "
    + ", ".join(f"it.stat_type{n}, it.stat_value{n}" for n in range(1, 11))
)

# The worn read: one row per worn slot with everything gearscore reads, plus
# the entry and inventory type gearupgrades lays the slots out by. `{holes}`
# is one placeholder per name; the first parameter is the slot bound.
WORN_COLUMNS = (
    "ii.itemEntry AS entry, it.InventoryType AS inventory_type, "
    "it.name AS item_name, " + _STAT_COLUMNS
)
WORN_SQL = (
    "SELECT c.name, ci.slot, it.fire_res, it.ItemLevel AS item_level, "  # noqa: S608 - constants only
    + WORN_COLUMNS
    + " FROM characters c JOIN character_inventory ci ON ci.guid = c.guid "
    "AND ci.bag = 0 AND ci.slot < %s JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes})"
)
# item_template rows for every item the lists name; `{holes}` one per id.
LIST_SQL = (
    "SELECT it.entry, it.name AS item_name, it.InventoryType AS inventory_type, "  # noqa: S608 - constants only
    "it.fire_res, " + _STAT_COLUMNS + " FROM acore_world.item_template it "
    "WHERE it.entry IN ({holes})"
)


def every_list_id() -> list[int]:
    """Every item id any spec's pre-raid or raid list names, sorted."""
    ids: set[int] = set()
    for spec in gearscore.spec_ids():
        ids.update(gearupgrades.all_list_ids(spec))
    return sorted(ids)


def _share(member: dict, rows: list, item_rows: dict) -> float | None:
    cid = member.get("class_id")
    tree = member.get("spec")
    if tree is None:
        tree = raidroles.tree_of(cid, member.get(raidroles.KEY))
    # A row with no item entry (a realm whose read fell back to the thin
    # query) cannot be scored; no scorable row is "not read", not zero.
    rows = [r for r in rows if r.get("entry") is not None]
    if not rows or not item_rows:
        return None
    slim = {
        "name": member.get("name"),
        "class": raidlineup.CLASS_NAMES.get(cid),
        "level": member.get("level"),
        "spec": {"primary": tree or None},
    }
    built = gearupgrades.build(slim, rows, item_rows, list(armory.EQUIPPED_SLOTS))
    ready = built.get("ready")
    return None if not ready else ready.get("pct")


def readiness_by_name(members: list, worn_rows: list, item_rows: dict) -> dict:
    """name -> share of scored slots at or near pre-raid best in slot, or None.

    `worn_rows` are WORN_SQL rows; `item_rows` maps item id to the LIST_SQL
    row of every id the lists name (every_list_id).
    """
    by_name: dict = {}
    for row in worn_rows or ():
        by_name.setdefault(row.get("name"), []).append(row)
    return {
        m["name"]: _share(m, by_name.get(m["name"], []), item_rows or {})
        for m in members
        if m.get("name")
    }


def attach(members: list, worn_rows: list, item_rows: dict) -> list:
    """The members, each with `readiness` (a share or None) for the lineup."""
    shares = readiness_by_name(members, worn_rows, item_rows)
    return [dict(m, readiness=shares.get(m.get("name"))) for m in members]


def percent(share) -> str:
    return "not read" if share is None else "%d%%" % round(share * 100)


def short_reason(share) -> str | None:
    """Why this share keeps a raider from being ready, or None when it does not."""
    if share is None:
        return "pre-raid gear not read"
    if share < READY_SHARE:
        return "pre-raid gear %s, needs %d%%" % (
            percent(share),
            round(READY_SHARE * 100),
        )
    return None
