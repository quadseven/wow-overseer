"""Regenerate itemextendedcost.json from ItemExtendedCost.dbc.

#558. A vendor row in `npc_vendor` names an ExtendedCost id; what that id costs
(honor, arena points, token items) lives in the client's ItemExtendedCost.dbc.
`acore_world.itemextendedcost_dbc` is EMPTY on this realm, so the world DB
cannot answer. CI runs the suite with no cluster access, so a committed
projection is the form a pull request can be gated on (same reasoning as
`tools/taxi_nodes_from_dbc.py`).

USAGE

    POD=$(kubectl get pods -n wow-dev -l app=worldserver \\
          -o jsonpath='{.items[0].metadata.name}')
    kubectl cp -n wow-dev -c worldserver \\
      "$POD:/azerothcore/env/dist/data/dbc/ItemExtendedCost.dbc" ./ItemExtendedCost.dbc
    python3 tools/item_extended_cost_from_dbc.py ./ItemExtendedCost.dbc

Compare `md5sum` of the copy with the pod's own before trusting it. Read on
2026-10-04: 998c568fb2df87208a231e130970f278 (972 records).

THE LAYOUT. 16 uint32 fields, 64 bytes per record:

    0 ID   1 reqhonorpoints   2 reqarenapoints   3 reqarenaslot
    4-8 reqitem[5]   9-13 reqitemcount[5]   14 reqpersonalarenarating   15 unused

Rows that cost nothing are dropped. Output maps id -> [honor, arena, rating,
[[item, count], ...]].
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

HEADER = struct.Struct("<4sIIII")
FIELDS = 16

# id -> [honor, arena, rating, items], read off the live realm 2026-10-04.
ANCHORS = {
    5: [0, 0, 0, [[26045, 40], [26044, 2]]],
}


def parse(raw: bytes) -> dict:
    magic, records, fields, size, _strings = HEADER.unpack(raw[: HEADER.size])
    if magic != b"WDBC":
        raise SystemExit("not a DBC: magic is %r" % (magic,))
    if fields != FIELDS or size != FIELDS * 4:
        raise SystemExit(
            "ItemExtendedCost.dbc should be %d fields of 4 bytes; got %d of %d"
            % (FIELDS, fields, size)
        )
    out: dict = {}
    for i in range(records):
        at = HEADER.size + i * size
        v = struct.unpack("<%dI" % fields, raw[at : at + size])
        items = [[v[4 + n], v[9 + n]] for n in range(5) if v[4 + n] and v[9 + n]]
        if not (v[1] or v[2] or items):
            continue
        out[str(v[0])] = [v[1], v[2], v[14], items]
    return out


def check(costs: dict) -> None:
    for key, want in ANCHORS.items():
        if costs.get(str(key)) != want:
            raise SystemExit(
                "row %d reads %r, the live realm says %r - the layout moved"
                % (key, costs.get(str(key)), want)
            )


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    costs = parse(pathlib.Path(argv[1]).read_bytes())
    check(costs)
    out = pathlib.Path(__file__).resolve().parents[1] / "itemextendedcost.json"
    out.write_text(
        json.dumps({"costs": costs}, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print("%s: %d priced row(s)" % (out.name, len(costs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
