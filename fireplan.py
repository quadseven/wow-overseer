"""The fire resistance plan for the raid's tanks and healers (#759).

WHY THIS EXISTS. raidsupply sets a fire resistance target per seat (the main
tank 200, every other tank 120, a healer 60) and the guild made one piece,
Wizardweave Leggings, which only cloth wearers can use. The tank fire sets in
`data/bis/situational.json` were read by nothing, so a tank reached level 60
wearing whatever fire resistance dropped by chance. This module reads those
sets and names, per seat, the next piece that closes the gap and where it
comes from, so the Raid tab and the bridge log say it, and so the dungeon
planner (preraid) can count a run that drops one for a family tank.

WHAT IT READS. Two committed files, both under `data/bis/`:

  situational.json  `tank_fire_resistance.sets`: per class (warrior, druid)
                    and phase (pre-raid, post-raid), one list of item ids a
                    slot. `fire_resistance_by_slot.slots`: every uncommon or
                    better piece with 10 or more fire resistance at required
                    level 50 to 60, with its fire resistance and armour type.
  items.json        each listed item's name, fire resistance, required level
                    and sources (dungeon, raid, craft, quest, ...).

WHO WEARS WHICH SET. A warrior, a paladin and a death knight wear the warrior
(plate) set; a druid the druid set. A tank of any other class, and every
healer, plans from the by-slot list, filtered to the armour its class wears at
level 60 (a back is cloth for everybody; a neck, ring, trinket or held off
hand is no armour type at all).

WHICH PIECE IS NEXT. The pre-raid set first, because it drops in the level 52
to 60 dungeons and the leatherworking and blacksmithing trades make it; the
post-raid set once the pre-raid set has nothing left to give. Within that, the
piece that adds the most fire resistance over what the seat wears in its slot
(the weaker of a pair of rings or trinkets). For the by-slot list a piece whose
source the item book knows comes before one it does not, since a piece with no
known road is no plan.

THE DARK IRON ROAD (#480). The blacksmith pieces on that list have a road of
their own, set out at the foot of this file: Thorium Brotherhood reputation,
Lokhtos's plans, the smelt, the Black Forge and the Black Anvil.

PURE MODULE: committed data and rows in, a plan and sentences out.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import gearscore

# THE TARGETS, PER SEAT. The Ragnaros tank first, as classic guilds asked
# (raidgoals' own range tops out at the same 200); other tanks next, because
# one of them takes over when the first dies; healers second. A convention,
# as raidsupply says of its own numbers: Molten Core gates nobody on it.
MAIN_TANK = "main tank"
TANK = "tank"
HEALER = "healer"
FIRE_TARGET = {MAIN_TANK: 200, TANK: 120, HEALER: 60}

WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST = 1, 2, 3, 4, 5
DEATH_KNIGHT, SHAMAN, MAGE, WARLOCK, DRUID = 6, 7, 8, 9, 11

# The tank set a class wears (situational.json `tank_fire_resistance.sets`).
SET_OF_CLASS = {
    WARRIOR: "warrior",
    PALADIN: "warrior",
    DEATH_KNIGHT: "warrior",
    DRUID: "druid",
}
PHASES = ("pre-raid", "post-raid")

# The heaviest armour a class wears at level 60 (item_template subclass:
# 1 cloth, 2 leather, 3 mail, 4 plate).
CLOTH, LEATHER, MAIL, PLATE = 1, 2, 3, 4
ARMOUR_OF_CLASS = {
    WARRIOR: PLATE,
    PALADIN: PLATE,
    DEATH_KNIGHT: PLATE,
    HUNTER: MAIL,
    SHAMAN: MAIL,
    ROGUE: LEATHER,
    DRUID: LEATHER,
    PRIEST: CLOTH,
    MAGE: CLOTH,
    WARLOCK: CLOTH,
}
ARMOUR = 4  # item_template class
MISC = 0  # armour subclass: neck, ring, trinket, held in the off hand

# The situational slot names, as equipment slots (EQUIPMENT_SLOT_*).
SLOTS = {
    "head": (0,),
    "neck": (1,),
    "shoulders": (2,),
    "chest": (4,),
    "waist": (5,),
    "legs": (6,),
    "feet": (7,),
    "wrist": (8,),
    "hands": (9,),
    "finger": (10, 11),
    "trinket": (12, 13),
    "back": (14,),
    "main_hand": (15,),
    "off_hand": (16,),
    "ranged": (17,),
}

# Source kinds in the order a reader cares about: what a run or a trade gets.
_KIND_ORDER = ("dungeon", "craft", "quest", "raid", "chest", "world_drop")
NO_SOURCE = "no source in the item book"


@dataclass(frozen=True)
class Piece:
    """One fire resistance piece a seat could plan for."""

    entry: int
    name: str
    fire: int
    slot: str  # the situational slot name
    required_level: int = 0
    source: str = NO_SOURCE
    phase: str = ""  # the tank set phase, "" for the by-slot list

    @property
    def known(self) -> bool:
        return self.source != NO_SOURCE


@dataclass(frozen=True)
class Next:
    """The next piece for one seat: which, in which slot, and what it adds."""

    piece: Piece
    slot: int  # the equipment slot it replaces
    gain: int  # fire resistance over what the seat wears there

    @property
    def said(self) -> str:
        return "%s (%s, +%d fire resistance; %s)" % (
            self.piece.name,
            self.piece.slot.replace("_", " "),
            self.gain,
            self.piece.source,
        )


@dataclass(frozen=True)
class FirePlan:
    """One seat's fire resistance plan: the target, the worn total, and the
    next piece that closes the gap (None when nothing planned adds to it)."""

    name: str
    seat: str  # main tank, tank or healer
    target: int
    worn: int
    next: Next | None

    @property
    def short(self) -> int:
        return max(0, self.target - self.worn)

    @property
    def line(self) -> str:
        head = "%s (%s) %d/%d" % (self.name, self.seat, self.worn, self.target)
        if not self.short:
            return head + ", at target"
        if self.next is None:
            return head + ", no planned piece adds to it"
        return "%s, next %s" % (head, self.next.said)


def _source(sources) -> str:
    """Where a piece comes from, said, from items.json `sources`."""
    found: dict = {}
    for src in sources or ():
        kind = str(src.get("type") or "")
        if kind == "dungeon" or kind == "raid":
            what = str(src.get("instance") or "")
        elif kind == "craft":
            what = " ".join(
                str(p) for p in (src.get("profession"), src.get("skill")) if p
            )
        elif kind == "quest":
            what = "quest %d" % int(src.get("quest") or 0)
        else:
            what = ""
        names = found.setdefault(kind, [])
        if what and what not in names:
            names.append(what)
    words = {
        "dungeon": "drops in",
        "raid": "drops in",
        "craft": "made by",
        "quest": "reward of",
        "chest": "a chest",
        "world_drop": "a world drop",
    }
    out = []
    for kind in sorted(
        found,
        key=lambda k: _KIND_ORDER.index(k) if k in _KIND_ORDER else len(_KIND_ORDER),
    ):
        if kind not in words:
            continue
        names = found[kind]
        out.append(("%s %s" % (words[kind], " and ".join(names))).strip())
    return "; ".join(out) or NO_SOURCE


def _piece(entry, slot: str, phase: str = "", row: dict | None = None) -> Piece:
    """A Piece for `entry`, named and sourced from items.json; `row` is the
    by-slot list's own row, which carries the fire resistance when the item
    book has no entry for it."""
    book = gearscore.load_item_book().get(str(int(entry))) or {}
    row = row or {}
    return Piece(
        entry=int(entry),
        name=str(book.get("name") or "item %d" % int(entry)),
        fire=int(book.get("fire_res") or row.get("fire_res") or 0),
        slot=slot,
        required_level=int(book.get("req") or row.get("req") or 0),
        source=iron_source(entry) or _source(book.get("sources")),
        phase=phase,
    )


@functools.lru_cache(maxsize=None)
def tank_pieces(class_id: int) -> tuple:
    """The class's tank fire set, pre-raid first, as Pieces with fire
    resistance on them; () for a class with no set."""
    name = SET_OF_CLASS.get(int(class_id or 0))
    if name is None:
        return ()
    sets = gearscore.load_situational()["tank_fire_resistance"]["sets"]
    out = []
    for phase in PHASES:
        for slot, entries in (sets.get("%s_%s" % (name, phase)) or {}).items():
            if slot not in SLOTS:
                continue
            for entry in entries:
                piece = _piece(entry, slot, phase)
                if piece.fire > 0:
                    out.append(piece)
    return tuple(out)


def wears(row: dict, class_id: int) -> bool:
    """Whether a class wears a by-slot row's piece at level 60."""
    if int(row.get("item_class") or 0) != ARMOUR:
        return False
    sub = int(row.get("item_subclass") or 0)
    if sub == MISC:
        return True
    heaviest = ARMOUR_OF_CLASS.get(int(class_id or 0))
    return heaviest is not None and sub == heaviest


@functools.lru_cache(maxsize=None)
def slot_pieces(class_id: int) -> tuple:
    """Every by-slot fire resistance piece the class wears, as Pieces.
    A back is cloth, which every class wears."""
    slots = gearscore.load_situational()["fire_resistance_by_slot"]["slots"]
    out = []
    for slot, rows in slots.items():
        if slot not in SLOTS:
            continue
        for row in rows or ():
            if slot == "back" or wears(row, class_id):
                out.append(_piece(row["id"], slot, "", row))
    return tuple(out)


def pieces_for(seat: str, class_id: int) -> tuple:
    """The pieces a seat plans from: its class's tank set for a tank that has
    one, else the by-slot list for its armour."""
    if seat in (TANK, MAIN_TANK):
        found = tank_pieces(class_id)
        if found:
            return found
    return slot_pieces(class_id)


def planned_entries(seat: str, class_id: int) -> frozenset:
    """The item entries a seat's plan names, for the dungeon planner."""
    return frozenset(p.entry for p in pieces_for(seat, class_id))


def _worn_in(slot_fire, slots: tuple) -> tuple:
    """(equipment slot, fire worn there) a piece for `slots` would replace:
    the weaker of a pair."""
    return min(((s, int(slot_fire(s))) for s in slots), key=lambda sf: sf[1])


def next_piece(pieces, slot_fire, level: int = 0) -> Next | None:
    """The next piece out of `pieces` (in plan order) for a seat whose worn
    fire resistance per equipment slot is `slot_fire(slot)`; None when no
    piece adds any. `level`, when known, leaves out a piece the seat cannot
    wear yet.

    The first phase that still adds anything is the one planned (the pre-raid
    set before the post-raid one); within it a piece with a known source
    first, then the biggest gain, then plan order.
    """
    best = None
    for order, piece in enumerate(pieces or ()):
        if level and piece.required_level > level:
            continue
        slot, worn = _worn_in(slot_fire, SLOTS[piece.slot])
        gain = piece.fire - worn
        if gain <= 0:
            continue
        phase = PHASES.index(piece.phase) if piece.phase in PHASES else 0
        key = (phase, not piece.known, -gain, order)
        if best is None or key < best[0]:
            best = (key, Next(piece, slot, gain))
    return None if best is None else best[1]


def plan(name: str, seat: str, class_id: int, worn_fire, level: int = 0) -> FirePlan:
    """One seat's FirePlan. `worn_fire` is ((equipment slot, fire resistance),
    ...) off the worn items, as raidsupply.Raider carries it."""
    worn = tuple((int(s), int(f)) for s, f in worn_fire or ())

    def slot_fire(slot: int) -> int:
        return sum(f for s, f in worn if s == slot)

    total = sum(f for _s, f in worn)
    target = FIRE_TARGET.get(seat, 0)
    nxt = None
    if total < target:
        nxt = next_piece(pieces_for(seat, class_id), slot_fire, level)
    return FirePlan(name, seat, target, total, nxt)


# ---------------------------------------------------------------------------
# THE DARK IRON ROAD (#480)
#
# Nothing on this road fails loudly in the world. A plan bought a rank early is
# simply absent from the vendor's list; a smelt cast at an ordinary forge
# returns a numeric SpellCastResult and no bar; a craft at the wrong anvil does
# the same. The order is the whole pipeline, so the order is what is modelled:
# reputation, the plan, the smelt, the bars, the reagents, the anvil.
#
# The item book gives these crafts skill 315 and 320; the classic cap is 300.
# `skill_note` says so rather than trusting the number: the realm's own
# item_template is the authority, and the ranks, plan ids and bar costs below
# are to be confirmed against it before a bot spends gold on them.
# ---------------------------------------------------------------------------

CLASSIC_SKILL = 300
NEUTRAL, FRIENDLY, HONORED, REVERED, EXALTED = (
    "Neutral",
    "Friendly",
    "Honored",
    "Revered",
    "Exalted",
)
# Thorium Brotherhood points at which each rank starts.
RANK_VALUE = {NEUTRAL: 0, FRIENDLY: 3000, HONORED: 9000, REVERED: 21000, EXALTED: 42000}
_RANKS = tuple(RANK_VALUE)

DARK_IRON_ORE, DARK_IRON_BAR = 11370, 11371
FIERY_CORE, LAVA_CORE, CORE_LEATHER = 17010, 17011, 17012
BLOOD_OF_THE_MOUNTAIN = 11382
ITEM_NAMES = {
    DARK_IRON_ORE: "Dark Iron Ore",
    DARK_IRON_BAR: "Dark Iron Bar",
    FIERY_CORE: "Fiery Core",
    LAVA_CORE: "Lava Core",
    CORE_LEATHER: "Core Leather",
    BLOOD_OF_THE_MOUNTAIN: "Blood of the Mountain",
}
ORE_PER_BAR = 8

# The turn-in quests that raise the reputation: (quest, ((item, count), ...)).
TURNINS = (
    (6642, ((DARK_IRON_ORE, 10),)),
    (6643, ((FIERY_CORE, 1),)),
    (6644, ((LAVA_CORE, 1),)),
    (6645, ((CORE_LEATHER, 2),)),
    (6646, ((BLOOD_OF_THE_MOUNTAIN, 1),)),
)

GRIND, BUY, LEARN, SMELT, GATHER, CRAFT = (
    "grind",
    "buy",
    "learn",
    "smelt",
    "gather",
    "craft",
)
VENDOR = "Lokhtos Darkbargainer"
FORGE = "the Black Forge in Blackrock Depths"
ANVIL = "the Black Anvil in Blackrock Depths"
SMELT_TRAINER = "The Spectral Chalice (Mining 230, with a Star Ruby)"


@dataclass(frozen=True)
class IronPlan:
    """One Dark Iron plan, the piece it makes and what the piece costs."""

    entry: int
    name: str
    rank: str
    piece: int
    piece_name: str
    fire: int
    teaches: int
    bars: int
    reagents: tuple  # ((item, count), ...) besides the bars


def _iron(entry, rank, piece, piece_name, fire, teaches, bars, reagents):
    return IronPlan(
        entry, "Plans: " + piece_name, rank, piece, piece_name, fire, teaches,
        bars, reagents,
    )  # fmt: skip


PLANS = (
    _iron(17051, FRIENDLY, 17014, "Dark Iron Bracers", 18, 20874, 4,
          ((FIERY_CORE, 2), (LAVA_CORE, 2))),
    _iron(19206, HONORED, 19148, "Dark Iron Helm", 35, 23636, 6,
          ((FIERY_CORE, 4), (LAVA_CORE, 4))),
    _iron(19207, HONORED, 19164, "Dark Iron Gauntlets", 28, 23637, 6,
          ((FIERY_CORE, 3), (LAVA_CORE, 3))),
    _iron(17060, REVERED, 17013, "Dark Iron Leggings", 30, 20876, 8,
          ((FIERY_CORE, 4), (LAVA_CORE, 4))),
    _iron(20040, EXALTED, 20039, "Dark Iron Boots", 28, 24399, 6,
          ((FIERY_CORE, 3), (LAVA_CORE, 3))),
)  # fmt: skip
_PIECES = {p.piece: p for p in PLANS}


def rank_index(rank: str) -> int:
    return _RANKS.index(rank)


@dataclass(frozen=True)
class IronStep:
    kind: str
    said: str
    plan: IronPlan | None = None


@dataclass(frozen=True)
class IronPipeline:
    plan: IronPlan | None
    step: IronStep | None

    @property
    def done(self) -> bool:
        return self.plan is None

    @property
    def line(self) -> str:
        if self.step is None:
            return "Dark Iron: every piece is made"
        return "Dark Iron: " + self.step.said


def skill_note() -> str:
    """Why the item book's skill numbers are not trusted."""
    return (
        "the item book gives these crafts skill 315 and 320 but the classic "
        "cap is %d; the realm's item_template is the authority" % CLASSIC_SKILL
    )


def _count(item: int, n: int) -> str:
    return "%d %s" % (n, ITEM_NAMES[item])


def _missing(plan: IronPlan, held: dict) -> tuple:
    return tuple(
        (item, need - held.get(item, 0))
        for item, need in plan.reagents
        if held.get(item, 0) < need
    )


def _grind_step(plan: IronPlan) -> IronStep:
    quests = ", ".join(_count(*needs[0]) for _q, needs in TURNINS)
    said = "raise Thorium Brotherhood to %s with %s's turn-ins (%s) to buy %s" % (
        plan.rank,
        VENDOR,
        quests,
        plan.name,
    )
    return IronStep(GRIND, said, plan)


def _buy_step(plan: IronPlan) -> IronStep:
    said = "buy %s from %s, who sells it at %s" % (plan.name, VENDOR, plan.rank)
    return IronStep(BUY, said, plan)


def _learn_step(plan: IronPlan) -> IronStep:
    said = "learn the Dark Iron smelt from %s before %s" % (SMELT_TRAINER, plan.name)
    return IronStep(LEARN, said, plan)


def _bars_step(plan: IronPlan, short: int) -> IronStep:
    said = "smelt %s from %s at %s" % (
        _count(DARK_IRON_BAR, short) + "s",
        _count(DARK_IRON_ORE, short * ORE_PER_BAR),
        FORGE,
    )
    return IronStep(SMELT, said, plan)


def _gather_step(plan: IronPlan, missing: tuple) -> IronStep:
    said = "gather %s for %s" % (
        ", ".join(_count(i, n) for i, n in missing),
        plan.piece_name,
    )
    return IronStep(GATHER, said, plan)


def _craft_step(plan: IronPlan) -> IronStep:
    said = "make %s (%d fire resistance) at %s" % (plan.piece_name, plan.fire, ANVIL)
    return IronStep(CRAFT, said, plan)


def _step_for(plan, known, rank, smelt_known, held) -> IronStep:
    if plan.entry not in known:
        if rank_index(rank) < rank_index(plan.rank):
            return _grind_step(plan)
        return _buy_step(plan)
    if not smelt_known:
        return _learn_step(plan)
    short = plan.bars - held.get(DARK_IRON_BAR, 0)
    if short > 0:
        return _bars_step(plan, short)
    missing = _missing(plan, held)
    if missing:
        return _gather_step(plan, missing)
    return _craft_step(plan)


def iron_plan(known=(), rank=NEUTRAL, smelt_known=False, held=None, made=()):
    """The next step of the Dark Iron road for a guild that knows the plans
    `known`, stands at `rank`, has (or lacks) the smelt, holds the items in
    `held` ({entry: count}) and has made the pieces `made`."""
    plan = next((p for p in PLANS if p.piece not in made), None)
    if plan is None:
        return IronPipeline(None, None)
    step = _step_for(plan, set(known), rank, smelt_known, held or {})
    return IronPipeline(plan, step)


def iron_source(entry) -> str:
    """The road to the Dark Iron piece `entry`, said; "" for any other item."""
    plan = _PIECES.get(int(entry))
    if plan is None:
        return ""
    return "made at %s from %s, bought from %s at %s with the Thorium Brotherhood" % (
        ANVIL,
        plan.name,
        VENDOR,
        plan.rank,
    )


IRON_ROAD = (
    "Dark Iron plate (blacksmithing): reputation with the Thorium Brotherhood "
    "for Lokhtos's plans, the smelt for Dark Iron bars at the Black Forge, and "
    "the piece made at the Black Anvil; first step for a guild with nothing yet: "
    + iron_plan().line
    + "; "
    + skill_note()
)
