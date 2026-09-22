"""Regenerate tests/test_craft.py's MEASURED_BANDS from the server's own DBCs.

THE SIBLING OF `spell_focus_from_dbc.py`, AND FOR THE SAME REASON ONE TURN ON.
That script exists because `craft.Recipe.focus` is a claim about the worldserver
that only the worldserver can settle, and the test which was meant to check it
compared the declared field against its own default. `Recipe.min_skill` and
`Recipe.max_skill` are claims of exactly the same kind, and until this script
NOTHING checked them at all - they came from a leveling guide's stated ranges,
which is the right source for the ROUTE and the wrong one for the EDGES.

TEN OF SIXTY-ONE ENTRIES WERE WRONG when this was first run, and the three that
mattered were the three live characters who had stopped moving. See craft.py's
COLOUR BANDS block for the whole list; the shape of the fault is what matters
here. A wrong edge is INVISIBLE from outside: `recipe_for` answers, the errand
is written, the cast goes off and the item lands in the bag. Only the skill
never moves, and nothing anywhere logs a word about it. That is why this has to
be a checked-in projection gated on every pull request rather than a thing
somebody re-derives when a character looks stuck.

WHAT THE TWO NUMBERS MEAN, because they gate different failures:

  MinSkillLineRank         the learn floor. Below it the character cannot hold
                           the spell, so `min_skill` below it buys a
                           `craft_spell` that DriveCraft drops with a WARN
                           calling it a planner bug - loud, but only in a log
                           nobody reads on a twenty-second loop.
  TrivialSkillLineRankHigh the grey value. At or above it the core rolls no
                           skill-up, so `max_skill` at or past it buys casts
                           that consume reagents and grant nothing - silent.

`TrivialSkillLineRankLow` (yellow) is carried too, because it is what decides
which of two legal recipes is the BETTER cast at a given value, and that
judgement is currently made by hand in craft.py's comments.

USAGE - identical to its sibling, and the same warning applies

    kubectl -n wow-dev exec <worldserver-pod> -c worldserver -- \\
      cat /azerothcore/env/dist/data/dbc/Spell.dbc > Spell.dbc
    kubectl -n wow-dev exec <worldserver-pod> -c worldserver -- \\
      cat /azerothcore/env/dist/data/dbc/SkillLineAbility.dbc > SkillLineAbility.dbc
    python3 tools/spell_bands_from_dbc.py <dir holding the two .dbc files>

`kubectl cp` is NOT used above on purpose: it refuses a Windows destination
path (the drive-letter colon reads as a pod separator) and a partial copy is a
truncated file that parses far enough to produce plausible nonsense. Stream it
and md5 it. As of 2026-09-13:

    Spell.dbc             543b9fe61355b6a77a01714d52fea2e5
    SkillLineAbility.dbc  d8c11abfcfe70596cb9068c0e97a1d9a

A SPELL CAN CARRY MORE THAN ONE ABILITY ROW, and picking the wrong one is this
file's version of the field-offset trap. Heavy Linen Bandage has two: an
AcquireMethod 0 row for ClassMask 0x5DF (every ordinary class) and an
AcquireMethod 1 row for ClassMask 0x20, which is Death Knight and nothing else.
The family is a Warrior, Paladin, Rogue, Mage and Priest, so the row that
applies to them is the FIRST, and a reader that took the auto-learn row would
conclude they get it free at 40. `_row_for` below keeps only rows this family
can actually match, and a spell whose only rows are Death-Knight-shaped is
reported rather than quietly given somebody else's numbers.
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
F_NAME = 136

# 3.3.5a SkillLineAbility.dbc: 14 fields.
A_SKILL, A_SPELL, A_CLASSMASK = 1, 2, 4
A_REQ, A_ACQUIRE, A_GREY, A_YELLOW = 7, 9, 10, 11

# Every class the family actually plays, as a ClassMask. 0x20 is Death Knight.
FAMILY_CLASSES = 0x5DF


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
    return blob[strings + offset : blob.index(b"\0", strings + offset)].decode(
        "utf-8", "replace"
    )


def _row_for(rows, skill_id):
    """The ability row THIS FAMILY matches, or None. See the module docstring."""
    same_skill = [r for r in rows if r["skill"] == skill_id] or rows
    usable = [r for r in same_skill if r["cm"] == 0 or (r["cm"] & FAMILY_CLASSES)]
    return usable[0] if usable else None


def main(argv):
    where = pathlib.Path(argv[1] if len(argv) > 1 else ".")
    spell, rows, _f, rowsize, body, strings = _load(where / "Spell.dbc")
    index = {_field(spell, body, rowsize, r, F_ID): r for r in range(rows)}

    # THE ANCHORS, BEFORE ANY NEW FACT IS READ (infra#3689, infra#3748).
    anchor = index[2963]
    assert _field(spell, body, rowsize, anchor, F_REAGENT) == 2589
    assert _field(spell, body, rowsize, anchor, F_REAGENT_COUNT) == 2
    assert (
        _text(spell, strings, _field(spell, body, rowsize, anchor, F_NAME))
        == "Bolt of Linen Cloth"
    )
    assert _field(spell, body, rowsize, index[2657], F_REQUIRES_SPELL_FOCUS) == 3

    abil, arows, _af, arowsize, abody, _as = _load(where / "SkillLineAbility.dbc")
    by_spell: dict = {}
    for r in range(arows):
        get = lambda i: _field(abil, abody, arowsize, r, i)  # noqa: E731
        by_spell.setdefault(get(A_SPELL), []).append(
            dict(
                skill=get(A_SKILL),
                cm=get(A_CLASSMASK),
                req=get(A_REQ),
                acquire=get(A_ACQUIRE),
                grey=get(A_GREY),
                yellow=get(A_YELLOW),
            )
        )

    # A THIRD ANCHOR, for the ability layout specifically - the Spell.dbc ones
    # above prove nothing about this file. Linen Bandage is req 1 / yellow 30 /
    # grey 60 and Heavy Linen Bandage carries the two-row Death Knight split.
    linen = _row_for(by_spell[3275], 129)
    assert (linen["req"], linen["yellow"], linen["grey"]) == (1, 30, 60), linen
    assert len(by_spell[3276]) == 2, by_spell[3276]

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import craft  # noqa: E402
    import goals  # noqa: E402

    by_id = {v: k for k, v in goals.SKILL_IDS.items()}
    print("MEASURED_BANDS = {")
    for skill_id, recipes in craft.RECIPES.items():
        if not recipes:
            continue
        print("    # %s" % by_id.get(skill_id, skill_id).upper())
        for recipe in recipes:
            row = _row_for(by_spell.get(recipe.spell_id, []), skill_id)
            if row is None:
                print(
                    "    # !! spell %d has no ability row this family matches"
                    % recipe.spell_id
                )
                continue
            print(
                "    %d: (%d, %d, %d),   # %s"
                % (recipe.spell_id, row["req"], row["yellow"], row["grey"], recipe.name)
            )
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
