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
  Talent.dbc      talent id -> tab, tier, column, the spell id per rank, and
                  the talent (and rank of it) this one requires
  TalentTab.dbc   tab id -> tree name, class mask, order within the class,
                  and the tree's icon
  Spell.dbc       spell id -> name and icon (both are the rank-1 spell's)
  SpellIcon.dbc   icon id -> icon file, whose bare name is what the page
                  asks the icon host for

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

# Spell.dbc (3.3.5a) is 234 fields wide; the enUS name is field 136 and the
# icon id field 133. Verified against the file rather than counted off a
# struct definition - field 153 is the "Rank N" subtext and 170 the
# description, so an off-by-two here would silently produce plausible-looking
# nonsense instead of an error.
SPELL_NAME_FIELD = 136
SPELL_ICON_FIELD = 133

# Talent.dbc: ID, TabID, TierID, ColumnIndex, SpellRank[9], PrereqTalent[3],
# PrereqRank[3], then flags this view has no use for. Only the first
# prerequisite slot is ever used in 3.3.5a, but all three are read so a
# talent with two arrows would draw two rather than silently one.
TALENT_RANK_FIELDS = slice(4, 13)
TALENT_PREREQ_FIELDS = slice(13, 16)
TALENT_PREREQ_RANK_FIELDS = slice(16, 19)

# TalentTab.dbc: ID, Name_Lang[16] + mask, SpellIconID, RaceMask, ClassMask,
# PetTalentMask, OrderIndex, BackgroundFile.
TAB_NAME_FIELD = 1
TAB_ICON_FIELD = 18
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


def icon_name(path: str) -> str:
    r"""'Interface\Icons\Spell_Nature_Lightning' -> 'spell_nature_lightning'."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def class_from_mask(mask: int) -> int:
    """ClassMask bit -> class id, or 0 when it is not a single player class.

    Every player tree belongs to exactly one class (mask 1 << (class - 1)).
    A mask with any other shape is a pet tree or something the client added,
    and gets 0 so the caller can drop it rather than guess.
    """
    if mask <= 0 or mask & (mask - 1):
        return 0
    return mask.bit_length()


def load_trees(dbc_dir: str, icons: dict[int, str]) -> dict[str, dict]:
    """TalentTab.dbc -> the player trees, keyed by tab id."""
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
            "icon": icons.get(r[TAB_ICON_FIELD], ""),
        }
    return trees


def load_spells(dbc_dir: str, wanted: set[int], icons: dict[int, str]
                ) -> tuple[dict[int, str], dict[int, str]]:
    """Spell.dbc -> (name, icon) per wanted spell.

    Only for the rank spells a talent actually names. The full table is 49k
    spells and 48MB of DBC; the ~2k that talents point at are the entire
    reason this file exists.
    """
    spell_rows, spell_strings = read_dbc(f"{dbc_dir}/Spell.dbc")
    names = {
        r[0]: cstr(spell_strings, r[SPELL_NAME_FIELD])
        for r in spell_rows
        if r[0] in wanted and r[SPELL_NAME_FIELD]
    }
    spell_icons = {
        r[0]: icons.get(r[SPELL_ICON_FIELD], "")
        for r in spell_rows
        if r[0] in wanted
    }
    return names, spell_icons


def talent_entry(r: tuple, ranks: list[int], names: dict[int, str],
                 spell_icons: dict[int, str]) -> dict:
    """One Talent.dbc row -> the talent as the page reads it."""
    # A talent is named after its first rank; every later rank is the same
    # name with a different "Rank N" subtext, so rank 1 is the only one
    # worth carrying. A talent whose rank-1 spell has no name would render
    # as a blank cell: say which spell instead, so the gap is diagnosable.
    name = names.get(ranks[0]) or f"Spell #{ranks[0]}"
    # PrereqRank is stored ZERO-based (Combustion needs 3/3 Critical Mass
    # and the file says 2). Carried as the rank a person would say, so the
    # page never has to know the file's counting.
    requires = [
        [talent, rank + 1]
        for talent, rank in zip(r[TALENT_PREREQ_FIELDS], r[TALENT_PREREQ_RANK_FIELDS],
                                strict=True)
        if talent
    ]
    return {
        "id": r[0],
        "name": name,
        "tree": r[1],
        "row": r[2],
        "col": r[3],
        "ranks": ranks,
        "icon": spell_icons.get(ranks[0], ""),
        # The arrow on the trainer's grid: [talent id, rank of it needed].
        "requires": requires,
    }


def main(dbc_dir: str, out_dir: str) -> None:
    icon_rows, icon_strings = read_dbc(f"{dbc_dir}/SpellIcon.dbc")
    icons = {r[0]: icon_name(cstr(icon_strings, r[1])) for r in icon_rows if r[1]}
    trees = load_trees(dbc_dir, icons)

    talent_rows, _ = read_dbc(f"{dbc_dir}/Talent.dbc")
    wanted: set[int] = set()
    for r in talent_rows:
        wanted.update(s for s in r[TALENT_RANK_FIELDS] if s)
    names, spell_icons = load_spells(dbc_dir, wanted, icons)

    talents = []
    for r in talent_rows:
        ranks = [s for s in r[TALENT_RANK_FIELDS] if s]
        if str(r[1]) in trees and ranks:
            talents.append(talent_entry(r, ranks, names, spell_icons))

    # Two talents in the shipped file (Sanctified Retribution, Merciless
    # Combat) still point at a prerequisite that was removed from the tree
    # before 3.3.5a. An arrow to nowhere is dropped here, once, rather than
    # handled by every reader.
    known = {t["id"] for t in talents}
    for t in talents:
        t["requires"] = [req for req in t["requires"] if req[0] in known]

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
        f.write("\n")
    print(f"trees: {len(trees)}  talents: {len(talents)}  rank spells: {len(wanted)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
