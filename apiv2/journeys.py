"""GET /api/v2/journeys?guild=cave&name=Grug: every epic item copy's journey.

    {guild, name, journeys: [{item_guid, item, steps, council, ending, flags,
     who, guilds, at, since}], more, empty, basis}

One journey per item copy (its guid), newest first: where it dropped and how
it was won, the loot council's decision with its candidates and scores, every
trade and mail, every equip, and how it ended (worn, in bags, sold to a
vendor and for how much). `flags` holds one plain line for each decision
worth a human look. Every sentence is written by epicjourney, a pure module;
this handler only reads.

`guild` keeps the journeys that touch a family guild's member; `name` keeps
the journeys a character took part in. Either is refused before any read
when it is outside the family guilds. `item` is the same payload the loot
stories draw (name, quality, icon, tooltip). Every `at` is Unix seconds from
the database's own clock.

FIVE READS, each bounded: the epic copies (by the loot, hand-over and equip
kinds' own index), their rows, the vendor sales of their entries (a sale has
no guid), the council rows for their guids, and the family guilds' members
with class and level, which say who could have used a copy. A realm without
the event or council table answers with no journeys.
"""

from __future__ import annotations

import achievements
import epicjourney
import recap
from apiv2 import _scope
from armory import QUALITY_NAMES, UNKNOWN_QUALITY

# Far more rows than LIMIT journeys need; every read is bounded.
MAX_ROWS = 5000
MAX_COPIES = 400

EPICS_SQL = (
    "SELECT DISTINCT item_guid, subject_id FROM overseer_event "
    "WHERE kind IN ('item_loot', 'loot_won', 'item_given', 'item_equip') "
    "AND subject_quality >= %s AND item_guid > 0 "
    "ORDER BY item_guid DESC LIMIT %s"
)
EVENTS_SQL = (
    "SELECT id, character_name, kind, subject_id, subject_name, subject_quality, "  # noqa: S608
    "detail, map, zone, UNIX_TIMESTAMP(first_seen) AS at, prior_state, prior_name, "
    "item_guid, counterpart, via, source FROM overseer_event "
    "WHERE kind IN ('item_loot', 'loot_won', 'item_given', 'item_equip', 'tidy') "
    "AND item_guid IN ({guids}) ORDER BY id LIMIT %s"
)
SALES_SQL = (
    "SELECT id, character_name, kind, subject_id, detail, map, zone, "  # noqa: S608
    "UNIX_TIMESTAMP(first_seen) AS at FROM overseer_event "
    "WHERE kind = 'vendor_sale' AND subject_id IN ({entries}) ORDER BY id LIMIT %s"
)
COUNCIL_SQL = (
    "SELECT council_key, kind, family, source, item_entry, item_name, item_quality, "  # noqa: S608
    "candidates, heuristic, heuristic_why, status, recipient, reason, decided_by, "
    "given_to, item_guid, outcome FROM overseer_loot_council "
    "WHERE item_guid IN ({guids}) LIMIT %s"
)
MEMBERS_SQL = (
    "SELECT c.name, c.class, c.level, g.name AS guild FROM guild_member gm "  # noqa: S608
    "JOIN characters c ON c.guid = gm.guid JOIN guild g ON g.guildid = gm.guildid "
    "WHERE g.name IN ({guilds})"
)
# The template columns the item card and can_use read; the map server's own
# list when it has one, so the tooltip matches the loot stories'.
ITEMS_SQL = (
    "SELECT it.entry, {columns} FROM acore_world.item_template it "  # noqa: S608
    "WHERE it.entry IN ({entries})"
)
COLUMNS = (
    "it.name AS item_name, it.Quality AS quality, it.ItemLevel AS item_level, "
    "it.RequiredLevel AS required_level, it.displayid, it.class, it.subclass, "
    "it.InventoryType AS inventory_type, it.AllowableClass AS allowable_class"
)


def _item(j: dict, items: dict, icons: dict, book) -> dict:
    item = achievements.item_payload(j["entry"], items, icons, book)
    if j["entry"] not in items:
        # The world database did not answer: the name the module recorded is the truth.
        item["name"] = j["name"] or item["name"]
        item["quality"] = j["quality"]
        item["quality_name"] = QUALITY_NAMES.get(j["quality"], UNKNOWN_QUALITY)
    return item


def _zones(server) -> dict:
    geo = getattr(server, "GEO", None)
    return recap.zone_names(geo.continents) if geo is not None else {}


def read(rd, server, guild_names: list) -> dict:
    """The rows epicjourney.build takes, from the realm."""
    copies = rd.rows(EPICS_SQL, (epicjourney.EPIC, MAX_COPIES), what="the epic copies")
    guids = sorted({int(r["item_guid"]) for r in copies})
    entries = sorted({int(r["subject_id"]) for r in copies})
    out = {"rows": [], "sales": [], "council": [], "members": [], "items": {}}
    holes = _scope.holes
    if guild_names:
        out["members"] = rd.must(
            MEMBERS_SQL.format(guilds=holes(len(guild_names))), tuple(guild_names)
        )
    if not guids:
        return out
    gh, eh = holes(len(guids)), holes(len(entries))
    out["rows"] = rd.rows(
        EVENTS_SQL.format(guids=gh), (*guids, MAX_ROWS), what="the epic journeys"
    )
    out["sales"] = rd.rows(
        SALES_SQL.format(entries=eh), (*entries, MAX_ROWS), what="the epic sales"
    )
    out["council"] = rd.rows(
        COUNCIL_SQL.format(guids=gh), (*guids, MAX_ROWS), what="the loot council"
    )
    columns = getattr(server, "_ITEM_TEMPLATE_COLUMNS", COLUMNS)
    found = rd.must(ITEMS_SQL.format(columns=columns, entries=eh), tuple(entries))
    out["items"] = {int(r["entry"]): r for r in found}
    return out


def journeys(query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/journeys?guild=cave&name=Grug - every epic item copy's journey: drop, roll, council, hand-overs, equips, ending."""
    asked = (query.get("guild") or [""])[0].strip()
    name = _scope.wanted_name(query).strip()
    if asked and _scope.guild(ctx, asked) is None:
        return 404, _scope.no_such_guild(ctx)
    if name and not _scope.name_shaped(name):
        return 400, {"error": "not a character name"}
    if name and not _scope.may_answer(ctx, name):
        return 404, _scope.NOT_A_MEMBER
    guild = _scope.guild(ctx, asked) if asked else ""
    server = ctx.server
    got = read(ctx.read, server, sorted(_scope.guilds(ctx).values()))
    built = epicjourney.build(
        got["rows"],
        sales=got["sales"],
        council=got["council"],
        members=got["members"],
        items=got["items"],
        zones=_zones(server),
        families=ctx.families.families(),
    )
    shown = epicjourney.pick(built, guild=guild, name=name)
    items = getattr(server, "ITEMS", None)
    icons = getattr(items, "icons", {}) if items is not None else {}
    for j in shown[: epicjourney.LIMIT]:
        j["item"] = _item(j, got["items"], icons, items)
    return 200, {
        "guild": guild,
        "name": name,
        "journeys": shown[: epicjourney.LIMIT],
        "more": max(0, len(shown) - epicjourney.LIMIT),
        "empty": epicjourney.EMPTY,
        "basis": epicjourney.BASIS,
    }


ROUTES = {"/api/v2/journeys": journeys}
