"""Who in the guild receives which recipe: the designated crafters (#248).

THE OPERATOR'S RULE. Rare recipes go first to the guild's chosen crafters:
the family members who hold the profession, then a couple of designated guild
members per profession. A recipe goes to the person who can learn it and
benefits most, and is learned promptly. Only a recipe nobody in the guild can
use is banked or sold.

MEASURED ON WOW-DEV 2026-09-23. Ugga, an Alliance priest with Alchemy 14,
carried eight recipes for trades she lacks or cannot learn yet. `clearance`
routed a recipe to the first guildmate BY NAME who could learn it now, with no
idea whether that guildmate already knew it: every Alliance alchemist at 285
or more has Purification Potion in `character_spell`. And a recipe mailed to a
guild bot stayed in its mailbox, because nothing takes a guild bot's letter out
or uses what is in it.

THE REGISTER, per guild and per trade:

    family       every family member who holds the trade, best skill first.
    designated   the N guild members outside the family with the best skill,
                 then the highest level, then the fewest seats already held in
                 this guild (so one maxed bot is not the crafter for all ten
                 trades), then the name. N is DESIGNATED_CRAFTERS_PER_TRADE,
                 default 2.

The register does not look at who is online, so it does not change from one
pass to the next as bots log in and out. Presence matters at delivery time.

THE ROUTE for one recipe. The first tier with a candidate wins:

    1. a family member who can learn it now
    2. a designated crafter who can learn it now
    3. a family member within RECIPE_SOON_GAP skill points of it
    4. a designated crafter within that gap
    5. any other guildmate who can learn it now

Learning now outranks family-soon because the rule asks for the recipe to be
learned promptly. Within a tier the candidate who benefits most wins: the
smallest distance between their skill and the recipe's rank, because a recipe
near the top of what a crafter can do still gives skill points and one far
below it is already grey. Ties go to whoever is online, then to register order,
then to the name. When the winner is the holder, the holder keeps it and the
recipe pass learns it.

"HAS NOT LEARNED IT" HAS TWO SOURCES, AND NEITHER ONE IS ENOUGH ON ITS OWN.
A `character_spell` row proves a character knows a recipe: the random bots'
maxed trades are all written there. A MISSING row does not prove the opposite,
because a recipe granted at runtime is never saved (recipebook's header). So
the `use` verb's own `already knows` answers are read back too, and a
character named by either source is skipped. A guess that is still wrong costs
nothing: the verb asks Player::HasSpell before anything is spent and refuses.

PURE MODULE: rows in, a register and routes out. No MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import classic
import guildroute
import mailrun
import recipebook

# The trades an item teaches into, by skill line id. Every class-9 item on the
# realm gates on one of these (item_template.RequiredSkill).
TRADES = {
    129: "first aid",
    164: "blacksmithing",
    165: "leatherworking",
    171: "alchemy",
    185: "cooking",
    197: "tailoring",
    202: "engineering",
    333: "enchanting",
    755: "jewelcrafting",
    773: "inscription",
}

PER_TRADE_ENV = "DESIGNATED_CRAFTERS_PER_TRADE"
DEFAULT_PER_TRADE = 2
MAX_PER_TRADE = 10
SOON_GAP_ENV = "RECIPE_SOON_GAP"
# One skill-colour band: a crafter this close reaches the rank within a few
# crafts of their own trade.
DEFAULT_SOON_GAP = 25
MAX_SOON_GAP = 75

# Seats, in the order the route prefers them.
HOLDER = "holder"
FAMILY = "family"
DESIGNATED = "designated"
GUILD = "guild"
NOW = "now"
SOON = "soon"

# The log prefix every line of this module's pass carries.
LOG_PREFIX = "crafter-route:"

# Walk and pickup bounds for the letters a designated crafter is sent.
# At most this many crafters are walked per pass, and at most this many
# recipes are taken out on one visit (one bag slot each).
WALKS_PER_PASS = 2
TAKES_PER_VISIT = 3
# `source` values for the rows the pickup writes. The learn row keeps
# recipebook's source so recipebook's read-back sees its answers.
WALK_SOURCE = "crafterwalk"
TAKE_SOURCE = "craftertake"


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _knob(environ, key, default, top) -> int:
    """A whole number from the environment, clamped to 0..top."""
    raw = str((environ or {}).get(key, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(0, min(top, value))


def per_trade(environ=None) -> int:
    """How many guild members are designated per trade."""
    return _knob(environ, PER_TRADE_ENV, DEFAULT_PER_TRADE, MAX_PER_TRADE)


def soon_gap(environ=None) -> int:
    """How many skill points short a crafter may be and still be sent a recipe."""
    return _knob(environ, SOON_GAP_ENV, DEFAULT_SOON_GAP, MAX_SOON_GAP)


@dataclass(frozen=True)
class Person:
    """A family member or guildmate: skill line id -> value, level, presence."""

    name: str
    skills: dict
    level: int = 0
    family: bool = False
    online: bool = False

    def rank(self, skill: int) -> int:
        return _int((self.skills or {}).get(int(skill), 0))


@dataclass(frozen=True)
class Seat:
    """One place in the register: who, in which trade, and why there."""

    trade: str
    skill: int
    name: str
    rank: int
    level: int
    seat: str

    @property
    def said(self) -> str:
        return "%s %d (level %d, %s)" % (self.name, self.rank, self.level, self.seat)


def register(people, n: int = DEFAULT_PER_TRADE) -> dict:
    """skill id -> tuple of Seat: family holders first, then N designated.

    `people` is one guild: the family and every other member. A family member
    holds a seat for every trade they have any skill in. A guildmate is
    designated by skill, then level, then fewest seats already held, then
    name, and only with some skill in the trade.
    """
    people = sorted(people, key=lambda p: p.name)
    load: dict = {}
    out: dict = {}
    for skill in sorted(TRADES):
        trade = TRADES[skill]
        seats = [
            Seat(trade, skill, p.name, p.rank(skill), _int(p.level), FAMILY)
            for p in sorted(
                people, key=lambda p: (-p.rank(skill), -_int(p.level), p.name)
            )
            if p.family and p.rank(skill) > 0
        ]
        others = [p for p in people if not p.family and p.rank(skill) > 0]
        others.sort(
            key=lambda p: (-p.rank(skill), -_int(p.level), load.get(p.name, 0), p.name)
        )
        for p in others[: max(0, int(n))]:
            load[p.name] = load.get(p.name, 0) + 1
            seats.append(
                Seat(trade, skill, p.name, p.rank(skill), _int(p.level), DESIGNATED)
            )
        out[skill] = tuple(seats)
    return out


def register_lines(reg: dict) -> list:
    """One line per trade with any seat, for the log and the page."""
    lines = []
    for skill in sorted(reg):
        seats = reg[skill]
        if seats:
            lines.append(
                "%s: %s"
                % (TRADES.get(skill, str(skill)), ", ".join(s.said for s in seats))
            )
    return lines


def register_payload(reg: dict) -> list:
    """The register as the Lineup page draws it."""
    return [
        {
            "trade": TRADES.get(skill, str(skill)),
            "seats": [
                {"name": s.name, "rank": s.rank, "level": s.level, "seat": s.seat}
                for s in reg[skill]
            ],
        }
        for skill in sorted(reg)
        if reg[skill]
    ]


@dataclass(frozen=True)
class Recipe:
    """One recipe item the family holds, and where it is."""

    holder: str
    guid: int
    entry: int
    name: str
    skill: int
    rank: int
    spell: int = 0
    where: str = "bags"


def recipe_from_row(row) -> Recipe | None:
    """A Recipe from one world row, or None for a row that cannot be read."""
    try:
        recipe = Recipe(
            holder=str(row["holder"]).strip(),
            guid=int(row["item_guid"]),
            entry=int(row["entry"]),
            name=str(row.get("name") or ""),
            skill=int(row.get("required_skill") or 0),
            rank=int(row.get("required_rank") or 0),
            spell=int(row.get("recipe_spell") or 0),
            where=str(row.get("location") or "bags"),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not recipe.holder or recipe.guid <= 0 or recipe.skill <= 0:
        return None
    return recipe


@dataclass(frozen=True)
class Known:
    """Who has already learned what: (name, spell) and (name, entry) pairs."""

    spells: frozenset = frozenset()
    entries: frozenset = frozenset()

    def has(self, name: str, recipe: Recipe) -> bool:
        return (name, int(recipe.spell)) in self.spells or (
            name,
            int(recipe.entry),
        ) in self.entries


def known_from_rows(spell_rows=(), verdict_rows=()) -> Known:
    """Known from `character_spell` rows and the `use` verb's answers.

    `spell_rows` carry `name` and `spell`. `verdict_rows` are the learn rows
    recipebook reads back (`target_name`, `detail`, `entry`); only an
    `already knows` answer counts here, because a `skill too low` answer
    changes as the crafter trains.
    """
    spells = set()
    for row in spell_rows or ():
        name = str(row.get("name") or "")
        spell = _int(row.get("spell"))
        if name and spell:
            spells.add((name, spell))
    entries = set()
    for row in verdict_rows or ():
        if str(row.get("detail") or "").strip() != recipebook.ALREADY_KNOWN:
            continue
        name = str(row.get("target_name") or "")
        entry = _int(row.get("entry"))
        if name and entry:
            entries.add((name, entry))
    return Known(frozenset(spells), frozenset(entries))


@dataclass(frozen=True)
class Pick:
    """Where one recipe goes: the taker, their seat, and why."""

    recipe: Recipe
    taker: str = ""
    seat: str = ""
    when: str = ""
    why: str = ""
    online: bool = False

    @property
    def kept(self) -> bool:
        return self.seat == HOLDER

    @property
    def routed(self) -> bool:
        """True when somebody other than the holder is to receive it."""
        return bool(self.taker) and self.seat != HOLDER

    @property
    def said(self) -> str:
        where = (
            "" if self.recipe.where == "bags" else " (in the %s)" % self.recipe.where
        )
        if self.kept:
            return "%s keeps %s%s: %s" % (self.taker, self.recipe.name, where, self.why)
        if self.taker:
            return "%s's %s%s -> %s: %s" % (
                self.recipe.holder,
                self.recipe.name,
                where,
                self.taker,
                self.why,
            )
        return "%s's %s%s -> nobody: %s" % (
            self.recipe.holder,
            self.recipe.name,
            where,
            self.why,
        )


def _seats_by_name(reg: dict, skill: int) -> dict:
    return {s.name: (i, s.seat) for i, s in enumerate(reg.get(int(skill), ()))}


def candidates(recipe: Recipe, reg: dict, people, known: Known, gap: int) -> list:
    """Every person who could take this recipe, best first, as Pick values.

    See the module docstring for the tiers. A person who has learned it, or
    who is further than `gap` below its rank, is not a candidate. Only the
    register's own members are considered for the "soon" tiers; any
    guildmate who can learn it now is the last tier.
    """
    seats = _seats_by_name(reg, recipe.skill)
    ranked = []
    for person in people:
        if known.has(person.name, recipe):
            continue
        have = person.rank(recipe.skill)
        if have <= 0:
            continue
        now = have >= recipe.rank
        if not now and recipe.rank - have > int(gap):
            continue
        order, seat = seats.get(person.name, (len(seats), GUILD))
        if person.family:
            seat = FAMILY
        if seat == GUILD and not now:
            continue
        tier = {
            (FAMILY, True): 0,
            (DESIGNATED, True): 1,
            (FAMILY, False): 2,
            (DESIGNATED, False): 3,
            (GUILD, True): 4,
        }[(seat, now)]
        benefit = abs(have - recipe.rank)
        online = bool(person.online or person.family)
        if now:
            why = "%s %s %d, learns it now at %d" % (
                person.name,
                TRADES.get(recipe.skill, "skill"),
                have,
                recipe.rank,
            )
        else:
            why = "%s %s %d, %d short of %d" % (
                person.name,
                TRADES.get(recipe.skill, "skill"),
                have,
                recipe.rank - have,
                recipe.rank,
            )
        if seat != GUILD:
            why += ", %s crafter" % seat
        if person.name == recipe.holder:
            seat = HOLDER
        ranked.append(
            (
                (tier, benefit, not online, order, person.name),
                Pick(recipe, person.name, seat, NOW if now else SOON, why, online),
            )
        )
    ranked.sort(key=lambda pair: pair[0])
    return [pick for _, pick in ranked]


def choose(recipe: Recipe, reg: dict, people, known: Known, gap: int) -> Pick:
    """The one route for this recipe; a Pick with no taker when nobody fits."""
    if not classic.skill_ok(recipe.rank):
        return Pick(
            recipe,
            why="%s needs %s %d, past the classic ruleset's %d: nobody learns it"
            % (
                recipe.name,
                TRADES.get(recipe.skill, "skill"),
                recipe.rank,
                classic.MAX_PROFESSION_SKILL,
            ),
        )
    found = candidates(recipe, reg, people, known, gap)
    if found:
        return found[0]
    return Pick(
        recipe,
        why="nobody in the family or guild can learn %s (%s %d) now or within %d "
        "points without already knowing it"
        % (
            recipe.name,
            TRADES.get(recipe.skill, "skill"),
            recipe.rank,
            int(gap),
        ),
    )


def route(recipes, reg: dict, people, known: Known, gap: int) -> dict:
    """item guid -> Pick for every recipe."""
    people = list(people)
    return {int(r.guid): choose(r, reg, people, known, gap) for r in recipes}


def summary(picks: dict) -> str:
    """The pass's one log line."""
    values = list(picks.values())
    return (
        "%s %d recipe(s): %d kept by a holder who learns them, %d routed to a "
        "crafter, %d with nobody"
        % (
            LOG_PREFIX,
            len(values),
            sum(1 for p in values if p.kept),
            sum(1 for p in values if p.routed),
            sum(1 for p in values if not p.taker),
        )
    )


# ---------------------------------------------------------------------------
# THE PICKUP: a designated crafter's recipe letters, taken out and learned.


@dataclass(frozen=True)
class Letter:
    """One recipe in one letter to one guild crafter."""

    receiver: str
    mail_id: int
    item_guid: int
    recipe: Recipe
    ready: bool = True


def letter_from_row(row) -> Letter | None:
    """A Letter from one mail row, or None for a row that cannot be read.

    `ready` is False for a letter still inside its delivery delay or carrying
    cash on delivery; the module refuses to take from either.
    """
    try:
        receiver = str(row["receiver"]).strip()
        mail_id = int(row["mail_id"])
        item_guid = int(row["item_guid"])
    except (KeyError, TypeError, ValueError):
        return None
    recipe = recipe_from_row(
        {
            "holder": receiver,
            "item_guid": item_guid,
            "entry": row.get("entry"),
            "name": row.get("name"),
            "required_skill": row.get("required_skill"),
            "required_rank": row.get("required_rank"),
            "recipe_spell": row.get("recipe_spell"),
            "location": "mailbox",
        }
    )
    if recipe is None or not receiver or mail_id <= 0:
        return None
    ready = bool(_int(row.get("delivered"), 1)) and _int(row.get("cod")) == 0
    return Letter(receiver, mail_id, item_guid, recipe, ready)


@dataclass(frozen=True)
class Take:
    """One recipe to take out of a letter and learn."""

    receiver: str
    mail_id: int
    item_guid: int
    name: str

    @property
    def take_command(self) -> str:
        return "%s mail:%d item:%d" % (mailrun.TAKE_ITEM, self.mail_id, self.item_guid)

    @property
    def use_command(self) -> str:
        return recipebook.use_command(item_guid=self.item_guid)


@dataclass(frozen=True)
class Visit:
    """One crafter walked to a mailbox to take out and learn its recipes."""

    receiver: str
    takes: tuple

    @property
    def walk_command(self) -> str:
        return "%s max:%d" % (guildroute.WALK_VERB, int(guildroute.MAIL_RUN_YARDS))

    @property
    def said(self) -> str:
        return "%s %s walks to a mailbox to take out and learn %s" % (
            LOG_PREFIX,
            self.receiver,
            ", ".join(t.name for t in self.takes),
        )


def visits(letters, crafters: dict, known: Known, busy=frozenset(), free_slots=None):
    """(visits, notes): which crafters walk to take their recipe letters.

    `crafters` maps a designated guild crafter's name (never a family member,
    whose own mail pass collects) to their Person. A letter is taken only
    when its receiver can learn the recipe now and has not learned it; the
    rest stay in the mailbox and a note says why. At most WALKS_PER_PASS
    visits and TAKES_PER_VISIT recipes each, within the crafter's free slots.
    """
    free_slots = free_slots or {}
    by_receiver: dict = {}
    notes = []
    for letter in sorted(letters, key=lambda x: (x.receiver, x.mail_id, x.item_guid)):
        person = crafters.get(letter.receiver)
        if person is None:
            continue
        name = letter.recipe.name
        if not letter.ready:
            notes.append("%s's %s is not ready to take yet" % (letter.receiver, name))
            continue
        if known.has(letter.receiver, letter.recipe):
            notes.append("%s already knows %s" % (letter.receiver, name))
            continue
        if person.rank(letter.recipe.skill) < letter.recipe.rank:
            notes.append(
                "%s's %s waits: %s %d of %d"
                % (
                    letter.receiver,
                    name,
                    TRADES.get(letter.recipe.skill, "skill"),
                    person.rank(letter.recipe.skill),
                    letter.recipe.rank,
                )
            )
            continue
        by_receiver.setdefault(letter.receiver, []).append(
            Take(letter.receiver, letter.mail_id, letter.item_guid, name)
        )
    out = []
    for receiver in sorted(by_receiver):
        if len(out) >= WALKS_PER_PASS:
            notes.append("%s waits: %d walks this pass" % (receiver, WALKS_PER_PASS))
            continue
        if receiver in busy:
            notes.append("%s is already on a walk" % receiver)
            continue
        if not crafters[receiver].online:
            notes.append("%s is offline" % receiver)
            continue
        room = _int(free_slots.get(receiver), -1)
        limit = TAKES_PER_VISIT if room < 0 else min(TAKES_PER_VISIT, room)
        if limit <= 0:
            notes.append("%s has no free bag slot" % receiver)
            continue
        out.append(Visit(receiver, tuple(by_receiver[receiver][:limit])))
    return out, notes


def walk_refusal(name: str, walker) -> str:
    """Why this crafter is not walked to a mailbox now, "" when it can be.

    The same refusals the gear route and the guild dues walks make
    (`guildroute.cannot_walk`), and only a bot off the roster: a family
    member's own mail pass collects its letters.
    """
    why = guildroute.cannot_walk(walker, name, guildroute.MAIL_RUN_YARDS)
    if not why and not walker.by_row:
        why = "%s cannot be walked by the mailbox walk row" % name
    return "%s waits: %s" % (name, why) if why else ""
