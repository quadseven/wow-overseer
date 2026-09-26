"""What the family is doing, chosen by Jev from what the module can carry out.

WHY THIS EXISTS. The operator watched the Alliance leader walk in stutter
steps and asked whether Jev was being used to the maximum. It was not: Jev
decided coarse things (which dungeon, which activity) while six of
mod-overseer's own rules took turns steering the leader, each on its own
poll. mod-overseer now gives each family leader one movement owner, an intent
book (mod-overseer#722), and publishes it in `overseer_family_intent`: what
holds the leader now, for how long, and every request its rules made in the
last 75 seconds ("on the table"). This kind lets Jev choose among those.

WHAT JEV IS OFFERED. Exactly the requests on the table the module could carry
out now, one option each, named `<kind>` or `<kind>:<target>`:

  quest               carry on with the quest drive
  economy:<npc>       a maintenance walk (vendor, repair, bank, supplies)
  errand:<npc>        a walk to a named NPC in town
  respec              a walk to the class trainer for a talent reset
  training:<npc>      the family walks to a member's trainer
  regroup:<member>    the leader holds still for a member walking back
  fetch:<member>      the leader walks back for a member held far away
  hearth:<inn>        the family's trip home

The campaign's dungeon run and an operator's order are never offered and never
asked about: they come first in the module whatever Jev says, and while
either holds the leader this kind stays silent.

THE HEURISTIC IS THE MODULE'S OWN STATIC ORDER: the highest-ranked request on
the table, which is what the book grants when nobody picks. Jev's answer is
carried out only when it differs, in act mode, above DEFAULT_THRESHOLD
(JEV_MODE_FAMILY_INTENT / JEV_THRESHOLD_FAMILY_INTENT override both): the
bridge writes it into the row's `chosen_*` columns for PICK_SECONDS, and the
module then ranks that request just below the run and the operator. Below the
threshold, or with no answer, the static order stands, and a pick the latest
judgment no longer supports is cleared.

WHEN IT IS ASKED. When the table or the current intent changes (an arrival, a
death, a failure, a new request - each shows up there), at most every
EVENT_SECONDS, and otherwise every ASK_SECONDS while there is a real choice
(two or more options).

WHAT JEV SEES THAT IT DID NOT BEFORE. The low-confidence movement judgments
asked about "goal banker ?" with no distance and could not see what the
module was doing with a far member. The row carries the leader's distance to
what his column resolved to (`goal_yards`) and each member's state as the
module holds it (walking back, held too far to walk, held off a deadly walk,
following) with its yards from the leader.

PURE: facts in, questions and judgments out; the only I/O is the client the
caller hands in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

import jev
import situation

KIND = "family_intent"
DEFAULT_THRESHOLD = 0.7
SOURCE = "overseer:family_intent"

# The module's book, lowest rank first (OverseerDecisions::LeaderIntentKind).
RANKS = (
    "none",
    "quest",
    "economy",
    "errand",
    "respec",
    "training",
    "regroup",
    "fetch",
    "hearth",
    "dungeon",
    "operator",
)
CHOOSABLE = frozenset(RANKS[1:9])
# While one of these holds the leader, nothing here is asked.
ALWAYS_FIRST = frozenset({"dungeon", "operator"})

# A row the module has not refreshed for this long is not a picture of now.
FRESH_SECONDS = 120
# An event asks at most this often; with no event, this often while a choice
# stands.
EVENT_SECONDS = 45.0
ASK_SECONDS = 300.0
# How long the module honours a pick (the row's chosen_until).
PICK_SECONDS = 600
# jev option ids are capped at 40 characters (jev.py).
OPTION_MAX = 40

MEANINGS = {
    "quest": "Carry on with the family's quests: the leader goes where the quest "
    "takes him and the family follows.",
    "economy": "The leader walks to the %s for the family's upkeep (selling, "
    "repairs, the bank, supplies) and the family follows.",
    "errand": "The leader walks to the %s in town and the family follows.",
    "respec": "The leader walks to his class trainer to reset his talents.",
    "training": "The leader walks the family to the trainer %s so a member can "
    "learn what it has earned.",
    "regroup": "The leader holds still until %s, who is walking back, catches up.",
    "fetch": "The leader walks back for %s, who cannot come back alone, and the "
    "family comes with him.",
    "hearth": "The family goes home to its inn.",
}


def policy(environ=None) -> jev.Policy:
    return jev.policy(
        KIND,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=DEFAULT_THRESHOLD,
    )


def rank(kind: str) -> int:
    try:
        return RANKS.index(kind)
    except ValueError:
        return 0


@dataclass(frozen=True)
class Ask:
    """One request on the module's table."""

    kind: str
    owner: str
    target: str = ""

    @property
    def option(self) -> str:
        text = self.kind if not self.target else "%s:%s" % (self.kind, self.target)
        return text[:OPTION_MAX]


@dataclass(frozen=True)
class Member:
    name: str
    state: str
    yards: str


@dataclass(frozen=True)
class Row:
    """One leader's row of overseer_family_intent, as read this cycle."""

    leader: str
    family: str = ""
    current_kind: str = "none"
    current_owner: str = ""
    current_target: str = ""
    current_for: int | None = None
    table: tuple = ()
    goal_yards: int | None = None
    members: tuple = ()
    module_age: int | None = None
    chosen_kind: str = ""
    chosen_target: str = ""
    chosen_by: str = ""
    changes: int = 0


def parse_table(text) -> tuple:
    """`kind|owner|target` lines into Asks, in the module's order."""
    out = []
    for line in str(text or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) < 2 or not parts[0].strip():
            continue
        out.append(
            Ask(
                parts[0].strip(),
                parts[1].strip(),
                (parts[2] if len(parts) > 2 else "").strip(),
            )
        )
    return tuple(out)


def parse_members(text) -> tuple:
    """`name|state|yards` lines into Members."""
    out = []
    for line in str(text or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) < 2 or not parts[0].strip():
            continue
        out.append(
            Member(
                parts[0].strip(),
                parts[1].strip(),
                (parts[2] if len(parts) > 2 else "").strip(),
            )
        )
    return tuple(out)


def _int_or_none(value):
    return None if value is None else int(value)


def row_from_db(r: dict) -> Row:
    """A Row from one SELECT of the table (see the bridge's reader)."""
    return Row(
        leader=str(r.get("leader_name") or ""),
        family=str(r.get("family") or ""),
        current_kind=str(r.get("current_kind") or "none"),
        current_owner=str(r.get("current_owner") or ""),
        current_target=str(r.get("current_target") or ""),
        current_for=_int_or_none(r.get("current_for")),
        table=parse_table(r.get("on_the_table")),
        goal_yards=_int_or_none(r.get("goal_yards")),
        members=parse_members(r.get("members_state")),
        module_age=_int_or_none(r.get("module_age")),
        chosen_kind=str(r.get("chosen_kind") or ""),
        chosen_target=str(r.get("chosen_target") or ""),
        chosen_by=str(r.get("chosen_by") or ""),
        changes=int(r.get("changes") or 0),
    )


@dataclass(frozen=True)
class Facts:
    """One family's intent row and, when readable, its movement picture."""

    family: str
    row: Row
    where: situation.Situation | None = None
    deaths: int = 0
    extra: dict = field(default_factory=dict)


def choosable(f: Facts) -> list:
    """The table's requests Jev may choose between, highest static rank first,
    one per option id."""
    seen = set()
    out = []
    ranked = sorted(
        (a for a in f.row.table if a.kind in CHOOSABLE),
        key=lambda a: (-rank(a.kind), a.owner, a.target),
    )
    for a in ranked:
        if a.option in seen:
            continue
        seen.add(a.option)
        out.append(a)
    return out


def _member(f: Facts, name: str) -> Member | None:
    return next((m for m in f.row.members if m.name == name), None)


def _meaning(f: Facts, a: Ask) -> str:
    text = MEANINGS.get(a.kind, "")
    if "%s" in text:
        text = text % (a.target or "one of them")
    if a.kind in ("regroup", "fetch") and a.target:
        m = _member(f, a.target)
        if m is not None:
            text += " %s is %s, %s yards from the leader." % (m.name, m.state, m.yards)
    if a.kind == f.row.current_kind and a.target == f.row.current_target:
        text += " This is what the leader is doing now."
    return text


def options(f: Facts) -> dict:
    """option -> what it means, for this family now."""
    return {a.option: _meaning(f, a) for a in choosable(f)}


def heuristic(f: Facts) -> tuple:
    """The module's static order: the highest-ranked request. (answer, why)."""
    asks = choosable(f)
    if not asks:
        return "", "nothing on the table"
    top = asks[0]
    return top.option, "the module's static order ranks %s by %s highest" % (
        top.kind,
        top.owner,
    )


def signature(f: Facts) -> str:
    """What has to change for this to be a new question: the current intent,
    the options on the table, and the family's deaths."""
    return "|".join(
        [
            f.row.current_kind,
            f.row.current_target,
            ",".join(sorted(options(f))),
            str(f.deaths),
        ]
    )


def due(f: Facts, last_signature: str, last_asked: float, now: float) -> bool:
    """Is there a question worth asking now?"""
    if f.row.module_age is None or f.row.module_age > FRESH_SECONDS:
        return False
    if f.row.current_kind in ALWAYS_FIRST:
        return False
    if len(options(f)) < 2:
        return False
    since = now - last_asked
    if signature(f) != last_signature:
        return since >= EVENT_SECONDS
    return since >= ASK_SECONDS


def question(f: Facts, offered: dict):
    """(state, questions) for "what does the family do now"."""
    doing = {"intent": f.row.current_kind}
    if f.row.current_kind != "none":
        doing["asked_by"] = f.row.current_owner
        if f.row.current_target:
            doing["target"] = f.row.current_target
        if f.row.current_for is not None:
            doing["for_seconds"] = f.row.current_for
    if f.row.goal_yards is not None:
        doing["leader_yards_from_his_errand"] = f.row.goal_yards
    state = {
        "family": f.family,
        "leader": f.row.leader,
        "doing_now": doing,
        "members": [
            {"name": m.name, "state": m.state, "yards_from_leader": m.yards}
            for m in f.row.members
        ],
    }
    if f.where is not None:
        state["situation"] = f.where.state()
    instructions = (
        "`family` is a group of World of Warcraft (3.3.5a) adventurers who play "
        "together the way a group of real human players does, following their "
        "leader. Choose what the leader does next, as a sensible human party "
        "leader would. People do not change course without a reason: a walk "
        "that is under way and closing on its goal is usually finished first, "
        "and turning back and forth is what looks least human. Wait for a "
        "member who is walking back and not far; go back for one who cannot "
        "come back alone; run town errands when bags or gear need them; "
        "otherwise carry on with the quests. `doing_now` is what the leader is "
        "doing, and each member's `state` is what is being done with them."
        + situation.INSTRUCTION
    )
    return state, {"intent": jev.choice(instructions, dict(offered))}


def pick_of(option: str) -> tuple:
    """(kind, target) for the row's chosen_* columns."""
    kind, _, target = str(option or "").partition(":")
    return kind, target


# Read before the class: its `jev` field shadows the module in the class body.
_HEURISTIC = jev.HEURISTIC


@dataclass(frozen=True)
class Judgment:
    """One intent choice, shaped for overseer_jev_judgment."""

    subject: str
    holder: str
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
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    def probabilities_json(self, limit: int = 1000) -> str:
        if not self.probabilities:
            return ""
        ranked = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        text = json.dumps({k: round(v, 4) for k, v in ranked}, separators=(",", ":"))
        return text if len(text) <= limit else ""

    @property
    def pick(self) -> str:
        """The option to write as the family's pick, or "" for none."""
        return self.jev if self.acted == jev.JEV else ""

    def line(self) -> str:
        answer = (
            "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
            if self.jev
            else "jev=-"
        )
        chose = (
            "Jev picks %s" % self.jev
            if self.acted == jev.JEV
            else "the module's order stands (%s)" % self.heuristic
        )
        return (
            "family intent: family=%s leader=%s %s; heuristic=%s %s status=%s "
            "latency_ms=%d mode=%s acted=%s now=%r facts=%r"
            % (
                self.subject,
                self.holder,
                chose,
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


def facts_line(f: Facts, limit: int = 1000) -> str:
    """The record's facts column: what the question carried, in one line."""
    parts = [
        "doing %s%s"
        % (
            f.row.current_kind,
            (" " + f.row.current_target) if f.row.current_target else "",
        )
    ]
    if f.row.goal_yards is not None:
        parts.append("errand %d yd" % f.row.goal_yards)
    parts.append("table " + ", ".join(options(f)))
    held = [
        "%s %s %s" % (m.name, m.state, m.yards)
        for m in f.row.members
        if m.state != "following"
    ]
    if held:
        parts.append("members " + "; ".join(held))
    if f.where is not None:
        parts.append(f.where.line(300))
    return "; ".join(parts)[:limit]


async def ask(client, f: Facts, rule: jev.Policy) -> Judgment | None:
    """Ask Jev what the family does now; None when there is nothing to ask."""
    if rule.mode == jev.OFF:
        return None
    offered = options(f)
    if len(offered) < 2 or f.row.current_kind in ALWAYS_FIRST:
        return None
    current, heuristic_why = heuristic(f)
    base = Judgment(
        subject=f.family,
        holder=f.row.leader,
        heuristic=current,
        heuristic_why=heuristic_why,
        mode=rule.mode,
        status="",
        item_name=("%s %s" % (f.row.current_kind, f.row.current_target)).strip()[:120],
        facts=facts_line(f),
    )
    state, questions = question(f, offered)
    outcome = await client.ask(KIND, state, questions)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["intent"]
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
