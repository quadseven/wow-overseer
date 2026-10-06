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
  object   an objective that needs a gameobject used or a spell cast: the
           module has no verb for it;
  source   an item with no creature that drops it, or no spawn row;
  map      every giver or objective spawn is on another map than the member's:
           walk-to-spawn refuses a spawn on another map.

PURE MODULE: rows in, a Move out. No MySQL, no clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

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

# The classic range: a class quest is built for a member that can take it by
# this level. Beyond it (Outland and Northrend class quests) is another job.
MAX_QUEST_LEVEL = 45

# The core's QuestStatus values a character_queststatus row carries.
STATUS_COMPLETE, STATUS_INCOMPLETE = 1, 3

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "classquest"

# A member's plan line carries this while it works a class quest.
MARK = "class quest"

# Move kinds.
TAKE, HUNT, TURN_IN, BLOCKED = "take", "hunt", "turnin", "blocked"
# Blockers.
GROUP, OBJECT, SOURCE, MAP, UNKNOWN = "group", "object", "source", "map", "unknown"

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

# Every class quest of the classic range, one row each.
QUESTS_SQL = (
    "SELECT q.ID AS id, q.LogTitle AS title, q.QuestSortID AS sort, "
    "q.MinLevel AS min_level, q.AllowableRaces AS races, "
    "COALESCE(a.AllowableClasses, 0) AS classes, "
    "COALESCE(a.PrevQuestID, 0) AS prev, q.RewardSpell AS reward, "
    "q.RewardDisplaySpell AS display, q.SuggestedGroupNum AS grp, "
    + _NPCS
    + _ITEMS
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

# Every spawn of the creatures an objective names.
SPAWNS_SQL = (
    "SELECT c.guid AS guid, c.id AS entry, c.map AS map_id, c.position_x AS x, "
    "c.position_y AS y, ct.name AS name, ct.`rank` AS `rank` "
    "FROM acore_world.creature c "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE c.id IN ({entries})"
)

# What one member holds: the quests in its log, the quests it has been
# rewarded, and the spells it knows (guildjobs reads the last already).
LOG_SQL = (
    "SELECT guid, quest, status FROM character_queststatus "
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


def build(quest_rows, giver_rows, spawn_rows, loot_rows, trained_rows=()) -> Book:
    """The Book from the world's rows.

    `giver_rows` are GIVERS_SQL's, `spawn_rows` SPAWNS_SQL's for every creature
    an objective names (a creature to kill, or one that drops a required item)
    and `loot_rows` LOOT_SQL's.
    """
    starts, ends = {}, {}
    for r in giver_rows or ():
        spawn = Spawn(
            _int(r.get("guid")),
            _int(r.get("entry")),
            _int(r.get("map_id")),
            float(r.get("x") or 0.0),
            float(r.get("y") or 0.0),
            str(r.get("name") or ""),
        )
        (starts if r.get("role") == "start" else ends).setdefault(
            _int(r.get("quest")), []
        ).append(spawn)
    by_entry = {}
    for r in spawn_rows or ():
        by_entry.setdefault(_int(r.get("entry")), []).append(
            Spawn(
                _int(r.get("guid")),
                _int(r.get("entry")),
                _int(r.get("map_id")),
                float(r.get("x") or 0.0),
                float(r.get("y") or 0.0),
                str(r.get("name") or ""),
                _int(r.get("rank")),
            )
        )
    droppers = {}
    for r in loot_rows or ():
        droppers.setdefault(_int(r.get("item")), set()).add(_int(r.get("entry")))
    quests = {}
    for r in quest_rows or ():
        klass = klass_of(r)
        if not klass:
            continue
        kills = _pairs(r, "npc", "npc_count", 4, True)
        objects = _pairs(r, "npc", "npc_count", 4, False)
        items = _pairs(r, "item", "item_count", 6)
        entries = {e for e, _n in kills}
        for item, _n in items:
            entries |= droppers.get(item, set())
        fields = tuple(s for e in sorted(entries) for s in by_entry.get(e, ()))
        qid = _int(r.get("id"))
        quests[qid] = Quest(
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
            objects,
            tuple(starts.get(qid, ())),
            tuple(ends.get(qid, ())),
            fields,
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


def _densest(member, spawns):
    """The spawn on the member's map with the most others within PACK_YARDS,
    the nearest of those; None when none is on the map."""
    here = [s for s in spawns if int(s.map_id) == int(member.map_id)]
    if not here:
        return None

    def pack(s):
        return sum(1 for o in here if math.hypot(o.x - s.x, o.y - s.y) <= PACK_YARDS)

    return min(here, key=lambda s: (-pack(s), _yards(member, s), s.guid))


def blocker_of(quest: Quest, member) -> tuple:
    """(kind, sentence) when this quest cannot be hunted solo, else ("", "")."""
    if quest.group >= 2:
        return GROUP, "%s suggests a group of %d" % (quest.title, quest.group)
    if quest.objects:
        return OBJECT, "%s needs a gameobject used, which no verb does" % quest.title
    if any(s.rank >= ELITE_RANK for s in quest.fields):
        return GROUP, "%s's objective is an elite" % quest.title
    if (quest.kills or quest.items) and not quest.fields:
        return SOURCE, (
            "%s needs %s no creature spawn or drop supplies (an item used on a "
            "creature, or a summoned spawn): the module has no verb for it"
            % (quest.title, "an objective" if quest.kills else "an item")
        )
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


def moves(book: Book, member) -> list:
    """Every class reward the member lacks and may work toward now, as Moves,
    the lowest quest level first; a blocked one is a BLOCKED Move naming why."""
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
        made = [_move_of(member, o, key) for o in options]
        # The first move that can be made; else the first blocker, named.
        out.append(next((m for m in made if m.kind != BLOCKED), made[0]))
    return out


def _move_of(member, option, key) -> Move:
    kind, quest, spot, reward_id = option
    reward = key[1]
    why = "%s (%s quest %d) for spell %s" % (
        quest.title,
        MARK,
        quest.id,
        "/".join(str(s) for s in reward),
    )
    if kind == HUNT:
        block, said = blocker_of(quest, member)
        if block:
            return Move(BLOCKED, quest.id, quest.klass, None, said, block, why)
        spot = _densest(member, quest.fields)
        return Move(
            HUNT,
            quest.id,
            quest.klass,
            spot,
            "%s hunts %s for %s" % (member.name, spot.name or "its objective", why),
            "",
            why,
        )
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


def next_move(book: Book, member):
    """(the move to make or None, [blocker sentences]) for one member.

    The first move that is not blocked wins; every blocked one is named, so a
    member that does nothing says why."""
    blocked = []
    for move in moves(book, member):
        if move.kind == BLOCKED:
            blocked.append(
                "%s cannot do its %s class quest: %s (%s)"
                % (
                    member.name,
                    CLASS_NAMES.get(move.klass, "class"),
                    move.blocker,
                    move.said,
                )
            )
            continue
        return move, blocked
    return None, blocked
