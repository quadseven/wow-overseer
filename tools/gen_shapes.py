"""Turn the zone RECTANGLES into zone REGIONS (one-time, committed).

`gen_geometry.py` reads the client's WorldMapArea.dbc and writes zones.json:
one axis-aligned rectangle per zone, in world coordinates. Those rectangles
are what place the dots, and they are correct for that. Drawn as rectangles
they are a mess - a city box sits INSIDE its zone box, neighbouring zones
share margin, and every box overshoots the real land into open sea. The page
drew 25 overlapping outlines and called it Eastern Kingdoms.

This turns the same rows into a map. Two rules do the work:

  1. The SMALLEST box containing a point wins. A point in both Ironforge and
     Dun Morogh is in Ironforge - the tighter box is the more specific claim.
  2. Everything is clipped to a coastline. A zone's outer edge then becomes
     shoreline instead of a rectangle corner, which is the whole difference
     between a quilt and a map.

The coastlines below are hand-drawn: the DBC has no landmass geometry, only
rectangles. They are stylised, not traced - the higher-fidelity path is the
client's own map art (Interface/WorldMap/<AreaName>/*.blp), indexed by these
same WorldMapArea rows, which would drop into the identical coordinate frame.

Input:  zones.json   (already committed; frozen 3.3.5a client data)
Output: shapes.json  (committed beside it - same reasoning, frozen input)

Usage: python3 gen_shapes.py <service_dir>
"""

from __future__ import annotations

import json
import math
import os
import sys

# Grid resolution across the continent's width. 170 puts a cell at roughly
# 60 world yards on Eastern Kingdoms - fine enough that a smoothed boundary
# reads as a coast, coarse enough that the traced output stays a few KB.
GRID_W = 170

# A WorldMapArea row whose rectangle is this small (as a fraction of the
# continent) is a place rather than a region: no cell can fall inside a
# zero-area box, so tracing one yields nothing. Those become map markers.
POINT_AREA = 0.00035

# Normalised 0..1, x east and y south - the frame the page already uses
# (u from world Y, v from world X; see gen_geometry.py's axis note). Each
# entry is a list of rings, because some regions are more than one island.
COASTS: dict[str, list[list[tuple[float, float]]]] = {
    # Lordaeron, Khaz Modan and Azeroth, down to Stranglethorn's tail.
    "0": [
        [
            (0.09, 0.10),
            (0.14, 0.05),
            (0.26, 0.03),
            (0.38, 0.06),
            (0.50, 0.03),
            (0.62, 0.05),
            (0.74, 0.02),
            (0.86, 0.06),
            (0.95, 0.09),
            (0.99, 0.16),
            (0.95, 0.22),
            (0.90, 0.20),
            (0.93, 0.27),
            (0.86, 0.33),
            (0.82, 0.38),
            (0.86, 0.44),
            (0.83, 0.50),
            (0.87, 0.56),
            (0.80, 0.60),
            (0.75, 0.66),
            (0.79, 0.72),
            (0.76, 0.78),
            (0.70, 0.84),
            (0.62, 0.87),
            (0.57, 0.90),
            (0.60, 0.96),
            (0.55, 0.99),
            (0.44, 0.99),
            (0.38, 0.94),
            (0.36, 0.87),
            (0.30, 0.83),
            (0.22, 0.81),
            (0.13, 0.76),
            (0.09, 0.70),
            (0.14, 0.65),
            (0.11, 0.61),
            (0.17, 0.55),
            (0.20, 0.50),
            (0.26, 0.46),
            (0.33, 0.43),
            (0.37, 0.38),
            (0.35, 0.34),
            (0.42, 0.32),
            (0.44, 0.29),
            (0.38, 0.28),
            (0.30, 0.27),
            (0.22, 0.25),
            (0.15, 0.28),
            (0.07, 0.25),
            (0.05, 0.17),
        ]
    ],
    # Kalimdor, with Teldrassil riding offshore rather than fused to the coast.
    "1": [
        [
            (0.44, 0.16),
            (0.55, 0.13),
            (0.68, 0.14),
            (0.80, 0.17),
            (0.90, 0.22),
            (0.95, 0.30),
            (1.00, 0.36),
            (0.96, 0.43),
            (0.92, 0.48),
            (0.94, 0.55),
            (0.88, 0.60),
            (0.90, 0.66),
            (0.84, 0.72),
            (0.86, 0.78),
            (0.90, 0.84),
            (0.87, 0.92),
            (0.80, 0.98),
            (0.68, 1.00),
            (0.58, 0.97),
            (0.50, 0.93),
            (0.42, 0.94),
            (0.34, 0.90),
            (0.28, 0.85),
            (0.20, 0.82),
            (0.10, 0.78),
            (0.04, 0.72),
            (0.08, 0.66),
            (0.14, 0.62),
            (0.09, 0.56),
            (0.16, 0.50),
            (0.22, 0.46),
            (0.20, 0.40),
            (0.26, 0.36),
            (0.22, 0.30),
            (0.28, 0.24),
            (0.32, 0.19),
        ],
        [
            (0.30, 0.01),
            (0.40, 0.03),
            (0.46, 0.08),
            (0.42, 0.13),
            (0.32, 0.15),
            (0.22, 0.12),
            (0.18, 0.07),
            (0.22, 0.03),
        ],
    ],
    # Outland is a shattered world, so its edge is deliberately ragged - a
    # smooth oval would read as an island, which is the one thing it is not.
    "530": [
        [
            (0.14, 0.14),
            (0.26, 0.06),
            (0.40, 0.10),
            (0.52, 0.03),
            (0.66, 0.05),
            (0.78, 0.02),
            (0.88, 0.10),
            (0.95, 0.20),
            (0.90, 0.30),
            (0.96, 0.40),
            (0.88, 0.48),
            (0.94, 0.58),
            (0.98, 0.70),
            (0.92, 0.82),
            (0.84, 0.94),
            (0.72, 0.99),
            (0.60, 0.94),
            (0.50, 0.98),
            (0.38, 0.93),
            (0.28, 0.86),
            (0.18, 0.88),
            (0.08, 0.80),
            (0.04, 0.68),
            (0.10, 0.58),
            (0.03, 0.48),
            (0.08, 0.38),
            (0.04, 0.28),
            (0.10, 0.20),
        ]
    ],
    "571": [
        [
            (0.10, 0.30),
            (0.18, 0.22),
            (0.30, 0.18),
            (0.40, 0.12),
            (0.52, 0.10),
            (0.62, 0.14),
            (0.72, 0.10),
            (0.82, 0.16),
            (0.90, 0.24),
            (0.96, 0.34),
            (0.92, 0.44),
            (0.97, 0.54),
            (0.94, 0.66),
            (0.98, 0.78),
            (0.90, 0.88),
            (0.80, 0.95),
            (0.68, 0.92),
            (0.56, 0.96),
            (0.44, 0.90),
            (0.34, 0.94),
            (0.24, 0.88),
            (0.14, 0.82),
            (0.06, 0.72),
            (0.10, 0.62),
            (0.03, 0.52),
            (0.08, 0.42),
        ]
    ],
    "quelthalas": [
        [
            (0.30, 0.04),
            (0.50, 0.02),
            (0.68, 0.06),
            (0.80, 0.14),
            (0.86, 0.26),
            (0.82, 0.38),
            (0.90, 0.50),
            (0.86, 0.62),
            (0.90, 0.74),
            (0.82, 0.86),
            (0.68, 0.95),
            (0.52, 0.98),
            (0.36, 0.94),
            (0.24, 0.86),
            (0.16, 0.74),
            (0.20, 0.62),
            (0.12, 0.50),
            (0.18, 0.38),
            (0.12, 0.26),
            (0.20, 0.14),
        ]
    ],
    # Two islands, and they must stay two: Bloodmyst is reached by boat.
    "azuremyst": [
        [
            (0.30, 0.03),
            (0.48, 0.05),
            (0.62, 0.12),
            (0.68, 0.24),
            (0.62, 0.36),
            (0.48, 0.44),
            (0.32, 0.45),
            (0.18, 0.38),
            (0.10, 0.26),
            (0.14, 0.13),
        ],
        [
            (0.42, 0.46),
            (0.60, 0.44),
            (0.78, 0.48),
            (0.90, 0.58),
            (0.94, 0.72),
            (0.88, 0.86),
            (0.74, 0.96),
            (0.56, 0.99),
            (0.38, 0.95),
            (0.24, 0.86),
            (0.16, 0.72),
            (0.20, 0.58),
            (0.30, 0.50),
        ],
    ],
}

# Ground colour per zone. This is most of why a glance at the in-game map
# tells you where you are, and it is a judgement call, not data - the DBC
# carries no such thing. Desaturated on purpose so the result still reads as
# a chart rather than a screenshot.
TERRAIN = {
    "Tirisfal": "#8f9a72",
    "Silverpine": "#7d8c6b",
    "WesternPlaguelands": "#a5a271",
    "EasternPlaguelands": "#9c9463",
    "Undercity": "#c0ad83",
    "Alterac": "#cfd6d8",
    "Hilsbrad": "#b3bf85",
    "Arathi": "#c0bb7e",
    "Hinterlands": "#86a06d",
    "Wetlands": "#8ea977",
    "LochModan": "#a2b07a",
    "DunMorogh": "#d2dade",
    "Ironforge": "#c0ad83",
    "SearingGorge": "#b07a4f",
    "Badlands": "#c39468",
    "BurningSteppes": "#a3663f",
    "Stormwind": "#c0ad83",
    "Elwynn": "#9fb573",
    "Westfall": "#d3c07f",
    "Duskwood": "#6f7a64",
    "Redridge": "#bb8a63",
    "DeadwindPass": "#8b8489",
    "SwampOfSorrows": "#7f8f6c",
    "BlastedLands": "#b0755c",
    "Stranglethorn": "#789e64",
    "Teldrassil": "#a9b98d",
    "Darnassis": "#c0ad83",
    "Darkshore": "#8ba189",
    "Moonglade": "#96b283",
    "Winterspring": "#d4dde2",
    "Felwood": "#8b9a6a",
    "Aszhara": "#b8a06a",
    "Ashenvale": "#7f9970",
    "StonetalonMountains": "#a3a677",
    "Ogrimmar": "#c0ad83",
    "Durotar": "#c48a5e",
    "Desolace": "#a9a583",
    "Mulgore": "#b5c184",
    "ThunderBluff": "#c0ad83",
    "Barrens": "#cbb277",
    "Dustwallow": "#7c8b6d",
    "Feralas": "#8fae72",
    "ThousandNeedles": "#c99a63",
    "UngoroCrater": "#7ba465",
    "Silithus": "#ceb98d",
    "Tanaris": "#ddc98d",
    "Netherstorm": "#9a8fb0",
    "BladesEdgeMountains": "#c08a5a",
    "Zangarmarsh": "#7fa89a",
    "Hellfire": "#b5714c",
    "Nagrand": "#96b072",
    "TerokkarForest": "#8a9376",
    "ShattrathCity": "#c0ad83",
    "ShadowmoonValley": "#7a6c85",
    "TheStormPeaks": "#d6dee3",
    "IcecrownGlacier": "#c9d6de",
    "HrothgarsLanding": "#cdd8de",
    "ZulDrak": "#a8b39a",
    "SholazarBasin": "#8fae72",
    "CrystalsongForest": "#a89ec4",
    "LakeWintergrasp": "#c2d2da",
    "Dragonblight": "#c3ccd0",
    "GrizzlyHills": "#7f9a6d",
    "BoreanTundra": "#a8b58e",
    "HowlingFjord": "#8fa382",
    "Dalaran": "#c0ad83",
    "EversongWoods": "#c9b06a",
    "Sunwell": "#d8c583",
    "Ghostlands": "#8e8a72",
    "SilvermoonCity": "#c0ad83",
    "AzuremystIsle": "#9fb98f",
    "BloodmystIsle": "#b57a72",
    "TheExodar": "#c0ad83",
}
DEFAULT_TERRAIN = "#bfae86"

CITIES = {
    "Undercity",
    "Ironforge",
    "Stormwind",
    "Darnassis",
    "Ogrimmar",
    "ThunderBluff",
    "ShattrathCity",
    "Dalaran",
    "SilvermoonCity",
    "TheExodar",
}

# WorldMapArea names are directory names, so they arrive jammed together and
# a couple are misspelt in the client's own data. The map should say what the
# game says out loud, not what the folder is called.
NAMES = {
    "Hilsbrad": "Hillsbrad Foothills",
    "Ogrimmar": "Orgrimmar",
    "Aszhara": "Azshara",
    "Darnassis": "Darnassus",
    "Stranglethorn": "Stranglethorn Vale",
    "Elwynn": "Elwynn Forest",
    "Tirisfal": "Tirisfal Glades",
    "Silverpine": "Silverpine Forest",
    "Alterac": "Alterac Mountains",
    "Arathi": "Arathi Highlands",
    "Hinterlands": "The Hinterlands",
    "Redridge": "Redridge Mountains",
    "Barrens": "The Barrens",
    "Dustwallow": "Dustwallow Marsh",
    "UngoroCrater": "Un'Goro Crater",
    "Stormwind": "Stormwind City",
    "Hellfire": "Hellfire Peninsula",
    "IcecrownGlacier": "Icecrown",
    "HrothgarsLanding": "Hrothgar's Landing",
    "ZulDrak": "Zul'Drak",
    "LakeWintergrasp": "Wintergrasp",
    "BladesEdgeMountains": "Blade's Edge Mountains",
}


def pretty(name: str) -> str:
    if name in NAMES:
        return NAMES[name]
    out = ""
    for i, ch in enumerate(name):
        if i and ch.isupper() and not name[i - 1].isupper():
            out += " "
        out += ch
    return out


def inside(ring: list[tuple[float, float]], x: float, y: float) -> bool:
    """Even-odd ray cast. Rings are small (a few dozen points) and this runs
    once per grid cell per ring, which is cheap enough to keep obvious."""
    hit = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                hit = not hit
    return hit


def rdp(pts: list, eps: float) -> list:
    """Douglas-Peucker. Tracing a grid yields one point per cell edge -
    thousands of them, in long collinear runs. Dropping those BEFORE
    smoothing is what keeps shapes.json small enough to serve inline."""
    if len(pts) < 3:
        return pts
    x1, y1 = pts[0]
    x2, y2 = pts[-1]
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy)
    worst, wi = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = (
            abs(dy * px - dx * py + x2 * y1 - y2 * x1) / n
            if n
            else math.hypot(px - x1, py - y1)
        )
        if d > worst:
            worst, wi = d, i
    if worst <= eps:
        return [pts[0], pts[-1]]
    return rdp(pts[: wi + 1], eps)[:-1] + rdp(pts[wi:], eps)


def chaikin(pts: list, rounds: int) -> list:
    """Corner cutting. One round takes the staircase off without rounding the
    whole thing into a pebble - borders on a map are angular, not blobby."""
    for _ in range(rounds):
        out = []
        n = len(pts)
        for i in range(n):
            p, q = pts[i], pts[(i + 1) % n]
            out.append((p[0] * 0.75 + q[0] * 0.25, p[1] * 0.75 + q[1] * 0.25))
            out.append((p[0] * 0.25 + q[0] * 0.75, p[1] * 0.25 + q[1] * 0.75))
        pts = out
    return pts


def path(pts: list, sx: float, sy: float) -> str:
    """Emit into 1000 x 1000*aspect - the continent's TRUE proportions - so
    the page can place it with a single uniform scale. Emitting into a square
    1000x1000 box (the first cut) squashed every landmass to half height."""
    return "M" + " L".join("%.1f %.1f" % (p[0] * sx, p[1] * sy) for p in pts) + "Z"


def trace(cells: set, gw: int, gh: int) -> list[list]:
    """Boundary of a cell set, as closed loops of cell-corner points.

    Every cell edge whose neighbour is outside the set is a boundary segment,
    directed so the loops close; chaining them by endpoint yields one loop per
    connected component (plus one per hole)."""
    edges: dict = {}
    for i, j in cells:
        for di, dj, a, c in (
            (0, -1, (i, j), (i + 1, j)),
            (1, 0, (i + 1, j), (i + 1, j + 1)),
            (0, 1, (i + 1, j + 1), (i, j + 1)),
            (-1, 0, (i, j + 1), (i, j)),
        ):
            if (i + di, j + dj) not in cells:
                edges.setdefault(a, []).append(c)
    loops = []
    while edges:
        start = next(iter(edges))
        loop, cur = [start], start
        while True:
            nxts = edges.get(cur)
            if not nxts:
                break
            nxt = nxts.pop()
            if not nxts:
                del edges[cur]
            if nxt == start:
                break
            loop.append(nxt)
            cur = nxt
        if len(loop) > 14:
            loops.append(loop)
    loops.sort(key=len, reverse=True)
    return loops


def deepest(cells: set) -> tuple[tuple[int, int], int]:
    """Pole of inaccessibility: the cell furthest from any edge, by a BFS
    inward from the boundary. The centroid is wrong for any region that wraps
    another - the Barrens' centroid lands in Mulgore, and its label with it."""
    dist = {}
    frontier = []
    for i, j in cells:
        if any(
            (i + di, j + dj) not in cells
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))
        ):
            dist[(i, j)] = 0
            frontier.append((i, j))
    step = 0
    while frontier:
        step += 1
        nxt = []
        for i, j in frontier:
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (i + di, j + dj)
                if n in cells and n not in dist:
                    dist[n] = step
                    nxt.append(n)
        frontier = nxt
    if not dist:
        c = next(iter(cells))
        return c, 1
    best = max(dist, key=lambda p: dist[p])
    return best, max(dist[best], 1)


def classify(cont: dict) -> tuple[list, list, list]:
    """Normalise every WorldMapArea row into the 0..1 frame, and sort the
    three kinds apart: regions to draw, places to mark, and rows with no
    position at all."""
    span_y = cont["left"] - cont["right"]
    span_x = cont["top"] - cont["bottom"]
    boxes, points, dropped = [], [], []
    for z in cont["zones"]:
        if all(z[k] == 0.0 for k in ("left", "right", "top", "bottom")):
            # An all-zero row is the DBC's NULL, not the world origin.
            # Dalaran's row is exactly this - the city floats and the client
            # has nowhere to file it. Projected naively it lands in the sea
            # south of Northrend, and a gold capital marker bobbing offshore
            # is a fabrication, not a placement. Dropped, and SAID so: absent
            # data rendered as a position is the failure this epic keeps
            # relearning.
            dropped.append(z["name"])
            continue
        ul = (cont["left"] - z["left"]) / span_y
        ur = (cont["left"] - z["right"]) / span_y
        vt = (cont["top"] - z["top"]) / span_x
        vb = (cont["top"] - z["bottom"]) / span_x
        entry = {
            "name": z["name"],
            "id": z["area_id"],
            "l": ul,
            "r": ur,
            "t": vt,
            "b": vb,
            "a": (ur - ul) * (vb - vt),
            "cx": (ul + ur) / 2,
            "cy": (vt + vb) / 2,
        }
        (points if entry["a"] < POINT_AREA else boxes).append(entry)
    boxes.sort(key=lambda b: b["a"])  # smallest first -> first hit wins
    return boxes, points, dropped


def claim(rings: list, boxes: list, gw: int, gh: int) -> dict:
    """Both rules of the rewrite, on one grid: land only (rule 2), and the
    smallest box containing a cell wins it (rule 1). One owner per cell, so
    regions cannot overlap by construction."""
    owner: dict = {}
    for j in range(gh):
        y = (j + 0.5) / gh
        for i in range(gw):
            x = (i + 0.5) / gw
            if not any(inside(r, x, y) for r in rings):
                continue
            owner[(i, j)] = nearest_or_containing(boxes, x, y)
    return owner


def nearest_or_containing(boxes: list, x: float, y: float) -> int:
    for k, b in enumerate(boxes):
        if b["l"] <= x <= b["r"] and b["t"] <= y <= b["b"]:
            return k
    # Land no box claims - the rectangles overshoot into sea in places and
    # fall short in others. Give it to the nearest zone centre rather than
    # leaving holes in the continent.
    return min(
        range(len(boxes)),
        key=lambda k: (boxes[k]["cx"] - x) ** 2 + (boxes[k]["cy"] - y) ** 2,
    )


def outline(cells: set, gw: int, gh: int, sy: float) -> str:
    """Trace, simplify, smooth. Up to three loops: a zone can be more than
    one island, and past three the extras are grid noise."""
    ds = []
    for lp in trace(cells, gw, gh)[:3]:
        lp = rdp(lp + [lp[0]], 2.0)[:-1]
        if len(lp) < 4:
            continue
        ds.append(path(chaikin([(p[0] / gw, p[1] / gh) for p in lp], 1), 1000.0, sy))
    return " ".join(ds)


def region(box: dict, cells: set, gw: int, gh: int, sy: float) -> dict | None:
    """One drawable zone, or None if nothing of it survived - a zone whose
    ground was entirely taken by tighter boxes has no region to draw."""
    d = outline(cells, gw, gh, sy)
    if not d:
        return None
    deep, room = deepest(cells)
    return {
        "name": box["name"],
        "label": pretty(box["name"]),
        "id": box["id"],
        "d": d,
        "cx": round((deep[0] + 0.5) / gw * 1000.0, 1),
        "cy": round((deep[1] + 0.5) / gh * sy, 1),
        "room": round(room * 1000.0 / gw, 1),
        "fill": TERRAIN.get(box["name"], DEFAULT_TERRAIN),
        "city": box["name"] in CITIES,
        "cells": len(cells),
    }


def build(cid: str, cont: dict) -> dict:
    aspect = abs((cont["top"] - cont["bottom"]) / (cont["left"] - cont["right"]))
    gw = GRID_W
    gh = max(1, int(round(gw * aspect)))
    sy = 1000.0 * aspect
    boxes, points, dropped = classify(cont)
    owner = claim(COASTS[cid], boxes, gw, gh)

    zones = []
    for k, box in enumerate(boxes):
        got = region(box, {c for c, o in owner.items() if o == k}, gw, gh, sy)
        if got is not None:
            zones.append(got)
    marks = [
        {
            "name": p["name"],
            "label": pretty(p["name"]),
            "id": p["id"],
            "cx": round(p["cx"] * 1000.0, 1),
            "cy": round(p["cy"] * sy, 1),
            "city": True,
        }
        for p in points
    ]
    return {
        "name": cont["name"],
        "aspect": round(aspect, 4),
        "coast": [path(chaikin(r, 3), 1000.0, sy) for r in COASTS[cid]],
        "zones": zones,
        "marks": marks,
        "dropped": dropped,
    }


def generate(service_dir: str) -> dict:
    """Build every continent in memory. Separate from main() so the tests can
    regenerate and compare against the committed file - a committed artifact
    nobody can re-derive is a fact with no source."""
    with open(os.path.join(service_dir, "zones.json")) as f:
        continents = json.load(f)["continents"]
    missing = sorted(set(continents) - set(COASTS))
    if missing:
        # Loud, not silent: a continent with no coastline renders as empty
        # sea, and an empty tab looks exactly like a broken page.
        raise SystemExit(f"no coastline for: {', '.join(missing)}")
    return {cid: build(cid, continents[cid]) for cid in continents}


def main(service_dir: str) -> None:
    shapes = generate(service_dir)
    with open(os.path.join(service_dir, "shapes.json"), "w") as f:
        json.dump(shapes, f, separators=(",", ":"), sort_keys=True)
    for cid, r in sorted(shapes.items()):
        note = (
            ("  DROPPED (no position in the client data): " + ", ".join(r["dropped"]))
            if r["dropped"]
            else ""
        )
        print(
            "%-12s %-18s aspect %.3f  zones %2d  marks %d%s"
            % (cid, r["name"], r["aspect"], len(r["zones"]), len(r["marks"]), note)
        )


if __name__ == "__main__":
    main(
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
