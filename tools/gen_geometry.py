"""Generate the map geometry JSON from client data (one-time, committed).

Inputs (3.3.5a client data v20.0 - frozen forever, so outputs are committed
rather than built per-run):
  WorldMapArea.dbc          zone/continent rectangles in world coordinates
  AreaTrigger.dbc           trigger positions (id, map, x, y, z, ...)
  areatrigger_teleport.tsv  trigger id -> target map (from acore_world)

Outputs (into the service dir root - the image build's shared-dir copy
takes top-level files only, so these stay flat beside the code):
  zones.json      continents with extents + zone rectangles
  entrances.json  instance map id -> overworld entrance point

World-coordinate convention (the part everyone gets backwards): +X is NORTH
and +Y is WEST. A WorldMapArea row's locLeft/locRight are the MAX/MIN world
Y of the rectangle, locTop/locBottom the MAX/MIN world X. Screen-fraction
conversion therefore flips both axes:
  u = (left - y) / (left - right)      # 0 at west edge, 1 at east
  v = (top - x) / (top - bottom)       # 0 at north edge, 1 at south

Usage: python3 gen_geometry.py <dbc_dir> <teleport_tsv> <out_dir>
"""
from __future__ import annotations

import json
import struct
import sys

CONTINENTS = {0: "Eastern Kingdoms", 1: "Kalimdor", 530: "Outland", 571: "Northrend"}

# The Blood Elf and Draenei lands are PHYSICALLY on map 530 in 3.3.5, so
# WorldMapArea files them under Outland - but they sit far outside Outland
# proper, so folding them into one extent would render everyone off-canvas
# (or squash Outland to nothing). They become their own regions, matched by
# the dbc's internal zone names (frozen data, explicit is honest).
EXILE_REGIONS = {
    "quelthalas": {"name": "Quel'Thalas",
                   "zones": {"EversongWoods", "Ghostlands", "SilvermoonCity", "Sunwell"}},
    "azuremyst": {"name": "Azuremyst Isles",
                  "zones": {"AzuremystIsle", "TheExodar", "BloodmystIsle"}},
}


def read_dbc(path: str) -> tuple[list[tuple], bytes]:
    with open(path, "rb") as f:
        magic, records, fields, recsize, strsize = struct.unpack("<4s4I", f.read(20))
        assert magic == b"WDBC", path
        assert recsize == fields * 4, (path, recsize, fields)
        rows = [struct.unpack(f"<{fields}I", f.read(recsize)) for _ in range(records)]
        strings = f.read(strsize)
    return rows, strings


def cstr(strings: bytes, offset: int) -> str:
    end = strings.index(b"\x00", offset)
    return strings[offset:end].decode("utf-8", "replace")


def as_float(u: int) -> float:
    return struct.unpack("<f", struct.pack("<I", u))[0]


def main(dbc_dir: str, teleport_tsv: str, out_dir: str) -> None:
    # WorldMapArea (3.3.5): ID, mapID, areaID, name, locLeft, locRight,
    # locTop, locBottom, displayMapID, defaultDungeonFloor, parentWorldMapID
    rows, strings = read_dbc(f"{dbc_dir}/WorldMapArea.dbc")
    continents: dict[str, dict] = {}
    for r in rows:
        _, map_id, area_id, name_ofs = r[0], r[1], r[2], r[3]
        left, right, top, bottom = (as_float(r[i]) for i in range(4, 8))
        if map_id not in CONTINENTS:
            continue
        if area_id == 0:
            # The overview row is NOT usable as the extent: for maps 0 and 1
            # it is the whole-world Azeroth rectangle (both continents side
            # by side), which would squash each continent into a strip.
            continue
        name = cstr(strings, name_ofs)
        zone = {"area_id": area_id, "name": name,
                "left": left, "right": right, "top": top, "bottom": bottom}
        region_key = str(map_id)
        for key, spec in EXILE_REGIONS.items():
            if map_id == 530 and name in spec["zones"]:
                region_key = key
        c = continents.setdefault(region_key, {
            "name": EXILE_REGIONS[region_key]["name"] if region_key in EXILE_REGIONS
                    else CONTINENTS[map_id],
            "zones": [],
        })
        if region_key in EXILE_REGIONS:
            c["parent_map"] = 530
        c["zones"].append(zone)
    # Every region's extent is the union of its zones - the one definition
    # under which "every zone fits its region" holds by construction.
    for c in continents.values():
        c["left"] = max(z["left"] for z in c["zones"])
        c["right"] = min(z["right"] for z in c["zones"])
        c["top"] = max(z["top"] for z in c["zones"])
        c["bottom"] = min(z["bottom"] for z in c["zones"])

    # AreaTrigger (3.3.5): ID, mapID, x, y, z, radius, box fields
    trows, _ = read_dbc(f"{dbc_dir}/AreaTrigger.dbc")
    triggers = {
        r[0]: {"map": r[1], "x": as_float(r[2]), "y": as_float(r[3])} for r in trows
    }
    targets = {}
    with open(teleport_tsv) as f:
        for line in f:
            tid, tmap = line.split()
            targets[int(tid)] = int(tmap)

    # Pass 1: triggers standing on a continent name their target's entrance.
    entrances: dict[str, dict] = {}
    for tid, tmap in targets.items():
        trig = triggers.get(tid)
        if not trig or tmap in CONTINENTS or trig["map"] not in CONTINENTS:
            continue
        entrances.setdefault(str(tmap), {"map": trig["map"], "x": trig["x"], "y": trig["y"]})
    # Pass 2 (transitive): an instance entered from inside another instance
    # inherits the outer instance's entrance (e.g. raid wings).
    for tid, tmap in targets.items():
        trig = triggers.get(tid)
        if not trig or str(tmap) in entrances or tmap in CONTINENTS:
            continue
        outer = entrances.get(str(trig["map"]))
        if outer:
            entrances[str(tmap)] = dict(outer)

    with open(f"{out_dir}/zones.json", "w") as f:
        json.dump({"continents": continents}, f, indent=1, sort_keys=True)
    with open(f"{out_dir}/entrances.json", "w") as f:
        json.dump(entrances, f, indent=1, sort_keys=True)
    print(f"continents: {len(continents)}  zones: {sum(len(c['zones']) for c in continents.values())}  entrances: {len(entrances)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
