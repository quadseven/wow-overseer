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


# A CLASSIC MOLTEN CORE RAID, not one tank and one healer per group. Guilds
# brought a main tank and three off tanks (Garr's adds, Majordomo's guards,
# the Ragnaros tank swap) and about three healers in ten. Per forty raiders:
# four tanks and twelve healers. A raid below the minimums cannot hold the
# fights at all: two tanks, and one healer for each group.
TANKS_PER_TEN = 1
HEALERS_PER_TEN = 3
MIN_TANKS = 2

# The duty words, written on each placed raider and into the seat table.
MAIN_TANK, OFF_TANK = "main tank", "off tank"
DAMAGE_WORD = "damage"

# Damage dealers are grouped by kind, the way a raid leader groups them: the
# melee together (shouts, Windfury, Leader of the Pack reach their own group
# only), then the hunters (Trueshot Aura), then the casters (Moonkin Aura, a
# priest's spirit). A damage dealer whose tree is unknown goes last.
_DPS_ORDER = {
    raidroles.TANK: 0,
    raidroles.MELEE: 1,
    raidroles.RANGED: 2,
    raidroles.CASTER: 3,
}


def _known_tree(member: dict) -> bool:
    return bool(member.get("spec"))


def _plays(role: str):
    return lambda member: member.get("raid_role") == role


def _unknown_tree(member: dict) -> bool:
    return not _known_tree(member)


def _pick_tanks(pool: list, want: int) -> list:
    """Tanks by tree first; then a member whose tree is unknown and whose
    class can tank (a pure tank class first); then a warrior playing a damage
    tree, as a classic raid's off tank in a shield. Never a known healer."""
    tanks = _take(pool, want, None, _plays(raidroles.TANK))
    tanks += _take(pool, want - len(tanks), PURE_TANKS, _unknown_tree)
    tanks += _take(pool, want - len(tanks), TANKS, _unknown_tree)
    tanks += _take(pool, want - len(tanks), PURE_TANKS)
    return tanks


def _pick_healers(pool: list, want: int) -> list:
    """Healers by tree first; then a member whose tree is unknown and whose
    class can heal. A damage tree is never made to heal: that is a respec,
    and the shortfall says so instead."""
    healers = _take(pool, want, None, _plays(raidroles.HEALER))
    healers += _take(pool, want - len(healers), PURE_HEALERS, _unknown_tree)
    healers += _take(pool, want - len(healers), HEALERS, _unknown_tree)
    return healers


def _label(member: dict) -> str:
    duty = member["duty"]
    return "%s, %s" % (duty, member["spec"]) if member.get("spec") else duty


def _placed(member: dict, role: str, duty: str) -> dict:
    out = dict(member, role=role, duty=duty)
    out["label"] = _label(out)
    return out


def _healer_order(healers) -> list:
    """The healers placed, a priest first: group 1's shields the tanks."""
    rest = list(healers)
    first = next((h for h in rest if h.get("class_id") == PRIEST), None)
    if first is None and rest:
        first = rest[0]
    order = ([first] if first is not None else []) + [h for h in rest if h is not first]
    return [_placed(h, "healer", raidroles.HEALER) for h in order]


def _deal_healers(groups: list, healers: list, size: int) -> None:
    """One healer to each group in order while they last, then the rest into
    the last groups, the raid's healing group."""
    for group in groups:
        if healers and len(group) < size:
            group.append(healers.pop(0))
    for group in reversed(groups):
        while healers and len(group) < size:
            group.append(healers.pop(0))


def _damage_queue(spare_tanks, dps) -> list:
    """Spare tanks as off tanks, then melee, hunters and casters in turn."""
    ordered = sorted(
        dps, key=lambda m: _DPS_ORDER.get(m.get("raid_role"), len(_DPS_ORDER))
    )
    duty = lambda m: (  # noqa: E731
        m.get("raid_role") if m.get("raid_role") in _DPS_ORDER else DAMAGE_WORD
    )
    return [_placed(m, "tank", OFF_TANK) for m in spare_tanks] + [
        _placed(m, "dps", duty(m)) for m in ordered
    ]


def _deal_damage(groups: list, damage: list, size: int) -> None:
    """EVEN, THEN FULL. The groups after the tanks' are filled in order to an
    even share first, so a short roster makes seven thin groups rather than
    four full ones and three with only a healer, and a full one still fills
    group by group, each kind together. Whatever is left fills any room."""
    rest = groups[1:]
    if rest:
        share = (sum(len(g) for g in rest) + len(damage)) // len(rest)
        for cap in (share, share + 1):
            for group in rest:
                while damage and len(group) < min(cap, size):
                    group.append(damage.pop(0))
    for group in groups:
        while damage and len(group) < size:
            group.append(damage.pop(0))


def _groups(tanks, healers, dps, count: int, size: int) -> list:
    """Deal the raid into `count` groups of `size`.

    Group 1 is the tanks' group: the main tank and the off tanks (up to
    size - 1) with a healer, a priest first (Power Word: Shield on the tank).
    Every other group gets one healer while they last, and the healers left
    over fill the last groups, the raid's healing group. The damage dealers
    fill the free places in group order, melee first, then hunters, then
    casters, so each kind stands together, to an even share per group first.
    """
    groups = [[] for _ in range(count)]
    if not count:
        return groups
    for index, member in enumerate(tanks[: size - 1]):
        groups[0].append(_placed(member, "tank", MAIN_TANK if index == 0 else OFF_TANK))
    _deal_healers(groups, _healer_order(healers), size)
    _deal_damage(groups, _damage_queue(tanks[size - 1 :], dps), size)
    return groups


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

    Each placed raider carries `role` (tank, healer or dps, as before),
    `spec` (the talent tree, or ""), `raid_role` (raidroles' word), `duty`
    (main tank, off tank, healer, melee, ranged, caster or damage) and
    `label`, the duty and the tree as the page prints them.
    """
    guaranteed = frozenset(guaranteed)
    pool = sorted(
        (raidroles.with_spec(m) for m in members if m.get("name")),
        key=lambda m: _sort_key(m, guaranteed),
    )

    groups_wanted = raiders // group_size if group_size else 0
    tanks_wanted = max(MIN_TANKS, raiders * TANKS_PER_TEN // 10) if raiders else 0
    healers_wanted = (
        max(groups_wanted, raiders * HEALERS_PER_TEN // 10) if raiders else 0
    )

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

    tanks = _pick_tanks(pool, tanks_wanted)
    healers = _pick_healers(pool, healers_wanted)
    dps = _take(pool, max(0, raiders - len(tanks) - len(healers)))
    upkeep = _take(pool, maintenance)

    groups = [
        {"number": index + 1, "members": members_}
        for index, members_ in enumerate(
            _groups(tanks, healers, dps, groups_wanted, group_size)
        )
    ]

    placed = sum(len(group["members"]) for group in groups)
    composition: dict = {}
    for group in groups:
        for member in group["members"]:
            composition[member["duty"]] = composition.get(member["duty"], 0) + 1
    return {
        "groups": groups,
        "maintenance": [dict(m, role="maintenance") for m in upkeep],
        "summoners": [dict(m, role="summoner") for m in summoner_corps],
        "surplus": list(pool),
        "wanted": {
            "raiders": raiders,
            "maintenance": maintenance,
            "summoners": summoners,
            "total": raiders + maintenance + summoners,
            "tanks": tanks_wanted,
            "healers": healers_wanted,
        },
        "shortfall": {
            "raiders": max(0, raiders - placed),
            "maintenance": max(0, maintenance - len(upkeep)),
            "summoners": max(0, summoners - len(summoner_corps)),
            "tanks": max(0, tanks_wanted - len(tanks)),
            "healers": max(0, healers_wanted - len(healers)),
        },
        "counts": {
            "raiders": placed,
            "maintenance": len(upkeep),
            "summoners": len(summoner_corps),
            "surplus": len(pool),
            "considered": len(members),
        },
        "composition": composition,
        "roles_line": roles_line(groups, tanks_wanted, healers_wanted),
    }


def roles_line(groups: list, tanks_wanted: int, healers_wanted: int) -> str:
    """The raid's make-up in one sentence, as a raid leader would say it."""
    placed = [m for g in groups for m in g["members"]]
    if not placed:
        return "Nobody is placed, so there is no raid to describe."
    main = next((m for m in placed if m["duty"] == MAIN_TANK), None)
    tanks = [m for m in placed if m["role"] == "tank"]
    healers = [m for m in placed if m["role"] == "healer"]

    def count(duty):
        return len([m for m in placed if m["duty"] == duty])

    head = "%d of %d tanks%s, %d of %d healers" % (
        len(tanks),
        tanks_wanted,
        " (%s the main tank)" % main["name"] if main else "",
        len(healers),
        healers_wanted,
    )
    kinds = [
        "%d %s" % (count(duty), duty)
        for duty in (raidroles.MELEE, raidroles.RANGED, raidroles.CASTER, DAMAGE_WORD)
        if count(duty)
    ]
    unknown = len([m for m in placed if not m.get("spec")])
    tail = "; %d with no talent tree read, placed by class" % unknown if unknown else ""
    return (
        head
        + (", " + ", ".join(kinds) if kinds else "")
        + ". Roles come from each raider's talent tree; group 1 holds the tanks, "
        "each other group a healer while they last, and the damage dealers "
        "stand with their own kind" + tail + "."
    )


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
