"""The guild coordinator: a bot guild's own five-mans, by the dungeon finder.

WHY THIS EXISTS. Only the two families are directed. The rest of each bot
guild, most of seventy-one members, levels alone and never groups, while the
operator's goal is the whole guild getting ready for Molten Core. The dungeon
finder is the way in now (mod-overseer's finder rung), so a guild group can be
sent into a dungeon without a walk, a crossing or a coordinate. This module
decides who goes where; mod-overseer's `finder-run` verb forms the party,
queues it, arms mod-dungeon-clear inside and reads the run back to its end.

WHAT IT DECIDES, and what Jev decides.

  groups       Online members of one guild, not in a family, a group or an
               instance, alive (no corpse: a ghost still reports health),
               out of combat and rested (COOLDOWN_MINUTES since their last
               run that went in), sorted by level. Nobody is picked until the
               worldserver has been up SETTLE_SECONDS, so a restart's
               logouts and logins are over first. A group is five within
               BAND_SPREAD levels of each other with a tank and a healer by the
               talent tree each plays (raidroles), or by the seat the raid plan
               gave them (overseer_raid_spec) when no talent is spent yet.
  composition  When the pool can seat the group more than one way (another
               tank, another healer), up to three compositions are offered.
               Jev chooses (a Choice with a confidence); the prior below is
               the heuristic.
  dungeon      Every door mod-overseer has a portal for whose band fits the
               group (campaignplan.RUNS, council's floors) and whose finder
               minimum every member meets. Jev chooses; the prior is the
               heuristic.

THE LEARNING LOOP. Every run is a row in overseer_guild_run, beside the
decision that made it: the options, Jev's answer and confidence, who acted,
and the outcome (cleared, wiped, abandoned, timed out, not entered), deaths,
time inside, bosses, loot and gear. `rates` folds the last ROLLING runs of each
(dungeon, level band, composition) into a smoothed success rate, (cleared + 1)
/ (runs + 2). Each option Jev is shown says its own record, and the heuristic
picks by that rate once an option has MIN_SAMPLES runs behind it, else by level
fit. Below Jev's confidence floor, or with no answer, the heuristic acts, so
the prior is what the coordinator falls back on.

GUARDRAILS. Off unless GUILD_RUNS is on. At most MAX_GROUPS groups in flight
(the realm runs two map-update threads, sized for its two continents; each
dungeon is one more active map), and each group makes its five always active
(playerbots' AllowActive exempts dungeons), far under the 250-bot throttle.
One new group per FORM_EVERY_SECONDS realm-wide, except that a run the module
refused over one named member is formed again at once without that member
(BENCH_MINUTES), up to MAX_SWAPS times in a row. mod-overseer has its own
switch and cap (Overseer.GuildFinder.Enable, .MaxGroups) behind this one.

WITH THE SOCIAL LAYER ON (GUILD_SOCIAL, the default), none of the picking
above runs: a group forms only from a member's ask in guild chat and the yeses
it drew (guildsocial.py, #569), and this module lends it the doors, the level
fit, the coverage and shield gates, the finder row and the record. Off, the
picking above is the fallback; the bridge never runs both.

PURE: facts in, groups, questions and judgments out. The bridge reads and
writes; the only I/O here is the Jev client the caller hands in.
"""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, field, replace

import campaignplan
import council
import dungeonpath
import jev
import raidroles

# --- the switch and the limits ---------------------------------------------

ENV_SWITCH = "GUILD_RUNS"
MAX_GROUPS = 2
# The operator wants every guild group that forms to run at once (2026-10-05:
# "let all groups run stuff at the same time, no limits"). Thirty covers every
# member of both guilds in five-man groups; GUILD_RUNS_MAX sets the live cap.
HARD_MAX_GROUPS = 30
FORM_EVERY_SECONDS = 300
COOLDOWN_MINUTES = 40
BAND_SPREAD = 4
# The guide minimum: a group goes in when its average reaches the door's floor,
# the lowest level public guides recommend. Attempts are how the guild learns,
# and the decision tools learn from every one; holding groups home for more
# levels starves that loop (operator, 2026-09-28).
LEVEL_MARGIN = 0
ROLLING = 20
MIN_SAMPLES = 3
MAX_OPTIONS = 3
MAX_DUNGEONS = 4
DEFAULT_GUILDS = ("Cave", "Bonkers")
# The continents a queue may start from: never from inside an instance.
OPEN_WORLD_MAPS = (0, 1, 530)
# A run no row has ended by now is lost (a worldserver restart, a sweep).
LOST_AFTER_MINUTES = 180
# Nobody is picked until the worldserver has been up this long. The first run
# after a restart went to five members the old process had just logged out,
# two seconds after the new one started; random bots log in over minutes.
SETTLE_SECONDS = 600
# A member the module refused (dead, locked out, already queued) sits out this
# long, and the run is formed again without them rather than waiting out
# FORM_EVERY_SECONDS. MAX_SWAPS refusals in a row fall back to the spacing, so
# a refusal no swap can fix cannot turn into a run a minute.
BENCH_MINUTES = 15
MAX_SWAPS = 3

SOURCE = "overseer:guildrun"

KIND_DUNGEON = "guild_dungeon"
KIND_COMPOSITION = "guild_composition"
DEFAULT_THRESHOLD = 0.6

TANK, HEALER, DPS = raidroles.SEAT_TANK, raidroles.SEAT_HEALER, raidroles.SEAT_DAMAGE

# Run states and outcomes, as overseer_guild_run holds them.
QUEUED, INSIDE, ENDED = "queued", "inside", "ended"
CLEARED = "cleared"
OUTCOMES = (
    CLEARED,
    "wiped",
    "abandoned",
    "timed out",
    "not entered",
    "refused",
    "lost",
)
# The outcomes of a run that went in. Only these say anything about the
# dungeon, and only these rest the members afterwards.
WENT_IN = (CLEARED, "wiped", "abandoned", "timed out")


def enabled(environ=None) -> bool:
    """On only when GUILD_RUNS says so: this sends bots into dungeons."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


def _int_env(env, key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(str(env.get(key, "") or default).strip())
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class Limits:
    max_groups: int = MAX_GROUPS
    form_every_seconds: int = FORM_EVERY_SECONDS
    cooldown_minutes: int = COOLDOWN_MINUTES
    guilds: tuple = DEFAULT_GUILDS


def limits(environ=None) -> Limits:
    """The guardrails, from the environment, each clamped to a sane range."""
    env = os.environ if environ is None else environ
    guilds = tuple(
        g.strip()
        for g in str(env.get("GUILD_RUNS_GUILDS", "") or "").split(",")
        if g.strip()
    )
    return Limits(
        max_groups=_int_env(env, "GUILD_RUNS_MAX", MAX_GROUPS, 0, HARD_MAX_GROUPS),
        form_every_seconds=_int_env(
            env, "GUILD_RUNS_EVERY_SECONDS", FORM_EVERY_SECONDS, 0, 86400
        ),
        cooldown_minutes=_int_env(
            env, "GUILD_RUNS_COOLDOWN_MINUTES", COOLDOWN_MINUTES, 0, 1440
        ),
        guilds=guilds or DEFAULT_GUILDS,
    )


# --- who can go -------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    """One online guild member as the coordinator sees them."""

    name: str
    guild: str
    level: int
    class_id: int
    tree: str = ""
    # The raid plan's tree for this member (overseer_raid_spec), which the
    # module spends talent points toward; used when no talent is spent yet.
    target_tree: str = ""
    map_id: int = 0
    grouped: bool = False
    in_combat: bool = False
    alive: bool = True
    online: bool = True
    race: int = 0
    zone_id: int = 0
    # Average item level of what it wears (None when unread).
    gear_ilvl: float | None = None
    # Armor slots it wears (head to back, no shirt), and whether it holds a
    # main-hand weapon; None when unread.
    worn_slots: int | None = None
    has_weapon: bool | None = None
    # A shield worn in the off hand; None when unread.
    has_shield: bool | None = None
    # Whether it knows the spell its class tanks with (raidroles.TANK_KIT:
    # Defensive Stance, Bear Form); None when unread.
    has_tank_kit: bool | None = None

    @property
    def played_tree(self) -> str:
        return self.tree or self.target_tree

    def plays(self, seat: str) -> bool:
        """Does this member actually PLAY the seat: its spent talents are a tree
        that tanks or heals. The raid plan's target tree does not count, and a
        class that only could tank or heal does not either (#575): Cave seated
        Enhancement shamans, Retribution paladins and Balance druids in the tank
        and healer seats, they played as damage dealers, and dungeon clear
        logged "no tank in the party" in 7 of 9 of its runs."""
        return bool(self.tree) and raidroles.fits_seat(self.class_id, self.tree, seat)

    def deals_damage(self) -> bool:
        """May this member fill a damage seat: its spent talents are not a tree
        that tanks or heals. A bot plays its tree whatever seat the coordinator
        gave it (a Protection warrior runs `tank`, `tank assist` and `pull`; a
        Holy or Discipline priest runs `heal`), so a tank or healer tree in a
        damage seat is a second tank pulling and taunting against the first, or
        a damage seat that heals. Guild runs 247, 256 and 265 each took one or
        two Protection warriors as damage dealers and all three wiped; run 271
        took a Holy priest and its pulls lasted twice as long as run 272's."""
        return not (self.plays(TANK) or self.plays(HEALER))

    def fit(self, seat: str) -> str:
        """ "spec" when the tree plays the seat, "class" when only the class
        can, "" when it cannot take the seat at all."""
        if not raidroles.can_seat(self.class_id, seat):
            return ""
        return (
            "spec"
            if raidroles.fits_seat(self.class_id, self.played_tree, seat)
            else "class"
        )


def _alive(row: dict) -> bool:
    """A released ghost reports a health of 1 and has a corpse row, and
    Player::IsAlive is false for it. A corpse row alone is not death: one
    resurrected without the corpse turning to bones keeps its row while it
    fights at full health."""
    health = int(row.get("health") or 0)
    return health > 1 or (health == 1 and not row.get("has_corpse"))


def alive_or_unread(row: dict) -> bool:
    """_alive, except a row with no health (no fresh snapshot: the member is
    offline) is taken as alive, so it reads as offline and not as dead."""
    return row.get("health") is None or _alive(row)


def _optional(row: dict, key: str, cast):
    """`cast(row[key])`, or None when the read had no value for it."""
    value = row.get(key)
    return None if value is None else cast(value)


def member_from_row(row: dict) -> Member | None:
    """A Member from one bridge read, or None when the row cannot say who."""
    name = str(row.get("name") or "")
    if not name:
        return None
    try:
        level = int(row.get("level") or 0)
        class_id = int(row.get("class_id") or 0)
        map_id = int(row.get("map_id") or 0)
    except (TypeError, ValueError):
        return None
    tree = raidroles.tree_of(class_id, row.get(raidroles.KEY))
    return Member(
        name=name,
        guild=str(row.get("guild_name") or ""),
        level=level,
        class_id=class_id,
        tree=tree,
        target_tree=str(row.get("target_tree") or ""),
        map_id=map_id,
        grouped=bool(row.get("group_leader")),
        in_combat=bool(row.get("in_combat")),
        alive=_alive(row),
        online=bool(row.get("online", 1)),
        race=int(row.get("race") or 0),
        zone_id=int(row.get("zone_id") or 0),
        gear_ilvl=_optional(row, "gear_ilvl", float),
        worn_slots=_optional(row, "worn_slots", int),
        has_weapon=_optional(row, "has_weapon", bool),
        has_shield=_optional(row, "has_shield", bool),
        has_tank_kit=_optional(row, "has_tank_kit", bool),
    )


# why_not's word for a member already in a party. A class quest party's own
# members read it too (classparty.py) and stay free to their ask.
GROUPED = "already in a group"
# why_not's word for a member that owes a class quest (classquest.owed).
OWES_CLASS_QUEST = "owes a class quest"


def why_not(
    member: Member,
    busy: set,
    resting: set,
    family: set,
    benched=frozenset(),
    owed=frozenset(),
) -> str:
    """Why this member cannot be picked now, or "".

    `owed` is the names of the members that owe a class quest: the operator's
    rule is that a class quest comes before any dungeon, so none is picked."""
    if member.name in family:
        return "a family member"
    if not member.online:
        return "offline"
    if member.name in busy:
        return "in a guild run"
    if member.name in resting:
        return "resting after a run"
    if member.name in benched:
        return "refused a run just now"
    if member.name in owed:
        return OWES_CLASS_QUEST
    # Where a member stands is read before its gear: a member left inside a
    # dungeon read as "gear too weak", which hid 50 of them (2026-10-04).
    if member.map_id not in OPEN_WORLD_MAPS:
        return "inside an instance"
    if not member.alive:
        return "dead"
    if member.in_combat:
        return "in combat"
    if member.grouped:
        return GROUPED
    return ""


def free_members(
    rows: list[dict],
    busy: set[str],
    resting: set[str],
    family: set[str],
    benched: frozenset[str] = frozenset(),
    owed: frozenset[str] = frozenset(),
) -> tuple[list[Member], dict[str, int]]:
    """The free guild roster and the reasons each other member was held."""
    free = []
    held = {}
    for row in rows:
        member = member_from_row(row)
        if member is None:
            continue
        why = why_not(member, busy, resting, family, benched, owed)
        if why:
            held[why] = held.get(why, 0) + 1
            continue
        free.append(member)
    return free, held


def settling(uptime_seconds, settle_seconds: int = SETTLE_SECONDS) -> bool:
    """Whether the worldserver is too newly started to pick anyone. An
    unknown uptime (no uptime table) does not hold the coordinator back."""
    if uptime_seconds is None:
        return False
    return int(uptime_seconds) < settle_seconds


def refused_member(why: str) -> str:
    """The member a module refusal names ("'Daidanden' is dead"), or ""
    when the refusal is about the realm or the door rather than one member."""
    text = str(why or "")
    if not text.startswith("'"):
        return ""
    end = text.find("'", 1)
    return text[1:end] if end > 1 else ""


# A refusal over something that passes in seconds benches nobody: a member
# refused for being in a fight is free again the moment the fight ends.
PASSING_REFUSALS = ("in combat",)


def benched(recent: list) -> set:
    """Members named by refusals in `recent` (overseer_guild_run rows ended
    within BENCH_MINUTES), except a refusal that passes (PASSING_REFUSALS)."""
    out = set()
    for row in recent:
        if str(row.get("outcome") or "") != "refused":
            continue
        if any(word in str(row.get("why") or "") for word in PASSING_REFUSALS):
            continue
        name = refused_member(row.get("why"))
        if name:
            out.add(name)
    return out


def swap_now(latest: list, max_swaps: int = MAX_SWAPS) -> bool:
    """Whether to form again without waiting FORM_EVERY_SECONDS. `latest` is
    the newest runs of any state, newest first. True when the newest was
    refused over one named member and fewer than `max_swaps` such refusals
    came in a row; a run formed since (queued, inside) heads the list and
    ends the streak."""
    streak = 0
    for row in latest:
        if str(row.get("outcome") or "") != "refused" or not refused_member(
            row.get("why")
        ):
            break
        streak += 1
    return 0 < streak < max_swaps


# --- the doors ----------------------------------------------------------------


@dataclass(frozen=True)
class Door:
    keyword: str
    place: str
    floor: int
    ceiling: int
    map_id: int
    finder_floor: int
    # The level the tank and healer seats must stand at (carries); 0 unread.
    carry_floor: int = 0


# THE SEATS THAT CARRY A GROUP STAND AT ITS BOSSES' LEVEL. Measured on wow-dev
# (2026-10-07 to 10-09): 0 of 57 guild runs cleared the Deadmines. 60 of the 68
# Deadmines runs ever made sat a tank or a healer under its bosses' level 20
# (level-17 to 19 priests and an 18 to 19 paladin tank), and the tank died
# first in 33 of the 51 runs with deaths read. The same line splits the doors
# the guilds do clear: Ragefire runs whose tank and healer both stood at its
# bosses' 16 cleared 21 of 38, those under it 10 of 89; Wailing Caverns at its
# bosses' 20, 3 of 11 against 3 of 111. A damage dealer goes in at the door's
# floor as before; only the two seats that carry the group wait for the level.
#
# The bosses' level is the highest credited encounter on the door's map
# (BOSS_LEVELS_SQL), never more than the top of the door's first band (floor
# plus BAND_SPREAD, so the Graveyard is not held to the Cathedral's bosses on
# the Monastery's shared map) or its ceiling (a level-60 door's skull bosses
# read 62 and 63).
BOSS_LEVELS_SQL = (
    "SELECT cr.map AS map_id, MAX(ct.maxlevel) AS level "
    "FROM acore_world.instance_encounters ie "
    "JOIN acore_world.creature_template ct ON ct.entry = ie.creditEntry "
    "JOIN acore_world.creature cr ON cr.id = ie.creditEntry "
    "WHERE ie.creditType = 0 GROUP BY cr.map"
)


def carry_floor(boss_level: int, floor: int, ceiling: int) -> int:
    """The level a door's tank and healer must stand at: its bosses', capped
    at the top of its first band and at its ceiling; 0 (no hold) unread."""
    if int(boss_level) <= 0:
        return 0
    return min(int(boss_level), int(floor) + BAND_SPREAD, int(ceiling))


def doors(finder_floors: dict | None = None, boss_levels: dict | None = None) -> list:
    """Every door mod-overseer has a portal for, with the level it wants
    (council's floor), the level it is outgrown at (campaignplan's ceiling),
    the finder's own minimum (dungeon_access_template, by map, read by
    the bridge; the council floor when unread) and the level its tank and
    healer must stand at (carry_floor, off BOSS_LEVELS_SQL by map)."""
    floors = finder_floors or {}
    bosses = boss_levels or {}
    out = []
    for run in campaignplan.RUNS:
        if run.keyword in dungeonpath.WITHHELD_DOORS:
            continue
        floor = council.door_floor(run.keyword)
        out.append(
            Door(
                keyword=run.keyword,
                place=council.keyword_place(run.keyword),
                floor=floor,
                ceiling=int(run.ceiling),
                map_id=run.map_id,
                finder_floor=int(floors.get(run.map_id, floor)),
                carry_floor=carry_floor(
                    int(bosses.get(run.map_id, 0)), floor, int(run.ceiling)
                ),
            )
        )
    return out


def carries(member: Member, door: Door) -> bool:
    """May this member take the tank or healer seat at this door: at or over
    its carry_floor. An unread bosses' level holds nobody."""
    return int(member.level) >= int(door.carry_floor)


def band_of(levels) -> str:
    """The five-level band a group's average falls in: "15-19"."""
    levels = [int(x) for x in levels]
    if not levels:
        return "?"
    mean = sum(levels) / len(levels)
    low = int(mean) // 5 * 5
    return "%d-%d" % (low, low + 4)


ALLIANCE_RACES = frozenset({1, 3, 4, 7, 11})
HORDE_RACES = frozenset({2, 5, 6, 8, 10})


def faction_of(members) -> str:
    """ "Alliance", "Horde" or "" off the members' own races."""
    races = {int(m.race) for m in members if m.race}
    if races and races <= ALLIANCE_RACES:
        return "Alliance"
    if races and races <= HORDE_RACES:
        return "Horde"
    return ""


# THE OTHER FACTION'S HOME GROUND, where its guards kill a member on sight.
# Measured on wow-dev (2026-09-28): 60 of 159 guild deaths in 30 minutes were
# Alliance members killed by Razor Hill Grunts (level 30 to 32) in Durotar,
# after Cave runs into Ragefire Chasm, a door inside Orgrimmar, left them on
# the Horde side. Zones: Durotar and Orgrimmar; Elwynn Forest and Stormwind.
HOSTILE_HOME_ZONES = {"Alliance": frozenset({14, 1637}), "Horde": frozenset({12, 1519})}
# The dungeon maps whose doors stand inside a capital (council._inside_capital).
HOSTILE_CAPITAL_DUNGEONS = {"Alliance": frozenset({389}), "Horde": frozenset({34})}


# THE ONLY NON-CONTINENT MAP A MEMBER LIVES ON ALONE: Acherus, the death
# knights' starting land, is a map of its own and no dungeon.
SOLO_HOME_MAPS = frozenset({609})


# Alterac Valley, Warsong Gulch and Arathi Basin. A member playing one for
# honor (pvpgear, #589) is not stranded: a hearthstone out of a battleground
# would end its game and mark it a deserter.
BATTLEGROUND_MAPS = frozenset({30, 489, 529})


def left_inside(member: Member) -> bool:
    """Alone, ungrouped, inside a dungeon: what a lost or timed-out guild run
    leaves behind. Measured on wow-dev (2026-10-04): 30 Bonkers members alone
    in Ragefire Chasm and 20 Cave members alone in Wailing Caverns, none
    grouped, there since the runs of 2026-09-30 and 2026-10-01 ended without
    them. Nothing walks a random bot out of an instance, and why_not holds
    every one of them from the next run. A battleground is not a dungeon."""
    return (
        member.map_id not in OPEN_WORLD_MAPS
        and member.map_id not in SOLO_HOME_MAPS
        and member.map_id not in BATTLEGROUND_MAPS
    )


def stranded(member: Member, faction: str) -> bool:
    """A living member standing on the other faction's home ground, inside a
    dungeon whose door is in the other faction's capital, or left alone inside
    any dungeon (left_inside): it hearths home."""
    if not member.alive or member.in_combat or member.grouped:
        return False
    if left_inside(member):
        return True
    if not faction:
        return False
    return member.zone_id in HOSTILE_HOME_ZONES.get(
        faction, ()
    ) or member.map_id in HOSTILE_CAPITAL_DUNGEONS.get(faction, ())


def stranded_names(members: list, busy: set) -> list:
    """Names of members stranded on the other faction's ground (`stranded`),
    each judged by its own guild's faction, leaving out anyone in a run."""
    factions = {
        guild: faction_of([m for m in members if m.guild == guild])
        for guild in {m.guild for m in members}
    }
    return [
        m.name
        for m in members
        if m.name not in busy and stranded(m, factions.get(m.guild, ""))
    ]


# THE DOORS EACH SIDE USES. 12 guild runs entered Ragefire Chasm and none
# cleared (wow-dev, 2026-09-28), and Cave's left its members among the Horde's
# guards. Each guild goes only to its own side's five-mans for its band.
GUILD_DOORS = {
    "Alliance": frozenset(
        {
            "deadmines", "wailing", "shadowfang", "blackfathom", "stockades",
            "scarlet", "gnomeregan", "razorfen-kraul", "razorfen-downs",
            "uldaman", "zulfarrak", "maraudon-orange", "maraudon-purple",
            "sunken-temple", "blackrock-depths", "scholomance",
        }
    ),
    "Horde": frozenset(
        {
            "ragefire", "deadmines", "wailing", "shadowfang", "blackfathom",
            "scarlet", "gnomeregan", "razorfen-kraul", "razorfen-downs",
            "uldaman", "zulfarrak", "maraudon-orange", "maraudon-purple",
            "sunken-temple", "blackrock-depths", "scholomance",
        }
    ),
}  # fmt: skip
# DOORS NEITHER SIDE IS OFFERED because mod-overseer's finder cannot resolve
# them today (FinderDungeonForDoor / ChooseFinderDungeon). Adding a keyword to
# GUILD_DOORS while it is here would queue a run the module refuses.
#   * scarlet-library, scarlet-armory, scarlet-cathedral: only the Graveyard
#     has a finder row with an entrance on map 189; the other wings share the
#     map's entrance, so the module refuses them as "the wrong one". Needs
#     lfg_dungeon_template rows for the three wings, with entrances matching
#     each door's landing, in mod-overseer's world data.
#   * dire-maul-*, lower-blackrock-spire: several finder wings share the map
#     (Dire Maul has three, the Spire has the lower and upper); whether each
#     door lands within 60 yards of its own wing's lfg_dungeon_template start
#     is not confirmed. Needs that check against the realm's world DB, then a
#     row fix in mod-overseer if a landing misses.
# Stratholme is separate: dungeonpath.WITHHELD_DOORS (mod-overseer#582).
BLOCKED_DOORS = {
    "scarlet-library": "no finder entrance for the wing",
    "scarlet-armory": "no finder entrance for the wing",
    "scarlet-cathedral": "no finder entrance for the wing",
    "lower-blackrock-spire": "finder wing match unconfirmed",
    "dire-maul-east-east": "finder wing match unconfirmed",
    "dire-maul-west-north": "finder wing match unconfirmed",
    "dire-maul-north": "finder wing match unconfirmed",
}
# NO ITEM-LEVEL GATE BELOW 60, A COVERAGE GATE FOR THE TWO SEATS THAT CARRY A
# GROUP (decided in #532, 2026-10-04). The old gate held a member out when its
# worn gear averaged more than 6 item levels under its level: on wow-dev that
# held 117 of 132 members out of the dungeons that gear them, and no guild run
# formed after 10-01. Real players run Deadmines in quest whites. A damage
# dealer goes in whatever it wears; a tank or a healer needs a main-hand weapon
# and COVERED_SLOTS of the 8 body-armor slots (head, shoulders, chest, waist,
# legs, feet, wrists, hands), because a naked tank or healer wipes the group.
#
# BODY ARMOR, NOT EVERY SLOT. The first version counted 10 of 15 slots,
# including neck, rings, trinkets and back, which a level-15 player rarely
# fills: live, every one of 21 tank-fit and 30 healer-fit members wore 4 to 7
# of the 15 and none could be seated, so no run formed at all.
COVERED_SLOTS = 4


# A WARRIOR OR PALADIN TANKS BEHIND A SHIELD (the operator, on #544). A druid
# tanks in bear form and needs none. Live 2026-10-04: 7 of 35 warriors and
# paladins in the two guilds wore one, 3 more carried one in their bags.
SHIELD_TANK_CLASSES = frozenset({1, 2})


def has_kit(member: Member) -> bool:
    """Whether the member knows the spell its class tanks with (Defensive
    Stance for a warrior, Bear Form for a druid), or needs none. An unread spell
    list is not held, as unread gear is not."""
    if not raidroles.tank_kit(member.class_id) or member.has_tank_kit is None:
        return True
    return bool(member.has_tank_kit)


def tank_ready(member: Member) -> bool:
    """May this member take the tank seat: covered, knows the spell its class
    tanks with, and a warrior or paladin wears a shield. Unread gear and an
    unread spell list are not held.

    No tank in a free window means no group forms: guildrun.compositions gives
    nothing and the social layer seats nobody, so the class quest that gives
    the spell (a mandatory one, classquest.py) is what unblocks the dungeon."""
    if not has_kit(member) or not covered(member):
        return False
    if int(member.class_id) not in SHIELD_TANK_CLASSES or member.has_shield is None:
        return True
    return bool(member.has_shield)


def covered(member: Member) -> bool:
    """May this member take a tank or healer seat? Unread gear is not held."""
    if member.worn_slots is None or member.has_weapon is None:
        return True
    return bool(member.has_weapon) and int(member.worn_slots) >= COVERED_SLOTS


def fitting_doors(levels, all_doors: list, faction: str = "") -> list:
    """The doors this set of levels fits, best fit first.

    A door inside the other faction's capital (council._other_capital) is
    never offered: its members come out among that capital's guards. A
    faction that cannot be read (no race in the snapshot, a mixed roster)
    counts as the other one, as council does, so only the doors both sides
    use are offered.

    Fits: every member at or over the finder's minimum, the average at least
    the door's floor (plus LEVEL_MARGIN), and nobody past its ceiling.
    Best fit is the door whose band's middle is nearest the average.
    """
    levels = [int(x) for x in levels]
    if not levels:
        return []
    low, high = min(levels), max(levels)
    mean = sum(levels) / len(levels)
    allowed = GUILD_DOORS.get(faction) or frozenset.intersection(*GUILD_DOORS.values())
    out = []
    for door in all_doors:
        if council._other_capital(door.map_id, faction):
            continue
        if door.keyword not in allowed:
            continue
        if low < door.finder_floor:
            continue
        if mean < door.floor + LEVEL_MARGIN:
            continue
        if high > door.ceiling:
            continue
        out.append(door)
    out.sort(
        key=lambda d: (abs((d.floor + d.ceiling) / 2.0 - mean), d.floor, d.keyword)
    )
    return out[:MAX_DUNGEONS]


# --- compositions ------------------------------------------------------------


@dataclass(frozen=True)
class Composition:
    """Five members in their seats: the tank leads."""

    tank: Member
    healer: Member
    dps: tuple

    @property
    def members(self) -> tuple:
        return (self.tank, self.healer) + tuple(self.dps)

    @property
    def names(self) -> tuple:
        return tuple(m.name for m in self.members)

    @property
    def key(self) -> str:
        """The shape the learning loop keys on: how well the tank and the
        healer fit their seats. Small on purpose, so a rate has runs behind
        it within a day."""
        return "%s-tank/%s-healer" % (self.tank.fit(TANK), self.healer.fit(HEALER))

    @property
    def levels(self) -> list:
        return [m.level for m in self.members]

    def describe(self) -> str:
        def one(m: Member, seat: str) -> str:
            return "%s (level %d %s%s, %s)" % (
                m.name,
                m.level,
                raidroles_class_name(m.class_id),
                (" " + m.played_tree) if m.played_tree else "",
                seat,
            )

        parts = [one(self.tank, "tank"), one(self.healer, "healer")]
        parts += [one(m, "damage") for m in self.dps]
        return "; ".join(parts)

    def command(self, keyword: str) -> str:
        """The mod-overseer row, targeted at the tank."""
        return "finder-run %s %s %s" % (
            keyword,
            self.healer.name,
            " ".join(m.name for m in self.dps),
        )


_CLASS_NAMES = {
    1: "warrior",
    2: "paladin",
    3: "hunter",
    4: "rogue",
    5: "priest",
    6: "death knight",
    7: "shaman",
    8: "mage",
    9: "warlock",
    11: "druid",
}


def raidroles_class_name(class_id: int) -> str:
    return _CLASS_NAMES.get(int(class_id), "adventurer")


def _seat_rank(member: Member, seat: str) -> int:
    fit = member.fit(seat)
    return 0 if fit == "spec" else 1 if fit == "class" else 9


def _dps_rank(member: Member) -> int:
    """Damage dealers first, then anyone whose tree is not a tank or healer."""
    if member.fit(TANK) == "spec" or member.fit(HEALER) == "spec":
        return 2
    return 0 if member.played_tree else 1


def compositions(window: list) -> list:
    """Up to MAX_OPTIONS ways to seat five of `window`, best first.

    The best tank by fit, the best healer by fit, and three damage dealers
    from the rest; then the same with the next tank, and with the next
    healer, so each alternative changes one seat. A window that cannot seat a
    tank and a healer who fit at least by class gives nothing.
    """
    tanks = sorted(
        (m for m in window if m.plays(TANK) and tank_ready(m)),
        key=lambda m: (_seat_rank(m, TANK), -m.level, m.name),
    )
    healers = sorted(
        (m for m in window if m.plays(HEALER) and covered(m)),
        key=lambda m: (_seat_rank(m, HEALER), -m.level, m.name),
    )
    out = []
    seen = set()

    def build(tank: Member, healer: Member):
        if tank.name == healer.name:
            return None
        rest = [
            m
            for m in window
            if m.name not in (tank.name, healer.name) and m.deals_damage()
        ]
        rest.sort(key=lambda m: (_dps_rank(m), -m.level, m.name))
        if len(rest) < 3:
            return None
        return Composition(tank, healer, tuple(rest[:3]))

    pairs = []
    for t in tanks[:2]:
        for h in healers[:2]:
            pairs.append((t, h))
    for tank, healer in pairs:
        comp = build(tank, healer)
        if comp is None or frozenset(comp.names) in seen:
            continue
        seen.add(frozenset(comp.names))
        out.append(comp)
        if len(out) >= MAX_OPTIONS:
            break
    return out


@dataclass(frozen=True)
class Pool:
    """The members one group is drawn from: one guild, one level band."""

    guild: str
    members: tuple

    @property
    def levels(self) -> list:
        return [m.level for m in self.members]


def pools(members: list, all_doors: list) -> list:
    """Windows of free members, one guild at a time, highest level first.

    A window is everyone within BAND_SPREAD levels below its top member. A
    window that can seat a group and fits a door is a pool; its members are
    then left out of the windows below it, so two pools never share a member.
    """
    out = []
    for guild in sorted({m.guild for m in members}):
        free = sorted(
            (m for m in members if m.guild == guild), key=lambda m: (-m.level, m.name)
        )
        taken: set = set()
        for top in free:
            if top.name in taken:
                continue
            window = [
                m
                for m in free
                if m.name not in taken
                and top.level - BAND_SPREAD <= m.level <= top.level
            ]
            if len(window) < 5:
                continue
            comps = compositions(window)
            if not comps:
                continue
            if not fitting_doors(comps[0].levels, all_doors, faction_of(window)):
                continue
            out.append(Pool(guild=guild, members=tuple(window)))
            taken.update(m.name for m in window)
    return out


# --- the record, and the prior it gives ------------------------------------------


@dataclass(frozen=True)
class Rate:
    runs: int
    cleared: int
    deaths: int

    @property
    def smoothed(self) -> float:
        return (self.cleared + 1.0) / (self.runs + 2.0)

    def words(self) -> str:
        if not self.runs:
            return "no runs yet"
        return "%d cleared of %d run%s (%.0f%%), %.1f deaths a run" % (
            self.cleared,
            self.runs,
            "" if self.runs == 1 else "s",
            100.0 * self.cleared / self.runs,
            self.deaths / float(self.runs),
        )


NO_RATE = Rate(0, 0, 0)


def rates(rows: list, rolling: int = ROLLING) -> dict:
    """(keyword, band, composition) -> Rate over the last `rolling` ended
    runs of each. Rows are overseer_guild_run rows, newest first. A run that
    never entered (refused, not entered, lost) says nothing about the dungeon
    and is not counted."""
    counted: dict = {}
    out: dict = {}
    for row in rows:
        if str(row.get("state") or "") != ENDED:
            continue
        outcome = str(row.get("outcome") or "")
        if outcome not in WENT_IN:
            continue
        key = (
            str(row.get("keyword") or ""),
            str(row.get("band") or ""),
            str(row.get("composition") or ""),
        )
        n = counted.get(key, 0)
        if n >= rolling:
            continue
        counted[key] = n + 1
        rate = out.get(key, NO_RATE)
        out[key] = Rate(
            rate.runs + 1,
            rate.cleared + (1 if outcome == CLEARED else 0),
            rate.deaths + int(row.get("deaths") or 0),
        )
    return out


def door_rate(table: dict, keyword: str, band: str, composition: str = "") -> Rate:
    """The record for a door: this composition's when it has one, else every
    composition's at this band together."""
    if composition:
        exact = table.get((keyword, band, composition))
        if exact and exact.runs:
            return exact
    runs = cleared = deaths = 0
    for (k, b, _c), rate in table.items():
        if k == keyword and b == band:
            runs += rate.runs
            cleared += rate.cleared
            deaths += rate.deaths
    return Rate(runs, cleared, deaths)


# THE RECORD BY SHAPE, COUNTING THE RUNS THAT NEVER GOT IN (#583, #584). The
# social layer asks for a door before any group exists, so the only group it
# can judge is the shape the asker's guild can seat: a real tank or not, a real
# healer or not (Member.plays). `rates` drops a run the finder turned away, yet
# Ragefire at 10 to 14 ran 92 times and 72 never got in; that is the strongest
# record there is, so it is counted here. A door is closed for a shape after
# FAILING_RUNS runs in with no clear, or TURNED_AWAY_RUNS turn-aways in a row.
# Only RECORD_DAYS of runs count: the record moves only when the door is run,
# so a door closed for a shape opens again a week after its last run.
RECORD_DAYS = 7
TURNED_AWAY = ("not entered", "refused")
TURNED_AWAY_RUNS = 5


def shape_key(real_tank: bool, real_healer: bool) -> str:
    """The shape a record is kept under, in Composition.key's words."""
    return "%s-tank/%s-healer" % (
        "spec" if real_tank else "class",
        "spec" if real_healer else "class",
    )


@dataclass(frozen=True)
class ShapeRecord:
    """One (door, band, shape)'s runs: those that went in, and those the
    finder turned away (`streak` of them newest first, before any run in)."""

    went_in: int = 0
    cleared: int = 0
    deaths: int = 0
    turned_away: int = 0
    streak: int = 0

    @property
    def rate(self) -> Rate:
        return Rate(self.went_in, self.cleared, self.deaths)

    @property
    def failing(self) -> bool:
        return (
            self.went_in >= FAILING_RUNS and self.cleared == 0
        ) or self.streak >= TURNED_AWAY_RUNS

    def words(self) -> str:
        text = self.rate.words()
        if self.turned_away:
            text += "; the dungeon finder turned %s away" % _n(
                self.turned_away, "group"
            )
        return text


NO_SHAPE_RECORD = ShapeRecord()


def _shape_row(row: dict, oldest) -> tuple | None:
    """(key, entered) for a run the shape record counts, or None: not ended,
    lost, or older than `oldest`. The helper suffix ("+1help") is dropped
    from the composition, since helpers do not change the shape."""
    if str(row.get("state") or "") != ENDED:
        return None
    outcome = str(row.get("outcome") or "")
    entered = outcome in WENT_IN
    if not entered and outcome not in TURNED_AWAY:
        return None
    ended_at = row.get("ended_at")
    if oldest is not None and ended_at is not None and ended_at < oldest:
        return None
    key = (
        str(row.get("keyword") or ""),
        str(row.get("band") or ""),
        str(row.get("composition") or "").split("+", 1)[0],
    )
    return key, entered


def _counted(rec: ShapeRecord, row: dict, entered: bool, streaking: bool):
    """`rec` with one more run: in (and how it went) or turned away."""
    if entered:
        outcome = str(row.get("outcome") or "")
        return replace(
            rec,
            went_in=rec.went_in + 1,
            cleared=rec.cleared + (1 if outcome == CLEARED else 0),
            deaths=rec.deaths + int(row.get("deaths") or 0),
        )
    return replace(
        rec, turned_away=rec.turned_away + 1, streak=rec.streak + int(streaking)
    )


def shape_records(
    rows: list, now=None, rolling: int = ROLLING, days: int = RECORD_DAYS
) -> dict:
    """(keyword, band, shape) -> ShapeRecord over the last `rolling` ended runs
    of each within `days` of `now` (every run when `now` or a row's ended_at is
    unknown). Rows are overseer_guild_run rows, newest first; a lost run says
    nothing either way and is skipped (_shape_row)."""
    counted: dict = {}
    got_in: set = set()
    out: dict = {}
    oldest = None if now is None else now - datetime.timedelta(days=days)
    for row in rows:
        seen = _shape_row(row, oldest)
        if seen is None:
            continue
        key, entered = seen
        if counted.get(key, 0) >= rolling:
            continue
        counted[key] = counted.get(key, 0) + 1
        rec = out.get(key, NO_SHAPE_RECORD)
        out[key] = _counted(rec, row, entered, key not in got_in)
        if entered:
            got_in.add(key)
    return out


def cleared_doors(rows: list) -> set:
    """(guild, keyword) for every door a guild has cleared in `rows`
    (overseer_guild_run rows). Guilds clear dungeons in level order, so a
    door a guild has cleared ranks below one it has not (guildsocial)."""
    return {
        (str(r.get("guild") or ""), str(r.get("keyword") or ""))
        for r in rows
        if str(r.get("outcome") or "") == "cleared" and r.get("guild")
    }


def comp_rate(table: dict, composition: str, band: str) -> Rate:
    runs = cleared = deaths = 0
    for (_k, b, c), rate in table.items():
        if c == composition and b == band:
            runs += rate.runs
            cleared += rate.cleared
            deaths += rate.deaths
    return Rate(runs, cleared, deaths)


# --- the plan for one pool, and the heuristic -------------------------------------


@dataclass(frozen=True)
class Plan:
    """Everything one decision is made from."""

    pool: Pool
    options: tuple  # compositions, labelled "a", "b", "c"
    doors: tuple  # Door
    band: str
    table: dict = field(default_factory=dict)

    @property
    def labels(self) -> tuple:
        return tuple("abc"[i] for i in range(len(self.options)))

    def composition(self, label: str) -> Composition:
        return self.options[self.labels.index(label)]


def plan_for(pool: Pool, all_doors: list, table: dict) -> Plan | None:
    comps = compositions(list(pool.members))
    if not comps:
        return None
    best = [
        door
        for door in fitting_doors(comps[0].levels, all_doors, faction_of(pool.members))
        if carries(comps[0].tank, door) and carries(comps[0].healer, door)
    ]
    if not best:
        return None
    return Plan(
        pool=pool,
        options=tuple(comps),
        doors=tuple(best),
        band=band_of(comps[0].levels),
        table=dict(table),
    )


# A DOOR THAT KEEPS FAILING IS RETIRED AT THAT BAND (#575). Wailing Caverns
# was 0 cleared of 48 runs over 30 days, and the heuristic kept re-picking it by
# level fit because no single composition had MIN_SAMPLES runs. A door with at
# least FAILING_RUNS runs at the band, pooled over compositions, and no clear is
# skipped while any other door fits.
#
# IT IS A PREFERENCE, NOT A BAN. When the failing door is the ONLY door that
# fits the band it is still chosen: the record is a rolling window that only
# moves when the door is run, so a hard ban would retire it for good, and the
# failures behind it were made by groups #575 found misseated.
FAILING_RUNS = 6


def failing_doors(plan: Plan) -> set:
    """Keywords of doors that have failed FAILING_RUNS times at this band with
    no clear. Callers prefer other doors over these; see FAILING_RUNS."""
    out = set()
    for door in plan.doors:
        rate = door_rate(plan.table, door.keyword, plan.band)
        if rate.runs >= FAILING_RUNS and rate.cleared == 0:
            out.add(door.keyword)
    return out


# AN UNTRIED DOOR CAN WIN (#583, #584). Every door is scored by its smoothed
# rate at the band, and a door with fewer than MIN_SAMPLES runs scores the
# untried prior (Rate.smoothed of no runs, 0.5) instead of being left out. So a
# door at 0 cleared of 10 loses to a door nobody has run, where before the
# known failure won every time (Wailing Caverns, 0 of 48). The level fit
# breaks a tie.
UNTRIED_PRIOR = NO_RATE.smoothed


def _door_score(rate: Rate) -> float:
    return rate.smoothed if rate.runs >= MIN_SAMPLES else UNTRIED_PRIOR


def heuristic_door(plan: Plan, composition: Composition) -> tuple:
    """(keyword, why). The best score among the doors that fit (_door_score:
    the smoothed rate at this band, or the untried prior under MIN_SAMPLES
    runs), the closest level fit on a tie. A failing door (failing_doors) is
    skipped while another door fits."""
    failing = failing_doors(plan)
    healthy = [d for d in plan.doors if d.keyword not in failing]
    # Only failing doors fit: still go (FAILING_RUNS says why).
    doors = healthy if healthy else list(plan.doors)
    scored = []
    for door in doors:
        rate = door_rate(plan.table, door.keyword, plan.band, composition.key)
        scored.append((_door_score(rate), door, rate))
    # Stable: on a tie the earlier door, the closer level fit, stays first.
    scored.sort(key=lambda t: -t[0])
    _score, door, rate = scored[0]
    if rate.runs >= MIN_SAMPLES:
        return door.keyword, "the best record at band %s: %s" % (
            plan.band,
            rate.words(),
        )
    if door.keyword != doors[0].keyword:
        return door.keyword, "untried at band %s, over records that lose" % plan.band
    return door.keyword, "the closest level fit (%s wants %d to %d)" % (
        door.place,
        door.floor,
        door.ceiling,
    )


def heuristic_composition(plan: Plan) -> tuple:
    """(label, why). The best record at this band with MIN_SAMPLES runs,
    else the first option, which seats the best-fitting tank and healer."""
    best = None
    for label, comp in zip(plan.labels, plan.options, strict=True):
        rate = comp_rate(plan.table, comp.key, plan.band)
        if rate.runs >= MIN_SAMPLES and (best is None or rate.smoothed > best[0]):
            best = (rate.smoothed, label, rate)
    first = plan.labels[0]
    first_rate = comp_rate(plan.table, plan.options[0].key, plan.band)
    if (
        best
        and best[1] != first
        and (first_rate.runs < MIN_SAMPLES or best[0] > first_rate.smoothed)
    ):
        return best[1], "the best record at band %s: %s" % (plan.band, best[2].words())
    return first, "the best-fitting tank and healer (%s)" % plan.options[0].key


# --- Jev ------------------------------------------------------------------------


def policy(kind: str, environ=None) -> jev.Policy:
    """Act by default, at a 0.6 floor.

    AN AGREEMENT BELOW THE FLOOR IS THE HEURISTIC'S (#584). #356 credited Jev
    with any agreement; #583 then found 30 Wailing Caverns runs recorded
    dungeon_by=both at confidence 0.02 to 0.64, a coin flip or worse, so a read
    of overseer_guild_run by chooser credited Jev with picks it was not sure
    of. The action is the same either way; only the record changes, and the
    `agree` column still says the two answers matched."""
    return jev.policy(
        kind,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=DEFAULT_THRESHOLD,
    )


def state_for(plan: Plan) -> dict:
    members = plan.pool.members
    return {
        "guild": plan.pool.guild,
        "level_band": plan.band,
        "pool": [
            {
                "name": m.name,
                "level": m.level,
                "class": raidroles_class_name(m.class_id),
                "talent_tree": m.played_tree or "none yet",
            }
            for m in members
        ],
        "how_runs_are_judged": (
            "cleared = the dungeon finder marks the dungeon finished; a wipe, an "
            "abandoned run or a timeout is a failure"
        ),
    }


def questions(plan: Plan) -> dict:
    """Two Choices in one request: the composition and the dungeon."""
    comp_criteria = {}
    for label, comp in zip(plan.labels, plan.options, strict=True):
        comp_criteria[label] = "%s. Shape %s; record at band %s: %s" % (
            comp.describe(),
            comp.key,
            plan.band,
            comp_rate(plan.table, comp.key, plan.band).words(),
        )
    door_criteria = {}
    for door in plan.doors:
        door_criteria[door.keyword] = (
            "%s, for levels %d to %d (the dungeon finder lets in level %d and up); "
            "record for this band: %s"
            % (
                door.place,
                door.floor,
                door.ceiling,
                door.finder_floor,
                door_rate(plan.table, door.keyword, plan.band).words(),
            )
        )
    return {
        "composition": jev.choice(
            "A World of Warcraft guild is sending five of its members into a "
            "dungeon together through the dungeon finder. `pool` is who is free "
            "at this level band. Choose the group most likely to clear a dungeon "
            "without dying: a tank whose talents are for tanking and a healer "
            "whose talents are for healing matter most, and each option says how "
            "groups of its shape have done before.",
            comp_criteria,
        ),
        "dungeon": jev.choice(
            "Choose the dungeon this group should run now: one it can clear at "
            "its level, which teaches it the most. Each option gives the "
            "dungeon's level range and how groups at this band have done there. "
            "Prefer a dungeon with a good record; a low-level group in a "
            "dungeon near the top of its range dies.",
            door_criteria,
        ),
    }


# Read before the class, whose own `jev` field shadows the module inside it.
_HEURISTIC, _JEV, _BOTH = jev.HEURISTIC, jev.JEV, jev.BOTH


@dataclass(frozen=True)
class GuildJudgment:
    """One of the two decisions, shaped for overseer_jev_judgment."""

    kind: str
    subject: str
    holder: str
    heuristic: str
    heuristic_why: str
    mode: str
    status: str = ""
    item_guid: int = 0
    item_entry: int = 0
    item_name: str = ""
    facts: str = ""
    jev: str = ""
    confidence: float | None = None
    probabilities: dict | None = None
    latency_ms: int = 0
    model: str = ""
    acted: str = _HEURISTIC

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    @property
    def chosen(self) -> str:
        return self.jev if self.acted in (_JEV, _BOTH) and self.jev else self.heuristic

    @property
    def chosen_by(self) -> str:
        return self.acted if self.jev else _HEURISTIC

    def probabilities_json(self, limit: int = 1000) -> str:
        if not self.probabilities:
            return ""
        ranked = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        text = json.dumps({k: round(v, 4) for k, v in ranked}, separators=(",", ":"))
        return text if len(text) <= limit else ""

    def line(self) -> str:
        answer = (
            "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
            if self.jev
            else "jev=-"
        )
        return "guild run: %s for %s chose %s (acted=%s); heuristic=%s %s status=%s" % (
            self.kind,
            self.subject,
            self.chosen,
            self.acted,
            self.heuristic,
            answer,
            self.status,
        )


@dataclass(frozen=True)
class Decision:
    plan: Plan
    composition: GuildJudgment
    dungeon: GuildJudgment

    @property
    def chosen(self) -> Composition:
        return self.plan.composition(self.composition.chosen)

    @property
    def door(self) -> Door:
        keyword = self.dungeon.chosen
        return next(d for d in self.plan.doors if d.keyword == keyword)

    @property
    def prior(self) -> Rate:
        return door_rate(
            self.plan.table, self.door.keyword, self.plan.band, self.chosen.key
        )


def _options_text(criteria: dict) -> str:
    text = json.dumps(criteria, separators=(",", ":"))
    return text[:1000]


async def decide(client, plan: Plan, environ=None) -> Decision:
    """Ask Jev both questions at once; each is carried out when its answer
    reaches its floor, and the heuristic's otherwise. A composition Jev
    picks that changes the level band keeps the door only if it still fits."""
    comp_rule = policy(KIND_COMPOSITION, environ)
    door_rule = policy(KIND_DUNGEON, environ)
    comp_label, comp_why = heuristic_composition(plan)
    qs = questions(plan)
    base_comp = GuildJudgment(
        kind=KIND_COMPOSITION,
        subject=plan.pool.guild[:12],
        holder=plan.options[0].tank.name,
        heuristic=comp_label,
        heuristic_why=comp_why,
        mode=comp_rule.mode,
        item_name=("band %s: %s" % (plan.band, ", ".join(plan.labels)))[:120],
        facts=_options_text(qs["composition"]["criteria"]),
    )
    door_keyword, door_why = heuristic_door(plan, plan.composition(comp_label))
    base_door = GuildJudgment(
        kind=KIND_DUNGEON,
        subject=plan.pool.guild[:12],
        holder=plan.options[0].tank.name,
        heuristic=door_keyword,
        heuristic_why=door_why,
        mode=door_rule.mode,
        item_name=(
            "band %s: %s" % (plan.band, ", ".join(d.keyword for d in plan.doors))
        )[:120],
        facts=_options_text(qs["dungeon"]["criteria"]),
    )
    if comp_rule.mode == jev.OFF and door_rule.mode == jev.OFF:
        return Decision(
            plan, replace(base_comp, status="off"), replace(base_door, status="off")
        )
    outcome = await client.ask("guild_run", state_for(plan), qs, wait=2.0)
    if outcome.answers is None:
        return Decision(
            plan,
            replace(base_comp, status=outcome.status, latency_ms=outcome.latency_ms),
            replace(base_door, status=outcome.status, latency_ms=outcome.latency_ms),
        )
    comp_answer = outcome.answers["composition"]
    door_answer = outcome.answers["dungeon"]
    comp = replace(
        base_comp,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=comp_answer.choice,
        confidence=comp_answer.confidence,
        probabilities=comp_answer.probabilities,
        acted=comp_rule.acted(
            comp_label,
            comp_answer.choice,
            comp_answer.confidence,
            can_act=comp_answer.choice in plan.labels,
        ),
    )
    chosen = plan.composition(comp.chosen)
    fits = {d.keyword for d in fitting_doors(chosen.levels, list(plan.doors))}
    # Jev may not send a group to a door that keeps failing either, unless only
    # failing doors fit (FAILING_RUNS says why).
    healthy_fits = fits - failing_doors(plan)
    if healthy_fits:
        fits = healthy_fits
    if door_keyword not in fits and fits:
        # The heuristic's door, re-asked for the composition that was chosen.
        door_keyword, door_why = heuristic_door(plan, chosen)
        base_door = replace(base_door, heuristic=door_keyword, heuristic_why=door_why)
    door = replace(
        base_door,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=door_answer.choice,
        confidence=door_answer.confidence,
        probabilities=door_answer.probabilities,
        acted=door_rule.acted(
            door_keyword,
            door_answer.choice,
            door_answer.confidence,
            can_act=door_answer.choice in fits,
        ),
    )
    return Decision(plan, comp, door)


# --- the run's record -------------------------------------------------------------


def members_text(comp: Composition) -> str:
    """name:seat:class:level, comma-separated, tank first."""
    seats = ["tank", "healer", "dps", "dps", "dps"]
    return ",".join(
        "%s:%s:%s:%d" % (m.name, seat, raidroles_class_name(m.class_id), m.level)
        for m, seat in zip(comp.members, seats, strict=True)
    )


def _num(result: dict, key: str) -> int:
    try:
        return int(result.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _result_of(row: dict) -> dict:
    try:
        result = json.loads(row.get("result") or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _levels_gained(members) -> int:
    levels = 0
    for m in members if isinstance(members, list) else []:
        if not isinstance(m, dict):
            continue
        start, end = _num(m, "level_start"), _num(m, "level_end")
        if start and end:
            levels += max(0, end - start)
    return levels


def _progress(result: dict) -> dict:
    return {
        key: _num(result, key)
        for key in ("deaths", "seconds_inside", "bosses_done", "bosses_total")
    }


def _ended(row: dict, result: dict) -> dict:
    outcome = str(result.get("outcome") or "")
    notable = result.get("loot_notable") or []
    ilvl_start, ilvl_end = _num(result, "ilvl_start"), _num(result, "ilvl_end")
    out = {
        "state": ENDED,
        "outcome": outcome if outcome in OUTCOMES else "lost",
        "why": str(result.get("why") or row.get("detail") or "")[:255],
        "loot_items": _num(result, "loot_items"),
        "loot_notable": ",".join(str(x) for x in notable if str(x).isdigit())[:200],
        "ilvl_gained": (ilvl_end - ilvl_start) if (ilvl_start and ilvl_end) else 0,
        "levels_gained": _levels_gained(result.get("members")),
    }
    out.update(_progress(result))
    return out


def outcome_from_row(row: dict) -> dict | None:
    """What an overseer_command row says about its run, or None while it is
    still queued. Keys are overseer_guild_run's columns. An ended row whose
    result names no known outcome (a sweep, a restart) is lost."""
    status = str(row.get("status") or "")
    result = _result_of(row)
    if status == "verifying":
        if str(result.get("phase") or "") != "inside":
            return None
        return dict(_progress(result), state=INSIDE)
    if status not in ("applied", "error", "delivered", "unchanged"):
        return None
    return _ended(row, result)


# --- the Guild tab ---------------------------------------------------------------


def _member_list(text: str) -> list:
    out = []
    for part in str(text or "").split(","):
        bits = part.split(":")
        if len(bits) != 4:
            continue
        name, seat, cls, level = bits
        try:
            out.append({"name": name, "seat": seat, "class": cls, "level": int(level)})
        except ValueError:
            continue
    return out


def _n(count: int, word: str) -> str:
    """ "1 death", "3 deaths": the count with its noun agreeing."""
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _choice_line(label: str, by: str, answer: str, confidence) -> str:
    """Who chose the dungeon or the group, in words (#567).

    A group answer is an option letter ("a"), so it is said as "lineup a";
    a dungeon answer is a portal keyword and is said as its place. "The
    prior" is the usual rule, the heuristic Jev is measured against.
    """
    if not by:
        return "%s: not recorded" % label
    if answer and confidence is not None:
        said = _place(answer) if label == "dungeon" else "lineup %s" % answer
        sure = round(100 * float(confidence))
        if by == _HEURISTIC:
            return (
                "%s: the usual rule chose; Jev suggested %s but was only %d%% sure"
                % (label, said, sure)
            )
        return "%s: Jev chose %s, %d%% sure" % (label, said, sure)
    return "%s: no answer from Jev, so the usual rule chose" % label


def _minutes(seconds) -> str:
    return "%d min" % round(int(seconds or 0) / 60.0)


# A run formed from a guild-chat ask (guildsocial) records who chose instead
# of a Jev judgment: the proposer chose the dungeon, the yeses the group.
ASKED, ANSWERED = "ask", "answers"


def _asked_lines(view: dict) -> list:
    who = view.get("proposer") or "a member"
    return [
        "dungeon: %s asked for it in guild chat" % who,
        "group: the guildmates who answered yes (%s)" % view["composition"],
    ]


def _run_lines(view: dict) -> list:
    if view["dungeon"]["by"] == ASKED:
        return _asked_lines(view) + _outcome_lines(view)
    lines = [
        _choice_line(
            "dungeon",
            view["dungeon"]["by"],
            view["dungeon"]["jev"],
            view["dungeon"]["confidence"],
        ),
        _choice_line(
            "group",
            view["choice"]["by"],
            view["choice"]["jev"],
            view["choice"]["confidence"],
        )
        + " (%s)" % view["composition"],
    ]
    if view["prior_runs"]:
        lines.append(
            "record before this run: %d%% over %s"
            % (round(100 * (view["prior"] or 0.0)), _n(view["prior_runs"], "run"))
        )
    return lines + _outcome_lines(view)


def _outcome_lines(view: dict) -> list:
    lines = []
    bosses = (
        "%d of %d bosses" % (view["bosses_done"], view["bosses_total"])
        if view["bosses_total"]
        else ""
    )
    if view["state"] == ENDED:
        parts = [
            _n(view["deaths"], "death"),
            _minutes(view["seconds_inside"]) + " inside",
        ]
        if bosses:
            parts.append(bosses)
        parts.append(_n(view["loot_items"], "item") + " looted")
        if view["levels_gained"]:
            parts.append(_n(view["levels_gained"], "level") + " gained")
        if view["ilvl_gained"]:
            parts.append("%d item levels gained" % view["ilvl_gained"])
        lines.append(", ".join(parts))
        if view["why"]:
            lines.append(view["why"])
    elif view["state"] == INSIDE:
        parts = [
            _minutes(view["seconds_inside"]) + " inside",
            _n(view["deaths"], "death"),
        ]
        if bosses:
            parts.append(bosses)
        lines.append(", ".join(parts))
    else:
        lines.append("queued in the dungeon finder")
    return lines


def _confidence(value):
    return None if value is None else round(float(value), 2)


def _judged(row: dict, prefix: str) -> dict:
    return {
        "by": row.get(prefix + "_by") or "",
        "jev": row.get(prefix + "_jev") or "",
        "confidence": _confidence(row.get(prefix + "_confidence")),
    }


_TEXT = ("guild", "band", "composition", "keyword", "state", "outcome", "why")
_COUNTS = (
    "prior_runs",
    "deaths",
    "seconds_inside",
    "bosses_done",
    "bosses_total",
    "loot_items",
    "ilvl_gained",
    "levels_gained",
)


def _run_view(row: dict) -> dict:
    view = {key: row.get(key) or "" for key in _TEXT}
    view.update({key: _num(row, key) for key in _COUNTS})
    view.update(
        {
            "id": row.get("id"),
            "proposer": str(row.get("proposer") or ""),
            "place": _place(view["keyword"]),
            "members": _member_list(row.get("members")),
            "dungeon": _judged(row, "dungeon"),
            "choice": _judged(row, "composition"),
            "prior": _confidence(row.get("prior_rate")),
            "created_at": str(row.get("created_at") or ""),
            "ended_at": str(row.get("ended_at") or ""),
        }
    )
    ended_run = view["state"] == ENDED
    view["title"] = "%s - %s" % (view["guild"], view["place"])
    view["band_line"] = "band %s" % view["band"]
    view["status"] = view["outcome"] if ended_run else view["state"]
    view["tone"] = (
        "good" if view["outcome"] == CLEARED else ("bad" if ended_run else "")
    )
    view["lines"] = _run_lines(view)
    return view


def _place(keyword: str) -> str:
    try:
        return council.keyword_place(keyword)
    except Exception:  # an unknown keyword is shown as itself
        return keyword


def page(rows: list) -> dict:
    """The Guild tab's payload from overseer_guild_run rows, newest first."""
    active = [
        _run_view(r) for r in rows if str(r.get("state") or "") in (QUEUED, INSIDE)
    ]
    recent = [_run_view(r) for r in rows if str(r.get("state") or "") == ENDED][:30]
    table = rates(rows)
    records = [
        {
            "keyword": k,
            "place": _place(k),
            "band": b,
            "composition": c,
            "runs": r.runs,
            "cleared": r.cleared,
            "rate": round(r.smoothed, 2),
            "words": r.words(),
            "line": "%s, band %s, %s: %s" % (_place(k), b, c, r.words()),
        }
        for (k, b, c), r in sorted(
            table.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])
        )
    ]
    head = "%s out, %d back" % (_n(len(active), "group"), len(recent))
    return {
        "head": head,
        "active": active,
        "recent": recent,
        "records": records,
        "empty_active": "No guild group is out.",
        "empty_recent": "No guild group has come back yet.",
        "empty_records": "Nothing learned yet: no run has an outcome.",
    }
