"""One interview exchange with a shortlisted recruit, before the guild invite.

THE PURE HALF OF THE INTERVIEW STEP. Rows in, one plan out. No database, no
clock, no LLM - the same seam recruit.py keeps, and for the same reason:
every branch below is a case somebody has to be able to write a test for
without a realm running.

WHAT THIS MODULE IS NOT ALLOWED TO DECIDE, and the line is worth stating
because it is easy to cross by accident. It does NOT judge the candidate.
Who is worth asking is answered by `RecruitVerdictFor` and `RecruitShortlist`
in mod-overseer's pure layer, against the guild's real holes - and the LLM is
never asked for a verdict of any kind. The question below is DETERMINISTIC:
asking the model to write its own interview question would put
verdict-shaped language one prompt edit away. The model only answers, in
character, through the existing chat path.

WHAT IT DOES. Takes one shortlisted candidate's grounding and builds the one
guild-appropriate question to ask them. Whether the candidate is online is
the CALLER's read - a fresh `overseer_snapshot` row under the same 60s
freshness rule `_fetch_grounding` enforces - and None here is the skip
signal: the caller tries the next shortlisted name rather than blocking on
this one.

WHERE THE EXCHANGE GOES. The bridge-side caller runs the question through
the inner voice and gets back an InterviewExchange: the question plus the
reply, as data. Where that transcript is stored long-term is a separate
question from asking it, and it is out of scope here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class InterviewPlan:
    """The one question to ask one shortlisted candidate.

    `reason` IS ALWAYS SET, on a plan like on recruit.py's actions - a pass
    that asks somebody has to say why this name, the same way a pass that
    asks nobody says why not.
    """

    candidate: str
    question: str
    reason: str


@dataclass(frozen=True)
class InterviewExchange:
    """One recorded interview exchange, as data for the caller to keep.

    `question` is the deterministic question this module built; `reply` is
    what the candidate said back through the inner voice. Nothing here is a
    judgement of the candidate - `RecruitVerdictFor` stays the sole
    pass/fail gate.
    """

    candidate: str
    question: str
    reply: str
    reason: str


def build_question(
    *,
    name: str,
    level: int,
    race_name: str,
    class_name: str,
    zone: str,
) -> str:
    """The one guild-appropriate interview question, grounded in the candidate.

    DETERMINISTIC ON PURPOSE - see the module docstring. An officer's
    question: why this guild, and what the candidate brings to it. Grounded
    in level, race, class and where they were last seen, so the reply comes
    back about this character and not about guilds in the abstract.
    """
    return (
        f"What brings you to look for a guild, {name}? You're a level {level} "
        f"{race_name} {class_name}, last seen in {zone} - what are you hoping "
        "to find here, and what would you bring to it?"
    )


def plan(*, name: str, snapshot: Mapping | None) -> InterviewPlan | None:
    """The interview question for one shortlisted candidate, or None.

    `snapshot` is the candidate's grounding as the caller resolved it -
    level, race_name, class_name, zone - or None when the candidate is not
    online. None is the skip signal: the caller tries the next shortlisted
    name rather than blocking.
    """
    if snapshot is None:
        return None
    return InterviewPlan(
        candidate=name,
        question=build_question(
            name=name,
            level=snapshot["level"],
            race_name=snapshot["race_name"],
            class_name=snapshot["class_name"],
            zone=snapshot["zone"],
        ),
        reason="shortlisted and online - asking the one interview question",
    )
