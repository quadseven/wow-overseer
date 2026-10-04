"""The gear upgrade tracker: one member's slots against their spec's lists (#541).

Decision #532 asks for a site view in the spirit of sixtyupgrades.com/forever:
per slot, what is worn, the pre-raid and raid best-in-slot targets with where
each comes from, the next upgrade, and how ready the member is for the raid.

EVERY SCORE IS gearscore's. This module picks the spec, lays the slots out,
reads where an item comes from (`data/bis/items.json`) and words the result;
it never weighs a stat itself. The lists are a shopping list, not the score
(see gearscore's docstring): targets are ranked by OUR stats.

THE SPEC. A member's tree is the one armory already reads from the talent
book (`spec.primary`). `choose_spec` maps class and tree to a data file in
`data/bis/`. A member with no tree (nothing spent, or a tie) gets the class's
first spec, and the payload says so in `spec.note`. A feral druid is scored as
damage, because the tree alone cannot tell the cat from the bear.

WHAT IS NOT SEEN. Scores come from item_template stats. Enchants, gems, random
suffixes ("of the Tiger") and equip-spell stats are not folded in, so a piece
that leans on them scores low. `scored_from` says so, and the page prints it.

PURE: dicts in, a dict out. The caller reads item_template.
"""

from __future__ import annotations

import functools
import json

import gearscore

# A slot is "near" pre-raid best in slot when it scores at least this share of
# the best pre-raid entry. Ninety percent is where a swap stops being worth a
# dungeon run; it is a reading aid, not a rule from the decision.
NEAR = 0.9
# At or above this share the slot counts as at best in slot.
AT_BEST = 0.99
TOP_TARGETS = 3

SCORED_FROM = (
    "Scores use item template stats only. Enchants, gems, random suffixes "
    "and equip effects are not counted."
)

# (class, tree) -> spec file. A class with one data file for every tree is
# keyed by its name alone.
_BY_TREE = {
    ("druid", "Balance"): "druid-balance",
    ("druid", "Feral Combat"): "druid-feral-dps",
    ("druid", "Restoration"): "druid-restoration",
    ("paladin", "Holy"): "paladin-holy",
    ("paladin", "Protection"): "paladin-protection",
    ("paladin", "Retribution"): "paladin-retribution",
    ("priest", "Discipline"): "priest-holy",
    ("priest", "Holy"): "priest-holy",
    ("priest", "Shadow"): "priest-shadow",
    ("shaman", "Elemental"): "shaman-elemental",
    ("shaman", "Enhancement"): "shaman-enhancement",
    ("shaman", "Restoration"): "shaman-restoration",
    ("warrior", "Arms"): "warrior-fury",
    ("warrior", "Fury"): "warrior-fury",
    ("warrior", "Protection"): "warrior-protection",
}
_ONE_SPEC = {
    "hunter": "hunter-dps",
    "mage": "mage-dps",
    "rogue": "rogue-dps",
    "warlock": "warlock-dps",
}

# Armory slot name -> (label, list key). The two rings and two trinkets read
# one list each. Shirt and tabard carry no stats and are not rows.
ROWS = (
    ("head", "Head", "head"),
    ("neck", "Neck", "neck"),
    ("shoulders", "Shoulders", "shoulders"),
    ("back", "Back", "back"),
    ("chest", "Chest", "chest"),
    ("wrists", "Wrists", "wrist"),
    ("hands", "Hands", "hands"),
    ("waist", "Waist", "waist"),
    ("legs", "Legs", "legs"),
    ("feet", "Feet", "feet"),
    ("finger 1", "Ring 1", "finger"),
    ("finger 2", "Ring 2", "finger"),
    ("trinket 1", "Trinket 1", "trinket"),
    ("trinket 2", "Trinket 2", "trinket"),
    ("main hand", "Main hand", "main_hand"),
    ("off hand", "Off hand", "off_hand"),
    ("ranged", "Ranged", "ranged"),
)
_PAIRS = {
    "finger 1": "finger 2",
    "finger 2": "finger 1",
    "trinket 1": "trinket 2",
    "trinket 2": "trinket 1",
}
TWO_HAND_INVENTORY_TYPE = 17

# Source kinds in the order a reader cares: the hardest content first.
_KIND_ORDER = (
    "raid",
    "dungeon",
    "craft",
    "honor_vendor",
    "quest",
    "world_drop",
    "open_world_npc",
    "chest",
    "container",
)
_KIND_TEXT = {
    "honor_vendor": "Honor vendor",
    "quest": "Quest reward",
    "world_drop": "World drop",
    "open_world_npc": "Open-world mob",
    "chest": "Chest",
    "container": "Container loot",
}


@functools.lru_cache(maxsize=None)
def _item_book() -> dict:
    with open(gearscore.DATA_DIR / "items.json", encoding="utf-8") as fh:
        return json.load(fh).get("items", {})


def all_list_ids(spec: str) -> list[int]:
    """Every item id the spec's pre-raid and raid lists name, sorted."""
    ids: set[int] = set()
    for phase in gearscore.PREFER_PHASES:
        lists = gearscore.load_spec(spec)["lists"].get(phase, {}).get("slots", {})
        for entries in lists.values():
            ids.update(int(i) for i in entries)
    return sorted(ids)


def choose_spec(class_name: str, tree: str | None) -> tuple[str | None, str]:
    """(spec file, note) for a class and tree; (None, note) with no data.

    The note is "" when the tree named the spec, else the reason it did not.
    """
    cls = str(class_name or "").lower()
    if cls in _ONE_SPEC:
        return _ONE_SPEC[cls], ""
    if tree and (cls, tree) in _BY_TREE:
        spec = _BY_TREE[(cls, tree)]
        note = ""
        if (cls, tree) == ("druid", "Feral Combat"):
            note = "Feral is scored as damage; the tree cannot tell cat from bear."
        return spec, note
    known = [s for s in gearscore.spec_ids() if s.startswith(cls + "-")]
    if not known:
        return None, f"No gear lists for the {cls or 'unknown'} class yet."
    why = f"tree {tree!r} has no list" if tree else "no talent tree is known"
    return known[0], f"Spec unknown ({why}); showing the class's first spec."


def where(entry: int) -> list[dict]:
    """Where an item comes from, one line per kind, hardest content first."""
    item = _item_book().get(str(entry))
    if not item:
        return []
    by_kind: dict[str, list[str]] = {}
    for src in item.get("sources", []):
        kind = src.get("type", "")
        detail = {
            "raid": src.get("instance"),
            "dungeon": src.get("instance"),
            "craft": " ".join(
                str(p) for p in (src.get("profession"), src.get("skill")) if p
            ),
        }.get(kind)
        names = by_kind.setdefault(kind, [])
        if detail and detail not in names:
            names.append(detail)
    out = []
    for kind in sorted(
        by_kind,
        key=lambda k: _KIND_ORDER.index(k) if k in _KIND_ORDER else len(_KIND_ORDER),
    ):
        names = by_kind[kind]
        text = _KIND_TEXT.get(kind) or {
            "raid": "Raid",
            "dungeon": "Dungeon",
            "craft": "Crafted",
        }.get(kind, kind)
        out.append(
            {"kind": kind, "label": f"{text}: {', '.join(names)}" if names else text}
        )
    return out


def _name(entry: int, rows: dict) -> str:
    row = rows.get(entry) or {}
    book = _item_book().get(str(entry)) or {}
    return (
        row.get("item_name") or row.get("name") or book.get("name") or f"item {entry}"
    )


def _round(value: float) -> float:
    return round(float(value), 1)


def _target(entry: int, value: float, rows: dict) -> dict:
    return {
        "entry": entry,
        "name": _name(entry, rows),
        "score": _round(value),
        "where": where(entry),
    }


def _ranked(spec, phase, key, stats_by_id, level) -> list[tuple[int, float]]:
    """The list's entries with known stats, best by gearscore first."""
    rows = []
    for item_id in gearscore.slot_list(spec, phase, key):
        stats = stats_by_id.get(item_id)
        if stats is not None:
            rows.append((item_id, gearscore.score(stats, spec, level, key)))
    return sorted(rows, key=lambda r: -r[1])


def _slot_key(key: str, worn_row: dict | None, spec: str) -> str:
    """The list key for the main hand: the two-hand list when a two-hander is
    worn (or the one-hand list is empty), else the one-hand list."""
    if key != "main_hand":
        return key
    two = worn_row is not None and (
        worn_row.get("inventory_type") == TWO_HAND_INVENTORY_TYPE
    )
    one_listed = any(
        gearscore.slot_list(spec, p, "main_hand") for p in gearscore.PREFER_PHASES
    )
    two_listed = any(
        gearscore.slot_list(spec, p, "two_hand") for p in gearscore.PREFER_PHASES
    )
    if (two and two_listed) or (not one_listed and two_listed):
        return "two_hand"
    return key


def _slot(
    spec, level, slot_name, label, key, worn_row, worn_by_slot, list_rows, stats_by_id
) -> dict:
    key = _slot_key(key, worn_row, spec)
    # A pair's second slot must not be told to buy what the first one wears.
    other = worn_by_slot.get(_PAIRS.get(slot_name, ""))
    pool = {
        i: s
        for i, s in stats_by_id.items()
        if not (other is not None and i == other["entry"])
    }
    worn_stats = None
    worn = None
    if worn_row is not None:
        worn_stats = gearscore.stats_from_row(worn_row)
        pool[worn_row["entry"]] = worn_stats
        worn_score = gearscore.score(worn_stats, spec, level, key)
        st = gearscore.standing(spec, key, worn_row["entry"], pool, level)
        worn = {
            "entry": worn_row["entry"],
            "name": _name(worn_row["entry"], {worn_row["entry"]: worn_row}),
            "score": _round(worn_score),
            "list": st.phase,
            "rank": st.rank,
            "size": st.size,
            "where": where(worn_row["entry"]),
        }
    targets = {}
    for phase in gearscore.PREFER_PHASES:
        label = gearscore.PHASE_LABEL[phase]
        targets[label] = [
            _target(i, s, list_rows)
            for i, s in _ranked(spec, phase, key, pool, level)[:TOP_TARGETS]
        ]
    best_pre = _ranked(spec, "preraid", key, pool, level)
    nxt = gearscore.next_target(spec, key, worn_stats, pool, level)
    next_upgrade = None
    if nxt:
        phase, item_id, value = nxt
        next_upgrade = _target(item_id, value, list_rows)
        next_upgrade["phase"] = phase
        next_upgrade["gain"] = _round(value - (worn["score"] if worn else 0.0))
    pct = None
    if worn and best_pre and best_pre[0][1] > 0:
        pct = min(1.0, gearscore.score(worn_stats, spec, level, key) / best_pre[0][1])
    if worn is None:
        state = "empty"
    elif not best_pre:
        state = "no_list"
    elif pct is not None and pct >= AT_BEST:
        state = "best"
    elif pct is not None and pct >= NEAR:
        state = "near"
    else:
        state = "upgrade"
    return {
        "slot": slot_name,
        "label": label,
        "list_key": key,
        "state": state,
        "worn": worn,
        "pct_of_preraid": None if pct is None else round(pct, 3),
        "targets": targets,
        "next": next_upgrade,
        "scored": bool(best_pre),
    }


def build(
    member: dict, equipment_rows: list[dict], list_rows: dict, slot_names: list[str]
) -> dict:
    """The tracker payload for one member.

    `member` is armory's member dict (name, class, level, spec.primary).
    `equipment_rows` are the worn rows as _fetch_armory reads them (`slot` is
    the paper-doll index into `slot_names`). `list_rows` maps item id to an
    item_template row for every id the spec's lists name.
    """
    level = int(member.get("level") or 1)
    tree = (member.get("spec") or {}).get("primary")
    spec, note = choose_spec(member.get("class"), tree)
    head = {
        "name": member.get("name"),
        "class": member.get("class"),
        "level": level,
        "scored_from": SCORED_FROM,
    }
    if spec is None:
        return {
            **head,
            "spec": {"id": None, "tree": tree, "assumed": True, "note": note},
            "ready": None,
            "slots": [],
        }
    data = gearscore.load_spec(spec)
    stats_by_id = {int(i): gearscore.stats_from_row(r) for i, r in list_rows.items()}
    worn_by_slot = {}
    for r in equipment_rows:
        idx = r.get("slot")
        if isinstance(idx, int) and 0 <= idx < len(slot_names):
            worn_by_slot[slot_names[idx]] = r
    slots = [
        _slot(
            spec,
            level,
            name,
            label,
            key,
            worn_by_slot.get(name),
            worn_by_slot,
            list_rows,
            stats_by_id,
        )
        for name, label, key in ROWS
    ]
    scored = [s for s in slots if s["scored"]]
    ready_n = sum(1 for s in scored if s["state"] in ("best", "near"))
    return {
        **head,
        "spec": {
            "id": spec,
            "tree": tree,
            "role": data.get("role"),
            "assumed": bool(note and not note.startswith("Feral")),
            "note": note,
        },
        "ready": {
            "slots_ready": ready_n,
            "slots_scored": len(scored),
            "pct": round(ready_n / len(scored), 3) if scored else None,
            "near": NEAR,
            "line": (
                f"{ready_n} of {len(scored)} slots at or near pre-raid best in slot"
            ),
        },
        "slots": slots,
    }
