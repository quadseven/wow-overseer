"""Who fills the guild's 71 places, and who is surplus to them.

THE LAW THIS ENFORCES, in the operator's own words: forty raiders in perfect
five-man groups, ten on maintenance, and twenty-one warlocks kept for
summoning. Seventy-one places, and a guild that holds more than that holds
people nobody chose.

WHY THE GUILD DOES NOT ALREADY LOOK LIKE THIS. Nothing selected its members.
The realm's random-bot rotation adds characters to a guild as ordinary
background behaviour, so the roster is an accident of who happened to be
rolled and when. The law is new; the guild predates it. That is the whole of
the discrepancy, and it is why the fix is a selection rather than a repair.

SUMMONERS ARE WARLOCKS, AND THAT IS THE GAME'S RULE RATHER THAN A PREFERENCE.
Ritual of Summoning is a warlock spell. A summoner corps can therefore only be
as large as the warlocks available to it, and asking for twenty-one when the
guild holds five is not a scheduling problem - it is a recruiting one. This
module never invents a summoner out of another class to make the count come
out; it fills what it can and reports the shortfall as a number the page can
show.

THE FAMILY IS PLACED FIRST AND IS NEVER SURPLUS. They are the characters with
names somebody chose, the two of them stream, and a lineup that benched one to
fit a better-rolled stranger would be optimising the wrong thing.

WHAT THIS MODULE IS NOT. It never talks to MySQL and never kicks anybody. It
takes a roster in and hands a lineup back, so the decision can be read on a
page before anything irreversible happens to a guild. The caller owns the
world.
"""

from __future__ import annotations

import raidroles

# WotLK class ids, as the realm's own `characters.class` column stores them.
WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST = 1, 2, 3, 4, 5
DEATH_KNIGHT, SHAMAN, MAGE, WARLOCK, DRUID = 6, 7, 8, 9, 11

CLASS_NAMES = {
    WARRIOR: "Warrior",
    PALADIN: "Paladin",
    HUNTER: "Hunter",
    ROGUE: "Rogue",
    PRIEST: "Priest",
    DEATH_KNIGHT: "Death Knight",
    SHAMAN: "Shaman",
    MAGE: "Mage",
    WARLOCK: "Warlock",
    DRUID: "Druid",
}

# Who can hold a slot. A hybrid appears in both lists on purpose - the
# assignment below spends the pure classes first precisely so the hybrids are
# still free when a gap has to be filled.
TANKS = frozenset({WARRIOR, DEATH_KNIGHT, PALADIN, DRUID})
HEALERS = frozenset({PRIEST, PALADIN, DRUID, SHAMAN})
# The classes that can ONLY tank or ONLY heal among the above. Spending these
# first is the whole of the packing strategy: a Paladin placed as a tank is a
# healer the roster no longer has, and there is no way back from that inside
# one pass.
PURE_TANKS = frozenset({WARRIOR, DEATH_KNIGHT})
PURE_HEALERS = frozenset({PRIEST})

RAIDERS, MAINTENANCE, SUMMONERS, GROUP_SIZE = 40, 10, 21, 5


def _sort_key(member: dict, guaranteed: frozenset) -> tuple:
    """Guaranteed first, then the highest level, then by name.

    Name last and always, so two runs over the same roster produce the same
    lineup. A lineup that reshuffled on every poll would make the kick list
    below it meaningless.
    """
    return (
        0 if member["name"] in guaranteed else 1,
        -int(member.get("level") or 0),
        member["name"],
    )


def _take(pool: list, want: int, allowed: frozenset | None = None, test=None) -> list:
    """Pull up to `want` members whose class is in `allowed` and who pass
    `test`, in pool order."""
    taken = []
    for member in list(pool):
        if len(taken) >= want:
            break
        if allowed is not None and member.get("class_id") not in allowed:
            continue
        if test is not None and not test(member):
            continue
        taken.append(member)
        pool.remove(member)
    return taken


# EIGHT PERFECT GROUPS OF FIVE (the operator, 2026-09-26). Every group is one
# tank, one healer and three damage dealers, so each also works as a dungeon
# party, and the raid's group buffs are spread: a paladin or a shaman in each
# group where the guild has them, a priest's Fortitude, a druid's Mark.
#
# THE SEATS ARE PLANNED FROM CLASSES. The natural guilds' bots start again at
# level 1 and choose talents as they level, so a talent tree read today is a
# preference, not a fact the plan must keep. Each placed raider gets the tree
# its seat needs (`target_spec`, `target_tab`), which mod-overseer's
# overseer_raid_spec takes so the bot spends its points there. A raider
# already in a tree that fits its seat keeps it. The family is the exception:
# a family character's tree is the operator's decision (the roster's spec
# tab), so it takes the seat its tree plays and is never planned a respec.
TANKS_PER_GROUP, HEALERS_PER_GROUP = 1, 1
DAMAGE_PER_GROUP = GROUP_SIZE - TANKS_PER_GROUP - HEALERS_PER_GROUP
# Below this many tanks a raid cannot hold a fight at all (raidready's hard
# blocker); between it and one a group, the raid runs thin.
MIN_TANKS = 2

# The duty words, written on each placed raider and into the seat table.
MAIN_TANK, OFF_TANK = "main tank", "off tank"
HEALER_WORD = "healer"
DAMAGE_WORD = "damage"

# The group buffs a raid leader spreads, by the class that brings them. A
# paladin's blessings and a shaman's totems are one need: either fills it.
BLESSINGS, FORTITUDE, MARK = "blessings or totems", "fortitude", "mark"
BUFF_OF = {PALADIN: BLESSINGS, SHAMAN: BLESSINGS, PRIEST: FORTITUDE, DRUID: MARK}
BUFFS = (BLESSINGS, FORTITUDE, MARK)

# Who to recruit for a missing seat, most useful first. A class that fills
# only the missing seat comes before a hybrid, which could be taken for the
# other. No death knight: recruits start at level 1 under the natural rules,
# and a death knight starts at 55.
RECRUIT_FOR = {
    "tanks": (WARRIOR, PALADIN, DRUID),
    "healers": (PRIEST, SHAMAN, PALADIN, DRUID),
}

_SEAT_ROLE = {
    raidroles.SEAT_TANK: "tank",
    raidroles.SEAT_HEALER: "healer",
    raidroles.SEAT_DAMAGE: "dps",
}


def _locked_seat(member: dict, guaranteed: frozenset) -> str:
    """The seat a family character's own tree plays, or "" when it is free."""
    if member["name"] not in guaranteed or not member.get("spec"):
        return ""
    role = member.get("raid_role")
    if role == raidroles.TANK:
        return raidroles.SEAT_TANK
    if role == raidroles.HEALER:
        return raidroles.SEAT_HEALER
    return raidroles.SEAT_DAMAGE


def _fits(seat: str):
    return lambda m: raidroles.fits_seat(m.get("class_id"), m.get("spec"), seat)


def _free_tree(member: dict) -> bool:
    return not member.get("spec")


def _pick_seats(pool: list, guaranteed: frozenset, groups: int) -> tuple:
    """(tanks, healers, damage) for `groups` groups, taken out of `pool`.

    The family first, each to the seat its tree plays. Then, for the tanks
    and the healers: a tree that already fits the seat; a class that can
    only take that seat (warrior and death knight tank, priest heals; a
    shaman heals but cannot tank), free trees before ones that would
    respec; and last the hybrids (paladin, druid), each to whichever of the
    two seats is shorter, so a guild short of both is short evenly. Then the
    damage dealers: the family, a class that brings a group buff, the rest.
    """
    want = {
        raidroles.SEAT_TANK: groups * TANKS_PER_GROUP,
        raidroles.SEAT_HEALER: groups * HEALERS_PER_GROUP,
        raidroles.SEAT_DAMAGE: groups * DAMAGE_PER_GROUP,
    }
    seats = {seat: [] for seat in want}

    def room(seat):
        return want[seat] - len(seats[seat])

    for member in [m for m in pool if _locked_seat(m, guaranteed)]:
        seat = _locked_seat(member, guaranteed)
        if room(seat) <= 0:
            continue
        pool.remove(member)
        seats[seat].append(member)

    def take(seat, allowed=None, test=None):
        seats[seat] += _take(pool, max(0, room(seat)), allowed, test)

    tank, healer = raidroles.SEAT_TANK, raidroles.SEAT_HEALER
    pure_tanks, pure_healers = frozenset({WARRIOR, DEATH_KNIGHT}), frozenset({PRIEST})
    healer_only = frozenset({PRIEST, SHAMAN})
    hybrids = frozenset({PALADIN, DRUID})

    take(tank, None, _fits(tank))
    take(healer, None, _fits(healer))
    take(tank, pure_tanks, _free_tree)
    take(tank, pure_tanks)
    take(healer, pure_healers, _free_tree)
    take(healer, healer_only, _free_tree)
    take(healer, pure_healers)
    take(healer, healer_only)
    for test in (_free_tree, None):
        while room(tank) > 0 or room(healer) > 0:
            seat = tank if room(tank) >= room(healer) else healer
            got = _take(pool, 1, hybrids, test)
            if not got:
                break
            seats[seat] += got

    take(raidroles.SEAT_DAMAGE, None, lambda m: m["name"] in guaranteed)
    take(raidroles.SEAT_DAMAGE, frozenset(BUFF_OF))
    take(raidroles.SEAT_DAMAGE)
    return seats[tank], seats[healer], seats[raidroles.SEAT_DAMAGE]


def _target(member: dict, seat: str, guaranteed: frozenset) -> str:
    if _locked_seat(member, guaranteed) == seat:
        return member.get("spec") or ""
    return raidroles.target_tree(member.get("class_id"), seat, member.get("spec"))


def _label(member: dict) -> str:
    duty, target, spec = member["duty"], member.get("target_spec"), member.get("spec")
    if not target:
        return duty
    if member.get("respec"):
        return "%s, %s (now %s)" % (duty, target, spec)
    return "%s, %s" % (duty, target)


def _placed(member: dict, seat: str, duty: str, guaranteed: frozenset) -> dict:
    target = _target(member, seat, guaranteed)
    if seat == raidroles.SEAT_DAMAGE:
        duty = (
            raidroles.seat_duty(member.get("class_id"), target)
            if target
            else DAMAGE_WORD
        )
    out = dict(
        member,
        role=_SEAT_ROLE[seat],
        seat=seat,
        duty=duty,
        target_spec=target,
        target_tab=raidroles.tree_tab(member.get("class_id"), target),
        respec=bool(member.get("spec"))
        and bool(target)
        and member.get("spec") != target,
        buff=BUFF_OF.get(member.get("class_id"), ""),
    )
    out["label"] = _label(out)
    return out


def _buffs(group: list) -> set:
    return {m["buff"] for m in group if m.get("buff")}


def _scarcity(members: list) -> dict:
    """buff -> how many of the members bring it; the rarest is placed first."""
    out: dict = {}
    for m in members:
        if m.get("buff"):
            out[m["buff"]] = out.get(m["buff"], 0) + 1
    return out


def _deal(groups: list, members: list, cap: int, kind=None) -> None:
    """Deal `members` into the groups, at most `cap` of this kind a group.

    A buff bearer goes to the group that lacks its buff and has the fewest
    buffs, the rarest buff first so it is not spent where a commoner one would
    do. Anyone else goes where the fewest of its own duty stand (a dungeon
    party wants a mix), then to the emptiest group. Ties to the lowest group.
    """
    count = _scarcity(members)
    ordered = sorted(
        members,
        key=lambda m: (0 if m.get("buff") else 1, count.get(m.get("buff"), 0)),
    )
    for member in ordered:
        open_ = [
            i
            for i, g in enumerate(groups)
            if len([m for m in g if (kind is None or m["seat"] == kind)]) < cap
            and len(g) < GROUP_SIZE
        ]
        if not open_:
            return

        def key(i):
            group = groups[i]
            lacks = (
                0 if member.get("buff") and member["buff"] not in _buffs(group) else 1
            )
            same = len([m for m in group if m["duty"] == member["duty"]])
            return (lacks, len(_buffs(group)), same, len(group), i)

        groups[min(open_, key=key)].append(member)


def _groups(tanks: list, healers: list, damage: list, count: int) -> list:
    """Eight groups: a tank each (the main tank in group 1), a healer each (a
    priest in group 1 when there is one, for Power Word: Shield on the main
    tank), and three damage dealers each, the buffs spread."""
    groups = [[] for _ in range(count)]
    if not count:
        return groups
    for index, tank in enumerate(tanks[:count]):
        groups[index].append(tank)
    healers = list(healers[:count])
    priest = next((h for h in healers if h.get("class_id") == PRIEST), None)
    if priest is not None:
        healers.remove(priest)
        groups[0].append(priest)
    _deal(groups, healers, HEALERS_PER_GROUP, raidroles.SEAT_HEALER)
    _deal(groups, damage, DAMAGE_PER_GROUP, raidroles.SEAT_DAMAGE)
    return groups


# A buff no group can have because too few raiders bring it: recruit the
# classes that do, after any missing seat.
RECRUIT_FOR_BUFF = {BLESSINGS: (PALADIN, SHAMAN), MARK: (DRUID,), FORTITUDE: (PRIEST,)}


def _recruit_classes(gaps: dict, cover: dict | None = None, groups: int = 0) -> list:
    """The classes recruiting prefers, most useful first: those that fill a
    missing tank or healer seat (a paladin or a druid first when both are
    short, since either fills either), then those that bring a group buff
    fewer raiders bring than there are groups."""
    wanted = [seat for seat in ("tanks", "healers") if gaps.get(seat)]
    if len(wanted) == 2:
        both = [c for c in RECRUIT_FOR["tanks"] if c in RECRUIT_FOR["healers"]]
        out = both + [c for s in wanted for c in RECRUIT_FOR[s] if c not in both]
    elif wanted:
        out = list(RECRUIT_FOR[wanted[0]])
    else:
        out = []
    for buff in BUFFS:
        if cover and groups and cover.get(buff, {}).get("bearers", 0) < groups:
            out += list(RECRUIT_FOR_BUFF[buff])
    return list(dict.fromkeys(out))


def _buff_cover(groups: list, raiders: list) -> dict:
    """buff -> (groups holding it, raiders who bring it)."""
    return {
        buff: {
            "groups": len([g for g in groups if buff in _buffs(g["members"])]),
            "bearers": len([m for m in raiders if m.get("buff") == buff]),
        }
        for buff in BUFFS
    }


def build_lineup(
    members: list,
    guaranteed=(),
    *,
    raiders: int = RAIDERS,
    maintenance: int = MAINTENANCE,
    summoners: int = SUMMONERS,
    group_size: int = GROUP_SIZE,
) -> dict:
    """Fill the lineup from `members`, and say what could not be filled.

    `members` is a list of dicts with `name`, `level` and `class_id`, and
    `talent_spells` (raidroles.TALENTS_COLUMN) where the read carried it.
    Anyone the lineup cannot place comes back under `surplus` - that is the
    kick list, and it is a list rather than a count so a page can name every
    character before a person acts on it.

    Each placed raider carries `role` (tank, healer or dps), `seat`, `spec`
    (the tree it plays now, or ""), `raid_role`, `duty` (main tank, off tank,
    healer, melee, ranged, caster or damage), `target_spec` and `target_tab`
    (the tree the seat needs), `respec` (it plays another tree now), `buff`
    and `label`. Each group carries `buffs` and `missing_buffs`. The lineup
    carries `gaps` (seats no class in the guild can fill), `recruit_classes`
    (the classes to recruit for them) and `buff_cover`.
    """
    guaranteed = frozenset(guaranteed)
    pool = sorted(
        (raidroles.with_spec(m) for m in members if m.get("name")),
        key=lambda m: _sort_key(m, guaranteed),
    )
    count = raiders // group_size if group_size else 0

    # SUMMONERS BEFORE RAIDERS, because the corps is class-locked and the raid
    # is not. Warlocks spent as raid DPS cannot be recovered for summoning,
    # and a warlock is a perfectly ordinary DPS that many other classes can
    # replace - so the scarce use wins the tie.
    summoner_corps = _take(pool, summoners, frozenset({WARLOCK}))

    # A guaranteed character is never left in the summoner corps by accident:
    # the family raids. Put any back at the front of the pool.
    for member in [m for m in summoner_corps if m["name"] in guaranteed]:
        summoner_corps.remove(member)
        pool.insert(0, member)

    tank_list, healer_list, damage_list = _pick_seats(pool, guaranteed, count)
    upkeep = _take(pool, maintenance)

    tanks = [
        _placed(m, raidroles.SEAT_TANK, MAIN_TANK if i == 0 else OFF_TANK, guaranteed)
        for i, m in enumerate(tank_list)
    ]
    healers = [
        _placed(m, raidroles.SEAT_HEALER, HEALER_WORD, guaranteed) for m in healer_list
    ]
    damage = [
        _placed(m, raidroles.SEAT_DAMAGE, DAMAGE_WORD, guaranteed) for m in damage_list
    ]
    dealt = _groups(tanks, healers, damage, count)
    groups = [
        {
            "number": index + 1,
            "members": group,
            "buffs": [b for b in BUFFS if b in _buffs(group)],
            "missing_buffs": [b for b in BUFFS if b not in _buffs(group)],
        }
        for index, group in enumerate(dealt)
    ]

    placed = [m for g in groups for m in g["members"]]
    composition: dict = {}
    for member in placed:
        composition[member["duty"]] = composition.get(member["duty"], 0) + 1
    wanted = {
        "raiders": raiders,
        "maintenance": maintenance,
        "summoners": summoners,
        "total": raiders + maintenance + summoners,
        "groups": count,
        "tanks": count * TANKS_PER_GROUP,
        "healers": count * HEALERS_PER_GROUP,
        "damage": count * DAMAGE_PER_GROUP,
    }
    gaps = {
        "tanks": max(0, wanted["tanks"] - len(tanks)),
        "healers": max(0, wanted["healers"] - len(healers)),
        "damage": max(0, wanted["damage"] - len(damage)),
    }
    cover = _buff_cover(groups, placed)
    recruit = _recruit_classes(gaps, cover, count)
    return {
        "groups": groups,
        "maintenance": [dict(m, role="maintenance") for m in upkeep],
        "summoners": [dict(m, role="summoner") for m in summoner_corps],
        "surplus": list(pool),
        "wanted": wanted,
        "shortfall": {
            "raiders": max(0, raiders - len(placed)),
            "maintenance": max(0, maintenance - len(upkeep)),
            "summoners": max(0, summoners - len(summoner_corps)),
            **gaps,
        },
        "gaps": gaps,
        "recruit_classes": recruit,
        "buff_cover": cover,
        "counts": {
            "raiders": len(placed),
            "maintenance": len(upkeep),
            "summoners": len(summoner_corps),
            "surplus": len(pool),
            "considered": len(members),
            "respec": len([m for m in placed if m.get("respec")]),
        },
        "composition": composition,
        "roles_line": roles_line(groups, wanted),
        "gap_line": gap_line(gaps, recruit, cover, count),
    }


def roles_line(groups: list, wanted: dict) -> str:
    """The raid's make-up in one sentence, as a raid leader would say it."""
    placed = [m for g in groups for m in g["members"]]
    if not placed:
        return "Nobody is placed, so there is no raid to describe."
    main = next((m for m in placed if m["duty"] == MAIN_TANK), None)

    def seated(seat):
        return len([m for m in placed if m["seat"] == seat])

    def duty(word):
        return len([m for m in placed if m["duty"] == word])

    kinds = [
        "%d %s" % (duty(word), word)
        for word in (raidroles.MELEE, raidroles.RANGED, raidroles.CASTER, DAMAGE_WORD)
        if duty(word)
    ]
    full = len(
        [
            g
            for g in groups
            if [m["seat"] for m in g["members"]].count(raidroles.SEAT_TANK)
            == TANKS_PER_GROUP
            and [m["seat"] for m in g["members"]].count(raidroles.SEAT_HEALER)
            == HEALERS_PER_GROUP
            and len(g["members"]) == GROUP_SIZE
        ]
    )
    respec = len([m for m in placed if m.get("respec")])
    return (
        "%d of %d tanks%s, %d of %d healers, %d of %d damage%s. %d of %d groups "
        "are a full tank, healer and three damage dealers; each raider is "
        "given the talent tree its seat needs%s."
        % (
            seated(raidroles.SEAT_TANK),
            wanted["tanks"],
            " (%s the main tank)" % main["name"] if main else "",
            seated(raidroles.SEAT_HEALER),
            wanted["healers"],
            seated(raidroles.SEAT_DAMAGE),
            wanted["damage"],
            " (%s)" % ", ".join(kinds) if kinds else "",
            full,
            wanted["groups"],
            "; %d play another tree now" % respec if respec else "",
        )
    )


def gap_line(
    gaps: dict, recruit: list, cover: dict | None = None, groups: int = 0
) -> str:
    """The seats no class in the guild can fill, the buffs too few raiders
    bring to reach every group, and who recruiting prefers for them."""
    short = [
        "%d %s" % (gaps[k], k[:-1] if gaps[k] == 1 else k)
        for k in ("tanks", "healers", "damage")
        if gaps.get(k)
    ]
    line = (
        "Short %s." % ", ".join(short)
        if short
        else "No seat gap: every seat of the %d groups has a raider of a class that can fill it."
        % groups
    )
    thin = [
        "%s reaches %d of %d" % (buff, cover[buff]["groups"], groups)
        for buff in BUFFS
        if cover and groups and cover.get(buff, {}).get("bearers", 0) < groups
    ]
    if thin:
        line += " Too few raiders bring a buff to every group: %s." % "; ".join(thin)
    if recruit:
        line += " Recruiting prefers %s." % ", ".join(CLASS_NAMES[c] for c in recruit)
    return line


# The party role words, as armory.py and gear.py spell them.
TANK, HEALER, DAMAGE = "tank", "healer", "damage"


def party_roles(members) -> dict:
    """name -> tank, healer or damage, for one party of five.

    The packing `build_lineup` uses, at the size of one group: the tank is the
    first member whose class can ONLY tank, else the first who can; the healer
    likewise; everybody else deals damage. `members` are dicts with `name` and
    `class_id`, in the order ties should break (the roster's). The caller
    decides who is present; a member left out gets no role.
    """
    pool = [m for m in members if m.get("name")]

    def take(allowed):
        for m in pool:
            if m.get("class_id") in allowed:
                pool.remove(m)
                return m
        return None

    roles = {}
    tank = take(PURE_TANKS) or take(TANKS)
    if tank:
        roles[tank["name"]] = TANK
    healer = take(PURE_HEALERS) or take(HEALERS)
    if healer:
        roles[healer["name"]] = HEALER
    for m in pool:
        roles[m["name"]] = DAMAGE
    return roles
