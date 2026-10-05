"""A guild short of tanks or healers grows them: a member respecs at its trainer (#580).

WHY THIS EXISTS. #575 found Cave had no healer specced for healing above level
15 and no tank specced for tanking above 16. Since #579 a tank or healer seat
goes only to a member whose spent talents play it (guildrun.Member.plays), so
Cave could not seat a group at all. Players in that guild would notice and one
of them would say "we're short on healers, I'll go Holy", walk to the class
trainer, pay for the reset and spend the points in the healing tree. This
module decides who does that.

THE COUNT. Per guild and per five-level band (guildrun.band_of), the members
that play a tank seat, a healer seat, or neither (a damage dealer). A band of n
members wants n // 5 of each: one tank and one healer for every five. The
family is left out of the count and is never asked; its trees are the
operator's (the roster's spec tab).

ALREADY ON THE WAY. The talents read from the database lag the game: a
character saves its talents some minutes after the trainer, so a respec that
just came back applied still reads as the old tree. A respec row from this
pass that came back applied (RESPEC_COUNTED_MINUTES) or is still waiting
(PENDING_MINUTES) counts as the seat it walked for, and so does a member with
no points outside the tree its raid plan target names (overseer_raid_spec):
mod-overseer spends its free points there at its next login or level.

WHO RESPECS. A member of a class that can take the seat (warrior, paladin or
druid to tank; priest, paladin, shaman or druid to heal), at RESPEC_LEVEL or
above (the core's own floor for a reset), that plays neither seat now, online,
out of combat, in the open world, naturally restarted (natural.py) and not on
another guild walk or run. It pays the trainer's fee from its own purse, so it
must carry the core's price (`reset_fee`, Player::resetTalentsCost); a member
with no talent points spent pays nothing and needs no trainer. The fewest
points spent first (the least to lose), then a member whose raid plan already
names that tree, then the class that can only take that seat (a paladin or a
druid could also be the other one), then the richer, then by name.

THE CAP. A respec never takes a band under DAMAGE_PER_GROUP damage dealers for
each group it can seat, so the guild keeps its damage. At most
RESPECS_PER_GUILD a pass, and a member whose respec failed waits
RETRY_MINUTES before it is asked again.

WHAT IT SAYS AND DOES. The member says why in guild chat ("Guild's short on
healers around my level, so I'll go Holy. Off to my trainer."), then walks to a
trainer of its own class with mod-overseer's `walk-to-trainer talents:<tab>`,
which buys the reset through the core's own handler (the price comes out of
its purse), spends the points in the tree with mod-playerbots' premade build
and resets its strategies so it plays the new seat. Once that comes back
applied, its overseer_raid_spec row names the tree (duty GUILD_DUTY), so every
point it earns later goes there too.

PURE: rows in, choices out. The bridge reads, says the line, writes the walk
row and the raid spec row.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import guildroute
import guildrun
import raidroles

ENV_SWITCH = "GUILD_RESPEC"

TANK, HEALER = raidroles.SEAT_TANK, raidroles.SEAT_HEALER
SEATS = (HEALER, TANK)

# The classes that can take each seat, and the tree they take it in. No death
# knight: recruits start at level 1 under the natural rules, and a death
# knight starts at 55.
TANK_TREE = {c: t for c, t in raidroles.TANK_TREE.items() if c != 6}
HEALER_TREE = dict(raidroles.HEALER_TREE)
TREE_FOR = {TANK: TANK_TREE, HEALER: HEALER_TREE}

# The level the core first resets talents at (Player::resetTalents needs a
# talent point to exist; mod-overseer's JudgeRespec refuses below it).
RESPEC_LEVEL = 10
GROUP_SIZE = 5
DAMAGE_PER_GROUP = 3
RESPECS_PER_GUILD = 1
# A respec row still waiting counts as its seat this long; an applied one for
# as long as the recent rows reach (a day).
PENDING_MINUTES = 120
RETRY_MINUTES = 360
FAILED = frozenset({"error", "unchanged"})
APPLIED = frozenset({"applied", "delivered"})

# Player::resetTalentsCost, in copper.
GOLD = 10000
MONTH_SECONDS = 30 * 24 * 3600

ACTION = "respec"
SOURCE = "guildjobs"
GUILD_DUTY = raidroles.GUILD_DUTY

# How a member says the tree it is going.
SPOKEN = {"Feral Combat": "bear", "Protection": "Prot", "Restoration": "Resto"}


def enabled(environ=None) -> bool:
    """On unless GUILD_RESPEC says off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


def source_for(name) -> str:
    """The command log's source for a respec row: guildjobs' own shape, so the
    job pass's recent rows carry it."""
    return "%s:%s:%s" % (SOURCE, ACTION, name)


def say_source_for(name) -> str:
    """The source of the guild chat line it says first; not a respec row."""
    return "%s:%s-say:%s" % (SOURCE, ACTION, name)


def reset_fee(cost, reset_time, now) -> int:
    """What the trainer charges, in copper: Player::resetTalentsCost over the
    character's resettalents_cost and resettalents_time columns."""
    cost = int(cost or 0)
    if cost < 1 * GOLD:
        return 1 * GOLD
    if cost < 5 * GOLD:
        return 5 * GOLD
    if cost < 10 * GOLD:
        return 10 * GOLD
    months = max(0, int(now) - int(reset_time or 0)) // MONTH_SECONDS
    if months > 0:
        return max(10 * GOLD, cost - 5 * GOLD * months)
    return min(50 * GOLD, cost + 5 * GOLD)


@dataclass(frozen=True)
class Mate:
    """One guild member as this pass sees it."""

    name: str
    guild: str
    level: int
    class_id: int
    # Talent points spent, by tree name.
    points: tuple = ()  # ((tree, points), ...)
    money: int = 0
    fee: int = GOLD
    # The raid plan's tree for it (overseer_raid_spec), "" when none.
    target_tree: str = ""
    # Online, out of combat, in the open world, natural, not on another walk.
    free: bool = False
    family: bool = False

    @property
    def spent(self) -> int:
        return sum(int(p) for _t, p in self.points)

    @property
    def tree(self) -> str:
        """The tree with the most points, "" when none or a tie (raidroles.tree_of)."""
        return raidroles.top_tree(dict(self.points))

    def outside(self, tree: str) -> int:
        return sum(int(p) for t, p in self.points if t != tree)

    def plays(self, seat: str) -> bool:
        """guildrun.Member.plays: its spent talents are a tree that plays the seat."""
        return guildrun.Member(
            name=self.name,
            guild=self.guild,
            level=self.level,
            class_id=self.class_id,
            tree=self.tree,
        ).plays(seat)


@dataclass(frozen=True)
class Respec:
    """One member going to fill a seat."""

    name: str
    guild: str
    band: str
    seat: str
    tree: str
    tab: int
    class_id: int
    fee: int
    # False when it has no points to move: the raid spec row alone does it.
    reset: bool
    said: str
    line: str

    def command(self, cap=guildroute.MAIL_RUN_YARDS) -> str:
        return "walk-to-trainer talents:%d%s" % (
            self.tab,
            guildroute.errand_cap_word(cap),
        )


@dataclass(frozen=True)
class Plan:
    choices: tuple = ()
    notes: tuple = ()
    # (guild, band) -> {"tank": n, "healer": n, "damage": n, "members": n}
    counts: dict = field(default_factory=dict)


def seat_of(class_id, tab) -> str:
    """The seat a respec to this tab walked for, "" when none."""
    for seat in SEATS:
        tree = TREE_FOR[seat].get(int(class_id or 0))
        if tree and raidroles.tree_tab(class_id, tree) == int(tab):
            return seat
    return ""


def _talent_tab(command) -> int | None:
    for token in str(command or "").split():
        if token.startswith("talents:") and token[len("talents:") :].isdecimal():
            return int(token[len("talents:") :])
    return None


def underway(rows, class_of) -> tuple:
    """({name: seat} counted as the seat they walked for, {names cooling after
    a failed respec}), from this pass's recent command rows (target_name,
    command, source, status, age in minutes)."""
    seats, cooling = {}, set()
    for row in sorted(rows or (), key=lambda r: -int(r.get("age") or 0)):
        name = str(row.get("target_name") or "")
        if str(row.get("source") or "") != source_for(name):
            continue
        tab = _talent_tab(row.get("command"))
        status = str(row.get("status") or "")
        age = int(row.get("age") if row.get("age") is not None else 10**6)
        if tab is None:
            continue
        if status in FAILED:
            seats.pop(name, None)
            if age < RETRY_MINUTES:
                cooling.add(name)
            continue
        seat = seat_of(class_of.get(name, 0), tab)
        if seat and (status in APPLIED or age < PENDING_MINUTES):
            seats[name] = seat
            cooling.discard(name)
    return seats, cooling


def _role(mate: Mate, underway_seats: dict) -> str:
    """tank, healer or damage, counting what is already on its way."""
    if mate.name in underway_seats:
        return underway_seats[mate.name]
    for seat in SEATS:
        if mate.plays(seat):
            return seat
    target = mate.target_tree
    if target and mate.outside(target) == 0:
        for seat in SEATS:
            if raidroles.fits_seat(mate.class_id, target, seat):
                return seat
    return "damage"


def count(mates, underway_seats=None) -> dict:
    """(guild, band) -> how many play each seat, the family left out."""
    underway_seats = underway_seats or {}
    out: dict = {}
    for m in mates or ():
        if m.family:
            continue
        key = (m.guild, guildrun.band_of([m.level]))
        c = out.setdefault(key, {TANK: 0, HEALER: 0, "damage": 0, "members": 0})
        c[_role(m, underway_seats)] += 1
        c["members"] += 1
    return out


def _band_low(band: str) -> int:
    try:
        return int(str(band).split("-")[0])
    except ValueError:
        return -1


def shortfall(c: dict) -> list:
    """[(seat, missing)] for one band's count, the larger gap first, healers on
    a tie; empty when the band seats no group or the damage would fall under
    DAMAGE_PER_GROUP a group."""
    groups = int(c.get("members", 0)) // GROUP_SIZE
    if groups < 1 or int(c.get("damage", 0)) - 1 < DAMAGE_PER_GROUP * groups:
        return []
    gaps = [(seat, groups - int(c.get(seat, 0))) for seat in SEATS]
    gaps = [(s, n) for s, n in gaps if n > 0]
    return sorted(gaps, key=lambda g: (-g[1], SEATS.index(g[0])))


def _only_seat(class_id, seat) -> int:
    """0 when the class can take only this seat of the two, 1 for a hybrid."""
    other = TANK if seat == HEALER else HEALER
    return 1 if int(class_id) in TREE_FOR[other] else 0


def candidates(mates, guild: str, band: str, seat: str, taken, underway_seats, cooling):
    """The members who could go `seat` in this band, best first."""
    out = []
    for m in mates:
        if m.family or m.guild != guild or guildrun.band_of([m.level]) != band:
            continue
        tree = TREE_FOR[seat].get(int(m.class_id))
        if not tree or m.level < RESPEC_LEVEL or not m.free:
            continue
        if m.name in taken or m.name in cooling or _role(m, underway_seats) != "damage":
            continue
        if m.spent and m.money < m.fee:
            continue
        out.append(m)
    return sorted(
        out,
        key=lambda m: (
            m.spent,
            0 if m.target_tree == TREE_FOR[seat][int(m.class_id)] else 1,
            _only_seat(m.class_id, seat),
            -int(m.money),
            m.name,
        ),
    )


def _gold(copper) -> str:
    copper = int(copper)
    if copper >= GOLD:
        return "%dg" % (copper // GOLD)
    return "%ds" % (copper // 100)


SAYINGS = {
    HEALER: (
        "Guild's short on healers around my level, so I'll go {tree}. Off to my trainer.",
        "Nobody heals in our bracket. I'll respec {tree}, heading to my trainer now.",
        "We keep going in without a healer. I'll go {tree}.",
    ),
    TANK: (
        "Guild's short on tanks around my level, so I'll go {tree}. Off to my trainer.",
        "Nobody tanks in our bracket. I'll respec {tree}, heading to my trainer now.",
        "We keep going in without a tank. I'll go {tree}.",
    ),
}
# Said by a member with no points to move: no trainer, the next points go there.
SAYINGS_FREE = {
    HEALER: "Guild's short on healers around my level. My talents go into {tree} from now on.",
    TANK: "Guild's short on tanks around my level. My talents go into {tree} from now on.",
}


def saying(name: str, seat: str, tree: str, reset: bool) -> str:
    spoken = SPOKEN.get(tree, tree)
    if not reset:
        return SAYINGS_FREE[seat].format(tree=spoken)
    lines = SAYINGS[seat]
    return lines[sum(ord(ch) for ch in name) % len(lines)].format(tree=spoken)


def plan(mates, recent_rows=(), per_guild: int = RESPECS_PER_GUILD) -> Plan:
    """Who goes tank or healer this pass, at most `per_guild` a guild."""
    mates = list(mates or ())
    class_of = {m.name: int(m.class_id) for m in mates}
    underway_seats, cooling = underway(recent_rows, class_of)
    counts = count(mates, underway_seats)
    choices, notes, taken = [], [], set()
    started: dict = {}
    # The highest band first: the doors there are the ones that keep failing.
    for guild, band in sorted(counts, key=lambda k: (k[0], -_band_low(k[1]))):
        if _band_low(band) < RESPEC_LEVEL:
            continue
        c = counts[(guild, band)]
        for seat, missing in shortfall(c):
            if started.get(guild, 0) >= per_guild:
                break
            found = candidates(mates, guild, band, seat, taken, underway_seats, cooling)
            if not found:
                notes.append(
                    "%s %s is %d %s(s) short and nobody free can go %s"
                    % (guild, band, missing, seat, seat)
                )
                continue
            m = found[0]
            tree = TREE_FOR[seat][int(m.class_id)]
            tab = raidroles.tree_tab(m.class_id, tree)
            if tab is None:
                continue
            reset = m.spent > 0
            choices.append(
                Respec(
                    name=m.name,
                    guild=guild,
                    band=band,
                    seat=seat,
                    tree=tree,
                    tab=int(tab),
                    class_id=int(m.class_id),
                    fee=int(m.fee) if reset else 0,
                    reset=reset,
                    said=saying(m.name, seat, tree, reset),
                    line="%s %s has %d tank(s), %d healer(s), %d damage of %d; %s goes %s "
                    "(%d point(s) to move%s)"
                    % (
                        guild,
                        band,
                        c[TANK],
                        c[HEALER],
                        c["damage"],
                        c["members"],
                        m.name,
                        tree,
                        m.spent,
                        ", %s fee from its %s" % (_gold(m.fee), _gold(m.money))
                        if reset
                        else "",
                    ),
                )
            )
            taken.add(m.name)
            c[seat] += 1
            c["damage"] -= 1
            started[guild] = started.get(guild, 0) + 1
            break
    return Plan(choices=tuple(choices), notes=tuple(notes), counts=counts)


def mates_from(job_members, rows, targets, family, busy, now) -> list:
    """Mates from the job pass's members (guildjobs.Member) and its member rows
    (talent_spells, resettalents_cost, resettalents_time), with `targets` name
    -> raid plan tree."""
    by_name = {str(r.get("name") or ""): r for r in rows or ()}
    family = {str(n) for n in family or ()}
    busy = {str(n) for n in busy or ()}
    out = []
    for m in job_members or ():
        row = by_name.get(m.name) or {}
        points = raidroles.points_by_tree(m.class_id, row.get(raidroles.KEY))
        free = (
            bool(m.eligible)
            and bool(m.online)
            and not m.in_combat
            and m.map_id is not None
            and int(m.map_id) in guildrun.OPEN_WORLD_MAPS
            and m.name not in busy
        )
        out.append(
            Mate(
                name=m.name,
                guild=m.guild,
                level=int(m.level),
                class_id=int(m.class_id),
                points=tuple(sorted(points.items())),
                money=int(m.money),
                fee=reset_fee(
                    row.get("resettalents_cost"), row.get("resettalents_time"), now
                ),
                target_tree=str((targets or {}).get(m.name) or ""),
                free=free,
                family=m.name in family,
            )
        )
    return out
