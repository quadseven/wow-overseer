"""What the family is trying to do RIGHT NOW - the RimWorld-style schedule.

infra#2834. Evan's own words: "i should be able to be like, its farming time,
sort of like rim world job schedule times, they should quest, farm, dungeon,
level, grind, try to get specific gear from something, etc". Everything the
epic had built before this (quest aims, turn-ins, cohesion, travel, trades) is
about whether a single behaviour works. None of it says WHAT the family should
currently be doing, which is the layer this module names.

WHAT SHIPS IN THIS PASS AND WHAT DOES NOT. `MODES` names the whole vocabulary
Evan asked for, because a schedule with one slot is not a schedule and a
person reading this file should see the shape of the thing being built. But
only `quest` is wired to an actual behaviour change (mod_overseer.cpp's
DriveQuests gate) - see IMPLEMENTED. Every other mode is a name the roster
will accept and remember, and the one thing setting it does today is turn OFF
the quest drive, honestly, with nothing yet turned on in its place. Building
farm/dungeon/grind/etc is the follow-up list in the PR body, not code here
pretending to be finished.

THE FAMILY, NOT THE CHARACTER. A quest AIM (goals.py, drive_quest) can differ
per character because they can each hold a different quest and still travel
together - the traveller carries them all. A JOB cannot: mod-overseer gates
`new rpg` to the leader alone (mod_overseer.cpp, "ONLY THE TRAVELLER"), so a
mode that told Grug to farm while Ugga kept questing would be independent aims
on multiple characters again - the exact 937-yard scatter of infra#2812, just
one layer up. So a job order is FAMILY-WIDE by construction: `core.JobDirective`
carries one mode with no per-character target, and the bridge writes it onto
every enabled roster row in one pass (see bridge._set_job).

PURE MODULE, same seam as travel.py: no MySQL, no Discord, no LLM. Vocabulary
and parsing in, a canonical mode string or None out.
"""
from __future__ import annotations

import re

# Canonical mode -> what it means, in the vocabulary Evan named plus what he
# said he was probably missing. Order is the order he named them in, which is
# also a reasonable build order.
MODES = {
    "quest": "follow the quest log - what the family does today",
    "farm": "gather deliberately for a named material, not opportunistically",
    "dungeon": "run an instance, tank bot leading (mod-dungeon-clear)",
    "grind": "kill things for experience, no objective (Evan's 'level / grind')",
    "gear hunt": "target a specific item from a specific source (infra#2797)",
    "craft": "level a profession, work a queue of things the family needs",
    "town run": "vendor, repair, restock, mail (needs infra#2783)",
    "train": "learn what is available - professions and class (infra#2757, #2782)",
    "rest": "hearth, inn, log off gracefully",
    "bank": "consolidate and hand off materials to whoever can use them (infra#2830)",
    "reputation": "grind faction standing",
    "guild business": "charter signatures, tabard, guild bank (infra#2831)",
}

# The only mode that changes behaviour in this pass. Every other key in MODES
# is accepted, stored, and said back honestly as "not built yet" - see
# `describe`. Kept as its own constant, not inferred from a "the code exists"
# check, so extending mod_overseer.cpp's gate is a one-line change here too:
# forgetting to widen this after wiring a new mode fails LOUD (test_jobs.py
# checks every MODES key against this set explicitly, not just 'quest').
IMPLEMENTED = frozenset({"quest"})

# The state every character starts in and returns to when nobody has an
# opinion. Matches overseer_roster.job's column default (migration
# 2026_08_26_01_overseer_roster_job.sql) - the two must agree, because a
# reader that defaults one way and a schema that defaults another is a silent
# behaviour change waiting for whichever one gets edited first.
DEFAULT = "quest"

# overseer_roster.job is VARCHAR(20). "guild business" (14 chars) is the
# longest entry in MODES; enforced here rather than only discovered as a
# truncated column, same discipline as travel.COLUMN_WIDTH.
COLUMN_WIDTH = 20

# How people actually say it, folded onto the canonical key. Deliberately
# includes Evan's own phrase from the issue ("its farming time") verbatim,
# because a recognizer that requires the formal noun and misses the sentence
# that prompted the whole epic would be a design that forgot its own ticket.
ALIASES = {
    "questing": "quest",
    "quests": "quest",
    "farming": "farm",
    "farming time": "farm",
    "gathering": "farm",
    "dungeons": "dungeon",
    "dungeon run": "dungeon",
    "dungeon clear": "dungeon",
    "leveling": "grind",
    "levelling": "grind",
    "level": "grind",
    "grinding": "grind",
    "xp": "grind",
    "gear": "gear hunt",
    "gearing": "gear hunt",
    "loot run": "gear hunt",
    "crafting": "craft",
    "professions": "craft",
    "town": "town run",
    "errands": "town run",
    "training": "train",
    "resting": "rest",
    "logging off": "rest",
    "banking": "bank",
    "sorting": "bank",
    "rep": "reputation",
    "reputation grind": "reputation",
    "guild": "guild business",
    "charter": "guild business",
}

# ALIASES ONLY, deliberately not MODES too. A bare canonical name like
# "quest", "grind", "rest", "bank" or "train" is an ordinary English word a
# person uses without giving an order - "Grug just finished a quest" must
# not become an order to stop questing. ALIASES is the hand-curated set of
# phrasings that actually sound like an instruction ("farming time",
# "questing", "time to grind"); the explicit "job <mode>" form (_explicit,
# below) is still the only way to name a bare mode word directly.
#
# Longest phrase first, so "farming time" matches whole rather than a
# shorter alias that happens to be a substring of it (there is none today;
# the ordering is the guarantee, not an accident of dict construction).
_PHRASES = tuple(sorted(ALIASES, key=len, reverse=True))
_PHRASE_RES = {p: re.compile(r"\b" + re.escape(p) + r"\b") for p in _PHRASES}


def resolve(text: str | None) -> str | None:
    """The canonical mode `text` names, or None.

    Accepts an exact MODES key or a known alias, whitespace- and
    case-folded - the same contract as travel.resolve, and for the same
    reason: this is fed by chat, and "that is not a mode" is an ordinary
    answer, not an error.
    """
    if text is None:
        return None
    cleaned = " ".join(str(text).strip().lower().split())
    if not cleaned:
        return None
    if cleaned in MODES:
        return cleaned
    return ALIASES.get(cleaned)


# "job <mode>" is the canonical, unambiguous form - it is also literally what
# gets delivered as the overseer_command row (kind='job', command=<mode>), so
# a person typing it is typing exactly what mod-overseer will read.
def _explicit(text: str) -> str | None:
    cleaned = " ".join(text.strip().lower().split())
    if not cleaned.startswith("job"):
        return None
    rest = cleaned[len("job"):].strip(" :=")
    return resolve(rest) if rest else None


def parse_order(text: str) -> str | None:
    """A mode order somewhere in free text, or None.

    Two shapes: the explicit "job <mode>" form, and Evan's natural register -
    "it's farming time", "time to grind" - matched as a whole known phrase
    inside the sentence. Deliberately NOT "any word in MODES appears
    anywhere": that would fire on "quest" inside an ordinary sentence about
    quests and turn every mention into an order. A phrase match is bounded by
    what ALIASES and MODES actually declare, so the vocabulary this accepts
    is exactly the vocabulary a person can read in this file.
    """
    if not text:
        return None
    explicit = _explicit(text)
    if explicit is not None:
        return explicit
    cleaned = " ".join(text.strip().lower().split())
    for phrase in _PHRASES:
        if _PHRASE_RES[phrase].search(cleaned):
            return ALIASES[phrase]
    return None


def describe(mode: str) -> str:
    """One sentence for what setting `mode` actually does right now."""
    what = MODES.get(mode, "")
    if mode in IMPLEMENTED:
        return f"job set to {mode} - {what}."
    return (
        f"job set to {mode} - {what}. NOT BUILT YET: this only stands the "
        f"quest drive down; nothing positive replaces it until {mode} is "
        "wired in mod-overseer (see infra#2834)."
    )
