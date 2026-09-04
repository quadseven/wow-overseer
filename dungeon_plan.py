"""Pure dungeon progression planner for the family page.

The HTTP adapter supplies catalog, roster, and loot rows.  This module owns
the judgements: which items are plausible upgrades, which dungeon is next,
and how much challenge the party can safely request.
"""
from __future__ import annotations


SAFE = "safe"
CHALLENGE = "challenge"
PUSH = "push"


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
