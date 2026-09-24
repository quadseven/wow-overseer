"""Two dungeon-run decisions asked of Jev: how to recover, and what yields.

  run_recovery    a dungeon attempt ended without the party inside, and
                  mod-overseer's coordinator is RECOVERING instead of stopping
                  the campaign. It writes a request row to
                  `overseer_run_recovery` with the failure, its facts, the
                  recoveries it offers and its own heuristic's choice, and
                  waits out a backoff. This pass asks Jev which recovery to
                  apply and writes the answer back on the row; the module
                  applies it when the backoff ends. ACT by default, behind
                  RECOVERY_THRESHOLD (JEV_MODE_RUN_RECOVERY and
                  JEV_THRESHOLD_RUN_RECOVERY override both).
  staging_stall   the leader's staging errand has been taken back several
                  times in one attempt. The request carries who ended it; Jev
                  picks whether the run keeps re-arming, yields for a while, or
                  recovers now. ACT by default, behind STALL_THRESHOLD.

Below the threshold, or with no answer at all, the module's own heuristic is
written back as the answer (answered_by 'heuristic'), so the row always says
who chose. Both kinds are recorded in overseer_jev_judgment.

THE FACTS LIVE IN ONE FUNCTION, `state_for`, and it is built to be extended.
Perception inputs (movement, what a character can see) are being added to Jev
by other work; they land in `Context.perception` or through `FACT_EXTENDERS`,
and every question here picks them up without a change to this file.

AND JEV LEARNS FROM WHAT FOLLOWED. `history` is every recent recovery the
module applied, on any family, with what the next attempt did: got inside, or
failed again and why. A recovery that keeps being followed by the same failure
is visible to the next judgment, which is how these answers get better.

PURE: rows in, questions and judgments out; the only I/O is the client the
caller hands in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

import jev

KIND_RECOVERY = "run_recovery"
KIND_STALL = "staging_stall"
KINDS = (KIND_RECOVERY, KIND_STALL)

# Confidence floors. A recovery that Jev is not sure of costs one more failed
# attempt at most (the module's backoff and ceilings bound every recovery), so
# the floor sits just above an even split between the two likeliest options.
RECOVERY_THRESHOLD = 0.6
STALL_THRESHOLD = 0.65

# What each option means, in the module's own words. Only the options a row
# offers are asked about; a word not in here is never offered to Jev.
RECOVERY_CRITERIA = {
    "restage_nearer": (
        "Walk the leader toward the dungeon (its town first where one is named) "
        "with no staging clock running, and open the next attempt once he is "
        "near the door. Right when the leader was far from the door."
    ),
    "regroup": (
        "Hold the leader still until every member is back beside him, then "
        "open the next attempt. Right when members straggled far behind."
    ),
    "town_for_bags": (
        "Stand the run down so the family goes to town and empties its bags, "
        "then resume the campaign. Right only when bags are full."
    ),
    "wait_for_client": (
        "Wait until every member has a working client again. Right when a "
        "member was offline or not steerable."
    ),
    "one_copy": (
        "Walk everybody out through the reset and in together, into one copy "
        "of the dungeon. Right when the party was split across maps or copies."
    ),
    "replan": (
        "Throw away the staging point and route and plan them again. Right "
        "when the approach itself failed: a ledge, or a leader whose errand "
        "kept being taken back near the door."
    ),
    "reset_instance": (
        "Reset the instance and try the same approach again. Right when the "
        "reset failed or nothing else fits."
    ),
}

STALL_CRITERIA = {
    "keep_rearming": (
        "The run keeps the leader's errand and takes it back at once each time; "
        "whatever ended it yields. Right when the ender was a one-off inside "
        "the module."
    ),
    "run_yields": (
        "The run stops re-claiming for two minutes with its staging clock "
        "stopped, so another owner of the leader's travel can finish. Right "
        "when something outside the run keeps writing his travel."
    ),
    "recover_now": (
        "Close this attempt now and recover (restage from nearer) rather than "
        "spend the rest of the staging clock re-arming. Right when the leader "
        "is far out and keeps being stopped."
    ),
}

# Extension point for other fact sources: each is called as
# fn(request, context, state) and may add keys to `state`. Kept empty here.
FACT_EXTENDERS: list = []


@dataclass(frozen=True)
class Request:
    """One overseer_run_recovery row the module wrote and nobody answered."""

    id: int
    family: str
    leader: str
    campaign_id: int
    run_number: int
    kind: str
    attempt: int
    failure: str
    facts: str
    options: tuple
    heuristic: str
    heuristic_why: str


def request_from_row(row: dict) -> Request | None:
    """A Request, or None for a row this pass cannot ask about."""
    kind = str(row.get("kind") or "")
    if kind not in KINDS:
        return None
    criteria = RECOVERY_CRITERIA if kind == KIND_RECOVERY else STALL_CRITERIA
    options = tuple(
        o.strip()
        for o in str(row.get("options") or "").split(",")
        if o.strip() in criteria
    )
    heuristic = str(row.get("heuristic") or "")
    if heuristic not in options or len(options) < 2:
        return None
    return Request(
        id=int(row.get("id") or 0),
        family=str(row.get("family") or ""),
        leader=str(row.get("leader_name") or ""),
        campaign_id=int(row.get("campaign_id") or 0),
        run_number=int(row.get("run_number") or 0),
        kind=kind,
        attempt=int(row.get("attempt") or 0),
        failure=str(row.get("failure") or ""),
        facts=str(row.get("facts") or ""),
        options=options,
        heuristic=heuristic,
        heuristic_why=str(row.get("heuristic_why") or ""),
    )


@dataclass
class Context:
    """What the bridge can see beyond the module's own facts line.

    `events` are the family's recent overseer_dungeon_run_event rows, newest
    first; `positions` maps a member to its snapshot row; `free_slots` maps a
    member to its free bag slots; `history` is `recovery_history`'s output.
    `perception` is for movement and vision inputs added by other work.
    """

    events: list = field(default_factory=list)
    positions: dict = field(default_factory=dict)
    free_slots: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    perception: dict = field(default_factory=dict)


def recovery_history(recovery_rows: list, run_rows: list, limit: int = 12) -> list:
    """Each applied recovery with what the next attempt did.

    `recovery_rows` are applied run_recovery rows (id, family, campaign_id,
    attempt, failure, applied, applied_by, applied_at); `run_rows` are
    overseer_dungeon_run rows (campaign_id, started_at, outcome,
    ended_reason). The attempt that followed a recovery is the first run row
    of the same campaign that started at or after it was applied.
    """
    out = []
    ordered = sorted(
        (r for r in recovery_rows if r.get("applied_at") is not None),
        key=lambda r: r["applied_at"],
    )
    for rec in ordered:
        applied_at = rec.get("applied_at")
        after = [
            r
            for r in run_rows
            if r.get("campaign_id") == rec.get("campaign_id")
            and r.get("started_at") is not None
            and r.get("started_at") >= applied_at
        ]
        after.sort(key=lambda r: r.get("started_at"))
        if not after:
            then = "not known yet"
        else:
            outcome = str(after[0].get("outcome") or "")
            if outcome in (
                "staging_failed",
                "reset_failed",
                "split_failed",
                "evacuated",
            ):
                then = "failed again (%s: %s)" % (
                    outcome,
                    str(after[0].get("ended_reason") or "")[:160],
                )
            elif outcome:
                then = "got inside (%s)" % outcome
            else:
                then = "got inside, still running"
        out.append(
            {
                "family": str(rec.get("family") or ""),
                "failure": str(rec.get("failure") or "")[:200],
                "recovery": str(rec.get("applied") or ""),
                "chosen_by": str(rec.get("applied_by") or ""),
                "then": then,
            }
        )
    return out[-limit:]


def _where(row: dict) -> dict:
    return {
        "map": int(row.get("map_id") or 0),
        "zone": int(row.get("zone_id") or 0),
        "x": round(float(row.get("pos_x") or 0.0), 1),
        "y": round(float(row.get("pos_y") or 0.0), 1),
        "in_combat": bool(row.get("in_combat")),
        "group_leader": int(row.get("group_leader") or 0),
    }


def state_for(request: Request, context: Context) -> dict:
    """Everything one question is asked with. THE place to add facts."""
    count_key = (
        "failures_in_a_row" if request.kind == KIND_RECOVERY else "times_taken_back"
    )
    state = {
        "family": request.family,
        "leader": request.leader,
        "campaign": request.campaign_id,
        "run_number": request.run_number,
        count_key: request.attempt,
        "what_happened": request.failure,
        "module_facts": request.facts,
        "module_heuristic": request.heuristic,
        "module_heuristic_why": request.heuristic_why,
        "recent_timeline": [
            {
                "phase": str(e.get("phase") or ""),
                "kind": str(e.get("kind") or ""),
                "detail": str(e.get("detail") or "")[:240],
            }
            for e in context.events[:25]
        ],
        "members": {
            name: dict(
                _where(row),
                free_bag_slots=context.free_slots.get(name, "unknown"),
            )
            for name, row in sorted(context.positions.items())
        },
        "offline_or_unseen": sorted(
            n for n in context.free_slots if n not in context.positions
        ),
        "recent_recoveries_and_what_followed": list(context.history),
    }
    if context.perception:
        state["perception"] = dict(context.perception)
    for extend in FACT_EXTENDERS:
        extend(request, context, state)
    return state


def question(request: Request, context: Context):
    """(state, questions) for one request."""
    state = state_for(request, context)
    if request.kind == KIND_RECOVERY:
        criteria = {o: RECOVERY_CRITERIA[o] for o in request.options}
        instructions = (
            "A family of World of Warcraft adventurers tried to enter a dungeon "
            "together and failed before getting inside. `what_happened` is the "
            "failure, `module_facts` what the server measured, `recent_timeline` "
            "the run's own recent events (newest first), `members` where each "
            "one stands, and `recent_recoveries_and_what_followed` how earlier "
            "recoveries worked out. The campaign never stops; choose the "
            "recovery most likely to get the whole party inside on the next "
            "attempt. Do not repeat a recovery that was followed by the same "
            "failure."
        )
        return state, {"recovery": jev.choice(instructions, criteria)}
    criteria = {o: STALL_CRITERIA[o] for o in request.options}
    instructions = (
        "A family leader is walking to a dungeon door, and the errand walking "
        "him there keeps being ended by something else and taken back. "
        "`module_facts` says what ended it last and how far out he is; "
        "`recent_timeline` is the run's recent events, newest first. Choose "
        "what should yield so the family reaches the door."
    )
    return state, {"stall": jev.choice(instructions, criteria)}


_HEURISTIC = jev.HEURISTIC


@dataclass(frozen=True)
class RecoveryJudgment:
    """One recovery or stall decision, shaped for overseer_jev_judgment."""

    subject: str
    heuristic: str
    heuristic_why: str
    mode: str
    status: str
    kind: str = KIND_RECOVERY
    item_name: str = ""
    facts: str = ""
    jev: str = ""
    confidence: float | None = None
    probabilities: dict | None = None
    latency_ms: int = 0
    model: str = ""
    acted: str = _HEURISTIC
    item_guid: int = 0
    item_entry: int = 0

    @property
    def holder(self) -> str:
        return self.subject

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    @property
    def chosen(self) -> str:
        """The option the module is told to apply."""
        return (
            self.jev
            if self.acted in (jev.JEV, jev.BOTH) and self.jev
            else self.heuristic
        )

    @property
    def chosen_by(self) -> str:
        return "jev" if self.acted in (jev.JEV, jev.BOTH) and self.jev else "heuristic"

    def probabilities_json(self, limit: int = 1000) -> str:
        if not self.probabilities:
            return ""
        ranked = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        text = json.dumps({k: round(v, 4) for k, v in ranked}, separators=(",", ":"))
        return text if len(text) <= limit else ""

    def line(self) -> str:
        answer = (
            "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
            if self.jev
            else "jev=-"
        )
        return (
            "run recovery: family=%s kind=%s chose %s (by %s); heuristic=%s %s "
            "status=%s latency_ms=%d mode=%s acted=%s failure=%r"
            % (
                self.subject,
                self.kind,
                self.chosen,
                self.chosen_by,
                self.heuristic,
                answer,
                self.status,
                self.latency_ms,
                self.mode,
                self.acted,
                self.item_name,
            )
        )


def policy(kind: str, environ=None) -> jev.Policy:
    """Both kinds act by default, each behind its own floor."""
    return jev.policy(
        kind,
        environ=environ,
        default_mode=jev.ACT,
        default_threshold=RECOVERY_THRESHOLD
        if kind == KIND_RECOVERY
        else STALL_THRESHOLD,
    )


def base_judgment(request: Request, rule: jev.Policy) -> RecoveryJudgment:
    return RecoveryJudgment(
        subject=(request.family or request.leader or "?")[:12],
        heuristic=request.heuristic,
        heuristic_why=request.heuristic_why,
        mode=rule.mode,
        status="",
        kind=request.kind,
        item_name=request.failure[:120],
        facts=request.facts[:1000],
    )


async def judge(client, request: Request, context: Context, rule: jev.Policy):
    """The judgment for one request. With the kind off, or no answer, the
    heuristic's choice stands and the judgment says why."""
    base = base_judgment(request, rule)
    if rule.mode == jev.OFF:
        return replace(base, status="off")
    state, questions = question(request, context)
    qid = next(iter(questions))
    outcome = await client.ask(request.kind, state, questions, wait=2.0)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers[qid]
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=rule.acted(
            request.heuristic,
            answer.choice,
            answer.confidence,
            can_act=answer.choice in request.options,
        ),
    )
