"""The guild's social layer: members ask in guild chat, free guildmates answer (#568, #569).

WHY THIS EXISTS. Decided in #521: nothing in a guild is assigned like a unit.
A member with a real need says so in guild chat ("Anyone up for The Deadmines?
Need a tank and a healer. Hoping for Cape of the Black Baron."), guildmates who
are free and would gain answer yes in chat, and the coordinator only turns an
ask and its yeses into a group. guildrun.py keeps the doors, the level fit, the
coverage and shield gates, the finder row and the learning record; this module
replaces only its picking of members.

WHO ASKS. A free member (guildrun.why_not, and not mid-job) with a real need at
a door that fits its own level and its guild's side (guildrun.fitting_doors over
GUILD_DOORS): a boss drop it can use now that scores higher for its spec than
what it wears (gearscore, gated by recap.verdict for class, proficiency, armor
grade and required level), a pre-raid best-in-slot pick above all, or a quest
for that dungeon in its log. One open ask per member, ASK_MINUTES to live,
ASK_COOLDOWN_MINUTES before an ask that came to nothing is asked again, and the
existing rest after a run (guildrun's resting set). At most
MAX_OPEN_ASKS_PER_GUILD asks are open in a guild, one new one a pass, and none
while every group the realm may run is already out or waiting.

The families' campaigns post too: when a family's queue starts a dungeon, its
head says so in guild chat once. The campaign itself runs exactly as before
(the family is its own group), so that ask is recorded as ran at once, with
no guild run behind it.

WHO ANSWERS. A free member of the same guild, not the asker, not asking itself
and not already counted on another ask, whose answer is worth more than what it
is doing now:

  need   the door fits its level, within BAND_SPREAD of the asker, and it
         would gain there (an upgrade, a quest, or simply its XP band);
  help   up to HELPER_LEVELS above the door's ceiling, at most MAX_HELPERS a
         group, for goodwill and guild standing.

  worth  NEED_UPGRADE (+ PRERAID_BONUS), NEED_QUEST or XP_BAND, or HELP; less
         what it is doing (QUESTING out in the world, nothing in a capital);
         less the travel to the door (YARDS_PER_POINT on its own continent,
         OTHER_CONTINENT across the sea). Far away usually means no.

A seat comes from the tree it plays (raidroles): a tank or healer seat only to
a member that passes guildrun.tank_ready or guildrun.covered. A member whose
seat is taken answers as damage. At most ANSWERS_PER_PASS answers an ask a
pass, so yeses trickle in the way people type them.

FORMING (#569). When an ask's yeses seat a tank, a healer and three damage
dealers with the asker, the group is those members and nobody else, the tank
leads, and the run row and a chat line credit the proposer ("Auren's Deadmines
group is heading in"). A member no longer free withdraws; a surplus yes is
declined. Nothing here seats anyone who did not say yes.

PURE: rows in, a Pass out. The bridge reads, writes the rows and the chat lines,
and writes the finder row exactly as the old coordinator did.
"""

from __future__ import annotations

import math
import os
import zlib
from dataclasses import dataclass, field

import campaignplan
import gearscore
import gearupgrades
import guildrun
import recap

ENV_SWITCH = "GUILD_SOCIAL"
SOURCE = "overseer:guildsocial"

# --- pacing -------------------------------------------------------------------

ASK_MINUTES = 10
# A filled ask waits for the realm's run spacing; it is given this much longer.
FILLED_GRACE_MINUTES = 10
ASK_COOLDOWN_MINUTES = 15
MAX_OPEN_ASKS_PER_GUILD = 2
NEW_ASKS_PER_PASS = 1
ANSWERS_PER_PASS = 2

# --- who may answer -----------------------------------------------------------

MAX_HELPERS = 2
HELPER_LEVELS = 10

# --- what an answer is worth --------------------------------------------------

NEED_UPGRADE = 3.0
PRERAID_BONUS = 1.0
NEED_QUEST = 2.5
XP_BAND = 2.0
HELP = 1.5
QUESTING = 1.0
YARDS_PER_POINT = 1500.0
OTHER_CONTINENT = 2.5
MAX_TRAVEL = 4.0
# A drop is an upgrade when it scores this much over what it replaces.
MIN_GAIN_SHARE = 0.1

# Capitals: a member standing in one is idle, so its time is worth nothing.
# Stormwind, Ironforge, Darnassus, Orgrimmar, Thunder Bluff, Undercity,
# Silvermoon, the Exodar.
CAPITAL_ZONES = frozenset({1519, 1537, 1657, 1637, 1638, 1497, 3487, 3557})

TANK, HEALER, DPS = "tank", "healer", "dps"
SEATS = (TANK, HEALER, DPS, DPS, DPS)
NEED, HELPS = "need", "help"

# Ask and answer states, as the tables hold them.
OPEN, FILLED, RAN, EXPIRED, CANCELLED = "open", "filled", "ran", "expired", "cancelled"
YES, SEATED, DECLINED, WITHDRAWN = "yes", "seated", "declined", "withdrawn"
LIVE_ASKS = (OPEN, FILLED)
# Why a member is held that passes in a moment: an ask or a yes waits it out
# rather than closing over it.
PASSING = frozenset({"in combat"})

KIND_DUNGEON = "dungeon"

ASK_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_guild_ask ("
    " id INT NOT NULL AUTO_INCREMENT,"
    " guild VARCHAR(32) NOT NULL,"
    " asker VARCHAR(12) NOT NULL,"
    " kind ENUM('dungeon','quest','battleground') NOT NULL,"
    " target VARCHAR(64) NOT NULL,"
    " target_label VARCHAR(96) NOT NULL DEFAULT '',"
    " roles_needed VARCHAR(32) NOT NULL DEFAULT '',"
    " reason VARCHAR(160) NOT NULL DEFAULT '',"
    " said VARCHAR(255) NOT NULL DEFAULT '',"
    " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " expires_at DATETIME NOT NULL,"
    " state ENUM('open','filled','ran','expired','cancelled') NOT NULL"
    " DEFAULT 'open',"
    " run_id INT NULL DEFAULT NULL,"
    " PRIMARY KEY (id), KEY idx_state (state), KEY idx_guild (guild, created_at),"
    " KEY idx_asker (asker, created_at)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

ANSWER_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_guild_answer ("
    " id INT NOT NULL AUTO_INCREMENT,"
    " ask_id INT NOT NULL,"
    " member VARCHAR(12) NOT NULL,"
    " role ENUM('tank','healer','dps') NOT NULL,"
    " stance ENUM('need','help') NOT NULL,"
    " said VARCHAR(255) NOT NULL DEFAULT '',"
    " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " state ENUM('yes','seated','declined','withdrawn') NOT NULL DEFAULT 'yes',"
    " PRIMARY KEY (id), KEY idx_ask (ask_id), KEY idx_member (member, state)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

# The asks still in play, and every ask made within the cooldown (for "one
# open ask per member" and "not again so soon").
ASKS_SQL = (
    "SELECT id, guild, asker, kind, target, target_label, roles_needed, reason, "
    "said, created_at, expires_at, state, run_id FROM overseer_guild_ask "
    "WHERE state IN ('open', 'filled') OR created_at > NOW() - INTERVAL %s MINUTE "
    "ORDER BY id"
)
ANSWERS_SQL = (
    "SELECT id, ask_id, member, role, stance, said, state FROM overseer_guild_answer "
    "WHERE ask_id IN ({holes}) ORDER BY id"
)
INSERT_ASK_SQL = (
    "INSERT INTO overseer_guild_ask (guild, asker, kind, target, target_label, "
    "roles_needed, reason, said, created_at, expires_at, state) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + INTERVAL %s MINUTE, %s)"
)
INSERT_ANSWER_SQL = (
    "INSERT INTO overseer_guild_answer (ask_id, member, role, stance, said, "
    "created_at, state) VALUES (%s, %s, %s, %s, %s, NOW(), 'yes')"
)
# Guarded on the states it moves from, so a pass that read an older table
# cannot revive an ask another pass already closed.
ASK_STATE_SQL = (
    "UPDATE overseer_guild_ask SET state = %s WHERE id = %s "
    "AND state IN ('open', 'filled')"
)
ASK_RAN_SQL = (
    "UPDATE overseer_guild_ask SET state = 'ran', run_id = %s WHERE id = %s "
    "AND state IN ('open', 'filled')"
)
ANSWER_STATE_SQL = (
    "UPDATE overseer_guild_answer SET state = %s WHERE id = %s AND state = 'yes'"
)

# What each member wears, with the stats gearscore reads and the columns
# recap.verdict reads.
_ITEM_COLUMNS = (
    "it.name AS item_name, it.Quality AS quality, it.ItemLevel AS item_level, "
    "it.RequiredLevel AS required_level, it.AllowableClass AS allowable_class, "
    "it.class, it.subclass, it.InventoryType AS inventory_type, it.armor, it.block, "
    "it.delay, it.dmg_min1, it.dmg_max1, it.holy_res, it.fire_res, it.nature_res, "
    "it.frost_res, it.shadow_res, it.arcane_res, "
    + ", ".join("it.stat_type%d, it.stat_value%d" % (n, n) for n in range(1, 11))
)
WORN_SQL = (
    "SELECT c.name, ci.slot, ii.itemEntry AS entry, " + _ITEM_COLUMNS + " "
    "FROM characters c JOIN character_inventory ci ON ci.guid = c.guid "
    "AND ci.bag = 0 AND ci.slot < 19 JOIN item_instance ii ON ii.guid = ci.item "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes})"
)
SKILLS_SQL = (
    "SELECT c.name, cs.skill, cs.value FROM characters c "
    "JOIN character_skills cs ON cs.guid = c.guid WHERE c.name IN ({holes})"
)
# A dungeon quest in the log, not yet complete (status 3): QuestSortID is the
# dungeon's own zone (campaignplan.Run.zone).
QUESTS_SQL = (
    "SELECT c.name, q.ID AS quest, q.LogTitle AS title, q.QuestSortID AS zone "
    "FROM character_queststatus s JOIN characters c ON c.guid = s.guid "
    "JOIN acore_world.quest_template q ON q.ID = s.quest "
    "WHERE s.status = 3 AND c.name IN ({holes}) AND q.QuestSortID IN ({zones})"
)
# The bosses of each door's map, and their loot (map_server's dungeon plan
# reads, narrowed to green and better). The world does not change under a
# running bridge, so these are read once.
ENCOUNTERS_SQL = (
    "SELECT DISTINCT cr.map AS map_id, ie.creditEntry AS creature, ct.name "
    "FROM acore_world.instance_encounters ie "
    "JOIN acore_world.creature_template ct ON ct.entry = ie.creditEntry "
    "JOIN acore_world.creature cr ON cr.id = ie.creditEntry "
    "WHERE ie.creditType = 0 AND cr.map IN ({holes})"
)
LOOT_SQL = (
    "SELECT clt.Item, ct.entry AS creature, " + _ITEM_COLUMNS + " "
    "FROM acore_world.creature_loot_template clt "
    "JOIN acore_world.creature_template ct ON ct.lootid = clt.Entry "
    "JOIN acore_world.item_template it ON it.entry = clt.Item "
    "WHERE clt.Reference = 0 AND it.Quality >= 2 AND ct.entry IN "
    "(SELECT DISTINCT id FROM acore_world.creature WHERE map IN ({holes})) "
    "AND ct.entry IN (SELECT creditEntry FROM acore_world.instance_encounters "
    "WHERE creditType = 0)"
)
# The families' campaigns: the dungeon each queue is running now, and since
# when, so the head says so once per start.
CAMPAIGNS_SQL = (
    "SELECT q.family, q.keyword, q.started_at, g.name AS guild_name, "
    "(SELECT COUNT(*) FROM overseer_roster r "
    "WHERE r.family = q.family COLLATE utf8mb4_unicode_ci "
    "AND r.enabled = 1) AS size FROM overseer_dungeon_queue q "
    "JOIN characters c ON c.name = q.family "
    "JOIN guild_member gm ON gm.guid = c.guid JOIN guild g ON g.guildid = gm.guildid "
    "WHERE q.status = 'active' AND q.started_at IS NOT NULL"
)


def enabled(environ=None) -> bool:
    """On unless GUILD_SOCIAL says off. Off, the old coordinator picks."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


# --- the rows ---------------------------------------------------------------------


@dataclass(frozen=True)
class Ask:
    """One overseer_guild_ask row."""

    id: int
    guild: str
    asker: str
    kind: str
    target: str
    target_label: str
    roles_needed: tuple
    reason: str
    said: str
    created_at: object
    expires_at: object
    state: str
    run_id: int | None = None


@dataclass(frozen=True)
class Answer:
    """One overseer_guild_answer row."""

    id: int
    ask_id: int
    member: str
    role: str
    stance: str
    said: str
    state: str


def roles_text(roles) -> str:
    return ",".join(roles)


def roles_of(text) -> tuple:
    return tuple(r for r in (p.strip() for p in str(text or "").split(",")) if r)


def ask_from_row(row: dict) -> Ask:
    return Ask(
        id=int(row["id"]),
        guild=str(row.get("guild") or ""),
        asker=str(row.get("asker") or ""),
        kind=str(row.get("kind") or KIND_DUNGEON),
        target=str(row.get("target") or ""),
        target_label=str(row.get("target_label") or ""),
        roles_needed=roles_of(row.get("roles_needed")),
        reason=str(row.get("reason") or ""),
        said=str(row.get("said") or ""),
        created_at=row.get("created_at"),
        expires_at=row.get("expires_at"),
        state=str(row.get("state") or OPEN),
        run_id=None if row.get("run_id") is None else int(row["run_id"]),
    )


def answer_from_row(row: dict) -> Answer:
    return Answer(
        id=int(row["id"]),
        ask_id=int(row["ask_id"]),
        member=str(row.get("member") or ""),
        role=str(row.get("role") or DPS),
        stance=str(row.get("stance") or NEED),
        said=str(row.get("said") or ""),
        state=str(row.get("state") or YES),
    )


# --- what a member would gain at a door ----------------------------------------------


@dataclass(frozen=True)
class Need:
    """Something a member would gain at a door: a drop, or a quest."""

    member: str
    keyword: str
    item: str
    entry: int = 0
    gain: float = 0.0
    preraid: bool = False
    slot: str = ""
    quest: int = 0

    @property
    def rank(self) -> tuple:
        """Best first: a pre-raid pick, then a drop by its gain, then a quest."""
        return (not self.preraid, self.quest != 0, -self.gain, self.keyword, self.item)


@dataclass(frozen=True)
class Mate:
    """One guild member as the social layer sees it."""

    member: guildrun.Member
    x: float | None = None
    y: float | None = None
    # recap.family_members' dict: by_slot, armour_grade, skills.
    gear: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.member.name


def gear_by_name(member_rows: list, worn_rows: list, skill_rows: list) -> dict:
    """name -> recap's member dict (by_slot, armour_grade, skills) for
    every member row (_GUILD_RUN_MEMBERS_SQL), from WORN_SQL and SKILLS_SQL."""
    chars = [
        {"name": r["name"], "level": r.get("level"), "class": r.get("class_id")}
        for r in member_rows
        if r.get("name")
    ]
    names = [c["name"] for c in chars]
    return {
        m["name"]: m for m in recap.family_members(chars, worn_rows, names, skill_rows)
    }


def mate_from_row(row: dict, gear: dict | None = None) -> Mate | None:
    member = guildrun.member_from_row(row)
    if member is None:
        return None

    def coord(key):
        value = row.get(key)
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    return Mate(member=member, x=coord("pos_x"), y=coord("pos_y"), gear=gear or {})


def spec_of(member: guildrun.Member) -> str | None:
    spec, _note = gearupgrades.choose_spec(
        guildrun.raidroles_class_name(member.class_id), member.played_tree or None
    )
    return spec


def _preraid_ids(spec: str | None) -> frozenset:
    if not spec:
        return frozenset()
    lists = gearscore.load_spec(spec)["lists"].get("preraid", {}).get("slots", {})
    return frozenset(int(i) for entries in lists.values() for i in entries)


# Weapon inventory types -> the gearscore slot whose weapon DPS weight applies.
_WEAPON_SLOT = {13: "main_hand", 21: "main_hand", 17: "two_hand", 22: "off_hand"}
_WEAPON_SLOT.update({15: "ranged", 25: "ranged", 26: "ranged", 28: "ranged"})
_SLOT_WORDS = {
    0: "head",
    1: "neck",
    2: "shoulders",
    4: "chest",
    5: "belt",
    6: "legs",
    7: "boots",
    8: "bracers",
    9: "gloves",
    10: "ring",
    11: "ring",
    12: "trinket",
    13: "trinket",
    14: "cloak",
    15: "weapon",
    16: "off hand",
    17: "ranged slot",
}
_USABLE = (recap.UPGRADE, recap.EMPTY, recap.SIDEGRADE, recap.WORSE)


def drop_gain(drop: dict, gear: dict, spec: str, level: int) -> tuple:
    """(gain, slot index) for a drop against what is worn, by the spec's
    score; (0.0, None) when the member cannot use it now (recap.verdict)."""
    who = dict(gear)
    who.setdefault("name", "")
    who.setdefault("by_slot", {})
    verdict = recap.verdict(drop, who)
    if verdict.get("verdict") not in _USABLE:
        return 0.0, None
    slots = recap.slots_for(drop.get("inventory_type"))
    key = _WEAPON_SLOT.get(int(drop.get("inventory_type") or 0), "")
    new = gearscore.score(gearscore.stats_from_row(drop), spec, level, key)
    weakest = None
    for index in slots:
        row = who["by_slot"].get(index)
        old = (
            0.0
            if row is None
            else gearscore.score(gearscore.stats_from_row(row), spec, level, key)
        )
        if weakest is None or old < weakest[0]:
            weakest = (old, index)
    if weakest is None:
        return 0.0, None
    old, index = weakest
    if new <= 0 or new <= old * (1.0 + MIN_GAIN_SHARE):
        return 0.0, None
    return new - old, index


def index_drops(encounter_rows: list, loot_rows: list) -> dict:
    """map id -> [(loot row, boss name)], each boss's drop once."""
    boss_name: dict = {}
    bosses_on: dict = {}
    for row in encounter_rows:
        creature = int(row["creature"])
        boss_name[creature] = str(row.get("name") or "")
        bosses_on.setdefault(int(row["map_id"]), set()).add(creature)
    loot: dict = {}
    for row in loot_rows:
        loot.setdefault(int(row["creature"]), []).append(row)
    out: dict = {}
    for map_id, creatures in bosses_on.items():
        seen = set()
        for creature in sorted(creatures):
            for row in loot.get(creature, []):
                item = int(row.get("Item") or 0)
                if item in seen:
                    continue
                seen.add(item)
                out.setdefault(map_id, []).append((row, boss_name[creature]))
    return out


def level_doors(level: int, all_doors: list, faction: str) -> list:
    """The doors one member's own level fits, on its guild's side."""
    return guildrun.fitting_doors([int(level)], all_doors, faction)


def needs_for(
    mate: Mate, drops_by_map: dict, all_doors: list, faction: str, quests=()
) -> list:
    """Everything this member would gain at a door its level fits, best first.

    `quests` are (quest id, title, zone) rows from its log (QUESTS_SQL).
    """
    member = mate.member
    spec = spec_of(member)
    preraid = _preraid_ids(spec)
    doors = level_doors(member.level, all_doors, faction)
    zones = guildrun_zones()
    out = []
    for door in doors:
        best = None
        if spec:
            for drop, _boss in drops_by_map.get(door.map_id, []):
                gain, index = drop_gain(drop, mate.gear, spec, member.level)
                if index is None:
                    continue
                entry = int(drop.get("Item") or 0)
                need = Need(
                    member=member.name,
                    keyword=door.keyword,
                    item=str(drop.get("item_name") or "item %d" % entry),
                    entry=entry,
                    gain=round(gain, 1),
                    preraid=entry in preraid,
                    slot=_SLOT_WORDS.get(index, ""),
                )
                if best is None or need.rank < best.rank:
                    best = need
        if best is not None:
            out.append(best)
        for quest, title, zone in quests:
            if zones.get(door.keyword) == int(zone):
                out.append(
                    Need(
                        member=member.name,
                        keyword=door.keyword,
                        item=str(title),
                        quest=int(quest),
                    )
                )
                break
    out.sort(key=lambda n: n.rank)
    return out


def guildrun_zones() -> dict:
    """door keyword -> the dungeon's quest zone (campaignplan.Run.zone)."""
    return {run.keyword: int(run.zone) for run in campaignplan.RUNS}


# --- free, and what its time is worth ----------------------------------------------


def role_of(member: guildrun.Member) -> str:
    """The seat a member plays by its tree, gated as guildrun gates it."""
    if member.fit(guildrun.TANK) == "spec" and guildrun.tank_ready(member):
        return TANK
    if member.fit(guildrun.HEALER) == "spec" and guildrun.covered(member):
        return HEALER
    return DPS


def can_take(member: guildrun.Member, seat: str) -> bool:
    if seat == TANK:
        return bool(member.fit(guildrun.TANK)) and guildrun.tank_ready(member)
    if seat == HEALER:
        return bool(member.fit(guildrun.HEALER)) and guildrun.covered(member)
    return True


def activity_value(mate: Mate) -> float:
    """What the member is doing now is worth: nothing in a capital, QUESTING
    anywhere else in the world."""
    return 0.0 if mate.member.zone_id in CAPITAL_ZONES else QUESTING


def travel_cost(mate: Mate, door, entrances: dict) -> float:
    """The walk to the door: YARDS_PER_POINT on the same continent,
    OTHER_CONTINENT across the sea, never more than MAX_TRAVEL. A door or a
    position nobody can read costs nothing extra."""
    spot = (entrances or {}).get(str(door.map_id))
    if not spot:
        return 0.0
    if int(spot.get("map", -1)) != int(mate.member.map_id):
        return OTHER_CONTINENT
    if mate.x is None or mate.y is None:
        return 0.0
    yards = math.hypot(float(spot["x"]) - mate.x, float(spot["y"]) - mate.y)
    return min(MAX_TRAVEL, yards / YARDS_PER_POINT)


def stance_of(mate: Mate, door, asker_level: int, faction: str, needs: list) -> tuple:
    """(stance, value, need) for this member and this door, or ("", 0, None)."""
    level = int(mate.member.level)
    if level > door.ceiling:
        if level <= door.ceiling + HELPER_LEVELS:
            return HELPS, HELP, None
        return "", 0.0, None
    if not guildrun.fitting_doors([level], [door], faction):
        return "", 0.0, None
    if abs(level - int(asker_level)) > guildrun.BAND_SPREAD:
        return "", 0.0, None
    here = [n for n in needs if n.keyword == door.keyword]
    if here:
        need = here[0]
        if need.quest:
            return NEED, NEED_QUEST, need
        return NEED, NEED_UPGRADE + (PRERAID_BONUS if need.preraid else 0.0), need
    return NEED, XP_BAND, None


def worth(mate: Mate, door, value: float, entrances: dict) -> float:
    """What answering yes is worth over what the member is doing now."""
    return value - activity_value(mate) - travel_cost(mate, door, entrances)


# --- the words ------------------------------------------------------------------------


def _pick(options: tuple, *keys) -> str:
    """A stable choice among templates, varied by who and what."""
    seed = zlib.crc32("|".join(str(k) for k in keys).encode("utf-8"))
    return options[seed % len(options)]


def roles_words(roles) -> str:
    """("tank", "dps", "dps") -> "a tank and 2 dps"."""
    counts = {seat: list(roles).count(seat) for seat in (TANK, HEALER, DPS)}
    parts = []
    for seat in (TANK, HEALER, DPS):
        n = counts[seat]
        if not n:
            continue
        if seat == DPS:
            parts.append("%d dps" % n if n > 1 else "a dps")
        else:
            parts.append(("a %s" % seat) if n == 1 else "%d %ss" % (n, seat))
    if not parts:
        return "nobody"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


_ASK_ITEM = (
    "Anyone up for {place}? Need {roles}. Hoping for {item}.",
    "LF{n}M {place}, need {roles}. After {item} for my {slot}.",
    "{place} run? Looking for {roles}, I'm after {item}.",
    "Who wants to do {place}? Need {roles}. Want to try for {item}.",
    "Heading to {place} if I can get a group: {roles}. {item} would be huge for me.",
)
_ASK_QUEST = (
    "Anyone want to do {place}? I've got {item} to finish, need {roles}.",
    "{place} for {item}? Need {roles}.",
    "LF{n}M {place}, need {roles}. Still on {item}.",
)
_ASK_CAMPAIGN = (
    "{place} tonight with the family. Wish us luck!",
    "Family's heading into {place}. Shout if you want anything from there.",
    "We're running {place} again. See you on the other side.",
)
_ANSWER = {
    (TANK, NEED): (
        "I'll tank {place}.",
        "Tank here, count me in.",
        "I can tank, inv me.",
    ),
    (HEALER, NEED): (
        "I'll heal {place}.",
        "Healer here, I'm in.",
        "I can heal, been wanting to go there.",
    ),
    (DPS, NEED): (
        "I'm in!",
        "Count me in for {place}.",
        "Sure, I'll come. Need the xp.",
    ),
    (TANK, HELPS): ("I can tank it for you, I've outleveled it.",),
    (HEALER, HELPS): ("I'll come heal, nothing in there for me but happy to help.",),
    (DPS, HELPS): (
        "I'll come help, I know the way.",
        "Nothing there for me but sure, I'll help out.",
    ),
}
_ANSWER_ITEM = (
    "I'm in, I want {item} too.",
    "Count me in, {item} would be nice.",
    "Yes! I need {item}.",
)
_FORMED_BY_OTHER = (
    "{proposer}'s {place} group is heading in. I'll lead.",
    "{proposer}'s {place} group is full, heading in now.",
)
_FORMED_BY_SELF = (
    "Got everyone, heading into {place} now. Thanks all!",
    "Group's full, {place} here we come.",
)
_EXPIRED = (
    "Never mind {place}, maybe later.",
    "No luck for {place}, I'll try again later.",
)


def _fit(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def ask_line(asker: str, door, roles, need: Need | None) -> str:
    n = len(roles)
    words = roles_words(roles)
    if need is not None and need.quest:
        template = _pick(_ASK_QUEST, asker, door.keyword, need.quest)
    else:
        template = _pick(_ASK_ITEM, asker, door.keyword, need.entry if need else 0)
    return _fit(
        template.format(
            place=door.place,
            roles=words,
            n=n,
            item=need.item if need else "",
            slot=(need.slot if need and need.slot else "gear"),
        ),
        255,
    )


def ask_reason(need: Need | None) -> str:
    if need is None:
        return ""
    if need.quest:
        return _fit("the quest %s" % need.item, 160)
    if need.preraid:
        return _fit("%s, a pre-raid pick for my %s slot" % (need.item, need.slot), 160)
    return _fit("%s for my %s slot" % (need.item, need.slot or "gear"), 160)


def answer_line(member: str, role: str, stance: str, door, need: Need | None) -> str:
    if stance == NEED and need is not None and not need.quest:
        template = _pick(_ANSWER_ITEM, member, door.keyword)
    else:
        template = _pick(_ANSWER[(role, stance)], member, door.keyword)
    return _fit(template.format(place=door.place, item=need.item if need else ""), 255)


def short_place(place: str) -> str:
    """ "The Deadmines" -> "Deadmines", for "Auren's Deadmines group"."""
    return place[4:] if place.startswith("The ") else place


def formed_line(proposer: str, tank: str, door) -> str:
    if proposer == tank:
        template = _pick(_FORMED_BY_SELF, proposer, door.keyword)
    else:
        template = _pick(_FORMED_BY_OTHER, proposer, door.keyword)
    # "Auren's Deadmines group", but "heading into The Deadmines".
    place = door.place if proposer == tank else short_place(door.place)
    return _fit(template.format(proposer=proposer, place=place), 255)


def expired_line(asker: str, door) -> str:
    return _fit(_pick(_EXPIRED, asker, door.keyword).format(place=door.place), 255)


# --- one pass ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Post:
    """A new ask to write, and say in guild chat."""

    guild: str
    asker: str
    kind: str
    target: str
    target_label: str
    roles_needed: str
    reason: str
    said: str
    state: str = OPEN
    minutes: int = ASK_MINUTES


@dataclass(frozen=True)
class Reply:
    """A new yes to write, and say in guild chat."""

    ask_id: int
    member: str
    role: str
    stance: str
    said: str


@dataclass(frozen=True)
class Formation:
    """An ask turned into a group: the asker and the yeses that seat it."""

    ask: Ask
    door: object
    composition: object  # guildrun.Composition
    seated: tuple  # answer ids
    declined: tuple  # answer ids
    helpers: tuple  # names
    said: str

    @property
    def key(self) -> str:
        """The learning record's composition key, with its helpers counted."""
        base = self.composition.key
        return base + ("+%dhelp" % len(self.helpers) if self.helpers else "")

    @property
    def band(self) -> str:
        helpers = set(self.helpers)
        levels = [m.level for m in self.composition.members if m.name not in helpers]
        return guildrun.band_of(levels)


@dataclass(frozen=True)
class Pass:
    """What one pass writes."""

    expire: tuple = ()  # (ask id, asker, line or "") the asker says the line
    cancel: tuple = ()  # ask ids
    withdraw: tuple = ()  # answer ids
    filled: tuple = ()  # ask ids whose seats are complete but cannot form yet
    posts: tuple = ()
    replies: tuple = ()
    form: Formation | None = None
    notes: tuple = ()


def _past(when, now) -> bool:
    return when is not None and now is not None and when <= now


def _minutes_since(when, now) -> float:
    if when is None or now is None:
        return 1e9
    return (now - when).total_seconds() / 60.0


def seat(ask: Ask, answers: list, free: dict, door, faction: str):
    """(Composition, seated answers, declined answers, helpers) from the
    asker and its yeses only, or None when they do not seat a group.

    `free` is name -> Member for the members free right now. The asker takes
    the seat its tree plays; the tank leads.
    """
    asker = free.get(ask.asker)
    if asker is None:
        return None
    yes = [a for a in answers if a.state == YES and a.member in free]
    yes.sort(key=lambda a: a.id)
    helpers = [a for a in yes if a.stance == HELPS][:MAX_HELPERS]
    helper_ids = {a.id for a in helpers}
    yes = [a for a in yes if a.stance != HELPS or a.id in helper_ids]
    mine = role_of(asker)
    seats = {TANK: None, HEALER: None}
    damage = []
    if mine in seats:
        seats[mine] = (asker, None)
    else:
        damage.append((asker, None))
    for answer in yes:
        member = free[answer.member]
        if (
            answer.role in seats
            and seats[answer.role] is None
            and can_take(member, answer.role)
        ):
            seats[answer.role] = (member, answer)
        elif answer.role == DPS and len(damage) < 3:
            damage.append((member, answer))
    if seats[TANK] is None or seats[HEALER] is None or len(damage) < 3:
        return None
    chosen = [seats[TANK], seats[HEALER]] + damage[:3]
    used = {a.id for _m, a in chosen if a is not None}
    helper_names = tuple(
        m.name for m, a in chosen if a is not None and a.stance == HELPS
    )
    beneficiaries = [m.level for m, a in chosen if a is None or a.stance != HELPS]
    if not guildrun.fitting_doors(beneficiaries, [door], faction):
        return None
    comp = guildrun.Composition(
        seats[TANK][0], seats[HEALER][0], tuple(m for m, _a in damage[:3])
    )
    declined = tuple(a.id for a in answers if a.state == YES and a.id not in used)
    return comp, tuple(sorted(used)), declined, helper_names


def plan_pass(
    mates: list,
    held: dict,
    asks: list,
    answers: list,
    needs: dict,
    all_doors: list,
    entrances: dict,
    now,
    room: int,
    can_form: bool,
    campaigns=(),
) -> Pass:
    """One pass of the social layer.

    mates     every online guild member read this pass (Mate), free or not
    held      name -> why_not reason for the members who are not free; a
              member mid-job is held by the caller with its own reason
    asks      Ask rows: the live ones and every one made within the cooldown
    answers   Answer rows for those asks
    needs     name -> [Need], best first (needs_for)
    room      groups the realm may still start (cap less runs out and filled
              asks); no new ask is posted without room
    can_form  whether the realm's spacing lets a group start this pass
    campaigns family campaign rows (CAMPAIGNS_SQL)
    """
    free_mates = {m.name: m for m in mates if m.name not in held}
    free = {name: m.member for name, m in free_mates.items()}
    doors = {d.keyword: d for d in all_doors}
    by_ask: dict = {}
    for answer in answers:
        by_ask.setdefault(answer.ask_id, []).append(answer)
    factions = {
        guild: guildrun.faction_of([m.member for m in mates if m.member.guild == guild])
        for guild in {m.member.guild for m in mates}
    }
    live = [a for a in asks if a.state in LIVE_ASKS and a.kind == KIND_DUNGEON]
    expire, cancel, withdraw, filled, notes = [], [], [], [], []
    still: list = []
    for ask in live:
        door = doors.get(ask.target)
        if ask.state == OPEN and _past(ask.expires_at, now):
            line = expired_line(ask.asker, door) if door and ask.asker in free else ""
            expire.append((ask.id, ask.asker, line))
            continue
        if ask.state == FILLED and _minutes_since(ask.expires_at, now) > (
            FILLED_GRACE_MINUTES
        ):
            expire.append((ask.id, ask.asker, ""))
            continue
        if door is None or (
            ask.asker not in free and held.get(ask.asker, "offline") not in PASSING
        ):
            cancel.append(ask.id)
            continue
        still.append(ask)
    closed = {e[0] for e in expire} | set(cancel)
    for ask in live:
        if ask.id in closed:
            withdraw += [a.id for a in by_ask.get(ask.id, []) if a.state == YES]
    for ask in still:
        withdraw += [
            a.id
            for a in by_ask.get(ask.id, [])
            if a.state == YES
            and a.member not in free
            and held.get(a.member, "offline") not in PASSING
        ]
    gone = set(withdraw)

    # Who is spoken for: an asker with a live ask, a member with a live yes.
    asking = {a.asker for a in still}
    counted = {
        ans.member
        for a in still
        for ans in by_ask.get(a.id, [])
        if ans.state == YES and ans.id not in gone
    }

    # Forming first: an ask whose yeses seat a group.
    form = None
    for ask in still:
        door = doors[ask.target]
        current = [a for a in by_ask.get(ask.id, []) if a.id not in gone]
        seated = seat(ask, current, free, door, factions.get(ask.guild, ""))
        if seated is None:
            continue
        comp, used, declined, helpers = seated
        if not can_form or form is not None:
            if ask.state == OPEN:
                filled.append(ask.id)
            continue
        form = Formation(
            ask=ask,
            door=door,
            composition=comp,
            seated=used,
            declined=declined,
            helpers=helpers,
            said=formed_line(ask.asker, comp.tank.name, door),
        )
    complete = set(filled) | ({form.ask.id} if form else set())

    # Answers: free members who would gain, to the asks still short.
    replies = []
    answered_now: set = set()
    for ask in sorted(still, key=lambda a: a.id):
        if ask.id in complete or ask.asker not in free:
            continue
        door = doors[ask.target]
        faction = factions.get(ask.guild, "")
        current = [a for a in by_ask.get(ask.id, []) if a.id not in gone]
        taken = [a.role for a in current if a.state == YES]
        open_seats = list(ask.roles_needed)
        for role in taken:
            if role in open_seats:
                open_seats.remove(role)
        helpers = sum(1 for a in current if a.state == YES and a.stance == HELPS)
        before = {a.member for a in current}
        asker_level = free[ask.asker].level
        options = []
        for name, mate in free_mates.items():
            if mate.member.guild != ask.guild or name == ask.asker:
                continue
            if name in asking or name in counted or name in answered_now:
                continue
            if name in before:
                continue
            stance, value, need = stance_of(
                mate, door, asker_level, faction, needs.get(name, [])
            )
            if not stance:
                continue
            net = worth(mate, door, value, entrances)
            if net <= 0:
                continue
            # The scarce seats first: a tank or healer for an open seat of
            # its own answers before another damage dealer.
            scarce = 0 if _seat_for(mate.member, open_seats) in (TANK, HEALER) else 1
            options.append((scarce, -net, name, mate, stance, need))
        options.sort(key=lambda o: o[:3])
        added = 0
        for _scarce, _neg, name, mate, stance, need in options:
            if added >= ANSWERS_PER_PASS or not open_seats:
                break
            if stance == HELPS and helpers >= MAX_HELPERS:
                continue
            role = _seat_for(mate.member, open_seats)
            if not role:
                continue
            open_seats.remove(role)
            if stance == HELPS:
                helpers += 1
            replies.append(
                Reply(
                    ask_id=ask.id,
                    member=name,
                    role=role,
                    stance=stance,
                    said=answer_line(name, role, stance, door, need),
                )
            )
            answered_now.add(name)
            added += 1

    # Asks: the free member with the strongest need, per guild, while the
    # realm has room for another group.
    posts = []
    open_by_guild: dict = {}
    for ask in still:
        open_by_guild[ask.guild] = open_by_guild.get(ask.guild, 0) + 1
    recent = {
        a.asker
        for a in asks
        if a.state not in LIVE_ASKS
        and _minutes_since(a.created_at, now) < ASK_COOLDOWN_MINUTES
    }
    doors_asked = {(a.guild, a.target) for a in still}
    # Every live ask may become a group, so they count against the room.
    spare = max(0, int(room) - len(still))
    for guild in sorted({m.member.guild for m in free_mates.values()}):
        if spare <= 0:
            break
        if open_by_guild.get(guild, 0) >= MAX_OPEN_ASKS_PER_GUILD:
            continue
        faction = factions.get(guild, "")
        choices = []
        for name, mate in free_mates.items():
            if mate.member.guild != guild:
                continue
            if name in asking or name in counted or name in answered_now:
                continue
            if name in recent:
                continue
            for need in needs.get(name, []):
                door = doors.get(need.keyword)
                if door is None or (guild, door.keyword) in doors_asked:
                    continue
                if not guildrun.fitting_doors([mate.member.level], [door], faction):
                    continue
                choices.append((need.rank, name, mate, need, door))
                break
        choices.sort(key=lambda c: (c[0], c[1]))
        for _rank, name, mate, need, door in choices[:NEW_ASKS_PER_PASS]:
            mine = role_of(mate.member)
            roles = list(SEATS)
            roles.remove(mine)
            posts.append(
                Post(
                    guild=guild,
                    asker=name,
                    kind=KIND_DUNGEON,
                    target=door.keyword,
                    target_label=door.place[:96],
                    roles_needed=roles_text(roles),
                    reason=ask_reason(need),
                    said=ask_line(name, door, roles, need),
                )
            )
            spare -= 1

    posts += campaign_posts(campaigns, asks, doors, now)
    if not posts and not replies and form is None and still:
        notes.append("%d ask(s) open, nobody new to answer" % len(still))
    return Pass(
        expire=tuple(expire),
        cancel=tuple(cancel),
        withdraw=tuple(withdraw),
        filled=tuple(filled),
        posts=tuple(posts),
        replies=tuple(replies),
        form=form,
        notes=tuple(notes),
    )


def _seat_for(member: guildrun.Member, open_seats: list) -> str:
    """The seat this member answers for: its own tree's seat when open, a
    tank or healer seat its class can take untalented, else damage."""
    mine = role_of(member)
    if mine in open_seats:
        return mine
    if not member.played_tree:
        for seat_name in (TANK, HEALER):
            if seat_name in open_seats and can_take(member, seat_name):
                return seat_name
    return DPS if DPS in open_seats else ""


def campaign_posts(campaigns, asks: list, doors: dict, now) -> list:
    """A family head says its campaign's dungeon in guild chat, once, within
    ASK_MINUTES of the queue starting it. The family is its own group and its
    campaign runs as before, so the ask is recorded as ran at once (no guild
    run row: run_id stays NULL) and nobody is asked to answer it."""
    out = []
    for row in campaigns or ():
        head = str(row.get("family") or "")
        keyword = str(row.get("keyword") or "")
        guild = str(row.get("guild_name") or "")
        started = row.get("started_at")
        door = doors.get(keyword)
        if not head or not guild or door is None:
            continue
        if _minutes_since(started, now) >= ASK_MINUTES:
            continue
        said_since = any(
            a.asker == head
            and a.target == keyword
            and a.created_at is not None
            and started is not None
            and a.created_at >= started
            for a in asks
        )
        if said_since:
            continue
        out.append(
            Post(
                guild=guild,
                asker=head[:12],
                kind=KIND_DUNGEON,
                target=keyword,
                target_label=door.place[:96],
                roles_needed="",
                reason=_fit("%s's family campaign" % head, 160),
                said=_fit(
                    _pick(_ASK_CAMPAIGN, head, keyword).format(place=door.place), 255
                ),
                state=RAN,
            )
        )
    return out
