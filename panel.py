"""Pure builder for the character side panel: DB rows -> panel JSON.

Same seam rule as map_core (infra#2597): the HTTP adapter fetches rows and
does nothing else; every rendering decision - which spec's hotbar, what a
bare action id is called, which inventory slot is "chest", who the target
counter really is - lives here where the stdlib suite can reach it.

Ticket: infra#2603.
"""

from __future__ import annotations

from core import _ALLIANCE_RACES, _HORDE_RACES

_RACE_NAMES = {
    1: "Human",
    2: "Orc",
    3: "Dwarf",
    4: "Night Elf",
    5: "Undead",
    6: "Tauren",
    7: "Gnome",
    8: "Troll",
    10: "Blood Elf",
    11: "Draenei",
}

_CLASS_NAMES = {
    1: "Warrior",
    2: "Paladin",
    3: "Hunter",
    4: "Rogue",
    5: "Priest",
    6: "Death Knight",
    7: "Shaman",
    8: "Mage",
    9: "Warlock",
    11: "Druid",
}

# The class's own colour, from the client's RAID_CLASS_COLORS table. Every
# name on every surface is drawn in it, the way every armory does - so it
# lives beside the names, and armory, family and the quest board all read
# this one table rather than each keeping a copy that could drift.
CLASS_COLOURS = {
    1: "#c79c6e",
    2: "#f58cba",
    3: "#abd473",
    4: "#fff569",
    5: "#ffffff",
    6: "#c41f3b",
    7: "#0070de",
    8: "#69ccf0",
    9: "#9482c9",
    11: "#ff7d0a",
}

# class id -> (power name, characters.power* column, stored x10). Rage and
# runic power are persisted x10 (350 = 35 rage); mana and energy are not.
_POWER_BY_CLASS = {
    1: ("Rage", "power2", True),
    4: ("Energy", "power4", False),
    6: ("Runic Power", "power7", True),
}
_DEFAULT_POWER = ("Mana", "power1", False)

# character_action.type (3.3.5 ActionButtonType). Spell names live in a
# client DBC, not the DB, so v1 shows the id; the type at least says what
# kind of thing the button does.
_ACTION_KINDS = {0: ("spell", "Spell"), 64: ("macro", "Macro"), 128: ("item", "Item")}

_BUTTONS_PER_BAR = 12

# Player inventory geography, 3.3.5 slot constants (bag = 0 rows).
_EQUIPMENT_SLOT_NAMES = [
    "head",
    "neck",
    "shoulders",
    "shirt",
    "chest",
    "waist",
    "legs",
    "feet",
    "wrists",
    "hands",
    "finger 1",
    "finger 2",
    "trinket 1",
    "trinket 2",
    "back",
    "main hand",
    "off hand",
    "ranged",
    "tabard",
]
_BAG_SLOTS = range(19, 23)  # the four carried bag slots
_BACKPACK_SLOTS = range(23, 39)  # the built-in 16-slot backpack
_BANK_SLOTS = range(39, 67)  # the bank's own 28 item slots (not carried)
_BANK_BAG_SLOTS = range(67, 74)  # bank bag containers (not carried)


def _item_name(row: dict) -> str:
    # LEFT JOIN miss on acore_world.item_template: custom or removed item.
    return row["name"] if row["name"] is not None else f"Item #{row['entry']}"


def _build_hotbar(action_rows: list[dict], active_spec: int) -> list[dict]:
    bars: dict[int, list[dict]] = {}
    for row in sorted(action_rows, key=lambda r: r["button"]):
        if row["spec"] != active_spec:
            continue
        kind, word = _ACTION_KINDS.get(row["type"], ("other", "Action"))
        bars.setdefault(row["button"] // _BUTTONS_PER_BAR, []).append(
            {
                "slot": row["button"] % _BUTTONS_PER_BAR,
                "label": f"{word} #{row['action']}",
                "kind": kind,
                "id": row["action"],
            }
        )
    # Bars are 1-based for humans, matching the in-game action bar numbers.
    return [{"bar": n + 1, "buttons": buttons} for n, buttons in sorted(bars.items())]


def _build_inventory(inventory_rows: list[dict]) -> dict:
    equipment, backpack, bag_rows = [], [], []
    carried: dict[int, dict] = {}  # container item guid -> bag payload
    bank_bag_guids: set[int] = set()
    elsewhere = 0
    for row in sorted(inventory_rows, key=lambda r: (r["bag"], r["slot"])):
        if row["bag"] != 0:
            bag_rows.append(row)
            continue
        slot = row["slot"]
        if slot < len(_EQUIPMENT_SLOT_NAMES):
            equipment.append(
                {"slot": _EQUIPMENT_SLOT_NAMES[slot], "name": _item_name(row)}
            )
        elif slot in _BAG_SLOTS:
            carried[row["item_guid"]] = {"name": _item_name(row), "items": []}
        elif slot in _BACKPACK_SLOTS:
            backpack.append({"name": _item_name(row), "count": row["count"]})
        elif slot in _BANK_BAG_SLOTS:
            # The bank bag itself is furniture, not cargo; only its
            # contents count toward the stored-elsewhere tally.
            bank_bag_guids.add(row["item_guid"])
        else:
            # Bank items, buyback, keyring, currency: real possessions the
            # panel does not draw. Counted so the panel never silently
            # understates what the character owns.
            elsewhere += 1
    for row in bag_rows:
        if row["bag"] in carried:
            carried[row["bag"]]["items"].append(
                {"name": _item_name(row), "count": row["count"]}
            )
        else:
            elsewhere += 1  # inside a bank bag
    return {
        "equipment": equipment,
        "bags": list(carried.values()),
        "backpack": backpack,
        "stored_elsewhere": elsewhere,
    }


def _build_target(
    target_guid: int, target_player: dict | None, target_creature_name: str | None
) -> dict | None:
    if not target_guid:
        return None
    # target_guid is a bare counter: player guids and creature spawn guids
    # overlap in the low range, so a live player match outranks a spawn row.
    if target_player is not None:
        return {
            "kind": "player",
            "name": target_player["name"],
            "level": target_player["level"],
        }
    if target_creature_name is not None:
        return {"kind": "creature", "name": target_creature_name}
    # Summoned/temporary units have no spawn row; admit it rather than
    # guessing.
    return {"kind": "unknown", "name": f"unit #{target_guid}"}


def _build_power(class_id: int, char_row: dict | None) -> dict | None:
    if char_row is None:
        # characters.* saves lag the live world; a missing row (brand-new
        # character mid-save) must degrade to "no power shown", not a 503.
        return None
    kind, column, scaled = _POWER_BY_CLASS.get(class_id, _DEFAULT_POWER)
    value = char_row[column]
    return {"kind": kind, "value": value // 10 if scaled else value}


def build_character_panel(
    name: str,
    snapshot_row: dict | None,
    char_row: dict | None,
    action_rows: list[dict],
    inventory_rows: list[dict],
    guild_name: str | None,
    group_rows: list[dict],
    target_player: dict | None,
    target_creature_name: str | None,
) -> dict:
    """One character's in-game reality as a JSON-shaped dict.

    snapshot_row None means the character is not in the fresh snapshot -
    logged out (the module sweeps their row) or never existed. Both get the
    same calm {"present": false} payload: the page says "left the world"
    instead of erroring, which is the logged-out-mid-view contract.
    """
    if snapshot_row is None:
        return {"present": False, "name": name}

    race, class_id = snapshot_row["race"], snapshot_row["class"]
    active_spec = char_row["activeTalentGroup"] if char_row is not None else 0

    group = None
    if snapshot_row["group_leader"]:
        leader = snapshot_row["group_leader"]
        members = [
            {
                "name": r["name"],
                "level": r["level"],
                "class": _CLASS_NAMES.get(r["class"], f"class {r['class']}"),
                "leader": r["guid"] == leader,
            }
            for r in group_rows
        ]
        members.sort(key=lambda m: (not m["leader"], m["name"]))
        group = {"members": members}

    panel = {
        "present": True,
        "name": snapshot_row["name"],
        "level": snapshot_row["level"],
        "race": _RACE_NAMES.get(race, f"race {race}"),
        "class": _CLASS_NAMES.get(class_id, f"class {class_id}"),
        "faction": "alliance"
        if race in _ALLIANCE_RACES
        else "horde"
        if race in _HORDE_RACES
        else "neutral",
        "bot": bool(snapshot_row["is_bot"]),
        "combat": bool(snapshot_row["in_combat"]),
        "vitals": {
            "health": snapshot_row["health"],
            "max_health": snapshot_row["max_health"],
            "power": _build_power(class_id, char_row),
        },
        "target": _build_target(
            snapshot_row["target_guid"], target_player, target_creature_name
        ),
        "guild": guild_name,
        "group": group,
        "hotbar": _build_hotbar(action_rows, active_spec),
        "age_seconds": snapshot_row["age_seconds"],
    }
    panel.update(_build_inventory(inventory_rows))
    return panel
