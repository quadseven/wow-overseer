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


def _take(pool: list, want: int, allowed: frozenset | None = None) -> list:
    """Pull up to `want` members whose class is in `allowed`, in pool order."""
    taken = []
    for member in list(pool):
        if len(taken) >= want:
            break
        if allowed is not None and member.get("class_id") not in allowed:
            continue
        taken.append(member)
        pool.remove(member)
    return taken


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

    `members` is a list of dicts with `name`, `level` and `class_id`. Anyone
    the lineup cannot place comes back under `surplus` - that is the kick
    list, and it is a list rather than a count so a page can name every
    character before a person acts on it.
    """
    guaranteed = frozenset(guaranteed)
    pool = sorted(
        (dict(m) for m in members if m.get("name")),
        key=lambda m: _sort_key(m, guaranteed),
    )

    groups_wanted = raiders // group_size if group_size else 0

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

    tanks = _take(pool, groups_wanted, PURE_TANKS)
    if len(tanks) < groups_wanted:
        tanks += _take(pool, groups_wanted - len(tanks), TANKS)
    healers = _take(pool, groups_wanted, PURE_HEALERS)
    if len(healers) < groups_wanted:
        healers += _take(pool, groups_wanted - len(healers), HEALERS)

    dps = _take(pool, max(0, raiders - len(tanks) - len(healers)))
    upkeep = _take(pool, maintenance)

    groups = []
    for index in range(groups_wanted):
        slots = []
        if index < len(tanks):
            slots.append(dict(tanks[index], role="tank"))
        if index < len(healers):
            slots.append(dict(healers[index], role="healer"))
        groups.append({"number": index + 1, "members": slots})
    # Deal the DPS round-robin rather than filling group one to capacity, so a
    # short roster produces eight thin groups instead of five full ones and
    # three empty. A thin group is a recruiting number; an empty one reads as
    # a bug.
    for position, member in enumerate(dps):
        if groups:
            groups[position % len(groups)]["members"].append(dict(member, role="dps"))

    placed = sum(len(group["members"]) for group in groups)
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
        },
        "shortfall": {
            "raiders": max(0, raiders - placed),
            "maintenance": max(0, maintenance - len(upkeep)),
            "summoners": max(0, summoners - len(summoner_corps)),
            "tanks": max(0, groups_wanted - len(tanks)),
            "healers": max(0, groups_wanted - len(healers)),
        },
        "counts": {
            "raiders": placed,
            "maintenance": len(upkeep),
            "summoners": len(summoner_corps),
            "surplus": len(pool),
            "considered": len(members),
        },
    }


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
