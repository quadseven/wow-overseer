"""Project Molten Core capability facts from a Standing export and Spell.dbc.

Usage: python3 tools/mc_spell_facts.py TRAINING_EXPORT Spell.dbc > mc-spells.next.json
Inspect a successful generation before replacing data/mc-spells.json.
The export is the name-keyed collection of /api/v2/training responses. Only
class, spell and trainer ReqLevel are retained, never character identities.
A partial export is accepted only when every required first rank is present.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys

# First trainer ranks, not talent spells or the aura applied by a totem.
SPELLS = {
    "Druid": (2782,),
    "Mage": (475, 118, 2139),
    "Paladin": (4987, 19891),
    "Priest": (527, 6346),
    "Shaman": (370, 57994, 8143, 8184),
    "Warlock": (710,),
    "Hunter": (1499, 19801),
    "Rogue": (6770, 1766),
    "Warrior": (72, 6552, 18499),
    "Death Knight": (47528,),
}
BOSSES = (19703, 19702, 19716, 19713, 19714, 19659, 19776)


def dbc_rows(blob: bytes) -> dict:
    if len(blob) < 20:
        raise ValueError("truncated DBC header")
    magic, count, fields, size, strings = struct.unpack_from("<4s4I", blob)
    end = 20 + count * size
    if magic != b"WDBC" or fields <= 136 or size != fields * 4:
        raise ValueError("unexpected Spell.dbc format")
    if len(blob) != end + strings:
        raise ValueError("truncated Spell.dbc")
    rows = {}
    for i in range(count):
        row = struct.unpack_from("<%dI" % fields, blob, 20 + i * size)
        offset = end + row[136]
        stop = blob.find(b"\0", offset)
        if not end <= offset < len(blob) or stop < 0:
            raise ValueError("invalid spell name offset")
        rows[row[0]] = {"name": blob[offset:stop].decode(), "dispel": row[2]}
    return rows


def _member_levels(member: dict, required: tuple, levels: dict) -> None:
    for state in ("learned", "trainable", "needs", "above"):
        for row in member.get("spells", {}).get(state, ()):
            spell, level = row["spell"], row["level"]
            if spell not in required:
                continue
            if type(level) is not int or level <= 0:
                raise ValueError("invalid trainer level for spell %s" % spell)
            old = levels.get(spell)
            if old is not None and old != level:
                raise ValueError("conflicting trainer levels for spell %s" % spell)
            levels[spell] = level


def project(training: dict, spells: dict) -> dict:
    levels = {name: {} for name in SPELLS}
    for member in training.values():
        klass = member.get("class")
        if klass in SPELLS:
            _member_levels(member, SPELLS[klass], levels[klass])
    learned = {}
    for klass, required in SPELLS.items():
        learned[klass] = {}
        for spell in required:
            if spell not in levels[klass] or spell not in spells:
                raise ValueError("missing required trainer/DBC spell %s" % spell)
            learned[klass][str(spell)] = {
                "level": levels[klass][spell],
                "name": spells[spell]["name"],
            }
    bosses = {}
    for spell in BOSSES:
        if spell not in spells:
            raise ValueError("missing boss spell %s" % spell)
        bosses[str(spell)] = spells[spell]
    return {"learned": learned, "boss_spells": bosses}


def main() -> None:
    training = Path(sys.argv[1]).read_bytes()
    blob = Path(sys.argv[2]).read_bytes()
    facts = project(json.loads(training), dbc_rows(blob))
    facts["source"] = {
        "training": "Archived Standing training export; capture time not recorded",
        "query": "trainer_spell.SpellId and MIN(ReqLevel), class trainer Type = 0",
        "spell_dbc_md5": hashlib.md5(blob, usedforsecurity=False).hexdigest(),
    }
    print(json.dumps(facts, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
