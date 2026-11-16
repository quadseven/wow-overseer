"""A feed for the low rungs of cloth, leather and stone (#2502).

WHY IT EXISTS. A crafter at the bottom of a ladder eats Rough Stone, Light
Leather, Linen and Wool Cloth, and the guild that should supply them did not.
The corps' farm jobs send a skinner to beasts from six levels under itself to
one over (`guildjobs.skin_band`), a cloth farmer to humanoids in the same band,
and a miner to the nearest field in its own level band (`gatheraim.choose`
prefers zones near the member's level). A level 60 member is therefore sent to
level 54 to 61 creatures and to thorium, where Rough Stone, Light Leather and
Linen Cloth do not drop. Read from the realm's world data: 238 of the 363
creatures with Light Leather in their skinning loot are level 20 or lower, and
Linen Cloth drops only from humanoids of level 6 to 31. The vault's forecast
(`bankforecast`) already says when the guild holds less of a material than it
will eat; nothing acted on it for these materials.

WHAT IT DECIDES. For each guild whose forecast names a starved low-rung
material, up to FEEDERS_PER_RUNG of its job members that have out-levelled the
rung and can work it are sent back to where it drops:

    SKIN    a skinner hunts skinnable beasts of the rung's level band
    CLOTH   a member with no gathering field of its own (the rule
            `guildjobs.farms_cloth` already uses) hunts the humanoids of the
            rung's band that carry the cloth
    NODE    a miner goes to the Copper Vein (Rough Stone) or the Tin Vein
            (Coarse Stone), the locks `gameobject_loot_template` lists

What the member loots reaches the crafters by the paths that already exist: the
keeper rule deposits a stack a family trade claims into the guild vault, and
the crafter takes it out at the next vault stop (`reagentplan`).

NORTH STAR. Nothing here grants, creates, lists or buys anything. The feed only
chooses which field a member's existing farm job walks to: gold and items come
from what the member kills, skins and mines. It never touches the auction
house.

WHERE IT LANDS. A feed is sent only when what it loots has somewhere to go: a
free stack in the guild vault (any purchased tab, so the second tab's overflow
counts), a guild banker's free stacks, or the crafters' own bags and banks. A
guild whose vault is full, with no banker room and crafters with full bags, is
sent nothing: farming would only fill a feeder's bags. `Room` is that count,
read by the bridge; an unread room feeds nobody.

PURE: members and counts in, feeds and sentences out. The bridge reads the
forecast, lays each feed on its member and walks it.
"""

from __future__ import annotations

from dataclasses import dataclass

import bank
import gatheraim
import gatherband
import guildjobs
import guildledger

SKIN, CLOTH, NODE = "skin", "cloth", "node"

# At most this many members of a guild chase one starved material, so a short
# stack never empties a guild's other jobs.
FEEDERS_PER_RUNG = 2


# Free stacks a guild needs across its vault, bankers and crafters before a feed
# is sent: one stack for the loot and one for the stack that follows it.
MIN_LANDING = 2


@dataclass(frozen=True)
class Room:
    """Free stacks where a feed's loot can land, by place."""

    vault: int = 0
    bankers: int = 0
    crafters: int = 0

    @property
    def total(self) -> int:
        return max(0, self.vault) + max(0, self.bankers) + max(0, self.crafters)

    @property
    def enough(self) -> bool:
        return self.total >= MIN_LANDING


def member_room(m) -> int:
    """Free stacks a bank.Member can take, the reserves a banker keeps off."""
    return max(0, m.bag_free - guildledger.BAG_RESERVE) + max(
        0, m.bank_free - bank.BANK_FREE_RESERVE
    )


def room_of(vault_free, bankers=(), crafters=()) -> Room:
    """The Room from the vault's free slots and the bankers' and crafters'
    bank.Member rows. A member with no level was not read and counts for none."""
    return Room(
        vault=int(vault_free or 0),
        bankers=sum(member_room(m) for m in bankers if m.level > 0),
        crafters=sum(member_room(m) for m in crafters if m.level > 0),
    )


@dataclass(frozen=True)
class Rung:
    """One low-rung material and where it drops.

    `band` is the creature level band that carries it (SKIN, CLOTH), read from
    the world's loot tables; `locks` are the node locks that carry it (NODE).
    """

    entry: int
    label: str
    kind: str
    band: tuple
    locks: tuple = ()


RUNGS = {
    r.entry: r
    for r in (
        Rung(2318, "Light Leather", SKIN, (2, 20)),
        Rung(2934, "Ruined Leather Scraps", SKIN, (2, 20)),
        Rung(2319, "Medium Leather", SKIN, (15, 35)),
        Rung(2589, "Linen Cloth", CLOTH, (6, 25)),
        Rung(2592, "Wool Cloth", CLOTH, (12, 32)),
        Rung(4306, "Silk Cloth", CLOTH, (25, 45)),
        Rung(4338, "Mageweave Cloth", CLOTH, (31, 50)),
        Rung(2835, "Rough Stone", NODE, (1, 20), (38,)),
        Rung(2836, "Coarse Stone", NODE, (1, 20), (39,)),
    )
}


@dataclass(frozen=True)
class Feed:
    """One member sent back to a rung's source."""

    name: str
    guild: str
    entry: int
    label: str
    kind: str
    band: tuple
    locks: tuple
    short: int
    crafters: tuple = ()


def outgrown(rung: Rung, level) -> bool:
    """Whether a member of `level`'s own field no longer reaches the rung."""
    level = int(level or 0)
    high = rung.band[1]
    if rung.kind == NODE:
        return level >= high + gatheraim.LEVEL_FLOOR_BELOW
    return level - guildjobs.SKIN_BELOW > high


def can_feed(rung: Rung, m) -> bool:
    """Whether job member `m` has out-levelled the rung and can work it."""
    if not outgrown(rung, m.level):
        return False
    if rung.kind == SKIN:
        return m.holds(guildjobs.SKINNING)
    if rung.kind == NODE:
        value = m.skill(guildjobs.MINING)[0]
        return m.holds(guildjobs.MINING) and all(
            gatherband.in_band(lock, "mining", value) for lock in rung.locks
        )
    # CLOTH: the member `guildjobs.farms_cloth` already sends to the humanoids.
    return not any(m.holds(s) for s in guildjobs.GATHERING) or m.holds(
        guildjobs.TAILORING
    )


def _ordered(short) -> list:
    return sorted(
        ((RUNGS[e], int(n)) for e, n in (short or {}).items() if e in RUNGS and n > 0),
        key=lambda pair: (-pair[1], pair[0].entry),
    )


def plan(members, starved, crafters=None, focus=None, room=None) -> dict:
    """name -> Feed for the members sent back to a starved rung.

    `starved` is guild -> {entry: units short guild-wide}
    (`bankforecast.Forecast.starved`); `crafters` is entry -> the crafters
    short of it. The biggest shortfall is fed first, a member takes one rung,
    and a guild sends at most FEEDERS_PER_RUNG members to each.

    `room` is guild -> Room. A guild with no room read, or without MIN_LANDING
    free stacks to land the loot in, sends nobody.
    """
    out: dict = {}
    for guild, short in sorted((starved or {}).items()):
        if not (room or {}).get(guild, Room()).enough:
            continue
        pool = sorted(
            (
                m
                for m in members
                if m.guild == guild and guildjobs.wants_field(m, focus)
            ),
            key=lambda m: m.name,
        )
        for rung, units in _ordered(short):
            sent = 0
            for m in pool:
                if sent >= FEEDERS_PER_RUNG:
                    break
                if m.name in out or not can_feed(rung, m):
                    continue
                out[m.name] = Feed(
                    m.name,
                    guild,
                    rung.entry,
                    rung.label,
                    rung.kind,
                    rung.band,
                    rung.locks,
                    units,
                    tuple((crafters or {}).get(rung.entry, ())),
                )
                sent += 1
    return out


def unfed(members, starved, crafters=None, focus=None, room=None) -> list:
    """One sentence per starved rung that no member can be sent to."""
    fed = {
        (f.guild, f.entry)
        for f in plan(members, starved, crafters, focus, room).values()
    }
    notes = []
    for guild, short in sorted((starved or {}).items()):
        for rung, units in _ordered(short):
            if (guild, rung.entry) in fed:
                continue
            here = (room or {}).get(guild, Room())
            if not here.enough:
                notes.append(
                    "%s is short %d %s%s but has %d free stack(s) to land it in "
                    "(vault %d, bankers %d, crafters %d; %d needed), so nothing "
                    "feeds it"
                    % (
                        guild,
                        units,
                        rung.label,
                        _who((crafters or {}).get(rung.entry, ())),
                        here.total,
                        here.vault,
                        here.bankers,
                        here.crafters,
                        MIN_LANDING,
                    )
                )
                continue
            notes.append(
                "%s is short %d %s%s and no member of %s has out-levelled the "
                "rung with the trade to farm it, so nothing feeds it"
                % (
                    guild,
                    units,
                    rung.label,
                    _who((crafters or {}).get(rung.entry, ())),
                    guild,
                )
            )
    return notes


def _who(crafters) -> str:
    return " (%s eat it)" % ", ".join(crafters) if crafters else ""


def line(feed: Feed) -> str:
    """One plain sentence: the crafters, the material and the source chosen."""
    if feed.kind == NODE:
        where = "mines the veins that drop it"
    elif feed.kind == SKIN:
        where = "skins beasts of levels %d to %d" % feed.band
    else:
        where = "hunts humanoids of levels %d to %d" % feed.band
    who = ", ".join(feed.crafters) or "the guild's crafters"
    return "%s %s short of %s (%d short guild-wide); %s %s for it" % (
        who,
        "is" if len(feed.crafters) <= 1 else "are",
        feed.label,
        feed.short,
        feed.name,
        where,
    )
