"""A guild member's class spells, bought at its class trainer with its own gold.

WHY THIS EXISTS. Measured on the dev realm on 2026-10-10 at about 12:50 ET:
134 of the 142 members of the two family guilds had class spells waiting at a
trainer, 1,569 in all and a median of ten each. A level 25 mage in Cave
waited on 25 of them (6 gold 1 silver), and the members who could afford
some of theirs had not bought them either. A guild member off the roster is a
random playerbot running the `new rpg` strategy, which never visits a trainer,
and no guild pass walked one to its class trainer: the module's
`walk-to-trainer` row bought trades (`skill:`) and talent resets
(`talents:`) only.

WHAT A PLAYER DOES. Rides to its class trainer when it has the gold and buys
what the trainer teaches it, the cheapest and lowest first. So a member that
can pay for at least one waiting spell is walked there by the module's
`walk-to-trainer class` row (quadseven/mod-overseer, the sibling of this
change), and on arrival the module buys each spell through the core's own
Trainer::TeachSpell, which takes the money and checks every requirement.
Nothing is taught for free and nothing here can teach.

TRAINING COMES FIRST (the operator, 2026-10-10: "Members keep gold for
training first, guild funds the rest"). `due` is also what the guild dues
leave in a member's purse (guildwork.dues_for's `reserve`) and what the guild
fund tops a short member up to (guildfund.py).

THE RULE IS THE PROFILE'S. Which spells count is `spell_state`, the same rule
the Standing card shows (apiv2/training.py reads it from here), so the page
and the pass cannot disagree about what a member is waiting on.

PURE MODULE: rows in, a plan and sentences out. No MySQL and no clock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import classic
import dungeonplan
import guildroute

LOG_PREFIX = "guild training:"
# The command log's source for a class trainer walk: `guildtrain:<member>`.
SOURCE = "guildtrain"
# The module's row, kind='cast' like every trainer walk.
VERB = "walk-to-trainer class"
KIND = "cast"

# How many members of one guild start a walk in one pass, so a guild of
# seventy is spread over a few passes rather than walked at once.
WALKS_PER_GUILD = 3
# A member walked in the last this many minutes is not walked again, whatever
# the walk answered: a trainer that taught what the purse covered has nothing
# more to sell it until it earns more or levels.
COOLDOWN_MINUTES = 180
# A worldserver that does not know the class walk answers this, and is not
# asked again for this long.
MALFORMED = "malformed walk-to-trainer command"
UNSUPPORTED_SECONDS = 6 * 3600.0


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _needs(row) -> list:
    return [_int(row.get(k)) for k in ("req1", "req2", "req3") if _int(row.get(k))]


def spell_state(row, known, level, cap) -> str:
    """'learned', 'trainable', 'needs', 'above' or '' (past the level cap).

    `row` is one class trainer spell: its id, the level it asks and the spells
    it requires first (ReqAbility1-3). Trainable now: not known, its level is
    reached, and every spell it requires is known.
    """
    spell = _int(row["spell"])
    if spell in known:
        return "learned"
    asks = _int(row.get("level"))
    if asks > level:
        return "above" if asks <= cap else ""
    if all(n in known for n in _needs(row)):
        return "trainable"
    return "needs"


@dataclass(frozen=True)
class Due:
    """What one member's class trainer would sell it now."""

    copper: int = 0  # every spell trainable now, together
    count: int = 0
    cheapest: int = 0  # the cheapest one, 0 when there is none

    def affords(self, money) -> bool:
        """Whether the purse covers at least one waiting spell."""
        return self.count > 0 and _int(money) >= self.cheapest


def due(trainer_rows, known, level) -> Due:
    """The class spells trainable now, by `spell_state`, and what they cost."""
    known = {_int(k) for k in known or ()}
    level = _int(level)
    costs = [
        _int(row.get("cost"))
        for row in trainer_rows or ()
        if spell_state(row, known, level, level) == "trainable"
    ]
    if not costs:
        return Due()
    return Due(sum(costs), len(costs), min(costs))


@dataclass(frozen=True)
class Trainee:
    """One guild member off the roster, as the bridge read it."""

    name: str
    guild: str
    level: int
    money: int
    due: Due
    online: bool = False


@dataclass(frozen=True)
class Walk:
    """One member walked to its class trainer to buy what it can afford."""

    name: str
    guild: str
    level: int
    spells: int
    cost: int
    money: int
    cap: float = guildroute.FAR_WALK_YARDS

    @property
    def command(self) -> str:
        return VERB + guildroute.errand_cap_word(self.cap)

    @property
    def source(self) -> str:
        return "%s:%s" % (SOURCE, self.name)

    @property
    def said(self) -> str:
        return (
            "%s %s (%s, level %d) walks to its class trainer with %dc for %d "
            "waiting spell(s) costing %dc"
            % (
                LOG_PREFIX,
                self.name,
                self.guild,
                self.level,
                self.money,
                self.spells,
                self.cost,
            )
        )


def trainees_from_rows(rows, dues) -> list:
    """Trainee rows out of the bridge's guild rows and classtrain.due's map."""
    return [
        Trainee(
            str(r["name"]),
            str(r.get("guild_name") or ""),
            _int(r.get("level")),
            _int(r.get("money")),
            (dues or {}).get(str(r["name"]), Due()),
            bool(_int(r.get("online"))),
        )
        for r in rows or ()
        if r.get("name")
    ]


def within(rows, seconds) -> list:
    """The log rows no older than `seconds` (their `age` is in minutes)."""
    return [r for r in rows or () if _int(r.get("age"), 10**9) * 60 <= seconds]


def pass_line(trainees, started) -> str:
    """The training pass's one line for the log."""
    return (
        "%s %d class spell(s) wait for %d member(s); %d can pay for one; started %d trainer walk(s)"
        % (
            LOG_PREFIX,
            sum(t.due.count for t in trainees),
            sum(1 for t in trainees if t.due.count),
            sum(1 for t in trainees if t.due.affords(t.money)),
            started,
        )
    )


def walk_refusal(walker, name) -> str:
    """Why this member is not walked to a trainer now, "" when it can be.

    The mailbox walk's own refusals (guildroute) without its mailbox distance:
    the module chooses the trainer, on the walker's own map.
    """
    if walker is None or walker.map_id is None:
        return "%s is not in the world" % name
    if walker.unwalkable:
        return "%s is %s" % (name, walker.unwalkable)
    if walker.in_combat:
        return "%s is in combat" % name
    if classic.is_expansion_map(walker.map_id):
        return classic.outside_note(name, walker.map_id)
    if walker.map_id not in dungeonplan.CONTINENT_MAPS:
        return "%s is inside an instance" % name
    if not walker.by_row:
        return "%s cannot be walked by the trainer walk row" % name
    return ""


def recent_walkers(rows, minutes=COOLDOWN_MINUTES) -> set:
    """Members walked inside the cooldown, from the command log's rows.

    `rows` carry target_name, source and age (minutes).
    """
    out = set()
    for row in rows or ():
        source = str(row.get("source") or "")
        if not source.startswith(SOURCE + ":"):
            continue
        if _int(row.get("age"), minutes + 1) <= minutes:
            out.add(str(row.get("target_name") or source.split(":", 1)[1]))
    return out


def unsupported(rows) -> bool:
    """Whether the worldserver refused the class walk as a malformed row."""
    return any(
        str(row.get("source") or "").startswith(SOURCE + ":")
        and MALFORMED in str(row.get("detail") or "")
        for row in rows or ()
    )


def plan(
    trainees,
    walkers,
    recent,
    busy,
    per_guild=WALKS_PER_GUILD,
    cap=guildroute.FAR_WALK_YARDS,
) -> tuple:
    """(walks, notes): which members walk to their class trainer this pass.

    A member walks when it is online, can pay for at least one waiting spell
    from its own purse, was not walked inside COOLDOWN_MINUTES, is not on
    another guild walk, and the walk row can move it. Inside a guild the
    member with the most spells it can pay for goes first.
    """
    recent = {str(n) for n in recent or ()}
    busy = {str(n) for n in busy or ()}
    walks, notes, started = [], [], {}

    def key(t):
        return (-min(t.due.count, _affordable(t)), -t.level, t.name)

    for t in sorted(trainees or (), key=key):
        if not t.due.count:
            continue
        if not t.due.affords(t.money):
            notes.append(
                "%s saves for its trainer: %d spell(s) wait, the cheapest %dc, "
                "it carries %dc" % (t.name, t.due.count, t.due.cheapest, t.money)
            )
            continue
        if not t.online:
            continue
        if t.name in recent:
            continue
        if t.name in busy:
            notes.append("%s is already on a guild walk" % t.name)
            continue
        why = walk_refusal((walkers or {}).get(t.name), t.name)
        if why:
            notes.append("%s waits: %s" % (t.name, why))
            continue
        if started.get(t.guild, 0) >= per_guild:
            notes.append(
                "%s waits: %d trainer walks per guild per pass" % (t.name, per_guild)
            )
            continue
        started[t.guild] = started.get(t.guild, 0) + 1
        walks.append(
            Walk(t.name, t.guild, t.level, t.due.count, t.due.copper, t.money, cap)
        )
    return walks, notes


def _affordable(trainee) -> int:
    """How many waiting spells the purse could cover, cheapest first, judged
    from the total and the cheapest alone (the bridge reads no more)."""
    if not trainee.due.count or trainee.money < trainee.due.cheapest:
        return 0
    if trainee.money >= trainee.due.copper:
        return trainee.due.count
    return max(1, trainee.due.count * trainee.money // max(1, trainee.due.copper))


def summary(rows) -> str:
    """One sentence over the class walks of the last day, from the log rows.

    `rows` carry status and result (the module's JSON, as text or a dict).
    """
    walks = learned = spells = 0
    for row in rows or ():
        if not str(row.get("source") or "").startswith(SOURCE + ":"):
            continue
        walks += 1
        result = row.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = {}
        taught = (result or {}).get("taught") or ()
        if str(row.get("status")) == "applied" and taught:
            learned += 1
            spells += len(taught)
    return (
        "%s %d class trainer walk(s) in the last day, %d bought spells, %d spell(s) learned"
        % (LOG_PREFIX, walks, learned, spells)
    )
