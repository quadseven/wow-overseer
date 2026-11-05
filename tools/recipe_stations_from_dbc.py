"""Regenerate tests/recipe_stations.json from the server's own Spell.dbc.

The projection tests/test_recipe_stations.py holds every recipe table to:
spell id -> [RequiresSpellFocus, [RequiredTotemCategoryID...]]. CI has no DBC,
so the answer is checked in. Copy Spell.dbc out as tools/spell_focus_from_dbc.py
says and check its md5 first.

    python3 tools/recipe_stations_from_dbc.py <dir holding Spell.dbc>

RequiredTotemCategoryID is fields 222 and 223 of the 234-field 3.3.5a layout.
The anchor is Runed Copper Belt (2666): an Anvil and a Blacksmith Hammer.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

F_ID = 0
F_REQUIRES_SPELL_FOCUS = 18
F_TOTEM_CATEGORY = (222, 223)
OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "recipe_stations.json"


def main(argv):
    blob = (pathlib.Path(argv[1]) / "Spell.dbc").read_bytes()
    magic, rows, fields, size, _strings = struct.unpack_from("<4siiii", blob, 0)
    if magic != b"WDBC" or fields != 234:
        raise SystemExit("not the 3.3.5a Spell.dbc")
    spells = {}
    for row in range(rows):
        values = struct.unpack_from("<234I", blob, 20 + row * size)
        tools = [values[f] for f in F_TOTEM_CATEGORY if values[f]]
        spells[values[F_ID]] = [values[F_REQUIRES_SPELL_FOCUS], tools]
    assert spells[2666] == [1, [162]]
    assert spells[2657] == [3, []]

    sys.path.insert(0, str(OUT.parents[1]))
    sys.path.insert(0, str(OUT.parent))
    import test_recipe_stations  # noqa: E402

    wanted = sorted(test_recipe_stations.every_issued_spell())
    OUT.write_text(json.dumps({str(s): spells[s] for s in wanted}, indent=0) + "\n")
    print("%d spells written to %s" % (len(wanted), OUT.name))


if __name__ == "__main__":
    main(sys.argv)
