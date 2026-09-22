"""Generate the item reference JSON from client data (one-time, committed).

The Armory tab draws each worn item as the game draws it: its own icon, and a
tooltip with the same lines the client shows. Almost all of that is in
acore_world.item_template and is read live. The rest is CLIENT data the
server database does not carry, and this freezes exactly that, the way
gen_talents.py freezes the talent tables and gen_geometry.py the zone maps:

  icons     item_template names a displayid; the icon is a property of the
            DISPLAY, in ItemDisplayInfo.dbc, and nowhere in the database.
  spells    "Equip: Improves your chance to hit by 1%." is the DESCRIPTION
            of the spell item_template names in spellid_N, and spell text is
            in Spell.dbc. The $s1/$d macros in that text are resolved here,
            at freeze time, from the same spell row - so the file carries
            the sentence a player reads, not the template behind it.
  sets      Set name, member items and (n) bonus thresholds: ItemSet.dbc.
  enchants  What an enchantment DOES (a stat, a resistance, a proc) and its
            name: SpellItemEnchantment.dbc. Every green "of the Tiger" in
            the family's bags carries its stats this way, so without it half
            their gear reads as having no stats at all.
  suffixes  "of the Monkey" and the allocation that scales its stats by item
            level: ItemRandomSuffix.dbc, ItemRandomProperties.dbc and
            RandPropPoints.dbc, the same three the core reads to apply them.

Inputs (3.3.5a client data, as extracted into the worldserver's data/dbc):
  Item.dbc, ItemDisplayInfo.dbc, Spell.dbc, SpellDuration.dbc, ItemSet.dbc,
  SpellItemEnchantment.dbc, ItemRandomSuffix.dbc, ItemRandomProperties.dbc,
  RandPropPoints.dbc

  plus tools/item_spells.txt: the spell ids item_template actually names in
  spellid_1..5, one per line. Spell.dbc has 49k spells; the ~2k an item can
  cast or carry are the only ones worth freezing, and WHICH ones is a fact
  about the world database, not the client. Refresh it with:

  SELECT DISTINCT s FROM (
    SELECT spellid_1 s FROM item_template WHERE spellid_1 > 0 AND InventoryType > 0
    UNION SELECT spellid_2 FROM item_template WHERE spellid_2 > 0 AND InventoryType > 0
    UNION SELECT spellid_3 FROM item_template WHERE spellid_3 > 0 AND InventoryType > 0
    UNION SELECT spellid_4 FROM item_template WHERE spellid_4 > 0 AND InventoryType > 0
    UNION SELECT spellid_5 FROM item_template WHERE spellid_5 > 0 AND InventoryType > 0
  ) x ORDER BY s;

Output (into the service dir root, flat beside the code, for the same
image-build reason gen_talents.py gives). Three files by concern rather
than one, because the repository refuses a single file over 500KB
(check-added-large-files) and together they are 780KB minified:
  icons.json    display id -> icon name
  spells.json   spell id -> the sentence a tooltip shows
  items.json    sets, enchantments, random suffixes and properties, and
                the RandPropPoints table

Icons are frozen for the displayids Item.dbc marks as equippable (an
InventoryType) - 18.7k of the 43k displays the client knows. The other 24k
are bags, reagents, quest items and recipes, which never sit in a paper-doll
slot and would double the file for nothing.

Usage: python3 gen_items.py <dbc_dir> <out_dir>
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys

# Spell.dbc (3.3.5a), the fields this reads. Verified against the file:
# 136 is the enUS name (gen_talents.py relies on the same), 170 the enUS
# description, 133 the icon. The effect arrays are three wide.
SPELL_NAME = 136
SPELL_DESC = 170
SPELL_ICON = 133
SPELL_DURATION_INDEX = 40
SPELL_PROC_CHANCE = 35
SPELL_PROC_CHARGES = 36
SPELL_STACKS = 49
SPELL_EFFECT_DIE_SIDES = slice(74, 77)
SPELL_EFFECT_BASE_POINTS = slice(80, 83)
SPELL_EFFECT_AMPLITUDE = slice(98, 101)
SPELL_EFFECT_CHAIN = slice(104, 107)
SPELL_EFFECT_TRIGGER = slice(116, 119)

# Item.dbc: ID, Class, Subclass, SoundOverride, Material, DisplayId,
# InventoryType, Sheath.
ITEM_DISPLAY = 5
ITEM_INVENTORY_TYPE = 6

# ItemDisplayInfo.dbc: ID, ModelName[2], ModelTexture[2], InventoryIcon[2], ...
DISPLAY_ICON = 5

# ItemSet.dbc: ID, Name[16]+mask, ItemID[17], SpellID[8], Threshold[8], ...
SET_NAME = 1
SET_ITEMS = slice(18, 35)
SET_SPELLS = slice(35, 43)
SET_THRESHOLDS = slice(43, 51)

# SpellItemEnchantment.dbc: ID, Charges, Effect[3], Min[3], Max[3], Arg[3],
# Name[16]+mask, ...
ENCHANT_EFFECTS = slice(2, 5)
ENCHANT_MIN = slice(5, 8)
ENCHANT_ARGS = slice(11, 14)
ENCHANT_NAME = 14

# ItemRandomSuffix.dbc: ID, Name[16]+mask, InternalName, Enchantment[5],
# AllocationPct[5].
SUFFIX_NAME = 1
SUFFIX_ENCHANTS = slice(19, 24)
SUFFIX_PCT = slice(24, 29)

# ItemRandomProperties.dbc: ID, InternalName, Enchantment[5], Name[16]+mask.
PROPERTY_ENCHANTS = slice(2, 7)
PROPERTY_NAME = 7

# RandPropPoints.dbc: ID (= item level), Epic[5], Rare[5], Good[5].
POINTS_EPIC = slice(1, 6)
POINTS_RARE = slice(6, 11)
POINTS_GOOD = slice(11, 16)


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


def signed(v: int) -> int:
    return v - (1 << 32) if v >= (1 << 31) else v


def icon_name(path: str) -> str:
    """'Interface\\Icons\\INV_Sword_04' -> 'inv_sword_04', the bare name."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def duration_text(ms: int) -> str:
    """Milliseconds -> the client's own '$d' wording."""
    if ms < 0:
        return "until cancelled"
    seconds = ms / 1000
    if seconds < 60:
        n = seconds
        unit = "sec"
    elif seconds < 3600:
        n = seconds / 60
        unit = "min"
    else:
        n = seconds / 3600
        unit = "hrs" if seconds / 3600 != 1 else "hour"
    shown = str(int(n)) if n == int(n) else f"{n:.1f}"
    return f"{shown} {unit}"


def number(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:g}"


class Expander:
    """Turns a Spell.dbc description into the sentence the client shows.

    The client fills '$s1' from the spell's own effect table at draw time.
    Nothing draws these at runtime here, so the same fill happens once, at
    freeze. Only the macros item and set-bonus text actually use are handled
    (the counts came from the file: $s, $d, $m, $M, $o, $t, $h, $n, $u, $x
    and the ${...} arithmetic form). Anything else is left exactly as
    written, so an unhandled macro shows as '$foo' in a tooltip rather than
    as a quietly wrong number.
    """

    # '$s1', '$12345s1' (another spell's effect), '$/1000;s1' (divided).
    # The lookahead keeps '$max(' and '$min(' out of it: '$m' would
    # otherwise eat the first two letters and leave 'ax(' behind.
    MACRO = re.compile(r"\$(?:/(\d+);)?(\d*)([sSmMoOtTdDhHnNuUxX])(\d?)(?![a-zA-Z])")
    EXPR = re.compile(r"\$\{([^}]*)\}(\.\d)?")
    PLURAL = re.compile(r"\$[lL]([^:;]*):([^;]*);")
    COLOUR = re.compile(r"\|c[0-9a-fA-F]{8}|\|r")

    def __init__(self, spells: dict[int, tuple], durations: dict[int, int]):
        self.spells = spells
        self.durations = durations

    def _duration(self, row: tuple) -> int:
        return signed(self.durations.get(row[SPELL_DURATION_INDEX], 0))

    def _periodic_total(self, row: tuple, i: int, low: int) -> str:
        amp = row[SPELL_EFFECT_AMPLITUDE][i]
        ticks = self._duration(row) // amp if amp else 1
        return str(abs(low) * max(ticks, 1))

    def value(self, row: tuple, kind: str, index: int) -> str | None:
        """One macro letter -> its text for this spell, or None if unknown."""
        i = index - 1 if index else 0
        base = signed(row[SPELL_EFFECT_BASE_POINTS][i])
        sides = signed(row[SPELL_EFFECT_DIE_SIDES][i])
        low, high = base + 1, base + max(sides, 1)
        amp = row[SPELL_EFFECT_AMPLITUDE][i]
        # Each letter, by what the client fills it with. Lambdas so that only
        # the one asked for is computed.
        letters = {
            "s": lambda: f"{abs(low)} to {abs(high)}" if sides > 1 else str(abs(low)),
            "m": lambda: str(abs(low)),
            "M": lambda: str(abs(high)),
            "o": lambda: self._periodic_total(row, i, low),
            "t": lambda: number(amp / 1000) if amp else None,
            "d": lambda: duration_text(self._duration(row)),
            "h": lambda: str(row[SPELL_PROC_CHANCE]),
            "n": lambda: str(row[SPELL_PROC_CHARGES]),
            "u": lambda: str(row[SPELL_STACKS]),
            "x": lambda: str(row[SPELL_EFFECT_CHAIN][i]),
        }
        # Case matters only for m/M (min and max); every other letter has an
        # upper-case twin the client treats the same.
        key = kind if kind in "mM" else kind.lower()
        fill = letters.get(key)
        return fill() if fill else None

    def expand(self, spell_id: int, text: str) -> str:
        row = self.spells[spell_id]

        def macro(m: re.Match) -> str:
            divisor, other, kind, index = m.groups()
            source = self.spells.get(int(other)) if other else row
            if source is None:
                return m.group(0)
            got = self.value(source, kind, int(index) if index else 0)
            if got is None:
                return m.group(0)
            if divisor and re.fullmatch(r"\d+", got):
                return number(int(got) / int(divisor))
            return got

        def expr(m: re.Match) -> str:
            inner = self.MACRO.sub(macro, m.group(1))
            if not re.fullmatch(r"[\d\s+\-*/().]+", inner):
                return m.group(0)
            try:
                result = eval(inner, {"__builtins__": {}}, {})  # noqa: S307 - digits and operators only, checked above
            except (SyntaxError, ZeroDivisionError, TypeError):
                return m.group(0)
            if m.group(2):
                return f"{result:.{int(m.group(2)[1])}f}"
            return number(result)

        def plural(m: re.Match) -> str:
            # The client pluralises on the number just before the macro; a
            # description that puts it elsewhere gets the plural, which is
            # the reading that is wrong least often ("N charges").
            before = text[: m.start()].rstrip()
            last = re.search(r"(\d+)\s*$", before)
            return m.group(1) if last and last.group(1) == "1" else m.group(2)

        text = self.COLOUR.sub("", text)
        text = self.EXPR.sub(expr, text)
        text = self.MACRO.sub(macro, text)
        text = self.PLURAL.sub(plural, text)
        return text.replace("\r\n", "\n").replace("|n", "\n").strip()


def freeze_icons(dbc_dir: str) -> dict:
    """display id -> icon name, for the equippable displays only."""
    item_rows, _ = read_dbc(f"{dbc_dir}/Item.dbc")
    equippable = {r[ITEM_DISPLAY] for r in item_rows if r[ITEM_INVENTORY_TYPE]}
    display_rows, display_strings = read_dbc(f"{dbc_dir}/ItemDisplayInfo.dbc")
    # 18.9k displays share 2.7k icon names, so the names are listed once
    # and each display points at one by index. This is the single largest
    # section of the freeze and the difference is a third of its size.
    by_display = {
        r[0]: icon_name(cstr(display_strings, r[DISPLAY_ICON]))
        for r in display_rows
        if r[0] in equippable and r[DISPLAY_ICON]
    }
    names = sorted(set(by_display.values()))
    index = {name: i for i, name in enumerate(names)}
    display = {str(d): index[n] for d, n in by_display.items()}
    return {"names": names, "display": display}


def freeze_sets(dbc_dir: str) -> tuple[dict, set[int]]:
    """Sets and their bonuses, plus the bonus spells whose text is wanted."""
    set_rows, set_strings = read_dbc(f"{dbc_dir}/ItemSet.dbc")
    sets: dict[str, dict] = {}
    wanted: set[int] = set()
    for r in set_rows:
        bonuses = sorted(
            (threshold, spell)
            for spell, threshold in zip(r[SET_SPELLS], r[SET_THRESHOLDS], strict=True)
            if spell
        )
        wanted.update(spell for _, spell in bonuses)
        sets[str(r[0])] = {
            "name": cstr(set_strings, r[SET_NAME]),
            "items": [i for i in r[SET_ITEMS] if i],
            "bonuses": [[threshold, spell] for threshold, spell in bonuses],
        }
    return sets, wanted


def freeze_enchants(dbc_dir: str) -> tuple[dict, set[int]]:
    """Enchantments, plus the spells their proc/equip/use effects name."""
    enchant_rows, enchant_strings = read_dbc(f"{dbc_dir}/SpellItemEnchantment.dbc")
    enchants: dict[str, list] = {}
    wanted: set[int] = set()
    for r in enchant_rows:
        effects = []
        effect_columns = zip(
            r[ENCHANT_EFFECTS], r[ENCHANT_MIN], r[ENCHANT_ARGS], strict=True
        )
        for kind, amount, arg in effect_columns:
            if kind:
                effects.append([kind, amount, arg])
                # 1 = proc, 3 = equip spell, 7 = use spell: the arg is a spell
                # whose description is the tooltip line.
                if kind in (1, 3, 7):
                    wanted.add(arg)
        name = cstr(enchant_strings, r[ENCHANT_NAME]) if r[ENCHANT_NAME] else ""
        enchants[str(r[0])] = [name, effects]
    return enchants, wanted


def freeze_random(dbc_dir: str) -> tuple[dict, dict, dict]:
    """The random suffix and property tables and the points that scale them."""
    suffix_rows, suffix_strings = read_dbc(f"{dbc_dir}/ItemRandomSuffix.dbc")
    suffixes = {
        str(r[0]): [
            cstr(suffix_strings, r[SUFFIX_NAME]),
            [
                [e, pct]
                for e, pct in zip(r[SUFFIX_ENCHANTS], r[SUFFIX_PCT], strict=True)
                if e
            ],
        ]
        for r in suffix_rows
    }
    property_rows, property_strings = read_dbc(f"{dbc_dir}/ItemRandomProperties.dbc")
    properties = {
        str(r[0]): [
            cstr(property_strings, r[PROPERTY_NAME]) if r[PROPERTY_NAME] else "",
            [e for e in r[PROPERTY_ENCHANTS] if e],
        ]
        for r in property_rows
    }
    points_rows, _ = read_dbc(f"{dbc_dir}/RandPropPoints.dbc")
    # Per item level: [epic, rare, uncommon], each five wide, indexed by the
    # slot group the core picks from the inventory type.
    points = {
        str(r[0]): [list(r[POINTS_EPIC]), list(r[POINTS_RARE]), list(r[POINTS_GOOD])]
        for r in points_rows
    }
    return suffixes, properties, points


def freeze_spells(dbc_dir: str, wanted: set[int]) -> dict[str, str]:
    """spell id -> its description with the macros resolved.

    Text only. A tooltip shows what an equip effect DOES, never the name of
    the spell behind it ("Attack Power 20" is not a line anybody sees). A
    spell with no description is left out rather than frozen as "", so the
    reader can tell "no text" from "not in the book" and say so.
    """
    spell_rows, spell_strings = read_dbc(f"{dbc_dir}/Spell.dbc")
    by_id = {r[0]: r for r in spell_rows}
    duration_rows, _ = read_dbc(f"{dbc_dir}/SpellDuration.dbc")
    durations = {r[0]: r[1] for r in duration_rows}
    # Every spell, not just the wanted ones: '$12345s1' reaches into another
    # spell's effect table, and the trigger of a proc is where its numbers
    # usually are.
    expander = Expander(by_id, durations)
    spells: dict[str, str] = {}
    for spell_id in sorted(wanted):
        r = by_id.get(spell_id)
        if r is None or not r[SPELL_DESC]:
            continue
        text = expander.expand(spell_id, cstr(spell_strings, r[SPELL_DESC]))
        if text:
            spells[str(spell_id)] = text
    return spells


def main(dbc_dir: str, out_dir: str) -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "item_spells.txt")) as f:
        item_spells = {int(line) for line in f if line.strip()}
    icons = freeze_icons(dbc_dir)
    sets, set_spells = freeze_sets(dbc_dir)
    enchants, enchant_spells = freeze_enchants(dbc_dir)
    suffixes, properties, points = freeze_random(dbc_dir)
    spells = freeze_spells(dbc_dir, item_spells | set_spells | enchant_spells)
    books = {
        "icons.json": icons,
        "spells.json": spells,
        "items.json": {
            "sets": sets,
            "enchants": enchants,
            "suffixes": suffixes,
            "properties": properties,
            "points": points,
        },
    }
    for name, book in books.items():
        with open(f"{out_dir}/{name}", "w") as f:
            # Minified for the same reason talents.json is: machine-written,
            # machine-read, and nobody hand-edits it.
            json.dump(book, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")
    print(
        f"icons: {len(icons['display'])}  spells: {len(spells)}  sets: {len(sets)}  "
        f"enchants: {len(enchants)}  suffixes: {len(suffixes)}  "
        f"properties: {len(properties)}"
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
