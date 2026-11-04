"""Class trainer rows a member can never be taught again (#792).

Three cases kept walking members to a trainer that refused them:

- A few trainer rows are a learn spell, not the spell itself. Summon Felsteed
  (1710) teaches Felsteed (5784) and Apprentice Riding through
  SPELL_EFFECT_LEARN_SPELL; only the taught spells reach character_spell, so
  the row read as owed forever. TAUGHT maps each such row to what it teaches,
  the row's own spell first. A member holding that first spell has the row,
  and the race check runs on every taught spell too (34768 teaches the blood
  elf warhorse, 34769, which only a blood elf can learn).
- Druid spells usable only in Bear Form or Dire Bear Form (BEAR_FORM_ONLY):
  a druid without Bear Form (a quest, never a trainer row) is refused them.
- Dual Wield (674) is on the rogue trainer list, but a rogue already has it
  and the trainer never teaches it.

Frozen from Spell.dbc (md5 543b9fe61355b6a77a01714d52fea2e5) and the realm's
class trainer list by tools/taught_spells_from_dbc.py, because the `*_dbc`
tables on the realm are empty. Only rows whose taught spell differs are kept.

PURE MODULE: tables and questions. No MySQL, no clock.
"""

from __future__ import annotations

DRUID, ROGUE = 11, 4
BEAR_FORM, DIRE_BEAR_FORM = 5487, 9634
DUAL_WIELD = 674

# trainer spell -> the spells its learn effects teach, the row's own first.
TAUGHT = {
    1710: (5784, 33388),
    10321: (20271, 21084),
    13820: (13819, 33388),
    33950: (33943, 34090),
    34768: (34769, 33388),
}

# Druid trainer spells whose Stances mask names only Bear Form and Dire Bear
# Form.
BEAR_FORM_ONLY = frozenset(
    {
        99,
        769,
        779,
        780,
        1735,
        5209,
        5211,
        5229,
        6798,
        6808,
        6809,
        8972,
        8983,
        9490,
        9745,
        9747,
        9754,
        9880,
        9881,
        9898,
        9908,
        22842,
        26996,
        26997,
        26998,
        33745,
        33986,
        33987,
        48479,
        48480,
        48559,
        48560,
        48561,
        48562,
        48563,
        48564,
        48567,
        48568,
        62600,
    }
)

# Spells outside the trainer list the bridge must read from character_spell
# to answer these questions.
READ_SPELLS = tuple(
    sorted({learns[0] for learns in TAUGHT.values()} | {BEAR_FORM, DIRE_BEAR_FORM})
)


def taught(spell) -> tuple:
    """What a trainer row teaches: its learn effects, else the spell itself."""
    spell = _int(spell)
    return TAUGHT.get(spell, (spell,))


def held(spell, known) -> bool:
    """Whether a member holding `known` has trainer row `spell` already."""
    return taught(spell)[0] in known


def with_held_rows(known, class_id=None) -> set:
    """`known` plus every trainer row the member has through what it holds:
    a learn row whose taught spell it holds, and Dual Wield for a rogue."""
    out = {_int(k) for k in known or ()}
    out.update(row for row, learns in TAUGHT.items() if learns[0] in out)
    if _int(class_id) == ROGUE:
        out.add(DUAL_WIELD)
    return out


def refused(spell, known, class_id) -> bool:
    """A druid without Bear Form is refused the bear-only spells."""
    return (
        _int(class_id) == DRUID
        and _int(spell) in BEAR_FORM_ONLY
        and not {BEAR_FORM, DIRE_BEAR_FORM} & set(known)
    )


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
