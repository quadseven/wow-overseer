"""The profession loop: gather, town, craft, train, and gather again (#2419).

WHY IT EXISTS. Each half of a profession session already works on its own:
`craft_rhythm` alternates gathering and crafting while a family is on one of
those two jobs, the town errand (townerrand.py) sells, banks, sorts and reads
the mail, and the learn errands buy a rank or a trainer recipe. Nothing moved a
family from one half to the next, so a person switched the job at every
boundary. This module is that switch, for a family an operator names.

THE PHASES, each with a measured entry and exit:

    GATHER  job quest, or farm:<trade> once the farm job is wired (#2417).
            -> TOWN   a member below TOWN_FREE_SLOTS free bag slots, or
                      GATHER_SECONDS spent (the haul goes to the bank).
            -> TOWN   after GATHER_MIN_SECONDS, every crafter holds reagents
                      for READY_CASTS casts and the mail or a bank holds more.
            -> CRAFT  the same, with nothing to fetch in town.
    TOWN    the town errand runs with LOOP_WHY as its reason (no cooldown).
            -> next   the errand ends, did not start within TOWN_START_SECONDS,
                      or TOWN_SECONDS pass.
    CRAFT   job craft, while a crafter's reagent plan (reagentplan.py) has a
            cast in the bags.
            -> next   no crafter has a cast left (after CRAFT_MIN_SECONDS), or
                      CRAFT_SECONDS pass.
    TRAIN   job train, while a rank or a trainer recipe is due and paid for.
            -> GATHER nothing is due, or TRAIN_SECONDS pass.

    "next" after TOWN is CRAFT when a crafter has a cast in the bags, else
    TRAIN when something is due, else GATHER. After CRAFT it is TRAIN or GATHER.

ONE OWNER OF THE JOB COLUMN. While a family is in the loop, this is the only
pass that writes its job outside a dungeon. The other writers (the craft
rhythm, the skill goal, the activity choice, the attunement step and the
leveling route) ask `enabled_for` and stand down. Two writers are let through
on purpose: the campaign queue and a dungeon run come first, and the loop waits
for them (`Facts.queue_owns`, `Facts.in_run`); and the town errand writes
`town run` and gives it back, which the TOWN phase expects. Any other job found
on a member is set back to the phase's job, at most once per REASSERT_SECONDS,
and said.

FAMILY-WIDE TODAY, PER MEMBER LATER. Jobs are family-wide until individual mode
(#2426) ships. `decide` reads its facts as maps keyed by member name and asks
nothing about the family beyond them, so individual mode can call it once per
member with that member's facts and its own State.

OFF BY DEFAULT. PROFESSION_LOOP names the families in the loop, comma-separated
(family keys, as overseer_roster.family holds them); empty means none.

PURE MODULE: no MySQL, no clock, no Discord. The caller passes `now`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

import craft_rhythm
import jobs

ENV_SWITCH = "PROFESSION_LOOP"
SOURCE = "overseer:loop"

GATHER = "gather"
TOWN = "town"
CRAFT = "craft"
TRAIN = "train"
PHASES = (GATHER, TOWN, CRAFT, TRAIN)

# Every town errand the loop starts says this first; townerrand.steps_for gives
# it the bag-room step order (vendor, bank, tidy first).
LOOP_WHY = "profession loop: "

# MEASURED ON THE DEV REALM, 2026-11-13. After a full town errand the two
# families stood at 13 to 26 free bag slots per member (Grug's 15 to 26, Zug's
# 13 to 25), and both families' banks were down to their last 2 slots. A target
# at or above 13 would send the fullest member straight back to town; 8 leaves
# a gathering trip room for five or more new stacks per member and still goes
# to town well before the vendor trigger of 3 (bag_pressure).
TOWN_FREE_SLOTS = 8
# The operator's time box for one gathering stretch.
GATHER_SECONDS = 6 * 3600.0
# A gathering stretch is never cut shorter than this by "the reagents are in
# hand", so a family is not sent back and forth across a field's edge.
GATHER_MIN_SECONDS = 20 * 60.0
# The town errand's own ceiling is an hour (townerrand.TOTAL_SECONDS), plus up
# to 20 minutes for its walk (GO_SECONDS); this outlasts both.
TOWN_SECONDS = 90 * 60.0
# The errand pass runs every couple of minutes; one that has not begun in ten
# has a reason not to (the head out of the world, a trade turn), so the loop
# moves on and says so rather than wait for the ceiling.
TOWN_START_SECONDS = 10 * 60.0
CRAFT_SECONDS = 90 * 60.0
CRAFT_MIN_SECONDS = 5 * 60.0
TRAIN_SECONDS = 45 * 60.0
REASSERT_SECONDS = 10 * 60.0
# "Reagents for the next crafts in hand" is the craft rhythm's own stocked bar.
READY_CASTS = craft_rhythm.STOCK_CASTS

# The node trades a farm job can name (#2417), in the order a tie is broken.
FARM_TRADES = ("mining", "herbalism")


def families(env=None) -> frozenset:
    """The family keys PROFESSION_LOOP names; empty when it is unset."""
    raw = (os.environ if env is None else env).get(ENV_SWITCH, "")
    return frozenset(part.strip() for part in str(raw).split(",") if part.strip())


def enabled_for(key, env=None) -> bool:
    """Whether the family `key` is in the loop."""
    return bool(key) and str(key) in families(env)


@dataclass(frozen=True)
class State:
    """One family's place in the loop. `since` is when the phase began;
    `asserted` when the loop last wrote a job; `town_seen` whether the town
    errand was seen under way during this TOWN phase."""

    phase: str = ""
    since: float = 0.0
    asserted: float = 0.0
    town_seen: bool = False


@dataclass(frozen=True)
class Facts:
    """What `decide` reads. Every map is keyed by member name.

    `casts`: casts each crafter's reagent plan has in the bags, for crafters
    whose recipe reagentplan judges. `fetch`: crafters whose short reagents
    all come from a bank, the mail, the guild bank or a vendor. `train_due`:
    the ranks and trainer recipes due and paid for. `errand_*`: the town
    errand, on the same monotonic clock as `now`.
    """

    now: float
    jobs: dict = field(default_factory=dict)
    free_slots: dict = field(default_factory=dict)
    mail_waiting: tuple = ()
    casts: dict = field(default_factory=dict)
    fetch: tuple = ()
    train_due: dict = field(default_factory=dict)
    errand_active: bool = False
    errand_ended: float = 0.0
    errand_why: str = ""
    in_run: bool = False
    queue_owns: bool = False
    gather_job: str = "quest"


@dataclass(frozen=True)
class Step:
    """`decide`'s answer. `job` is the job to write now ('' for none);
    `ask_town` the reason to hand the town errand ('' for none); `line` the
    sentence to log ('' for nothing new); `moved` whether the phase changed."""

    state: State
    job: str = ""
    ask_town: str = ""
    line: str = ""
    moved: bool = False


def gather_job(skills: dict) -> tuple:
    """(job, why) for the GATHER phase, from name -> {trade: value}.

    The farm job (#2417) aims a family at the nodes its best holder of one
    trade can open, so the loop names the node trade the family is furthest
    behind in: the lowest best value among the members who hold it. Until
    `jobs.can_set` accepts `farm:<trade>` the answer is `quest`, which gathers
    by roaming. Skinning is not a node trade (the farm job cannot aim at
    creatures), so it rises on the creatures the family kills on either job.
    """
    best: dict = {}
    for trades in (skills or {}).values():
        for trade in FARM_TRADES:
            value = int((trades or {}).get(trade) or 0)
            if value > 0:
                best[trade] = max(best.get(trade, 0), value)
    if not best:
        return "quest", "nobody holds mining or herbalism, so the family roams"
    trade = min(best, key=lambda t: (best[t], FARM_TRADES.index(t)))
    job = "farm:%s" % trade
    if not jobs.can_set(job):
        return "quest", (
            "%s is furthest behind (best %d), but the farm job is not wired "
            "here, so the family gathers by roaming" % (trade, best[trade])
        )
    return job, "%s is furthest behind (best %d)" % (trade, best[trade])


def phase_job(phase: str, facts: Facts) -> str:
    """The job a phase writes; '' for TOWN, whose errand writes its own."""
    if phase == GATHER:
        return facts.gather_job or "quest"
    if phase == CRAFT:
        return craft_rhythm.MODE_CRAFT
    if phase == TRAIN:
        return "train"
    return ""


def _held(phase: str, job: str, gather: str = "quest") -> bool:
    """Whether `job` on a member is what `phase` expects there.

    GATHER wants a farm job when the loop has one to name: a member left on
    `quest` is on the council and leveling drives, which walk to quest givers
    and never to a node, so it is not gathering."""
    job = str(job or "").strip().lower()
    if phase == GATHER:
        if job.startswith("farm:"):
            return True
        return job == "quest" and not str(gather or "").startswith("farm:")
    if phase == TOWN:
        return job in ("quest", jobs.TOWN_RUN)
    if phase == CRAFT:
        return job == craft_rhythm.MODE_CRAFT
    if phase == TRAIN:
        return job == "train"
    return False


def _joined(facts: Facts) -> str:
    """The phase a family joining the loop is already in, by its jobs."""
    held = {str(j or "").strip().lower() for j in facts.jobs.values()}
    if facts.errand_active or held == {jobs.TOWN_RUN}:
        return TOWN
    if held == {craft_rhythm.MODE_CRAFT}:
        return CRAFT
    if held == {"train"}:
        return TRAIN
    return GATHER


def _low(facts: Facts) -> list:
    """'Name (N)' for each member below TOWN_FREE_SLOTS free bag slots."""
    return [
        "%s (%d)" % (name, slots)
        for name, slots in sorted((facts.free_slots or {}).items())
        if slots is not None and int(slots) < TOWN_FREE_SLOTS
    ]


def _due(facts: Facts) -> list:
    return sorted(name for name, due in (facts.train_due or {}).items() if due)


def _casting(facts: Facts) -> list:
    return sorted(n for n, c in (facts.casts or {}).items() if int(c or 0) > 0)


def _stocked(facts: Facts) -> bool:
    """Every judged crafter holds READY_CASTS casts, and there is one."""
    casts = facts.casts or {}
    return bool(casts) and all(int(c or 0) >= READY_CASTS for c in casts.values())


def _after_town(facts: Facts) -> tuple:
    casting = _casting(facts)
    if casting:
        return CRAFT, "%s can cast from the bags" % ", ".join(casting)
    due = _due(facts)
    if due:
        return TRAIN, "a rank or recipe is due for %s" % ", ".join(due)
    return GATHER, "nobody can cast and nothing is due at a trainer"


def _after_craft(facts: Facts) -> tuple:
    due = _due(facts)
    if due:
        return TRAIN, "a rank or recipe is due for %s" % ", ".join(due)
    return GATHER, "nothing is due at a trainer"


def _move(state: State, facts: Facts, to: str, why: str, ask_town: str = "") -> Step:
    """A phase change, its job and its one log line."""
    job = phase_job(to, facts)
    new = State(phase=to, since=facts.now, asserted=facts.now if job else 0.0)
    line = "%s -> %s: %s" % (state.phase or "joined", to, why)
    if job:
        line += "; job %s" % job
    return Step(new, job=job, ask_town=ask_town, line=line, moved=True)


def _stay(state: State, facts: Facts) -> Step:
    """No phase change: set back a job another writer put on a member."""
    wrong = sorted(
        "%s=%s" % (name, job or "nothing")
        for name, job in (facts.jobs or {}).items()
        if not _held(state.phase, job, facts.gather_job)
    )
    job = phase_job(state.phase, facts)
    if not wrong or not job or facts.now - state.asserted < REASSERT_SECONDS:
        return Step(state)
    return Step(
        replace(state, asserted=facts.now),
        job=job,
        line="%s holds: %s found on the job column; the loop owns it, so job %s"
        % (state.phase, ", ".join(wrong), job),
    )


def _town_ask(why: str) -> str:
    return LOOP_WHY + why


def _join(state: State, facts: Facts) -> Step:
    """A family seen for the first time joins at the phase its jobs say."""
    phase = _joined(facts)
    if phase == TOWN:
        return Step(
            State(phase=TOWN, since=facts.now, town_seen=facts.errand_active),
            line="joined -> town: the family is in town (%s)"
            % (facts.errand_why or "job town run"),
            moved=True,
        )
    step = _move(state, facts, phase, "joined the loop on its current job")
    if facts.jobs and all(
        str(j or "").strip().lower() == step.job for j in facts.jobs.values()
    ):
        step = replace(step, job="", state=replace(step.state, asserted=0.0))
    return step


def _gather(state: State, facts: Facts, elapsed: float) -> Step:
    low = _low(facts)
    if low:
        why = "%s below %d free bag slots" % (", ".join(low), TOWN_FREE_SLOTS)
        return _move(state, facts, TOWN, why, _town_ask(why))
    if elapsed >= GATHER_SECONDS:
        why = "%d hours gathered; the haul goes to the bank" % (GATHER_SECONDS // 3600)
        return _move(state, facts, TOWN, why, _town_ask(why))
    if elapsed < GATHER_MIN_SECONDS or not _stocked(facts):
        return _stay(state, facts)
    ready = "every crafter holds reagents for %d casts" % READY_CASTS
    errands = sorted(set(facts.mail_waiting) | set(facts.fetch))
    if not errands:
        return _move(state, facts, CRAFT, ready)
    why = "%s, and %s have more in the mail or a bank" % (ready, ", ".join(errands))
    return _move(state, facts, TOWN, why, _town_ask(why))


def _town(state: State, facts: Facts, elapsed: float) -> Step:
    if facts.errand_active:
        return Step(replace(state, town_seen=True))
    if state.town_seen or facts.errand_ended >= state.since > 0:
        to, why = _after_town(facts)
        return _move(state, facts, to, "the town errand ended; " + why)
    if elapsed >= TOWN_START_SECONDS:
        to, why = _after_town(facts)
        late = "the town errand did not start in %d minutes; " % (
            TOWN_START_SECONDS // 60
        )
        return _move(state, facts, to, late + why)
    return Step(state, ask_town=_town_ask("the loop is in its town phase"))


def _craft_done(facts: Facts, elapsed: float) -> str:
    """Why the craft phase is over, or ''."""
    if elapsed >= CRAFT_MIN_SECONDS and not facts.casts:
        return "no crafter has a recipe whose reagents can be planned"
    if elapsed >= CRAFT_MIN_SECONDS and not _casting(facts):
        return "the reagents in the bags are spent"
    if elapsed >= CRAFT_SECONDS:
        return "%d minutes crafted" % (CRAFT_SECONDS // 60)
    return ""


def _craft(state: State, facts: Facts, elapsed: float) -> Step:
    done = _craft_done(facts, elapsed)
    if not done:
        return _stay(state, facts)
    to, why = _after_craft(facts)
    return _move(state, facts, to, "%s; %s" % (done, why))


def _train(state: State, facts: Facts, elapsed: float) -> Step:
    due = _due(facts)
    if not due:
        return _move(state, facts, GATHER, "nothing left to buy at a trainer")
    if elapsed >= TRAIN_SECONDS:
        why = "%d minutes at the trainers; %s still due, tried again next loop" % (
            TRAIN_SECONDS // 60,
            ", ".join(due),
        )
        return _move(state, facts, GATHER, why)
    return _stay(state, facts)


_PHASE_STEP = {GATHER: _gather, TOWN: _town, CRAFT: _craft, TRAIN: _train}


def decide(state: State, facts: Facts) -> Step:
    """The loop's next step for one family (or, later, one member)."""
    if facts.in_run:
        return Step(state, line="waits: a dungeon run is under way")
    if facts.queue_owns:
        return Step(state, line="waits: the campaign queue owns the job")
    if not state.phase:
        return _join(state, facts)
    if facts.errand_active and state.phase != TOWN:
        return Step(
            State(phase=TOWN, since=facts.now, town_seen=True),
            line="%s -> town: the town errand started on its own (%s)"
            % (state.phase, facts.errand_why or "no reason given"),
            moved=True,
        )
    step = _PHASE_STEP.get(state.phase)
    if step is None:
        return _move(state, facts, GATHER, "unknown phase %r" % state.phase)
    return step(state, facts, facts.now - state.since)


def line(family: str, step: Step) -> str:
    """One plain log line naming the family, or '' when there is nothing new."""
    if not step.line:
        return ""
    return "profession loop: %s: %s" % (family, step.line)
