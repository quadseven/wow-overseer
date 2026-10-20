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
  a craft that   the ordered member does not sit out while its craft cannot
  cannot move    move (`walled`): its ladder (craft.recipe_for) names a
                 trainer recipe it does not hold (a rung granted with the
                 trade, craft.AUTO_LEARNED, is never one), or no rung at all.
                 Sitting
                 out would make nothing: on wow-dev, 2026-10-06 to 2026-10-10,
                 Og sat out four and a half days at Tailoring 81 without Bolt
                 of Woolen Cloth (2964) while his family ran four-handed. With
                 his family, its training stop walks him to his trainer to buy
                 the recipe (guildjobs.recipes_due writes that learn errand,
                 #769), and he sits out again the pass the recipe is held.
  when it ends   the order is removed, the crafting goal is met, a release
                 below, or the crafting turn is over (`turn_over`).
  a guest lost   between runs, a guest that is no longer free (offline, in a
                 guild run, dead, inside another instance, gone from the guild
                 or out of the door's band) gives the seat back and the row
                 stays with no guest (`_guest_lost`): the member keeps sitting
                 out and the family runs short-handed until another guildmate
                 can take the seat. Grouped or in a fight is not a reason: the
                 guest is grouped with the family. Ending the row there sent
                 the member back to its family for one pass and out again on
                 the next: on wow-dev, 2026-10-18 to 2026-10-20, Og "rejoined"
                 Grug's family 19 times and 16 of those lasted one minute.
  a release      the member's craft cannot move (`walled`) or it has too
                 little to craft with (`starved`, wow-overseer#47): it rejoins
                 its family, between runs only (`waits_for_the_run`).
  turns          sitting out is bounded and alternates with the family's runs
                 (`Turn`): a crafting turn lasts CRAFT_TURN_SECONDS, then the
                 member rejoins its family (between runs only) for a family
                 turn of FAMILY_TURN_SECONDS, in which it is not sat out again,
                 whatever ends the row. Before this, the only end was the
                 crafting goal (tailoring 300), so on wow-dev Og sat out Grug's
                 family's runs from 2026-10-05 on: 32 of the 34 hours the log
                 archive holds (2026-10-18 to 2026-10-20) on job='craft', for
                 tailoring 125 to 128. The operator, 2026-10-20: a member
                 should go between dungeons and crafting.

Never mid-run: while the family is inside a dungeon the row stands as it is,
save for the order removed or changed, or the goal met.

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
import craft
import craft_rhythm
import goals
import guildjobs
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

# THE TURNS. A crafting turn is about one dungeon run long, so the member
# sits out about one run and runs the next; the family turn is as long, so it
# is a real run with the family and not a pass. Both are wall time, kept by
# the bridge across restarts (its memo store), because a turn that a restart
# began again is the unbounded sit-out this replaces.
CRAFT, FAMILY = "craft", "family"
CRAFT_TURN_SECONDS = 60 * 60
FAMILY_TURN_SECONDS = 60 * 60


@dataclass(frozen=True)
class Turn:
    """Whose turn it is in one family: `out_name` crafting (CRAFT) or back
    with its family (FAMILY), since `since` (Unix seconds)."""

    out_name: str
    phase: str
    since: float


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


def walled(skills: dict, known) -> str:
    """Why the member's craft cannot move ("tailoring 81 needs Bolt of Woolen
    Cloth (2964), a trainer recipe it does not hold"), or "" when it can.

    The rung is the one craft.recipe_for names at the trade's value, the same
    rung the craft errand casts. It can move when the rung is granted with the
    trade (guildjobs.AUTO_LEARNED, never written to character_spell) or held;
    every other rung is a trainer purchase, which persists to character_spell,
    so its absence there is real (guildjobs._open_recipe reads it the same
    way). `known` None means the spellbook was not read: not judged.
    """
    if known is None:
        return ""
    trade = craft_trade(skills)
    if not trade:
        return ""
    value = int(skills[trade] or 0)
    recipe = craft.recipe_for(goals.SKILL_IDS[trade], value)
    if recipe is None:
        return "%s %d has no rung on its ladder to cast" % (trade, value)
    if recipe.spell_id in guildjobs.AUTO_LEARNED or recipe.spell_id in known:
        return ""
    return "%s %d needs %s (%d), a trainer recipe it does not hold" % (
        trade,
        value,
        recipe.name,
        recipe.spell_id,
    )


def starved(reagents, sitting: bool) -> str:
    """Why the member has too little to craft with to sit out ("Og holds 0
    Wool Cloth against 3 per cast of spell 2964, ..."), or "" when it has
    enough or is not judged (wow-overseer#47).

    `reagents` is craft_rhythm.stand's verdict on its standing craft errand.
    None (not read) and UNJUDGED (no gathered reagent to count) are not
    judged. A new sit-out needs craft_rhythm's own bar, at least SHORT_CASTS
    casts in hand; one already sitting out keeps its seat until it has no
    cast left, so a member a cast or two short of the bar is not regrouped
    with its family on every pass.
    """
    if reagents is None or reagents.verdict == craft_rhythm.UNJUDGED:
        return ""
    if sitting:
        return reagents.why if int(reagents.casts) <= 0 else ""
    return reagents.why if reagents.verdict == craft_rhythm.SHORT else ""


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
    # The spells the ordered member holds (character_spell), or None when the
    # spellbook was not read, which `walled` does not judge.
    known: frozenset | None = None
    # Where the ordered member stands on the gathered reagents of its standing
    # craft errand (a craft_rhythm.Stand), or None when it was not read, which
    # `starved` does not judge.
    reagents: craft_rhythm.Stand | None = None
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
    # The members that owe a class quest (classquest.owed): a class quest comes
    # before any dungeon, so none is seated as a guest, and a seated one that
    # comes to owe one is released between runs.
    owed: frozenset = frozenset()
    # Every roster name of every family: guildrun.why_not's `family`.
    every_family: frozenset = frozenset()
    # Whether the family is inside a dungeon now.
    mid_run: bool = False
    # The family's current row, or None.
    current: Seat | None = None
    # The family's turn as the bridge last recorded it, or None, and the clock
    # it is read against (Unix seconds). With no clock turns are not judged.
    turn: Turn | None = None
    now: float | None = None


def _minutes(seconds: float) -> str:
    return "%d minute(s)" % max(0, int(seconds // 60))


def _turn(facts: Facts) -> Turn | None:
    """The recorded turn when it is the ordered member's and a clock is given."""
    turn = facts.turn
    if facts.now is None or turn is None or turn.out_name != facts.ordered:
        return None
    return turn


def turn_over(facts: Facts) -> str:
    """Why the ordered member's crafting turn is over, or "" while it lasts."""
    turn = _turn(facts)
    if turn is None or turn.phase != CRAFT:
        return ""
    spent = facts.now - turn.since
    if spent < CRAFT_TURN_SECONDS:
        return ""
    return (
        "%s has sat out to craft for %s, so it runs with its family for the "
        "next %s before it crafts again"
        % (facts.ordered, _minutes(spent), _minutes(FAMILY_TURN_SECONDS))
    )


def family_turn(facts: Facts) -> str:
    """Why the ordered member stays with its family now (its family turn has
    not run out), or ""."""
    turn = _turn(facts)
    if turn is None or turn.phase != FAMILY:
        return ""
    left = FAMILY_TURN_SECONDS - (facts.now - turn.since)
    if left <= 0:
        return ""
    return "%s runs with its family for %s more before its next crafting turn" % (
        facts.ordered,
        _minutes(left + 59),
    )


def next_turn(facts: Facts, step: "Step") -> Turn | None:
    """The turn to record after `step`, or None to leave the record as it is.

    A sit-out that begins (SEAT with no row before it) begins a crafting turn;
    a new guest in a standing row keeps the turn it has. A row that ends
    (CLEAR) begins the member's family turn, whatever ended it. A standing row
    with no turn recorded (one written before turns) starts its turn now.
    """
    if facts.now is None:
        return None
    turn = _turn(facts)
    current = facts.current
    if step.action == SEAT and step.seat is not None:
        if current is not None and turn is not None and turn.phase == CRAFT:
            return None
        return Turn(step.seat.out_name, CRAFT, facts.now)
    if step.action == CLEAR and current is not None:
        if facts.turn is not None and facts.turn.out_name == current.out_name:
            if facts.turn.phase == FAMILY:
                return None
        return Turn(current.out_name, FAMILY, facts.now)
    if (
        step.action == KEEP
        and current is not None
        and current.out_name == facts.ordered
        and turn is None
    ):
        return Turn(facts.ordered, CRAFT, facts.now)
    return None


def sits_out(facts: Facts) -> str:
    """Why the ordered member does not sit out now, or "" when it does."""
    return _held_in(facts) or released(facts)


def _held_in(facts: Facts) -> str:
    """Why the ordered member cannot sit out at all (no order, the head, off
    the roster, no crafting goal, an unread spellbook with no row), or ""."""
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
    if facts.known is None and facts.current is None:
        return (
            "%s's spellbook was not read this pass, so no new sit-out row is written"
            % name
        )
    return ""


def released(facts: Facts) -> str:
    """Why sitting out makes nothing now, so the member rejoins its family:
    its craft cannot move (`walled`) or it has too little to craft with
    (`starved`). "" when neither. Unlike the order or the goal, either can
    turn while the family is inside, as the member crafts on alone, so
    `step` holds the row until the run ends (`waits_for_the_run`)."""
    name = facts.ordered
    wall = walled(facts.skills, facts.known)
    if wall:
        return (
            "%s's craft cannot move (%s), so it rejoins its family, whose "
            "training stop walks it to its trainer to buy it (#769)" % (name, wall)
        )
    sitting = facts.current is not None and facts.current.out_name == name
    hunger = starved(facts.reagents, sitting)
    if hunger:
        return (
            "%s has too little to craft with (%s), so it rejoins its family, "
            "whose roaming and runs gather it" % (name, hunger)
        )
    return ""


def step(facts: Facts) -> Step:
    """What to do with this family's stand-in row this pass."""
    current = facts.current
    held = _held_in(facts)
    # A turn that is over ends the row like a release: between runs only.
    why = held or released(facts) or turn_over(facts) or family_turn(facts)
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
        elif not held and facts.mid_run:
            return waits_for_the_run(current, why)
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


def waits_for_the_run(current: Seat, why: str) -> Step:
    """A release (`released`) that comes while the family is inside a dungeon
    keeps the row as it is: deleting it would pull a guest out of the run, and
    the member rejoins its family's next idle pass instead (Never mid-run)."""
    return Step(
        KEEP,
        "the family is inside; %s keeps the seat until the run ends, then %s "
        "rejoins: %s" % (current.guest_word, current.out_name, why),
    )


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
            facts.owed,
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


def _guest_lost(facts: Facts, current: Seat, why: str) -> Step:
    """The guest gives the seat back and the member keeps sitting out with no
    guest (the operator's no-guest rule, 2026-10-05); `_fill_or_keep` seats
    another guildmate between runs once one can take it. The row is not
    cleared: that sent the member back to its family for one pass and out
    again on the next, writing two job orders for nothing."""
    reason = (
        short_handed_reason(facts)
        if facts.door is not None
        else "%s sits out with no guest" % current.out_name
    )
    return Step(
        SEAT,
        "%s, so %s sits out with no guest until another guildmate can take the "
        "%s seat" % (why, current.out_name, current.seat),
        Seat(current.family, current.out_name, "", current.seat, reason),
    )


def _keep_or_clear(facts: Facts, current: Seat, seat: str) -> Step:
    """The seated guest stays unless, between runs, it is no longer free; then
    the seat is emptied (`_guest_lost`)."""
    if facts.mid_run:
        return Step(KEEP, "the family is inside; %s keeps the seat" % current.in_name)
    guest = next((m for m in facts.candidates if m.name == current.in_name), None)
    if guest is None:
        return _guest_lost(
            facts,
            current,
            "%s is no longer in the world with %s"
            % (current.in_name, facts.guild or "the guild"),
        )
    why = guildrun.why_not(
        guest,
        set(facts.busy),
        set(facts.resting),
        set(facts.every_family),
        facts.benched,
        facts.owed,
    )
    if why not in KEEPS_SEAT:
        return _guest_lost(
            facts, current, "%s is no longer free: %s" % (current.in_name, why)
        )
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
            return _guest_lost(
                facts, current, "%s no longer fits: %s" % (current.in_name, why)
            )
    return Step(KEEP, "%s keeps the %s seat" % (current.in_name, current.seat))
