"""Regenerate racespells.py's table from the worldserver's SkillLineAbility.dbc.

The core refuses to teach a spell that no SkillLineAbility row of the spell
allows the character's race and class (Player::IsSpellFitByClassAndRace), and
every `*_dbc` table in acore_world is empty, so the rule has to be frozen
into the repo like the other DBC books.

USAGE

    kubectl -n wow-dev exec <worldserver-pod> -c worldserver -- \\
      cat /azerothcore/env/dist/data/dbc/SkillLineAbility.dbc > SkillLineAbility.dbc
    python3 tools/race_spells_from_dbc.py SkillLineAbility.dbc > racespells_table.txt

As of 2026-10-29 the file's md5 is d8c11abfcfe70596cb9068c0e97a1d9a. Paste
the output over the ROWS block in racespells.py.

SkillLineAbility fields: ID, SkillLine, Spell, RaceMask, ClassMask. Only a
spell with at least one row that names a race is kept; every other spell fits
every race.
"""

from __future__ import annotations

import collections
import struct
import sys


def rows_by_spell(path: str) -> dict:
    with open(path, "rb") as f:
        magic, records, fields, recsize, _ = struct.unpack("<4s4I", f.read(20))
        assert magic == b"WDBC" and recsize == fields * 4, path
        out = collections.defaultdict(list)
        for _ in range(records):
            row = struct.unpack(f"<{fields}I", f.read(recsize))
            out[row[2]].append((row[3], row[4]))
    return out


def main(path: str) -> None:
    by_spell = rows_by_spell(path)
    for spell in sorted(by_spell):
        rows = sorted(set(by_spell[spell]))
        if any(race for race, _ in rows):
            print("    %d: %r," % (spell, tuple(rows)))


if __name__ == "__main__":
    main(sys.argv[1])
