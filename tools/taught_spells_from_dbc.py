"""Regenerate taughtspells.py's tables from Spell.dbc and the class trainer list.

A few class trainer rows are a learn spell, not the spell itself: Summon
Felsteed (1710) teaches Felsteed (5784) through SPELL_EFFECT_LEARN_SPELL, and
only the taught spell is written to character_spell. The bridge counted such a
row as owed forever (#792). Druid trainer spells whose Stances mask names only
the bear forms are the second table.

USAGE

1. Spell.dbc. The worldserver's copy is the public AzerothCore client data
   (wowgaming/client-data, Data.zip, dbc/Spell.dbc); check its md5 is
   543b9fe61355b6a77a01714d52fea2e5, the one craft.py and raidcraft.py were
   built from (the archive's SkillLineAbility.dbc matches racespells.py's
   d8c11abfcfe70596cb9068c0e97a1d9a too).

2. The class trainer list, read-only through the agent_reader route
   (quadseven/infra production/oke/manifests/wow-dev-agent-db-reader):

     SELECT DISTINCT t.Requirement, ts.SpellId
     FROM acore_world.trainer_spell ts
     JOIN acore_world.trainer t ON t.Id = ts.TrainerId WHERE t.Type = 0

   saved as two tab separated columns.

3. python3 tools/taught_spells_from_dbc.py Spell.dbc trainer_rows.tsv

Paste the output over the TAUGHT and BEAR_FORM_ONLY blocks in taughtspells.py.
"""

from __future__ import annotations

import struct
import sys

F_STANCES = 12
F_EFFECT = 71
F_EFFECT_TRIGGER_SPELL = 116
SPELL_EFFECT_LEARN_SPELL = 36
DRUID = 11
# Stances bits: 1 << (form - 1). Bear Form is form 5, Dire Bear Form form 8.
BEAR_MASK = (1 << 4) | (1 << 7)


def spell_fields(path: str):
    with open(path, "rb") as f:
        blob = f.read()
    magic, rows, fields, rowsize, _ = struct.unpack_from("<4s4I", blob)
    assert magic == b"WDBC" and rowsize == fields * 4, path
    index = {
        struct.unpack_from("<I", blob, 20 + r * rowsize)[0]: r for r in range(rows)
    }

    def get(spell, field):
        return struct.unpack_from("<I", blob, 20 + index[spell] * rowsize + field * 4)[
            0
        ]

    return index, get


def main(spell_path: str, trainer_path: str) -> None:
    index, get = spell_fields(spell_path)
    # Anchors: the learn effect of Summon Felsteed and Bash's bear-only mask.
    assert get(1710, F_EFFECT) == SPELL_EFFECT_LEARN_SPELL
    assert get(1710, F_EFFECT_TRIGGER_SPELL) == 5784
    assert get(5211, F_STANCES) == BEAR_MASK
    rows = set()
    with open(trainer_path) as f:
        for line in f:
            if line.strip():
                klass, spell = line.split()[:2]
                rows.add((int(klass), int(spell)))
    taught, bear = {}, set()
    for klass, spell in sorted(rows):
        if spell not in index:
            continue
        learns = tuple(
            get(spell, F_EFFECT_TRIGGER_SPELL + i)
            for i in range(3)
            if get(spell, F_EFFECT + i) == SPELL_EFFECT_LEARN_SPELL
        )
        if learns and learns != (spell,):
            taught[spell] = learns
        stances = get(spell, F_STANCES)
        if klass == DRUID and stances and not stances & ~BEAR_MASK:
            bear.add(spell)
    print("TAUGHT = {")
    for spell in sorted(taught):
        print("    %d: %r," % (spell, taught[spell]))
    print("}")
    print("BEAR_FORM_ONLY = frozenset({")
    for spell in sorted(bear):
        print("    %d," % spell)
    print("})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
