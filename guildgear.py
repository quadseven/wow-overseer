"""Every family-guild member's gear on one table (the Lineup tab).

WHY A TABLE AND NOT THE ARMORY. The Armory draws one character at a time, and
the guild sections under it are a collapsed list of names. A reader asking
"who in the guild is badly geared" wants every member side by side, sorted by
what is wrong: no weapon, empty slots, a low average. This module turns one
read of every member's worn items into those rows. The page only draws them.

WHAT COUNTS. The 17 stat slots: every equipment slot but the shirt and the
tabard, which carry no stats. The average item level is over what is worn in
those 17. The weakest slot is the worn piece with the lowest item level. A
member without a main-hand weapon, or with EMPTY_WARN or more empty slots, is
flagged, and the flags come with the words the page prints.

PURE: rows in, rows out. No database, no clock.
"""

from __future__ import annotations

import raidroles
import wealth
from panel import CLASS_COLOURS, _CLASS_NAMES, _EQUIPMENT_SLOT_NAMES

COSMETIC = frozenset({"shirt", "tabard"})
STAT_SLOTS = tuple(s for s in _EQUIPMENT_SLOT_NAMES if s not in COSMETIC)
MAIN_HAND = "main hand"
# At or above this many empty stat slots, a member is flagged. Six is the
# campaign's own gear gate (the bridge holds a dungeon run for it).
EMPTY_WARN = 6
# ...but only from this level. Below it, a character wearing six or seven
# pieces is ordinary play, and flagging it flagged 139 of 142 members on the
# dev realm, which is the same as flagging nobody.
EMPTY_WARN_LEVEL = 20


def worst_first(m: dict) -> tuple:
    """Flagged first, then no weapon, most empty, lowest average, name."""
    return (not m["flags"], m["weapon"], -m["empty"], m["avg_item_level"], m["name"])


def _slot_name(slot):
    try:
        i = int(slot)
    except (TypeError, ValueError):
        return None
    if 0 <= i < len(_EQUIPMENT_SLOT_NAMES):
        return _EQUIPMENT_SLOT_NAMES[i]
    return None


def members_from_rows(rows: list[dict]) -> list[dict]:
    """One row per member, from one row per (member, worn slot).

    Each row carries guild_name, name, level, class_id, money, online, dead,
    talent_spells, and slot/item_level/item_name/item_entry for one worn item
    (all None for a member wearing nothing). Sorted worst first (`worst_first`).
    """
    by_name: dict = {}
    for r in rows or ():
        name = r.get("name")
        if not name:
            continue
        m = by_name.get(name)
        if m is None:
            m = by_name[name] = {"row": r, "worn": {}}
        slot = _slot_name(r.get("slot"))
        if slot is None or slot in COSMETIC:
            continue
        m["worn"][slot] = {
            "item_level": int(r["item_level"])
            if r.get("item_level") is not None
            else None,
            "name": r.get("item_name") or "",
            "entry": r.get("item_entry"),
        }
    out = [_member(m["row"], m["worn"]) for m in by_name.values()]
    out.sort(key=worst_first)
    return out


def _weakest(worn: dict):
    """The worn stat piece with the lowest item level, or None."""
    weakest = None
    for slot in STAT_SLOTS:
        w = worn.get(slot)
        if w is None or w["item_level"] is None:
            continue
        if weakest is None or w["item_level"] < weakest["item_level"]:
            weakest = {
                "slot": slot,
                "item_level": w["item_level"],
                "name": w["name"],
                "entry": w["entry"],
            }
    return weakest


def _presence(row: dict) -> str:
    if row.get("dead"):
        return "dead"
    return "online" if row.get("online") else "offline"


def _flags(weapon: bool, empty: int, level: int) -> list:
    flags = [] if weapon else ["no weapon"]
    if empty >= EMPTY_WARN and level >= EMPTY_WARN_LEVEL:
        flags.append("%d empty" % empty)
    return flags


def _member(row: dict, worn: dict) -> dict:
    class_id = row.get("class_id")
    levels = [w["item_level"] for w in worn.values() if w["item_level"] is not None]
    empty_slots = [s for s in STAT_SLOTS if s not in worn]
    weapon = MAIN_HAND in worn
    role = raidroles.role_of(
        {"class_id": class_id, raidroles.KEY: row.get(raidroles.KEY)}
    )
    return {
        "name": row["name"],
        "guild": row.get("guild_name") or "",
        "class": _CLASS_NAMES.get(class_id, ""),
        "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
        "level": int(row.get("level") or 0),
        "role": role or "",
        "avg_item_level": round(sum(levels) / len(levels), 1) if levels else 0.0,
        "worn": len(worn),
        "of": len(STAT_SLOTS),
        "empty": len(empty_slots),
        "empty_slots": empty_slots,
        "weapon": weapon,
        "weakest": _weakest(worn),
        "gold": wealth.coins(row.get("money")),
        "presence": _presence(row),
        "flags": _flags(weapon, len(empty_slots), int(row.get("level") or 0)),
    }


def build(rows: list[dict]) -> dict:
    """The payload: guilds in name order, each with its members worst first."""
    guilds: dict = {}
    for m in members_from_rows(rows):
        guilds.setdefault(m["guild"], []).append(m)
    return {
        "empty_warn": EMPTY_WARN,
        "empty_warn_level": EMPTY_WARN_LEVEL,
        "slots": len(STAT_SLOTS),
        "guilds": [
            {
                "name": name,
                "members": members,
                "flagged": sum(1 for m in members if m["flags"]),
            }
            for name, members in sorted(guilds.items())
        ],
    }
