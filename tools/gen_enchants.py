"""Freeze the Enchanting recipes the realm teaches (data/enchants.json).

The enchant-for planner (`enchantfor.py`) has to know, for every Enchanting
spell, which enchantment it writes, which item it fits, what it eats and what
that enchantment is worth. That is client data the world database does not
carry, so it is frozen here from the same three files tools/gen_items.py
reads, the way that tool freezes the item book.

Inputs (3.3.5a client data, as extracted into the worldserver's data/dbc):
  Spell.dbc, SkillLineAbility.dbc, SpellItemEnchantment.dbc, TotemCategory.dbc

`totem_categories` carries the TotemCategory rows the recipes' tools name:
id -> [type, mask]. The core's IsTotemCategoryCompatibleWith says a held
category answers a required one when they are the same, or when both have the
same type and the held mask holds every bit of the required mask. Runed Rods
are type 3 with cumulative masks, so a better rod answers a lower rung, and the
Outland and Northrend rods (41, 62, 63, 190) are one line above the arcanite
rod (10) that a Truesilver-era enchanter holds.

A recipe is every Spell.dbc row that SkillLineAbility.dbc files under the
Enchanting skill line (333) and whose effect is ENCHANT_ITEM (53).

Usage: python3 tools/gen_enchants.py <dbc_dir> <out_file>
"""

from __future__ import annotations

import json
import struct
import sys

ENCHANTING = 333
EFFECT_ENCHANT_ITEM = 53

SPELL_REAGENT = slice(52, 60)
SPELL_REAGENT_COUNT = slice(60, 68)
SPELL_TOTEM = slice(222, 224)
SPELL_ITEM_CLASS, SPELL_SUBCLASS_MASK, SPELL_INVTYPE_MASK = 68, 69, 70
SPELL_EFFECT = slice(71, 74)
SPELL_MISC = slice(110, 113)
SPELL_NAME = 136

ABILITY_SKILL, ABILITY_SPELL = 1, 2
# SkillLineAbility.dbc: ID, SkillLine, Spell, RaceMask, ClassMask,
# ExcludeRace, ExcludeClass, MinSkillLineRank, SupercededBySpell,
# AcquireMethod, TrivialSkillLineRankHigh, TrivialSkillLineRankLow.
ABILITY_TRIVIAL_HIGH, ABILITY_TRIVIAL_LOW = 10, 11

ENCHANT_EFFECTS = slice(2, 5)
ENCHANT_MIN = slice(5, 8)
ENCHANT_ARGS = slice(11, 14)
ENCHANT_NAME = 14

# TotemCategory.dbc: ID, Name[16]+mask, TotemCategoryType, TotemCategoryMask.
TOTEM_TYPE, TOTEM_MASK = -2, -1


def read_dbc(path: str):
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


def freeze_totems(dbc_dir: str, wanted) -> dict:
    """{category id: [type, mask]} for the categories in `wanted`."""
    rows, _ = read_dbc(f"{dbc_dir}/TotemCategory.dbc")
    return {str(r[0]): [r[TOTEM_TYPE], r[TOTEM_MASK]] for r in rows if r[0] in wanted}


def freeze(dbc_dir: str) -> list:
    spells, spell_strings = read_dbc(f"{dbc_dir}/Spell.dbc")
    by_id = {r[0]: r for r in spells}
    abilities, _ = read_dbc(f"{dbc_dir}/SkillLineAbility.dbc")
    enchants, enchant_strings = read_dbc(f"{dbc_dir}/SpellItemEnchantment.dbc")
    enchant_by_id = {r[0]: r for r in enchants}
    out = []
    for ability in abilities:
        if ability[ABILITY_SKILL] != ENCHANTING:
            continue
        row = by_id.get(ability[ABILITY_SPELL])
        if row is None:
            continue
        misc = None
        for effect, value in zip(row[SPELL_EFFECT], row[SPELL_MISC], strict=True):
            if effect == EFFECT_ENCHANT_ITEM:
                misc = value
        if misc is None:
            continue
        ench = enchant_by_id.get(misc)
        effects = []
        name = ""
        if ench is not None:
            for kind, amount, arg in zip(
                ench[ENCHANT_EFFECTS],
                ench[ENCHANT_MIN],
                ench[ENCHANT_ARGS],
                strict=True,
            ):
                if kind:
                    effects.append([kind, amount, arg])
            name = (
                cstr(enchant_strings, ench[ENCHANT_NAME]) if ench[ENCHANT_NAME] else ""
            )
        out.append(
            {
                "spell": row[0],
                "name": cstr(spell_strings, row[SPELL_NAME]),
                "enchant": misc,
                "enchant_name": name,
                "effects": effects,
                "yellow": ability[ABILITY_TRIVIAL_LOW],
                "grey": ability[ABILITY_TRIVIAL_HIGH],
                "reagents": [
                    [item, count]
                    for item, count in zip(
                        row[SPELL_REAGENT], row[SPELL_REAGENT_COUNT], strict=True
                    )
                    if item and count
                ],
                "tools": [t for t in row[SPELL_TOTEM] if t],
                "item_class": row[SPELL_ITEM_CLASS]
                if row[SPELL_ITEM_CLASS] < 1 << 31
                else -1,
                "subclass_mask": row[SPELL_SUBCLASS_MASK],
                "invtype_mask": row[SPELL_INVTYPE_MASK],
            }
        )
    out.sort(key=lambda r: r["spell"])
    return out


if __name__ == "__main__":
    recipes = freeze(sys.argv[1])
    tools = {t for r in recipes for t in r["tools"]}
    totems = freeze_totems(sys.argv[1], tools)
    with open(sys.argv[2], "w", newline="\n") as f:
        json.dump(
            {"recipes": recipes, "totem_categories": totems},
            f,
            separators=(",", ":"),
        )
        f.write("\n")
    print(len(recipes), "recipes")
