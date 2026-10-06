"""Every class quest a guild member can do, and the next move toward it.

WHY THIS EXISTS. Measured on the dev realm on 2026-10-06: every Bonkers
warrior at level 14 or above (Bigzug, Chillmon, Dreadlox, Fleshless, Ghoulish,
Eyesocket) and three of Cave's (Durg, Hurk, Gronk) lacked Defensive Stance,
Taunt and Sunder Armor. Those spells are the reward of the warrior's level-10
class quest chain (reward spell 8121; the trainers of this realm do not teach
Defensive Stance: trainer_spell holds no row for spell 71). The members HELD
the quest (1498, 1819, 1678 at status 3 in character_queststatus) and never
finished it: nothing sent them to its objective, which is level 9-11 content,
and the leveling walk (guildlevel.py) took them past it to higher hubs. A
warrior that tanks the Deadmines in Battle Stance with no Taunt cannot hold
threat, and the party died in one pull, 0 of 46 clears at those doors.

WHAT A PLAYER DOES. Takes the class quest at its trainer as soon as the level
allows, does the objective, hands it in, and learns the spell. This is that
for one guild member, for every class: the next quest of the chain of every
class reward it lacks, as one move:

  take    walk to the quest giver, then `take quest:<id>`;
  hunt    walk to the creature spawn the objective names (the creature to kill,
          or the creature whose loot is the item), where the member's own grind
          and loot strategies work, as a skinner's field does;
  turnin  walk to the quest ender, then `turnin quest:<id>`.

WHAT IS READ, NOT WRITTEN HERE. The table is built from acore_world at run
time (QUESTS_SQL and its companions), never typed in: a quest is a class quest
when quest_template_addon.AllowableClasses names one class or its QuestSortID
is a class sort, and a reward quest when it grants a spell (RewardSpell or
RewardDisplaySpell). Its chain is the PrevQuestID links back to the first
quest. A member has a reward when it knows the spell or has been rewarded any
quest of the same class and reward.

WHAT IT REFUSES, WITH A NAMED BLOCKER (a member never waits in silence):
  group    a quest that suggests a group or whose objective is an elite: left
           for the ask path (guildsocial), named so here;
  object   an objective that needs a gameobject used and no spawn of it is on
           record, or one this worldserver cannot use yet;
  source   an item with no creature that drops it, no chest that holds it and
           no quest that hands it over, or no spawn row;
  item     a quest item the member must use and no longer carries;
  map      every giver or objective spawn is on another map than the member's:
           walk-to-spawn refuses a spawn on another map.
  level    every spawn of the objective is more than OVERLEVEL_MAX levels over
           the member: no pack is chosen that would kill it.

A HUNT LEAVES WHAT THE MODULE REFUSED. A spawn the module refused, or a walk to
which did not reach it (SPAWN_REFUSALS), is left for SPAWN_REFUSED_MINUTES and
the member goes to the next pack of the objective (guildjobs.class_avoid).

WHAT A PLAYER USES (quadseven/mod-overseer#865). Two verbs on kind='quest'
rows, written beside `take quest:` and `turnin quest:`:

  use-item-on creature:<entry> item:<entry>   a carried item used on a creature
  use-gameobject <entry>                      the nearest gameobject clicked

Both fire only when the member already stands beside the target, so a USE move
is a walk to the target's spawn and then the row, as a take is a walk and then
a row. They are read from the world, never typed in:

  item on a creature  an item the quest hands over (StartItem, ItemDrop1-4) or
                      requires, whose on-use spell (item_template.spellid_1,
                      spelltrigger_1 = 0) is bound by `conditions` (source type
                      17, condition 31, object type 3) to named creatures: the
                      hunter's Taming Rod and Taming Totem, a druid's Curative
                      Animal Salve;
  gameobject          a required item no creature drops that a chest holds
                      (gameobject_loot_template through a type 3
                      gameobject_template), and a negative RequiredNpcOrGo.

An item the quest hands over is carried after the take; any other item the
member must already hold, and one it does not is a named blocker (the class
step buys nothing). A worldserver that predates the verbs answers `malformed
request: want take quest:...` (classuse.py); the bridge then plans from
Book.plain(), the same book with no uses, and every use quest is named as it
was before. What the verbs do NOT cover stays blocked and named: an item cast
at nothing in particular, at a spell focus (the warlock's Summoning Circle, a
water source) or on a corpse nearby, and a creature a script summons.

PURE MODULE: rows in, a Move out. No MySQL, no clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

# The class a class QuestSortID names, and the class bit AllowableClasses holds.
CLASS_OF_SORT = {
    -81: 1,  # warrior
    -141: 2,  # paladin
    -261: 3,  # hunter
    -162: 4,  # rogue
    -262: 5,  # priest
    -82: 7,  # shaman
    -161: 8,  # mage
    -61: 9,  # warlock
    -263: 11,  # druid
}
CLASS_NAMES = {
    1: "warrior",
    2: "paladin",
    3: "hunter",
    4: "rogue",
    5: "priest",
    7: "shaman",
    8: "mage",
    9: "warlock",
    11: "druid",
}
# AllowableClasses is a bit mask: bit (class id - 1).
SINGLE_CLASS_MASKS = tuple(1 << (c - 1) for c in sorted(CLASS_NAMES))

WARRIOR = 1

# The classic range: a class quest is built for a member that can take it by
# this level. Beyond it (Outland and Northrend class quests) is another job.
MAX_QUEST_LEVEL = 45

# The core's QuestStatus values a character_queststatus row carries.
STATUS_COMPLETE, STATUS_INCOMPLETE = 1, 3

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "classquest"

# A member's plan line carries this while it works a class quest.
MARK = "class quest"

# Move kinds. USE writes a use-item-on or use-gameobject row at a target.
TAKE, HUNT, TURN_IN, USE, BLOCKED = "take", "hunt", "turnin", "use", "blocked"
# Blockers.
GROUP, OBJECT, SOURCE, MAP, UNKNOWN = "group", "object", "source", "map", "unknown"
# A quest item the member must use and does not carry.
ITEM = "item"
# A hunt that made no progress through every field it was sent to.
STALLED = "stalled"
# Every spawn of the objective is too many levels over the member to hunt.
LEVEL = "level"
# A use the world refused for good, or that changed nothing through every
# target it was sent to.
USE_STALLED = "usestalled"
# The blockers a guildmate can help with: the rest are the module's to fix.
HELPABLE = frozenset({GROUP, STALLED, USE_STALLED})

# The two verbs of kind='quest' (quadseven/mod-overseer#865).
USE_ITEM, USE_OBJECT = "use-item-on", "use-gameobject"
# A member this near its target (yards) is already beside it: the use row is
# written with no walk. The module's creature reach is 8 yards.
USE_NEAR = 4.0

# A GROUP-BLOCKED QUEST ASKS FOR THIS MANY HELPERS when the world data names no
# group size (an elite objective): the asker and two make a party of three.
ELITE_HELPERS = 2
MAX_HELPERS = 4

# THE HUNT'S CLOCK. A hunt that makes no progress (the quest's kill and item
# counts do not move) for HUNT_STALL_MINUTES is sent to another pack of the
# objective's spawns, at most MAX_REROLLS times; the last stall gives the quest
# up for GIVE_UP_MINUTES and the member asks guild chat for help instead
# (classask.py). The numbers come from the guild-step conventions in
# guildjobs.COOLDOWN_MINUTES: a farm or a door is asked of a member every 45
# minutes and a craft every 15, so a hunt is judged on 30 (a few respawn cycles
# of an ordinary creature, whose spawn time is 2 to 10 minutes, plus the walk,
# and under the 45 of a farm that would otherwise replace it). Three packs at
# 30 minutes is an hour and a half before the member gives the quest up, and
# 120 minutes is the cool-down the level walk and a sale use for a step that
# keeps failing, long enough that the member is not walked at the same quest
# every pass.
HUNT_STALL_MINUTES = 30
MAX_REROLLS = 2
GIVE_UP_MINUTES = 120
# Two walk rows in a row that ended in error or unchanged are a stall at once:
# the spawn cannot be reached.
FAILED_WALKS = 2

# NEVER A SPAWN WHOSE CREATURE IS MORE THAN THIS MANY LEVELS OVER THE MEMBER. On
# the dev realm on 2026-10-06 members walked to spawns and were killed on the
# way or at them (8 of 163 class quest walks ended "died on the way to the
# spawn"). Three is the module's own lethal gap: it holds a revived character
# out of combat on ground reaching three levels over it.
OVERLEVEL_MAX = 3

# A SPAWN THE MODULE REFUSED, OR THAT A WALK DID NOT REACH, IS NOT ASKED OF THE
# SAME MEMBER AGAIN FOR THIS LONG: the member is sent to the next pack of the
# objective instead (guildjobs.class_avoid). These are the module's refusals
# that say the spawn or the way to it is the trouble, in its own words
# (SpawnWalkRefusal): the first step goes over a drop, the way crosses the
# other side's ground, the ground does not hold, the walk stopped getting
# nearer, ran out of time or ended in the member's death, and the spawn is not
# in the world, on this map or in season. The words that name the member's
# state (dead, in combat, held, in flight, a far walk wall) are not here: they
# say nothing about the spawn. The time is GIVE_UP_MINUTES, the hold a hunt
# gets when it stalled through every pack, so a refused spawn and a stalled
# pack are left alone for as long.
SPAWN_REFUSED_MINUTES = 120
SPAWN_REFUSALS = frozenset(
    {
        "the first step toward the creature goes over a drop",
        "the way to the spawn crosses the other side's ground",
        "the ground toward the spawn does not hold",
        "stopped getting nearer the spawn",
        "did not reach the spawn in time",
        "died on the way to the spawn",
        "no such spawn in the world",
        "the spawn is on another map than the character",
        "the spawn belongs to a world event that is not running",
    }
)

# THE REALM'S FAR WALKS ARE FEW (mod-overseer's FarWalkBudgetGate: a handful
# under way at once on the whole realm, a couple of starts per bot per hour).
# A class quest walk the realm refuses for either wall is RETRYABLE: the wall
# moves, the member is not at fault and the spawn is not out of reach. The
# worldserver names the two walls in these words (FarWalkRefusal).
REALM_FULL_REASON = "the realm has as many far walks under way as it allows"
BOT_BUDGET_REASON = "this character has started as many far walks this hour as one may"
# A walk refused because another verb holds the character. The longest hold
# the module places is the one after a revival, 690 seconds; 32 of 163 class
# quest walks on 2026-10-06 were refused this way.
HELD_REASON = "character is held by another verb"
# HOW LONG A MEMBER IS LEFT ALONE AFTER EITHER REFUSAL. The realm wall: a far
# walk on the dev realm took 4 to 266 seconds to finish on 2026-10-06, so a slot
# frees within minutes; 15 minutes is three times the longest of those and more
# than the 10 minute cooldown any class row gets, so a refusal is asked again no
# sooner than a success would be. The member wall: a bot's starts leave the budget window one at a time
# over an hour, so asking sooner than half of it is another refusal; 30 minutes
# is also still inside the window of the oldest start, so no member waits more
# than the hour. Neither doubles: both are bounded by the wall's own clock.
REALM_FULL_BACKOFF_MINUTES = 15
BOT_BUDGET_BACKOFF_MINUTES = 30
# 690 seconds is 11.5 minutes: asked again at 12, the hold has lapsed.
HELD_BACKOFF_MINUTES = 12
BACKOFF_MINUTES = {
    REALM_FULL_REASON: REALM_FULL_BACKOFF_MINUTES,
    BOT_BUDGET_REASON: BOT_BUDGET_BACKOFF_MINUTES,
    HELD_REASON: HELD_BACKOFF_MINUTES,
}


class FarSlots:
    """The far walk slots the realm has free this pass, spent as a pass starts
    class quest walks so the bridge never writes more rows than the realm can
    take. `free` None means the count is unknown and nothing is held back."""

    def __init__(self, free=None):
        self.free = None if free is None else max(0, int(free))
        self.holders: set = set()

    def take(self, name) -> bool:
        """Spend one slot for `name`; False when none is left."""
        if name in self.holders:
            return True
        if self.free is not None:
            if self.free <= 0:
                return False
            self.free -= 1
        self.holders.add(name)
        return True

    def release(self, name) -> None:
        """Give back the slot `name` took, for a step the plan then refused."""
        if name in self.holders:
            self.holders.discard(name)
            if self.free is not None:
                self.free += 1


# A member this near its hunting ground is hunting; this near a giver is there.
HUNT_REACH = 400.0
# Spawns this close are one pack, for choosing the densest part of a field.
PACK_YARDS = 120.0
# A creature of this rank or above (elite, rare elite, boss) is a group kill.
ELITE_RANK = 1

_SORTS = ", ".join(str(s) for s in sorted(CLASS_OF_SORT))
_MASKS = ", ".join(str(m) for m in SINGLE_CLASS_MASKS)

_NPCS = "".join(
    "q.RequiredNpcOrGo%d AS npc%d, q.RequiredNpcOrGoCount%d AS npc_count%d, "
    % (i, i, i, i)
    for i in range(1, 5)
)
_ITEMS = "".join(
    "q.RequiredItemId%d AS item%d, q.RequiredItemCount%d AS item_count%d, "
    % (i, i, i, i)
    for i in range(1, 7)
)
# The items a quest hands over when it is taken: StartItem and ItemDrop1-4.
_PROVIDED = "q.StartItem AS provided0, " + "".join(
    "q.ItemDrop%d AS provided%d, " % (i, i) for i in range(1, 5)
)

# Every class quest of the classic range, one row each.
# Built from this module's own integer constants only (S608 does not apply).
QUESTS_SQL = (  # noqa: S608
    "SELECT q.ID AS id, q.LogTitle AS title, q.QuestSortID AS sort, "
    "q.MinLevel AS min_level, q.AllowableRaces AS races, "
    "COALESCE(a.AllowableClasses, 0) AS classes, "
    "COALESCE(a.PrevQuestID, 0) AS prev, q.RewardSpell AS reward, "
    "q.RewardDisplaySpell AS display, q.SuggestedGroupNum AS grp, "
    + _NPCS
    + _ITEMS
    + _PROVIDED
    + "0 AS pad FROM acore_world.quest_template q "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE (a.AllowableClasses IN ("
    + _MASKS
    + ") OR q.QuestSortID IN ("
    + _SORTS
    + ")) "
    "AND q.MinLevel <= " + str(MAX_QUEST_LEVEL) + " AND q.LogTitle NOT LIKE '<%%' "
    "AND q.LogTitle NOT LIKE 'NOT A QUEST%%'"
)

# The creatures that start and end each quest, with every spawn of them.
GIVERS_SQL = (
    "SELECT s.quest AS quest, 'start' AS role, c.guid AS guid, c.id AS entry, "
    "c.map AS map_id, c.position_x AS x, c.position_y AS y, ct.name AS name "
    "FROM acore_world.creature_queststarter s "
    "JOIN acore_world.creature c ON c.id = s.id "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE s.quest IN ({quests}) "
    "UNION ALL "
    "SELECT e.quest, 'end', c.guid, c.id, c.map, c.position_x, c.position_y, ct.name "
    "FROM acore_world.creature_questender e "
    "JOIN acore_world.creature c ON c.id = e.id "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE e.quest IN ({quests})"
)

# The reward spells a trainer teaches for coin: not a class quest's to give.
TRAINED_SQL = (
    "SELECT DISTINCT SpellId AS spell FROM acore_world.trainer_spell "
    "WHERE SpellId IN ({spells})"
)

# Which creatures drop a required item.
LOOT_SQL = (
    "SELECT l.Item AS item, ct.entry AS entry FROM acore_world.creature_loot_template l "
    "JOIN acore_world.creature_template ct ON ct.lootid = l.Entry "
    "WHERE l.Item IN ({items})"
)

# The items whose on-use spell is bound to named creatures: the spell's target
# condition (source type 17, "object entry", type 3 = a creature, applied to
# the spell's target). A spell with no such row (a self cast, a spell focus, a
# corpse nearby) is not a use-item-on.
USE_ITEMS_SQL = (
    "SELECT it.entry AS item, c.ConditionValue2 AS target "
    "FROM acore_world.item_template it "
    "JOIN acore_world.conditions c ON c.SourceTypeOrReferenceId = 17 "
    "AND c.SourceEntry = it.spellid_1 AND c.ConditionTypeOrReference = 31 "
    "AND c.ConditionValue1 = 3 AND c.ConditionTarget = 1 "
    "AND c.NegativeCondition = 0 "
    "WHERE it.spelltrigger_1 = 0 AND it.entry IN ({items})"
)

# The chests (gameobject type 3) whose loot holds a required item.
CHEST_SQL = (
    "SELECT l.Item AS item, g.entry AS entry "
    "FROM acore_world.gameobject_loot_template l "
    "JOIN acore_world.gameobject_template g ON g.type = 3 AND g.Data1 = l.Entry "
    "WHERE l.Item IN ({items})"
)

# Every spawn of the gameobjects a quest uses (a chest, an objective).
OBJECT_SPAWNS_SQL = (
    "SELECT o.guid AS guid, o.id AS entry, o.map AS map_id, o.position_x AS x, "
    "o.position_y AS y, gt.name AS name, 0 AS `rank`, 0 AS level "
    "FROM acore_world.gameobject o "
    "JOIN acore_world.gameobject_template gt ON gt.entry = o.id "
    "WHERE o.id IN ({entries})"
)

# Every spawn of the creatures an objective names.
SPAWNS_SQL = (
    "SELECT c.guid AS guid, c.id AS entry, c.map AS map_id, c.position_x AS x, "
    "c.position_y AS y, ct.name AS name, ct.`rank` AS `rank`, "
    "ct.maxlevel AS level "
    "FROM acore_world.creature c "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE c.id IN ({entries})"
)

# What one member holds: the quests in its log, the quests it has been
# rewarded, and the spells it knows (guildjobs reads the last already).
LOG_SQL = (
    "SELECT guid, quest, status, "
    "(mobcount1 + mobcount2 + mobcount3 + mobcount4 + itemcount1 + itemcount2 + "
    "itemcount3 + itemcount4 + itemcount5 + itemcount6) AS progress "
    "FROM character_queststatus "
    "WHERE guid IN ({guids}) AND quest IN ({quests}) AND status IN (1, 3)"
)
REWARDED_SQL = (
    "SELECT guid, quest FROM character_queststatus_rewarded "
    "WHERE guid IN ({guids}) AND quest IN ({quests})"
)


@dataclass(frozen=True)
class Spawn:
    """A creature spawn row of the world, by its guid."""

    guid: int
    entry: int
    map_id: int
    x: float
    y: float
    name: str = ""
    rank: int = 0
    # The creature's top level; 0 when the row does not say.
    level: int = 0


@dataclass(frozen=True)
class Use:
    """One thing the quest has the member use, and where.

    `verb` is USE_ITEM (item `item` used on a creature of `targets`) or
    USE_OBJECT (a gameobject of `targets` clicked: a chest that holds `count`
    of `item`, or an objective gameobject when `item` is 0). `spots` are the
    spawns of the targets. `provided` is True for an item the quest hands over
    when it is taken."""

    verb: str
    item: int = 0
    count: int = 1
    targets: tuple = ()
    spots: tuple = ()
    provided: bool = False


@dataclass(frozen=True)
class Quest:
    id: int
    title: str
    klass: int
    min_level: int
    races: int
    prev: int
    reward: int
    display: int
    group: int
    # (creature entry, count) to kill, and (item entry, count) to collect.
    kills: tuple = ()
    items: tuple = ()
    # A required gameobject (a negative RequiredNpcOrGo), which no verb uses.
    objects: tuple = ()
    starters: tuple = ()
    enders: tuple = ()
    # Spawns of every creature that satisfies an objective.
    fields: tuple = ()
    # What the quest has the member use (use-item-on, use-gameobject), and the
    # item entries it hands over when taken.
    uses: tuple = ()
    provided: tuple = ()
    # Required items a creature with a spawn drops.
    droppable: frozenset = frozenset()

    @property
    def spells(self) -> frozenset:
        return frozenset(s for s in (self.reward, self.display) if s)

    @property
    def rewards(self) -> bool:
        return bool(self.spells)

    def admits(self, race: int) -> bool:
        return not self.races or bool(int(self.races) & (1 << (int(race) - 1)))


@dataclass(frozen=True)
class Book:
    """Every class quest, and the reward groups they make."""

    quests: dict = field(default_factory=dict)
    # (class, reward spells) -> reward quest ids
    groups: dict = field(default_factory=dict)
    # Reward spells a trainer teaches: those groups are the trainer's, not a quest's.
    trained: frozenset = frozenset()

    def quest_ids(self) -> list:
        return sorted(self.quests)

    def spell_ids(self) -> list:
        return sorted({s for q in self.quests.values() for s in q.spells})

    def plain(self) -> "Book":
        """The same book with no uses: what the planner works from while the
        worldserver does not carry the use verbs (classuse.py)."""
        if not any(q.uses for q in self.quests.values()):
            return self
        quests = {i: replace(q, uses=()) for i, q in self.quests.items()}
        return Book(quests, self.groups, self.trained)

    def watch_items(self) -> list:
        """The item entries to read from a member's bags: every use item, the
        items a use quest hands over and the items it requires."""
        out = set()
        for q in self.quests.values():
            if q.uses:
                out.update(q.provided)
                out.update(i for i, _n in q.items)
                out.update(u.item for u in q.uses if u.item)
        return sorted(out)

    def use_entries(self) -> tuple:
        """(creature entries, gameobject entries) the uses target, for the
        spawn reads."""
        creatures, objects = set(), set()
        for q in self.quests.values():
            for u in q.uses:
                (creatures if u.verb == USE_ITEM else objects).update(u.targets)
        return sorted(creatures), sorted(objects)


@dataclass(frozen=True)
class Move:
    """One thing a member does toward a class quest, or why it cannot."""

    kind: str
    quest: int = 0
    klass: int = 0
    spot: Spawn | None = None
    said: str = ""
    blocker: str = ""
    why: str = ""
    # For a blocker a guildmate can help with: how many helpers, the quest's
    # title, and the objective's spawn the group would go to.
    want: int = 0
    title: str = ""
    # For a USE move: what is used at `spot`.
    use: Use | None = None


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def klass_of(row) -> int:
    """The one class a quest row belongs to, 0 when it names none or several."""
    mask = _int(row.get("classes"))
    if mask in SINGLE_CLASS_MASKS:
        return mask.bit_length()
    return CLASS_OF_SORT.get(_int(row.get("sort")), 0)


def _pairs(row, key, count, span, positive=True) -> tuple:
    out = []
    for i in range(1, span + 1):
        entry = _int(row.get("%s%d" % (key, i)))
        if entry and (entry > 0) == positive:
            out.append((abs(entry), max(1, _int(row.get("%s%d" % (count, i))))))
    return tuple(out)


def _spawn(r) -> Spawn:
    return Spawn(
        _int(r.get("guid")),
        _int(r.get("entry")),
        _int(r.get("map_id")),
        float(r.get("x") or 0.0),
        float(r.get("y") or 0.0),
        str(r.get("name") or ""),
        _int(r.get("rank")),
        _int(r.get("level")),
    )


def _givers(giver_rows) -> tuple:
    """(quest -> start spawns, quest -> end spawns) from GIVERS_SQL's rows."""
    starts, ends = {}, {}
    for r in giver_rows or ():
        side = starts if r.get("role") == "start" else ends
        side.setdefault(_int(r.get("quest")), []).append(_spawn(r))
    return starts, ends


def _spawns_by_entry(spawn_rows) -> dict:
    out = {}
    for r in spawn_rows or ():
        out.setdefault(_int(r.get("entry")), []).append(_spawn(r))
    return out


def _droppers(loot_rows) -> dict:
    out = {}
    for r in loot_rows or ():
        out.setdefault(_int(r.get("item")), set()).add(_int(r.get("entry")))
    return out


def _targets(rows, key="item", value="target") -> dict:
    """item entry -> the sorted entries a use read names for it."""
    out: dict = {}
    for r in rows or ():
        out.setdefault(_int(r.get(key)), set()).add(_int(r.get(value)))
    return {k: tuple(sorted(v - {0})) for k, v in out.items()}


def _provided(r) -> tuple:
    """The item entries the quest hands over when it is taken."""
    seen = []
    for i in range(5):
        entry = _int(r.get("provided%d" % i))
        if entry and entry not in seen:
            seen.append(entry)
    return tuple(seen)


def _uses(r, items, provided, droppers, aims) -> tuple:
    """The Uses of one quest: items used on creatures, chests that hold a
    required item no creature drops, and gameobject objectives.

    `aims` is (item -> creature entries, item -> chest entries, spawns by
    creature entry, spawns by gameobject entry)."""
    item_aims, chests, creature_spawns, object_spawns = aims
    out = []
    required = [i for i, _n in items]
    for item in dict.fromkeys([*provided, *required]):
        targets = item_aims.get(item, ())
        if targets:
            spots = tuple(s for t in targets for s in creature_spawns.get(t, ()))
            out.append(Use(USE_ITEM, item, 1, targets, spots, item in provided))
    for item, count in items:
        if item in provided or any(
            creature_spawns.get(e) for e in droppers.get(item, ())
        ):
            continue
        found = chests.get(item, ())
        if found:
            spots = tuple(s for g in found for s in object_spawns.get(g, ()))
            out.append(Use(USE_OBJECT, item, count, found, spots))
    for entry, count in _pairs(r, "npc", "npc_count", 4, False):
        spots = tuple(object_spawns.get(entry, ()))
        out.append(Use(USE_OBJECT, 0, count, (entry,), spots))
    return tuple(out)


def _quest(r, klass, starts, ends, by_entry, droppers, aims) -> Quest:
    kills = _pairs(r, "npc", "npc_count", 4, True)
    items = _pairs(r, "item", "item_count", 6)
    entries = {e for e, _n in kills}
    for item, _n in items:
        entries |= droppers.get(item, set())
    qid = _int(r.get("id"))
    provided = _provided(r)
    return Quest(
        qid,
        str(r.get("title") or ""),
        klass,
        _int(r.get("min_level")),
        _int(r.get("races")),
        abs(_int(r.get("prev"))),
        _int(r.get("reward")),
        _int(r.get("display")),
        _int(r.get("grp")),
        kills,
        items,
        _pairs(r, "npc", "npc_count", 4, False),
        tuple(starts.get(qid, ())),
        tuple(ends.get(qid, ())),
        tuple(s for e in sorted(entries) for s in by_entry.get(e, ())),
        _uses(r, items, provided, droppers, aims),
        provided,
        frozenset(
            i for i, _n in items if any(by_entry.get(e) for e in droppers.get(i, ()))
        ),
    )


def build(
    quest_rows,
    giver_rows,
    spawn_rows,
    loot_rows,
    trained_rows=(),
    use_rows=(),
    chest_rows=(),
    object_rows=(),
) -> Book:
    """The Book from the world's rows.

    `giver_rows` are GIVERS_SQL's, `spawn_rows` SPAWNS_SQL's for every creature
    an objective names (a creature to kill, one that drops a required item, or
    one an item is used on) and `loot_rows` LOOT_SQL's. `use_rows` are
    USE_ITEMS_SQL's, `chest_rows` CHEST_SQL's and `object_rows`
    OBJECT_SPAWNS_SQL's: with none of them no quest has a use, as on a world
    read before the verbs existed.
    """
    starts, ends = _givers(giver_rows)
    by_entry = _spawns_by_entry(spawn_rows)
    droppers = _droppers(loot_rows)
    aims = (
        _targets(use_rows),
        _targets(chest_rows, "item", "entry"),
        by_entry,
        _spawns_by_entry(object_rows),
    )
    quests = {}
    for r in quest_rows or ():
        klass = klass_of(r)
        if klass:
            quests[_int(r.get("id"))] = _quest(
                r, klass, starts, ends, by_entry, droppers, aims
            )
    groups = {}
    for q in quests.values():
        if q.rewards:
            groups.setdefault((q.klass, tuple(sorted(q.spells))), []).append(q.id)
    trained = frozenset(_int(r.get("spell")) for r in trained_rows or ())
    return Book(quests, {k: sorted(v) for k, v in groups.items()}, trained)


def chain(book: Book, quest_id: int) -> list:
    """The quests from the first of the chain to `quest_id`, oldest first. A
    quest the book does not hold ends the walk back (a prerequisite of another
    class's or an unreadable one)."""
    out, seen, at = [], set(), int(quest_id)
    while at and at in book.quests and at not in seen:
        seen.add(at)
        out.append(at)
        at = book.quests[at].prev
    return out[::-1]


def has_reward(book: Book, member, key) -> bool:
    """True when the member knows the reward's spells, or has been rewarded
    any quest that grants them."""
    klass, spells = key
    if any(s in member.known for s in spells):
        return True
    done = member.quests_done
    return any(q in done for q in book.groups.get(key, ()))


def _yards(member, spawn) -> float:
    return math.hypot(float(member.x) - spawn.x, float(member.y) - spawn.y)


def _nearest(member, spawns):
    """The spawn nearest the member on its map, None when none is."""
    here = [s for s in spawns if int(s.map_id) == int(member.map_id)]
    return min(here, key=lambda s: (_yards(member, s), s.guid)) if here else None


def _avoids(spawn, avoid) -> bool:
    return any(
        int(spawn.map_id) == int(m)
        and math.hypot(spawn.x - x, spawn.y - y) <= PACK_YARDS
        for m, x, y in avoid or ()
    )


def _densest(member, spawns, avoid=()):
    """The spawn on the member's map with the most others within PACK_YARDS,
    the nearest of those; None when none is on the map. A spawn within
    PACK_YARDS of a place in `avoid` ((map, x, y), a pack already tried) is
    left out."""
    here = [
        s
        for s in spawns
        if int(s.map_id) == int(member.map_id) and not _avoids(s, avoid)
    ]
    if not here:
        return None

    def pack(s):
        return sum(1 for o in here if math.hypot(o.x - s.x, o.y - s.y) <= PACK_YARDS)

    return min(here, key=lambda s: (-pack(s), _yards(member, s), s.guid))


def _source_blocker(quest: Quest) -> tuple:
    return SOURCE, (
        "%s needs %s no creature spawn or drop supplies (an item used on a "
        "creature, or a summoned spawn): the module has no verb for it"
        % (quest.title, "an objective" if quest.kills else "an item")
    )


def _unmet(quest: Quest) -> bool:
    """True when something the quest requires has no source at all: an item
    no creature drops, no chest holds and the quest does not hand over, or a
    kill with no spawn that no item use credits."""
    spawned = {s.entry for s in quest.fields}
    chested = {u.item for u in quest.uses if u.verb == USE_OBJECT and u.item}
    given = set(quest.provided)
    fed = any(u.verb == USE_ITEM for u in quest.uses)
    if any(e not in spawned and not fed for e, _n in quest.kills):
        return True
    return any(
        i not in chested and i not in given and i not in quest.droppable
        for i, _n in quest.items
    )


def _hunting(quest: Quest, member) -> bool:
    """True while the quest has creatures to hunt: a kill with a spawn, or a
    dropped item the member does not yet carry in full."""
    kills = {e for e, _n in quest.kills}
    if any(s.entry in kills for s in quest.fields):
        return True
    return any(member.count(i) < n for i, n in quest.items if i in quest.droppable)


def _pending_use(quest: Quest, member):
    """The Use the member has next, None when it has none or must hunt first."""
    if not quest.uses or _hunting(quest, member):
        return None
    for use in quest.uses:
        if use.verb == USE_OBJECT and use.item and member.count(use.item) >= use.count:
            continue
        return use
    return None


def _use_blocker(quest: Quest, member) -> tuple:
    """(kind, sentence) when a quest with uses cannot be done now, else
    ("", "")."""
    spots = [s for u in quest.uses for s in u.spots] + list(quest.fields)
    if any(s.rank >= ELITE_RANK for s in spots):
        return GROUP, "%s's objective is an elite" % quest.title
    if _unmet(quest):
        return _source_blocker(quest)
    use = _pending_use(quest, member)
    if use is None:
        if quest.fields and _nearest(member, quest.fields) is None:
            return MAP, "%s's objective is on another map than the member" % quest.title
        return "", ""
    if not use.spots:
        what = "gameobject" if use.verb == USE_OBJECT else "creature"
        return (
            OBJECT,
            "%s needs a %s used (entry %s has no spawn row in the world data)"
            % (
                quest.title,
                what,
                "/".join(str(t) for t in use.targets),
            ),
        )
    if _nearest(member, use.spots) is None:
        return MAP, "%s's use target is on another map than the member" % quest.title
    if use.verb == USE_ITEM and not member.carries(use.item):
        return ITEM, (
            "%s needs item %d used on a creature and the member does not carry "
            "it (the class step buys nothing and cannot hand a quest item out again)"
            % (quest.title, use.item)
        )
    return "", ""


def blocker_of(quest: Quest, member) -> tuple:
    """(kind, sentence) when this quest cannot be hunted solo, else ("", "")."""
    if quest.group >= 2:
        return GROUP, "%s suggests a group of %d" % (quest.title, quest.group)
    if quest.uses:
        return _use_blocker(quest, member)
    if quest.objects:
        return OBJECT, "%s needs a gameobject used, which no verb does" % quest.title
    if any(s.rank >= ELITE_RANK for s in quest.fields):
        return GROUP, "%s's objective is an elite" % quest.title
    if (quest.kills or quest.items) and not quest.fields:
        return _source_blocker(quest)
    if quest.fields and _nearest(member, quest.fields) is None:
        return MAP, "%s's objective is on another map than the member" % quest.title
    return "", ""


def _status(member, quest_id) -> int:
    return int(member.quest_log.get(int(quest_id), 0))


def _variant_move(book: Book, member, reward_id: int):
    """The next move along one reward quest's chain, or None when it is not
    open to this member (race, level)."""
    path = chain(book, reward_id)
    done = member.quests_done
    todo = [q for q in path if q not in done]
    if not todo:
        return None
    quest = book.quests[todo[0]]
    if quest.prev and quest.prev not in book.quests and quest.prev not in done:
        return None
    if not all(
        book.quests[q].admits(member.race) for q in path[: path.index(todo[0]) + 1]
    ):
        return None
    if int(member.level) < quest.min_level:
        return None
    status = _status(member, quest.id)
    if status == STATUS_COMPLETE:
        return TURN_IN, quest, _nearest(member, quest.enders), reward_id
    if status == STATUS_INCOMPLETE:
        return HUNT, quest, None, reward_id
    return TAKE, quest, _nearest(member, quest.starters), reward_id


def helpers_for(quest: Quest) -> int:
    """How many guildmates a group-blocked quest asks for: the suggested group
    less the member itself, or ELITE_HELPERS for an elite objective with no
    group size, at most MAX_HELPERS."""
    wanted = quest.group - 1 if quest.group >= 2 else ELITE_HELPERS
    return max(1, min(MAX_HELPERS, wanted))


def moves(book: Book, member, avoid=None, held_off=frozenset()) -> list:
    """Every class reward the member lacks and may work toward now, as Moves,
    the lowest quest level first; a blocked one is a BLOCKED Move naming why.

    `avoid` is quest id -> ((map, x, y), ...), the packs a hunt already tried
    without progress; `held_off` the quest ids whose hunt was given up for now."""
    out = []
    for key, rewards in sorted(
        book.groups.items(), key=lambda kv: (book.quests[kv[1][0]].min_level, kv[0])
    ):
        klass, _spells = key
        if klass != int(member.class_id) or has_reward(book, member, key):
            continue
        if book.trained.intersection(key[1]):
            continue
        options = [m for m in (_variant_move(book, member, q) for q in rewards) if m]
        if not options:
            continue
        # A variant already in the log first, then the nearest giver.
        options.sort(
            key=lambda o: (
                _status(member, o[1].id) == 0,
                _yards(member, o[2]) if o[2] else 1e12,
                o[1].id,
            )
        )
        made = [_move_of(member, o, key, avoid or {}, held_off) for o in options]
        # The first move that can be made; else the first blocker, named.
        out.append(next((m for m in made if m.kind != BLOCKED), made[0]))
    return out


def _move_of(member, option, key, avoid=None, held_off=frozenset()) -> Move:
    kind, quest, spot, reward_id = option
    reward = key[1]
    why = "%s (%s quest %d) for spell %s" % (
        quest.title,
        MARK,
        quest.id,
        "/".join(str(s) for s in reward),
    )
    if kind == HUNT:
        return _hunt_move(member, quest, why, (avoid or {}).get(quest.id, ()), held_off)
    if spot is None:
        ends = quest.enders if kind == TURN_IN else quest.starters
        word = "ender" if kind == TURN_IN else "giver"
        block, said = (
            (MAP, "%s has no %s on the member's map" % (quest.title, word))
            if ends
            else (
                SOURCE,
                "%s has no %s creature in the world data" % (quest.title, word),
            )
        )
        return Move(BLOCKED, quest.id, quest.klass, None, said, block, why)
    verb = "hands in" if kind == TURN_IN else "takes"
    return Move(
        kind,
        quest.id,
        quest.klass,
        spot,
        "%s walks to %s and %s %s" % (member.name, spot.name or "its giver", verb, why),
        "",
        why,
    )


def _nearest_untried(member, spawns, avoid=()):
    """The spawn on the member's map nearest it that is not within PACK_YARDS
    of a place in `avoid` (a target already used without result)."""
    here = [
        s
        for s in spawns
        if int(s.map_id) == int(member.map_id) and not _avoids(s, avoid)
    ]
    return min(here, key=lambda s: (_yards(member, s), s.guid)) if here else None


def within_level(member, spawns) -> tuple:
    """The spawns whose creature is at most OVERLEVEL_MAX levels over the
    member; a spawn whose level the world data does not give (0) is kept."""
    top = int(member.level) + OVERLEVEL_MAX
    return tuple(s for s in spawns if int(s.level) <= top)


def _level_said(member, quest: Quest) -> str:
    lowest = min(int(s.level) for s in quest.fields)
    return (
        "%s: every spawn of its objective is more than %d levels over the "
        "member (the lowest is level %d, the member %d)"
        % (quest.title, OVERLEVEL_MAX, lowest, int(member.level))
    )


def refused_places(book: Book, refused) -> dict:
    """quest id -> ((map, x, y), ...) of every objective spawn whose guid is in
    `refused` (the spawns the module refused this member lately): the places a
    hunt leaves, as it leaves a pack that made no progress."""
    if not refused:
        return {}
    out = {}
    for quest in book.quests.values():
        places = tuple(
            (int(s.map_id), float(s.x), float(s.y))
            for s in quest.fields
            if s.guid in refused
        )
        if places:
            out[quest.id] = places
    return out


def _hunt_move(member, quest: Quest, why: str, tried, held_off) -> Move:
    """The member's work on an incomplete quest (a hunt, or a use), or why it
    is blocked."""
    using = _pending_use(quest, member)
    if quest.id in held_off:
        if using is not None:
            said = "%s: using it changed nothing through %d target(s)" % (
                quest.title,
                len(tried) + 1,
            )
            return Move(
                BLOCKED,
                quest.id,
                quest.klass,
                None,
                said,
                USE_STALLED,
                why,
                1,
                quest.title,
            )
        said = "%s: no progress through %d pack(s) of its objective" % (
            quest.title,
            len(tried) + 1,
        )
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, STALLED, why, 1, quest.title
        )
    block, said = blocker_of(quest, member)
    if block:
        want = helpers_for(quest) if block == GROUP else 0
        spot = _densest(member, quest.fields) if block == GROUP else None
        return Move(
            BLOCKED, quest.id, quest.klass, spot, said, block, why, want, quest.title
        )
    if using is not None:
        return _use_move(member, quest, using, why, tried)
    if quest.uses and not quest.fields:
        # Everything its uses need is carried; the quest log has not caught up.
        said = (
            "%s: the member carries what its uses need; the quest log has not caught up"
            % quest.title
        )
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, UNKNOWN, why, 0, quest.title
        )
    fields = within_level(member, quest.fields)
    if quest.fields and not fields:
        return Move(
            BLOCKED,
            quest.id,
            quest.klass,
            None,
            _level_said(member, quest),
            LEVEL,
            why,
            0,
            quest.title,
        )
    spot = _densest(member, fields, tried)
    if spot is None:
        said = "%s: every pack of its objective was tried" % quest.title
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, STALLED, why, 1, quest.title
        )
    return Move(
        HUNT,
        quest.id,
        quest.klass,
        spot,
        "%s hunts %s for %s" % (member.name, spot.name or "its objective", why),
        "",
        why,
    )


def _use_move(member, quest: Quest, use: Use, why: str, tried) -> Move:
    """The member walks to a target of the use and writes its row there."""
    spot = _nearest_untried(member, use.spots, tried)
    if spot is None:
        said = "%s: every target of its use was tried" % quest.title
        return Move(
            BLOCKED, quest.id, quest.klass, None, said, USE_STALLED, why, 1, quest.title
        )
    what = "uses item %d on" % use.item if use.verb == USE_ITEM else "uses"
    said = "%s %s %s for %s" % (member.name, what, spot.name or "its target", why)
    return Move(USE, quest.id, quest.klass, spot, said, "", why, use=use)


def use_command(use: Use, spot: Spawn) -> str:
    """The kind='quest' command row that does this use at `spot`."""
    if use.verb == USE_ITEM:
        return "%s creature:%d item:%d" % (USE_ITEM, int(spot.entry), int(use.item))
    return "%s %d" % (USE_OBJECT, int(spot.entry))


def blocked_sentence(member, move: Move) -> str:
    return "%s cannot do its %s class quest: %s (%s)" % (
        member.name,
        CLASS_NAMES.get(move.klass, "class"),
        move.blocker,
        move.said,
    )


def helps(book: Book, member, avoid=None, held_off=frozenset()) -> list:
    """The BLOCKED Moves a guildmate can help with (a group quest, a hunt that
    stalled) that the member has no other class move ahead of: the member asks
    for these in guild chat (classask.py)."""
    return [
        m
        for m in moves(book, member, avoid, held_off)
        if m.kind == BLOCKED and m.blocker in HELPABLE and m.want
    ]


def objective_spot(book, move: Move, member):
    """The creature spawn a party walks to for a helpable move, None when it
    has none: the group quest's own densest pack (Move.spot), or, for a hunt
    given up after it stalled, the densest pack of the quest's objective with
    no pack left out (a party can face the pack a lone member could not).

    A use that changed nothing (USE_STALLED) has no spot: a party walk only
    gets the party there, and the use is the leader's own row."""
    if move.spot is not None:
        return move.spot
    quest = book.quests.get(int(move.quest)) if book is not None else None
    if quest is None or move.blocker != STALLED:
        return None
    return _densest(member, quest.fields)


def next_move(book: Book, member, avoid=None, held_off=frozenset()):
    """(the move to make or None, [blocker sentences]) for one member.

    The first move that is not blocked wins; every blocked one is named, so a
    member that does nothing says why."""
    blocked = []
    for move in moves(book, member, avoid, held_off):
        if move.kind == BLOCKED:
            blocked.append(blocked_sentence(member, move))
            continue
        return move, blocked
    return None, blocked


# --- the hunt's clock and the asks ----------------------------------------------

REROLL, GIVE_UP = "reroll", "giveup"


@dataclass(frozen=True)
class Hunt:
    """One member's current hunt: the quest, its progress when last seen, when
    that last changed, the packs tried without progress, and (when set) the
    moment the quest is given up until."""

    quest: int
    progress: int
    since: float
    tried: tuple = ()
    until: float | None = None


class Hunts:
    """What each member's hunt has done lately, kept in memory by the bridge.

    A restart forgets it, which only gives a stalled hunt a fresh 30 minutes.
    Times are seconds from one clock for the life of the object, any epoch
    (time.time() or time.monotonic(), which may start near 0): no time is a
    sentinel, an unset hold-off is None."""

    def __init__(self):
        self._by: dict = {}

    def get(self, name):
        return self._by.get(name)

    def state(self, name, now) -> tuple:
        """(avoid, held_off) for moves(): the packs tried for the member's
        hunt, and the quest given up while its hold-off lasts."""
        hunt = self._by.get(name)
        if hunt is None:
            return {}, frozenset()
        if hunt.until is not None and hunt.until <= now:
            return {}, frozenset()
        off = frozenset({hunt.quest}) if hunt.until is not None else frozenset()
        return {hunt.quest: hunt.tried}, off

    def observe(self, name, quest, progress, spot, now, failed=False) -> str:
        """Record one pass of a hunt toward `spot`; REROLL when it has stalled
        and another pack is to be tried, GIVE_UP when it stalled through every
        retry, else ""."""
        hunt = self._by.get(name)
        fresh = hunt is None or hunt.quest != quest
        if not fresh and hunt.until is not None:
            if hunt.until > now:
                return ""
            fresh = True
        if fresh:
            hunt = Hunt(quest, progress, now)
        elif progress != hunt.progress:
            hunt = Hunt(quest, progress, now)
        idle = now - hunt.since >= HUNT_STALL_MINUTES * 60
        if not (idle or failed):
            self._by[name] = hunt
            return ""
        tried = hunt.tried + ((int(spot.map_id), float(spot.x), float(spot.y)),)
        if len(tried) > MAX_REROLLS:
            self._by[name] = Hunt(
                quest, progress, now, tried, now + GIVE_UP_MINUTES * 60
            )
            return GIVE_UP
        self._by[name] = Hunt(quest, progress, now, tried)
        return REROLL

    def give_up(self, name, quest, now) -> None:
        """Give a quest up for GIVE_UP_MINUTES at once: the world refused its
        use for good (classuse.NEVER), so no other target is worth a try."""
        hunt = self._by.get(name)
        tried = hunt.tried if hunt is not None and hunt.quest == quest else ()
        self._by[name] = Hunt(int(quest), 0, now, tried, now + GIVE_UP_MINUTES * 60)

    def pause(self, name, quest, now) -> None:
        """Restart the stall clock of a hunt that is waiting on the realm, not
        on the member: a far walk refused for a wall that moves (BACKOFF_MINUTES)
        or held back for want of a slot. The 30 minutes count a member hunting
        with no progress, and a member standing in a queue has not hunted."""
        hunt = self._by.get(name)
        if hunt is None or hunt.quest != quest or hunt.until is not None:
            return
        self._by[name] = replace(hunt, since=now)

    def forget(self, name) -> None:
        self._by.pop(name, None)


@dataclass(frozen=True)
class Help:
    """A member's class quest that a guildmate could help with."""

    member: str
    guild: str
    level: int
    map_id: int
    move: Move
