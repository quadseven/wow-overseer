"""GET /api/v2/guildbank?guild=cave: a family guild's bank, tab by tab.

    {guild, tabs: [{tab, name, holds, used, total, items}], item_total,
     truncated}

Each item is the cell the bags read draws (vclient.item_cell: entry, name
from item_template, quality, icon, count) plus its slot and category. Nothing
about who deposited or owns an item is read. A tab with nothing in it has
`items: []`; a guild with no tab bought has `tabs: []`. Read-only, bound
parameters only, and at most MAX_ITEMS items are sent (`truncated` says when
more existed).
"""

from __future__ import annotations

import guildbank as bank_plan
import vclient
from apiv2 import _scope
from apiv2.guild import _GUILD_SQL as GUILD_SQL

# Six tabs of ninety-eight slots is the game's own ceiling.
MAX_TABS = 6
MAX_ITEMS = MAX_TABS * vclient.GUILD_BANK_TAB_SLOTS

TABS_SQL = (
    "SELECT TabId AS tab_id, TabName AS tab_name, TabIcon AS tab_icon "
    "FROM guild_bank_tab WHERE guildid = %s ORDER BY TabId LIMIT %s"
)
ITEMS_SQL = (
    "SELECT gbi.TabId AS tab_id, gbi.SlotId AS slot_id, "
    "ii.itemEntry AS entry, ii.count, it.name AS item_name, "
    "it.Quality AS quality, it.displayid, it.class AS item_class, "
    "it.subclass AS item_subclass "
    "FROM guild_bank_item gbi "
    "JOIN item_instance ii ON ii.guid = gbi.item_guid "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE gbi.guildid = %s ORDER BY gbi.TabId, gbi.SlotId LIMIT %s"
)


def build(tab_rows: list, item_rows: list, icons: dict) -> dict:
    tabs = {}
    for row in sorted(tab_rows, key=lambda r: r["tab_id"]):
        tab_id = int(row["tab_id"])
        tab = {
            "tab": tab_id,
            "name": row.get("tab_name") or "Tab %d" % (tab_id + 1),
            "items": [],
        }
        kept = bank_plan.TAB_BY_ID.get(tab_id)
        if kept is not None:
            tab["holds"] = kept.holds
        tabs[tab_id] = tab
    for row in item_rows[:MAX_ITEMS]:
        tab = tabs.get(int(row["tab_id"]))
        if tab is None:
            continue
        cell = vclient.item_cell(row, icons) | vclient.item_category(row)
        tab["items"].append({"slot": int(row["slot_id"]), **cell})
    for tab in tabs.values():
        tab["used"] = len(tab["items"])
        tab["total"] = vclient.GUILD_BANK_TAB_SLOTS
    return {
        "tabs": list(tabs.values()),
        "item_total": sum(t["used"] for t in tabs.values()),
        "truncated": len(item_rows) > MAX_ITEMS,
    }


def page(query: dict, ctx) -> tuple[int, dict]:
    asked = (query.get("guild") or [""])[0].strip()
    if not asked:
        return 400, {"error": "say guild="}
    name = _scope.guild(ctx, asked)
    if name is None:
        return 404, _scope.no_such_guild(ctx)
    found = ctx.read.must(GUILD_SQL, (name,))
    if not found:
        return 404, {"error": "no such guild", "guild": name}
    guild_id = found[0]["guildid"]
    tabs = ctx.read.must(TABS_SQL, (guild_id, MAX_TABS))
    # One past the cap, so a bank over it can say so.
    items = ctx.read.must(ITEMS_SQL, (guild_id, MAX_ITEMS + 1))
    icons = getattr(ctx.server, "CLIENT_ICONS", None) or {}
    return 200, {"guild": name, **build(tabs, items, icons)}


ROUTES = {"/api/v2/guildbank": page}
