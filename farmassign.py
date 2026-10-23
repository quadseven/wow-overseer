"""Farming assignments: connect the raid's consumable deficits to bots that
gather the missing materials and mail them to the crafters who need them.

Pure module: deficits in, assignments and mail steps out. Nothing here talks
to MySQL, touches a clock or writes the command log. The bridge reads the
facts, runs the assignment, logs `farmassign: assigned <bot> to <material>`
for each task, and runs the mail steps with the corps' own runner.

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
"""

from __future__ import annotations

from dataclasses import dataclass

import classic
import guildcorps as gc
import guildroute

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


# Eastern Kingdoms = 0, Kalimdor = 1, the continent a gatherer stands on.
# A material missing from this table has no known farmed source and is named
# in the plan's notes instead of being dropped silently.
MATERIALS: dict[int, Material] = {
    13463: Material(
        13463,
        "Dreamfoil",
        HERBALISM,
        "herbalism",
        "Eastern Plaguelands",
        0,
        HERB_DURATION,
    ),
    13464: Material(
        13464,
        "Golden Sansam",
        HERBALISM,
        "herbalism",
        "Western Plaguelands",
        0,
        HERB_DURATION,
    ),
    13465: Material(
        13465,
        "Mountain Silversage",
        HERBALISM,
        "herbalism",
        "Silithus",
        1,
        HERB_DURATION,
    ),
    13466: Material(
        13466,
        "Plaguebloom",
        HERBALISM,
        "herbalism",
        "Eastern Plaguelands",
        0,
        HERB_DURATION,
    ),
    13467: Material(
        13467, "Icecap", HERBALISM, "herbalism", "Winterspring", 1, HERB_DURATION
    ),
    13468: Material(
        13468,
        "Black Lotus",
        HERBALISM,
        "herbalism",
        "Western Plaguelands",
        0,
        HERB_DURATION,
    ),
    8846: Material(
        8846, "Gromsblood", HERBALISM, "herbalism", "Blasted Lands", 0, HERB_DURATION
    ),
    3818: Material(
        3818, "Fadeleaf", HERBALISM, "herbalism", "Arathi Highlands", 0, HERB_DURATION
    ),
    7067: Material(
        7067, "Elemental Earth", MINING, "mining", "Arathi Highlands", 0, ORE_DURATION
    ),
    7912: Material(
        7912, "Solid Stone", MINING, "mining", "The Hinterlands", 0, ORE_DURATION
    ),
    12365: Material(
        12365, "Dense Stone", MINING, "mining", "Western Plaguelands", 0, ORE_DURATION
    ),
}

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


@dataclass(frozen=True)
class FarmPlan:
    """The assignments and mail steps for one pass.

    `tasks` are logged live as `farmassign: assigned <bot> to <material>`.
    `steps` route collected material to the designated crafters by mail.
    """

    tasks: tuple
    steps: tuple
    notes: tuple


def source_for(action, key) -> str:
    return "%s:%s:%d" % (SOURCE, action, int(key))


def _stack(member, entry):
    """The member's biggest carried stack of `entry`, or None."""
    held = [h for h in member.carried if int(h.entry) == int(entry)]
    return max(held, key=lambda h: (int(h.count), -int(h.guid))) if held else None


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
        if classic.is_expansion_map(m.map_id):
            continue
        out.append(m)
    out.sort(key=lambda m: (-int(m.skill(skill)[0]), m.name))
    return out


def _gatherer_for(posts, members, skill, busy):
    """The best free gatherer for `skill`, or None."""
    cands = _online_gatherers(posts, members, skill, busy)
    return cands[0] if cands else None


def _crafter_for(material, members, posts, busy) -> object:
    """The member whose corps post consumes `material`, or None."""
    craft = CRAFT_OF.get(material.entry)
    if craft is None:
        return None
    by_name = {m.name: m for m in members or ()}
    for p in posts or ():
        if int(p.skill) != int(craft):
            continue
        m = by_name.get(p.name)
        if m is None or not m.online or m.name in busy or m.family:
            continue
        if classic.is_expansion_map(m.map_id):
            continue
        return m
    return None


def _holder_for(entry, members, busy, skip) -> object:
    """An online member who already carries `entry`, most of it first, not
    `skip` and not busy."""
    out = []
    for m in members or ():
        if m.name in busy or m.name == skip or not m.online or m.family:
            continue
        if m.count(entry) > 0:
            out.append(m)
    out.sort(key=lambda m: (-m.count(entry), m.name))
    return out[0] if out else None


def _cooling(step, recent) -> bool:
    minutes = COOLDOWN_MINUTES.get(step.action, 30)
    age = (recent or {}).get((step.holder, step.action, int(step.key)))
    return age is not None and age < minutes


def _post_step(holder, entry, name, crafter, cap) -> object:
    """The holder's stack of `entry`, posted by mail to the crafter."""
    stack = _stack(holder, entry)
    if stack is None:
        return None
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


def assign(
    deficits,
    members,
    posts,
    busy=frozenset(),
    recent=None,
    cap=guildroute.MAIL_RUN_YARDS,
) -> FarmPlan:
    """One farming assignment per short, trackable material.

    `deficits` are raidsupply.Line-shaped objects carrying `entry`, `name` and
    `short`. `members` are the guild's Members and `posts` its corps Posts.
    `busy` is shared with the corps plan and is added to, so no member takes
    two steps. `recent` are the last-pass cooldown readings keyed by
    (holder, action, key). Returns the tasks, the mail steps and any notes.
    """
    busy = set(busy or ())
    tasks = []
    steps = []
    notes = []
    for d in sorted(deficits, key=lambda d: (d.entry, d.name)):
        if d.short <= 0:
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
        tasks.append(
            Task(
                gatherer.name,
                material.entry,
                material.name,
                material.zone,
                material.map_id,
                material.duration,
            )
        )
        crafter = _crafter_for(material, members, posts, busy)
        if crafter is not None:
            holder = _holder_for(material.entry, members, busy, gatherer.name)
            if holder is not None and holder.name != crafter.name:
                step = _post_step(
                    holder, material.entry, material.name, crafter.name, cap
                )
                if step is not None and not _cooling(step, recent):
                    steps.append(step)
                    busy.add(holder.name)
    return FarmPlan(tuple(tasks), tuple(steps), tuple(notes))
