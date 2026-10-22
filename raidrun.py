"""The raid run: the operator's order for a raid night, and what it needs.

WHAT THIS IS FOR. A family's dungeon campaign is a `dungeon:<keyword>` job
the queue writes and mod-overseer's coordinator runs. A raid is not a bigger
dungeon run: forty characters, most of them guild bots off the roster, have to
be put in one raid group, brought to one door and walked through it together.
mod-overseer's raid run (quadseven/mod-overseer#634) does that on a
`raid:<keyword>` job, reading who sits where from `overseer_raid_seat`. This
module is the site's half: the keyword, the seats the bridge writes from the
Lineup tab's own selection, the attunement path, and the plain facts the Raid
tab states about what the overseer can and cannot do yet.

AN ORDER AND NEVER A PLAN. The only way `raid:moltencore` reaches a roster row
is an operator typing `queue <family>: moltencore 1`. The campaign planner and
the council choose among jobs.PORTAL_KEYWORDS, which a raid keyword is not in,
so neither can propose one.

PURE MODULE, same seam as campaignqueue.py: rows in, rows and sentences out,
nothing that talks to MySQL. bridge.py runs the statements named here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import jobs
import raidroles

# The one raid door mod-overseer has (RaidDoorFor in overseer_decisions).
MOLTEN_CORE = "moltencore"
MOLTEN_CORE_MAP = 409

# THE LEVEL THE INSTANCE'S OWN ACCESS ROW ASKS: dungeon_access_template for map
# 409 says min_level 50 and carries no requirement rows. The site reads the row
# live for the readiness card; this copy is only the queue's refusal, checked
# before an order is written.
MIN_LEVEL = {MOLTEN_CORE: 50}

# ONE NIGHT PER ORDER. The queue counts an entry done off the leader's
# `dungeon_runs_done`, which only the dungeon coordinator writes, so a raid
# entry stays active until the operator clears the queue. An order for "3"
# would read as a promise of three nights that nothing counts.
RUNS_PER_ORDER = 1

# The names an order may use for the raid, folded the way campaignqueue folds.
NAMES = {
    "moltencore": MOLTEN_CORE,
    "molten core": MOLTEN_CORE,
    "mc": MOLTEN_CORE,
}

# WHAT THE OVERSEER CAN DO WITH AN ORDERED RAID, stated rather than inferred,
# because the module that does it is another repository. Pinned to
# quadseven/mod-overseer#634 and #640; change these with the module, never
# ahead of it.
FORMS = True  # converts the head's group and seats the lineup
ENTERS = True  # assembles at the door and walks the raid in, head last
# Molten Core's dungeon-clear behavior belongs to the later clearing slice.
# Until that slice orders it, the raid run forms and enters but holds inside.
CLEARS = False
# ASSEMBLE walks the head alone (StepRaidRun's aimStaging), and after the
# assemble wait the raid goes in with whoever has arrived. The bridge's
# gathering (THE GATHERING below) asks for a meeting stone summon for each
# raider too far to walk; this stays False until a live night shows a
# summoned raider arrive at the mountain.
GATHERS = False

# --- the seats -----------------------------------------------------------------

SEAT_TABLE = "overseer_raid_seat"

# The module's migration (2026_09_23_01_overseer_raid_seat.sql) creates the
# table; the bridge only replaces one family's rows for one raid.
DELETE_SEATS_SQL = "DELETE FROM overseer_raid_seat WHERE family = %s AND keyword = %s"
INSERT_SEAT_SQL = (
    "INSERT INTO overseer_raid_seat (family, keyword, name, subgroup, role) "
    "VALUES (%s, %s, %s, %s, %s)"
)
# THE DUTY, from the talent tree (raidlineup: main tank, off tank, healer,
# melee, ranged, caster or damage), in the column mod-overseer's
# 2026_09_24_02_overseer_raid_seat_duty.sql adds. A realm without the column
# refuses this statement with 1054, and the bridge writes INSERT_SEAT_SQL
# instead, so the seats still form the raid.
INSERT_SEAT_DUTY_SQL = (
    "INSERT INTO overseer_raid_seat (family, keyword, name, subgroup, role, duty) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)

# EVERY MEMBER OF THE FAMILY'S GUILD, found from the family's own names, which
# is the same read the Raid tab's lineup is chosen from (map_server's
# _RAID_GUILD), so the seats written are the lineup the operator saw.
# Built from constant strings only (raidroles.TALENTS_COLUMN is one); every
# value is bound by the driver.
GUILD_MEMBERS_SQL = (
    "SELECT c.name, c.level, c.class AS class_id, c.race, "  # noqa: S608 - constant fragments only
    + raidroles.TALENTS_COLUMN
    + " FROM characters c JOIN guild_member gm ON gm.guid = c.guid "
    "WHERE gm.guildid IN (SELECT gm2.guildid FROM guild_member gm2 "
    "JOIN characters c2 ON c2.guid = gm2.guid WHERE c2.name IN ({holes}))"
)


# --- the seat targets ------------------------------------------------------------
#
# THE TALENT TREE EACH RAIDER'S SEAT NEEDS, in mod-overseer's
# overseer_raid_spec (2026_09_25_10_overseer_raid_spec.sql). Written for every
# placed raider of each family's guild whenever the bridge plans the lineup,
# not only when a raid is ordered: the natural guilds' bots level from 1 and
# the module spends each new talent point in the seat's tree (`tab`, the
# talent frame's order, 0 to 2). A family character's row is written for the
# page and the log; the module leaves the family to its roster tree.
SPEC_TABLE = "overseer_raid_spec"
DELETE_SPECS_SQL = "DELETE FROM overseer_raid_spec WHERE guild = %s"
INSERT_SPEC_SQL = (
    "INSERT INTO overseer_raid_spec (name, guild, class, tab, tree, duty, subgroup) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE guild = VALUES(guild), class = VALUES(class), "
    "tab = VALUES(tab), tree = VALUES(tree), duty = VALUES(duty), "
    "subgroup = VALUES(subgroup)"
)
# The guild a family's names are in: the first one, as every guild read here
# takes the family's guild to be one.
GUILD_OF_SQL = (
    "SELECT g.name FROM guild g JOIN guild_member gm ON gm.guildid = g.guildid "  # noqa: S608 - constant fragments only
    "JOIN characters c ON c.guid = gm.guid WHERE c.name IN ({holes}) "
    "ORDER BY g.guildid LIMIT 1"
)


def spec_rows(guild: str, lineup: dict) -> list:
    """(name, guild, class, tab, tree, duty, subgroup) per placed raider whose
    seat names a tree, subgroup zero-based as the seat table holds it."""
    rows = []
    for index, group in enumerate(lineup.get("groups") or []):
        number = int(group.get("number") or index + 1)
        for member in group.get("members") or []:
            tab = member.get("target_tab")
            if tab is None or not member.get("target_spec"):
                continue
            rows.append(
                (
                    str(member["name"]),
                    str(guild or ""),
                    int(member.get("class_id") or 0),
                    int(tab),
                    str(member["target_spec"]),
                    str(member.get("duty") or ""),
                    number - 1,
                )
            )
    return rows


def is_raid(keyword: str) -> bool:
    return str(keyword or "") in jobs.RAID_KEYWORDS


def keyword_for(text: str) -> str | None:
    """The raid keyword `text` names, or None."""
    folded = " ".join(str(text or "").lower().replace("'", "").split())
    if folded.startswith("the "):
        folded = folded[4:]
    return NAMES.get(folded)


# How each raid keyword is said. Every jobs.RAID_KEYWORDS entry needs one, or
# the queue would speak a bare keyword; tests/test_raidrun.py holds the two
# sets equal so they move together.
PLACES = {MOLTEN_CORE: "Molten Core"}


def place(keyword: str) -> str:
    return PLACES.get(keyword, keyword)


def refusal(keyword: str, runs: int, level_rows: list) -> str:
    """Why this family cannot be ordered to this raid, or "".

    Every member must be at the instance's own minimum level: the core refuses
    the door to anybody below it, and one member refused at the door is a
    family split at the door.
    """
    if not is_raid(keyword):
        return "the overseer has no raid door for %s" % keyword
    if int(runs) != RUNS_PER_ORDER:
        return (
            "a raid order is one night; order %s %d and clear the queue when "
            "it is over" % (place(keyword), RUNS_PER_ORDER)
        )
    floor = MIN_LEVEL.get(keyword, 0)
    under = sorted(
        str(r.get("name")) for r in level_rows or [] if int(r.get("level") or 0) < floor
    )
    if under:
        return "%s %s below level %d, the lowest %s admits" % (
            ", ".join(under),
            "is" if len(under) == 1 else "are",
            floor,
            place(keyword),
        )
    return ""


def seat_rows(family: str, keyword: str, lineup: dict, *, duty: bool = False) -> list:
    """(family, keyword, name, subgroup, role) per placed raider, and the
    duty last when `duty` is set (INSERT_SEAT_DUTY_SQL).

    `lineup` is raidlineup.build_lineup's answer. Groups there are numbered
    1 to 8 for the page; the module and the core hold subgroups 0 to 7, so the
    conversion is made once, here.
    """
    rows = []
    for index, group in enumerate(lineup.get("groups") or []):
        number = int(group.get("number") or index + 1)
        for member in group.get("members") or []:
            rows.append(
                (
                    family,
                    keyword,
                    str(member["name"]),
                    number - 1,
                    str(member.get("role") or ""),
                )
                + ((str(member.get("duty") or ""),) if duty else ())
            )
    return rows


# --- the attunement ------------------------------------------------------------
#
# "Attunement to the Core", both of the core's rows (7848 Alliance, 7487 Horde;
# raidready.ATTUNEMENT_QUESTS). Given and taken by Lothos Riftwaker (creature
# 14387) on Blackrock Mountain's own ledge, at (-7508.63, -1039.84, 180.995) on
# map 0. The objective is one Core Fragment (item 18412), which drops only for
# a character holding the quest, from the Core Fragment chest (gameobject
# 179553) inside Blackrock Depths at (1128.01, -471.76, -104.03) on map 230,
# beside the Molten Bridge. The Alliance row is not shareable (quest Flags 64,
# no sharable bit), so each member takes it from Lothos in person.
#
# WHAT IT BUYS, AND WHAT IT DOES NOT. Lothos's gossip "Teleport me to the
# Molten Core" is conditioned on either row rewarded. The Molten Core window
# (areatrigger 3529), a few yards from him, asks only a raid group and level
# 50. So the attunement is a shortcut for a person, not a gate for the raid.

LOTHOS = 14387
CORE_FRAGMENT = "Core Fragment"
CORE_FRAGMENT_ITEM = 18412

ATTUNED = "attuned"
FRAGMENT_HELD = "fragment held"
IN_LOG = "in the quest log"
NOT_TAKEN = "not taken"

# Quest status 3 is QUEST_STATUS_INCOMPLETE and 1 QUEST_STATUS_COMPLETE in
# character_queststatus, the two a quest in the log carries.
IN_LOG_STATUSES = frozenset({1, 3})

STEPS = (
    # attunestep.py walks them to creature LOTHOS; each member takes the
    # quest through a kind='quest' command row.
    "The family walks to Lothos Riftwaker once every member is at level 55 "
    "or more, all are on the Eastern Kingdoms and the family's queued runs "
    "are done. Each member standing at him takes Attunement to the Core in "
    "person (the Alliance quest cannot be shared).",
    "Queue the family into Blackrock Depths, one run, from the Decree tab. "
    "The Core Fragment chest stands beside the Molten Bridge in the back "
    "half of the dungeon, past the Lyceum; it opens only for a member holding "
    "the quest, one fragment each.",
    "With a fragment carried, the attunement step walks the family back to "
    "Lothos and each member hands it in the same way. The Raid tab shows each "
    "member move from not taken to in the quest log to fragment held to "
    "attuned, read from the realm.",
)

STEPS_UNPROVEN = (
    "Not yet seen on this realm: whether every follower stands within twelve "
    "yards of Lothos when the head arrives, and whether the dungeon brain's "
    "route passes close enough to the chest for each member to loot it. Each "
    "is read back from the realm rather than assumed."
)


# THE GUILD BOTS ARE NOT ON THIS PATH, and that is a finding rather than an
# omission. Nothing in the overseer drives a guild bot's quests (mod-overseer
# steers roster characters; a guild bot only follows the head it is grouped
# with), Blackrock Depths is a five-player dungeon a raid group cannot take in,
# and the window they walk through does not ask for the attunement.
BOTS_LINE = (
    "The guild bots in the raid are not attuned, and nothing in the overseer "
    "can make them: it steers the family, and a guild bot only follows the "
    "head it is grouped with. They do not need it to walk in."
)


def attunement_status(rewarded: bool, in_log: bool, fragments: int) -> str:
    if rewarded:
        return ATTUNED
    if in_log and fragments > 0:
        return FRAGMENT_HELD
    if in_log:
        return IN_LOG
    return NOT_TAKEN


def attunement(names: list, rewarded: set, in_log: set, fragments: dict) -> dict:
    """Where each of `names` stands on the attunement, and the steps.

    `rewarded` and `in_log` are names; `fragments` is name -> Core Fragments
    carried or banked.
    """
    members = []
    for name in names:
        status = attunement_status(
            name in rewarded, name in in_log, int(fragments.get(name) or 0)
        )
        members.append(
            {"name": name, "status": status, "line": "%s: %s" % (name, status)}
        )
    done = len([m for m in members if m["status"] == ATTUNED])
    return {
        "line": "%d of %d attuned to the Core. It opens Lothos Riftwaker's "
        "teleport; the Molten Core window beside him admits a raid without it."
        % (done, len(members)),
        "members": members,
        "steps": list(STEPS),
        "unproven": STEPS_UNPROVEN,
        "bots": BOTS_LINE,
    }


# --- the gathering (#762) -------------------------------------------------------
#
# HOW A RAID NIGHT GATHERS, DECIDED: THE RAID SUMMONS ITSELF AT THE BLACKROCK
# MOUNTAIN MEETING STONE. Three orders were on the table:
#
#   (a) form with fewer than forty, let the guild's summoner warlocks join,
#       summon and leave, then seat the rest. What players did, but the module
#       forms the raid from overseer_raid_seat all at once and has no swap.
#   (b) the raid summons its own, raiders clicking.
#   (c) release the raiders early enough to walk: a boat, a flight and a walk
#       from Kalimdor, thirty to sixty minutes a night.
#
# (b) is the one the module can carry today, and not through a warlock's
# ritual: mod-overseer's `kind='summon'` drives the meeting stone (GameObject
# type 23), which needs no warlock and no Soul Shard, only a summoner standing
# at the stone and one more raid member clicking the portal, both in the
# target's raid. The core's IsInSameRaidWith check is the reason it has to be
# raiders: none of the twenty-one summoners holds a seat.
#
# Each seated raider arrives one of three ways, read off where it stands when
# the raid is ordered: already at the mountain; walking in behind the head,
# when it is on the door's continent and close enough; or summoned at the
# stone, from anywhere else, another continent included. A raider the
# snapshot does not show is said as not in the world: nothing can summon it.

BLACKROCK_MOUNTAIN = "Blackrock Mountain"
AT_MOUNTAIN = "at Blackrock Mountain"
WALK = "walk"
SUMMON = "summon"
UNSEEN = "not in the world"

# INSIDE THE MOUNTAIN: within these many yards of the Molten Core door on its
# map. Blackrock Depths' door is 360 yards from it and Lower Blackrock Spire's
# 200 (entrances.json), so this holds the mountain and no more.
MOUNTAIN_YARDS = 400.0
# CLOSE ENOUGH TO WALK: on the door's map within these many yards, which is
# the Burning Steppes and the Searing Gorge around the mountain. Further than
# this a summon is quicker than the road, whatever the continent.
WALK_YARDS = 1500.0
# HOW CLOSE A CLICKER HAS TO STAND: mod-overseer walks a clicker the last
# yards to the stone from no further than this (SUMMON_APPROACH_YARDS in
# mod_overseer.cpp), and refuses one further out.
STONE_REACH = 40.0
# The stone's portal wants the summoner and one more clicker.
CLICKERS = 2
# ONE RITUAL AT A TIME. Nobody has yet seen two portals at one stone settle
# apart, so the next summon waits for the last row to finish.
SUMMONS_AT_ONCE = 1

# The command log's `source` for every row the gathering writes.
GATHER_SOURCE = "raidgather"


def gather_source(action: str, name: str) -> str:
    return "%s:%s:%s" % (GATHER_SOURCE, action, name)


def _yards(position: dict, x: float, y: float) -> float:
    return math.hypot(float(position["pos_x"]) - x, float(position["pos_y"]) - y)


def _on_map(position, map_id) -> bool:
    try:
        return position is not None and int(position["map_id"]) == int(map_id)
    except (KeyError, TypeError, ValueError):
        return False


def arrival(position: dict | None, door: dict) -> str:
    """How one raider standing at `position` (map_id, pos_x, pos_y; None when
    the snapshot does not show it) reaches `door` (entrances.json's map, x, y)."""
    if not position:
        return UNSEEN
    if not _on_map(position, door["map"]):
        return SUMMON
    yards = _yards(position, float(door["x"]), float(door["y"]))
    if yards <= MOUNTAIN_YARDS:
        return AT_MOUNTAIN
    return WALK if yards <= WALK_YARDS else SUMMON


def arrivals(names, positions: dict, door: dict) -> dict:
    """name -> how it arrives, for every seated raider in `names`."""
    return {name: arrival(positions.get(name), door) for name in names}


def order_line(family: str, keyword: str, ways: dict) -> str:
    """The order's one log line: how each raider not at the mountain arrives."""
    said = []
    for way, label in (
        (WALK, "walk in behind the head"),
        (SUMMON, "summoned at the %s meeting stone" % BLACKROCK_MOUNTAIN),
        (UNSEEN, UNSEEN),
    ):
        names = sorted(n for n, w in ways.items() if w == way)
        if names:
            said.append("%s %d: %s" % (label, len(names), ", ".join(names)))
    here = len([w for w in ways.values() if w == AT_MOUNTAIN])
    return "raid order: %s into %s, %d seated: %d %s%s" % (
        family,
        place(keyword),
        len(ways),
        here,
        AT_MOUNTAIN,
        "".join("; " + s for s in said),
    )


def at_stone(position, stone) -> bool:
    """Whether `position` stands within STONE_REACH of `stone` (a guildjobs
    Spot: map_id, x, y)."""
    if not _on_map(position, stone.map_id):
        return False
    return _yards(position, float(stone.x), float(stone.y)) <= STONE_REACH


@dataclass(frozen=True)
class Summon:
    """One meeting stone summon: who stands at the stone, who is brought, and
    the second clicker."""

    summoner: str
    target: str
    helper: str

    @property
    def command(self) -> str:
        # mod-overseer's ParseSummonRequest: `use <name>`.
        return "use %s" % self.target


@dataclass(frozen=True)
class Gathering:
    """This pass's step: raiders walked to the stone, or one summon, and why
    nothing else was written."""

    walks: tuple = ()
    summon: Summon | None = None
    why: str = ""


def _open_names(open_rows, kind: str) -> set:
    """Every name an open row of `kind` holds: its actor, its second clicker
    and, for a summon, the raider it brings."""
    out = set()
    for row in open_rows or ():
        if str(row.get("kind") or "") != kind:
            continue
        out.add(str(row.get("target_name") or ""))
        out.add(str(row.get("target_arg") or ""))
        command = str(row.get("command") or "")
        if command.startswith("use "):
            out.add(command[4:].strip())
    return out - {""}


def _waiting(ways, positions, in_raid, door, tried) -> list:
    """The raiders a summon still has to bring, in name order: seated, in the
    raid, not tried lately and still too far to walk."""
    return sorted(
        name
        for name, way in ways.items()
        if way == SUMMON
        and name in in_raid
        and name not in tried
        and arrival(positions.get(name), door) == SUMMON
        and not _on_map(positions.get(name), MOLTEN_CORE_MAP)
    )


def _clickers(names, positions, in_raid, stone) -> list:
    return sorted(
        n for n in names if n in in_raid and at_stone(positions.get(n), stone)
    )


def _walkers(names, positions, in_raid, stone, door, keep, busy, need) -> tuple:
    """The `need` raiders at the mountain nearest the stone, to walk to it.
    `keep` is the family, whose job the walk would replace."""
    near = [
        (_yards(positions[n], float(stone.x), float(stone.y)), n)
        for n in names
        if n in in_raid
        and n not in keep
        and n not in busy
        and arrival(positions.get(n), door) == AT_MOUNTAIN
        and not at_stone(positions.get(n), stone)
    ]
    return tuple(n for _y, n in sorted(near)[:need])


def gather(ways, positions, in_raid, door, stone, *, keep=(), open_rows=(), tried=()):
    """This pass's gathering step for one raid.

    `ways` is the order's arrivals; `positions` this pass's snapshot;
    `in_raid` the names in the head's group (the core summons only within the
    raid); `stone` the Blackrock Mountain meeting stone; `open_rows` this
    gathering's rows not yet finished; `tried` the raiders whose last summon
    ended without them arriving, left for a later pass.
    """
    if stone is None:
        return Gathering(why="no meeting stone stands near the door")
    waiting = _waiting(ways, positions, in_raid, door, set(tried))
    if not waiting:
        return Gathering(why="nobody in the raid waits on a summon")
    summoning = len([r for r in open_rows or () if r.get("kind") == "summon"])
    if summoning >= SUMMONS_AT_ONCE:
        return Gathering(why="a summon is under way")
    clickers = _clickers(ways, positions, in_raid, stone)
    if len(clickers) >= CLICKERS:
        return Gathering(summon=Summon(clickers[0], waiting[0], clickers[1]))
    walking = _open_names(open_rows, "job") - set(clickers)
    need = CLICKERS - len(clickers) - len(walking)
    if need <= 0:
        return Gathering(why="%d raider(s) walk to the stone" % len(walking))
    walks = _walkers(ways, positions, in_raid, stone, door, set(keep), walking, need)
    if not walks:
        return Gathering(
            why="%d of %d clickers at the stone and nobody at the mountain to "
            "walk there" % (len(clickers), CLICKERS)
        )
    return Gathering(walks=walks)


# A gathering row still running, as overseer_command says it.
OPEN_STATUSES = frozenset({"pending", "claimed", "verifying"})


def open_rows(rows) -> list:
    """The gathering's rows not yet finished."""
    return [r for r in rows or () if str(r.get("status") or "") in OPEN_STATUSES]


def tried(rows) -> set:
    """The raiders whose summon finished without bringing them ('applied' is
    the module's only arrival), left out until the rows age past the read."""
    return {
        str(r.get("command") or "")[4:].strip()
        for r in rows or ()
        if r.get("kind") == "summon"
        and str(r.get("command") or "").startswith("use ")
        and str(r.get("status") or "") not in OPEN_STATUSES | {"applied"}
    }


def inside(names, positions: dict) -> int:
    """How many of `names` the snapshot shows inside Molten Core."""
    return len([n for n in names if _on_map(positions.get(n), MOLTEN_CORE_MAP)])


def gathered_line(family: str, keyword: str, count: int, total: int, seconds) -> str:
    """How long the night took from the order to `count` of `total` inside."""
    if seconds is None:
        since = "since an order whose start is not read"
    else:
        since = "%d minute(s) after the order" % (int(seconds) // 60)
    lead = "all %d" % total if count >= total else "%d of %d" % (count, total)
    return "raid gather: %s: %s inside %s, %s" % (family, lead, place(keyword), since)


# --- what the overseer can and cannot do with the raid ------------------------

DUNGEON_CLEAR_LINE = (
    "Molten Core is map 409. The dungeon-clear brain stays off there until a "
    "clearing order arms it; the raid run currently holds at the entrance."
)


def run_line() -> str:
    """What an order does today, in the order it happens."""
    did = []
    if FORMS:
        did.append("forms the raid from the lineup")
    if ENTERS:
        did.append("walks it to the Molten Core door and in, the head last")
    head = (
        "An order (queue <family>: moltencore 1) "
        + " and ".join(did)
        + ", with a family member streaming."
        if did
        else "Nothing can take a raid in yet."
    )
    if CLEARS:
        head += (
            " Inside, it rests at the entrance, then clears it with the dungeon "
            "brain armed on the head, and runs back after a wipe."
        )
    else:
        head += " It does not clear: inside, the raid holds at the entrance."
    if not GATHERS:
        head += (
            " Only the head is walked to the door. A raider too far to walk in "
            "behind it is summoned at the %s meeting stone, two raiders at the "
            "stone clicking, and after the wait the raid goes in with whoever "
            "has arrived." % BLACKROCK_MOUNTAIN
        )
    return head
