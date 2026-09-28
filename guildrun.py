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

PURE: facts in, groups, questions and judgments out. The bridge reads and
writes; the only I/O here is the Jev client the caller hands in.
"""

from __future__ import annotations

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
HARD_MAX_GROUPS = 4
FORM_EVERY_SECONDS = 300
COOLDOWN_MINUTES = 40
BAND_SPREAD = 4
ROLLING = 20
MIN_SAMPLES = 3
MAX_OPTIONS = 3
MAX_DUNGEONS = 4
DEFAULT_GUILDS = ("Cave", "Bonkers")
# The continents a queue may start from: never from inside an instance.
OPEN_WORLD_MAPS = (0, 1, 530)
# A run no row has ended by now is lost (a worldserver restart, a sweep).
LOST_AFTER_MINUTES = 120
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
            env, "GUILD_RUNS_EVERY_SECONDS", FORM_EVERY_SECONDS, 60, 86400
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

    @property
    def played_tree(self) -> str:
        return self.tree or self.target_tree

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
    )


def why_not(
    member: Member, busy: set, resting: set, family: set, benched=frozenset()
) -> str:
    """Why this member cannot be picked now, or ""."""
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
    if not member.alive:
        return "dead"
    if member.in_combat:
        return "in combat"
    if member.grouped:
        return "already in a group"
    if member.map_id not in OPEN_WORLD_MAPS:
        return "inside an instance"
    return ""


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


def benched(recent: list) -> set:
    """Members named by refusals in `recent` (overseer_guild_run rows ended
    within BENCH_MINUTES)."""
    out = set()
    for row in recent:
        if str(row.get("outcome") or "") != "refused":
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


def doors(finder_floors: dict | None = None) -> list:
    """Every door mod-overseer has a portal for, with the level it wants
    (council's floor), the level it is outgrown at (campaignplan's ceiling)
    and the finder's own minimum (dungeon_access_template, by map, read by
    the bridge; the council floor when unread)."""
    floors = finder_floors or {}
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
            )
        )
    return out


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


def stranded(member: Member, faction: str) -> bool:
    """A living member standing on the other faction's home ground, or inside
    a dungeon whose door is in the other faction's capital: it hearths home."""
    if not faction or not member.alive or member.in_combat or member.grouped:
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


def fitting_doors(levels, all_doors: list, faction: str = "") -> list:
    """The doors this set of levels fits, best fit first.

    A door inside the other faction's capital (council._other_capital) is not
    offered to a guild of known faction: its members come out among that
    capital's guards.

    Fits: every member at or over the finder's minimum, the average within
    council.NEAR_ENOUGH of the door's floor, and nobody past its ceiling.
    Best fit is the door whose band's middle is nearest the average.
    """
    levels = [int(x) for x in levels]
    if not levels:
        return []
    low, high = min(levels), max(levels)
    mean = sum(levels) / len(levels)
    out = []
    for door in all_doors:
        if faction and council._other_capital(door.map_id, faction):
            continue
        if low < door.finder_floor:
            continue
        if mean + council.NEAR_ENOUGH < door.floor:
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
        (m for m in window if m.fit(TANK)),
        key=lambda m: (_seat_rank(m, TANK), -m.level, m.name),
    )
    healers = sorted(
        (m for m in window if m.fit(HEALER)),
        key=lambda m: (_seat_rank(m, HEALER), -m.level, m.name),
    )
    out = []
    seen = set()

    def build(tank: Member, healer: Member):
        if tank.name == healer.name:
            return None
        rest = [m for m in window if m.name not in (tank.name, healer.name)]
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
    best = fitting_doors(comps[0].levels, all_doors, faction_of(pool.members))
    if not best:
        return None
    return Plan(
        pool=pool,
        options=tuple(comps),
        doors=tuple(best),
        band=band_of(comps[0].levels),
        table=dict(table),
    )


def heuristic_door(plan: Plan, composition: Composition) -> tuple:
    """(keyword, why). The best smoothed rate among doors with MIN_SAMPLES
    runs at this band, when it beats the level fit's own; else the level fit."""
    fit = plan.doors[0]
    known = []
    for door in plan.doors:
        rate = door_rate(plan.table, door.keyword, plan.band, composition.key)
        if rate.runs >= MIN_SAMPLES:
            known.append((rate.smoothed, door, rate))
    if known:
        known.sort(key=lambda t: (-t[0], plan.doors.index(t[1])))
        smoothed, door, rate = known[0]
        fit_rate = door_rate(plan.table, fit.keyword, plan.band, composition.key)
        if (
            door.keyword == fit.keyword
            or fit_rate.runs < MIN_SAMPLES
            or smoothed > fit_rate.smoothed
        ):
            return door.keyword, "the best record at band %s: %s" % (
                plan.band,
                rate.words(),
            )
    return fit.keyword, "the closest level fit (%s wants %d to %d)" % (
        fit.place,
        fit.floor,
        fit.ceiling,
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
    """Act by default, at a 0.6 floor; an agreement is Jev's (#356)."""
    return jev.policy(
        kind,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=DEFAULT_THRESHOLD,
        on_agreement=True,
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


def _choice_line(label: str, by: str, answer: str, confidence) -> str:
    if not by:
        return "%s: not recorded" % label
    if answer and confidence is not None:
        return "%s: Jev chose %s at %.2f confidence, and %s" % (
            label,
            answer,
            float(confidence),
            "the prior acted (below the floor)"
            if by == _HEURISTIC
            else "Jev's answer acted",
        )
    return "%s: no answer from Jev, so the prior chose" % label


def _minutes(seconds) -> str:
    return "%d min" % round(int(seconds or 0) / 60.0)


def _run_lines(view: dict) -> list:
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
            "record before this run: %d%% over %d run(s)"
            % (round(100 * (view["prior"] or 0.0)), view["prior_runs"])
        )
    bosses = (
        "%d of %d bosses" % (view["bosses_done"], view["bosses_total"])
        if view["bosses_total"]
        else ""
    )
    if view["state"] == ENDED:
        parts = [
            "%d death(s)" % view["deaths"],
            _minutes(view["seconds_inside"]) + " inside",
        ]
        if bosses:
            parts.append(bosses)
        parts.append("%d item(s) looted" % view["loot_items"])
        if view["levels_gained"]:
            parts.append("%d level(s) gained" % view["levels_gained"])
        if view["ilvl_gained"]:
            parts.append("%d item levels gained" % view["ilvl_gained"])
        lines.append(", ".join(parts))
        if view["why"]:
            lines.append(view["why"])
    elif view["state"] == INSIDE:
        parts = [
            _minutes(view["seconds_inside"]) + " inside",
            "%d death(s)" % view["deaths"],
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
    head = "%d group(s) out, %d back" % (len(active), len(recent))
    return {
        "head": head,
        "active": active,
        "recent": recent,
        "records": records,
        "empty_active": "No guild group is out.",
        "empty_recent": "No guild group has come back yet.",
        "empty_records": "Nothing learned yet: no run has an outcome.",
    }
