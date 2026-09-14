"""Regenerate craftbook.json - every craft in the game, per profession.

infra#3507 (the Trades view) closes with a paragraph admitting the one thing
that page could not do, and guildcraft.py's own `_trainer_line` repeats it:

    A craft a TRAINER teaches is counted and never named.
    skilllineability_dbc is empty on this realm and spell_dbc holds custom rows
    only, because that data ships inside the client files the worldserver reads
    and this service never sees them.

Both halves of that are true and neither is a reason to stop. This service
never sees the client files AT RUNTIME; a tool run by hand against the DBCs
sitting in the running worldserver's own image sees them fine, which is exactly
the precedent `spell_focus_from_dbc.py` set for `RequiresSpellFocus`. So the
map from a craft spell to its NAME, its skill line and the rank it opens at is
committed here as a projection, and the page that could only count can now
name.

WHAT IT IS FOR, WHICH IS MORE THAN NAMES. The operator asked for "all recipes
trying to go for 100% completion", and a percentage is a fraction: the
numerator was always readable (`character_spell` against a craft spell) and the
DENOMINATOR was not. `item_template` class 9 carries only the recipes that
exist as an ITEM - a pattern off a vendor, a plan off a corpse - which is a
minority of any profession. Blacksmithing has 525 abilities on its skill line
and 118 recipe items; a completion figure built on the item table alone would
have read 100% while four hundred crafts were still unlearned. This file is the
denominator.

WHY THE PROJECTION IS COMMITTED RATHER THAN READ AT RUNTIME. The same reason
`tests/test_craft.py` carries MEASURED_FOCUS: CI runs stdlib-only with no
cluster access, the DBCs are 48 MB of client data that does not belong in a
repository, and a checked-in projection is the only form of the server's answer
that a pull request can be gated on.

USAGE

    POD=$(kubectl -n wow-dev get pods -l app=worldserver -o name | head -1)
    for f in Spell.dbc SkillLineAbility.dbc; do
      kubectl -n wow-dev exec "${POD#pod/}" -c worldserver -- \\
        sh -c "cat /azerothcore/env/dist/data/dbc/$f" > "$f"
    done
    python3 tools/craftbook_from_dbc.py <dir holding the two .dbc files>

VERIFY THE COPY BEFORE TRUSTING IT, exactly as spell_focus_from_dbc.py says:
`md5sum` the local files against the pod's own `md5sum` of the same paths, and
note that a `kubectl exec ... -- sh -c "cat ..."` is used above rather than a
bare argument because Git Bash rewrites a leading-slash argument into a Windows
path and the exec then looks for C:/Program Files/Git/azerothcore. As of
2026-09-14, on the worldserver running mod-playerbots/azerothcore-wotlk
47960183bb03b83e8943eb2f0f39c16df9710c9d:

    Spell.dbc              543b9fe61355b6a77a01714d52fea2e5
    SkillLineAbility.dbc   d8c11abfcfe70596cb9068c0e97a1d9a

The Spell.dbc hash is the same one spell_focus_from_dbc.py recorded on
2026-09-13, which is a second reason to trust this pull: two tools written a
day apart read the identical bytes.

THE FIELD INDICES ARE THE TRAP, and this file inherits the one
spell_focus_from_dbc.py already documents plus one of its own. Spell.dbc is 234
fields of 3.3.5a layout and `Effect[3]` begins at 71 while `EffectItemType[3]`
begins at 107; a first pass that walked the effect block from 73 produced a
plausible-looking file in which every smelt created nothing. So this tool
asserts FOUR anchors against known-good values before it reads a single new
fact, and refuses to write anything if one of them moves - a parse that cannot
find a value it already knows is not a parse to read new facts off.
"""
from __future__ import annotations

import json
import pathlib
import struct
import sys

# 3.3.5a Spell.dbc field offsets. `spell_focus_from_dbc.py` documents F_NAME,
# F_REAGENT and F_REQUIRES_SPELL_FOCUS and this file re-derives nothing: the
# same three numbers appear here so the two tools' anchors can be compared.
F_ID = 0
F_REQUIRES_SPELL_FOCUS = 18
F_REAGENT = 52
F_REAGENT_COUNT = 60
F_EFFECT = 71
F_EFFECT_ITEM_TYPE = 107
F_NAME = 136

# 3.3.5a SkillLineAbility.dbc, 14 fields. AcquireMethod is the field
# professions.py's infra#3614 note turns on: 0 is an explicit grant (a trainer
# purchase, a quest, a recipe item) and PERSISTS to `character_spell`, while 1
# is auto-learned on a rank-up and is NEVER written back, so its absence from
# that table proves nothing. A projection that dropped it would leave every
# consumer re-deriving that rule or, worse, not knowing it exists.
#
# A_MIN_RANK IS NOT THE LEARN GATE AND THE PROJECTION SAYS SO BY CARRYING BOTH.
# Measured over this file's own output: `ReqSkillValue` is 1 for 439 of 439
# tailoring abilities, 508 of 525 blacksmithing and 258 of 264 alchemy, so a
# consumer treating it as "the skill you need" concludes that a tailor at 50
# can learn every recipe in the game. The real gate lives in the world
# database - `trainer_spell.ReqSkillRank` for a trainer craft and
# `item_template.RequiredSkillRank` for one that exists as a recipe item - and
# the two together cover almost every craft. `TrivialSkillLineRankLow` (the
# YELLOW value, the skill at which a craft stops granting a guaranteed point)
# is carried as the LAST RESORT for the handful the world database places
# nowhere. It is always at or above the true learn rank, so falling back to it
# can only UNDER-report what is learnable, never over-report it, which is the
# safe direction for a figure whose whole job is to reach 100% honestly.
A_SKILL_LINE = 1
A_SPELL = 2
A_MIN_RANK = 7
A_ACQUIRE = 9
A_TRIVIAL_HIGH = 10
A_TRIVIAL_LOW = 11

# SpellEffect names, for the two this tool cares about.
SPELL_EFFECT_CREATE_ITEM = 24
SPELL_EFFECT_TRADE_SKILL = 47

# The professions this projects. Deliberately NOT read from goals.SKILL_IDS at
# generation time even though the two agree today: this file is the input to a
# test, and a generator that silently re-scoped itself when an unrelated table
# was edited would move the denominator of every completion figure on the site
# with nothing failing. `tests/test_tradespec.py` asserts the two agree, which
# is the check being made explicit rather than assumed.
SKILL_LINES = {
    129: "first aid",
    164: "blacksmithing",
    165: "leatherworking",
    171: "alchemy",
    182: "herbalism",
    185: "cooking",
    186: "mining",
    197: "tailoring",
    202: "engineering",
    333: "enchanting",
    356: "fishing",
    393: "skinning",
    755: "jewelcrafting",
    773: "inscription",
}


def _load(path: pathlib.Path):
    """One DBC, or a sentence saying which file could not be read and why.

    THE THREE WAYS THIS FILE ARRIVES BROKEN, and they must not all look like a
    traceback. The usage above tells a person to `kubectl exec ... cat` two 48
    MB files out of a running pod, so: the copy may never have been made (a
    typo'd pod name, an expired context), it may be EMPTY because the exec
    failed and the redirect still created the file, or it may be TRUNCATED
    because the stream was cut. A raw OSError names the first only as a stack,
    and a truncated read reaches `unpack_from` and raises `struct.error`, which
    says nothing about which of the two files it was. Each one is answered here
    with the path and what was wrong with it, so the person re-running the
    kubectl line knows which line to re-run.
    """
    try:
        blob = path.read_bytes()
    except OSError as problem:
        # `from None` and not `from problem` (ruff B904 wants one of the two).
        # The OSError's own message is interpolated below, so chaining would
        # add nothing but a "During handling of the above exception" block and
        # a traceback - which is exactly the noise this guard exists to remove.
        # The other two SystemExits here print one readable line; this one
        # should not be the exception that prints twenty.
        raise SystemExit(
            "could not read %s: %s. The usage in this file's docstring says "
            "how to copy it out of the running worldserver, and warns to "
            "md5sum the result against the pod's own before trusting it."
            % (path, problem)) from None
    if len(blob) < 20:
        raise SystemExit(
            "%s is %d bytes, which is shorter than a DBC header. That is what "
            "a failed `kubectl exec` looks like: the redirect still creates "
            "the file." % (path, len(blob)))
    magic, rows, fields, rowsize, _strings = struct.unpack_from("<4siiii", blob, 0)
    if magic != b"WDBC":
        raise SystemExit("%s is not a DBC (magic %r) - a bad copy?" % (path, magic))
    body = 20
    end = body + rows * rowsize
    if len(blob) < end:
        raise SystemExit(
            "%s claims %d rows of %d bytes (%d bytes of body) and holds only "
            "%d bytes: the copy is TRUNCATED. md5sum it against the pod."
            % (path, rows, rowsize, end, len(blob)))
    return blob, rows, fields, rowsize, body, end


def _field(blob, body, rowsize, row, index):
    return struct.unpack_from("<i", blob, body + row * rowsize + index * 4)[0]


def _text(blob, strings, offset):
    return blob[strings + offset:blob.index(b"\0", strings + offset)].decode(
        "utf-8", "replace")


def _anchor(spell, body, rowsize, strings, index, ability):
    """Four known-good values, checked before any new fact is read.

    THE FIRST THREE ARE spell_focus_from_dbc.py's OWN ANCHORS, restated rather
    than referenced so that this tool fails on its own terms if the layout
    moves. 2963 is Bolt of Linen Cloth, it takes two of item 2589, and Smelt
    Copper is Forge-gated - between them they pin the name, reagent and focus
    fields.

    THE FOURTH IS THIS TOOL'S, and it is the one the other tool does not need:
    the EFFECT block. Bolt of Linen Cloth must CREATE item 2996 through
    SPELL_EFFECT_CREATE_ITEM, which pins F_EFFECT and F_EFFECT_ITEM_TYPE
    together. Reading 2997 here - the very next item, Bolt of Woolen Cloth -
    would be a layout off by one row rather than by one field, so the assertion
    names the value it got.

    THE FIFTH PINS THE OTHER FILE. SkillLineAbility's row for 2963 must sit on
    skill line 197 at rank 1 with AcquireMethod 1, which is the fact
    professions.py records with its own measurement. A Spell.dbc that parses
    and a SkillLineAbility.dbc that does not would otherwise produce a
    perfectly-named projection with every rank wrong.
    """
    row = index[2963]
    got = _field(spell, body, rowsize, row, F_REAGENT)
    if got != 2589:
        raise SystemExit("Spell.dbc anchor: reagent of 2963 read %d, not 2589" % got)
    got = _field(spell, body, rowsize, row, F_REAGENT_COUNT)
    if got != 2:
        raise SystemExit("Spell.dbc anchor: reagent count read %d, not 2" % got)
    got = _text(spell, strings, _field(spell, body, rowsize, row, F_NAME))
    if got != "Bolt of Linen Cloth":
        raise SystemExit("Spell.dbc anchor: name of 2963 read %r" % got)
    got = _field(spell, body, rowsize, index[2657], F_REQUIRES_SPELL_FOCUS)
    if got != 3:
        raise SystemExit("Spell.dbc anchor: focus of Smelt Copper read %d, not 3" % got)
    got = _field(spell, body, rowsize, row, F_EFFECT)
    if got != SPELL_EFFECT_CREATE_ITEM:
        raise SystemExit("Spell.dbc anchor: effect of 2963 read %d, not 24" % got)
    got = _field(spell, body, rowsize, row, F_EFFECT_ITEM_TYPE)
    if got != 2996:
        raise SystemExit(
            "Spell.dbc anchor: 2963 creates item %d, not 2996 (2997 here would "
            "mean the row index is off by one, not the field index)" % got)
    if ability != (197, 1, 1):
        raise SystemExit(
            "SkillLineAbility.dbc anchor: 2963 read as skill %d rank %d "
            "acquire %d, not (197, 1, 1)" % ability)


def main(argv):
    where = pathlib.Path(argv[1] if len(argv) > 1 else ".")
    spell, rows, _fields, rowsize, body, strings = _load(where / "Spell.dbc")
    index = {_field(spell, body, rowsize, r, F_ID): r for r in range(rows)}

    sla, arows, _af, arowsize, abody, _astr = _load(where / "SkillLineAbility.dbc")

    def ability(row):
        return (_field(sla, abody, arowsize, row, A_SKILL_LINE),
                _field(sla, abody, arowsize, row, A_MIN_RANK),
                _field(sla, abody, arowsize, row, A_ACQUIRE))

    anchor_row = next(r for r in range(arows)
                      if _field(sla, abody, arowsize, r, A_SPELL) == 2963)
    _anchor(spell, body, rowsize, strings, index, ability(anchor_row))

    book: dict = {}
    absent = 0
    for r in range(arows):
        skill = _field(sla, abody, arowsize, r, A_SKILL_LINE)
        if skill not in SKILL_LINES:
            continue
        sid = _field(sla, abody, arowsize, r, A_SPELL)
        row = index.get(sid)
        if row is None:
            # A skill line row naming a spell the client does not carry. Counted
            # and dropped rather than written as a craft with no name: a null
            # name in the denominator is a recipe nobody can ever learn, which
            # would make 100% unreachable by construction.
            absent += 1
            continue
        effects = [_field(spell, body, rowsize, row, F_EFFECT + i)
                   for i in range(3)]
        created = _field(spell, body, rowsize, row, F_EFFECT_ITEM_TYPE)
        # EVERY ability on the line is kept, not only the ones that create an
        # item. Enchanting creates almost nothing (32 of its 306 abilities
        # make an item; the rest apply an enchant to somebody else's gear) and
        # a filter on CREATE_ITEM would have reported it as a 32-recipe
        # profession, which is the shape of mistake this whole file exists to
        # stop. `creates` is recorded so a consumer can still tell them apart.
        book.setdefault(str(skill), {})[str(sid)] = [
            _text(spell, strings, _field(spell, body, rowsize, row, F_NAME)),
            _field(sla, abody, arowsize, r, A_MIN_RANK),
            _field(sla, abody, arowsize, r, A_TRIVIAL_LOW),
            _field(sla, abody, arowsize, r, A_ACQUIRE),
            created if effects[0] == SPELL_EFFECT_CREATE_ITEM else 0,
        ]

    out = where.parent / "craftbook.json" if len(argv) > 2 else pathlib.Path(
        __file__).resolve().parents[1] / "craftbook.json"
    out.write_text(json.dumps(book, sort_keys=True, separators=(",", ":")),
                   encoding="utf-8")
    total = sum(len(v) for v in book.values())
    print("wrote %s: %d professions, %d crafts (%d skill-line rows named a "
          "spell absent from Spell.dbc and were dropped)"
          % (out, len(book), total, absent))
    for skill, word in sorted(SKILL_LINES.items(), key=lambda kv: kv[1]):
        print("  %-16s %d" % (word, len(book.get(str(skill), {}))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
