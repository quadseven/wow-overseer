"""Generate the talent reference JSON from client data (one-time, committed).

`character_talent` stores one row per learned talent, and the only thing in
that row is the SPELL id of the rank the character currently holds. That is
enough for the server and useless to a reader: "Grug has spell 12308" is not
a build. Turning it back into "3/3 Puncture, Protection" needs the client's
own talent tables, and those are the one thing the server database does not
have - acore_world ships `talent_dbc` and `talenttab_dbc` as EMPTY tables,
because the core reads the real DBCs off disk instead.

So this reads them off disk, exactly as the worldserver does, and freezes
the answer into JSON beside zones.json and shapes.json. Same reasoning as
those two: 3.3.5a client data never changes, so the output is committed
rather than built per-run, and no runtime process needs a DBC mount.

Inputs (3.3.5a client data, as extracted into the worldserver's data/dbc):
  Talent.dbc      talent id -> tab, tier, column, and the spell id per rank
  TalentTab.dbc   tab id -> tree name, class mask, order within the class
  Spell.dbc       spell id -> name (the talent's name is its rank-1 spell's)

Output (into the service dir root - the image build's shared-dir copy takes
top-level files only, so this stays flat beside the code):
  talents.json    trees + talents, keyed so a rank spell id resolves to a
                  named talent, its tree, and how many points that rank is

Pet trees (Ferocity, Tenacity, Cunning) are deliberately left out: they have
no class mask, and pet talents are persisted in the pet's own tables, never
in `character_talent`. Including them would add a branch nothing can reach.

Usage: python3 gen_talents.py <dbc_dir> <out_dir>
"""
from __future__ import annotations

import json
import struct
import sys

# Spell.dbc (3.3.5a) is 234 fields wide; the enUS name is field 136. Verified
# against the file rather than counted off a struct definition - field 133 is
# a description and 153 the "Rank N" subtext, so an off-by-two here would
# silently produce plausible-looking nonsense instead of an error.
SPELL_NAME_FIELD = 136

# Talent.dbc: ID, TabID, TierID, ColumnIndex, SpellRank[9], then prereqs and
# flags this view has no use for.
TALENT_RANK_FIELDS = slice(4, 13)

# TalentTab.dbc: ID, Name_Lang[16] + mask, SpellIconID, RaceMask, ClassMask,
# PetTalentMask, OrderIndex, BackgroundFile.
TAB_NAME_FIELD = 1
TAB_CLASS_MASK_FIELD = 20
TAB_ORDER_FIELD = 22


def read_dbc(path: str) -> tuple[list[tuple], bytes]:
    with open(path, "rb") as f:
        magic, records, fields, recsize, strsize = struct.unpack("<4s4I", f.read(20))
        assert magic == b"WDBC", path
        assert recsize == fields * 4, (path, recsize, fields)
        rows = [struct.unpack(f"<{fields}I", f.read(recsize)) for _ in range(records)]
        strings = f.read(strsize)
    return rows, strings


def cstr(strings: bytes, offset: int) -> str:
    end = strings.index(b"\x00", offset)
    return strings[offset:end].decode("utf-8", "replace")


def class_from_mask(mask: int) -> int:
    """ClassMask bit -> class id, or 0 when it is not a single player class.

    Every player tree belongs to exactly one class (mask 1 << (class - 1)).
    A mask with any other shape is a pet tree or something the client added,
    and gets 0 so the caller can drop it rather than guess.
    """
    if mask <= 0 or mask & (mask - 1):
        return 0
    return mask.bit_length()


def main(dbc_dir: str, out_dir: str) -> None:
    tab_rows, tab_strings = read_dbc(f"{dbc_dir}/TalentTab.dbc")
    trees: dict[str, dict] = {}
    for r in tab_rows:
        class_id = class_from_mask(r[TAB_CLASS_MASK_FIELD])
        if not class_id:
            continue  # pet tree: never referenced by character_talent
        trees[str(r[0])] = {
            "name": cstr(tab_strings, r[TAB_NAME_FIELD]),
            "class": class_id,
            "order": r[TAB_ORDER_FIELD],
        }

    # Spell names, but only for the rank spells a talent actually names. The
    # full table is 49k spells and 48MB of DBC; the ~2k that talents point at
    # are the entire reason this file exists.
    talent_rows, _ = read_dbc(f"{dbc_dir}/Talent.dbc")
    wanted: set[int] = set()
    for r in talent_rows:
        wanted.update(s for s in r[TALENT_RANK_FIELDS] if s)

    spell_rows, spell_strings = read_dbc(f"{dbc_dir}/Spell.dbc")
    names = {
        r[0]: cstr(spell_strings, r[SPELL_NAME_FIELD])
        for r in spell_rows
        if r[0] in wanted and r[SPELL_NAME_FIELD]
    }

    talents = []
    for r in talent_rows:
        tab = str(r[1])
        if tab not in trees:
            continue
        ranks = [s for s in r[TALENT_RANK_FIELDS] if s]
        if not ranks:
            continue
        # A talent is named after its first rank; every later rank is the
        # same name with a different "Rank N" subtext, so rank 1 is the only
        # one worth carrying.
        name = names.get(ranks[0])
        if not name:
            # A talent whose rank-1 spell has no name would render as a blank
            # cell. Say which spell instead, so the gap is diagnosable.
            name = f"Spell #{ranks[0]}"
        talents.append({
            "name": name,
            "tree": r[1],
            "row": r[2],
            "col": r[3],
            "ranks": ranks,
        })

    talents.sort(key=lambda t: (t["tree"], t["row"], t["col"]))
    with open(f"{out_dir}/talents.json", "w") as f:
        # Minified, the same posture shapes.json takes and for the same
        # reason: this is machine-written and machine-read, nobody hand-edits
        # it, and pretty-printing costs 40KB of indentation no one reads. It
        # also keeps the file inside a reviewer's single-look window - the
        # first cut shipped at 108KB and the PR review bot could not hold it
        # in one pass, which made the one file nobody can eyeball also the
        # one file nothing had checked.
        json.dump({"trees": trees, "talents": talents}, f,
                  separators=(",", ":"), sort_keys=True)
    print(f"trees: {len(trees)}  talents: {len(talents)}  rank spells: {len(wanted)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
