"""What a class quest use row answered, and what the bridge does next.

THE ROWS. classquest.py writes `use-item-on creature:<entry> item:<entry>` and
`use-gameobject <entry>` as kind='quest' rows beside `take quest:` and
`turnin quest:` (quadseven/mod-overseer#865). The module answers a use in the
status column and in the result JSON:

  applied    outcome `progressed` (a quest counter or status moved) or `spent`
             (nothing counted, but the item was used up, a loot window opened
             or the item's cooldown started: the bridge re-reads the quest log)
  unchanged  outcome `nothing`: the use changed nothing the character could be
             read for
  error      a refusal, or `unreadable` (the character left the world). The
             result carries `reason` (the literal in `detail`) and `retry`: `never` (the row is wrong: ask someone), `elsewhere`
             (the character stands in an instance: leave and walk again) or
             `later` (too far, no target in reach, the creature dead, a fight,
             a move: wait, and walk again when the target is out of reach)

A WORLDSERVER BEFORE #865 knows neither verb. Its quest parser answers any
other command `malformed request: want take quest:<id> or turnin quest:<id>`.
That is UNSUPPORTED, and the bridge plans from classquest.Book.plain() for
WALK_UNSUPPORTED_SECONDS (guildroute), as it does for a walk row the module
does not know: every use quest is named as blocked, as it was, and nothing is
asked of the world until the window passes.

The result's `outcome` is the word to read; `verdict` is only the read-back
and says nothing for a refusal.

PURE MODULE: a row's answer in, a verdict out. No MySQL, no clock, no sleeping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import classquest

# Verdicts.
PROGRESSED = "progressed"
SPENT = "spent"
NOTHING = "nothing"
RETRY = "retry"
ELSEWHERE = "elsewhere"
NEVER = "never"
UNREADABLE = "unreadable"
UNSUPPORTED = "unsupported"
WAITING = "waiting"

# The use did something: the quest log is read again next pass.
DONE = frozenset({PROGRESSED, SPENT})

# What an older worldserver says to a quest command it cannot parse.
OLD_QUEST_PARSER = "malformed request: want take quest:"

# The module's refusal literals (mod-overseer QuestUseRefusal), for a result
# that carries no `retry`. Anything not named here is worth asking again.
NEVER_REASONS = (
    "malformed use-item-on command",
    "malformed use-gameobject command",
    "character has no bot AI",
    "that item has no spell that takes a creature target",
    "the character does not carry that item",
    "the core will not let this character use that item",
)
ELSEWHERE_REASONS = ("character is inside an instance or battleground",)
# A target out of reach: one walk toward it again may fix it.
OUT_OF_REACH = (
    "no such target within reach on this map",
    "the target is too far to use the item or object",
)
# A target that is not there yet: it respawns, so the wait is long.
TARGET_DEAD = "the creature is dead"

# Asks per step: the first and, after a wait or a walk, two more.
MAX_ATTEMPTS = 3
# Walks toward the target again within one step.
REWALKS = 1
# Seconds to wait before asking again, by what refused.
LATER_WAIT_SECONDS = 20.0
DEAD_WAIT_SECONDS = 60.0


@dataclass(frozen=True)
class UseAnswer:
    """One reading of a use row: `state`, the sentence for the log, whether to
    walk toward the target again, and the seconds to wait before asking again."""

    state: str
    said: str = ""
    rewalk: bool = False
    wait: float = 0.0


def is_use_row(command) -> bool:
    """True for a quest row that uses an item or a gameobject."""
    head = str(command or "").split(" ", 1)[0]
    return head in (classquest.USE_ITEM, classquest.USE_OBJECT, classquest.USE_HERE)


def _body(result) -> dict:
    if isinstance(result, dict):
        return result
    try:
        parsed = json.loads(result or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def unsupported(status, detail) -> bool:
    """True when this answer says the worldserver does not carry the verbs."""
    return str(status or "").strip().lower() == "error" and str(
        detail or ""
    ).startswith(OLD_QUEST_PARSER)


def _retry_word(detail, body) -> str:
    word = str(body.get("retry") or "").strip().lower()
    if word in (NEVER, ELSEWHERE, "later"):
        return word
    if detail in NEVER_REASONS:
        return NEVER
    if detail in ELSEWHERE_REASONS:
        return ELSEWHERE
    return "later"


def _applied(holder, body) -> UseAnswer:
    """An 'applied' row: the module says progressed or spent, nothing else."""
    word = str(body.get("outcome") or "").lower()
    if word == PROGRESSED:
        return UseAnswer(PROGRESSED, "%s's use moved its quest" % holder)
    if word == SPENT:
        return UseAnswer(
            SPENT, "%s's use was spent; the quest log is read again" % holder
        )
    return UseAnswer(
        UNREADABLE,
        "%s's use row read 'applied' without a reading in its result" % holder,
    )


def _refused(holder, detail, body) -> UseAnswer:
    """An 'error' row: unreadable, or a refusal with its retry word."""
    if str(body.get("outcome") or "").lower() == UNREADABLE:
        return UseAnswer(
            UNREADABLE, "%s left the world before its use could be read" % holder
        )
    retry = _retry_word(detail, body)
    why = detail or "the world refused the use and said nothing about why"
    if retry == NEVER:
        return UseAnswer(NEVER, "%s cannot do this use: %s" % (holder, why))
    if retry == ELSEWHERE:
        return UseAnswer(
            ELSEWHERE, "%s cannot use it here: %s" % (holder, why), rewalk=True
        )
    wait = DEAD_WAIT_SECONDS if detail == TARGET_DEAD else LATER_WAIT_SECONDS
    return UseAnswer(
        RETRY,
        "%s's use is refused for now: %s" % (holder, why),
        detail in OUT_OF_REACH,
        wait,
    )


def judge(holder, status, detail, result) -> UseAnswer:
    """What one use row's status, detail and result say."""
    status = str(status or "").strip().lower()
    detail = str(detail or "").strip()
    body = _body(result)
    if status in ("pending", "claimed", "verifying", ""):
        return UseAnswer(WAITING, "%s's use row has not been answered" % holder)
    if unsupported(status, detail):
        return UseAnswer(
            UNSUPPORTED,
            "this worldserver answered the use as %r, so it cannot use a quest "
            "item or object yet; use quests are named as blocked until it can" % detail,
        )
    if status == "applied":
        return _applied(holder, body)
    if status == "unchanged":
        return UseAnswer(
            NOTHING, "%s's use changed nothing: %s" % (holder, detail or "no reading")
        )
    return _refused(holder, detail, body)
