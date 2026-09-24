"""How close each guild is to its first raid, and what stands in the way.

THE QUESTION THIS ANSWERS is the operator's goal, stated once per guild: forty
raiders in eight groups of five, ten on maintenance, twenty-one warlocks kept
for summoning, and a raid the guild can actually walk into. raidgoals.py
already counts the consumables a Molten Core night calls for and
raidlineup.py already decides who fills which place. Neither said whether the
guild could raid, so the Raid tab read as a shopping list with no verdict.

ONE ANSWER PER GUILD, because two families are two guilds on two factions, and
a raid is formed inside one guild. A merged count would put a Horde level ten
into an Alliance group and call the pair of them half a raid.

HARD AND SOFT ARE KEPT APART, and that split is the whole finding. A HARD
blocker stops the first raid outright: not enough raiders to fill the groups,
a group with no tank or no healer, a raider below the level the instance's own
access row asks for, or nothing in the overseer able to take a group inside.
A SOFT one makes the night worse and stops nothing: a raider below the level
cap, thin gear, no attunement shortcut, a short summoner corps, consumables
still to farm. A page that drew the two alike would send somebody farming
flasks for a raid its own coordinator cannot start.

PURE MODULE, same seam as raidgoals.py and dungeonplan.py: rows in, sentences
out, nothing that talks to MySQL. Every sentence a reader sees is written here
so a Python test can read it.
"""

from __future__ import annotations

import bank
import jobs
import raidgoals
import raidlineup
import raidrun

# The race ids of each faction, as `characters.race` stores them (3.3.5a).
ALLIANCE_RACES = frozenset({1, 3, 4, 7, 11})
HORDE_RACES = frozenset({2, 5, 6, 8, 10})

# The level cap on this realm, and the tier the first raid belongs to.
LEVEL_CAP = 60

# THE ATTUNEMENT QUEST, BOTH OF ITS ROWS. The pinned core's quest_template
# carries "Attunement to the Core" twice (7487 and 7848). Either one rewarded
# means Lothos Riftwaker will port that character in. It is a shortcut and not
# a gate: the Molten Core window beside him (areatrigger 3529 on Blackrock
# Mountain's own map) asks only a raid group and level 50, which is why a
# missing attunement is soft. raidrun.py carries the path to earning it.
ATTUNEMENT_QUESTS = (7487, 7848)

# A CONVENTION AND NOT A GATE. Molten Core's access row states no item level
# (min_avg_item_level is 0 on this realm). Players went in wearing dungeon
# blues, which sit at item level 55 to 63, so an average below 55 across the
# equipped slots is called thin and nothing more. Printed beside the number so
# it can be disagreed with.
GEAR_CONVENTION = 55

# The paper-doll slots that carry no stats worth averaging: the shirt and the
# tabard. Counting a level 1 shirt would drag every average down by a point.
COSMETIC_SLOTS = frozenset({3, 18})

# The keyword an ordered Molten Core night carries (`raid:moltencore`). Absent
# from jobs.RAID_KEYWORDS, mod-overseer's DoJob refuses the job, so no raid
# night can be started by the overseer at all.
RAID_PORTAL = raidrun.MOLTEN_CORE

# The paper-doll read's fire resistance, per raider, is item_template's own
# `fire_res` summed over worn items. Enchantments and buffs are not counted,
# the same limit raidgoals states for its resistance goal.
FIRE_PROTECTION = ("Greater Fire Protection Potion", "Fire Protection Potion")

# `characters.map` as a reader would say where somebody is. The raid walks to
# a door on Eastern Kingdoms; a raider anywhere else cannot follow the head
# there, and nothing summons them yet.
CONTINENTS = {0: "Eastern Kingdoms", 1: "Kalimdor", 530: "Outland", 571: "Northrend"}
DOOR_MAP = 0

HARD = "hard"
SOFT = "soft"


def faction_of(races) -> str:
    """ "Alliance", "Horde", or "" when the races say neither or both."""
    races = {int(r) for r in races if r is not None}
    alliance = bool(races & ALLIANCE_RACES)
    horde = bool(races & HORDE_RACES)
    if alliance and not horde:
        return "Alliance"
    if horde and not alliance:
        return "Horde"
    return ""


def group_guilds(guild_rows: list, families: dict) -> list:
    """Each family's guild, with every member of it, in family order.

    `families` is {family name: [its roster names]} in the order the page
    should draw them. A family none of whose members is in a guild is still
    drawn, with its own five as the roster and an empty guild name, because
    "no guild yet" is an answer the operator needs rather than a gap.
    """
    by_guild: dict = {}
    for row in guild_rows:
        if row.get("name") is None:
            continue
        key = row.get("guildid")
        entry = by_guild.setdefault(
            key, {"guildid": key, "guild": row.get("guild_name") or "", "rows": []}
        )
        entry["rows"].append(row)
    out = []
    seen = set()
    for family, names in families.items():
        homes = [
            g
            for g in by_guild.values()
            if any(r.get("name") in names for r in g["rows"])
        ]
        if not homes:
            out.append(
                {
                    "guildid": None,
                    "guild": "",
                    "family": family,
                    "family_names": list(names),
                    "rows": [],
                }
            )
            continue
        for home in homes:
            if home["guildid"] in seen:
                continue
            seen.add(home["guildid"])
            out.append(
                {
                    "guildid": home["guildid"],
                    "guild": home["guild"],
                    "family": family,
                    "family_names": [
                        n
                        for n in names
                        if any(r.get("name") == n for r in home["rows"])
                    ],
                    "rows": home["rows"],
                }
            )
    return out


def _count(count: int, one: str, many: str) -> str:
    return "%d %s" % (count, one if count == 1 else many)


def _names(members: list, limit: int = 3) -> str:
    """ "Oz 10, Uzza 10 and 3 more" - the lowest few, by level then name."""
    shown = [
        "%s %s"
        % (
            m["name"],
            m.get("level") if m.get("level") is not None else "(level unknown)",
        )
        for m in members[:limit]
    ]
    rest = len(members) - len(shown)
    if rest > 0:
        return "%s and %d more" % (", ".join(shown), rest)
    if len(shown) > 1:
        return "%s and %s" % (", ".join(shown[:-1]), shown[-1])
    return shown[0] if shown else ""


def worn_item_levels(worn_rows: list) -> dict:
    """name -> the average item level of what that character wears.

    Averaged over the slots that hold something, shirt and tabard left out.
    An empty slot is not counted as zero: an empty slot and a weak item are
    two different fixes, and averaging a zero in would blur them together.
    """
    totals: dict = {}
    for row in worn_rows:
        if row.get("slot") is not None and int(row["slot"]) in COSMETIC_SLOTS:
            continue
        level = row.get("item_level")
        if level is None:
            continue
        slot = totals.setdefault(row.get("name"), [0, 0])
        slot[0] += int(level)
        slot[1] += 1
    return {
        name: round(total / count) for name, (total, count) in totals.items() if count
    }


def _placed_raiders(lineup: dict) -> list:
    return [m for group in lineup["groups"] for m in group["members"]]


def _roles(lineup: dict) -> dict:
    counts = {"tank": 0, "healer": 0, "dps": 0}
    for member in _placed_raiders(lineup):
        counts[member.get("role", "dps")] = counts.get(member.get("role", "dps"), 0) + 1
    return counts


def _tile(label: str, have: int, want: int) -> dict:
    return {
        "label": label,
        "value": "%d / %d" % (have, want),
        "tone": "up" if have >= want else "no",
    }


def _by_level(members: list) -> list:
    return sorted(members, key=lambda m: (int(m.get("level") or 0), m["name"]))


def _staffing_blockers(
    lineup: dict, raiders: list, runnable: bool, clears: bool = True
) -> list:
    """The HARD blockers about who is there: the raid cannot start without."""
    out = []
    short = lineup["shortfall"]
    groups = raidlineup.RAIDERS // raidlineup.GROUP_SIZE
    if not runnable:
        out.append(
            "The overseer cannot take a raid in yet: mod-overseer's raid run "
            "only answers the raid keywords it has doors for (%s), and Molten "
            "Core is not one of them. Until it is, a raid night is somebody's "
            "manual work." % (", ".join(sorted(jobs.RAID_KEYWORDS)) or "none")
        )
    elif not clears:
        out.append(
            "Nothing clears Molten Core yet. An order forms the raid, walks it "
            "to the door and in with the head last, and then it holds at the "
            "entrance: the dungeon brain is kept off raid maps until clearing "
            "is built and ordered."
        )
    if short["raiders"]:
        out.append(
            "%s short of the %d a raid is planned for: the guild has %s to "
            "place."
            % (
                _count(short["raiders"], "raider", "raiders"),
                lineup["wanted"]["raiders"],
                _count(len(raiders), "raider", "raiders"),
            )
        )
    if short["tanks"]:
        out.append(
            "%s short: every one of the %d groups wants one, and only "
            "warriors, death knights, paladins and druids can hold the role."
            % (_count(short["tanks"], "tank", "tanks"), groups)
        )
    if short["healers"]:
        out.append(
            "%s short: every one of the %d groups wants one, and only "
            "priests, paladins, druids and shamans can heal."
            % (_count(short["healers"], "healer", "healers"), groups)
        )
    return out


def _level_blockers(raiders: list, min_level) -> tuple:
    """(hard, soft): below the instance's own gate, and merely below the cap."""
    gate = int(min_level) if min_level else 0
    under = _by_level([m for m in raiders if int(m.get("level") or 0) < gate])
    below = _by_level(
        [m for m in raiders if gate <= int(m.get("level") or 0) < LEVEL_CAP]
    )
    hard = (
        [
            "%s below level %d, the lowest the instance's own access row lets "
            "in: %s."
            % (_count(len(under), "raider is", "raiders are"), gate, _names(under))
        ]
        if under
        else []
    )
    soft = (
        [
            "%s allowed in but below level %d: %s."
            % (_count(len(below), "raider is", "raiders are"), LEVEL_CAP, _names(below))
        ]
        if below
        else []
    )
    return hard, soft


def _gear_blockers(raiders: list, gear: dict, attuned: set) -> list:
    """SOFT: thin gear against the convention, and the attunement shortcut."""
    out = []
    thin = sorted(
        (
            m
            for m in raiders
            if gear.get(m["name"]) is not None and gear[m["name"]] < GEAR_CONVENTION
        ),
        key=lambda m: (gear[m["name"]], m["name"]),
    )
    if thin:
        named = ", ".join("%s %d" % (m["name"], gear[m["name"]]) for m in thin[:3])
        if len(thin) > 3:
            named += " and %d more" % (len(thin) - 3)
        out.append(
            "%s gear averaging below item level %d, the dungeon blues players "
            "usually bring: %s."
            % (
                _count(len(thin), "raider wears", "raiders wear"),
                GEAR_CONVENTION,
                named,
            )
        )
    unattuned = [m for m in raiders if m["name"] not in attuned]
    if unattuned:
        out.append(
            "%d of %s %s Attunement to the Core. The Molten Core window in "
            "Blackrock Mountain admits a raid without it; it only opens Lothos "
            "Riftwaker's teleport."
            % (
                len(unattuned),
                _count(len(raiders), "raider", "raiders"),
                "lacks" if len(unattuned) == 1 else "lack",
            )
        )
    return out


def _support_blockers(lineup: dict, goals: dict) -> list:
    """SOFT: the people who never raid, and the consumables still to gather."""
    out = []
    short = lineup["shortfall"]
    if short["summoners"]:
        out.append(
            "%s short: summoning is a warlock spell and the guild has %s "
            "outside the raid. Summoning saves the walk; it does not stop the "
            "raid."
            % (
                _count(short["summoners"], "summoner", "summoners"),
                _count(len(lineup["summoners"]), "warlock", "warlocks"),
            )
        )
    if short["maintenance"]:
        out.append(
            "%s short of the %d who keep the bank, the crafting and the "
            "auction house going. They never raid, so this stops nothing."
            % (
                _count(short["maintenance"], "maintenance place", "maintenance places"),
                lineup["wanted"]["maintenance"],
            )
        )
    goal_list = goals.get("goals") or []
    unmet = [g for g in goal_list if g.get("status") != raidgoals.MET]
    if unmet:
        out.append(
            "%d of %s still to gather (%s). Molten Core admits a raid "
            "carrying none; the list is further down this page."
            % (
                len(unmet),
                _count(len(goal_list), "consumable goal", "consumable goals"),
                ", ".join(g["name"].lower() for g in unmet),
            )
        )
    return out


def _blockers(
    lineup: dict,
    raiders: list,
    min_level,
    gear: dict,
    attuned: set,
    goals: dict,
    runnable: bool,
    clears: bool = True,
) -> list:
    """Everything between this guild and its first raid, hard ones first."""
    level_hard, level_soft = _level_blockers(raiders, min_level)
    hard = _staffing_blockers(lineup, raiders, runnable, clears) + level_hard
    soft = (
        level_soft
        + _gear_blockers(raiders, gear, attuned)
        + _support_blockers(lineup, goals)
    )
    return [{"tone": HARD, "text": t} for t in hard] + [
        {"tone": SOFT, "text": t} for t in soft
    ]


def _headline(guild: str, family: str, hard: int, soft: int) -> str:
    who = guild or ("%s's family, in no guild" % family)
    if hard:
        line = "%s cannot raid Molten Core yet: %s the first raid" % (
            who,
            _count(hard, "thing stops", "things stop"),
        )
        if soft:
            line += ", and %d more would make it harder" % soft
        return line + "."
    if soft:
        return (
            "%s could form its first Molten Core raid today; %s would "
            "make the night easier." % (who, _count(soft, "thing", "things"))
        )
    return "%s is ready for its first Molten Core raid." % who


def _guild_members(group: dict, char_rows: list) -> list:
    """Everybody the lineup is chosen from: the guild, or the family alone."""
    by_name = {r["name"]: r for r in char_rows if r.get("name")}
    in_guild = {r["name"]: r for r in group["rows"] if r.get("name")}
    names = list(in_guild) or list(group["family_names"])
    members = []
    for name in dict.fromkeys(names):
        row = by_name.get(name) or {}
        guild_row = in_guild.get(name) or {}
        members.append(
            {
                "name": name,
                "level": row.get("level", guild_row.get("level")),
                "class_id": row.get("class", guild_row.get("class_id")),
                "race": guild_row.get("race", row.get("race")),
                "map": row.get("map"),
                "online": row.get("online"),
            }
        )
    return members


def _tiles(lineup: dict, raiders: list) -> list:
    roles = _roles(lineup)
    groups = raidlineup.RAIDERS // raidlineup.GROUP_SIZE
    at_cap = len([m for m in raiders if int(m.get("level") or 0) >= LEVEL_CAP])
    return [
        _tile("raiders placed", len(raiders), raidlineup.RAIDERS),
        _tile("tanks", roles["tank"], groups),
        _tile("healers", roles["healer"], groups),
        _tile("raiders at %d" % LEVEL_CAP, at_cap, raidlineup.RAIDERS),
        _tile("summoners", len(lineup["summoners"]), raidlineup.SUMMONERS),
        _tile("maintenance", len(lineup["maintenance"]), raidlineup.MAINTENANCE),
    ]


def _roster_line(members: list, lineup: dict, raiders: list) -> str:
    roles = _roles(lineup)
    return (
        "%s in the guild; %s placed as %s, %s and %s, one tank and one "
        "healer per group of five."
        % (
            _count(len(members), "character", "characters"),
            _count(len(raiders), "raider", "raiders"),
            _count(roles["tank"], "tank", "tanks"),
            _count(roles["healer"], "healer", "healers"),
            _count(roles["dps"], "damage dealer", "damage dealers"),
        )
    )


def _gear_line(raiders: list, gear: dict) -> str:
    worn = [gear[m["name"]] for m in raiders if m["name"] in gear]
    if not worn:
        return "Nothing the placed raiders wear could be read."
    return (
        "Placed raiders wear item level %d on average; %d or more is the "
        "usual convention for a first raid, not a rule the instance keeps."
        % (round(sum(worn) / len(worn)), GEAR_CONVENTION)
    )


def fire_resistance(worn_rows: list) -> dict:
    """name -> the fire resistance that character's worn items give."""
    out: dict = {}
    for row in worn_rows:
        name = row.get("name")
        out[name] = out.get(name, 0) + int(row.get("fire_res") or 0)
    return out


def carried(holding_rows: list, names: list, items: tuple) -> dict:
    """name -> how many of `items` that character carries or banks.

    bank.py places each stack, so a potion worn nowhere and a stack in a bank
    bag are counted the way the Bags tab counts them.
    """
    out = {name: 0 for name in names}
    for member in bank.members_from_rows(holding_rows or [], sorted(names)):
        for holding in list(member.carried) + list(member.banked):
            if holding.item.name in items:
                out[member.name] = out.get(member.name, 0) + int(holding.count)
    return out


# The per-raider table's columns, in order, as the page labels them. The page
# draws `cells` under these and decides nothing: every value is written here.
RAIDER_COLUMNS = (
    "group",
    "raider",
    "role",
    "level",
    "gear (avg ilvl)",
    "fire resistance",
    "attuned",
    "fire protection potions",
    "where",
)


def _cells(row: dict) -> list:
    return [
        str(row["group"]),
        row["name"],
        row["role"],
        "?" if row["level"] is None else str(row["level"]),
        "not read" if row["gear"] is None else str(row["gear"]),
        str(row["fire_res"]),
        "yes" if row["attuned"] else "no",
        str(row["fire_potions"]),
        row["where"],
    ]


def _where(member: dict) -> str:
    map_id = member.get("map")
    if map_id is None:
        return "unknown"
    place = CONTINENTS.get(int(map_id), "in an instance (map %d)" % int(map_id))
    return place if member.get("online") else "%s, offline" % place


def raider_rows(
    lineup: dict,
    members: list,
    gear: dict,
    fire: dict,
    attuned: set,
    potions: dict,
) -> list:
    """One row per placed raider: what the operator asked to see, per person.

    Group and role are the lineup's; level from characters; gear the average
    item level worn; fire resistance summed from worn items; attuned from the
    rewarded quest; where, from the saved map and the online flag, because a
    raider on another continent cannot follow the head to the door.
    """
    by_name = {m["name"]: m for m in members}
    rows = []
    for group in lineup["groups"]:
        for member in group["members"]:
            name = member["name"]
            seen = by_name.get(name, {})
            rows.append(
                {
                    "name": name,
                    "group": group.get("number"),
                    "role": member.get("role", "dps"),
                    "level": member.get("level"),
                    "gear": gear.get(name),
                    "fire_res": fire.get(name, 0),
                    "attuned": name in attuned,
                    "fire_potions": potions.get(name, 0),
                    "where": _where(seen),
                    "at_door_continent": seen.get("map") is not None
                    and int(seen["map"]) == DOOR_MAP,
                }
            )
            rows[-1]["cells"] = _cells(rows[-1])
    return rows


def _raiders_line(rows: list) -> str:
    if not rows:
        return "No raider is placed."
    attuned = len([r for r in rows if r["attuned"]])
    with_fire = len([r for r in rows if r["fire_res"]])
    fire = sum(r["fire_res"] for r in rows)
    potions = sum(r["fire_potions"] for r in rows)
    away = len([r for r in rows if not r["at_door_continent"]])
    return (
        "%d raiders: %d attuned, %d wearing any fire resistance (%d in all), "
        "%d fire protection potions carried, %d not on Eastern Kingdoms where "
        "the door is." % (len(rows), attuned, with_fire, fire, potions, away)
    )


def build_guild(
    group: dict,
    char_rows: list,
    worn_rows: list,
    attuned_rows: list,
    min_level,
    goals: dict,
    *,
    quest_rows: list = (),
    holding_rows: list = (),
) -> dict:
    """One guild's readiness card.

    `group` is one entry of group_guilds. `char_rows` carry name, level and
    class for every character the raid fetch read; the ones in this guild are
    who the lineup is chosen from. `attuned_rows` are {"name"} rows for every
    character with either attunement quest rewarded. `min_level` is the
    instance's own access-row minimum, or None when the realm did not say.
    `goals` is raidgoals.build_raidgoals for this guild. `quest_rows` are
    {"name", "status"} rows for the attunement quest held in a log, and
    `holding_rows` the Raid tab's bag read, for fragments and potions.
    """
    members = _guild_members(group, char_rows)
    lineup = raidlineup.build_lineup(members, guaranteed=group["family_names"])
    raiders = _placed_raiders(lineup)
    gear = worn_item_levels(worn_rows)
    attuned = {r["name"] for r in attuned_rows if r.get("name")}
    blockers = _blockers(
        lineup,
        raiders,
        min_level,
        gear,
        attuned,
        goals,
        RAID_PORTAL in jobs.RAID_KEYWORDS,
        raidrun.CLEARS,
    )
    names = [m["name"] for m in raiders]
    rows = raider_rows(
        lineup,
        members,
        gear,
        fire_resistance(worn_rows),
        attuned,
        carried(holding_rows, names, FIRE_PROTECTION),
    )
    in_log = {
        r["name"]
        for r in quest_rows
        if r.get("name") and int(r.get("status") or 0) in raidrun.IN_LOG_STATUSES
    }
    fragments = carried(
        holding_rows, list(group["family_names"]), (raidrun.CORE_FRAGMENT,)
    )
    hard = len([b for b in blockers if b["tone"] == HARD])
    faction = faction_of(m["race"] for m in members)
    name = group["guild"] or "%s's family" % group["family"]
    return {
        "guild": group["guild"],
        "family": group["family"],
        "faction": faction,
        "title": name + (" (%s)" % faction if faction else ""),
        "ready": hard == 0,
        "headline": _headline(
            group["guild"], group["family"], hard, len(blockers) - hard
        ),
        "tiles": _tiles(lineup, raiders),
        "roster_line": _roster_line(members, lineup, raiders),
        "gear_line": _gear_line(raiders, gear),
        "blockers": blockers,
        "blockers_line": (
            "Nothing stands between this guild and its first raid."
            if not blockers
            else "What stops the first raid is listed first; the rest would only "
            "make it harder."
        ),
        "goals": goals,
        "raiders": rows,
        "raider_columns": list(RAIDER_COLUMNS),
        "raiders_line": _raiders_line(rows),
        "run_line": raidrun.run_line(),
        "clearing_line": raidrun.DUNGEON_CLEAR_LINE,
        "attunement": raidrun.attunement(
            list(group["family_names"]), attuned, in_log, fragments
        ),
    }


def build_readiness(groups: list) -> dict:
    """Both guilds' cards, and the one line above them."""
    ready = [g for g in groups if g["ready"]]
    if not groups:
        line = "no family was found on the roster, so there is no guild to judge"
    elif len(ready) == len(groups):
        line = "every guild could form its first raid today"
    else:
        line = "%d of %s could form its first raid today" % (
            len(ready),
            _count(len(groups), "guild", "guilds"),
        )
    return {
        "line": line,
        "goal_line": (
            "The goal for each guild: %d raiders in %d groups of %d, %d on "
            "maintenance and %d warlocks for summoning. Molten Core is the "
            "first raid at this level cap."
            % (
                raidlineup.RAIDERS,
                raidlineup.RAIDERS // raidlineup.GROUP_SIZE,
                raidlineup.GROUP_SIZE,
                raidlineup.MAINTENANCE,
                raidlineup.SUMMONERS,
            )
        ),
        "guilds": groups,
        "basis": (
            "Who fills which place is the Lineup tab's own selection "
            "(raidlineup.py). Levels and classes from characters, guilds from "
            "guild_member, gear from the item_template item level of every "
            "worn slot except shirt and tabard, attunement from "
            "character_queststatus_rewarded, and the lowest level the "
            "instance admits from its own dungeon_access_template row. "
            "Whether the overseer can run the raid at all is read from the "
            "portal keywords the site knows mod-overseer carries. The item "
            "level of %d is a convention and is labelled as one wherever it "
            "appears." % GEAR_CONVENTION
        ),
    }
