"""Pure builder for the virtual game client over the Watch tab's streams.

WHY THIS EXISTS. The Watch tab shows what a family head sees, and the Bags
tab and the Armory say what the family owns and wears, but none of them
looks like the game the stream is showing. The operator asked for the
client's own frames over the picture: click a character's bags and see them
the way a Bagnon user sees them, one grid with every slot drawn, hover an
item and read the game's tooltip, and the same for the bank, the guild bank,
the character sheet and the social window.

THE SEAM IS THE SAME ONE EVERY OTHER VIEW HAS. The HTTP adapter in
map_server fetches rows and does nothing else. Which rows are the backpack,
which are the bank, how big a bag with an unknown template is, what a
guild bank tab looks like with nothing in it and who counts as a friend are
all decisions, so they live here where the stdlib suite reaches them
without a database.

READ ONLY. Nothing here, and nothing in the endpoints that call it, writes a
row or commands a character. The overlay is a window onto saved state.

Slot ranges, from the core's Player.h and panel.py's carried ranges:

  bag = 0, slot 19..22   the four carried bag slots
  bag = 0, slot 23..38   the sixteen-slot backpack
  bag = 0, slot 39..66   the twenty-eight personal bank slots
  bag = 0, slot 67..73   the seven bank bag slots
  bag != 0               inside the container whose item guid that is
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
from collections import OrderedDict

from armory import template_tooltip
from panel import (
    _BACKPACK_SLOTS,
    _BAG_SLOTS,
    _BANK_BAG_SLOTS,
    _CLASS_NAMES,
    _RACE_NAMES,
    CLASS_COLOURS,
)

# The bank's own twenty-eight slots. panel.py names the carried ranges and the
# bank bag range; this one only matters to a view that draws the bank.
BANK_SLOTS = range(39, 67)

# A guild bank tab is fourteen columns by seven rows in the 3.3.5a client.
GUILD_BANK_TAB_SLOTS = 98
GUILD_BANK_COLUMNS = 14

# character_social.flags, from the core's SocialMgr.h.
SOCIAL_FRIEND = 0x01
SOCIAL_IGNORED = 0x02

BAGS, BANK = "bags", "bank"

# The two built-in containers, and where each one's slots start.
_BUILT_IN = {
    BAGS: ("backpack", "Backpack", _BACKPACK_SLOTS),
    BANK: ("bank", "Bank", BANK_SLOTS),
}
# The equipped bag slots each view hangs its extra containers off.
_BAG_HOLDERS = {BAGS: _BAG_SLOTS, BANK: _BANK_BAG_SLOTS}

FRAME_TITLES = {BAGS: "Bags", BANK: "Bank"}

# Sent with an empty frame so the page never composes a sentence of its own.
NO_GUILD_NOTE = "not in a guild, so there is no guild bank to open."
NO_TABS_NOTE = "the guild has not bought a bank tab yet."
NO_FRIENDS_NOTE = "no friends on the list."
EMPTY_BANK_NOTE = "nothing in the bank. The bank is only saved once visited."

# Where the item art comes from, said once so the page can print it.
ICON_NOTE = (
    "Icons are the game's own art, fetched by name from the public icon host "
    "the Armory already uses: the server holds the icon names (frozen from "
    "the client's tables) but not the pictures. An icon the host cannot serve "
    "is drawn as the item's initials in its quality colour."
)


def load_book(static_dir: str, items):
    """The Armory's ItemBook, widened to everything a bag can hold.

    icons.json and spells.json (gen_items.py) cover only what can be worn,
    because the paper doll was their only reader. bagicons.json and
    bagspells.json (tools/gen_bag_book.py) are the complement: the cloth,
    food, reagents and quest items a bag is mostly full of, and the text of
    their "Use:" lines. Where both books name something, the Armory's wins.
    """
    with open(os.path.join(static_dir, "bagicons.json")) as f:
        book = json.load(f)
    with open(os.path.join(static_dir, "bagspells.json")) as f:
        spells = {int(k): v for k, v in json.load(f).items()}
    names = book["names"]
    icons = {int(d): names[i] for d, i in book["display"].items()}
    return dataclasses.replace(
        items, icons={**icons, **items.icons}, spells={**spells, **items.spells}
    )


def letters(name: str | None) -> str:
    """The two letters a slot shows when there is no icon.

    The initials of the first two words ("Linen Cloth" is "LC"), or the first
    two letters of a one-word name ("Hearthstone" is "He"). Words that open
    with a non-letter ("+5", "(Unused)") are skipped.
    """
    words = [w for w in (name or "").split() if w[:1].isalpha()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].capitalize()
    return (words[0][0] + words[1][0]).upper()


def item_cell(row: dict, icons: dict[int, str]) -> dict:
    """One occupied slot: what the grid draws before anybody hovers it."""
    name = row.get("item_name")
    if name is None:
        name = "Item #%d" % row["entry"]
    quality = row.get("quality")
    return {
        "entry": row["entry"],
        "name": name,
        "quality": quality,
        "icon": icons.get(row.get("displayid") or 0),
        "letters": letters(name),
        "count": int(row.get("count") or 1),
    }


def _container(key: str, name: str, size: int, row: dict | None, icons) -> dict:
    return {
        "key": key,
        "name": name,
        "size": size,
        # The bag itself, for the bag bar along the top of the frame. The
        # built-in backpack and bank are not items and carry none of this.
        "bag": item_cell(row, icons) if row else None,
        "cells": [None] * size,
    }


def _place(container: dict, position: int, cell: dict) -> None:
    """Put an item in a slot, growing a container whose size is unknown.

    A bag whose template the world database no longer has arrives with a size
    of 0; its items are still real and still drawn, so the grid grows to hold
    them rather than dropping them.
    """
    cells = container["cells"]
    if position >= len(cells):
        cells.extend([None] * (position + 1 - len(cells)))
    cells[position] = cell


def _hang_bags(
    held: dict[int, dict], holders: range, key: str, icons: dict[int, str]
) -> tuple[list[dict], list[dict]]:
    """The bag slots -> (the bag bar, the containers hung off them).

    The bar has every slot, filled or not; a container exists only for a
    slot with a bag in it.
    """
    bar: list[dict] = []
    bags: list[dict] = []
    for number, slot in enumerate(holders, start=1):
        row = held.get(slot)
        bar.append({"position": number, "bag": item_cell(row, icons) if row else None})
        if row is not None:
            bags.append(
                _container(
                    "%s%d" % (key, number),
                    row.get("item_name") or "Bag #%d" % number,
                    int(row.get("container_slots") or 0),
                    row,
                    icons,
                )
            )
    return bar, bags


def build_inventory(
    rows: list[dict], icons: dict[int, str], where: str, money: int | None = None
) -> dict:
    """One character's character_inventory rows -> the Bags or Bank frame.

    Every container in the order the game hangs them (the built-in one first,
    then each bag slot), each as its full run of cells with the empty ones
    left as None, so the page can draw them as one Bagnon grid. The counts
    are over every slot, full or not.
    """
    key, name, built_in = _BUILT_IN[where]
    holders = _BAG_HOLDERS[where]
    base = _container(key, name, len(built_in), None, icons)
    top = [r for r in rows if r["bag"] == 0]
    held = {r["slot"]: r for r in top if r["slot"] in holders}
    for row in top:
        if row["slot"] in built_in:
            _place(base, row["slot"] - built_in.start, item_cell(row, icons))
    bar, bags = _hang_bags(held, holders, key, icons)
    by_guid = {
        held[slot]["item_guid"]: bag
        for slot, bag in zip(sorted(held), bags, strict=True)
    }
    for row in rows:
        bag = by_guid.get(row["bag"]) if row["bag"] != 0 else None
        # Inside a container this frame does not draw (a bank bag seen from
        # the Bags frame, or the other way round) is skipped.
        if bag is not None:
            _place(bag, row["slot"], item_cell(row, icons))
    containers = [base, *bags]
    total = sum(len(c["cells"]) for c in containers)
    used = sum(1 for c in containers for cell in c["cells"] if cell is not None)
    return {
        "where": where,
        "title": FRAME_TITLES[where],
        "containers": containers,
        "bag_slots": bar,
        "total": total,
        "used": used,
        "free": total - used,
        "money": coins(money),
        "note": EMPTY_BANK_NOTE if where == BANK and used == 0 else None,
    }


def coins(copper: int | None) -> dict | None:
    """Copper -> gold, silver and copper, or None when there is no purse."""
    if copper is None:
        return None
    copper = int(copper)
    return {
        "gold": copper // 10000,
        "silver": copper // 100 % 100,
        "copper": copper % 100,
    }


def build_guild_bank(
    guild: dict | None,
    tab_rows: list[dict],
    item_rows: list[dict],
    icons: dict[int, str],
) -> dict:
    """The guild bank frame: one grid of ninety-eight slots per bought tab.

    `guild` is the character's guild row (guild_id, guild_name, bank_money)
    or None. A guild with no tab bought, and a character with no guild, each
    arrive with the sentence that says so rather than an empty frame.
    """
    if guild is None:
        return {"guild": None, "tabs": [], "money": None, "note": NO_GUILD_NOTE}
    tabs = []
    by_id = {}
    for row in sorted(tab_rows, key=lambda r: r["tab_id"]):
        tab = {
            "tab": int(row["tab_id"]),
            "name": row.get("tab_name") or "Tab %d" % (int(row["tab_id"]) + 1),
            "icon": row.get("tab_icon") or None,
            "cells": [None] * GUILD_BANK_TAB_SLOTS,
        }
        tabs.append(tab)
        by_id[tab["tab"]] = tab
    for row in item_rows:
        tab = by_id.get(int(row["tab_id"]))
        slot = int(row["slot_id"])
        if tab is not None and 0 <= slot < GUILD_BANK_TAB_SLOTS:
            tab["cells"][slot] = item_cell(row, icons)
    for tab in tabs:
        tab["used"] = sum(1 for c in tab["cells"] if c is not None)
        tab["total"] = GUILD_BANK_TAB_SLOTS
    return {
        "guild": guild["guild_name"],
        "tabs": tabs,
        "columns": GUILD_BANK_COLUMNS,
        "money": coins(guild.get("bank_money")),
        "note": None if tabs else NO_TABS_NOTE,
    }


def person(row: dict) -> dict:
    """One name in the social frame: who, what, and whether they are on."""
    class_id = row.get("class")
    words = [
        "Level %s" % row.get("level"),
        _RACE_NAMES.get(row.get("race")),
        _CLASS_NAMES.get(class_id),
    ]
    out = {
        "name": row["name"],
        "level": row.get("level"),
        "line": " ".join(w for w in words if w),
        "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
        "online": bool(row.get("online")),
    }
    if "rank_name" in row:
        out["rank"] = row.get("rank_name") or "Rank %s" % row.get("rank")
    if row.get("note"):
        out["note"] = row["note"]
    return out


def _online_first(people: list[dict]) -> list[dict]:
    return sorted(
        people, key=lambda p: (not p["online"], -(p["level"] or 0), p["name"])
    )


def build_social(
    name: str,
    family_key: str,
    family_names: list[str],
    family_rows: list[dict],
    guild: dict | None,
    guild_rows: list[dict],
    social_rows: list[dict],
) -> dict:
    """The social frame: the family, the guild roster and the friends list.

    The family is in roster order, lead first, because that is the order every
    other view draws it in. The guild and the friends are online first, then
    highest level, the way the game's own lists read.
    """
    rows = {r["name"]: r for r in family_rows}
    fam = []
    for member in family_names:
        row = rows.get(member)
        if row is None:
            fam.append(
                {
                    "name": member,
                    "level": None,
                    "line": "not on this realm",
                    "class_colour": "#ffffff",
                    "online": False,
                }
            )
        else:
            fam.append(person(row))
    roster = _online_first([person(r) for r in guild_rows])
    friends = _online_first(
        [person(r) for r in social_rows if int(r.get("flags") or 0) & SOCIAL_FRIEND]
    )
    ignored = sorted(
        r["name"] for r in social_rows if int(r.get("flags") or 0) & SOCIAL_IGNORED
    )
    return {
        "name": name,
        "family": {"key": family_key, "members": fam},
        "guild": {
            "name": guild["guild_name"] if guild else None,
            "members": roster,
            "online": sum(1 for p in roster if p["online"]),
            "total": len(roster),
            "note": None if guild else NO_GUILD_NOTE,
        },
        "friends": friends,
        "friends_note": None if friends else NO_FRIENDS_NOTE,
        "ignored": ignored,
    }


class TooltipCache:
    """Tooltips by item entry, kept for the life of the process.

    An item template does not change while the world is up, so a tooltip is
    built once per entry and never again. Bounded, oldest first out, so a
    crawl through every entry cannot grow it without limit.
    """

    def __init__(self, limit: int = 4096):
        self.limit = limit
        self._items: OrderedDict[int, dict] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, entry: int, build):
        """The cached tooltip for `entry`, or `build(entry)` stored. None is not kept."""
        with self._lock:
            hit = self._items.get(entry)
            if hit is not None:
                self._items.move_to_end(entry)
                return hit
        made = build(entry)
        if made is None:
            return None
        with self._lock:
            self._items[entry] = made
            while len(self._items) > self.limit:
                self._items.popitem(last=False)
        return made

    def __len__(self) -> int:
        return len(self._items)


def item_tooltip(row: dict | None, book) -> dict | None:
    """An item_template row -> the hover payload: the cell plus the tooltip."""
    if not row:
        return None
    tooltip = template_tooltip(row, book)
    if tooltip is None:
        return None
    cell = item_cell(dict(row, count=1), book.icons)
    cell["tooltip"] = tooltip
    return cell
