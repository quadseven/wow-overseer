"""A family member sits out its campaign to craft, and a guildmate takes the seat.

WHY THIS EXISTS. The operator, 2026-10-05: when a family member is busy
tailoring, put a different damage dealer, tank or healer in. Grug's family
needs Og tailoring, learning recipes and clearing bag space now, while Zug's
family keeps running dungeons. A family's job is family-wide by design
(jobs.py), so before this the only choices were the whole family crafting or
the whole family in the dungeon.

THE ORDER. `FAMILY_STANDIN` names who sits out, as `head:member` pairs split
by commas: `FAMILY_STANDIN=Grug:Og` sits Og out of Grug's family's campaign.
Unset or empty, nothing sits out and no row is written. A pair naming the head
itself is ignored: the head leads the campaign and never sits out.

WHAT THIS DECIDES, one family at a time (`step`):

  who sits out   the ordered member, only while its crafting goal is live:
                 it holds a crafting trade (professions.CRAFTING) below the
                 profession cap (classic.MAX_PROFESSION_SKILL). Never the head
                 or the roster leader.
  who stands in  a free member of the family's guild and side
                 (guildrun.why_not, with the family's names excluded and a
                 member already in a guild run or standing in for another
                 family counted busy), who can take the sitting-out member's
                 seat (guildsocial.can_take; the seat is the one its spent
                 talents play: tank, healer, else dps), who fits the
                 campaign's current door alongside the family
                 (fits_door, the door's own band) and is within guildrun.BAND_SPREAD
                 of the family's average level. Best fit first: a member
                 whose talents play the seat, then the level nearest the
                 sitting-out member's, then the name.
  no guest       the operator's decision, 2026-10-05: when no guildmate can
                 take the seat, the member still sits out and the family runs
                 short-handed (four of five) rather than taking the crafter
                 along. The row is written with `in_name` empty
                 (`Seat.has_guest`), and a guest found between runs later
                 takes the empty seat.
  when it ends   the order is removed, the crafting goal is met, or, between
                 runs, the guest is no longer free (offline, in a guild run,
                 dead, inside another instance, gone from the guild or out of
                 the door's band). Grouped or in a fight is not a reason: the
                 guest is grouped with the family. A row with no guest ends
                 only with the order or the goal.

Never mid-run: while the family is inside a dungeon the row stands as it is.

THE CONTRACT with the worldserver module is the table `overseer_family_standin`
(`TABLE_SQL`), one row per family. The bridge writes and deletes rows; the
module reads them and, at the family's next idle point, runs the campaign with
`in_name` in `out_name`'s seat, leaves `out_name` to its own job, and releases
the guest when the row is deleted. An empty `in_name` means "sit out with no
guest": the module runs the family without `out_name`, and a party under five
goes in by the walk-in path, as the dungeon finder takes only a full five.

PURE: facts in, a Step out. The bridge reads, writes and logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import classic
import guildrun
import guildsocial
import professions

ENV = "FAMILY_STANDIN"
SOURCE = "overseer:standin"
CAP = classic.MAX_PROFESSION_SKILL
TANK, HEALER, DPS = guildrun.TANK, guildrun.HEALER, guildrun.DPS
# The column widths the contract gives.
NAME_WIDTH = 12
REASON_WIDTH = 160

# A guest the family's own party holds is grouped and, now and then, in a
# fight; neither ends its seat.
KEEPS_SEAT = frozenset({"", "already in a group", "in combat"})

TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_family_standin ("
    " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " family VARCHAR(12) NOT NULL,"
    " out_name VARCHAR(12) NOT NULL,"
    " in_name VARCHAR(12) NOT NULL,"
    " seat ENUM('tank','healer','dps') NOT NULL,"
    " reason VARCHAR(160) NOT NULL DEFAULT '',"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " PRIMARY KEY (id), UNIQUE KEY uq_family (family)"
    # NAMED, and the roster's: the module joins `family` and the names to
    # overseer_roster, which is utf8mb4_unicode_ci, as its own tables are.
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
)
ROWS_SQL = "SELECT family, out_name, in_name, seat, reason FROM overseer_family_standin"
INSERT_SQL = (
    "INSERT INTO overseer_family_standin (family, out_name, in_name, seat, reason) "
    "VALUES (%s, %s, %s, %s, %s)"
)
DELETE_SQL = "DELETE FROM overseer_family_standin WHERE family = %s"

# Actions a Step carries.
NONE, KEEP, SEAT, CLEAR = "none", "keep", "seat", "clear"


def orders(environ=None) -> dict:
    """family head -> the member who sits out, from FAMILY_STANDIN.

    A malformed pair, or one naming the head itself, is left out.
    """
    env = os.environ if environ is None else environ
    out = {}
    for part in str(env.get(ENV, "") or "").split(","):
        head, sep, member = part.partition(":")
        head, member = head.strip(), member.strip()
        if not sep or not head or not member or head == member:
            continue
        out[head] = member
    return out


def craft_trade(skills: dict) -> str:
    """The crafting trade the member has climbed furthest, or "" when it
    holds none. A tie goes to the name, so the answer is stable."""
    held = [
        (int(v or 0), t) for t, v in (skills or {}).items() if t in professions.CRAFTING
    ]
    if not held:
        return ""
    held.sort(key=lambda vt: (-vt[0], vt[1]))
    return held[0][1]


def goal(skills: dict, cap: int = CAP) -> str:
    """Why the member's crafting goal is live ("tailoring 120/300"), or ""
    when it is met or there is none."""
    trade = craft_trade(skills)
    if not trade:
        return ""
    value = int(skills[trade] or 0)
    if value >= cap:
        return ""
    return "%s %d/%d" % (trade, value, cap)


def seat_of(member: guildrun.Member) -> str:
    """The seat the member's spent talents play: tank, healer, else dps."""
    if member.plays(TANK):
        return TANK
    if member.plays(HEALER):
        return HEALER
    return DPS


def _average(levels) -> float:
    levels = [int(x) for x in levels]
    return sum(levels) / len(levels) if levels else 0.0


def fits_door(family_levels, guest_level: int, door) -> bool:
    """The guest fits the family's campaign door.

    THE CAMPAIGN'S BAND, NOT THE GUILD'S DOOR LIST. A family campaign is not
    a guild run: its door is a wing keyword such as `scarlet-library`, which
    the guild-run list (guildrun.GUILD_DOORS, `scarlet`) does not name, and a
    wing is outgrown only when the family's weakest member outgrows it, so
    Grug's family runs the Library (ceiling 38) with Grug at 41 (2026-10-05).
    The guest is held to that: at or over the finder's minimum, no higher than
    the door's ceiling or the family's own top level, and the party's average
    at least the door's floor.
    """
    family = [int(x) for x in family_levels]
    guest = int(guest_level)
    if guest < int(door.finder_floor):
        return False
    if guest > max([int(door.ceiling)] + family):
        return False
    party = family + [guest]
    return sum(party) / len(party) >= int(door.floor) + guildrun.LEVEL_MARGIN


def unfit(
    member: guildrun.Member, seat: str, family_levels, door, faction: str, guild: str
) -> str:
    """Why this member cannot take the seat for this family, or "".

    Freedom (guildrun.why_not) is the caller's: a new guest must be wholly
    free, a seated one may be grouped with the family.
    """
    if guild and member.guild != guild:
        return "not in %s" % guild
    if faction and guildrun.faction_of([member]) != faction:
        return "the other side"
    if not guildsocial.can_take(member, seat):
        return "does not play the %s seat" % seat
    if door is None:
        return "no dungeon door to fit"
    levels = [int(x) for x in family_levels]
    if not fits_door(levels, member.level, door):
        return "the family does not fit %s with it" % door.keyword
    if levels and abs(member.level - _average(levels)) > guildrun.BAND_SPREAD:
        return "more than %d levels from the family" % guildrun.BAND_SPREAD
    return ""


def guests(
    candidates,
    seat: str,
    out_level: int,
    family_levels,
    door,
    faction: str,
    guild: str,
    free,
) -> list:
    """The members who may stand in, best fit first.

    `free(member)` is guildrun.why_not's answer for a new guest. Best fit: a
    member whose talents play the seat (for dps, any damage tree), then the
    level nearest the sitting-out member's, then the name.
    """
    fit = [
        m
        for m in candidates
        if not free(m) and not unfit(m, seat, family_levels, door, faction, guild)
    ]
    fit.sort(
        key=lambda m: (m.fit(seat) != "spec", abs(m.level - int(out_level)), m.name)
    )
    return fit


@dataclass(frozen=True)
class Seat:
    """One overseer_family_standin row."""

    family: str
    out_name: str
    in_name: str
    seat: str
    reason: str

    def args(self) -> tuple:
        return (
            self.family[:NAME_WIDTH],
            self.out_name[:NAME_WIDTH],
            self.in_name[:NAME_WIDTH],
            self.seat,
            self.reason[:REASON_WIDTH],
        )

    @property
    def has_guest(self) -> bool:
        """False for a row that sits the member out with nobody in its seat."""
        return bool(self.in_name)

    @property
    def guest_word(self) -> str:
        """The guest's name, or "nobody" for a row with no guest."""
        return self.in_name or "nobody"


def seat_from_row(row: dict) -> Seat:
    return Seat(
        family=str(row.get("family") or ""),
        out_name=str(row.get("out_name") or ""),
        in_name=str(row.get("in_name") or ""),
        seat=str(row.get("seat") or DPS),
        reason=str(row.get("reason") or ""),
    )


@dataclass(frozen=True)
class Step:
    """What to do with one family's row: NONE (no row, none written), KEEP,
    SEAT (write `seat`, deleting any row first) or CLEAR (delete it)."""

    action: str
    why: str
    seat: Seat | None = None


@dataclass(frozen=True)
class Facts:
    """One family's facts, as the bridge read them."""

    family: str
    leader: str = ""
    # The member FAMILY_STANDIN names, or "" when no order names this family.
    ordered: str = ""
    # The enabled roster names of the family, the ordered member included.
    roster: tuple = ()
    # The ordered member's trade skills, {trade: value}.
    skills: dict | None = None
    # The ordered member as a guildrun.Member (None when it could not be read).
    out_member: guildrun.Member | None = None
    # The levels of the members who run (the family without the ordered one).
    family_levels: tuple = ()
    guild: str = ""
    faction: str = ""
    # The campaign's current door (a guildrun.Door), or None.
    door: object = None
    # The guild's members as guildrun.Member, and what why_not reads. `busy`
    # is every member in a guild run and every guest of another family; never
    # this family's own guest by its row alone.
    candidates: tuple = ()
    busy: frozenset = frozenset()
    resting: frozenset = frozenset()
    benched: frozenset = frozenset()
    # Every roster name of every family: guildrun.why_not's `family`.
    every_family: frozenset = frozenset()
    # Whether the family is inside a dungeon now.
    mid_run: bool = False
    # The family's current row, or None.
    current: Seat | None = None


def sits_out(facts: Facts) -> str:
    """Why the ordered member does not sit out now, or "" when it does."""
    name = facts.ordered
    if not name:
        return "no %s order names this family" % ENV
    if name in (facts.family, facts.leader):
        return "%s leads the family and never sits out" % name
    if name not in facts.roster:
        return "%s is not on the family's enabled roster" % name
    if not facts.skills or not craft_trade(facts.skills):
        return "%s holds no crafting trade" % name
    if not goal(facts.skills):
        return "%s's crafting goal is met (%s at %d)" % (
            name,
            craft_trade(facts.skills),
            CAP,
        )
    return ""


def step(facts: Facts) -> Step:
    """What to do with this family's stand-in row this pass."""
    current = facts.current
    why = sits_out(facts)
    if current is not None and current.out_name != facts.ordered and facts.ordered:
        why = why or "the order now names %s, not %s" % (
            facts.ordered,
            current.out_name,
        )
        return Step(CLEAR, why)
    if why:
        if current is None:
            return Step(NONE, why)
        if not facts.ordered:
            why = "the %s order is removed" % ENV
        return Step(CLEAR, why)
    if facts.out_member is None:
        if current is not None:
            return Step(
                KEEP,
                "%s could not be read; %s keeps the seat"
                % (facts.ordered, current.guest_word),
            )
        return Step(NONE, "%s could not be read, so no seat is known" % facts.ordered)
    seat = seat_of(facts.out_member)
    if current is not None:
        if not current.has_guest:
            return _fill_or_keep(facts, current, seat)
        return _keep_or_clear(facts, current, seat)
    if facts.door is None:
        return Step(
            NONE,
            "no dungeon is queued for %s's family, so nobody stands in" % facts.family,
        )
    found = _found(facts, seat, _free_for(facts))
    if not found:
        return _no_guest(facts, seat)
    return _seat_guest(facts, seat, found[0])


def _found(facts: Facts, seat: str, free) -> list:
    """The guests who may take `seat` now, best fit first."""
    return guests(
        facts.candidates,
        seat,
        facts.out_member.level,
        facts.family_levels,
        facts.door,
        facts.faction,
        facts.guild,
        free,
    )


def _free_for(facts: Facts):
    """guildrun.why_not's answer for a new guest of this family."""

    def free(member):
        return guildrun.why_not(
            member,
            set(facts.busy),
            set(facts.resting),
            set(facts.every_family),
            facts.benched,
        )

    return free


_HANDS = {1: "one", 2: "two", 3: "three", 4: "four"}


def short_handed_reason(facts: Facts) -> str:
    """The row's reason when nobody stands in: "no guest at scarlet-library;
    the family runs four-handed" for a family of five."""
    left = max(len(facts.roster) - 1, 0)
    return "no guest at %s; the family runs %s-handed" % (
        facts.door.keyword,
        _HANDS.get(left, str(left)),
    )


def _no_guest(facts: Facts, seat: str) -> Step:
    """No guildmate can take the seat: the member still sits out, and the
    family runs without it (operator decision, 2026-10-05)."""
    reason = short_handed_reason(facts)
    why = "no free %s member can take the %s seat at %s, so %s sits out: %s" % (
        facts.guild or "guild",
        seat,
        facts.door.keyword,
        facts.ordered,
        reason,
    )
    return Step(SEAT, why, Seat(facts.family, facts.ordered, "", seat, reason))


def _seat_guest(facts: Facts, seat: str, guest: guildrun.Member) -> Step:
    """Seat `guest` in the ordered member's place."""
    reason = "%s crafts (%s); %s takes the %s seat at %s" % (
        facts.ordered,
        goal(facts.skills),
        guest.name,
        seat,
        facts.door.keyword,
    )
    return Step(
        SEAT, reason, Seat(facts.family, facts.ordered, guest.name, seat, reason)
    )


def _fill_or_keep(facts: Facts, current: Seat, seat: str) -> Step:
    """A row with no guest stands while the member sits out. Between runs, a
    guildmate who can now take the seat is written into it; mid-run nothing
    changes, and with no door there is nothing to fit a guest to."""
    if facts.mid_run:
        return Step(
            KEEP, "the family is inside; %s sits out with no guest" % current.out_name
        )
    if facts.door is not None:
        found = _found(facts, current.seat or seat, _free_for(facts))
        if found:
            return _seat_guest(facts, current.seat or seat, found[0])
        return Step(KEEP, short_handed_reason(facts))
    return Step(KEEP, "%s sits out with no guest" % current.out_name)


def _keep_or_clear(facts: Facts, current: Seat, seat: str) -> Step:
    """The seated guest stays unless, between runs, it is no longer free."""
    if facts.mid_run:
        return Step(KEEP, "the family is inside; %s keeps the seat" % current.in_name)
    guest = next((m for m in facts.candidates if m.name == current.in_name), None)
    if guest is None:
        return Step(
            CLEAR,
            "%s is no longer in the world with %s"
            % (current.in_name, facts.guild or "the guild"),
        )
    why = guildrun.why_not(
        guest,
        set(facts.busy),
        set(facts.resting),
        set(facts.every_family),
        facts.benched,
    )
    if why not in KEEPS_SEAT:
        return Step(CLEAR, "%s is no longer free: %s" % (current.in_name, why))
    if facts.door is not None:
        why = unfit(
            guest,
            current.seat or seat,
            facts.family_levels,
            facts.door,
            facts.faction,
            facts.guild,
        )
        if why:
            return Step(CLEAR, "%s no longer fits: %s" % (current.in_name, why))
    return Step(KEEP, "%s keeps the %s seat" % (current.in_name, current.seat))
