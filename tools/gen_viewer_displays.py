"""Generate viewerdisplays.json: the model host's display id for a worn item.

WHY THIS FILE EXISTS. The Armory draws each character in Wowhead's model
viewer, and the viewer fetches one metadata file per worn piece, named by a
DISPLAY id: meta/armor/<slot>/<display>.json, or meta/item/<display>.json for
anything held. The world database names a display id for every item too, in
item_template.displayid - but it is the 3.3.5a client's number, and the model
host does not use that numbering. Its art is keyed by the display ids of the
modern Wrath Classic client, whose item tables were rebuilt: roughly half of
the equippable items kept their old number and the other half got a new one.
Every item in the second half was a 404 on the model host, which the viewer
swallows, so the character was drawn without it.

Measured on the dev world when this was written: Neophyte's Shirt (entry 53)
is display 9944 in item_template and 8370 on the model host; Jouster's
Chestplate (8157) is 27340 and 13028; Banded Cloak (9838) 27779 and 26018.
Every one of the 3.3.5a numbers is a 404 upstream and every modern one is
there.

HOW THE MODERN NUMBER IS FOUND. Two Wrath Classic client tables, exported as
CSV (wago.tools serves both for any build):

  ItemModifiedAppearance  ItemID, ItemAppearanceModifierID -> ItemAppearanceID
  ItemAppearance          ID -> ItemDisplayInfoID

The base appearance of an item is its modifier-0 row; its display is that
appearance's ItemDisplayInfoID. This is the same resolution the open-source
wrapper around the viewer relies on, and it agrees with it on every item
checked.

WHAT IS FROZEN. Only the items whose modern display DIFFERS from what the
world database already says, keyed by item entry. An entry that is absent
means the world's own display id is already the model host's, which is true
for about half of them, and keeps the file well under the repository's 500KB
cap. Items the modern client does not know (custom items, a few removed ones)
are absent too, so they keep the world's number and are reported as undrawn
exactly as before - a claim this file cannot improve on.

Inputs:
  ItemModifiedAppearance.csv, ItemAppearance.csv  (Wrath Classic, 3.4.x)
  a TSV of the world database's equippable items, no header:

    SELECT entry, displayid, InventoryType FROM acore_world.item_template
    WHERE InventoryType > 0 AND displayid > 0;

Usage: python3 gen_viewer_displays.py <csv_dir> <items.tsv> <out_dir> <build>
"""
from __future__ import annotations

import csv
import json
import os
import sys


def base_displays(modified_rows, appearance_rows) -> dict[int, int]:
    """item entry -> the modern client's display id for its base look."""
    appearance = {}
    for row in modified_rows:
        if int(row["ItemAppearanceModifierID"]) != 0:
            continue
        appearance.setdefault(int(row["ItemID"]), int(row["ItemAppearanceID"]))
    display_of = {int(r["ID"]): int(r["ItemDisplayInfoID"]) for r in appearance_rows}
    out = {}
    for item, app in appearance.items():
        display = display_of.get(app)
        if display:
            out[item] = display
    return out


def differing(world_rows, modern: dict[int, int]) -> dict[int, int]:
    """Only the entries whose modern display is not the world's own."""
    out = {}
    for entry, display, _inventory_type in world_rows:
        new = modern.get(entry)
        if new and new != display:
            out[entry] = new
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    csv_dir, tsv, out_dir, build = argv[1:]
    with open(os.path.join(csv_dir, "ItemModifiedAppearance.csv"), newline="") as f:
        modified = list(csv.DictReader(f))
    with open(os.path.join(csv_dir, "ItemAppearance.csv"), newline="") as f:
        appearances = list(csv.DictReader(f))
    with open(tsv) as f:
        world = [tuple(int(v) for v in line.split()) for line in f if line.strip()]
    table = differing(world, base_displays(modified, appearances))
    payload = {"build": build,
               "display": {str(k): table[k] for k in sorted(table)}}
    path = os.path.join(out_dir, "viewerdisplays.json")
    with open(path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
        f.write("\n")
    print(f"{len(table)} of {len(world)} items remapped -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
