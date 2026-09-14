"""Regenerate tests/test_raidcraft.py's MEASURED_CONSUMABLES from the DBCs.

THE THIRD SIBLING OF `spell_focus_from_dbc.py` AND `spell_bands_from_dbc.py`,
and it answers a question neither of them can. Those two start from a SPELL ID
that `craft.RECIPES` already names and look up its fields. This one starts from
an ITEM NAME - "Flask of the Titans" - and has to find the spell that makes it,
which is the direction the brief that asked for raidcraft.py got wrong: it
listed "Brilliant Wizard Oil 20749", and 20749 is the item. The spell is 25129.

SO THE LOOKUP IS INVERTED ON PURPOSE. Every record in Spell.dbc is scanned for
a `SPELL_EFFECT_CREATE_ITEM` (Effect == 24) whose `EffectItemType` is the entry
in question, and an item nothing creates comes back with an EMPTY list rather
than with a plausible neighbour. That empty list is the answer for nine of the
brief's twenty-six items - the six Jujus, Rumsey Rum Black Label and Blessed
Wizard Oil - and `raidcraft.NOT_CRAFTED` is where it is written down.

WHAT THIS SCRIPT CANNOT DO, AND IT IS HALF THE TABLE. `Consumable.floor` is NOT
in these files. `SkillLineAbility.MinSkillLineRank` reads 1 for every one of
these recipes, because a recipe that is TAUGHT carries its rank in the world
DATABASE instead - `trainer_spell.ReqSkillRank`, or `RequiredSkillRank` on the
`Recipe:`/`Formula:`/`Plans:` item whose `spellid_2` teaches it. This script
prints the DBC half and prints a reminder of the two queries for the other
half; `tests/test_raidcraft.py`'s MEASURED_RANKS is the checked-in projection
of those, and it has no regenerator because it needs a live cluster.

USAGE - identical to its two siblings, and the same warning applies

    kubectl -n wow-dev exec <worldserver-pod> -c worldserver -- \\
      cat /azerothcore/env/dist/data/dbc/Spell.dbc > Spell.dbc
    kubectl -n wow-dev exec <worldserver-pod> -c worldserver -- \\
      cat /azerothcore/env/dist/data/dbc/SkillLineAbility.dbc > SkillLineAbility.dbc
    kubectl -n wow-dev exec <worldserver-pod> -c worldserver -- \\
      cat /azerothcore/env/dist/data/dbc/SpellFocusObject.dbc > SpellFocusObject.dbc
    python3 tools/raid_consumables_from_dbc.py <dir holding the three .dbc files>

`kubectl cp` is NOT used above on purpose: it refuses a Windows destination
path (the drive-letter colon reads as a pod separator) and a partial copy is a
truncated file that parses far enough to produce plausible nonsense. Stream it
and md5 it. As of 2026-09-14, unchanged since 2026-09-13:

    Spell.dbc             543b9fe61355b6a77a01714d52fea2e5
    SkillLineAbility.dbc  d8c11abfcfe70596cb9068c0e97a1d9a
    SpellFocusObject.dbc  797c65a49ae1e6336c9d851eb18011e0

A SPELL CAN CARRY MORE THAN ONE ABILITY ROW and `_row_for` keeps only the ones
this family's classes can match, exactly as `spell_bands_from_dbc.py` does and
for the reason its docstring gives. It matters more here, not less: EVERY
bandage above Linen Bandage carries the Death-Knight split, so a reader that
took the auto-learn row would conclude the family gets the whole First Aid
ladder for free.
"""
from __future__ import annotations

import pathlib
import struct
import sys

# 3.3.5a Spell.dbc offsets. See spell_focus_from_dbc.py on why 18 and not 23.
F_ID = 0
F_REQUIRES_SPELL_FOCUS = 18
F_REAGENT = 52
F_REAGENT_COUNT = 60
F_EQUIPPED_ITEM_CLASS = 68
F_EFFECT = 71
F_EFFECT_ITEM_TYPE = 107
F_NAME = 136

# 3.3.5a SkillLineAbility.dbc: 14 fields.
A_SKILL, A_SPELL, A_CLASSMASK = 1, 2, 4
A_REQ, A_ACQUIRE, A_GREY, A_YELLOW = 7, 9, 10, 11

# Every class the family actually plays, as a ClassMask. 0x20 is Death Knight.
FAMILY_CLASSES = 0x5DF

# SPELL_EFFECT_CREATE_ITEM. The one effect that makes a spell a recipe.
CREATE_ITEM = 24


def _load(path: pathlib.Path):
    blob = path.read_bytes()
    magic, rows, fields, rowsize, _strings = struct.unpack_from("<4siiii", blob, 0)
    if magic != b"WDBC":
        raise SystemExit("%s is not a DBC (magic %r) - a bad copy?" % (path, magic))
    body = 20
    return blob, rows, fields, rowsize, body, body + rows * rowsize


def _field(blob, body, rowsize, row, index):
    return struct.unpack_from("<i", blob, body + row * rowsize + index * 4)[0]


def _text(blob, strings, offset):
    if offset <= 0:
        return ""
    return blob[strings + offset:blob.index(b"\0", strings + offset)].decode(
        "utf-8", "replace")


def _row_for(rows, skill_id):
    """The ability row THIS FAMILY matches, or None. See the module docstring."""
    same_skill = [r for r in rows if r["skill"] == skill_id] or rows
    usable = [r for r in same_skill
              if r["cm"] == 0 or (r["cm"] & FAMILY_CLASSES)]
    return usable[0] if usable else None


def main(argv):
    where = pathlib.Path(argv[1] if len(argv) > 1 else ".")
    spell, rows, _f, rowsize, body, strings = _load(where / "Spell.dbc")
    index = {_field(spell, body, rowsize, r, F_ID): r for r in range(rows)}

    # THE ANCHORS, BEFORE ANY NEW FACT IS READ (infra#3689, infra#3748). The
    # same two every other reader of these files asserts, plus the one this
    # script needs and they do not: that the CREATE_ITEM lookup resolves a
    # known spell to a known item.
    anchor = index[2963]
    assert _field(spell, body, rowsize, anchor, F_REAGENT) == 2589
    assert _field(spell, body, rowsize, anchor, F_REAGENT_COUNT) == 2
    assert _text(spell, strings, _field(
        spell, body, rowsize, anchor, F_NAME)) == "Bolt of Linen Cloth"
    assert _field(spell, body, rowsize, index[2657], F_REQUIRES_SPELL_FOCUS) == 3
    assert _field(spell, body, rowsize, anchor, F_EFFECT) == CREATE_ITEM
    assert _field(spell, body, rowsize, anchor, F_EFFECT_ITEM_TYPE) == 2996

    focus, frows, _ff, frowsize, fbody, fstrings = _load(
        where / "SpellFocusObject.dbc")
    focus_names = {
        _field(focus, fbody, frowsize, r, 0): _text(
            focus, fstrings, _field(focus, fbody, frowsize, r, 1))
        for r in range(frows)
    }
    # The one focus the brief claimed the flasks need. Asserted rather than
    # looked up, so that this script fails loudly on a realm where the id moved
    # instead of quietly printing "the flasks need no focus" for a wrong reason.
    assert focus_names.get(663) == "Alchemy Lab", focus_names.get(663)

    abil, arows, _af, arowsize, abody, _as = _load(where / "SkillLineAbility.dbc")
    by_spell: dict = {}
    for r in range(arows):
        get = lambda i: _field(abil, abody, arowsize, r, i)  # noqa: E731
        by_spell.setdefault(get(A_SPELL), []).append(dict(
            skill=get(A_SKILL), cm=get(A_CLASSMASK), req=get(A_REQ),
            acquire=get(A_ACQUIRE), grey=get(A_GREY), yellow=get(A_YELLOW)))

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import goals       # noqa: E402
    import raidcraft   # noqa: E402

    print("MEASURED_CONSUMABLES = {")
    for c in raidcraft.CONSUMABLES:
        row = index.get(c.spell_id)
        if row is None:
            print("    # !! spell %d (%s) is not in Spell.dbc at all"
                  % (c.spell_id, c.name))
            continue
        get = lambda i: _field(spell, body, rowsize, row, i)  # noqa: E731
        made = [get(F_EFFECT_ITEM_TYPE + i) for i in range(3)
                if get(F_EFFECT + i) == CREATE_ITEM and get(F_EFFECT_ITEM_TYPE + i)]
        band = _row_for(by_spell.get(c.spell_id, []), goals.SKILL_IDS[c.skill])
        if band is None:
            print("    # !! spell %d has no ability row this family matches"
                  % c.spell_id)
            continue
        print("    %d: (%d, %d, %d, %d, %d),   # %s" % (
            c.spell_id, band["skill"], made[0] if made else 0,
            band["yellow"], band["grey"], get(F_REQUIRES_SPELL_FOCUS), c.name))
    print("}")

    # THE HALF THIS SCRIPT CANNOT PRINT, spelled as the queries that do, so the
    # next reader regenerates BOTH projections rather than the easy one.
    spells = ",".join(str(c.spell_id) for c in raidcraft.CONSUMABLES)
    print()
    print("# MEASURED_RANKS needs the live world database - run these:")
    print("#   SELECT SpellId, ReqSkillLine, ReqSkillRank, COUNT(*) FROM "
          "trainer_spell")
    print("#    WHERE SpellId IN (%s)" % spells)
    print("#    GROUP BY SpellId, ReqSkillLine, ReqSkillRank;")
    print("#   SELECT entry, name, RequiredSkill, RequiredSkillRank, spellid_2")
    print("#     FROM item_template WHERE spellid_2 IN (%s);" % spells)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
