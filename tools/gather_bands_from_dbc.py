"""Regenerate gatherband.py's MINING_BANDS / HERBALISM_BANDS from Lock.dbc.

infra#3789. "Is anything here within reach of this skill value" needs the
per-node skill requirement, and that number lives in `Lock.dbc`.
`acore_world.lock_dbc` is EMPTY on this realm - the same hole as `skillline_dbc`
and `skilllineability_dbc` - so it is not readable from the world DB at all.
It IS readable from the worldserver's own client data, which is what this reads.

Same shape and same reasoning as `tools/spell_focus_from_dbc.py`: CI runs the
suite stdlib-only with no cluster access, so a checked-in projection is the only
form of the server's answer a pull request can be gated on.

USAGE

    POD=$(kubectl get pods -n wow-dev -l app=worldserver \\
          -o jsonpath='{.items[0].metadata.name}')
    kubectl cp -n wow-dev -c worldserver \\
      "$POD:/azerothcore/env/dist/data/dbc/Lock.dbc" ./Lock.dbc
    python3 tools/gather_bands_from_dbc.py ./Lock.dbc

VERIFY THE COPY BEFORE TRUSTING IT. `md5sum` the local file against the pod's
own `md5sum` of the same path; a partial `kubectl cp` is a truncated file that
parses far enough to produce plausible nonsense. As of 2026-09-19:

    Lock.dbc  74ddd0458e50a1d65acb78700b45e4d1

ON A GIT BASH HOST, `md5sum` INSIDE THE POD NEEDS THE PATH ESCAPED. MSYS
rewrites a leading `/` into a Windows path, so
`kubectl exec ... -- md5sum /azerothcore/...` silently becomes
`C:/Program Files/Git/azerothcore/...` and reports "No such file". Use a
double leading slash (`//azerothcore/...`), which MSYS leaves alone.
`MSYS_NO_PATHCONV=1` also works for the exec but breaks `KUBECONFIG=~/...`
resolution in the same command, so the double slash is the safer of the two.

THE LAYOUT. Lock.dbc is 33 uint32 fields, 132 bytes per record:

    field 0       ID
    fields 1-8    Type[8]     1 = ITEM, 2 = LOCKTYPE
    fields 9-16   Index[8]    when Type == 2, a LockType.dbc id
    fields 17-24  Skill[8]    the required skill value
    fields 25-32  Action[8]

Only `Type == 2` entries carry a skill requirement, and only LockType 2
(Herbalism) and 3 (Mining) are professions this family can raise by walking
somewhere. Picklock, fishing poles and quest locks are deliberately dropped.

A BAND OF 0 IS A REAL ANSWER. Copper Vein (lock 38) and Peacebloom/Silverleaf
(lock 29) both read 0, meaning no minimum, which is why Mining 1 can mine
copper. It is not the same as "absent", which means the lock is not a node of
that profession at all.

THE ANCHORS THIS ASSERTS, so a bad parse cannot quietly produce a new table:
copper 38 -> mining 0, tin 39 -> 65, silver 40 -> 75, iron 41 -> 125,
gold 42 -> 155, mithril 379 -> 175, earthroot 30 -> herbalism 15.
Note truesilver (380) reads **205**, not the 230 that is widely repeated for
it - which is exactly why this is measured rather than typed.
"""

from __future__ import annotations

import pathlib
import struct
import sys

LOCKTYPE_HERBALISM = 2
LOCKTYPE_MINING = 3
SKILL_OF_LOCKTYPE = {LOCKTYPE_HERBALISM: "herbalism", LOCKTYPE_MINING: "mining"}

TYPE_LOCKTYPE = 2
N_SLOTS = 8

# (lock id, skill, expected band). A parse that cannot reproduce these is not
# one to read new facts off.
ANCHORS = (
    (38, "mining", 0),
    (39, "mining", 65),
    (40, "mining", 75),
    (41, "mining", 125),
    (42, "mining", 155),
    (379, "mining", 175),
    (380, "mining", 205),
    (29, "herbalism", 0),
    (30, "herbalism", 15),
    (45, "herbalism", 125),
)


def load(path: pathlib.Path) -> dict:
    """{lock_id: {skill_name: band}} for every lock that gates a profession."""
    blob = path.read_bytes()
    if len(blob) < 20:
        raise SystemExit("%s is too short to be a DBC" % path)
    magic, count, fields, record_size, _ = struct.unpack("<4sIIII", blob[:20])
    if magic != b"WDBC":
        raise SystemExit("%s is not a DBC (magic %r)" % (path, magic))
    if fields * 4 != record_size:
        raise SystemExit(
            "field count %d disagrees with record size %d" % (fields, record_size)
        )
    if fields != 33:
        raise SystemExit(
            "expected the 33-field 3.3.5a Lock.dbc, got %d fields" % fields
        )

    out: dict = {}
    for i in range(count):
        off = 20 + i * record_size
        row = struct.unpack("<%dI" % fields, blob[off : off + record_size])
        lock_id = row[0]
        types = row[1 : 1 + N_SLOTS]
        index = row[1 + N_SLOTS : 1 + 2 * N_SLOTS]
        skills = row[1 + 2 * N_SLOTS : 1 + 3 * N_SLOTS]
        for slot in range(N_SLOTS):
            if types[slot] != TYPE_LOCKTYPE:
                continue
            skill_name = SKILL_OF_LOCKTYPE.get(index[slot])
            if skill_name is None:
                continue
            out.setdefault(lock_id, {})[skill_name] = int(skills[slot])
    return out


def check_anchors(table: dict) -> None:
    for lock_id, skill_name, expected in ANCHORS:
        got = table.get(lock_id, {}).get(skill_name)
        if got != expected:
            raise SystemExit(
                "anchor failed: lock %d %s should read %d, read %r. The parse "
                "is wrong; do not use this output."
                % (lock_id, skill_name, expected, got)
            )


def emit(table: dict, skill_name: str) -> str:
    pairs = sorted(
        (
            (lock, bands[skill_name])
            for lock, bands in table.items()
            if skill_name in bands
        ),
        key=lambda kv: (kv[1], kv[0]),
    )
    return "\n".join("    %d: %d," % pair for pair in pairs)


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = pathlib.Path(argv[1])
    if path.is_dir():
        path = path / "Lock.dbc"
    table = load(path)
    check_anchors(table)
    print("# anchors pass; %d locks gate a gathering profession" % len(table))
    print("\nMINING_BANDS = {")
    print(emit(table, "mining"))
    print("}")
    print("\nHERBALISM_BANDS = {")
    print(emit(table, "herbalism"))
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
