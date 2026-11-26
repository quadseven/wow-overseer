"""A member carrying a weapon it has no skill for learns it at a weapon master.

WHY (wow-overseer#399). Measured on the dev realm on 2026-09-28: the level 35
mage carried a Silithid Ripper, a one-handed sword of item level 36, with no
Swords skill, and wore no main hand at all; the level 38 warrior carried a
Ravenwood Bow with no Bows skill and an empty ranged slot. The gear planners
treat a weapon as usable only when its skill is already held, which is right
for equipping, and nothing asked the next question a player asks: would a few
silver at a weapon master let me wield what I already carry?

THE PLAYER'S WAY. The family walks to a weapon master of its own side on the
leader's map (the leader's ordinary travel aim), each member that needs a
skill buys it with its own gold (mod-overseer's `train-weapon skill:<id>`,
which goes through the trainer and takes the money), and then puts the weapon
on (`e Hitem:<entry>:0`). Nothing is granted.

WeaponSkillPass coordinates the family's training. Its adapter supplies the
realm reads and writes, the town errand lock, and the travel claim.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol

import townerrand
import travel

if TYPE_CHECKING:
    import guildcorps
    import guildjobs
    from townslot import Cohort, Slot

log = logging.getLogger("wow-overseer")

WEAPON_SKILL_CLAIMANT = "weapon master"

# item_template.class for weapons. Kept local so this decision module does not
# import gear.py and create a dependency cycle.
ITEM_CLASS_WEAPON = 2

# item_template.subclass for a weapon -> (SkillLine id, the trainer spell that
# teaches it). Wands are left out: no trainer sells them, the class has them.
WEAPON_SKILLS = {
    0: (44, 196),  # one-handed axes
    1: (172, 197),  # two-handed axes
    2: (45, 264),  # bows
    3: (46, 266),  # guns
    4: (54, 198),  # one-handed maces
    5: (160, 199),  # two-handed maces
    6: (229, 200),  # polearms
    7: (43, 201),  # one-handed swords
    8: (55, 202),  # two-handed swords
    10: (136, 227),  # staves
    13: (473, 15590),  # fist weapons
    15: (173, 1180),  # daggers
    16: (176, 2567),  # thrown
    18: (226, 5011),  # crossbows
}

# Which weapon types each class can ever learn, by class id and subclass, as
# the classic trainers teach them. A member is never walked to learn what its
# class cannot hold.
CLASS_WEAPONS = {
    1: {0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 15, 16, 18},  # warrior
    2: {0, 1, 4, 5, 6, 7, 8},  # paladin
    3: {0, 1, 2, 3, 6, 7, 8, 10, 13, 15, 16, 18},  # hunter
    4: {2, 3, 4, 7, 13, 15, 16, 18},  # rogue
    5: {4, 10, 15},  # priest
    7: {0, 1, 4, 5, 10, 13, 15},  # shaman
    8: {7, 10, 15},  # mage
    9: {7, 10, 15},  # warlock
    11: {4, 5, 6, 10, 13, 15},  # druid
}

# WHAT THE BOT'S OWN EQUIP NEVER DOES (#830). Measured on the dev realm over
# two days: `e` put on 0 of 11 melee weapons asked of hunters, though each held
# the skill line and the piece was a clear upgrade; their bots keep the weapon
# they were made with. Every path that would write that `e` row, or walk a
# hunter to a weapon master for it, asks this one rule. A hunter's ranged
# weapon (InventoryType 15, 25, 26) is never refused here.
HUNTER = 3
MELEE_INVENTORY_TYPES = frozenset({13, 17, 21, 22})


def bot_wont_wear(class_id, item_class, inventory_type) -> bool:
    """True when the member's bot will not put this piece on, whatever the
    numbers say: today, a hunter and any melee weapon."""
    try:
        cls, item, inv = int(class_id), int(item_class), int(inventory_type)
    except (TypeError, ValueError):
        return False
    return cls == HUNTER and item == ITEM_CLASS_WEAPON and inv in MELEE_INVENTORY_TYPES


# InventoryType -> the slot the weapon goes in. Off-hand weapons are left to
# the dual-wield rule in gearup; this is about the main hand and the ranged slot.
WEAPON_SLOT = {13: "mainhand", 17: "mainhand", 21: "mainhand", 15: "ranged",
               25: "ranged", 26: "ranged"}  # fmt: skip

# Weapon masters by faction template: which side each one serves. Read off
# acore_world on 2026-09-28 (creature_template.subname = 'Weapon Master').
MASTER_TEAM = {
    12: "alliance", 55: "alliance", 80: "alliance",
    29: "horde", 68: "horde", 104: "horde", 876: "horde",
}  # fmt: skip

# Keep a margin inside the core's five-yard trainer gate: these are snapshot
# and spawn coordinates, not the live NPC's position or interaction geometry.
IN_REACH_YARDS = 4.0

TRAIN_SOURCE = "gear:weapon-skill"


@dataclass(frozen=True)
class Need:
    """One member, one weapon it carries, and the skill that would let it."""

    name: str
    skill: int
    spell: int
    entry: int
    item: str
    slot: str
    why: str

    @property
    def train_command(self) -> str:
        return "train-weapon skill:%d" % self.skill

    @property
    def equip_command(self) -> str:
        return "e Hitem:%d:0" % self.entry

    @property
    def fills_empty(self) -> bool:
        """The weapon would go in a slot that holds nothing now."""
        return self.why == "its %s is empty" % self.slot


# A GUILD MEMBER'S TRIP (#793). The family walks with its leader (above); a
# guild member outside the family walks alone, as its own guild job: to the
# weapon master's spawn, then `train-weapon`, then the guild equip pass puts the
# weapon on once the skill reads learned. On the dev realm on 2026-10-18 each
# guild's equip pass logged 10 to 11 carried weapon upgrades that "wait on a
# weapon skill a weapon master teaches", pass after pass, because only the
# family's pass ever walked anyone to one.


@dataclass(frozen=True)
class Offer:
    """One guild member's weapon-master trip: the need, and the master's spawn
    (0 when no master of its side teaches the skill on its map or across the
    water). A map_id other than the member's is a master across the water
    (choose_far_master): the member crosses first."""

    need: Need
    spawn: int = 0
    map_id: int = 0
    x: float = 0.0
    y: float = 0.0
    master: str = ""
    cost: int = 0


def offer(need, master) -> Offer:
    """The Offer for `need` at `master` (a choose_master row that carries the
    spawn guid and the trainer's MoneyCost); a master-less Offer when `master`
    is empty or names no spawn."""
    try:
        spawn = int((master or {}).get("spawn") or 0)
        if not spawn:
            return Offer(need)
        return Offer(
            need,
            spawn,
            int(master["map_id"]),
            float(master["x"]),
            float(master["y"]),
            str(master.get("name") or ""),
            int(master.get("cost") or 0),
        )
    except (KeyError, TypeError, ValueError):
        return Offer(need)


def may_need(class_id, level, carried) -> bool:
    """Could one of `carried` (guildjobs.Carried) make a Need, before the
    skills are read: a main hand or ranged weapon its class can learn, at its
    level. Keeps the skill and bag reads to members who carry one."""
    try:
        cls, lvl = int(class_id), int(level)
    except (TypeError, ValueError):
        return False
    learnable = CLASS_WEAPONS.get(cls, set())
    for item in carried or ():
        try:
            if int(item.item_class) != ITEM_CLASS_WEAPON:
                continue
            sub = int(item.subclass)
            if sub not in learnable:
                continue
            inv = int(item.inventory_type)
            if inv not in WEAPON_SLOT:
                continue
            if int(item.required_level) > lvl:
                continue
            # Hunters do not walk to train melee weapons
            if cls == HUNTER and inv in MELEE_INVENTORY_TYPES:
                continue
        except (AttributeError, TypeError, ValueError):
            continue
        if not bot_wont_wear(cls, ITEM_CLASS_WEAPON, inv):
            return True
    return False


def needs(facts: dict, bag_rows) -> list:
    """The best untrained weapon upgrade per member, sorted by name.

    `facts` is bridge._fetch_gearup_facts (class name, level, `equipped` slot
    -> item level or a worn-item mapping with `item_level`, and
    `skills.weapons` subclasses held). `bag_rows` are carried
    weapons: name, entry, label, subclass, InventoryType, ItemLevel,
    RequiredLevel, AllowableClass. An upgrade fills an empty slot or beats the
    worn piece's item level.
    """
    best: dict = {}
    for row in bag_rows or ():
        name = str(row.get("name") or "")
        need = _need(name, (facts or {}).get(name), row)
        if need is None:
            continue
        item_level = int(row.get("ItemLevel") or 0)
        if name not in best or item_level > best[name][0]:
            best[name] = (item_level, need)
    return [need for _level, need in (best[n] for n in sorted(best))]


def _class_id(fact) -> int:
    from gearup import CLASS_IDS

    return CLASS_IDS.get(str(fact.get("class") or "").lower(), 0)


def _learnable(fact, row) -> bool:
    """Its class can learn the type, it lacks the skill, and it can wear it."""
    cls_id = _class_id(fact)
    sub = row.get("subclass")
    sub = int(sub) if sub is not None else -1
    held = set((fact.get("skills") or {}).get("weapons") or ())
    if sub not in WEAPON_SKILLS or sub in held:
        return False
    if sub not in CLASS_WEAPONS.get(cls_id, set()):
        return False
    if int(row.get("RequiredLevel") or 0) > int(fact.get("level") or 0):
        return False
    # The skill would buy nothing: the bot never wears the weapon (#830).
    if bot_wont_wear(cls_id, ITEM_CLASS_WEAPON, row.get("InventoryType") or 0):
        return False
    allowed = int(row.get("AllowableClass") or 0)
    return allowed in (-1, 0) or bool(allowed & (1 << (cls_id - 1)))


def _need(name, fact, row):
    """The Need this carried weapon makes for its holder, or None."""
    if not fact or not _learnable(fact, row):
        return None
    slot = WEAPON_SLOT.get(int(row.get("InventoryType") or 0))
    if not slot:
        return None
    equipped = fact.get("equipped") or {}
    item_level = int(row.get("ItemLevel") or 0)
    worn = equipped.get(slot)
    worn_level = worn.get("item_level") if isinstance(worn, dict) else worn
    if slot in equipped and worn_level is not None and item_level <= int(worn_level):
        return None
    skill, spell = WEAPON_SKILLS[int(row["subclass"])]
    why = (
        "its %s is empty" % slot
        if slot not in equipped
        else "item level %d over %s worn" % (item_level, worn_level)
    )
    return Need(
        name,
        skill,
        spell,
        int(row.get("entry") or 0),
        str(row.get("label") or ""),
        slot,
        why,
    )


# THE GROUND A WALK REACHES (#1585). Teldrassil, with Darnassus on it, stands
# on map 1 but off the Kalimdor mainland: it is reached only by the boat from
# Auberdine to Rut'theran Village, and a walk from the mainland to a master
# there ends at the shore without arriving. The pre-ship review of the bridge
# ship of 846499d8 found an Alliance member could be sent there from
# Auberdine. Each island is a box of zones.json (its continent's zone box:
# top/bottom bound x, left/right bound y); a master is walked to only on the
# ground the walker stands on, and never across the water to an island.
MAINLAND = ""
ISLANDS = {
    1: (("Teldrassil", 8437.5, 11831.25, -1277.083251953125, 3814.583251953125),),
}


def ground_of(map_id, x, y) -> str:
    """The island (ISLANDS) a point of `map_id` lies on, MAINLAND for any
    other point, and for one that cannot be read."""
    try:
        here, px, py = int(map_id), float(x), float(y)
    except (TypeError, ValueError):
        return MAINLAND
    for name, bottom, top, right, left in ISLANDS.get(here, ()):
        if bottom <= px <= top and right <= py <= left:
            return name
    return MAINLAND


def _best_master(masters, wanted, team, map_id, ground, yards) -> dict:
    """Of `masters` on `map_id`, of `team`'s side, standing on `ground` (None:
    any), the one that teaches the most of `wanted`, then the fewest `yards`
    (a function of the row). An entry keeps its spawn of fewest yards, and the
    row's `yards` is that number."""
    by: dict = {}
    for row in masters or ():
        try:
            if int(row["map_id"]) != int(map_id):
                continue
            if MASTER_TEAM.get(int(row["faction"])) != str(team or "").lower():
                continue
            spell = int(row["spell"])
            if spell not in wanted:
                continue
            if ground is not None and ground_of(map_id, row["x"], row["y"]) != ground:
                continue
            far = float(yards(row))
            entry = int(row["entry"])
        except (KeyError, TypeError, ValueError):
            continue
        seen = by.get(entry)
        spells = (seen["spells"] if seen else set()) | {spell}
        if seen is None or far < float(seen["yards"]):
            seen = dict(row, yards=far)
        seen["spells"] = spells
        by[entry] = seen
    if not by:
        return {}
    return min(
        by.values(),
        key=lambda r: (-len(r["spells"]), float(r["yards"]), int(r["entry"])),
    )


def choose_master(masters, wanted, team: str, map_id: int, at=None) -> dict:
    """The weapon master on `map_id`, of `team`'s side, that teaches the most
    of `wanted` (trainer spell ids), nearest first. {} when none.

    `masters` rows: entry, name, faction, map_id, x, y, yards, spell, and
    (bridge._WEAPON_MASTERS_SQL) the spawn guid and the spell's cost. The
    yards are from the walker, so an entry keeps its nearest spawn. With `at`
    (a snapshot reading: pos_x, pos_y) only a master on the walker's own
    ground (ground_of) is chosen: never one on an island across the water.
    """
    ground = None
    if at:
        ground = ground_of(map_id, at.get("pos_x"), at.get("pos_y"))
    return _best_master(
        masters, wanted, team, map_id, ground, lambda r: float(r["yards"])
    )


# A WEAPON MASTER ACROSS THE WATER (#793). Each side's masters do not all teach
# every skill, and they stand on both classic continents. When none teaches the
# skill on the member's map, select a classic master from the other classic
# continent, or from either classic continent for an Outland member. The module
# checks whether its transport catalogue has a route before carrying out the
# resulting `cross-to-map` row. Northrend has no far candidate here.
CLASSIC_CONTINENTS = (0, 1)
OUTLAND_MAP_ID = 530


def far_maps(map_id) -> list:
    """Classic continents to search for a weapon master away from `map_id`.

    A classic continent searches the other one. Outland searches both; the
    module decides whether its transport catalogue can reach the chosen map.
    Other maps have no far candidate.
    """
    try:
        here = int(map_id)
    except (TypeError, ValueError):
        return []
    if here == OUTLAND_MAP_ID:
        return list(CLASSIC_CONTINENTS)
    if here not in CLASSIC_CONTINENTS:
        return []
    return [m for m in CLASSIC_CONTINENTS if m != here]


# WHERE A CROSSING SETS THE MEMBER DOWN (#1585). The rows' yards are from the
# member on its own continent, so they rank nothing on the other one: the
# master across the water is chosen by its yards from the side's landings
# there. The module picks the boat or zeppelin by its own price, so each
# port a side's crossing may land at counts, and a master is ranked from the
# nearest of them. Each landing is the port's flight point (taxinodes.json
# node id, x, y): the berth itself is in no table here (crossing.py). Every
# landing is on the mainland, so a master on an island (ISLANDS) needs a
# second crossing nothing plans, and is never chosen.
LANDINGS = {
    ("alliance", 0): (
        (7, -3792.260009765625, -783.2899780273438),  # Menethil Harbor
        (19, -14473.0498046875, 464.1499938964844),  # Booty Bay
    ),
    ("alliance", 1): (
        (26, 6341.3798828125, 557.6799926757812),  # Auberdine
        (32, -3825.3701171875, -4516.580078125),  # Theramore
        (80, -894.5900268554688, -3773.010009765625),  # Ratchet
    ),
    ("horde", 0): (
        (11, 1568.6199951171875, 267.9700012207031),  # the Undercity
        (20, -12414.1796875, 146.2899932861328),  # Grom'gol
        (18, -14444.2900390625, 509.6199951171875),  # Booty Bay
    ),
    ("horde", 1): (
        (23, 1677.5899658203125, -4315.7099609375),  # Orgrimmar
        (80, -894.5900268554688, -3773.010009765625),  # Ratchet
    ),
}


def landing_yards(team, map_id, x, y) -> float:
    """Yards from (x, y) on `map_id` to the nearest landing of `team`'s
    crossing there (LANDINGS)."""
    points = LANDINGS.get((str(team or "").lower(), int(map_id)), ())
    if not points:
        raise ValueError("no landing of %r on map %r" % (team, map_id))
    return min(
        ((float(x) - lx) ** 2 + (float(y) - ly) ** 2) ** 0.5 for _node, lx, ly in points
    )


def choose_far_master(masters, wanted, team: str, map_id: int) -> dict:
    """The compatible far weapon master nearest the side's landing.

    A classic map searches its opposite continent; Outland searches both
    classic continents (far_maps). Other maps have no far candidate. Masters
    on `map_id` itself are choose_master's, never this one's.
    """
    chosen: dict = {}
    for there in far_maps(map_id):
        got = _best_master(
            masters,
            wanted,
            team,
            there,
            MAINLAND,
            lambda r, there=there: landing_yards(team, there, r["x"], r["y"]),
        )
        if got and (not chosen or len(got["spells"]) > len(chosen["spells"])):
            chosen = got
    return chosen


def in_reach(master: dict, at: dict, yards: float = IN_REACH_YARDS) -> bool:
    """Is a snapshot reading within `yards` of the master's spawn."""
    if not master or not at:
        return False
    try:
        if int(at["map_id"]) != int(master["map_id"]):
            return False
        dx = float(at["pos_x"]) - float(master["x"])
        dy = float(at["pos_y"]) - float(master["y"])
    except (KeyError, TypeError, ValueError):
        return False
    return dx * dx + dy * dy <= float(yards) ** 2


def _learned_weapon_times(rows):
    """Most recent learning time for each character and weapon subclass."""
    subclass_by_skill = {
        skill: subclass for subclass, (skill, _spell) in WEAPON_SKILLS.items()
    }
    learned_at = {}
    for row in rows or ():
        try:
            key = (str(row["name"]), subclass_by_skill[int(row["skill"])])
            learned = row["learned_at"]
        except (KeyError, TypeError, ValueError):
            continue
        if learned is not None and (key not in learned_at or learned > learned_at[key]):
            learned_at[key] = learned
    return learned_at


def _carried_weapon_commands(rows):
    """Map each carried weapon equip command to its trained skill subclass."""
    commands = {}
    for row in rows or ():
        try:
            item_class = int(row.get("item_class", row.get("class")))
            name = str(row.get("holder") or row["name"])
            entry = int(row["entry"])
            subclass = int(row.get("item_subclass", row.get("subclass")))
        except (KeyError, TypeError, ValueError):
            continue
        if item_class == ITEM_CLASS_WEAPON and subclass in WEAPON_SKILLS:
            commands[(name, "e Hitem:%d:0" % entry)] = subclass
    return commands


def _was_blocked_by_unlearned_skill(attempt, commands, learned_at) -> bool:
    """Whether a resolved equip attempt predates learning its weapon skill."""
    try:
        key = (str(attempt["target_name"]), str(attempt["command"]))
        subclass = commands[key]
        learned = learned_at[(key[0], subclass)]
        created = attempt["created_at"]
        status = str(attempt["status"])
    except (KeyError, TypeError):
        return False
    return (
        status in {"delivered", "error"} and created is not None and created < learned
    )


def reopen_equip_attempts(history, learned, carried):
    """Retire resolved attempts made before a carried weapon's skill was learned.

    Pending and post-training attempts stay counted, so each eligible weapon
    gets one retry without resetting its give-up count on every pass.
    Returns `(remaining_history, reopened_attempts)`.
    """
    commands = _carried_weapon_commands(carried)
    learned_at = _learned_weapon_times(learned)
    remaining, reopened = [], []
    for attempt in history or ():
        if _was_blocked_by_unlearned_skill(attempt, commands, learned_at):
            reopened.append(attempt)
        else:
            remaining.append(attempt)
    return tuple(remaining), tuple(reopened)


@dataclass(frozen=True)
class WeaponSkillIO:
    """Existing synchronous realm operations and shared family lookups."""

    family_of: Callable[[Cohort | None], tuple[list[str], str]]
    family_label: Callable[[Cohort | None], str]
    cohort_key: Callable[[Cohort | None], str | None]
    gear_facts: Callable[[list[str]], dict]
    bag_weapons: Callable[[list[str]], list[dict]]
    positions: Callable[[list[str]], dict]
    teams: Callable[[list[str]], dict]
    masters: Callable[[dict, list[int], list[int]], list[dict]]
    crossings: Callable[[list[str]], tuple[guildjobs.Recent, ...]]
    errand_state: Callable[[list[str]], townerrand.State | None]
    train_asked: Callable[[Need], bool]
    insert_train: Callable[[Need], int]
    trains_applied: Callable[[list[str]], list[dict]]
    insert_equip: Callable[[dict], int]
    counter_yards: float


class WeaponSkillBridge(Protocol):
    """Bridge operations used by the weapon skill pass."""

    def _weapon_skill_io(self) -> WeaponSkillIO: ...
    def _town_errand_lock(self, names: list[str]) -> asyncio.Lock: ...
    async def _mid_run(self, names: list[str]) -> bool: ...
    def _cohort_town_slot(self, cohort: str | None) -> Slot: ...
    async def _town_errand_yield_for_weapon(
        self,
        state: townerrand.State,
        names: list[str],
        leader: str,
        slot: Slot,
        label: str,
    ) -> bool: ...
    async def _class_cross_row(
        self, step: guildcorps.Step, row: guildcorps.Row
    ) -> None: ...
    async def _claim_town_slot(
        self,
        claimant: str,
        character: str,
        aim: str,
        *,
        urgent: bool,
        cohort: str | None,
    ) -> bool: ...


class WeaponSkillPass:
    def __init__(self, bridge: WeaponSkillBridge) -> None:
        self._bridge = bridge

    async def run_once(self, cohort: Cohort | None = None) -> None:
        """Equip what was trained, train in reach, or walk the leader to the master."""
        io = self._bridge._weapon_skill_io()
        names, _leader = await asyncio.to_thread(io.family_of, cohort)
        if not names:
            return
        async with self._bridge._town_errand_lock(names):
            await self._run_locked(io, cohort)

    async def _run_locked(self, io: WeaponSkillIO, cohort: Cohort | None) -> None:
        names, leader = await asyncio.to_thread(io.family_of, cohort)
        if not names or not leader:
            return
        label = io.family_label(cohort)
        await self._weapon_skill_equip(io, names, label)
        if await self._bridge._mid_run(names):
            return
        facts = await asyncio.to_thread(io.gear_facts, names)
        wanted = needs(facts, await asyncio.to_thread(io.bag_weapons, names))
        if not wanted:
            return
        if not await self._town_errand_allows_training(
            io, cohort, names, leader, wanted, label
        ):
            return
        positions = await asyncio.to_thread(io.positions, list(names))
        at = positions.get(leader)
        if not at:
            return
        teams = await asyncio.to_thread(io.teams, [leader])
        spells = {n.spell for n in wanted}
        masters = await asyncio.to_thread(
            io.masters, at, sorted(spells), far_maps(at["map_id"])
        )
        master = choose_master(
            masters, spells, teams.get(leader, ""), int(at["map_id"]), at
        )
        said = "; ".join(
            "%s carries %s (%s) and has no skill %d for it"
            % (n.name, n.item, n.why, n.skill)
            for n in wanted
        )
        if not master:
            far = choose_far_master(
                masters, spells, teams.get(leader, ""), int(at["map_id"])
            )
            await self._cross_or_report_no_master(
                io, names, leader, at, wanted, far, said, label
            )
            return
        if await self._weapon_skill_train(io, wanted, master, positions, label):
            return
        await self._walk_to_weapon_master(io, cohort, leader, master, said, label)

    async def _town_errand_allows_training(
        self,
        io: WeaponSkillIO,
        cohort: Cohort | None,
        names: list[str],
        leader: str,
        wanted: list[Need],
        label: str,
    ) -> bool:
        critical = any(
            need.slot == "mainhand" and need.why == "its mainhand is empty"
            for need in wanted
        )
        state = io.errand_state(names)
        if state is None or not state.active:
            return True
        if not critical:
            return False
        slot = self._bridge._cohort_town_slot(io.cohort_key(cohort))
        return await self._bridge._town_errand_yield_for_weapon(
            state, names, leader, slot, label
        )

    async def _cross_or_report_no_master(
        self,
        io: WeaponSkillIO,
        names: list[str],
        leader: str,
        at: dict,
        wanted: list[Need],
        far: dict,
        said: str,
        label: str,
    ) -> None:
        if not far:
            log.info(
                "weapon skill: %s; no weapon master of the family's side "
                "on this map teaches it, so nobody walks%s",
                said,
                label,
            )
            return
        # The guild planner also imports weaponskill for its decisions.
        import guildjobs

        need = next(n for n in wanted if n.spell in far["spells"])
        step, note = guildjobs.weapon_cross_step(
            SimpleNamespace(name=leader, map_id=int(at["map_id"])),
            offer(need, far),
            await asyncio.to_thread(io.crossings, names),
        )
        if note:
            log.info("weapon skill: %s%s", note, label)
        if step:
            await self._bridge._class_cross_row(step, step.rows[0])

    async def _walk_to_weapon_master(
        self,
        io: WeaponSkillIO,
        cohort: Cohort | None,
        leader: str,
        master: dict,
        said: str,
        label: str,
    ) -> None:
        target = travel.resolve(str(int(master["entry"])))
        if not target:
            return
        aimed = await self._bridge._claim_town_slot(
            WEAPON_SKILL_CLAIMANT,
            leader,
            target,
            urgent=True,
            cohort=io.cohort_key(cohort),
        )
        log.info(
            "weapon skill: %s; %s is aimed at %s (%d yards) (aim taken=%s)%s",
            said,
            leader,
            master["name"],
            int(float(master["yards"])),
            aimed,
            label,
        )

    async def _weapon_skill_train(self, io, needs, master, positions, label) -> int:
        """Write a train row for each member standing at the master; how many."""
        written = 0
        for need in needs:
            if need.spell not in master["spells"]:
                continue
            # The snapshot-to-spawn distance is center-to-center; the core's
            # trainer interaction check also includes the creature's reach.
            # Use the existing town radius here and let the worldserver apply
            # the exact interaction gate before charging or teaching.
            if not in_reach(master, positions.get(need.name), io.counter_yards):
                continue
            if await asyncio.to_thread(io.train_asked, need):
                continue
            if await asyncio.to_thread(io.insert_train, need):
                written += 1
                log.info(
                    "weapon skill: %s buys skill %d at %s with its own gold, to wield %s%s",
                    need.name,
                    need.skill,
                    master["name"],
                    need.item,
                    label,
                )
        return written

    async def _weapon_skill_equip(self, io, names, label) -> None:
        """Put on each weapon whose skill row reads applied and not yet worn."""
        for row in await asyncio.to_thread(io.trains_applied, names):
            if await asyncio.to_thread(io.insert_equip, row):
                log.info(
                    "weapon skill: %s learned skill %s; puts on %s%s",
                    row["name"],
                    row["skill"],
                    row.get("item_name") or "an unnamed item (%s)" % row["entry"],
                    label,
                )
