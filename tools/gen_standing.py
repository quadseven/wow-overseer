"""Generate the standing reference JSON from client data (one-time, committed).

WHY THIS EXISTS. `character_skills`, `character_reputation` and
`character_spell` are three tables of pure numbers. A row says skill 333 is
0/0, faction 72 is at 3577, spell 3275 is known - and not one of those is a
sentence anybody can read. Turning them back into "Enchanting, untrained",
"Stormwind, Friendly 3677/6000" and "Linen Bandage" needs the client's own
tables, and those are exactly what this server does NOT have.

THE WALL, MEASURED. Every `*_dbc` table in acore_world on this realm is
empty, because the core reads the real DBCs off disk instead:

    talent_dbc  talenttab_dbc  faction_dbc  skillline_dbc
    skilllineability_dbc  skillraceclassinfo_dbc  skilltiers_dbc

    SELECT COUNT(*)  ->  0, every one of them (verified 2026-09-02)

and `acore_world.faction` does not exist at all. So the join a reader would
reach for first - `character_reputation` against `faction_dbc` for names -
silently yields nothing rather than failing, which is the worst shape a
missing dependency can take.

WHY THIS SHAPE. tools/gen_talents.py hit this exact wall for talents and
answered it by freezing the DBCs into a committed JSON book; gen_items.py
did the same for items. 3.3.5a client data never changes, so the output is
committed rather than built per-run, and no runtime process needs a DBC
mount. This is the third book, built the same way, for the same reason.

Inputs (3.3.5a client data, as extracted into the worldserver's data/dbc):
  SkillLine.dbc         skill id -> name, category and icon
  Faction.dbc           faction id -> name, reputation index, and the BASE
                        reputation table (see below - without it every
                        standing this page prints is wrong)
  SkillLineAbility.dbc  spell id -> which skill line it belongs to, and the
                        skill rank it needs
  Spell.dbc             spell id -> name, and what the spell makes
  SpellIcon.dbc         icon id -> icon file, whose bare name is what the
                        page asks the icon host for (for the SKILL icons;
                        see below for why recipes carry none)

Output (into the service dir root - the image build's shared-dir copy takes
top-level files only, so this stays flat beside the code):
  standing.json         icons + skills + factions + recipes

THE RECIPE TABLE IS POSITIONAL, and that is the one place this file trades
legibility for size. Three and a half thousand recipes written as objects
spend a third of the file on the same four key names repeated per row. So a
recipe is [name, skill, rank, creates], and skill icons are interned into
one shared list - the same index-into-a-list scheme icons.json already
uses, decoded once in StandingBook.load so nothing downstream sees an index.

RECIPES CARRY NO ICON, deliberately. Spell.dbc gives a crafting spell a
generic trade-skill picture - `Linen Bandage` and `Big Black Mace` are both
`spell_shadow_sealofkings` - because the game draws the recipe list from
the icon of the ITEM the recipe makes, not from the spell. Freezing the
spell's icon would put a confident wrong picture beside every recipe, which
is worse than none: the achievements tab already draws an item line with no
icon when the book has none, and that is the shape this follows. `creates`
is carried so the produced item stays resolvable later.

BASE REPUTATION IS NOT OPTIONAL. `character_reputation.standing` is stored
RELATIVE to a base the client reads out of Faction.dbc, and the core adds
the two back together on load (ReputationMgr::GetReputation). The base is
picked by race and class mask, and it is large: 3000 or 4000 for an
Alliance character's own capitals. Grug's Stormwind row says 7186; the
number a person should read is 11186, which is Honored and not Friendly.
Dropping the base would put four of the family's twenty-five standings in
the wrong RANK, so the masks and values are carried here and applied in
standing.py rather than assumed to be zero.

WHAT COUNTS AS A RECIPE. A profession-linked spell that CREATES something -
an item, or an enchantment on one. The profession rank spells (`Alchemy`,
`Journeyman Herbalism`) are linked to the same skill lines and make nothing,
and listing them under "what they can make" would answer the question with
its own premise. The effect ids are the core's own SpellEffects enum.

Usage: python3 gen_standing.py <dbc_dir> <out_dir>
"""
from __future__ import annotations

import json
import struct
import sys

# Spell.dbc (3.3.5a) is 234 fields wide. The name is where gen_talents.py
# already found it; the effect and item-type triples were located the same
# way that file located its two - against the file itself, not off a struct
# definition. Spell 3275 (`Linen Bandage`) has effect 24 (CREATE_ITEM) in
# field 71 and item 1251 in field 107, which is what fixes both triples.
SPELL_NAME_FIELD = 136
SPELL_EFFECT_FIELDS = slice(71, 74)
SPELL_ITEM_FIELDS = slice(107, 110)

# The core's SpellEffects, for the four that make a thing a person can hold
# or wear. CREATE_ITEM_2 is the "make several" variant; the three enchant
# effects are how an enchanter's whole recipe list is spelled, since an
# enchant produces no item at all.
MAKES_SOMETHING = frozenset({
    24,   # SPELL_EFFECT_CREATE_ITEM
    53,   # SPELL_EFFECT_ENCHANT_ITEM
    54,   # SPELL_EFFECT_ENCHANT_ITEM_TEMPORARY
    156,  # SPELL_EFFECT_ENCHANT_ITEM_PRISMATIC
    157,  # SPELL_EFFECT_CREATE_ITEM_2
})

# SkillLine.dbc: ID, CategoryID, SkillCostsID, DisplayName_Lang[16] + mask,
# Description_Lang[16] + mask, SpellIconID, AlternateVerb_Lang[16] + mask,
# CanLink. 56 fields.
SKILL_CATEGORY_FIELD = 1
SKILL_NAME_FIELD = 3
SKILL_ICON_FIELD = 37

# SkillLineAbility.dbc: ID, SkillLine, Spell, RaceMask, ClassMask,
# ExcludeRace, ExcludeClass, MinSkillLineRank, SupercededBySpell,
# AcquireMethod, TrivialSkillLineRankHigh, TrivialSkillLineRankLow,
# CharacterPoints[2]. 14 fields.
ABILITY_SKILL_FIELD = 1
ABILITY_SPELL_FIELD = 2
ABILITY_MIN_RANK_FIELD = 7

# Faction.dbc: ID, ReputationIndex, ReputationRaceMask[4],
# ReputationClassMask[4], ReputationBase[4], ReputationFlags[4],
# ParentFactionID, ParentFactionMod[2], ParentFactionCap[2],
# Name_Lang[16] + mask, Description_Lang[16] + mask. 57 fields.
FACTION_INDEX_FIELD = 1
FACTION_RACE_MASK_FIELDS = slice(2, 6)
FACTION_CLASS_MASK_FIELDS = slice(6, 10)
FACTION_BASE_FIELDS = slice(10, 14)
FACTION_NAME_FIELD = 23

# The trade skills a recipe can belong to: the ten primaries and the three
# secondaries, by SkillLine id. Deliberately a literal list rather than
# "every skill in category 11 or 9" - SkillLine's own SECONDARY category
# also holds the racial passives and Riding, none of which make anything,
# and a category-shaped rule would sweep them in. These ids are the same
# ones goals.SKILL_IDS carries, which is the module that already owns
# "which number is which profession" for this service.
TRADE_SKILLS = frozenset({
    129,  # First Aid
    164,  # Blacksmithing
    165,  # Leatherworking
    171,  # Alchemy
    182,  # Herbalism
    185,  # Cooking
    186,  # Mining
    197,  # Tailoring
    202,  # Engineering
    333,  # Enchanting
    356,  # Fishing
    393,  # Skinning
    755,  # Jewelcrafting
    773,  # Inscription
})


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


def signed(value: int) -> int:
    """DBC fields are read as unsigned; these four columns are not.

    ReputationIndex is -1 for a faction with no reputation bar, and a base
    reputation is negative for anyone starting out hated. Read unsigned,
    both come back as numbers near 4.29 billion, which sort and compare
    perfectly happily and are silently wrong.
    """
    return struct.unpack("<i", struct.pack("<I", value))[0]


def icon_name(path: str) -> str:
    r"""'Interface\Icons\Trade_Alchemy' -> 'trade_alchemy'."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


class Interner:
    """Icon names -> a shared list plus the index of each, built as it goes.

    Two thousand recipes share a few hundred icons between them; written
    out per row they are most of what the file weighs.
    """

    def __init__(self) -> None:
        self.names: list[str] = []
        self._index: dict[str, int] = {}

    def index(self, name: str) -> int:
        found = self._index.get(name)
        if found is None:
            found = self._index[name] = len(self.names)
            self.names.append(name)
        return found


def load_skills(dbc_dir: str, icons: dict[int, str], pool: Interner) -> dict[str, list]:
    """SkillLine.dbc -> every skill line, keyed by id.

    Positional, like the recipes and for the same reason: [name, category,
    icon]. A hundred and fifty rows is not where the file's weight is, but
    two shapes for the same kind of row is a reason to look twice at each.
    """
    rows, strings = read_dbc(f"{dbc_dir}/SkillLine.dbc")
    return {
        str(r[0]): [
            cstr(strings, r[SKILL_NAME_FIELD]),
            r[SKILL_CATEGORY_FIELD],
            pool.index(icons.get(r[SKILL_ICON_FIELD], "")),
        ]
        for r in rows
    }


def load_factions(dbc_dir: str) -> dict[str, dict]:
    """Faction.dbc -> the factions a character can hold a standing with.

    Only those with a reputation index: the core creates a reputation row
    for no others (ReputationMgr::LoadFromDB skips them), so a faction
    without one can never appear in `character_reputation` and carrying it
    would be dead weight in a committed file.
    """
    rows, strings = read_dbc(f"{dbc_dir}/Faction.dbc")
    out: dict[str, dict] = {}
    for r in rows:
        index = signed(r[FACTION_INDEX_FIELD])
        if index < 0:
            continue
        # The four base-reputation entries, in the order the core tries
        # them. Zero-value entries are kept: an entry is chosen by its
        # MASKS, and dropping a zero one would let a later, non-zero entry
        # match a character the client would have stopped at zero for.
        base = [
            [race, cls, signed(value)]
            for race, cls, value in zip(r[FACTION_RACE_MASK_FIELDS],
                                        r[FACTION_CLASS_MASK_FIELDS],
                                        r[FACTION_BASE_FIELDS], strict=True)
        ]
        out[str(r[0])] = {
            "name": cstr(strings, r[FACTION_NAME_FIELD]),
            "index": index,
            "base": base,
        }
    return out


def load_recipes(dbc_dir: str) -> dict[str, list]:
    """SkillLineAbility.dbc + Spell.dbc -> what each trade skill can make.

    A spell can be linked to a skill line more than once (a different race
    or class mask per row); the LOWEST required rank wins, which is the
    rank the character who has it will actually have needed.
    """
    ability_rows, _ = read_dbc(f"{dbc_dir}/SkillLineAbility.dbc")
    wanted: dict[int, tuple[int, int]] = {}
    for r in ability_rows:
        skill = r[ABILITY_SKILL_FIELD]
        if skill not in TRADE_SKILLS:
            continue
        spell = r[ABILITY_SPELL_FIELD]
        rank = r[ABILITY_MIN_RANK_FIELD]
        current = wanted.get(spell)
        if current is None or rank < current[1]:
            wanted[spell] = (skill, rank)

    spell_rows, spell_strings = read_dbc(f"{dbc_dir}/Spell.dbc")
    out: dict[str, list] = {}
    for r in spell_rows:
        found = wanted.get(r[0])
        if found is None:
            continue
        if not any(e in MAKES_SOMETHING for e in r[SPELL_EFFECT_FIELDS]):
            continue  # a profession rank spell, not a recipe
        skill, rank = found
        # The item the recipe produces, when it produces one. An enchant
        # makes no item, so this is 0 there and the spell's own name -
        # "Enchant Bracer - Minor Health" - is the whole answer.
        creates = next((i for i in r[SPELL_ITEM_FIELDS] if i), 0)
        name = cstr(spell_strings, r[SPELL_NAME_FIELD]) if r[SPELL_NAME_FIELD] else ""
        out[str(r[0])] = [name, skill, rank, creates]
    return out


def main(dbc_dir: str, out_dir: str) -> None:
    icon_rows, icon_strings = read_dbc(f"{dbc_dir}/SpellIcon.dbc")
    icons = {r[0]: icon_name(cstr(icon_strings, r[1])) for r in icon_rows if r[1]}

    pool = Interner()
    skills = load_skills(dbc_dir, icons, pool)
    factions = load_factions(dbc_dir)
    recipes = load_recipes(dbc_dir)

    with open(f"{out_dir}/standing.json", "w") as f:
        # Minified, the same posture talents.json and shapes.json take and
        # for the same reason: machine-written, machine-read, nobody hand
        # edits it, and indentation nobody reads is the difference between
        # a file a reviewer can hold in one pass and one they cannot.
        json.dump({"icons": pool.names, "skills": skills,
                   "factions": factions, "recipes": recipes}, f,
                  separators=(",", ":"), sort_keys=True)
        f.write("\n")
    print(f"skills: {len(skills)}  factions: {len(factions)}  "
          f"recipes: {len(recipes)}  icons: {len(pool.names)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
