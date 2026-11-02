"""Validate routing's computed danger snapshot for the read-only API.

No death query or scoring rule lives here. An older module, stale snapshot or
malformed answer stays unknown rather than becoming a measured empty list.
"""

from __future__ import annotations


def _number(row: dict, key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"invalid danger field: {key}")
    return value


def normalize(result) -> dict:
    """Validate the native projection without filtering or rescoring it."""
    if not isinstance(result, dict) or not isinstance(result.get("zones"), list):
        raise ValueError("worldserver has not reported zone danger")
    out = {
        key: _number(result, key)
        for key in (
            "map_id",
            "party_level",
            "sampled_at",
            "window_seconds",
            "level_gap",
            "threshold",
        )
    }
    if not out["party_level"]:
        raise ValueError("routing party level is unavailable")
    zones = []
    for row in result["zones"]:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("invalid danger zone")
        zone = {
            key: _number(row, key)
            for key in (
                "zone_id",
                "score",
                "deaths_counted",
                "strongest_killer",
            )
        }
        zones.append(dict(zone, name=row["name"]))
    return dict(out, zones=zones)
