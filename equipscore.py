"""Which carried piece a member should wear, judged by its spec's gear score.

WHY ITEM LEVEL WAS THE WRONG JUDGE. The equip pass (`gear.equips`) put a piece
on when its item level beat the worn one. Measured on the dev realm on
2026-10-10: the pass held back 42 pieces across the two family guilds after
three `e` commands each, and 31 of them score LOWER than what the member wears
by the member's own spec weights (gearscore.py). Bork, a rogue, was asked to
wear a cloth Mistscape Sash (item level 42) over his leather belt (37); Grug,
a Protection warrior, a Warmonger's Cloak scoring 5 over a worn cloak scoring
39. Every one of those pieces is soulbound now, so each was put on and taken
off again: mod-playerbots' own equip action ("equip upgrades", on loot, trade
and a random non-combat tick) scores items by their stats and puts the better
one back. The bridge asked, the bot undid it, and after three asks the bridge
gave up for a day. Meanwhile the pass never looked at a ring, a neck or a
trinket (`gear._SLOT_BY_INVTYPE` has no bucket for them), refused every
one-hander while a two-hander was worn, and read only uncommon or better
pieces for a guild member.

THE RULE HERE. One opinion, the one the upgrade tracker and the guild's loot
board already use: `gearscore.score` for the member's spec (its played talent
tree, else the raid plan's, `gearupgrades.choose_spec`), with the item
instance's random suffix and enchant folded in. Where the spec values nothing
on either piece (a level 25 mage's spec weighs stamina and spirit at 0, so a
Runic Stave and a Walking Stick both score 0), the role weights of
statweights.py decide, the module's own scorer that the loot council shows.
A piece is worn when it beats the worn one by MIN_GAIN of its score, the same
ten percent the guild loot board asks (guildsocial.MIN_GAIN_SHARE) and the
margin mod-playerbots' own equip test applies, so the two do not fight over a
sidegrade.

WHAT IT JUDGES THAT THE OLD PASS DID NOT.
  * Necks, rings and trinkets. A pair (two rings, two trinkets) keeps its two
    best pieces; a unique-equipped piece is counted once.
  * The weapon hands as one set. A one-hander and an off-hand piece that
    together beat the two-hander worn are both put on, the main hand first
    (the core refuses an off-hand piece while a two-hander is worn). A shield
    tank's set always holds a shield when it owns one.
  * Usable means usable NOW, by the character's own rows: level, class and
    race masks, the proficiency skill the core checks
    (`recap.item_skill`, from character_skills), dual wield for an off-hand
    weapon, and the off-hand guards of gear.py (a caster's held piece is never
    a warrior's, a tank's off hand holds a shield). A weapon the member lacks
    the skill for is never asked for; `waiting_on_skill` names it, so the
    weapon-skill pass can be pointed at it.

PURE: rows in, `bag_pressure.Equip` rows out. The bridge reads the rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import armory
import bag_pressure
import gearscore
import gearupgrades
import guildrun
import recap
import statweights
import weaponskill

# The share of the worn piece's score a carried piece must add to be put on.
MIN_GAIN = 0.1
# A score difference smaller than this is no difference.
EPSILON = 1e-6
# Below this gear score on both pieces the spec has no real opinion (a stray
# point of armour), and the role weights decide.
SCORE_FLOOR = 0.5

ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR = 2, 4
WEAPON_MISC, WEAPON_FISHING_POLE = 14, 20
DUAL_WIELD_SKILL = 118
# item_template.Flags: ITEM_FLAG_UNIQUE_EQUIPPABLE.
UNIQUE_EQUIPPABLE = 0x80000

# InventoryType -> the slot group a piece is judged in.
SINGLE = {
    1: "head",
    2: "neck",
    3: "shoulder",
    5: "chest",
    20: "chest",
    6: "waist",
    7: "legs",
    8: "feet",
    9: "wrist",
    10: "hands",
    16: "back",
    15: "ranged",
    25: "ranged",
    26: "ranged",
    28: "ranged",
}
PAIRS = {11: "finger", 12: "trinket"}
# character_inventory equipment slot (bag 0) -> the group worn there.
WORN_GROUP = {
    0: "head",
    1: "neck",
    2: "shoulder",
    4: "chest",
    5: "waist",
    6: "legs",
    7: "feet",
    8: "wrist",
    9: "hands",
    10: "finger",
    11: "finger",
    12: "trinket",
    13: "trinket",
    14: "back",
    17: "ranged",
}
MAIN_HAND_SLOT, OFF_HAND_SLOT = 15, 16
ONE_HAND, TWO_HAND, MAIN_HAND_ONLY = 13, 17, 21
SHIELD, OFF_HAND_WEAPON, HELD = 14, 22, 23
HAND_TYPES = frozenset(
    {ONE_HAND, TWO_HAND, MAIN_HAND_ONLY, SHIELD, OFF_HAND_WEAPON, HELD}
)
# The weapon DPS weight a hand reads (gearscore._DPS_WEIGHT's keys).
_KEY = {
    ONE_HAND: "main_hand",
    MAIN_HAND_ONLY: "main_hand",
    TWO_HAND: "two_hand",
    OFF_HAND_WEAPON: "off_hand",
    15: "ranged",
    25: "ranged",
    26: "ranged",
    28: "ranged",
}
# The tanks' specs: a member playing one holds a shield.
SHIELD_TANK_SPECS = frozenset({"warrior-protection", "paladin-protection"})

# gearscore's normalized stat names -> the names statweights prices.
_ROLE_STAT = {
    "agility": "agility",
    "strength": "strength",
    "intellect": "intellect",
    "spirit": "spirit",
    "stamina": "stamina",
    "defense_rating": "defense",
    "dodge_rating": "dodge",
    "parry_rating": "parry",
    "block_rating": "block",
    "block_value": "block_value",
    "hit_rating": "hit",
    "hit_melee_rating": "hit",
    "hit_ranged_rating": "hit",
    "hit_spell_rating": "spell_hit",
    "crit_rating": "crit",
    "crit_melee_rating": "crit",
    "crit_ranged_rating": "crit",
    "crit_spell_rating": "crit",
    "attack_power": "attack_power",
    "ranged_attack_power": "attack_power",
    "spell_power": "spell_power",
    "mp5": "mana_regeneration",
    "weapon_dps": "weapon_dps",
}


@dataclass(frozen=True)
class Wearer:
    """What the judge needs to know about one member."""

    name: str
    class_id: int
    level: int
    race: int = 0
    spec: str | None = None
    role: str = statweights.UNKNOWN
    # character_skills lines held at a value above 0.
    skills: frozenset = field(default_factory=frozenset)
    shield_tank: bool = False

    @property
    def dual_wields(self) -> bool:
        return DUAL_WIELD_SKILL in self.skills


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _skills(text) -> frozenset:
    out = set()
    for part in str(text or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


def wearer_from_row(row: dict, tanks=()) -> Wearer | None:
    """A Wearer from one member row (name, class_id, level, race,
    talent_spells, target_tree, skills: the held skill lines, comma
    separated), or None when the row cannot say who."""
    member = guildrun.member_from_row(row)
    if member is None or member.class_id <= 0:
        return None
    tree = member.played_tree or None
    spec, _note = gearupgrades.choose_spec(
        guildrun.raidroles_class_name(member.class_id), tree
    )
    role = statweights.role_for(member.class_id, tree or "")
    if role == statweights.UNKNOWN and spec:
        # No tree spent yet: the role of the spec choose_spec settled on
        # (gearscore's spec files name the same five roles statweights does).
        named = str(gearscore.load_spec(spec).get("role") or "")
        role = named if named in statweights.STAT_WEIGHTS else role
    return Wearer(
        name=member.name,
        class_id=member.class_id,
        level=member.level,
        race=member.race,
        spec=spec,
        role=role,
        skills=_skills(row.get("skills")),
        shield_tank=spec in SHIELD_TANK_SPECS or member.name in set(tanks or ()),
    )


# --- what a piece is worth ---------------------------------------------------


def stats_of(row: dict, book=None) -> dict:
    """The piece's normalized stats: its template, plus its instance's random
    suffix and enchants when an item book is given (armory.instance_stats)."""
    stats = gearscore.stats_from_row(row)
    if book is not None and (row.get("random_property_id") or row.get("enchantments")):
        try:
            extra, _names = armory.instance_stats(row, book)
        except (KeyError, TypeError, ValueError):
            extra = {}
        stats = gearscore.add_stats(stats, extra)
    return stats


def role_score(stats: dict, role: str) -> float:
    """What the stats are worth to a role by statweights, armour per ten
    points, the way bankpolicy.role_scores prices a piece."""
    weights = statweights.stat_weights(role)
    total = 0.0
    for name, value in stats.items():
        if name == "armor":
            total += weights.get("armor", 0.0) * float(value) / 10.0
            continue
        total += weights.get(_ROLE_STAT.get(name, ""), 0.0) * float(value)
    return total


def value(row: dict, wearer: Wearer, key: str = "", book=None) -> tuple:
    """(gear score, role score) of one piece for this member, in hand `key`."""
    if row is None:
        return (0.0, 0.0)
    stats = stats_of(row, book)
    gs = gearscore.score(stats, wearer.spec, wearer.level, key) if wearer.spec else 0.0
    return (gs, role_score(stats, wearer.role))


def _add(a: tuple, b: tuple) -> tuple:
    return (a[0] + b[0], a[1] + b[1])


def beats(new: tuple, old: tuple) -> bool:
    """Does `new` beat `old` by MIN_GAIN: by gear score, or by the role score
    when the spec scores neither."""
    if _spec_decides(new, old):
        return new[0] - old[0] > EPSILON and new[0] > old[0] * (1.0 + MIN_GAIN)
    return new[1] - old[1] > EPSILON and new[1] > old[1] * (1.0 + MIN_GAIN)


def _spec_decides(new: tuple, old: tuple) -> bool:
    return max(new[0], old[0]) >= SCORE_FLOOR


def _rank(v: tuple, row: dict | None) -> tuple:
    return (round(v[0], 6), round(v[1], 6), _int((row or {}).get("item_level")))


# --- can it be put on now ----------------------------------------------------


def skill_needed(row: dict) -> int:
    """The proficiency line the core checks for this piece, 0 for none."""
    return recap.item_skill(
        {
            "class": _int(row.get("item_class")),
            "subclass": _int(row.get("item_subclass")),
            "inventory_type": _int(row.get("inventory_type")),
        }
    )


def refusal(row: dict, wearer: Wearer, off_hand: bool = False) -> str:
    """Why this member cannot put the piece on now, or "" when it can."""
    item_class = _int(row.get("item_class"))
    inv = _int(row.get("inventory_type"))
    if item_class not in (ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR):
        return "not gear"
    if inv not in SINGLE and inv not in PAIRS and inv not in HAND_TYPES:
        return "inventory type %d is not judged" % inv
    if item_class == ITEM_CLASS_WEAPON and _int(row.get("item_subclass")) in (
        WEAPON_MISC,
        WEAPON_FISHING_POLE,
    ):
        return "a tool, not a weapon"
    if _int(row.get("required_level")) > wearer.level:
        return "requires level %d" % _int(row.get("required_level"))
    classes = _int(row.get("allowable_class"), -1)
    if classes not in (0, -1) and not classes & (1 << (wearer.class_id - 1)):
        return "not for this class"
    races = _int(row.get("allowable_race"), -1)
    if wearer.race and races not in (0, -1) and not races & (1 << (wearer.race - 1)):
        return "not for this race"
    need = skill_needed(row)
    if need and need not in wearer.skills:
        return "lacks the %s skill" % recap.SKILL_NAMES.get(need, str(need))
    if _int(row.get("required_skill")):
        # A profession's own gear (an engineer's goggles) asks a skill RANK,
        # which this pass does not read; the profession passes own it.
        return "asks a profession skill rank"
    if _int(row.get("required_spell")) or _int(row.get("required_reputation")):
        return "asks a spell or a reputation this pass cannot read"
    if off_hand and inv in (ONE_HAND, OFF_HAND_WEAPON) and not wearer.dual_wields:
        return "cannot dual wield"
    if inv in (SHIELD, OFF_HAND_WEAPON, HELD) or off_hand:
        role = (
            bag_pressure.ROLE_TANK if wearer.shield_tank else bag_pressure.ROLE_UNKNOWN
        )
        if wearer.role == statweights.MELEE and wearer.class_id == 2:
            role = bag_pressure.ROLE_DAMAGE
        said = bag_pressure.off_hand_refusal(row, wearer.class_id, wearer.level, role)
        if said:
            return said
    return ""


def waits_on_skill(row: dict, wearer: Wearer) -> bool:
    """Is a weapon skill its class can learn at a weapon master the only
    thing between member and piece (weaponskill's own tables)."""
    if _int(row.get("item_class")) != ITEM_CLASS_WEAPON:
        return False
    subclass = _int(row.get("item_subclass"), -1)
    if subclass not in weaponskill.WEAPON_SKILLS:
        return False
    if subclass not in weaponskill.CLASS_WEAPONS.get(wearer.class_id, set()):
        return False
    if not refusal(row, wearer).startswith("lacks the ") or not skill_needed(row):
        return False
    held = Wearer(**{**wearer.__dict__, "skills": wearer.skills | {skill_needed(row)}})
    return refusal(row, held) == ""


def _unique(row: dict) -> bool:
    return _int(row.get("max_count")) == 1 or bool(
        _int(row.get("item_flags")) & UNIQUE_EQUIPPABLE
    )


# --- the choice ----------------------------------------------------------------


def _equip(row: dict, wearer: Wearer, slot: str, worn_level: int, reason: str):
    return bag_pressure.Equip(
        holder=wearer.name,
        guid=_int(row.get("item_guid")),
        entry=_int(row.get("entry")),
        name=str(row.get("name") or ""),
        slot=slot,
        item_level=_int(row.get("item_level")),
        worn_level=int(worn_level),
        reason=reason,
    )


def _said(new: tuple, old: tuple, wearer: Wearer) -> str:
    if _spec_decides(new, old):
        return "gear score %.1f over %.1f for %s" % (new[0], old[0], wearer.spec)
    return "%s role score %.1f over %.1f (the %s spec scores neither)" % (
        wearer.role,
        new[1],
        old[1],
        wearer.spec or "unknown",
    )


def _singles(wearer, worn, carried, book) -> list:
    out = []
    for group in sorted(set(SINGLE.values())):
        on = [r for r in worn if WORN_GROUP.get(_int(r.get("equipment_slot"))) == group]
        old_row = on[0] if on else None
        key = _KEY.get(_int((old_row or {}).get("inventory_type")), "")
        old = value(old_row, wearer, key, book)
        best = None
        for row in carried:
            if SINGLE.get(_int(row.get("inventory_type"))) != group:
                continue
            if refusal(row, wearer):
                continue
            v = value(row, wearer, _KEY.get(_int(row.get("inventory_type")), ""), book)
            if best is None or _rank(v, row) > _rank(best[0], best[1]):
                best = (v, row)
        if best is not None and beats(best[0], old):
            out.append(
                _equip(
                    best[1],
                    wearer,
                    group,
                    _int((old_row or {}).get("item_level")),
                    _said(best[0], old, wearer),
                )
            )
    return out


def _pairs(wearer, worn, carried, book) -> list:
    out = []
    for group in sorted(set(PAIRS.values())):
        on = [r for r in worn if WORN_GROUP.get(_int(r.get("equipment_slot"))) == group]
        pool = [(value(r, wearer, "", book), r, True) for r in on]
        for row in carried:
            if PAIRS.get(_int(row.get("inventory_type"))) != group or refusal(
                row, wearer
            ):
                continue
            pool.append((value(row, wearer, "", book), row, False))
        pool.sort(key=lambda t: _rank(t[0], t[1]), reverse=True)
        chosen, entries = [], set()
        for v, row, is_worn in pool:
            entry = _int(row.get("entry"))
            if entry in entries and (_unique(row) or not is_worn):
                # A unique piece is worn once; and `e Hitem:<entry>` cannot
                # name a second copy of what is already worn.
                continue
            entries.add(entry)
            chosen.append((v, row, is_worn))
            if len(chosen) == 2:
                break
        old = (0.0, 0.0)
        for r in on:
            old = _add(old, value(r, wearer, "", book))
        new = (0.0, 0.0)
        for v, _row, _w in chosen:
            new = _add(new, v)
        if not beats(new, old):
            continue
        floor = (
            min((_int(r.get("item_level")) for r in on), default=0)
            if len(on) == 2
            else 0
        )
        for v, row, is_worn in chosen:
            if not is_worn:
                out.append(_equip(row, wearer, group, floor, _said(new, old, wearer)))
    return out


def _hands(wearer, worn, carried, book) -> list:
    main = next(
        (r for r in worn if _int(r.get("equipment_slot")) == MAIN_HAND_SLOT), None
    )
    off = next(
        (r for r in worn if _int(r.get("equipment_slot")) == OFF_HAND_SLOT), None
    )
    two_worn = main is not None and _int(main.get("inventory_type")) == TWO_HAND

    def main_value(row):
        key = "two_hand" if _int(row.get("inventory_type")) == TWO_HAND else "main_hand"
        return value(row, wearer, key, book)

    def off_value(row):
        key = "off_hand" if _int(row.get("item_class")) == ITEM_CLASS_WEAPON else ""
        return value(row, wearer, key, book)

    old = (0.0, 0.0)
    if main is not None:
        old = _add(old, main_value(main))
    if off is not None:
        old = _add(old, off_value(off))

    usable = [r for r in carried if _int(r.get("inventory_type")) in HAND_TYPES]
    twos = [
        r
        for r in usable
        if _int(r.get("inventory_type")) == TWO_HAND and not refusal(r, wearer)
    ]
    mains = [
        r
        for r in usable
        if _int(r.get("inventory_type")) in (ONE_HAND, MAIN_HAND_ONLY)
        and not refusal(r, wearer)
    ]
    offs = [
        r
        for r in usable
        if _int(r.get("inventory_type")) in (SHIELD, OFF_HAND_WEAPON, HELD, ONE_HAND)
        and not refusal(r, wearer, off_hand=True)
    ]
    if main is not None and not two_worn:
        mains.append(main)
    if off is not None:
        offs.append(off)
    if two_worn:
        twos.append(main)

    shields = [r for r in offs if _int(r.get("inventory_type")) == SHIELD]
    need_shield = wearer.shield_tank and bool(shields)

    configs = []
    if not need_shield:
        for row in twos:
            configs.append(((row, None), main_value(row)))
    for m in mains + [None]:
        if m is None and two_worn:
            # The core will not put an off-hand piece beside a two-hander, and
            # nothing here takes the two-hander off on its own.
            continue
        for o in offs + [None]:
            if m is not None and o is not None and m is o:
                continue
            if (
                m is not None
                and o is not None
                and _int(m.get("item_guid")) == _int(o.get("item_guid"))
            ):
                continue
            if m is None and o is None:
                continue
            if need_shield and (o is None or _int(o.get("inventory_type")) != SHIELD):
                continue
            v = (0.0, 0.0)
            if m is not None:
                v = _add(v, main_value(m))
            if o is not None:
                v = _add(v, off_value(o))
            configs.append(((m, o), v))
    if not configs:
        return []

    def rank(config):
        (m, o), v = config
        level = _int((m or {}).get("item_level")) + _int((o or {}).get("item_level"))
        return (round(v[0], 6), round(v[1], 6), level)

    (m, o), new = max(configs, key=rank)
    if not beats(new, old):
        return []
    worn_rows = [r for r in (main, off) if r is not None]
    out = []
    said = _said(new, old, wearer)
    if m is not None and all(m is not r for r in worn_rows):
        slot = "two_hand" if _int(m.get("inventory_type")) == TWO_HAND else "main_hand"
        out.append(_equip(m, wearer, slot, _int((main or {}).get("item_level")), said))
    if o is not None and all(o is not r for r in worn_rows):
        out.append(
            _equip(o, wearer, "off_hand", _int((off or {}).get("item_level")), said)
        )
    return out


def choose(wearer: Wearer, worn, carried, book=None) -> tuple:
    """The carried pieces this member should put on now, best per slot.

    `worn` rows carry `equipment_slot` (bag 0, slot 0..18); `carried` rows are
    the member's own bags. Both carry the item_template columns
    `gearscore.stats_from_row` reads and the usability columns `refusal`
    reads. Weapon rows come first within a member (the main hand before the
    off hand), so the core is asked in an order it can carry out.
    """
    worn = list(worn or ())
    carried = [r for r in carried or () if _int(r.get("inventory_type"))]
    out = _hands(wearer, worn, carried, book)
    out += _singles(wearer, worn, carried, book)
    out += _pairs(wearer, worn, carried, book)
    return tuple(out)


def waiting_on_skill(wearer: Wearer, worn, carried, book=None) -> tuple:
    """Carried weapons that would be worn but for a proficiency not yet
    learned: (row, skill line) for each, best first. What the weapon-skill pass
    could take to a weapon master."""
    skilled = []
    for row in carried or ():
        if _int(row.get("item_class")) != ITEM_CLASS_WEAPON or not waits_on_skill(
            row, wearer
        ):
            continue
        skilled.append(row)
    if not skilled:
        return ()
    taught = Wearer(
        **{
            **wearer.__dict__,
            "skills": wearer.skills | {skill_needed(r) for r in skilled},
        }
    )
    picks = {e.guid for e in choose(taught, worn, list(carried or ()), book)}
    return tuple(
        (row, skill_needed(row))
        for row in skilled
        if _int(row.get("item_guid")) in picks
    )


# --- the pass ------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """What one equip pass asks for.

    `equips` are the rows to write, members in name order and each member's
    weapon rows first. `waiting` is (member, item name, skill line) for each
    carried weapon held back only by a weapon skill. `scored` names the
    members judged here; the rest kept the item-level judge's picks.
    """

    equips: tuple = ()
    waiting: tuple = ()
    scored: frozenset = frozenset()


def _is_worn(row: dict) -> bool:
    slot = row.get("equipment_slot")
    return slot is not None and 0 <= _int(slot, -1) < 19


def plan(
    legacy, wearer_rows, gear_rows, names, keep_names=(), tanks=(), book=None
) -> Plan:
    """The scored picks for every member this can judge, the item-level
    judge's `legacy` picks for the rest.

    `wearer_rows` are member rows for `wearer_from_row`; `gear_rows` are worn
    (`equipment_slot` 0..18) and carried rows for `choose`, each naming its
    `holder`. A member is judged here when its row names a class with gear
    lists (`gearupgrades.choose_spec`); a carried piece the owner marked
    never-dispose (`bag_pressure.owner_keeps`) is left in the bags.
    """
    wanted = {str(n) for n in names or ()}
    wearers = {}
    for row in wearer_rows or ():
        if str(row.get("name") or "") not in wanted:
            continue
        wearer = wearer_from_row(row, tanks)
        if wearer is not None and wearer.spec:
            wearers[wearer.name] = wearer
    worn: dict = {}
    carried: dict = {}
    for row in gear_rows or ():
        holder = str(row.get("holder") or "")
        if holder not in wearers:
            continue
        if _is_worn(row):
            worn.setdefault(holder, []).append(row)
        elif not bag_pressure.owner_keeps(str(row.get("name") or ""), keep_names):
            carried.setdefault(holder, []).append(row)
    out = [e for e in legacy or () if e.holder not in wearers]
    waiting = []
    for name in sorted(wearers):
        wearer = wearers[name]
        out.extend(choose(wearer, worn.get(name, ()), carried.get(name, ()), book))
        for row, skill in waiting_on_skill(
            wearer, worn.get(name, ()), carried.get(name, ()), book
        ):
            waiting.append((name, str(row.get("name") or ""), skill))
    # Members in name order; the sort is stable, so each member keeps the
    # order `choose` gave its rows (weapons first, main hand before off hand).
    out.sort(key=lambda e: e.holder)
    return Plan(equips=tuple(out), waiting=tuple(waiting), scored=frozenset(wearers))
