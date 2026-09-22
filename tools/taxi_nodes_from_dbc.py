"""Regenerate taxinodes.json from TaxiNodes.dbc.

infra#4206. "Which taxi node should this character go and learn" needs the
node's id, the map it is on, where it stands, and which side may use it. All
four live in `TaxiNodes.dbc`. `acore_world.taxinodes_dbc` is EMPTY on this
realm - the same hole as `lock_dbc`, `skillline_dbc` and `skilllineability_dbc`
- measured 2026-09-19:

    SELECT COUNT(*) FROM acore_world.taxinodes_dbc;      -> 0
    SELECT COUNT(*) FROM acore_world.taxipath_dbc;       -> 0
    SELECT COUNT(*) FROM acore_world.taxipathnode_dbc;   -> 0

so it is not readable from the world DB at all. It IS readable from the
worldserver's own client data, which is what this reads.

Same shape and same reasoning as `tools/gather_bands_from_dbc.py`: CI runs the
suite stdlib-only with no cluster access, so a checked-in projection is the
only form of the server's answer a pull request can be gated on.

USAGE

    POD=$(kubectl get pods -n wow-dev -l app=worldserver \\
          -o jsonpath='{.items[0].metadata.name}')
    kubectl cp -n wow-dev -c worldserver \\
      "$POD:/azerothcore/env/dist/data/dbc/TaxiNodes.dbc" ./TaxiNodes.dbc
    python3 tools/taxi_nodes_from_dbc.py ./TaxiNodes.dbc

VERIFY THE COPY BEFORE TRUSTING IT. `md5sum` the local file against the pod's
own `md5sum` of the same path; a partial `kubectl cp` is a truncated file that
parses far enough to produce plausible nonsense. As of 2026-09-19:

    TaxiNodes.dbc  3a870df7039a76607e31846237a1daec

ON A GIT BASH HOST, `md5sum` INSIDE THE POD NEEDS THE PATH ESCAPED. MSYS
rewrites a leading `/` into a Windows path, so
`kubectl exec ... -- md5sum /azerothcore/...` silently becomes
`C:/Program Files/Git/azerothcore/...` and reports "No such file". Use a
double leading slash (`//azerothcore/...`), which MSYS leaves alone.

THE LAYOUT. TaxiNodes.dbc is 24 uint32-wide fields, 96 bytes per record:

    field 0        ID
    field 1        ContinentID          the map the node stands on
    fields 2-4     X, Y, Z              floats, the node's own position
    field 5        Name_lang            offset into the string block (enUS)
    fields 6-21    the other 15 locales plus the locale flags word
    field 22       MountCreatureID[0]   the HORDE taxi mount, 0 if none
    field 23       MountCreatureID[1]   the ALLIANCE taxi mount, 0 if none

THE TWO MOUNT FIELDS ARE THE TEAM GATE AND THEY ARE THE ONLY ONE THERE IS.
`ObjectMgr::GetNearestTaxiNode` skips a node whose `MountCreatureID[team ==
TEAM_ALLIANCE ? 1 : 0]` is zero, which makes "is this node on my network" a
question about these two numbers and nothing else - not about the faction of
whatever creature happens to stand there. Measured against the live world
database on 2026-09-19, which is why it is read rather than assumed:

    node 39  Gadgetzan, Tanaris   mounts (0, 541)      Bera Stonehammer 7823
    node 40  Gadgetzan, Tanaris   mounts (2224, 0)     Bulkrek Ragefist 7824

Two nodes, one town, 180 yards apart, one per side. Reading the pair backwards
would send an Alliance family to a flight master that will never speak to them,
which is an errand that cannot finish - and infra#3703's rule is that one of
those must not hold the family's single travel column.

A NODE WITH NEITHER MOUNT IS KEPT, NOT DROPPED. TaxiNodes.dbc carries rows that
are not flight points at all - "Quest - Caverns of Time (Intro Flight Path)",
"Filming" (node 168, which mod-overseer's own comment names as the trap) - and
some of them do carry mounts. Dropping rows here would bake a judgement into
the DATA, where no test can see it. The team gate and the "is a flight master
actually standing here" gate both live in `flightlearn.py`, where they are
read, argued and tested.

THE ANCHORS THIS ASSERTS, so a bad parse cannot quietly produce a new table:
the four nodes above plus node 79 (Marshal's Refuge, Un'Goro Crater, both
mounts - a neutral goblin town) and node 80 (Ratchet, The Barrens, both).
Every one was read off the live realm on 2026-09-19 while investigating
infra#4206.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

HEADER = struct.Struct("<4sIIII")
MAGIC = b"WDBC"

# The field indices named in the layout note above.
FIELD_ID = 0
FIELD_MAP = 1
FIELD_NAME = 5
FIELD_MOUNT_HORDE = 22
FIELD_MOUNT_ALLIANCE = 23
FIELDS = 24

# Where X, Y and Z sit in the record, in bytes. Named rather than written as a
# bare 8:20 slice because they are the only FLOATS in a record this file
# otherwise reads as unsigned integers, and reading a float as a uint is the
# mistake that produces a plausible table.
POSITION_AT = 8
POSITION = struct.Struct("<3f")

# (node id, name, map, horde mount, alliance mount) read off the live realm.
ANCHORS = (
    (39, "Gadgetzan, Tanaris", 1, 0, 541),
    (40, "Gadgetzan, Tanaris", 1, 2224, 0),
    (79, "Marshal's Refuge, Un'Goro Crater", 1, 2224, 541),
    (80, "Ratchet, The Barrens", 1, 2224, 541),
    # mod_overseer.cpp's own worked example of a node nothing can ever
    # discover: it "carries an alliance mount id, and has a real taxi path to
    # Stormwind", and the nearest creature with UNIT_NPC_FLAG_FLIGHTMASTER is
    # 740 yards away. The mount id below is read, not quoted - it is the
    # anchor that proves field 23 is the Alliance one.
    (168, "Filming", 0, 0, 3837),
)


def parse(raw: bytes) -> list:
    """Every TaxiNodes.dbc record, in id order."""
    magic, records, fields, size, _strings = HEADER.unpack(raw[: HEADER.size])
    if magic != MAGIC:
        raise SystemExit("not a DBC: magic is %r, not %r" % (magic, MAGIC))
    if fields != FIELDS or size != FIELDS * 4:
        raise SystemExit(
            "TaxiNodes.dbc should be %d fields of 4 bytes; this one is %d "
            "fields of %d bytes, so the layout above no longer describes it"
            % (FIELDS, fields, size)
        )
    body = HEADER.size
    block = raw[body + records * size :]

    def text(offset: int) -> str:
        end = block.index(b"\x00", offset)
        return block[offset:end].decode("utf-8", "replace")

    out = []
    for index in range(records):
        record = raw[body + index * size : body + (index + 1) * size]
        values = struct.unpack("<%dI" % fields, record)
        x, y, z = POSITION.unpack(record[POSITION_AT : POSITION_AT + POSITION.size])
        out.append(
            {
                "id": int(values[FIELD_ID]),
                "map": int(values[FIELD_MAP]),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "name": text(values[FIELD_NAME]),
                "horde": int(values[FIELD_MOUNT_HORDE]),
                "alliance": int(values[FIELD_MOUNT_ALLIANCE]),
            }
        )
    out.sort(key=lambda node: node["id"])
    return out


def check(nodes: list) -> None:
    """Refuse a table that disagrees with what the live realm answered."""
    by_id = {node["id"]: node for node in nodes}
    for node_id, name, map_id, horde, alliance in ANCHORS:
        got = by_id.get(node_id)
        if got is None:
            raise SystemExit("node %d is missing - this is not TaxiNodes.dbc" % node_id)
        actual = (got["name"], got["map"], got["horde"], got["alliance"])
        if actual != (name, map_id, horde, alliance):
            raise SystemExit(
                "node %d reads %r and the live realm says %r - the field "
                "layout has moved" % (node_id, actual, (name, map_id, horde, alliance))
            )
    if len(nodes) != len(by_id):
        raise SystemExit(
            "TaxiNodes.dbc has duplicate ids, which the reader below indexes by"
        )


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    source = pathlib.Path(argv[1])
    nodes = parse(source.read_bytes())
    check(nodes)
    out = pathlib.Path(__file__).resolve().parents[1] / "taxinodes.json"
    out.write_text(
        json.dumps({"nodes": nodes}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("%s: %d node(s) from %s" % (out.name, len(nodes), source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
