"""Where an item comes from, shaped for the site's universal gear tooltip.

GET /api/item?entry=N answers one question: what is this item, and how does a
character get it. The adapter in map_server reads rows out of the world
database and does nothing else; every decision is made here, so the suite can
reach it with fake rows and no database.

THE CONTRACT (other pages are built against it, so it is fixed):

  {"entry", "name", "quality", "tooltip", "wowhead", "sources": [...]}

  {"kind": "drop", "boss", "where", "map", "chance"}   chance is a percent
  {"kind": "quest", "quest", "giver", "zone"}
  {"kind": "vendor", "npc", "zone", "copper"?, "honor"?, "items"?}
  {"kind": "craft", "profession", "skill", "recipe"}
  {"kind": "object", "object", "where"}
  {"kind": "world", "chance_max"}                      every sub-1% drop, folded

ORDER IS USEFULNESS. A dungeon or raid boss first (best chance first), then a
named creature outside an instance, a chest, a quest, a vendor, a craft, and
last the one world-drop line. Each kind is capped so a very common item cannot
crowd the others out, and the whole list is capped at MAX_SOURCES.

WHAT IS NOT DECODED. `itemextendedcost_dbc` is empty on this realm, so a
vendor that sells for honor, arena points or tokens has no readable price: it
is listed with no `copper`, `honor` or `items` rather than with a guessed one.

LOOT CHANCE FOLLOWS THE CORE. A row with a chance is that chance. A row with
chance 0 inside a group (GroupId > 0) shares whatever the group's explicit
chances leave, equally. A row that is a reference rolls the referenced table,
so its chance is the reference's chance times the item's chance inside it. A
reference row with chance 0 (or none) rolls for certain, as 100: the world's
reference rows state 100 outright and 0 would make the whole table unreachable.
"""

from __future__ import annotations

import tradespec

MAX_SOURCES = 8
# Per kind, before the overall cap. Four of anything is already a list.
PER_KIND_CAP = 4
# A drop below this percent is not a place to go, it is background noise.
WORLD_FLOOR = 1.0

# The dungeon table the site already uses (achievements.MAP_NAMES) stops at
# the level 60 five-mans. Raids and the outland and northrend instances are
# named here so a boss in one of them reads as an instance and not as "World".
EXTRA_INSTANCES = {
    249: "Onyxia's Lair",
    309: "Zul'Gurub",
    409: "Molten Core",
    469: "Blackwing Lair",
    509: "Ruins of Ahn'Qiraj",
    531: "Temple of Ahn'Qiraj",
    532: "Karazhan",
    533: "Naxxramas",
    534: "Hyjal Summit",
    540: "The Shattered Halls",
    542: "The Blood Furnace",
    543: "Hellfire Ramparts",
    544: "Magtheridon's Lair",
    545: "The Steamvault",
    546: "The Underbog",
    547: "The Slave Pens",
    548: "Serpentshrine Cavern",
    550: "The Eye",
    552: "The Arcatraz",
    553: "The Botanica",
    554: "The Mechanar",
    555: "Shadow Labyrinth",
    556: "Sethekk Halls",
    557: "Mana-Tombs",
    558: "Auchenai Crypts",
    560: "Old Hillsbrad Foothills",
    564: "Black Temple",
    565: "Gruul's Lair",
    568: "Zul'Aman",
    580: "Sunwell Plateau",
    585: "Magisters' Terrace",
    603: "Ulduar",
    615: "The Obsidian Sanctum",
    616: "The Eye of Eternity",
    624: "Vault of Archavon",
    631: "Icecrown Citadel",
    649: "Trial of the Crusader",
    724: "The Ruby Sanctum",
}


# creature.zoneId is 0 for most spawns on this realm, so an outdoor creature
# with no zone is named by its continent rather than by nothing.
CONTINENTS = {0: "Eastern Kingdoms", 1: "Kalimdor", 530: "Outland", 571: "Northrend"}


def _num(value, default=0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def row_chance(row: dict) -> float:
    """The percent one loot row gives its item, by the core's own rule.

    Needs `chance`, `group_id`, and for a group row `zeros` (rows in the same
    group with chance 0) and `explicit` (sum of the group's stated chances).
    """
    chance = _num(row.get("chance"))
    if chance > 0:
        return min(chance, 100.0)
    zeros = _int(row.get("zeros"))
    if _int(row.get("group_id")) > 0 and zeros > 0:
        return max(0.0, 100.0 - _num(row.get("explicit"))) / zeros
    return 0.0


def _either(a: float, b: float) -> float:
    """Two independent chances at the same item, as one percent."""
    return 100.0 * (1.0 - (1.0 - a / 100.0) * (1.0 - b / 100.0))


def loot_chances(
    direct: list[dict], via_ref: list[dict], ref_users: list[dict]
) -> dict[int, float]:
    """loot table entry -> percent, merging direct rows and references.

    `direct` are rows of the loot table naming the item; `via_ref` are rows of
    the reference table naming it (entry = the reference); `ref_users` are
    loot rows pointing at a reference (entry, reference, chance).
    """
    inside = {int(r["entry"]): row_chance(r) for r in via_ref}
    out: dict[int, float] = {}
    for row in direct:
        key = int(row["entry"])
        out[key] = _either(out.get(key, 0.0), row_chance(row))
    for user in ref_users:
        inner = inside.get(int(user["reference"]))
        if not inner:
            continue
        rolled = _num(user.get("chance"), 100.0)
        rolled = 100.0 if rolled <= 0 else min(rolled, 100.0)
        key = int(user["entry"])
        out[key] = _either(out.get(key, 0.0), rolled * inner / 100.0)
    return {k: v for k, v in out.items() if v > 0}


def place(map_id: int, zone_id: int, dungeons: dict, zones: dict) -> str:
    """An instance name for an instance map, else the zone, else the continent,
    else "World"."""
    name = dungeons.get(map_id) or EXTRA_INSTANCES.get(map_id)
    return name or zones.get(zone_id) or CONTINENTS.get(map_id) or "World"


def _is_instance(map_id: int, dungeons: dict) -> bool:
    return map_id in dungeons or map_id in EXTRA_INSTANCES


def drop_sources(
    chances: dict[int, float], creatures: list[dict], dungeons: dict, zones: dict
) -> tuple[list[dict], list[dict], float]:
    """(instance drops, outdoor drops >= 1%, highest sub-1% chance).

    `creatures` carry lootid, name, map and zone. Many creatures share a name
    (every wolf in a zone), so one line per (name, map) at the best chance.
    """
    best: dict[tuple[str, int], dict] = {}
    world_max = 0.0
    for c in creatures:
        chance = chances.get(_int(c.get("lootid")))
        name = c.get("name") or ""
        if not chance or not name:
            continue
        map_id = _int(c.get("map"))
        instance = _is_instance(map_id, dungeons)
        if not instance and chance < WORLD_FLOOR:
            world_max = max(world_max, chance)
            continue
        key = (name, map_id)
        if key in best and best[key]["chance"] >= chance:
            continue
        best[key] = {
            "kind": "drop",
            "boss": name,
            "where": place(map_id, _int(c.get("zone")), dungeons, zones),
            "map": map_id,
            "chance": round(chance, 2),
            "_instance": instance,
        }
    inst = [d for d in best.values() if d["_instance"]]
    outdoor = [d for d in best.values() if not d["_instance"]]
    order = lambda d: (-d["chance"], d["boss"])  # noqa: E731
    return sorted(inst, key=order), sorted(outdoor, key=order), world_max


def _clean(source: dict) -> dict:
    return {k: v for k, v in source.items() if not k.startswith("_")}


def object_sources(rows: list[dict], dungeons: dict, zones: dict) -> list[dict]:
    """Chests: rows of object name, chance fields, map and zone."""
    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        chance = row_chance(r)
        name = r.get("name") or ""
        if not name or chance <= 0:
            continue
        where = place(_int(r.get("map")), _int(r.get("zone")), dungeons, zones)
        key = (name, where)
        if key not in best or best[key]["_chance"] < chance:
            best[key] = {
                "kind": "object",
                "object": name,
                "where": where,
                "_chance": chance,
            }
    return sorted(best.values(), key=lambda s: (-s["_chance"], s["object"]))


def quest_sources(rows: list[dict], zones: dict) -> list[dict]:
    """Quests rewarding the item: title, starter name and zone id."""
    seen: dict[tuple[str, str, str], dict] = {}
    for r in rows:
        title = r.get("title") or ""
        if not title:
            continue
        zone = zones.get(_int(r.get("zone_id")), "")
        key = (title, r.get("giver") or "", zone)
        seen.setdefault(
            key,
            {
                "kind": "quest",
                "quest": title,
                "giver": key[1],
                "zone": key[2],
                "_level": _int(r.get("level")),
            },
        )
    return sorted(seen.values(), key=lambda s: (s["_level"], s["quest"]))


def vendor_sources(
    rows: list[dict], buy_price: int, dungeons: dict, zones: dict
) -> list[dict]:
    """Vendors: npc name, map, zone, ExtendedCost. Copper only when plain gold."""
    seen: dict[tuple[str, str], dict] = {}
    for r in rows:
        npc = r.get("npc") or ""
        if not npc:
            continue
        zone = place(_int(r.get("map")), _int(r.get("zone")), dungeons, zones)
        source = {"kind": "vendor", "npc": npc, "zone": zone}
        plain = not _int(r.get("extended_cost"))
        if plain and buy_price > 0:
            source["copper"] = int(buy_price)
        key = (npc, zone)
        if key not in seen or ("copper" in source and "copper" not in seen[key]):
            seen[key] = source
    # Cheapest plain-gold vendors first; unreadable prices last.
    return sorted(
        seen.values(), key=lambda s: ("copper" not in s, s.get("copper", 0), s["npc"])
    )


def craft_sources(entry: int, craftbook: dict, skill_names: dict) -> list[dict]:
    """Trade skill spells whose created item is this one, from craftbook.json."""
    out = []
    for skill, crafts in (craftbook or {}).items():
        try:
            skill_id = int(skill)
        except (TypeError, ValueError):
            continue
        profession = skill_names.get(skill_id)
        if not profession:
            continue
        for spell in crafts.values():
            if len(spell) >= 5 and _int(spell[4]) == entry:
                out.append(
                    {
                        "kind": "craft",
                        "profession": profession,
                        "skill": tradespec.effective_rank(spell, None),
                        "recipe": spell[0],
                        "_id": skill_id,
                    }
                )
    return sorted(out, key=lambda s: (s["skill"], s["profession"], s["recipe"]))


def order_sources(
    instance_drops: list[dict],
    outdoor_drops: list[dict],
    objects: list[dict],
    quests: list[dict],
    vendors: list[dict],
    crafts: list[dict],
    world_max: float,
) -> list[dict]:
    """The final list: usefulness order, per-kind cap, overall cap."""
    groups = [instance_drops, outdoor_drops, objects, quests, vendors, crafts]
    counts: dict[str, int] = {}
    out: list[dict] = []
    for group in groups:
        for source in group:
            kind = source["kind"]
            if counts.get(kind, 0) >= PER_KIND_CAP:
                continue
            counts[kind] = counts.get(kind, 0) + 1
            out.append(_clean(source))
    tail = (
        [{"kind": "world", "chance_max": round(world_max, 2)}] if world_max > 0 else []
    )
    return out[: MAX_SOURCES - len(tail)] + tail


def build_item(
    entry: int,
    shaped: dict,
    rows: dict,
    *,
    craftbook: dict,
    skill_names: dict,
    dungeons: dict,
    zones: dict,
) -> dict:
    """The /api/item payload. `shaped` is recap.item_payload's output (name,
    quality, tooltip, wowhead); `rows` are the world rows the adapter read.
    """
    chances = loot_chances(
        rows.get("loot_direct", []),
        rows.get("loot_via_ref", []),
        rows.get("ref_users", []),
    )
    inst, outdoor, world_max = drop_sources(
        chances, rows.get("creatures", []), dungeons, zones
    )
    sources = order_sources(
        inst,
        outdoor,
        object_sources(rows.get("objects", []), dungeons, zones),
        quest_sources(rows.get("quests", []), zones),
        vendor_sources(
            rows.get("vendors", []), _int(rows.get("buy_price")), dungeons, zones
        ),
        craft_sources(entry, craftbook, skill_names),
        world_max,
    )
    return {
        "entry": entry,
        "name": shaped["name"],
        "quality": shaped["quality"],
        "tooltip": shaped["tooltip"],
        "wowhead": shaped["wowhead"],
        "sources": sources,
    }


class BoundedCache:
    """A small insertion-ordered cache. Item data is static, so there is no
    expiry, only a ceiling on how many items it will hold."""

    def __init__(self, limit: int = 2048):
        self.limit = limit
        self._data: dict = {}

    def get(self, key):
        if key in self._data:
            value = self._data.pop(key)
            self._data[key] = value
            return value
        return None

    def put(self, key, value) -> None:
        self._data.pop(key, None)
        self._data[key] = value
        while len(self._data) > self.limit:
            self._data.pop(next(iter(self._data)))

    def __len__(self) -> int:
        return len(self._data)
