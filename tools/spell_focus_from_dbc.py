"""Regenerate tests/test_craft.py's MEASURED_FOCUS from the server's own DBCs.

infra#3760, built as part of infra#3748. `craft.Recipe.focus` is a claim about
the worldserver, and the test that was supposed to check it compared the
declared field against its own default - so eleven Engineering entries declared
"no focus needed" while the server required an Anvil, and every one of them was
refused on every twenty-second poll for its whole life.

`tests/test_craft.py` now holds a projection of `Spell.dbc`'s own
`RequiresSpellFocus` for every spell `craft.RECIPES` names, and asserts the
declarations against it. This script is what makes that projection reproducible
in one command instead of by hand, so the next person adding a recipe states a
MEASUREMENT rather than a hope.

WHY THE PROJECTION IS CHECKED IN AT ALL, RATHER THAN READ AT TEST TIME. CI runs
this suite with `install-cmd: "true"` - stdlib only, no cluster access - and
`Spell.dbc` is 48 MB of client data that does not belong in the repository. A
checked-in projection is the only form of the server's answer a pull request can
be gated on. It is a second, independent copy on purpose: craft.py's author has
to make two places agree, and only one of them can be typed from memory.

USAGE

    kubectl -n wow-dev cp \\
      worldserver-<pod>:/azerothcore/env/dist/data/dbc/Spell.dbc ./Spell.dbc
    kubectl -n wow-dev cp \\
      worldserver-<pod>:/azerothcore/env/dist/data/dbc/SpellFocusObject.dbc .
    python3 tools/spell_focus_from_dbc.py <dir holding the two .dbc files>

VERIFY THE COPY BEFORE TRUSTING IT. `md5sum` the local files against the pod's
own `md5sum` of the same paths; a partial `kubectl cp` is a truncated file that
parses far enough to produce plausible nonsense. As of 2026-09-13:

    Spell.dbc             543b9fe61355b6a77a01714d52fea2e5
    SpellFocusObject.dbc  797c65a49ae1e6336c9d851eb18011e0

THE FIELD INDEX IS THE TRAP. `RequiresSpellFocus` is field 18 of the 234-field
3.3.5a layout and `EquippedItemClass` is field 68 - NOT 23 and 69, which a first
pass at this used and which produce `focus = 0` for every smelt in the game.
infra#3689's anchor (spell 2963 -> Reagent[0]=2589, ReagentCount[0]=2) proves
the reagent and name fields and does NOT touch focus, so it passes either way.
This script asserts the anchor anyway - a parse that cannot find a known-good
value is not one to read new facts off - and then sanity-checks the focus field
against a second known value: spell 2657 (Smelt Copper) must read 3, Forge.
"""

from __future__ import annotations

import pathlib
import struct
import sys

# 3.3.5a Spell.dbc field offsets. See the module docstring on why 18 and not 23.
F_ID = 0
F_REQUIRES_SPELL_FOCUS = 18
F_REAGENT = 52
F_REAGENT_COUNT = 60
F_NAME = 136


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


def main(argv):
    where = pathlib.Path(argv[1] if len(argv) > 1 else ".")
    spell, rows, fields, rowsize, body, strings = _load(where / "Spell.dbc")
    index = {_field(spell, body, rowsize, r, F_ID): r for r in range(rows)}

    # THE ANCHOR, BEFORE ANY NEW FACT IS READ OFF THIS FILE (infra#3689).
    anchor = index[2963]
    assert _field(spell, body, rowsize, anchor, F_REAGENT) == 2589
    assert _field(spell, body, rowsize, anchor, F_REAGENT_COUNT) == 2
    assert (
        _text(spell, strings, _field(spell, body, rowsize, anchor, F_NAME))
        == "Bolt of Linen Cloth"
    )
    # AND A SECOND ONE FOR THE FIELD THE ANCHOR DOES NOT COVER. Smelt Copper is
    # Forge-gated; a layout that answers anything else here is the wrong layout.
    assert _field(spell, body, rowsize, index[2657], F_REQUIRES_SPELL_FOCUS) == 3

    names = {}
    focus_file = where / "SpellFocusObject.dbc"
    if focus_file.exists():
        foc, frows, _ff, frowsize, fbody, fstrings = _load(focus_file)
        names = {
            _field(foc, fbody, frowsize, r, 0): _text(
                foc, fstrings, _field(foc, fbody, frowsize, r, 1)
            )
            for r in range(frows)
        }

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import craft  # noqa: E402
    import goals  # noqa: E402

    by_id = {v: k for k, v in goals.SKILL_IDS.items()}
    print("MEASURED_FOCUS = {")
    for skill_id, recipes in craft.RECIPES.items():
        if not recipes:
            continue
        print("    # %s" % by_id.get(skill_id, skill_id).upper())
        for recipe in recipes:
            row = index.get(recipe.spell_id)
            if row is None:
                print("    # !! spell %d is not in Spell.dbc at all" % recipe.spell_id)
                continue
            focus = _field(spell, body, rowsize, row, F_REQUIRES_SPELL_FOCUS)
            print(
                "    %d: %d,   # %s%s"
                % (
                    recipe.spell_id,
                    focus,
                    _text(spell, strings, _field(spell, body, rowsize, row, F_NAME)),
                    " (%s)" % names[focus] if focus and focus in names else "",
                )
            )
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
