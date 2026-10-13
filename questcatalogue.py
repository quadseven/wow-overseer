"""Every quest in the classic level-60 ruleset, in one list (#923).

WHY THIS EXISTS. The questers (#922) are there to prove that every quest
works, and that needs a list of every quest to prove. quest_template is read
in many places (levelroute, classquest, campaignplan, guildlevel), but each
reads the slice its planner needs: the hub zones, the class chains, the
dungeon quests. Nothing read the whole catalogue.

WHAT IS IN IT (`in_ruleset`). The realm runs Wrath data, so quest_template
holds Outland and Northrend too. A quest is in the classic ruleset
(classic.py) when:

  * its level and its minimum level are at most classic.MAX_LEVEL;
  * it is taken and handed in where a classic character can stand: some
    spawn of a creature or gameobject that starts it, and some spawn of one
    that ends it, is on a classic map (classic.is_classic_map), or on map
    530 inside one of the Blood Elf and Draenei starting lands when the
    quest's own zone is one of them. "Some" and not "every", because a
    holiday or city NPC stands in Shattrath as well as Stormwind. A quest
    no creature or gameobject starts (an item starts it) is judged on its
    end alone; a quest with no spawned giver at either end cannot be taken
    by anybody and is left out;
  * its title is not a placeholder ("<UNUSED>", "NOT A QUEST").

Spawn maps and not the quest's zone, because QuestSortID is a zone only when
it is positive: class, profession and holiday quests carry a negative sort
and no zone at all, and "Through the Dark Portal" is filed under Blasted Lands
while it is handed in in Hellfire.

WHAT EACH QUEST CARRIES (`Quest`): id, title, level, minimum level, zone (id
and name, or none), faction (from the race mask), the race and class masks,
and the quest it follows (quest_template_addon.PrevQuestID: positive when
that quest must be rewarded first, negative when it must be in the log).

READ ONCE PER PROCESS (`load`), as levelroute's hub quests are: none of it
changes while a realm runs. A read the realm cannot answer is not remembered
and is tried again next time.

PURE apart from `load`, which is handed the read and keeps its answer.
"""

from __future__ import annotations

from dataclasses import dataclass

import classic
import levelroute
import places

HORDE = levelroute.HORDE
ALLIANCE = levelroute.ALLIANCE
BOTH = "both"
FACTIONS = (HORDE, ALLIANCE, BOTH)

# A quest level of -1 scales to the player (holiday and repeatable quests):
# not over the cap, so the map test alone decides.
QUESTS_SQL = (
    "SELECT t.ID AS quest, t.LogTitle AS title, t.QuestLevel AS level, "
    "t.MinLevel AS min_level, t.QuestSortID AS sort, t.AllowableRaces AS races, "
    "COALESCE(a.AllowableClasses, 0) AS classes, "
    "COALESCE(a.PrevQuestID, 0) AS follows "
    "FROM acore_world.quest_template t "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = t.ID "
    "WHERE t.LogTitle NOT LIKE '<%%' AND t.LogTitle NOT LIKE 'NOT A QUEST%%'"
)

# Every map a quest's starters and enders stand on. creature.id, not id1, as
# everywhere else on this world.
GIVERS_SQL = (
    "SELECT DISTINCT s.quest AS quest, 'start' AS role, c.map AS map_id "
    "FROM acore_world.creature_queststarter s "
    "JOIN acore_world.creature c ON c.id = s.id "
    "UNION SELECT DISTINCT s.quest, 'start', g.map "
    "FROM acore_world.gameobject_queststarter s "
    "JOIN acore_world.gameobject g ON g.id = s.id "
    "UNION SELECT DISTINCT e.quest, 'end', c.map "
    "FROM acore_world.creature_questender e "
    "JOIN acore_world.creature c ON c.id = e.id "
    "UNION SELECT DISTINCT e.quest, 'end', g.map "
    "FROM acore_world.gameobject_questender e "
    "JOIN acore_world.gameobject g ON g.id = e.id"
)


@dataclass(frozen=True)
class Quest:
    id: int
    title: str
    level: int
    min_level: int
    zone: int | None  # an area id, or None for a class or holiday sort
    zone_name: str
    faction: str  # HORDE, ALLIANCE or BOTH
    races: int  # AllowableRaces; 0 is every race
    classes: int  # AllowableClasses; 0 is every class
    follows: int  # PrevQuestID; 0 is none

    def view(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level,
            "min_level": self.min_level,
            "zone": self.zone,
            "zone_name": self.zone_name,
            "faction": self.faction,
            "races": self.races,
            "classes": self.classes,
            "follows": self.follows,
        }


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def faction_of(races) -> str:
    """HORDE, ALLIANCE or BOTH off an AllowableRaces mask. 0 (and -1, which
    some rows carry) is every race."""
    mask = _int(races)
    if mask <= 0:
        return BOTH
    horde = bool(mask & levelroute.RACE_MASK[HORDE])
    alliance = bool(mask & levelroute.RACE_MASK[ALLIANCE])
    if horde and not alliance:
        return HORDE
    if alliance and not horde:
        return ALLIANCE
    return BOTH


def _zone(sort) -> int | None:
    sort = _int(sort)
    return sort if sort > 0 else None


# What levelroute.zone_name answers for a zone it cannot place.
_UNPLACED = levelroute.zone_name(-1)


def zone_name(zone_id) -> str:
    """The zone's name, or "" for no zone or one nothing here can name."""
    if not zone_id:
        return ""
    name = levelroute.zone_name(zone_id)
    return "" if name == _UNPLACED else places.zone_display(name)


def givers(rows) -> dict:
    """quest -> {"start": set of maps, "end": set of maps} off GIVERS_SQL."""
    out: dict = {}
    for row in rows or ():
        role = str(row.get("role") or "")
        if role not in ("start", "end") or row.get("map_id") is None:
            continue
        out.setdefault(_int(row.get("quest")), {"start": set(), "end": set()})[
            role
        ].add(_int(row.get("map_id")))
    return out


def _map_ok(map_id: int, zone) -> bool:
    if classic.is_classic_map(map_id):
        return True
    return map_id == classic.OUTLAND_MAP and _int(zone) in classic.STARTING_LAND_ZONES


def in_ruleset(row, maps) -> bool:
    """Is this quest_template row a classic quest? `maps` is its givers()
    entry, or None when nothing spawned starts or ends it."""
    if _int(row.get("level")) > classic.MAX_LEVEL:
        return False
    if _int(row.get("min_level")) > classic.MAX_LEVEL:
        return False
    if not maps or not (maps["start"] or maps["end"]):
        return False
    zone = row.get("sort")
    for role in ("start", "end"):
        found = maps[role]
        if found and not any(_map_ok(m, zone) for m in found):
            return False
    return True


def build(quest_rows, giver_rows) -> tuple:
    """Quest for every ruleset row, in id order."""
    by_quest = givers(giver_rows)
    out = []
    for row in quest_rows or ():
        quest_id = _int(row.get("quest"))
        if not quest_id or not in_ruleset(row, by_quest.get(quest_id)):
            continue
        zone = _zone(row.get("sort"))
        out.append(
            Quest(
                id=quest_id,
                title=str(row.get("title") or ""),
                level=_int(row.get("level")),
                min_level=_int(row.get("min_level")),
                zone=zone,
                zone_name=zone_name(zone),
                faction=faction_of(row.get("races")),
                races=_int(row.get("races")),
                classes=_int(row.get("classes")),
                follows=_int(row.get("follows")),
            )
        )
    return tuple(sorted(out, key=lambda q: q.id))


# --- the filters -----------------------------------------------------------


def for_faction(quests, faction: str) -> tuple:
    """The quests one side can take: its own and BOTH. BOTH or "" is all."""
    if faction not in (HORDE, ALLIANCE):
        return tuple(quests)
    return tuple(q for q in quests if q.faction in (faction, BOTH))


def select(quests, faction="", zone=None, level_min=None, level_max=None) -> tuple:
    """The catalogue narrowed by side, zone id and quest level range (both
    ends included). A scaling quest (level -1) passes any level range."""
    out = for_faction(quests, faction)
    if zone is not None:
        out = tuple(q for q in out if q.zone == zone)
    if level_min is not None:
        out = tuple(q for q in out if q.level < 0 or q.level >= level_min)
    if level_max is not None:
        out = tuple(q for q in out if q.level <= level_max)
    return out


# --- read once per process -------------------------------------------------

_CATALOGUE: tuple | None = None


def load(read) -> tuple:
    """The catalogue. `read(sql)` returns rows; the answer is kept for the
    process once both reads return rows, and an empty read is tried again."""
    global _CATALOGUE
    if _CATALOGUE is not None:
        return _CATALOGUE
    quest_rows = read(QUESTS_SQL) or []
    giver_rows = read(GIVERS_SQL) or []
    found = build(quest_rows, giver_rows)
    if quest_rows and giver_rows:
        _CATALOGUE = found
    return found


def forget() -> None:
    """Drop the kept catalogue (tests)."""
    global _CATALOGUE
    _CATALOGUE = None
