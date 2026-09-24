"""Three family decisions asked of Jev: the next dungeon, the leveling zone
and the quest aim (#95).

  dungeon_choice  which of the runs campaignplan.options offers a family whose
                  campaign queue has run out. At level 60 each run carries
                  what it is worth to the raid (#280): the upgrades its loot
                  tables hold for each member, the item levels expected per
                  run, the attunement or key progress, and the continent.
                  ACT by default, behind a confidence floor
                  (DUNGEON_THRESHOLD; JEV_MODE_DUNGEON_CHOICE and
                  JEV_THRESHOLD_DUNGEON_CHOICE override both): Jev's run
                  is queued when it is sure enough, campaignplan.heuristic's
                  otherwise, and on no answer at all. Asked only with two or
                  more runs to choose from.
  leveling_zone   which of the hubs levelroute.options offers a family below
                  the level cap should level at. ACT by default behind
                  ZONE_THRESHOLD, the same shape as the dungeon: Jev's hub is
                  carried out when it is sure enough, levelroute.heuristic's
                  otherwise and on no answer. Asked only with two or more.
  quest_pick      which of the quests questbook.drive_candidates lists the
                  family's aim should drive. This is the bridge's `drive_quest`
                  aim, not the leader's own pick inside mod-overseer's
                  DriveFamilyQuests, which the bridge cannot see or change;
                  the aim is the one seam the bridge owns. SHADOW only: no act
                  path is built, so JEV_MODE_QUEST_PICK=act says so and runs
                  shadow (jev.effective_mode). Asked only with two or more.

Both are recorded in overseer_jev_judgment beside the heuristic's answer,
with `acted` saying which one the world got.

PURE: facts in, questions and Judgments out; the only I/O is the client the
caller hands in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import campaignplan
import jev
import levelroute
import situation
from jev_items import Judgment

KIND_DUNGEON = "dungeon_choice"
KIND_ZONE = levelroute.KIND
KIND_QUEST = "quest_pick"
KINDS = (KIND_DUNGEON, KIND_ZONE, KIND_QUEST)

# The dungeon's confidence floor. The shadow record's answers ran 0.76 to
# 0.79 and agreed with the heuristic every time, so 0.7 lets a confident
# answer act without letting a guess do so.
DUNGEON_THRESHOLD = 0.7

# The leveling zone's floor: the dungeon's, for the same reason. A family sent
# to the wrong hub walks for minutes; a guess must not do that.
ZONE_THRESHOLD = 0.7


def policy(kind: str, environ=None) -> jev.Policy:
    """The dungeon and the leveling zone act by default at their thresholds;
    the quest aim is shadow only, because no act path is built for it."""
    if kind in (KIND_DUNGEON, KIND_ZONE):
        return jev.policy(
            kind,
            environ=environ,
            default_mode=jev.ACT,
            default_threshold=DUNGEON_THRESHOLD
            if kind == KIND_DUNGEON
            else ZONE_THRESHOLD,
        )
    return jev.policy(kind, environ=environ, act_supported=False)


def _judged(base: Judgment, outcome: jev.Outcome, qid: str) -> Judgment:
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
        acted=jev.HEURISTIC,
    )


def _base(kind, subject, heuristic, why, mode) -> Judgment:
    return Judgment(
        kind=kind,
        subject=subject,
        holder=subject,
        item_guid=0,
        item_entry=0,
        item_name="",
        heuristic=heuristic,
        heuristic_why=why,
        mode=mode,
        status="",
        acted=jev.HEURISTIC,
    )


# ---------------------------------------------------------------------------
# THE DUNGEON


# Read before the class: its `jev` field shadows the module in the class body.
_HEURISTIC = jev.HEURISTIC


@dataclass(frozen=True)
class DungeonJudgment:
    """One dungeon choice, shaped for overseer_jev_judgment.

    The columns jev_items.Judgment fills, plus `facts`: what the question was
    asked with, so the record shows why a run was queued. `item_name` carries
    why the planner was asked now.
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
    kind: str = KIND_DUNGEON
    item_guid: int = 0
    item_entry: int = 0
    prefix: str = "planner"

    @property
    def holder(self) -> str:
        return self.subject

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    @property
    def chosen(self) -> str:
        """The run the world gets: Jev's where it acted, the heuristic's else."""
        return self.jev if self.acted == jev.JEV else self.heuristic

    def probabilities_json(self, limit: int = 1000) -> str:
        if not self.probabilities:
            return ""
        ranked = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        text = json.dumps({k: round(v, 4) for k, v in ranked}, separators=(",", ":"))
        return text if len(text) <= limit else ""

    def line(self) -> str:
        """One structured log line: who chose which run, and from what."""
        answer = (
            "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
            if self.jev
            else "jev=-"
        )
        return (
            "%s: family=%s chose %s; kind=%s heuristic=%s %s status=%s "
            "latency_ms=%d mode=%s acted=%s why_now=%r facts=%r"
            % (
                self.prefix,
                self.subject,
                self.chosen,
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


def _unknown(value):
    return "unknown" if value is None else value


def dungeon_question(facts, opts, where=None):
    """(state, questions) for "which dungeon next", over campaignplan Options.

    `where` is the family's situation.Situation, or None. With one, each run
    says how far its door is from the leader, and the state carries the
    movement picture; without one the question is exactly as it was.
    """
    gear = facts.gear or {}
    state = {
        "family": [
            {
                "name": str(r.get("name") or ""),
                "level": int(r.get("level") or 0),
                "worn_item_level": _unknown(gear.get(str(r.get("name")), (None,))[0]),
                "empty_gear_slots": _unknown(
                    gear.get(str(r.get("name")), (None, None))[1]
                ),
            }
            for r in facts.level_rows
        ],
        "dungeons": [
            {
                "door": o.keyword,
                "dungeon": o.place,
                "levels": "%d to %d" % (o.floor, o.ceiling),
                "weakest_member_ready": o.ready,
                "completed_runs": o.done,
                "failed_attempts": o.failed,
                "runs_it_would_be_queued_for": o.runs,
                "open_quests": _unknown(o.quests),
                "boss_gear_item_level": _unknown(o.loot_level),
                "members_whose_gear_is_below_it": list(o.below),
                "expected_item_levels_gained_per_run": _unknown(o.expected),
                "upgrades_per_member": [g.line for g in o.gains] or "unknown",
                "raid_progress": o.progress or "none",
                "continent": o.continent or "unknown",
                "needs_a_continent_crossing": o.crossing,
                **(
                    {
                        "yards_from_the_leader_to_its_door": where.yards_to_door(
                            o.keyword
                        )
                    }
                    if where is not None
                    else {}
                ),
            }
            for o in opts
        ],
    }
    if where is not None:
        state["situation"] = where.state()
    criteria = {
        o.keyword: "The family runs %s next, %d times (levels %d to %d)."
        % (o.place, o.runs, o.floor, o.ceiling)
        for o in opts
    }
    instructions = (
        "`family` is a party of World of Warcraft adventurers whose list of "
        "dungeon runs is empty. `dungeons` is every dungeon they can walk to "
        "and enter now: the levels it suits, how often they have completed it "
        "and failed at it, how many runs it would be queued for, the quests it "
        "still holds for them, and how its bosses' gear compares with what "
        "they wear. At level 60 they are gearing for their guild's first "
        "Molten Core raid, the way a raid guild does it: each dungeon lists "
        "the upgrades its loot tables hold for each member against what they "
        "wear (with drop chances), the item levels the family should gain per "
        "run summed over every member's slots, the raid progress a run gives "
        "(the Molten Core attunement, the Upper Blackrock Spire key), and "
        "whether it needs a continent crossing. Choose the dungeon a sensible group would run next: one "
        "that suits the weakest member's level, levels and gears the party, "
        "moves the raid's attunement or key along when it can, finishes open "
        "quests, does not cross a continent for little, and is not one they "
        "have run to exhaustion or keep failing at."
    )
    if where is not None:
        instructions += (
            " A door on another continent, or far away while the family is "
            "scattered, stuck or dying, costs the group a long trip first."
            + situation.INSTRUCTION
        )
    return state, {"dungeon": jev.choice(instructions, criteria)}


def facts_line(facts, opts, where=None) -> str:
    """The question's facts in one line for the record, at most 1000 chars."""
    who, level = facts.weakest
    parts = ["weakest %s %d" % (who, level)]
    for o in opts:
        parts.append(
            "%s %d-%d done %d/%d failed %d quests %s loot %s below %d "
            "exp %s prog %d%s"
            % (
                o.keyword,
                o.floor,
                o.ceiling,
                o.done,
                o.target,
                o.failed,
                _unknown(o.quests),
                _unknown(o.loot_level),
                len(o.below),
                _unknown(o.expected),
                o.progress_rank,
                " cross" if o.crossing else "",
            )
        )
    line = "; ".join(parts)
    if where is not None:
        line += " | situation: " + where.line()
    return line[:1000]


async def dungeon_ask(client, facts, opts, pick, rule, why_now: str = "", where=None):
    """The dungeon_choice judgment, acted on per `rule`, or None when there is
    nothing to ask: the kind is off, or there is one run or none."""
    if rule.mode == jev.OFF or pick is None or len(opts) < 2:
        return None
    base = DungeonJudgment(
        subject=str(facts.family or facts.weakest[0] or "?"),
        heuristic=pick.keyword,
        heuristic_why=campaignplan.heuristic_why(pick),
        mode=rule.mode,
        status="",
        item_name=why_now,
        facts=facts_line(facts, opts, where),
    )
    state, questions = dungeon_question(facts, opts, where)
    outcome = await client.ask(KIND_DUNGEON, state, questions)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["dungeon"]
    offered = {o.keyword for o in opts}
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=rule.acted(
            pick.keyword,
            answer.choice,
            answer.confidence,
            can_act=answer.choice in offered,
        ),
    )


def dungeon_carried(opts, pick, judgment):
    """The Option to queue: Jev's where its answer acted, `pick` otherwise."""
    if judgment is None or judgment.acted != jev.JEV:
        return pick
    return next((o for o in opts if o.keyword == judgment.jev), pick)


# ---------------------------------------------------------------------------
# THE LEVELING ZONE


def zone_question(facts, opts):
    """(state, questions) for "where does the family level next", over
    levelroute Options."""
    gear = facts.gear or {}
    who, level = facts.weakest
    state = {
        "weakest_member": {"name": who, "level": level},
        "family": [
            {
                "name": str(m.get("name") or ""),
                "level": int(m.get("level") or 0),
                "standing_in": levelroute.zone_name(
                    (facts.zones or {}).get(str(m.get("name")), 0)
                ),
                "worn_item_level": _unknown(gear.get(str(m.get("name")), (None,))[0]),
            }
            for m in facts.members
        ],
        "zones": [
            {
                "zone": o.zone,
                "hub": o.hub,
                "quest_levels": "%d to %d" % (o.floor, o.ceiling),
                "weakest_member_ready": o.ready,
                "open_quests_for_the_family": o.open,
                "quests_the_family_has_done_there": o.done,
                "quests_there_somebody_holds": o.held,
                "quests_there_everyone_holds": o.held_by_all,
                "hostile_spawns_near_the_hub": o.hostile,
                "of_them_five_or_more_levels_above_the_weakest": o.above,
                "hostile_elites_near_the_hub": o.elites,
                "enemy_faction_towns_in_the_zone": list(o.towns),
                "family_deaths_there_in_the_last_day": _unknown(o.deaths),
                "yards_from_the_leader": _unknown(o.yards),
                "the_family_is_there_now": o.here,
            }
            for o in opts
        ],
    }
    criteria = {
        o.key: "The family levels in %s from %s next (quests %d to %d)."
        % (o.zone, o.hub, o.floor, o.ceiling)
        for o in opts
    }
    instructions = (
        "`family` is a party of World of Warcraft adventurers who level "
        "together, and `zones` is every quest hub of their faction they can "
        "walk to now: the levels its quests run at, how many quests are left "
        "there that all of them can take, what they have already done or "
        "carry there, how dangerous it is near the hub for the weakest member "
        "(monsters far above them, elites, towns of the enemy faction whose "
        "guards kill them), how often the family died there in the last day, "
        "and how far away it is. Choose the hub a sensible group of players "
        "would level at next: one the weakest member can survive, with plenty "
        "of quests they can do together, in level order, and not one where "
        "they keep dying."
    )
    return state, {"zone": jev.choice(instructions, criteria)}


def zone_facts_line(facts, opts) -> str:
    """The question's facts in one line for the record, at most 1000 chars."""
    who, level = facts.weakest
    parts = ["weakest %s %d" % (who, level)]
    for o in opts:
        parts.append(
            "%s %d-%d open %d done %d held %d/%d above %d/%d elites %d towns %d "
            "deaths %s yards %s"
            % (
                o.key,
                o.floor,
                o.ceiling,
                o.open,
                o.done,
                o.held_by_all,
                o.held,
                o.above,
                o.hostile,
                o.elites,
                len(o.towns),
                _unknown(o.deaths),
                _unknown(o.yards),
            )
        )
    return "; ".join(parts)[:1000]


async def zone_ask(client, facts, opts, pick, rule, why_now: str = ""):
    """The leveling_zone judgment, acted on per `rule`, or None when there is
    nothing to ask: the kind is off, or there is one hub or none."""
    if rule.mode == jev.OFF or pick is None or len(opts) < 2:
        return None
    base = DungeonJudgment(
        subject=str(facts.family or facts.weakest[0] or "?"),
        heuristic=pick.key,
        heuristic_why=levelroute.heuristic_why(pick),
        mode=rule.mode,
        status="",
        item_name=why_now,
        facts=zone_facts_line(facts, opts),
        kind=KIND_ZONE,
        prefix="levelroute",
    )
    state, questions = zone_question(facts, opts)
    outcome = await client.ask(KIND_ZONE, state, questions)
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers["zone"]
    offered = {o.key for o in opts}
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
        acted=rule.acted(
            pick.key,
            answer.choice,
            answer.confidence,
            can_act=answer.choice in offered,
        ),
    )


def zone_carried(opts, pick, judgment):
    """The Option to carry out: Jev's where its answer acted, `pick` otherwise."""
    if judgment is None or judgment.acted != jev.JEV:
        return pick
    return next((o for o in opts if o.key == judgment.jev), pick)


# ---------------------------------------------------------------------------
# THE QUEST AIM


def quest_option(quest_id: int) -> str:
    return "q%d" % int(quest_id)


def quest_question(candidates, beneficiary: str, held: dict, levels: dict):
    """(state, questions) for "which quest should the aim drive"."""
    holders = {
        q.id: sorted(n for n, ids in held.items() if q.id in set(ids))
        for q in candidates
    }
    state = {
        "beneficiary": beneficiary,
        "family": [{"name": n, "level": int(levels.get(n, 0))} for n in sorted(held)],
        "quests": [
            {
                "quest": q.title or "quest %d" % q.id,
                "quest_level": q.quest_level,
                "held_by": holders[q.id],
            }
            for q in candidates
        ],
    }
    criteria = {
        quest_option(q.id): "The family works on %s next."
        % (q.title or "quest %d" % q.id)
        for q in candidates
    }
    instructions = (
        "`family` are World of Warcraft adventurers who quest together, and "
        "`beneficiary` is the one the family agreed to help. Every quest in "
        "`quests` is in the beneficiary's log and held by the members named. "
        "Choose the quest that helps the beneficiary most and that the family "
        "can most sensibly work on together now."
    )
    return state, {"quest": jev.choice(instructions, criteria)}


async def quest_shadow(client, candidates, chosen, beneficiary, held, levels, mode):
    """The quest_pick Judgment, or None when there is nothing to choose."""
    if mode == jev.OFF or not chosen or len(candidates) < 2:
        return None
    base = _base(
        KIND_QUEST,
        beneficiary or "?",
        quest_option(chosen),
        "the quest the council named if held, else the first on the "
        "beneficiary's catch-up plan",
        mode,
    )
    state, questions = quest_question(candidates, beneficiary, held, levels)
    outcome = await client.ask(KIND_QUEST, state, questions)
    return _judged(base, outcome, "quest")
