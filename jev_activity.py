"""What a family does next, asked of Jev the way a group of players decides (#216).

WHY THIS EXISTS. The families' activities come from fixed rules on timers: a
campaign queue, the craft rhythm, the skill goal, the council's dungeon lease.
Each pass writes the same job until a cap or a threshold flips it, so a family
grinds one thing and then another. Real players choose among activities all
session long, for reasons: bags are full, so sell first; the group has run the
same dungeon for an hour, so take a break; a trainer has new ranks waiting.
Every one of those activities already has a command path in the bridge, which
makes the choice between them a closed Choice, and that is Jev's shape.

WHAT JEV IS OFFERED. Only what the family can carry out now (`options`):

  campaign  keep running the dungeon the operator queued (or the council's
            dungeon job). Offered only when a run can start: never while bag
            pressure withholds it.
  quest     the default job and the quest drive, always available.
  gather    walk to a node field for the family's gathering trades. Offered
            only where the bridge can aim the walk (this bridge's own family,
            with a gatherer and room in the bags).
  craft     job=craft, which DriveCraft carries out for every member holding a
            recipe errand (`overseer_roster.craft_spell`). Offered only when
            somebody holds one.
  sell      the vendor pass and the bag purchase: sell junk and outgrown gear,
            buy bags, then walk to a bag vendor if none is in reach. Offered
            when the run is withheld for bag space or a member is nearly full.
  train     job=train, which aims the leader at a trainer. Offered only where
            trainjob.readiness has something to learn (this bridge's family).
  fish      job=fish, mod-overseer's fishing drive (jobs.DRIVES): the bots'
            own fishing AI, which a player reaches for between errands (#267).
            Offered only with room in every member's bags and the run not
            withheld. Nothing else ever writes job=fish, so when its lease
            ends the bridge puts the family back on the default job.

REST IS NOT OFFERED, and that is the honest choice set rather than an
omission. `jobs.MODES` names `rest` but it is not in `jobs.IMPLEMENTED`, and
nothing in the bridge writes a hearth or an inn errand, so choosing it would
stand the quest drive down and put nothing in its place. The same rule
jev_items applies to disenchanting: a route with no executor is never shown.

OPERATOR ORDERS ARE COMMITMENTS. Nothing here, and nothing the bridge does with
an answer, cancels, reorders or rewrites a queue entry. A choice other than
`campaign` is an INTERLUDE: a bounded lease (`LEASE_MINUTES`) during which the
queue pass holds its next start or re-assert, after which the queue resumes
exactly where it was. When the run cannot start at all (withheld for bag
space), the choice is what to do instead of idling, which is the case the
operator named: sell or buy bags.

ACT MODE WITH A CONFIDENCE FLOOR. `policy` defaults this kind to act at 0.6
(JEV_MODE_ACTIVITY_CHOICE and JEV_THRESHOLD_ACTIVITY_CHOICE override both).
The heuristic's answer is "carry on with what today's rules are doing", so
whenever Jev is slow, down, busy, has no key, or is below the floor, nothing
is written and today's rules stand.

WHEN IT IS ASKED (`due`). On a cadence (`CADENCE_MINUTES`) and at the natural
breakpoints a player stops at: a run finished, a level gained, a death, bags
too full for the next run, arriving in town. Never mid-run, and never while an
interlude it chose is still running.

NOT IN LOCKSTEP (#267). Every family used to be asked on the same 20-minute
clock and every interlude lasted exactly its LEASE_MINUTES, so the realm's
families changed what they were doing on the same minute. Each family now has
its own cadence within SPREAD of CADENCE_MINUTES (`cadence_seconds`, fixed per
family) and each interlude its own length within SPREAD of its lease
(`lease_minutes`, which also varies with the minute the interlude began, so
one family's breaks differ from one another too). Deterministic, from the family key and the minute, so a
test can pin it and a log can explain it.

SAID OUT LOUD. When Jev changes what a family does, its leader says so with a
text emote (`emote`), the way a player announces a break to the group.

PURE: facts in, questions and judgments out. The only I/O is the client the
caller hands in.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, replace

import bag_pressure
import bonds
import jev
import jobs

KIND = "activity_choice"
DEFAULT_THRESHOLD = 0.6

# The source every job row a carried-out choice writes, so the Decree and the
# log can tell Jev's activity from any other job order.
SOURCE = "overseer:activity"

CAMPAIGN = "campaign"
QUEST = "quest"
GATHER = "gather"
CRAFT = "craft"
SELL = "sell"
TRAIN = "train"
FISH = "fish"
ACTIVITIES = (CAMPAIGN, QUEST, GATHER, CRAFT, SELL, TRAIN, FISH)

# The job each activity puts the family on. "" writes none: the campaign's
# job belongs to the queue (or the council's lease), which re-asserts it.
# Gathering and selling happen under the quest job, as they do today.
JOB = {
    CAMPAIGN: "",
    QUEST: jobs.DEFAULT,
    GATHER: jobs.DEFAULT,
    SELL: jobs.DEFAULT,
    CRAFT: "craft",
    TRAIN: "train",
    FISH: "fish",
}

# The job to put the family back on when an interlude ends, for the jobs no
# other pass re-asserts. Craft and train have their own passes; nothing but
# this choice ever writes job=fish.
RESTORE = {FISH: jobs.DEFAULT}

# How long an interlude holds the queue and the automatic job passes. Long
# enough for the errand to be walked and done, short enough that a commitment
# of fifty runs loses minutes to it, never the order.
LEASE_MINUTES = {QUEST: 30, GATHER: 20, CRAFT: 20, SELL: 10, TRAIN: 15, FISH: 15}

CADENCE_MINUTES = 20
# How far a family's cadence and an interlude's length stray from the above:
# 0.25 is 15 up to 25 minutes on the 20-minute cadence.
SPREAD = 0.25

# A member at or below this many free slots makes a town trip worth offering
# even while the run can still start. bag_pressure.TOWN_RUN_FREE_SLOTS is the
# stricter floor at which the run is withheld outright.
SELL_FREE_SLOTS = 6
# Fishing fills bags with the catch, so it is offered only while every member
# has more than this many free slots.
FISH_FREE_SLOTS = 10

# Why the question was asked now; recorded with it.
CADENCE = "on the cadence"
AFTER_RUN = "a dungeon run finished"
AFTER_LEVEL = "a level was gained"
AFTER_DEATH = "a member died"
BAGS_FULL = "bags too full for the next run"
TOWN = "arrived in town"


def policy(environ=None) -> jev.Policy:
    """Act by default, at a 0.6 floor."""
    return jev.policy(
        KIND,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=DEFAULT_THRESHOLD,
    )


@dataclass(frozen=True)
class Member:
    """One family member as the choice sees them.

    `free_slots` is None when the bags could not be read. `recipe` is whether
    the member holds a craft errand (overseer_roster.craft_spell), which is
    what job=craft carries out.
    """

    name: str
    level: int
    class_name: str = ""
    free_slots: int | None = None
    empty_gear_slots: int | None = None
    trade_goods: int = 0
    recipe: bool = False


@dataclass(frozen=True)
class Facts:
    """Everything the question carries about one family, read this cycle."""

    family: str
    members: tuple
    job: str = ""
    queue: str = ""
    withheld: bool = False
    can_gather: bool = False
    can_train: bool = False
    minutes_on_activity: int = 0
    reason: str = CADENCE
    minutes_since_fishing: int | None = None

    @property
    def levels(self) -> list:
        return [int(m.level) for m in self.members]

    @property
    def spread(self) -> int:
        levels = self.levels
        return max(levels) - min(levels) if levels else 0

    @property
    def on_dungeon(self) -> bool:
        return jobs.is_dungeon_job(self.job)


# The equipment slots a member can fill (bag 0, slots 0-17), less the shirt
# (3), which carries no stats. The tabard (18) is not counted either.
GEAR_SLOTS = tuple(s for s in range(18) if s != 3)


def members_from_rows(names, level_rows, free_slots, worn_rows, goods_rows, recipes):
    """Members, in `names` order, from the bridge's reads. Pure.

    A member with no level row is still shown, at level 0, rather than
    dropped: the question is about the whole family. A member whose worn
    items could not be read (`worn_rows` None) has `empty_gear_slots` None,
    not 0.
    """
    levels = {str(r.get("name")): r for r in level_rows or ()}
    worn = _counts(worn_rows, "worn")
    goods = _counts(goods_rows, "stacks")
    free = dict(free_slots or {})
    holders = set(recipes or ())
    return tuple(
        Member(
            name=name,
            level=int(levels.get(name, {}).get("level") or 0),
            class_name=str(levels.get(name, {}).get("class_name") or ""),
            free_slots=int(free[name]) if name in free else None,
            empty_gear_slots=_empty(worn, name),
            trade_goods=goods.get(name, 0) if goods else 0,
            recipe=name in holders,
        )
        for name in names
    )


def _counts(rows, column: str) -> dict | None:
    """name -> int(column), or None when the rows could not be read."""
    if rows is None:
        return None
    return {str(r.get("name")): int(r.get(column) or 0) for r in rows}


def _empty(worn: dict | None, name: str) -> int | None:
    if worn is None:
        return None
    return max(0, len(GEAR_SLOTS) - worn.get(name, 0))


def withheld(queued: bool, free_slots: dict) -> bool:
    """Whether a queued run would be withheld for bag space right now.

    The same predicate bridge._drive_dungeon asks before it writes a run, so
    this can never disagree with the writer about whether the run can start.
    """
    return bool(queued) and bag_pressure.family_town_run_needed(dict(free_slots))


# ---------------------------------------------------------------------------
# WHEN TO ASK


@dataclass(frozen=True)
class Marks:
    """What a breakpoint is measured against, from one cycle to the next."""

    runs_done: int | None
    levels: tuple
    deaths: int
    withheld: bool
    at_town: bool


def stopped_at(before: Marks | None, now: Marks) -> str:
    """The breakpoint between two cycles, or "" when nothing happened."""
    if before is None:
        return ""
    if (
        now.runs_done is not None
        and before.runs_done is not None
        and now.runs_done > before.runs_done
    ):
        return AFTER_RUN
    was = dict(before.levels)
    if any(level > was.get(name, level) for name, level in now.levels):
        return AFTER_LEVEL
    if now.deaths > before.deaths:
        return AFTER_DEATH
    if now.withheld and not before.withheld:
        return BAGS_FULL
    if now.at_town and not before.at_town:
        return TOWN
    return ""


def due(reason: str, last_asked: float | None, now: float, cadence_seconds) -> str:
    """Why to ask now, or "": a breakpoint, else the cadence running out."""
    if reason:
        return reason
    if last_asked is None or now - last_asked >= float(cadence_seconds):
        return CADENCE
    return ""


# ---------------------------------------------------------------------------
# THE OPTIONS AND TODAY'S ANSWER


def _crafters(f: Facts) -> list:
    return sorted(m.name for m in f.members if m.recipe)


def _nearly_full(f: Facts) -> list:
    return sorted(
        m.name
        for m in f.members
        if m.free_slots is not None and m.free_slots <= SELL_FREE_SLOTS
    )


def options(f: Facts) -> dict:
    """Every activity the family can carry out now, as a Choice's criteria."""
    out = {}
    if (f.queue or f.on_dungeon) and not f.withheld:
        out[CAMPAIGN] = (
            "Keep the commitment: run the next dungeon from the operator's "
            "queue (%s)." % f.queue
            if f.queue
            else "Keep running the dungeon the council chose."
        )
    out[QUEST] = "Quest together through the family's quest logs."
    if f.can_gather:
        out[GATHER] = "Go out and gather herbs or ore for the family's professions."
    crafters = _crafters(f)
    if crafters:
        out[CRAFT] = (
            "Stop and craft: %s work the recipes they are levelling (bags, "
            "potions, gear)." % ", ".join(crafters)
        )
    if f.withheld or _nearly_full(f):
        out[SELL] = (
            "Go to town: sell junk and outgrown gear, buy bigger bags, repair "
            "and restock."
        )
    if f.can_train:
        out[TRAIN] = "Visit a trainer to learn the ranks and trades waiting."
    if can_fish(f):
        out[FISH] = "Take a break by the water: fish together for food and reagents."
    return out


def can_fish(f: Facts) -> bool:
    """Fishing fills bags, so it is offered only with room in every member's
    (and never while the run is withheld for bag space)."""
    if f.withheld or not f.members:
        return False
    return all(
        m.free_slots is not None and m.free_slots > FISH_FREE_SLOTS for m in f.members
    )


def heuristic(f: Facts) -> tuple:
    """(activity, why): what today's rules are doing, which acting changes nothing."""
    if f.queue:
        if f.withheld:
            return CAMPAIGN, (
                "the operator's queue (%s); the run is withheld for bag space "
                "and today's rules wait for the vendor pass" % f.queue
            )
        return CAMPAIGN, "the operator's queue: %s" % f.queue
    job = str(f.job or "").strip().lower()
    if jobs.is_dungeon_job(job):
        return CAMPAIGN, "the family is on the council's dungeon job (%s)" % job
    if job == JOB[CRAFT]:
        return CRAFT, "the craft rhythm has the family on job=craft"
    if job == JOB[TRAIN]:
        return TRAIN, "the family is on job=train"
    return QUEST, "the family is on job=%s, the default" % (job or jobs.DEFAULT)


# ---------------------------------------------------------------------------
# THE QUESTION


def _persona(name: str) -> dict:
    bond = bonds.bond_of(name)
    if bond is None:
        return {}
    text = " ".join(str(bond.persona or "").split())
    return {"role": bond.role, "persona": text[:240]}


def facts_line(f: Facts) -> str:
    """The facts as one sentence, for the record and the Jev card."""
    levels = f.levels
    parts = [
        "levels %d-%d (spread %d)" % (min(levels), max(levels), f.spread)
        if levels
        else "levels unknown"
    ]
    parts.append(
        "free bag slots "
        + ", ".join(
            "%s %s" % (m.name, "?" if m.free_slots is None else m.free_slots)
            for m in f.members
        )
    )
    gaps = [
        "%s %d" % (m.name, m.empty_gear_slots) for m in f.members if m.empty_gear_slots
    ]
    if gaps:
        parts.append("empty gear slots " + ", ".join(gaps))
    goods = ["%s %d" % (m.name, m.trade_goods) for m in f.members if m.trade_goods]
    if goods:
        parts.append("trade goods " + ", ".join(goods))
    if _crafters(f):
        parts.append("recipes " + ", ".join(_crafters(f)))
    parts.append("queue " + (f.queue or "empty"))
    if f.withheld:
        parts.append("run withheld for bag space")
    parts.append("job %s" % (f.job or jobs.DEFAULT))
    parts.append("%d min on this activity" % int(f.minutes_on_activity))
    return "; ".join(parts)


def question(f: Facts, offered: dict):
    """(state, questions) for "what does the family do next"."""
    state = {
        "family": [
            dict(
                {
                    "name": m.name,
                    "class": m.class_name or "unknown",
                    "level": int(m.level),
                    "free_bag_slots": (
                        "unknown" if m.free_slots is None else int(m.free_slots)
                    ),
                    "empty_gear_slots": (
                        "unknown"
                        if m.empty_gear_slots is None
                        else int(m.empty_gear_slots)
                    ),
                    "trade_goods_carried": int(m.trade_goods),
                    "has_a_recipe_to_craft": bool(m.recipe),
                },
                **_persona(m.name),
            )
            for m in f.members
        ],
        "level_spread": f.spread,
        "dungeon_queue": f.queue or "nothing queued",
        "dungeon_run": (
            "withheld: bags are too full to loot a run"
            if f.withheld
            else ("can start" if (f.queue or f.on_dungeon) else "none planned")
        ),
        "current_job": f.job or jobs.DEFAULT,
        "minutes_on_current_activity": int(f.minutes_on_activity),
        "minutes_since_the_family_last_fished": (
            "not this session"
            if f.minutes_since_fishing is None
            else int(f.minutes_since_fishing)
        ),
        "why_now": f.reason,
    }
    instructions = (
        "`family` is a group of World of Warcraft (3.3.5a) adventurers who "
        "play together the way a group of real human players does. Choose "
        "what they do next from the options, as sensible players would: "
        "first fix what stops play (bags too full to loot means sell or buy "
        "bags before anything else), keep the operator's `dungeon_queue` "
        "when the run can start, take a break from a long stretch of one "
        "activity, learn from a trainer when ranks are waiting, craft or "
        "gather for their professions when it helps the group, now and then "
        "unwind by fishing when nothing presses, and let each member's role "
        "and persona color the choice."
    )
    return state, {"activity": jev.choice(instructions, dict(offered))}


# ---------------------------------------------------------------------------
# THE RECORD


# Read before the class: its `jev` field shadows the module in the class body.
_HEURISTIC = jev.HEURISTIC


@dataclass(frozen=True)
class Judgment:
    """One activity choice, shaped for overseer_jev_judgment.

    The same columns jev_items.Judgment fills. `item_name` carries why the
    question was asked now and `facts` what it was asked with, so the record
    and the Jev card show both.
    """

    subject: str
    heuristic: str
    heuristic_why: str
    mode: str
    status: str
    item_name: str = ""
    facts: str = ""
    jev: str = ""
    confidence: float | None = None
    probabilities: dict | None = None
    latency_ms: int = 0
    model: str = ""
    acted: str = _HEURISTIC
    kind: str = KIND
    item_guid: int = 0
    item_entry: int = 0

    @property
    def holder(self) -> str:
        return self.subject

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    def probabilities_json(self, limit: int = 1000) -> str:
        if not self.probabilities:
            return ""
        ranked = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        text = json.dumps({k: round(v, 4) for k, v in ranked}, separators=(",", ":"))
        return text if len(text) <= limit else ""

    @property
    def carried_out(self) -> str:
        """The activity to carry out, or "" when today's rules stand."""
        return self.jev if self.acted == jev.JEV else ""

    def line(self) -> str:
        """One structured log line: who chose what, and from what."""
        if self.jev:
            answer = "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
        else:
            answer = "jev=-"
        chose = (
            "Jev chose %s" % self.jev
            if self.acted == jev.JEV
            else "today's rules stand (%s)" % self.heuristic
        )
        return (
            "activity: family=%s %s; kind=%s heuristic=%s %s status=%s "
            "latency_ms=%d mode=%s acted=%s why_now=%r facts=%r"
            % (
                self.subject,
                chose,
                self.kind,
                self.heuristic,
                answer,
                self.status,
                self.latency_ms,
                self.mode,
                self.acted,
                self.item_name,
                self.facts,
            )
        )


async def ask(client, f: Facts, rule: jev.Policy) -> Judgment | None:
    """Ask Jev what the family does next; None when there is nothing to ask.

    Nothing to ask is the kind switched off, or a single option that is
    already what the family is doing.
    """
    if rule.mode == jev.OFF:
        return None
    offered = options(f)
    current, why = heuristic(f)
    if len(offered) < 2 and current in offered:
        return None
    base = Judgment(
        subject=f.family,
        heuristic=current,
        heuristic_why=why,
        mode=rule.mode,
        status="",
        item_name=f.reason,
        facts=facts_line(f),
    )
    state, questions = question(f, offered)
    outcome = await client.ask(KIND, state, questions)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["activity"]
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=rule.acted(
            current, answer.choice, answer.confidence, can_act=answer.choice in offered
        ),
    )


# ---------------------------------------------------------------------------
# THE INTERLUDE


@dataclass(frozen=True)
class Interlude:
    """A chosen activity holding the family's job until `until` (monotonic)."""

    activity: str
    until: float

    def live(self, now: float) -> bool:
        return now < self.until


def _unit(*parts) -> float:
    """A fixed number in [0, 1) from `parts`: the same parts, the same number."""
    text = "|".join(str(p) for p in parts).encode("utf-8")
    return (zlib.crc32(text) & 0xFFFFFFFF) / 2**32


def _spread(value: float, *parts) -> float:
    """`value` moved by up to SPREAD either way, fixed by `parts`."""
    return value * (1.0 - SPREAD + 2.0 * SPREAD * _unit(*parts))


def cadence_seconds(family: str) -> float:
    """This family's own cadence: CADENCE_MINUTES within SPREAD, fixed per
    family, so families asked on one pass drift apart rather than turning
    together."""
    return 60.0 * _spread(CADENCE_MINUTES, "cadence", family)


def lease_minutes(activity: str, family: str = "", now: float = 0.0) -> float:
    """How long this interlude holds: its LEASE_MINUTES within SPREAD, varied
    by family and by the minute it began; 0 for the campaign."""
    minutes = LEASE_MINUTES.get(activity)
    if not minutes:
        return 0.0
    return _spread(minutes, "lease", activity, family, int(now // 60))


def interlude(activity: str, now: float, family: str = "") -> Interlude | None:
    """The lease for a carried-out activity, or None for the campaign itself."""
    minutes = lease_minutes(activity, family, now)
    if not minutes:
        return None
    return Interlude(activity, now + 60.0 * minutes)


# What the leader does, in the emote channel, when Jev changes the family's
# activity. Two per activity, picked by `emote`, so a long session does not
# repeat one line. Third person, as a text emote reads in the chat frame.
EMOTES = {
    QUEST: (
        "unrolls a worn quest map and taps the next mark.",
        "rallies the others back onto the road.",
    ),
    GATHER: (
        "sniffs the air for herbs and ore.",
        "shoulders a pick and heads for the hills.",
    ),
    CRAFT: (
        "rummages for reagents and settles in to craft.",
        "clears a spot to work and lays out the tools.",
    ),
    SELL: (
        "pats a bulging pack and points toward town.",
        "grumbles about full bags and turns for the vendor.",
    ),
    TRAIN: (
        "mutters about lessons waiting at the trainer.",
        "heads off to learn something new.",
    ),
    FISH: (
        "stretches and eyes the nearest water.",
        "digs out a fishing pole and whistles.",
    ),
}


def emote(activity: str, family: str = "", now: float = 0.0) -> str:
    """The leader's emote for starting `activity`, or '' for none."""
    lines = EMOTES.get(activity, ())
    if not lines:
        return ""
    return lines[int(_unit("emote", activity, family, int(now // 60)) * len(lines))]
