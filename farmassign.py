"""Farming assignments: connect the raid's consumable deficits to bots that
gather the missing materials and mail them to the crafters who need them.

Pure module: deficits in, assignments and mail steps out. Nothing here talks
to MySQL, touches a clock or writes the command log. The bridge reads the
facts, runs the assignment, writes each new task's gather errand
(`errand_step`), logs `farmassign: assigned <bot> to <material>` only once
that row is written, and runs the mail steps with the corps' own runner. A
restarted bridge rebuilds its standing tasks from those rows
(`standing_from_rows`).

WHY THIS EXISTS. `raidcraft` plans what consumables a raid night eats and
`raidsupply` tracks how many of each the guild holds. Neither says who goes to
gather the shortfall, or where, or for how long. This module is the join: a
short material is matched to a gatherer who can reach it, a place it grows, and
a length of time to spend there, and the gathered stack is routed by post to a
designated crafter.

THE TABLE IS CURATED, NOT MEASURED. `itemsource` shapes where an item comes
from from live world rows, but that data is not read here - this module stays
pure and dependency-light. The locations below are the classic gather spots for
the raid's herbs and ores, named by zone and continent so a bot can be walked
there. A material with no row here is not refused silently: it is named in the
plan's notes so the gap is visible.

GATHERING IS CORPS WORK. A gatherer is taken from the guild's miner and
herbalist posts (guildcorps.ROLES), so a family member is never pulled off its
own craft rhythm to farm, and a maintainer already on another errand is left
alone. Once a material is gathered it is mailed to the crafter whose post
consumes it (herbs to an alchemist, for the potions and flasks the raid eats).

ONLY WHAT THE GATHERER GATHERED IS POSTED. A task remembers the stacks its bot
already carried when it was given (`Task.baseline`). A later pass posts only a
stack the bot picked up since; a stack that was already in the guild, with the
gatherer or anyone else, is left where it is. raidsupply's own reagent letters
move the guild's existing stock.
"""

from __future__ import annotations

from dataclasses import dataclass

import classic
import guildcorps as gc
import guildroute
import raidsupply

SOURCE = "farmassign"
KIND = "farm_assign"

# How long one bot farms one material, in minutes. A night's want is split
# across the guild's gatherers, and one pass assigns each short material to one
# gatherer for one stint.
HERB_DURATION = 60
ORE_DURATION = 90

MINING = gc.MINING
HERBALISM = gc.HERBALISM
ALCHEMY = gc.ALCHEMY


@dataclass(frozen=True)
class Material:
    """One gatherable raid material and where a bot farms it."""

    entry: int
    name: str
    skill: int  # guildcorps trade id that gathers it (MINING or HERBALISM)
    skill_name: str  # "mining" or "herbalism", for notes
    zone: str  # the zone to walk to
    map_id: int  # the continent the zone stands on
    duration: int  # minutes a bot should farm it


def _herb(entry: int, name: str, zone: str, map_id: int) -> Material:
    return Material(entry, name, HERBALISM, "herbalism", zone, map_id, HERB_DURATION)


def _ore(entry: int, name: str, zone: str, map_id: int) -> Material:
    return Material(entry, name, MINING, "mining", zone, map_id, ORE_DURATION)


# Eastern Kingdoms = 0, Kalimdor = 1, the continent a gatherer stands on.
# A material missing from this table has no known farmed source and is named
# in the plan's notes instead of being dropped silently.
# Each row is built once and keyed by its own entry, so a key can never
# disagree with the material it names.
MATERIALS: dict[int, Material] = {
    material.entry: material
    for material in (
        _herb(13463, "Dreamfoil", "Eastern Plaguelands", 0),
        _herb(13464, "Golden Sansam", "Western Plaguelands", 0),
        _herb(13465, "Mountain Silversage", "Silithus", 1),
        _herb(13466, "Plaguebloom", "Eastern Plaguelands", 0),
        _herb(13467, "Icecap", "Winterspring", 1),
        _herb(13468, "Black Lotus", "Western Plaguelands", 0),
        _herb(8846, "Gromsblood", "Blasted Lands", 0),
        _herb(3818, "Fadeleaf", "Arathi Highlands", 0),
        _ore(7067, "Elemental Earth", "Arathi Highlands", 0),
        _ore(7912, "Solid Stone", "The Hinterlands", 0),
        _ore(12365, "Dense Stone", "Western Plaguelands", 0),
    )
}

# The zones above by their area id, as the world's gameobject rows carry it
# (`gameobject.zoneId`), so a task's zone names the nodes it walks to.
ZONE_IDS: dict[str, int] = {
    "Eastern Plaguelands": 139,
    "Western Plaguelands": 28,
    "Silithus": 1377,
    "Winterspring": 618,
    "Blasted Lands": 4,
    "Arathi Highlands": 45,
    "The Hinterlands": 47,
}

# The gather node names that yield each material, for the errand's walk. An
# herb grows on a node of its own name; a stone comes out of the ore veins.
# Elemental Earth drops from elementals, not a node, so it has no errand and
# its task is named as not assigned instead of standing with no row.
NODES: dict[int, tuple] = {
    13463: ("Dreamfoil",),
    13464: ("Golden Sansam",),
    13465: ("Mountain Silversage",),
    13466: ("Plaguebloom",),
    13467: ("Icecap",),
    13468: ("Black Lotus",),
    8846: ("Gromsblood",),
    3818: ("Fadeleaf",),
    7912: ("Mithril Deposit", "Ooze Covered Mithril Deposit"),
    12365: (
        "Small Thorium Vein",
        "Ooze Covered Thorium Vein",
        "Rich Thorium Vein",
        "Ooze Covered Rich Thorium Vein",
    ),
}

# The row kind a gather errand is written as: the guild jobs' own field walk.
ROW_KIND = "job"

# A persisted assignment row in one of these states still stands after a
# restart; any other state (an error, a refusal) ended it.
LIVE_STATUSES = frozenset(
    ("", "pending", "claimed", "verifying", "applied", "delivered")
)

# The trade whose crafter consumes each gathered material, for designating the
# crafter a farmed stack is mailed to. Herbs feed alchemy (potions, elixirs,
# flasks). Ores have no corps crafter on this realm, so they are farmed but not
# routed to a crafter here.
CRAFT_OF: dict[int, int] = {
    13463: ALCHEMY,
    13464: ALCHEMY,
    13465: ALCHEMY,
    13466: ALCHEMY,
    13467: ALCHEMY,
    13468: ALCHEMY,
    8846: ALCHEMY,
    3818: ALCHEMY,
}

# How long one step waits before it is tried again for the same holder and
# thing, read from the command log like the corps' own cooldowns.
COOLDOWN_MINUTES = {
    "post": 30,
    "supply": 120,
}


@dataclass(frozen=True)
class Deficit:
    """One material the raid is short of, as raidsupply's Line reports it."""

    entry: int
    name: str
    short: int  # how many more are wanted


@dataclass(frozen=True)
class Task:
    """One farming assignment: which bot, what, where, for how long."""

    bot: str
    material: int
    name: str
    zone: str
    map_id: int
    duration: int
    # The guids of the bot's stacks of `material` when the task was given:
    # those were already in the guild, so they are never posted as gathered.
    baseline: frozenset = frozenset()


@dataclass(frozen=True)
class FarmPlan:
    """The assignments and mail steps for one pass.

    `tasks` are this pass's new assignments, each logged live as
    `farmassign: assigned <bot> to <material>` once its gather errand's row is
    written (`errand_step`). `steps` mail what standing
    assignments gathered to the designated crafters.
    """

    tasks: tuple
    steps: tuple
    notes: tuple


def source_for(action, key) -> str:
    return "%s:%s:%d" % (SOURCE, action, int(key))


def _online_gatherers(posts, members, skill, busy) -> list:
    """Online, non-family, non-expansion members holding a post in `skill`,
    best skill first."""
    by_name = {m.name: m for m in members or ()}
    out = []
    for p in posts or ():
        if int(p.skill) != int(skill):
            continue
        m = by_name.get(p.name)
        if m is None or not m.online or m.name in busy or m.family:
            continue
        if classic.stands_outside(m):
            continue
        out.append(m)
    out.sort(key=lambda m: (-int(m.skill(skill)[0]), m.name))
    return out


def _gatherer_for(posts, members, skill, busy):
    """The best free gatherer for `skill`, or None."""
    cands = _online_gatherers(posts, members, skill, busy)
    return cands[0] if cands else None


def _crafter_for(material, members, posts) -> object:
    """The member whose corps post consumes `material`, or None. A crafter
    on another step still takes a letter: receiving one is not a step."""
    craft = CRAFT_OF.get(material.entry)
    if craft is None:
        return None
    by_name = {m.name: m for m in members or ()}
    for p in posts or ():
        if int(p.skill) != int(craft):
            continue
        m = by_name.get(p.name)
        if m is None or not m.online or m.family:
            continue
        if classic.stands_outside(m):
            continue
        return m
    return None


def _cooling(step, recent) -> bool:
    minutes = COOLDOWN_MINUTES.get(step.action, 30)
    age = (recent or {}).get((step.holder, step.action, int(step.key)))
    return age is not None and age < minutes


def _post_step(holder, stack, name, crafter, cap) -> object:
    """The holder's `stack`, posted by mail to the crafter."""
    entry = int(stack.entry)
    return gc.Step(
        holder.name,
        "post",
        entry,
        "farmassign: %s posts %d %s to %s for the raid's consumables"
        % (holder.name, int(stack.count), name, crafter),
        rows=(
            gc.Row(
                "mail",
                "send item:%d subject:%s" % (int(stack.guid), name[:40]),
                crafter,
                source_for("post", entry),
            ),
        ),
        walk=gc.Row(
            "mail",
            guildroute.mailbox_walk_command(cap),
            "",
            source_for("post-walk", entry),
        ),
    )


def reagent_deficits(lines, members) -> list:
    """The gathered reagents the raid's short consumables need, beyond what
    the guild's members already carry, one Deficit per reagent.

    `lines` are raidsupply.Line-shaped (`entry`, `short`); a supply with no
    craft (bought or quested) needs no reagent and is passed over.
    """
    need = {}
    for line in lines or ():
        supply = raidsupply.SUPPLY_BY_ENTRY.get(int(line.entry))
        if supply is None or supply.make is None or line.short <= 0:
            continue
        for entry, per in supply.make.reagents:
            need[int(entry)] = need.get(int(entry), 0) + int(per) * int(line.short)
    out = []
    for entry, want in sorted(need.items()):
        have = sum(m.count(entry) for m in members or ())
        if want > have:
            name = raidsupply.REAGENT_NAMES.get(entry) or str(entry)
            out.append(Deficit(entry, name, want - have))
    return out


def _collected(member, task):
    """The member's biggest stack of the task's material that it did not
    carry when the task was given, or None: only what it gathered."""
    held = [
        h
        for h in member.carried
        if int(h.entry) == int(task.material) and int(h.guid) not in task.baseline
    ]
    return max(held, key=lambda h: (int(h.count), -int(h.guid))) if held else None


def _route_collected(standing, members, posts, busy, recent, cap) -> list:
    """Mail steps for what each standing task's gatherer has gathered since it
    was assigned. A stack the gatherer already carried, or any stack held by
    another member, is never posted."""
    by_name = {m.name: m for m in members or ()}
    steps = []
    for task in standing:
        gatherer = by_name.get(task.bot)
        material = MATERIALS.get(task.material)
        if gatherer is None or material is None or task.bot in busy:
            continue
        if not gatherer.online:
            continue
        stack = _collected(gatherer, task)
        crafter = _crafter_for(material, members, posts)
        if stack is None or crafter is None:
            continue
        step = _post_step(gatherer, stack, material.name, crafter.name, cap)
        if not _cooling(step, recent):
            steps.append(step)
            busy.add(task.bot)
    return steps


def errand_step(task, spawns, cap=guildroute.MAIL_RUN_YARDS):
    """The gather errand that carries out `task`: one job row walking its
    gatherer to a node of its material in its zone, or None when no such node
    is among `spawns` (gameobject rows with guid, map_id, zone_id and name).
    The lowest spawn id is taken, so the same task always names the same node.
    """
    names = set(NODES.get(int(task.material), ()))
    zone = ZONE_IDS.get(task.zone)
    if not names or zone is None:
        return None
    found = []
    for s in spawns or ():
        try:
            if (
                int(s["map_id"]) == int(task.map_id)
                and int(s["zone_id"]) == zone
                and str(s.get("name") or "") in names
            ):
                found.append(int(s["guid"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not found:
        return None
    entry = int(task.material)
    return gc.Step(
        task.bot,
        "assign",
        entry,
        "farmassign: %s walks to a %s node in %s to gather for the raid"
        % (task.bot, task.name, task.zone),
        rows=(
            gc.Row(
                ROW_KIND,
                "walk-to-spawn gameobject:%d%s"
                % (min(found), guildroute.errand_cap_word(cap)),
                "",
                source_for("assign", entry),
            ),
        ),
    )


def standing_from_rows(rows, members) -> list:
    """[(Task, age in minutes)] for the assignments the command log shows
    still inside their stint, for a bridge that has none in memory (a
    restart). One per material, the newest row's; only for `members`, and
    only a row still live (LIVE_STATUSES). The gatherer's stacks today are
    its baseline: what it carried before the restart is not posted."""
    by_name = {m.name: m for m in members or ()}
    newest = {}
    for row in rows or ():
        found = _live_assignment(row, by_name)
        if found is None:
            continue
        gatherer, material, age = found
        if material.entry not in newest or age < newest[material.entry][1]:
            newest[material.entry] = (_new_task(gatherer, material), age)
    return [newest[e] for e in sorted(newest)]


def _assignment_of(row):
    """(material entry, age in minutes) of an assignment row, or None for
    any other row of the command log."""
    parts = str(row.get("source") or "").split(":")
    if len(parts) != 3 or parts[0] != SOURCE or parts[1] != "assign":
        return None
    try:
        return int(parts[2]), int(row.get("age") or 0)
    except (TypeError, ValueError):
        return None


def _live_assignment(row, by_name):
    """(gatherer, material, age) for an assignment row that still stands:
    a known material, a member of the guild, a live status, inside its
    stint. None otherwise."""
    parsed = _assignment_of(row)
    if parsed is None:
        return None
    entry, age = parsed
    material = MATERIALS.get(entry)
    gatherer = by_name.get(str(row.get("target_name") or ""))
    if material is None or gatherer is None or age >= material.duration:
        return None
    if str(row.get("status") or "") not in LIVE_STATUSES:
        return None
    return gatherer, material, age


def _new_task(gatherer, material) -> Task:
    """The task for `gatherer`, remembering the stacks it already carries."""
    baseline = frozenset(
        int(h.guid) for h in gatherer.carried if int(h.entry) == material.entry
    )
    return Task(
        gatherer.name,
        material.entry,
        material.name,
        material.zone,
        material.map_id,
        material.duration,
        baseline,
    )


def assign(
    deficits,
    members,
    posts,
    busy=frozenset(),
    recent=None,
    cap=guildroute.MAIL_RUN_YARDS,
    standing=(),
) -> FarmPlan:
    """One farming assignment per short, trackable material, and the mail
    steps that route what standing assignments gathered.

    `deficits` carry `entry`, `name` and `short` (reagent_deficits).
    `members` are the guild's Members and `posts` its corps Posts. `busy` is
    copied, never changed. `recent` are the cooldown readings keyed by
    (holder, action, key), read with this module's SOURCE prefix.
    `standing` are Tasks given on an earlier pass and still inside their
    stint: their gatherers keep farming, are not assigned again, and post
    only the stacks they gathered since. Returns the new tasks, the mail
    steps and any notes.
    """
    busy = set(busy or ())
    standing = tuple(standing or ())
    steps = _route_collected(standing, members, posts, busy, recent, cap)
    busy |= {t.bot for t in standing}
    farming = {t.material for t in standing}
    tasks = []
    notes = []
    for d in sorted(deficits, key=lambda d: (d.entry, d.name)):
        if d.short <= 0 or d.entry in farming:
            continue
        material = MATERIALS.get(d.entry)
        if material is None:
            notes.append("no farmed source is known for %s (%d)" % (d.name, d.entry))
            continue
        gatherer = _gatherer_for(posts, members, material.skill, busy)
        if gatherer is None:
            notes.append("no %s is free to farm %s" % (material.skill_name, d.name))
            continue
        busy.add(gatherer.name)
        tasks.append(_new_task(gatherer, material))
    return FarmPlan(tuple(tasks), tuple(steps), tuple(notes))
