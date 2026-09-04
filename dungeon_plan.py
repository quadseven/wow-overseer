"""Pure dungeon progression planner for the family page.

The HTTP adapter supplies catalog, roster, and loot rows.  This module owns
the judgements: which items are plausible upgrades, which dungeon is next,
and how much challenge the party can safely request.
"""
from __future__ import annotations


SAFE = "safe"
CHALLENGE = "challenge"
PUSH = "push"

DUNGEON_CATALOG = (
    {"map_id": 389, "name": "Ragefire Chasm", "level": 15, "order": 1},
    {"map_id": 43, "name": "Wailing Caverns", "level": 18, "order": 2},
    {"map_id": 36, "name": "The Deadmines", "level": 20, "order": 3},
    {"map_id": 33, "name": "Shadowfang Keep", "level": 22, "order": 4},
    {"map_id": 34, "name": "The Stockade", "level": 24, "order": 5},
    {"map_id": 48, "name": "Blackfathom Deeps", "level": 24, "order": 6},
    {"map_id": 90, "name": "Gnomeregan", "level": 28, "order": 7},
    {"map_id": 47, "name": "Razorfen Kraul", "level": 32, "order": 8},
    {"map_id": 189, "name": "Scarlet Monastery", "level": 38, "order": 9},
    {"map_id": 129, "name": "Razorfen Downs", "level": 40, "order": 10},
    {"map_id": 70, "name": "Uldaman", "level": 42, "order": 11},
    {"map_id": 209, "name": "Zul'Farrak", "level": 44, "order": 12},
    {"map_id": 349, "name": "Maraudon", "level": 48, "order": 13},
    {"map_id": 109, "name": "Sunken Temple", "level": 52, "order": 14},
    {"map_id": 230, "name": "Blackrock Depths", "level": 55, "order": 15},
    {"map_id": 229, "name": "Blackrock Spire", "level": 58, "order": 16},
    {"map_id": 289, "name": "Scholomance", "level": 58, "order": 17},
    {"map_id": 329, "name": "Stratholme", "level": 58, "order": 18},
    {"map_id": 429, "name": "Dire Maul", "level": 58, "order": 19},
)


def _level(item: dict) -> int:
    return int(item.get("item_level", item.get("ItemLevel", 0)) or 0)


def _entry(item: dict) -> int:
    return int(item.get("entry", item.get("item_id", 0)) or 0)


def _usable(item: dict, member: dict) -> bool:
    classes = item.get("classes")
    if classes and member.get("class") not in classes:
        return False
    roles = item.get("roles")
    return not roles or member.get("role") in roles


def item_targets(loot: list[dict], family: list[dict]) -> list[dict]:
    """Return each dungeon item with the family members it can improve."""
    result = []
    for item in loot:
        targets = []
        for member in family:
            if not _usable(item, member):
                continue
            equipped = member.get("equipped", {}).get(str(item.get("slot", "")), 0)
            carried = {_entry(row) for row in member.get("carried", [])}
            if _entry(item) in carried:
                continue
            if _level(item) > int(equipped or 0):
                targets.append({"name": member.get("name", ""),
                                "current_item_level": int(equipped or 0),
                                "upgrade": _level(item) - int(equipped or 0)})
        if targets:
            result.append({"entry": _entry(item), "name": item.get("name", ""),
                          "quality": int(item.get("quality", item.get("Quality", 0)) or 0),
                          "item_level": _level(item), "slot": item.get("slot", ""),
                          "targets": targets})
    return result


def challenge_for(party_level: int, dungeon: dict, mode: str = SAFE) -> dict:
    """Describe the level band without silently authorising an unsafe run."""
    minimum = int(dungeon.get("level_min", 1))
    recommended = int(dungeon.get("level", dungeon.get("level_max", minimum)) or minimum)
    deficit = max(0, recommended - int(party_level))
    allowed = {SAFE: 0, CHALLENGE: 3, PUSH: 6}.get(mode, 0)
    return {"mode": mode if mode in (SAFE, CHALLENGE, PUSH) else SAFE,
            "recommended_level": recommended, "deficit": deficit,
            "allowed_deficit": allowed, "eligible": deficit <= allowed}


def recommend_next(dungeons: list[dict], party_level: int,
                   completed_maps: set[int], mode: str = SAFE) -> dict | None:
    """Choose the first eligible unfinished dungeon with a useful upgrade."""
    for dungeon in sorted(dungeons, key=lambda row: int(row.get("order", 0))):
        map_id = int(dungeon.get("map_id", 0) or 0)
        if map_id in completed_maps:
            continue
        challenge = challenge_for(party_level, dungeon, mode)
        if challenge["eligible"]:
            return {"map_id": map_id, "name": dungeon.get("name", "Unknown dungeon"),
                    "challenge": challenge, "reason": dungeon.get("reason", "new dungeon")}
    return None


def build_payload(family: list[dict], completed_maps: set[int],
                  loot_by_map: dict[int, list[dict]] | None = None,
                  mode: str = SAFE) -> dict:
    """Build the page contract from already-fetched rows."""
    levels = [int(row.get("level") or 0) for row in family if row.get("level")]
    party_level = min(levels) if levels else 0
    loot_by_map = loot_by_map or {}
    dungeons = []
    for dungeon in DUNGEON_CATALOG:
        row = dict(dungeon)
        row["completed"] = dungeon["map_id"] in completed_maps
        row["loot"] = loot_by_map.get(dungeon["map_id"], [])
        dungeons.append(row)
    return {"party_level": party_level, "mode": mode,
            "dungeons": dungeons,
            "next": recommend_next(list(dungeons), party_level, completed_maps, mode),
            "loot_status": "verified rows only; missing rows are not inferred"}
