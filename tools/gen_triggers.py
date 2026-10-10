"""Generate triggers.json: every teleporting areatrigger, from acore_world.

The module aims a family at a doorway as `trigger:<id>`, and the site has to
say which doorway that is. The answer is two world tables: `areatrigger` (the
map the trigger stands on) and `areatrigger_teleport` (the map it leads to).
Both are the pinned core's own data, so the join is done once and committed,
the way tools/gen_geometry.py commits entrances.json.

Input is the tab-separated output of:

    SELECT t.ID AS id, a.map, a.x, a.y, t.target_map,
           t.target_position_x AS to_x, t.target_position_y AS to_y
    FROM areatrigger_teleport t JOIN areatrigger a ON a.entry = t.ID
    ORDER BY t.ID

(`mysql -B acore_world -e "..."`). Usage: python3 gen_triggers.py <tsv> <out>
"""

from __future__ import annotations

import csv
import json
import sys


def build(rows) -> dict:
    out = {}
    for row in rows:
        out[str(int(row["id"]))] = {
            "map": int(row["map"]),
            "x": round(float(row["x"]), 1),
            "y": round(float(row["y"]), 1),
            "to_map": int(row["target_map"]),
            "to_x": round(float(row["to_x"]), 1),
            "to_y": round(float(row["to_y"]), 1),
        }
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: gen_triggers.py <teleport_tsv> <out_json>", file=sys.stderr)
        return 2
    with open(argv[1], newline="") as f:
        data = build(csv.DictReader(f, delimiter="\t"))
    with open(argv[2], "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
