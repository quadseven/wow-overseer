"""Two council decisions asked of Jev in shadow: the dungeon and the quest (#95).

SHADOW ONLY. Both choices are made elsewhere and stay made there: the dungeon
by council._dungeon_proposal's frontier rule, the quest aim by
questbook.drive_target. Jev is asked the same question over the same options
and its answer is recorded beside the heuristic's in overseer_jev_judgment. No
act path is built for either kind, so JEV_MODE_<KIND>=act says so and runs
shadow (jev.effective_mode).

  dungeon_choice  which of the doors council.dungeon_doors allows (#204, #207)
                  the family should take next. Asked only with two or more.
  quest_pick      which of the quests questbook.drive_candidates lists the
                  family's aim should drive. This is the bridge's `drive_quest`
                  aim, not the leader's own pick inside mod-overseer's
                  DriveFamilyQuests, which the bridge cannot see or change;
                  the aim is the one seam the bridge owns. Asked only with two
                  or more.

PURE: facts in, questions and Judgments out; the only I/O is the client the
caller hands in.
"""

from __future__ import annotations

from dataclasses import replace

import jev
from jev_items import Judgment

KIND_DUNGEON = "dungeon_choice"
KIND_QUEST = "quest_pick"
KINDS = (KIND_DUNGEON, KIND_QUEST)


def policy(kind: str, environ=None) -> jev.Policy:
    """Shadow by default, and never act: no act path is built for these."""
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


def dungeon_question(doors, level_rows, completed_runs=None):
    """(state, questions) for "which dungeon next", over `doors` by keyword."""
    runs = dict(completed_runs or {})
    state = {
        "family": [
            {"name": str(r.get("name") or ""), "level": int(r.get("level") or 0)}
            for r in level_rows
        ],
        "dungeons": [
            {
                "dungeon": d.place,
                "door": d.keyword,
                "level_it_wants": d.wants,
                "ready_now": d.ready,
                "runs_already_done": int(runs.get(d.keyword, 0)),
            }
            for d in doors
        ],
    }
    criteria = {
        d.keyword: "The family runs %s next (it wants level %d, %s)."
        % (d.place, d.wants, "they are ready" if d.ready else "close enough to try")
        for d in doors
    }
    instructions = (
        "`family` is a party of World of Warcraft adventurers choosing their "
        "next dungeon run from `dungeons`, every one of which they can walk to "
        "and enter now. Choose the run that serves the whole party best: a "
        "dungeon that challenges them without overwhelming the weakest, "
        "rewards their levels with experience and gear, and is not one they "
        "have already run too often."
    )
    return state, {"dungeon": jev.choice(instructions, criteria)}


async def dungeon_shadow(client, doors, pick, level_rows, completed_runs, mode):
    """The dungeon_choice Judgment, or None when there is nothing to choose."""
    if mode == jev.OFF or pick is None or len(doors) < 2:
        return None
    weakest = min(level_rows, key=lambda r: (int(r.get("level") or 0), r.get("name")))
    base = _base(
        KIND_DUNGEON,
        str(weakest.get("name") or "?"),
        pick.keyword,
        "the hardest door the weakest member can walk into (%s)" % pick.place,
        mode,
    )
    state, questions = dungeon_question(doors, level_rows, completed_runs)
    outcome = await client.ask(KIND_DUNGEON, state, questions)
    return _judged(base, outcome, "dungeon")


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
