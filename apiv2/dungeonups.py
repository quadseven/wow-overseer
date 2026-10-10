"""GET /api/v2/dungeonups: what a dungeon drops that beats what a family wears.

    /api/v2/dungeonups?family=grug&dungeon=36
      -> [{map_id, dungeon, member, slot, item, boss, gain, worn, worn_ilvl,
           req, now}]

`dungeon` is a map id and may be left out, which answers for every dungeon at
once (each row says its own `map_id`), so the guild's path can count the
upgrades on every row without one read per row.

ONE DEFINITION OF AN UPGRADE, AND IT IS NOT THIS MODULE'S. The verdict is
`recap.verdict`, the same one the loot board uses, over the dungeon plan's
reads (`_fetch_dungeonplan`), so "beats what is worn" cannot mean two things
on two pages. This module adds one thing: a drop the member is not yet
high enough for (the verdict says `locked`) is asked again at the level it
needs, and when it would beat what is worn then, it is listed with `now`
false and `req` the level it needs. Only drops up to LOOKAHEAD levels ahead
are listed that way; beyond that a reader cannot act on them this week.

`gain` is item levels over the item worn in that slot, or the drop's whole
item level when the slot is empty (`worn` is null then). One row per member
and slot: the drop with the biggest gain, as a member wears one item there.
"""

from __future__ import annotations

import dungeonplan
import recap
from apiv2 import _allow

LOOKAHEAD = 5


def _gain(verdict: dict, ilvl: int) -> int | None:
    if verdict["verdict"] == recap.UPGRADE:
        return int(verdict.get("gain") or 0)
    if verdict["verdict"] == recap.EMPTY:
        return ilvl
    return None


def judge(row: dict, member: dict) -> tuple[dict, int | None, bool]:
    """(verdict, gain, wearable now) for one drop and one member.

    A locked drop within LOOKAHEAD levels is judged again at its own required
    level, with everything else about the member unchanged.
    """
    ilvl = int(row.get("item_level") or 0)
    verdict = recap.verdict(row, member)
    if verdict["verdict"] in dungeonplan.GAIN_VERDICTS:
        return verdict, _gain(verdict, ilvl), True
    if verdict["verdict"] != recap.LOCKED:
        return verdict, None, False
    required = int(row.get("required_level") or 0)
    if required > int(member.get("level") or 0) + LOOKAHEAD:
        return verdict, None, False
    later = recap.verdict(row, dict(member, level=required))
    return later, _gain(later, ilvl), False


def _item(row: dict, icons: dict) -> dict:
    payload = recap.item_payload(int(row["Item"]), row, icons)
    return {k: payload.get(k) for k in ("entry", "name", "quality", "icon", "ilvl")}


def _row(map_id, names, member, verdict, gain, now, row, boss, icons) -> dict:
    return {
        "map_id": map_id,
        "dungeon": names.get(map_id) or "",
        "member": member["name"],
        "slot": verdict["slot"],
        "item": _item(row, icons),
        "boss": boss,
        "gain": gain,
        "worn": verdict.get("worn"),
        "worn_ilvl": verdict.get("worn_ilvl"),
        "req": int(row.get("required_level") or 0) or None,
        "now": now,
    }


def ups_on(map_id: int, index: tuple, members: list, icons: dict, names: dict) -> list:
    """Every member's best upgrade per slot on one map, biggest gain first."""
    boss_name, bosses_on, by_creature = index
    best: dict = {}
    for creature in sorted(bosses_on.get(map_id, ())):
        rows = [
            r
            for r in by_creature.get(creature, [])
            if recap.slots_for(r.get("inventory_type"))
        ]
        for row, member in ((r, m) for r in rows for m in members):
            verdict, gain, now = judge(row, member)
            key = (member["name"], verdict["slot"])
            if gain is None or gain <= 0 or (key in best and best[key]["gain"] >= gain):
                continue
            boss = boss_name.get(creature) or ""
            best[key] = _row(
                map_id, names, member, verdict, gain, now, row, boss, icons
            )
    return sorted(best.values(), key=lambda r: (-r["gain"], r["member"], r["slot"]))


def build(
    fetched: dict, head: str, map_id: int | None, icons: dict, names: dict
) -> list:
    roster = fetched["families"][head]
    members = recap.family_members(
        fetched["char_rows"], fetched["equipped_rows"], roster, fetched["skill_rows"]
    )
    index = dungeonplan._index(fetched["encounter_rows"], fetched["loot_rows"])
    maps = [map_id] if map_id is not None else sorted(index[1])
    out: list = []
    for m in maps:
        out += ups_on(int(m), index, members, icons, names)
    return out


def _arg(query: dict, key: str) -> str:
    return (query.get(key) or [""])[0].strip()


def dungeonups(query: dict, ctx) -> tuple[int, object]:
    family, dungeon = _arg(query, "family"), _arg(query, "dungeon")
    if not family:
        return 400, {"error": "say family="}
    # Nothing from the query reaches SQL here: the family is matched against
    # the roster's own heads below, and the map id only filters rows in
    # memory. The shapes are still checked first, before the world is read.
    if not _allow.name(family):
        return 400, {"error": "family= is a family head's name"}
    map_id = None
    if dungeon:
        if not dungeon.isdigit() or len(dungeon) > 5:
            return 400, {"error": "dungeon= is a map id"}
        map_id = int(dungeon)
    server = ctx.server
    fetched = server._fetch_dungeonplan()
    heads = {h.lower(): h for h in fetched["families"]}
    head = heads.get(family.lower())
    if head is None:
        return 404, {"error": "no such family", "families": sorted(heads.values())}
    names = server.achievements.MAP_NAMES
    return 200, build(fetched, head, map_id, server.ITEMS.icons, names)


ROUTES = {"/api/v2/dungeonups": dungeonups}
