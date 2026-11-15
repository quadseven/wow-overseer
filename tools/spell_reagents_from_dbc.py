"""Regenerate spellreagents.json from the worldserver's Spell.dbc (#2622).

CI and the bridge container run with no access to 48 MB client DBCs, so
checked-in projections (`craftbook.json`, `itemextendedcost.json`) carry the
server's DBC tables into the image (`Dockerfile`). This script extracts every
non-craft spell's Reagent_1..8 / ReagentCount_1..8 pairs into
`spellreagents.json` so `classreagents.load_spell_reagents` works identically
with or without Spell.dbc present, while `acore_world.spell_dbc` overrides apply
on top at runtime.

USAGE

    POD=$(kubectl -n "$NAMESPACE" get pods -l app=worldserver -o name | head -1)
    kubectl -n "$NAMESPACE" exec "${POD#pod/}" -c worldserver -- \\
      sh -c "cat /azerothcore/env/dist/data/dbc/Spell.dbc" > Spell.dbc
    python3 tools/spell_reagents_from_dbc.py ./Spell.dbc
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import classreagents
from world_data import DATA_ROOT

SPELL_DBC_MD5 = "543b9fe61355b6a77a01714d52fea2e5"

# Known Spell.dbc reagent anchors on 3.3.5a build 12340.
ANCHORS = {
    2963: ((2589, 2),),  # Bolt of Linen Cloth -> 2x Linen Cloth
    20608: ((17030, 1),),  # Reincarnation -> Ankh
    25898: ((21177, 1),),  # Greater Blessing of Kings -> Symbol of Kings
}


def generate(dbc_path: pathlib.Path, out_path: pathlib.Path | None = None) -> int:
    """Parse `dbc_path`, verify hash and anchors, and write `spellreagents.json`."""
    raw = dbc_path.read_bytes()
    actual_md5 = hashlib.md5(raw, usedforsecurity=False).hexdigest()
    if actual_md5 != SPELL_DBC_MD5:
        raise SystemExit(
            f"Spell.dbc md5 mismatch: got {actual_md5}, expected {SPELL_DBC_MD5}"
        )
    parsed = classreagents.parse_spell_dbc(raw)
    for sid, expected in ANCHORS.items():
        if parsed.get(sid) != expected:
            raise SystemExit(
                f"anchor spell {sid} read {parsed.get(sid)!r}, expected {expected!r}"
            )
    craft = classreagents.craft_spells()
    spells = {
        str(sid): [[int(entry), int(count)] for entry, count in pairs]
        for sid, pairs in sorted(parsed.items())
        if sid not in craft and pairs
    }
    target = out_path if out_path is not None else DATA_ROOT / "spellreagents.json"
    payload = json.dumps({"spells": spells}, sort_keys=True, separators=(",", ":"))
    target.write_bytes((payload + "\n").encode("utf-8"))
    return len(spells)


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 2:
        print(__doc__)
        return 2
    count = generate(pathlib.Path(argv[1]))
    print(f"wrote {count} non-craft reagent spells to spellreagents.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
