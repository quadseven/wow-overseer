"""Class reagents a guild member buys with its own gold (#2622).

Reagents come at run time from the realm's Spell.dbc and acore_world.spell_dbc
(never a reagent table written in code), minus profession recipes owned by the
trade tickets (craftbook.json). When a member knows a class spell whose reagent
stack is low and no vendor sells it on the realm (such as a Soul Shard), the
item is skipped with a reason; vendored reagents are bought at a nearby
friendly vendor up to TARGET_STOCK units per entry, spending only above the
class spell, riding and food reserves in purse.ORDER.

PURE MODULE: facts and DBC bytes in, buys out. No MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct

import situation
import world_data

ACTION = "classreagents"
COOLDOWN_MINUTES = 60
STEPS_PER_GUILD = 6
TARGET_STOCK = 5

# 3.3.5a Spell.dbc field indices (tools/craftbook_from_dbc.py).
F_ID = 0
F_REAGENT = 52
F_REAGENT_COUNT = 60
REAGENT_SLOTS = 8
SPELL_DBC_ENV = "SPELL_DBC_PATH"
_DEFAULT_DBC_PATHS = (Path("/azerothcore/env/dist/data/dbc/Spell.dbc"),)

_CRAFT_SPELLS_CACHE: frozenset[int] | None = None
_DBC_CACHE: dict[tuple[str, int, int], dict[int, tuple[tuple[int, int], ...]]] = {}


@dataclass(frozen=True)
class Offer:
    """What the bridge read for one member: reachable vendor stock and which
    wanted entries are sold anywhere on the realm."""

    rows: tuple = ()
    sold: frozenset | None = None


@dataclass(frozen=True)
class Buy:
    """One reagent purchase at a vendor."""

    vendor: int
    vendor_name: str
    entry: int
    name: str
    count: int
    units: int
    ceiling: int

    @property
    def command(self) -> str:
        """The kind='buy' row the module's DoBuy reads."""
        return "entry:%d count:%d max:%d" % (self.entry, self.count, self.ceiling)


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _join_reasons(*parts: str) -> str:
    return "; ".join(p for p in parts if p)


def craft_spells() -> frozenset[int]:
    """Every profession spell id in craftbook.json: out of scope for class
    reagents."""
    global _CRAFT_SPELLS_CACHE
    if _CRAFT_SPELLS_CACHE is not None:
        return _CRAFT_SPELLS_CACHE
    path = world_data.DATA_ROOT / "craftbook.json"
    if not path.is_file():
        _CRAFT_SPELLS_CACHE = frozenset()
        return _CRAFT_SPELLS_CACHE
    raw = json.loads(path.read_text(encoding="utf-8"))
    ids = set()
    for skill_recipes in raw.values():
        if isinstance(skill_recipes, dict):
            for sid in skill_recipes:
                val = _int(sid, 0)
                if val > 0:
                    ids.add(val)
    _CRAFT_SPELLS_CACHE = frozenset(ids)
    return _CRAFT_SPELLS_CACHE


def parse_spell_dbc(blob: bytes) -> dict[int, tuple[tuple[int, int], ...]]:
    """Parse Spell.dbc binary bytes into ``spell_id -> ((entry, per_cast), ...)``."""
    if len(blob) < 20 or blob[:4] != b"WDBC":
        return {}
    records, _fields, record_size, _string_size = struct.unpack_from("<4I", blob, 4)
    min_size = (F_REAGENT_COUNT + REAGENT_SLOTS) * 4
    if record_size < min_size:
        return {}
    end_of_records = 20 + records * record_size
    if len(blob) < end_of_records:
        return {}
    out: dict[int, tuple[tuple[int, int], ...]] = {}
    for idx in range(records):
        offset = 20 + idx * record_size
        spell_id = struct.unpack_from("<i", blob, offset + F_ID * 4)[0]
        if spell_id <= 0:
            continue
        reagents = struct.unpack_from("<8i", blob, offset + F_REAGENT * 4)
        counts = struct.unpack_from("<8i", blob, offset + F_REAGENT_COUNT * 4)
        pairs = tuple(
            (int(entry), max(1, int(count)))
            for entry, count in zip(reagents, counts, strict=True)
            if entry > 0
        )
        if pairs:
            out[int(spell_id)] = pairs
    return out


def spell_reagents_from_rows(rows) -> dict[int, tuple[tuple[int, int], ...]]:
    """Parse acore_world.spell_dbc rows into ``spell_id -> ((entry, per_cast), ...)``.

    An explicit SQL row with all Reagent_1..8 <= 0 keeps an empty tuple so
    `merge_spell_reagents` lets it clear a base Spell.dbc entry.
    """
    out: dict[int, tuple[tuple[int, int], ...]] = {}
    for row in rows or ():
        spell_id = _int(
            row.get("spell_id") if row.get("spell_id") is not None else row.get("ID")
        )
        if spell_id <= 0:
            continue
        pairs = []
        for slot in range(1, REAGENT_SLOTS + 1):
            entry = _int(row.get("Reagent_%d" % slot))
            count = _int(row.get("ReagentCount_%d" % slot), 1)
            if entry > 0:
                pairs.append((entry, max(1, count)))
        out[spell_id] = tuple(pairs)
    return out


def merge_spell_reagents(
    dbc_map: dict | None,
    sql_map: dict | None = None,
    excluded: frozenset | set | None = None,
) -> dict[int, tuple[tuple[int, int], ...]]:
    """Merge runtime DBC and SQL spell reagent maps, dropping profession recipes
    and empty reagent lists."""
    merged = dict(dbc_map or {})
    if sql_map:
        merged.update(sql_map)
    skip = set(excluded or ())
    return {
        int(sid): pairs
        for sid, pairs in merged.items()
        if int(sid) not in skip and pairs
    }


def default_spell_dbc_path() -> Path | None:
    """First readable Spell.dbc path from env, server dist, or data root."""
    candidates = []
    env_path = os.environ.get(SPELL_DBC_ENV, "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(_DEFAULT_DBC_PATHS)
    candidates.append(world_data.DATA_ROOT / "Spell.dbc")
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_spell_reagents(
    dbc_path: Path | None = None,
    sql_rows=None,
    excluded: frozenset | set | None = None,
) -> dict[int, tuple[tuple[int, int], ...]]:
    """Load runtime spell reagent requirements from Spell.dbc + spell_dbc SQL."""
    path = dbc_path if dbc_path is not None else default_spell_dbc_path()
    dbc_map: dict[int, tuple[tuple[int, int], ...]] = {}
    if path is not None and path.is_file():
        stat = path.stat()
        key = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
        if key not in _DBC_CACHE:
            _DBC_CACHE[key] = parse_spell_dbc(path.read_bytes())
        dbc_map = _DBC_CACHE[key]
    sql_map = spell_reagents_from_rows(sql_rows) if sql_rows else None
    skip = frozenset(excluded or ()) | craft_spells()
    return merge_spell_reagents(dbc_map, sql_map, excluded=skip)


def entries_for_known(
    known, spell_reagents: dict | None, craft: frozenset | set | None = None
) -> frozenset[int]:
    """Every reagent item entry required by spells in `known`."""
    if not known or not spell_reagents:
        return frozenset()
    skip = set(craft or ()) | set(craft_spells())
    out = set()
    for spell_id in known:
        sid = _int(spell_id)
        if sid in skip:
            continue
        for entry, _count in spell_reagents.get(sid, ()):
            if entry > 0:
                out.add(int(entry))
    return frozenset(out)


def relevant_spells(
    spell_reagents: dict | None, craft: frozenset | set | None = None
) -> frozenset[int]:
    """Every non-trade spell id that consumes at least one reagent."""
    if not spell_reagents:
        return frozenset()
    skip = set(craft or ()) | set(craft_spells())
    return frozenset(
        int(sid)
        for sid, pairs in spell_reagents.items()
        if pairs and int(sid) not in skip
    )


def all_reagent_entries(
    spell_reagents: dict | None, craft: frozenset | set | None = None
) -> frozenset[int]:
    """Every item entry listed as a reagent on any non-trade spell."""
    if not spell_reagents:
        return frozenset()
    skip = set(craft or ()) | set(craft_spells())
    out = set()
    for sid, pairs in spell_reagents.items():
        if int(sid) in skip:
            continue
        for entry, _count in pairs:
            if entry > 0:
                out.add(int(entry))
    return frozenset(out)


def wanted(
    member, spell_reagents: dict | None, craft: frozenset | set | None = None
) -> dict[int, int]:
    """``entry -> additional units wanted`` for known class spells short of
    TARGET_STOCK."""
    if not spell_reagents or not member.known:
        return {}
    skip = set(craft or ()) | set(craft_spells())
    targets: dict[int, int] = {}
    for spell_id in member.known:
        sid = _int(spell_id)
        if sid in skip:
            continue
        for entry, per_cast in spell_reagents.get(sid, ()):
            target = max(TARGET_STOCK, _int(per_cast, 1) * 2)
            if target > targets.get(int(entry), 0):
                targets[int(entry)] = target
    short: dict[int, int] = {}
    for entry in sorted(targets):
        have = member.count(entry)
        gap = targets[entry] - have
        if gap > 0:
            short[entry] = gap
    return short


def _friendly_rows(member, rows, wanted_entries):
    side = situation.side_mask([member.race])
    return [
        r
        for r in rows or ()
        if _int(r.get("entry")) in wanted_entries
        and _int(r.get("price")) > 0
        and situation.hostile(r.get("enemy_group"), side) is not True
    ]


def _pick_at_vendor(member, stock_rows, vendored, room):
    by_entry = {}
    for row in stock_rows:
        entry = _int(row.get("entry"))
        price = _int(row.get("price"))
        prev = by_entry.get(entry)
        if prev is None or price < _int(prev.get("price")):
            by_entry[entry] = row
    copper = max(0, _int(member.money))
    slots_left = None if room is None else max(0, _int(room))
    buys = []
    for entry in sorted(by_entry):
        needs_new_slot = member.count(entry) == 0
        if slots_left is not None and needs_new_slot and slots_left <= 0:
            continue
        row = by_entry[entry]
        price = _int(row.get("price"))
        buy_count = max(1, _int(row.get("buy_count"), 1))
        short_units = vendored[entry]
        needed_lots = max(1, (short_units + buy_count - 1) // buy_count)
        affordable_lots = copper // price
        lots = min(needed_lots, affordable_lots)
        if lots <= 0:
            continue
        cost = lots * price
        copper -= cost
        if slots_left is not None and needs_new_slot:
            slots_left -= 1
        buys.append(
            Buy(
                vendor=_int(row.get("vendor")),
                vendor_name=str(row.get("vendor_name") or ""),
                entry=entry,
                name=str(row.get("item_name") or ""),
                count=lots,
                units=lots * buy_count,
                ceiling=cost,
            )
        )
    return tuple(buys)


def _split_vendored(need: dict[int, int], sold_entries) -> tuple[dict[int, int], str]:
    """Split ``need`` into realm-vendored items and an unvendored skip note."""
    if sold_entries is None:
        return dict(need), ""
    sold_set = {int(e) for e in sold_entries}
    unvendored = [e for e in need if e not in sold_set]
    vendored = {e: gap for e, gap in need.items() if e in sold_set}
    note = (
        "item %s has no vendor on the realm (made or dropped, not bought)"
        % ", ".join(str(e) for e in unvendored)
        if unvendored
        else ""
    )
    return vendored, note


def _pick_best_vendor(member, friendly, vendored: dict[int, int], room):
    """Choose the nearest vendor offering the fullest affordable buy tuple."""
    vendors: dict[int, list] = {}
    for row in friendly:
        vendors.setdefault(_int(row.get("vendor")), []).append(row)
    best = None
    for vendor_id, stock in vendors.items():
        buys = _pick_at_vendor(member, stock, vendored, room)
        if not buys:
            continue
        yards = min(float(r.get("yards") or 0.0) for r in stock)
        key = (-len(buys), yards, vendor_id)
        if best is None or key < best[0]:
            best = (key, buys)
    return best[1] if best is not None else ()


def plan(
    member,
    spell_reagents,
    vendor_rows,
    *,
    sold_entries=None,
    room=None,
    craft=frozenset(),
) -> tuple[tuple[Buy, ...], str]:
    """``(buys, reason)`` for one member's missing class reagents."""
    need = wanted(member, spell_reagents, craft)
    if not need:
        return (), ""
    vendored, skip_reason = _split_vendored(need, sold_entries)
    if not vendored:
        return (), skip_reason
    friendly = _friendly_rows(member, vendor_rows, set(vendored))
    if not friendly:
        return (
            (),
            _join_reasons(
                skip_reason,
                "no vendor in reach sells class reagents for %s" % member.name,
            ),
        )
    if (
        room is not None
        and _int(room) <= 0
        and all(member.count(e) == 0 for e in vendored)
    ):
        return (
            (),
            _join_reasons(
                skip_reason,
                "%s has no bag room for class reagents" % member.name,
            ),
        )
    buys = _pick_best_vendor(member, friendly, vendored, room)
    if not buys:
        return (
            (),
            _join_reasons(
                skip_reason,
                "%s cannot afford class reagents (%d copper)"
                % (member.name, max(0, _int(member.money))),
            ),
        )
    return buys, skip_reason


def said(member, buys) -> str:
    """The sentence the pass logs for a class reagent walk."""
    items = ", ".join(
        "%d %s" % (b.units, b.name or ("item %d" % b.entry)) for b in buys
    )
    return "%s walks to %s to buy class reagents with its own gold: %s" % (
        member.name,
        buys[0].vendor_name or "a vendor",
        items,
    )
