"""World-coordinate -> map-fraction transforms for the live map.

Geometry comes from the committed zones.json + entrances.json sitting flat
beside this module (the image build's shared-dir copy takes top-level files
only - tools/gen_geometry.py documents the generation and the axis
convention: +X north, +Y west, hence both axes flip into screen fractions).

Regions are almost continents: maps 0/1/530/571 plus the two exile regions
(Quel'Thalas, Azuremyst) that are physically on map 530 but far outside
Outland proper. place() routes a map-530 character to whichever region's
extent contains them.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

CONTINENT_IDS = {0, 1, 530, 571}


def _inside(region: dict, x: float, y: float) -> bool:
    return region["right"] <= y <= region["left"] and region["bottom"] <= x <= region["top"]


def _fraction(region: dict, x: float, y: float) -> tuple[float, float]:
    u = (region["left"] - y) / (region["left"] - region["right"])
    v = (region["top"] - x) / (region["top"] - region["bottom"])
    return u, v


@dataclass(frozen=True)
class Geometry:
    continents: dict
    entrances: dict

    @classmethod
    def load(cls, static_dir: str) -> "Geometry":
        with open(os.path.join(static_dir, "zones.json")) as f:
            continents = json.load(f)["continents"]
        with open(os.path.join(static_dir, "entrances.json")) as f:
            entrances = json.load(f)
        return cls(continents=continents, entrances=entrances)

    def _regions_for(self, map_id: int):
        """Exile regions first (smaller, specific), then the map itself."""
        for key, region in self.continents.items():
            if region.get("parent_map") == map_id:
                yield key, region
        region = self.continents.get(str(map_id))
        if region:
            yield str(map_id), region

    def to_fraction(self, map_id: int, x: float, y: float) -> tuple[float, float]:
        return _fraction(self.continents[str(map_id)], x, y)

    def place(self, map_id: int, x: float, y: float):
        """(region_key, u, v) for any character position, or None.

        Continent dwellers place in whichever region contains them (exile
        regions checked first); a point in none of them clamps into the
        map's own region rather than drawing off-canvas. Instance dwellers
        surface at their instance's overworld entrance; an instance with no
        known entrance places nowhere - the caller counts those instead of
        guessing.
        """
        if map_id in CONTINENT_IDS:
            fallback = None
            for key, region in self._regions_for(map_id):
                if _inside(region, x, y):
                    return key, *_fraction(region, x, y)
                fallback = (key, region)
            key, region = fallback
            u, v = _fraction(region, x, y)
            return key, min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)
        entrance = self.entrances.get(str(map_id))
        if not entrance:
            return None
        return self.place(entrance["map"], entrance["x"], entrance["y"])

    def zone_by_id(self, zone_id) -> str | None:
        """The zone the WORLD says a character is in, by its area id.

        The core writes `GetZoneId()` into the snapshot beside the position,
        and that id is the game's own answer. zone_name() below is a guess
        from bounding rectangles, and the rectangles overlap: Felwood's box
        is smaller than Winterspring's and covers the west of it, so a
        character standing in Winterspring was captioned "in Felwood". None
        when the id is 0 or not a zone this file draws, so the caller can
        fall back to the guess rather than print nothing.
        """
        try:
            wanted = int(zone_id or 0)
        except (TypeError, ValueError):
            return None
        if not wanted:
            return None
        for region in self.continents.values():
            for z in region["zones"]:
                if z.get("area_id") == wanted:
                    return z["name"]
        return None

    def zone_name(self, map_id: int, x: float, y: float) -> str:
        """Smallest zone rectangle containing the point, or the region name.

        Zone rectangles overlap (subzones inside parents); smallest wins.
        Exile-region zones are searched too - they belong to map 530.
        """
        best = None
        best_area = None
        fallback = "an unknown place"
        for _, region in self._regions_for(map_id):
            fallback = region["name"] if fallback == "an unknown place" else fallback
            for z in region["zones"]:
                if _inside(z, x, y):
                    area = (z["left"] - z["right"]) * (z["top"] - z["bottom"])
                    if best_area is None or area < best_area:
                        best, best_area = z["name"], area
        return best or fallback
