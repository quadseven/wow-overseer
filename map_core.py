"""Pure payload builder for the live map: snapshot rows -> JSON-shaped dict.

The HTTP adapter (map_server.py) does IO and nothing else; everything the
page renders is decided here, which is the test seam.
"""

from __future__ import annotations

from core import _ALLIANCE_RACES, _HORDE_RACES
from transform import Geometry


def build_payload(rows: list[dict], geo: Geometry) -> dict:
    dots = []
    unplaced = 0
    freshest = None
    for r in rows:
        age = int(r["age_seconds"])
        freshest = age if freshest is None else min(freshest, age)
        placed = geo.place(r["map_id"], r["pos_x"], r["pos_y"])
        if placed is None:
            unplaced += 1
            continue
        continent, u, v = placed
        in_instance = str(r["map_id"]) != continent
        dots.append(
            {
                "name": r["name"],
                "level": r["level"],
                "continent": continent,
                "u": round(u, 4),
                "v": round(v, 4),
                "faction": "alliance"
                if r["race"] in _ALLIANCE_RACES
                else "horde"
                if r["race"] in _HORDE_RACES
                else "neutral",
                "zone": geo.zone_name(r["map_id"], r["pos_x"], r["pos_y"])
                if not in_instance
                else "inside an instance",
                "combat": bool(r["in_combat"]),
                "bot": bool(r["is_bot"]),
                "instance": in_instance,
            }
        )
    return {"dots": dots, "unplaced": unplaced, "freshest_seconds": freshest}
