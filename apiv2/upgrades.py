"""GET /api/v2/upgrades?name=X: /api/upgrades, plus what to wear at this level, now.

THE SAME PAYLOAD AS /api/upgrades, extended and never changed: the map
server's _upgrades_payload builds it, with the same gate (a family guild
member, by the world's name rule), and this adds fields beside its own.

`now` PER SLOT is the best boss drop the member can wear today from a dungeon
open to them: the dungeon page's own cross product (dungeonplan, which borrows
recap.verdict), run for this one member. A dungeon is open when the world's
access table lets the member's level in, or names no minimum. A drop counts
when the verdict says it beats what is worn (or fills an empty slot) and the
member can hold it: class, armour grade, weapon skill and required level are
the verdict's checks. The gain is item levels, the verdict's own measure; an
empty slot gains the drop's whole item level. None when nothing open beats
what is worn.

`items` gives the quality and icon of every item the payload names, so the
page can draw each as an item link; the lists in data/bis carry neither.

The world rows (the catalogue, the bosses, their loot) do not change under a
running server, so they are read once per process.
"""

from __future__ import annotations

import threading

import achievements
import dungeonplan

from ._scope import NOT_A_MEMBER, guild_member, holes, wanted_name

_WORLD: dict = {}
_WORLD_LOCK = threading.Lock()

ITEMS_SQL = (
    "SELECT entry, Quality AS quality, displayid, ItemLevel AS item_level "
    "FROM acore_world.item_template WHERE entry IN ({holes})"
)

BASIS = (
    "At level {level}, now: the best boss drop in a dungeon open at this level "
    "that this member can wear and hold, by item level against what is worn. "
    "Quest rewards, vendors and crafts are not counted here."
)


def _world(ctx) -> dict:
    """The catalogue, encounter and loot rows, read once and kept."""
    with _WORLD_LOCK:
        if _WORLD:
            return _WORLD
        server, rd = ctx.server, ctx.read
        catalogue = rd.rows(
            server._PLAN_CATALOGUE,
            (),
            fallback=server._PLAN_CATALOGUE_OLD,
            what="dungeon_access_template",
        )
        maps = dungeonplan.map_ids(catalogue, achievements.MAP_NAMES)
        encounters, loot = [], []
        if maps:
            h = holes(len(maps))
            encounters = rd.rows(
                server._PLAN_ENCOUNTERS.format(holes=h),
                tuple(maps),
                what="instance_encounters",
            )
            loot = rd.rows(
                server._PLAN_LOOT.format(holes=h),
                tuple(maps),
                what="creature_loot_template",
            )
        if catalogue and loot:
            _WORLD.update(catalogue=catalogue, encounters=encounters, loot=loot)
        return {"catalogue": catalogue, "encounters": encounters, "loot": loot}


def fetch(ctx, name: str) -> dict:
    """The world rows and this member's own: level, worn gear, skills."""
    server = ctx.server
    rd = ctx.read
    world = _world(ctx)
    one = holes(1)
    chars = rd.rows(
        server._PLAN_CHARS.format(holes=one),
        (name,),
        fallback=server._PLAN_CHARS_OLD.format(holes=one),
        what="characters",
    )
    worn = rd.rows(
        server._RECAP_WORN.format(holes=one),
        (len(server.armory.EQUIPPED_SLOTS), name),
        what="character_inventory",
    )
    skills = rd.rows(
        server._RECAP_SKILLS.format(holes=one),
        (name,),
        what="character_skills",
    )
    return dict(world, chars=chars, worn=worn, skills=skills)


def item_rows(ctx, entries) -> list:
    """Quality, display and item level for each entry named."""
    entries = sorted({int(e) for e in entries if e})
    if not entries:
        return []
    return ctx.read.rows(
        ITEMS_SQL.format(holes=holes(len(entries))),
        tuple(entries),
        what="item_template",
    )


# --------------------------------------------------------------------- pure --


def best_now(plan: dict) -> dict:
    """slot -> the best gain in an open dungeon, from a one-member plan."""
    best: dict = {}
    for dungeon in plan.get("dungeons") or ():
        if dungeon.get("shut"):
            continue
        for found in dungeon.get("members") or ():
            for gain in found.get("gains") or ():
                _offer(best, dungeon, gain)
    return best


def _offer(best: dict, dungeon: dict, gain: dict) -> None:
    delta = gain.get("delta")
    worth = int(gain.get("ilvl") or 0) if delta is None else int(delta)
    if worth <= 0:
        return
    slot = gain.get("slot")
    held = best.get(slot)
    if held is not None and held["gain"] >= worth:
        return
    best[slot] = {
        "entry": gain.get("entry"),
        "name": gain.get("name"),
        "quality": gain.get("quality"),
        "icon": gain.get("icon"),
        "item_level": gain.get("ilvl"),
        "gain": worth,
        "empty": delta is None,
        "dungeon": dungeon.get("name"),
        "boss": gain.get("boss"),
        "where": "%s, %s" % (dungeon.get("name"), gain.get("boss")),
    }


def named_entries(payload: dict) -> set:
    """Every item entry the upgrades payload names."""
    out = set()
    for slot in payload.get("slots") or ():
        for block in (slot.get("worn"), slot.get("next")):
            if block and block.get("entry"):
                out.add(int(block["entry"]))
        for phase in (slot.get("targets") or {}).values():
            out.update(int(t["entry"]) for t in phase or () if t.get("entry"))
    return out


def extend(payload: dict, now: dict, items: dict, level: int) -> dict:
    """The /api/upgrades payload with `now` per slot, `items` and the basis."""
    out = dict(payload)
    slots = []
    for slot in payload.get("slots") or ():
        row = dict(slot)
        row["now"] = now.get(slot.get("slot"))
        slots.append(row)
    out["slots"] = slots
    out["level"] = level
    out["now_count"] = sum(1 for s in slots if s["now"])
    out["now_basis"] = BASIS.format(level=level)
    out["items"] = items
    return out


def item_index(rows, icons: dict) -> dict:
    """entry -> {quality, icon, item_level} for the page's item links."""
    return {
        str(int(r["entry"])): {
            "quality": r.get("quality"),
            "icon": icons.get(r.get("displayid"))
            if r.get("displayid") is not None
            else None,
            "item_level": r.get("item_level"),
        }
        for r in rows or ()
    }


# ------------------------------------------------------------------ handler --


def upgrades(query: dict, ctx) -> tuple[int, dict]:
    name = wanted_name(query)
    if not guild_member(ctx, name):
        return 404, dict(NOT_A_MEMBER)
    code, payload = ctx.server._upgrades_payload(name)
    if code != 200:
        return code, payload
    server = ctx.server
    f = fetch(ctx, name)
    plan = dungeonplan.build_dungeonplan(
        f["catalogue"],
        f["encounters"],
        f["loot"],
        f["chars"],
        f["worn"],
        server.ITEMS.icons,
        [name],
        achievements.MAP_NAMES,
        server.GEO.entrances,
        server.GEO.continents,
        f["skills"],
    )
    level = int((f["chars"] or [{}])[0].get("level") or payload.get("level") or 0)
    items = item_index(item_rows(ctx, named_entries(payload)), server.ITEMS.icons)
    return 200, extend(payload, best_now(plan), items, level)


ROUTES = {"/api/v2/upgrades": upgrades}
