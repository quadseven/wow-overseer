"""Per-spec gear scoring and best-in-slot standing (#539).

Decision #532: "better gear" follows the sixtyupgrades approach. Per-spec stat
weights score every item at every level; at 60 a member aims first for its
pre-raid best-in-slot list, then the raid list. The lists are a curated
snapshot in `data/bis/` (research #537); nothing here reads the network.

THE LIST IS A SHOPPING LIST, NEVER THE SCORE. A guide ranks items by their
classic stats, and this server carries the 3.3.5 versions: percent stats are
ratings, +healing is spell power, one-school damage is all-school. So every
score comes from OUR item stats, and an item that is weaker here ranks lower
even when a list names it.

STATS IN. `score` takes a flat dict of normalized stat names (see
`stats_from_row` for an `item_template` row): primary stats, `*_rating`
stats, `spell_power`, `armor`, resistances and `weapon_dps`. Equip-spell stats
(a helm whose crit is an equip spell) are the caller's to fold in before
scoring; this module never sees spells.

WEIGHTS. The numbers are wowsims/classic's default EP weights (MIT, see
`data/bis/NOTICE.txt`). Percent weights (hit, crit, haste, dodge, parry,
block) apply per 1%, so a rating is converted with the level-60 table in
`data/bis/ratings-l60.json` first. Defense and expertise apply per skill
point (rating over the per-point rating). Not scored, on purpose:
  - caps (a 9% melee hit cap needs the whole set, not one item);
  - school powers (the server folds them into all-school spell power);
  - melee haste (the weight's unit is not stated by the source);
  - resilience, armor penetration, and anything no weight names.
Healer specs carry classic +healing weights, and this server's spell power
heals about 1.88 times as well per point (the patch 3.0 rescale), so a healer
weighs spell power at 1.88 times the weight.

LEVELS. Ratings convert at level 60 from the server's own tables. Below 60 the
documented 3.x curve scales the rating needed per percent by (level - 8) / 52
(floor of 2 / 52 under level 10), so the same rating is worth more percent to
a low level. Above 60 the level-60 values hold.

ENCHANTS AND RANDOM SUFFIXES (#561). A worn item's instance adds stats the
template does not have: its permanent enchant, gems, and the stats of "of the
Tiger". `armory.instance_stats` resolves them from the committed client
tables in `items.json`; `add_stats` folds them into the template stats before
`score`. Only a WORN item has an instance, so a list entry is scored bare.
Equip procs and the temporary enchant (poisons, oils) are not folded in.

PURE MODULE: dicts in, numbers and dicts out. Callers read item_template.
"""

from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import dataclass

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data" / "bis"

PREFER_PHASES = ("preraid", "mc")  # aim order: pre-raid list first, then raid
PHASE_LABEL = {"preraid": "preraid", "mc": "raid"}

# One spell power point heals this many classic +healing points (patch 3.0).
HEALING_SPELL_POWER_SCALE = 1.88

# The ratings table's own names for each rating stat this module reads.
_RATING_KIND = {
    "defense_rating": "defense",
    "dodge_rating": "dodge",
    "parry_rating": "parry",
    "block_rating": "block",
    "hit_rating": "hit_melee",
    "hit_melee_rating": "hit_melee",
    "hit_ranged_rating": "hit_ranged",
    "hit_spell_rating": "hit_spell",
    "crit_rating": "crit_melee",
    "crit_melee_rating": "crit_melee",
    "crit_ranged_rating": "crit_ranged",
    "crit_spell_rating": "crit_spell",
    "haste_rating": "haste_spell",
    "expertise_rating": "expertise",
}

# item_template.stat_type -> normalized stat name.
STAT_TYPES = {
    1: "health",
    0: "mana",
    3: "agility",
    4: "strength",
    5: "intellect",
    6: "spirit",
    7: "stamina",
    12: "defense_rating",
    13: "dodge_rating",
    14: "parry_rating",
    15: "block_rating",
    16: "hit_melee_rating",
    17: "hit_ranged_rating",
    18: "hit_spell_rating",
    19: "crit_melee_rating",
    20: "crit_ranged_rating",
    21: "crit_spell_rating",
    28: "haste_rating",
    29: "haste_rating",
    30: "haste_rating",
    31: "hit_rating",
    32: "crit_rating",
    35: "resilience_rating",
    36: "haste_rating",
    37: "expertise_rating",
    38: "attack_power",
    39: "ranged_attack_power",
    40: "feral_attack_power",
    41: "spell_power",
    42: "spell_power",
    43: "mp5",
    45: "spell_power",
    48: "block_value",
}

# item_template resistance columns -> normalized stat name.
_RESISTANCES = {
    "fire_res": "fire_resistance",
    "frost_res": "frost_resistance",
    "nature_res": "nature_resistance",
    "shadow_res": "shadow_resistance",
    "arcane_res": "arcane_resistance",
}

# stat name -> the weight it takes per point, for stats that need no conversion.
_FLAT_WEIGHT = {
    "strength": "Strength",
    "agility": "Agility",
    "stamina": "Stamina",
    "intellect": "Intellect",
    "spirit": "Spirit",
    "health": "Health",
    "mana": "Mana",
    "mp5": "MP5",
    "attack_power": "AttackPower",
    "ranged_attack_power": "RangedAttackPower",
    "feral_attack_power": "FeralAttackPower",
    "armor": "Armor",
    "block_value": "BlockValue",
    "fire_resistance": "FireResistance",
    "frost_resistance": "FrostResistance",
    "nature_resistance": "NatureResistance",
    "shadow_resistance": "ShadowResistance",
    "arcane_resistance": "ArcaneResistance",
}

_DPS_WEIGHT = {
    "main_hand": "MainHandDps",
    "two_hand": "MainHandDps",
    "off_hand": "OffHandDps",
    "ranged": "RangedDps",
}


# --- data readers ----------------------------------------------------------


def _read(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


@functools.lru_cache(maxsize=None)
def load_ratings() -> dict:
    """The level-60 combat rating table (`ratings-l60.json`)."""
    return _read("ratings-l60.json")["ratings"]


@functools.lru_cache(maxsize=None)
def load_spec(spec: str) -> dict:
    """One spec's weights and lists, e.g. `load_spec("mage-dps")`.

    Raises KeyError for a spec with no data file, so a typo is loud.
    """
    path = DATA_DIR / f"{spec}.json"
    if not path.is_file() or spec in ("items", "situational", "ratings-l60"):
        raise KeyError(f"no gear data for spec {spec!r}")
    return _read(f"{spec}.json")


def spec_ids() -> list:
    """Every spec that has a data file, sorted."""
    skip = {"items", "situational", "ratings-l60", "weights-wowsims"}
    return sorted(p.stem for p in DATA_DIR.glob("*.json") if p.stem not in skip)


@functools.lru_cache(maxsize=None)
def load_situational() -> dict:
    """Fire resistance, PvP honor and battleground sets (`situational.json`)."""
    return _read("situational.json")


def slot_list(spec: str, phase: str, slot: str) -> list:
    """The listed item ids for a slot, best first. Empty when the guide has none."""
    lists = load_spec(spec)["lists"]
    return list(lists.get(phase, {}).get("slots", {}).get(slot, []))


# --- rating conversion -----------------------------------------------------


def level_scale(level: int) -> float:
    """How much of a level-60 rating a percent costs at this level (1.0 at 60)."""
    lv = int(level)
    if lv >= 60:
        return 1.0
    return max(lv - 8, 2) / 52.0


def rating_per_pct(kind: str, class_name: str, level: int = 60) -> float:
    """Rating points that make 1% (or 1 skill point for defense and expertise)."""
    entry = load_ratings()[kind]["rating_per_pct_by_class"]
    return entry[class_name] * level_scale(level)


def rating_to_pct(stat: str, rating: float, class_name: str, level: int = 60) -> float:
    """What `rating` of a rating stat is worth, in percent (skill points for
    defense and expertise)."""
    return rating / rating_per_pct(_RATING_KIND[stat], class_name, level)


# --- item stats ------------------------------------------------------------


def stats_from_row(row: dict) -> dict:
    """Normalized stats from an item_template row (stat_type1..10 and friends).

    Reads `stat_typeN`/`stat_valueN`, `armor`, `block`, the five resistance
    columns and `dmg_min1`/`dmg_max1`/`delay` (as `weapon_dps`). Stats that
    come from equip spells are not in the row; add them to the result.
    """
    out: dict = {}

    def add(name, value):
        if value:
            out[name] = out.get(name, 0) + value

    for n in range(1, 11):
        name = STAT_TYPES.get(_int(row.get(f"stat_type{n}")))
        if name:
            add(name, _int(row.get(f"stat_value{n}")))
    add("armor", _int(row.get("armor")))
    add("block_value", _int(row.get("block")))
    for col, name in _RESISTANCES.items():
        add(name, _int(row.get(col)))
    delay = _int(row.get("delay"))
    if delay > 0:
        mid = (_flt(row.get("dmg_min1")) + _flt(row.get("dmg_max1"))) / 2.0
        if mid > 0:
            out["weapon_dps"] = mid / (delay / 1000.0)
    return out


def add_stats(base: dict, extra: dict) -> dict:
    """`base` plus `extra` ({item_template stat type: amount}, as
    `armory.instance_stats` returns), as a new dict of normalized stats.
    A stat type this module has no name for is dropped, never scored as 0."""
    out = dict(base)
    for kind, amount in extra.items():
        name = STAT_TYPES.get(_int(kind))
        if name and amount:
            out[name] = out.get(name, 0) + amount
    return out


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _flt(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# --- scoring ---------------------------------------------------------------


def score(item_stats: dict, spec: str, level: int = 60, slot: str = "") -> float:
    """What an item is worth to a spec at a level, from its stats alone.

    `slot` picks the weapon DPS weight (main hand and two hand, off hand,
    ranged); it matters only for an item with `weapon_dps`.
    """
    data = load_spec(spec)
    w = data["weights"]["values"]
    cls = data["class"]
    total = 0.0

    for stat, weight_name in _FLAT_WEIGHT.items():
        value = item_stats.get(stat)
        if value:
            total += value * float(w.get(weight_name) or 0.0)

    sp = item_stats.get("spell_power")
    if sp:
        weight = float(w.get("SpellPower") or w.get("SpellDamage") or 0.0)
        if data.get("role") == "healer":
            weight *= HEALING_SPELL_POWER_SCALE
        total += sp * weight

    dps = item_stats.get("weapon_dps")
    if dps:
        total += dps * float(w.get(_DPS_WEIGHT.get(slot, "MainHandDps")) or 0.0)

    for stat, kind in _RATING_KIND.items():
        rating = item_stats.get(stat)
        if rating:
            total += _rating_value(stat, kind, rating, w, cls, level)
    return total


# Generic hit and crit ratings serve melee and spell together: each side is
# converted at its own rating-per-percent and weighed at its own weight.
_BOTH_SIDES = {
    "hit_rating": (("hit_melee", "MeleeHit"), ("hit_spell", "SpellHit")),
    "crit_rating": (("crit_melee", "MeleeCrit"), ("crit_spell", "SpellCrit")),
}

_RATING_WEIGHT = {
    "defense_rating": "Defense",
    "dodge_rating": "Dodge",
    "parry_rating": "Parry",
    "block_rating": "Block",
    "hit_melee_rating": "MeleeHit",
    "hit_ranged_rating": "MeleeHit",
    "hit_spell_rating": "SpellHit",
    "crit_melee_rating": "MeleeCrit",
    "crit_ranged_rating": "MeleeCrit",
    "crit_spell_rating": "SpellCrit",
    "haste_rating": "SpellHaste",
    "expertise_rating": "Expertise",
}


def _rating_value(
    stat: str, kind: str, rating: float, w: dict, cls: str, level: int
) -> float:
    sides = _BOTH_SIDES.get(stat)
    if sides:
        return sum(
            rating / rating_per_pct(k, cls, level) * float(w.get(name) or 0.0)
            for k, name in sides
        )
    weight = float(w.get(_RATING_WEIGHT.get(stat, "")) or 0.0)
    return rating / rating_per_pct(kind, cls, level) * weight


# --- best-in-slot standing -------------------------------------------------


@dataclass(frozen=True)
class Standing:
    """Where one item sits against a spec's lists for a slot.

    `phase` is "preraid" or "raid" for the first list that names the item, or
    "" when neither does. `rank` is 1 for the best-scoring entry of that list
    (the list the item is in; for an unlisted item, the pre-raid list), counted
    by OUR score, not the guide's order. `size` counts the list entries that
    have known stats. `pct_of_best` is score over the list's best score.
    """

    item_id: int
    phase: str
    rank: int
    size: int
    score: float
    best_id: int
    best_score: float
    pct_of_best: float


def _phase_scores(spec, phase, slot, stats_by_id, level):
    """[(item_id, score)] for the slot's list, best score first; ties keep the
    guide's order. An entry with no known stats is skipped, never scored as 0."""
    rows = []
    for item_id in slot_list(spec, phase, slot):
        stats = stats_by_id.get(item_id)
        if stats is not None:
            rows.append((item_id, score(stats, spec, level, slot)))
    return sorted(rows, key=lambda r: -r[1])


def standing(
    spec: str, slot: str, item_id: int, stats_by_id: dict, level: int = 60
) -> Standing:
    """Where `item_id` ranks among the spec's pre-raid, then raid, entries.

    `stats_by_id` maps item id to stats for the item and every list entry (the
    caller reads them from item_template). An item named by the pre-raid list
    ranks there; else one named by the raid list ranks there; an unlisted item
    ranks against the pre-raid list by score, so "does this beat my target"
    has an answer for any item.
    """
    own = stats_by_id.get(item_id)
    own_score = score(own, spec, level, slot) if own is not None else 0.0
    for phase in PREFER_PHASES:
        if item_id in slot_list(spec, phase, slot):
            break
    else:
        phase = ""
    rank_phase = phase or PREFER_PHASES[0]
    rows = _phase_scores(spec, rank_phase, slot, stats_by_id, level)
    rows = [r for r in rows if r[0] != item_id]
    rank = 1 + sum(1 for _, s in rows if s > own_score)
    best_id, best_score = (item_id, own_score)
    if rows and rows[0][1] > own_score:
        best_id, best_score = rows[0]
    pct = (own_score / best_score) if best_score > 0 else 0.0
    return Standing(
        item_id=item_id,
        phase=PHASE_LABEL.get(phase, ""),
        rank=rank,
        size=len(rows) + 1,
        score=own_score,
        best_id=best_id,
        best_score=best_score,
        pct_of_best=pct,
    )


def is_upgrade(
    spec: str,
    candidate: dict,
    worn: dict | None,
    level: int = 60,
    slot: str = "",
    min_gain: float = 0.0,
) -> bool:
    """True when the candidate scores more than what is worn (or an empty slot)."""
    new = score(candidate, spec, level, slot)
    old = score(worn, spec, level, slot) if worn else 0.0
    return new > old + min_gain


def next_target(
    spec: str, slot: str, worn: dict | None, stats_by_id: dict, level: int = 60
) -> tuple | None:
    """The list item to aim for: `(phase, item_id, score)`, or None.

    Pre-raid list first, the raid list once nothing pre-raid beats what is
    worn. Within a list the highest score wins, by OUR stats. Entries with
    unknown stats are skipped.
    """
    old = score(worn, spec, level, slot) if worn else 0.0
    for phase in PREFER_PHASES:
        rows = _phase_scores(spec, phase, slot, stats_by_id, level)
        if rows and rows[0][1] > old:
            return (PHASE_LABEL[phase], rows[0][0], rows[0][1])
    return None
