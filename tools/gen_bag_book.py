"""Generate bagicons.json and bagspells.json: the book for what is carried.

icons.json (gen_items.py) freezes icon names only for the displays Item.dbc
marks as equippable, because the Armory's paper doll was its only reader.
The virtual client draws BAGS, and what is in a bag is mostly the other
kind: cloth, reagents, food, quest items, keys, recipes and the bags
themselves. Without this file every one of those draws as its initials.

This is the complement, kept as its own file for the reason gen_items.py
gives for splitting its output: the repository refuses a single file over
500KB, and icons.json plus this would cross it. The shape is the same
(names listed once, each display pointing at one by index), and a display
already in icons.json is left out so the two never disagree.

bagspells.json does the same for spell TEXT. spells.json freezes the
description of every spell an equippable item names, so "Use: Restores 243
health over 18 sec." on a piece of bread was "Use: spell #433". This adds
the spells the carried items name with a trigger a tooltip draws, listed in
tools/bag_spells.txt, less the ones spells.json already has. Refresh the
list with (triggers 0, 1, 2 and 5 are the ones armory.SPELL_TRIGGERS draws;
the rest, a recipe's learn spell among them, are not a tooltip line):

  SELECT DISTINCT s FROM (
    SELECT spellid_1 s FROM item_template
     WHERE spellid_1 > 0 AND InventoryType = 0 AND spelltrigger_1 IN (0,1,2,4,5)
    UNION ... the same for spellid_2 to spellid_5
  ) x ORDER BY s;

The ART is not here and is not anywhere this server can read: the 3.3.5a
client keeps it in its MPQ archives, and the extracted client data the
worldserver runs on carries only the DBC tables. So the file maps a display
to the icon's NAME, which is what the page asks the icon host for.

Inputs (3.3.5a client data, as extracted into the worldserver's data/dbc):
  Item.dbc, ItemDisplayInfo.dbc, Spell.dbc, SpellDuration.dbc, and the
  committed icons.json and spells.json.

Usage: python3 gen_bag_book.py <dbc_dir> <out_dir>
"""

from __future__ import annotations

import json
import os
import sys

from gen_items import (
    DISPLAY_ICON,
    ITEM_DISPLAY,
    ITEM_INVENTORY_TYPE,
    cstr,
    freeze_spells,
    icon_name,
    read_dbc,
)


def freeze_bag_icons(dbc_dir: str, worn: set[int]) -> dict:
    """display id -> icon name, for non-equippable displays not in `worn`."""
    item_rows, _ = read_dbc(f"{dbc_dir}/Item.dbc")
    carried = {r[ITEM_DISPLAY] for r in item_rows if not r[ITEM_INVENTORY_TYPE]} - worn
    display_rows, display_strings = read_dbc(f"{dbc_dir}/ItemDisplayInfo.dbc")
    by_display = {
        r[0]: icon_name(cstr(display_strings, r[DISPLAY_ICON]))
        for r in display_rows
        if r[0] in carried and r[DISPLAY_ICON]
    }
    names = sorted(set(by_display.values()))
    index = {name: i for i, name in enumerate(names)}
    return {
        "names": names,
        "display": {str(d): index[n] for d, n in sorted(by_display.items())},
    }


def main(dbc_dir: str, out_dir: str) -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "icons.json")) as f:
        worn = {int(d) for d in json.load(f)["display"]}
    with open(os.path.join(out_dir, "spells.json")) as f:
        known = {int(k) for k in json.load(f)}
    with open(os.path.join(here, "bag_spells.txt")) as f:
        wanted = {int(line) for line in f if line.strip()} - known
    icons = freeze_bag_icons(dbc_dir, worn)
    # "$z" is the hearthstone's bind point, which the client fills in from
    # the character. A frozen book has no character, so it says what it is.
    spells = {
        k: v.replace("$z", "your home location")
        for k, v in freeze_spells(dbc_dir, wanted).items()
    }
    for name, book in (("bagicons.json", icons), ("bagspells.json", spells)):
        with open(os.path.join(out_dir, name), "w") as f:
            json.dump(book, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")
    print(
        f"bag icons: {len(icons['display'])} displays, {len(icons['names'])} "
        f"names; bag spells: {len(spells)}"
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
