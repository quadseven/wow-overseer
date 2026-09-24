"""What the family is trying to do RIGHT NOW - the RimWorld-style schedule.

infra#2834. The operator's own words: "i should be able to be like, its farming time,
sort of like rim world job schedule times, they should quest, farm, dungeon,
level, grind, try to get specific gear from something, etc". Everything the
epic had built before this (quest aims, turn-ins, cohesion, travel, trades) is
about whether a single behaviour works. None of it says WHAT the family should
currently be doing, which is the layer this module names.

WHAT SHIPS AND WHAT DOES NOT. `MODES` names the whole vocabulary the operator asked
for, because a schedule with one slot is not a schedule and a person reading
this file should see the shape of the thing being built. The modes wired to an
actual behaviour change are named in IMPLEMENTED, one at a time, each with the
branch that proves it - deliberately NOT counted in this sentence, because the
count is the first thing to rot: this paragraph read "two of those modes" for
as long as IMPLEMENTED held three, and was still saying it when a fourth
landed. Every other mode is
a name the roster will accept and remember, and the one thing setting it does
today is turn OFF the quest drive, honestly, with nothing yet turned on in its
place. Building farm/grind/etc is the follow-up list, not code here pretending
to be finished.

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

# Canonical mode -> what it means, in the vocabulary the operator named plus what he
# said he was probably missing. Order is the order he named them in, which is
# also a reasonable build order.
MODES = {
    "quest": "follow the quest log - what the family does today",
    "raid prep": "get the family ready to raid - professions, recipes, mail, guild-bank raid materials",
    "farm": "gather deliberately for a named material, not opportunistically",
    "dungeon": "run an instance, tank bot leading (mod-dungeon-clear)",
    "fish": "toggle the bots' own fishing AI - accumulate food and reagents from water",
    "grind": "kill things for experience, no objective (The operator's 'level / grind' / 'xp')",
    "gear hunt": "target a specific item from a specific source (infra#2797)",
    "craft": "level a profession, work a queue of things the family needs",
    "town run": "vendor, repair, restock, mail, with the family together in town",
    "train": "learn what is available - professions and class (infra#2757, #2782)",
    "rest": "hearth, inn, log off gracefully",
    "bank": "consolidate and hand off materials to whoever can use them (infra#2830)",
    "reputation": "grind faction standing",
    "guild business": "charter signatures, tabard, guild bank (infra#2831)",
}

# Dungeon keywords are deliberately a closed vocabulary.  The C++ coordinator
# stores the selected keyword in the existing VARCHAR(20) job column as
# ``dungeon:<keyword>``; keeping the suffix short preserves that schema.
DUNGEONS = {
    "deadmines": "deadmines",
    "shadowfang": "shadowfang",
    "shadowfang keep": "shadowfang",
}

# Every keyword mod-overseer's coordinator has a portal row for
# (DungeonPortals() in mod_overseer.cpp), which is the only set a
# `dungeon:<keyword>` job can actually act on. Wider than DUNGEONS above on
# purpose: DUNGEONS is what chat accepts, while the council's own goals already
# send the Scarlet wings and the rest. tests/test_dungeon_goal.py pins this set
# to the C++ table, so a portal added there fails here until it is listed.
PORTAL_KEYWORDS = frozenset(
    {
        "deadmines",
        "shadowfang",
        "scarlet",
        "scarlet-library",
        "scarlet-armory",
        "scarlet-cathedral",
        "stockades",
        "wailing",
        "blackfathom",
        "razorfen-kraul",
        "razorfen-downs",
        "gnomeregan",
        "gnomeregan-depot",
        "uldaman",
        "uldaman-back",
        "zulfarrak",
        "sunken-temple",
        "blackrock-depths",
        "lower-blackrock-spire",
        "stratholme-live",
        "stratholme-undead",
        "ragefire",
        "maraudon-orange",
        "maraudon-purple",
        "scholomance",
        "dire-maul-east-east",
        "dire-maul-east-west",
        "dire-maul-east-south",
        "dire-maul-west-north",
        "dire-maul-west-south",
        "dire-maul-north",
    }
)


def dungeon_job(keyword: str) -> str | None:
    """The job a dungeon goal writes for `keyword`, or None to refuse it.

    "" is the bare `dungeon` job, whose default portal belongs to
    mod-overseer. A keyword with no portal row is refused: written anyway, it
    parks every enabled character on a job the coordinator cannot run, and the
    other drives stand down for it, so the whole roster stalls in silence.
    """
    if not keyword:
        return "dungeon"
    if keyword in PORTAL_KEYWORDS:
        return "dungeon:%s" % keyword
    return None


# THE RAID DOORS mod-overseer's raid run has (RaidDoorFor in its
# overseer_decisions, quadseven/mod-overseer#634). A `raid:<keyword>` job is
# refused by the module's DoJob for any keyword not in its table, so this set
# is the whole vocabulary. DELIBERATELY APART FROM PORTAL_KEYWORDS: the council
# and the campaign planner choose among portal keywords, and a raid is only
# ever an operator's order.
RAID_KEYWORDS = frozenset({"moltencore"})
RAID_PREFIX = "raid:"


def raid_job(keyword: str) -> str | None:
    """`raid:<keyword>` for a raid door the module has, or None."""
    if keyword in RAID_KEYWORDS:
        return RAID_PREFIX + keyword
    return None


def is_raid_job(job) -> bool:
    return str(job or "").strip().lower().startswith(RAID_PREFIX)


def job_for(keyword: str) -> str | None:
    """The job a queue entry writes for `keyword`: a raid or a dungeon job."""
    return raid_job(keyword) or dungeon_job(keyword)


def is_dungeon_job(job) -> bool:
    """Whether `job` is a dungeon job, bare or naming its portal (#206).

    The same test mod-overseer's IsDungeonJob makes: `dungeon` or
    `dungeon:<keyword>`, matched whole, so `quest` or an empty job is not one.
    """
    text = str(job or "").strip().lower()
    return text == "dungeon" or text.startswith("dungeon:")


# The modes that change behaviour. Every other key in MODES is accepted,
# stored, and said back honestly as "not built yet" - see `describe`. Kept as
# its own constant, not inferred from a "the code exists" check, so extending
# mod_overseer.cpp's gate is a one-line change here too: forgetting to widen
# this after wiring a new mode fails LOUD (test_jobs.py checks every MODES key
# against this set explicitly, not just 'quest').
#
# `dungeon` JOINED THIS SET LATE, and it is worth saying why rather than
# quietly editing the line. It was added to MODES at infra#2834 as a name with
# nothing behind it, and this constant plus the migration comment both went on
# saying so for a week after it stopped being true. quadseven/mod-overseer#88
# and #144 wired it fully: the leader's `job` being `dungeon` is the SOLE
# trigger for the whole run coordinator - reset, stage, gather, cross, clear,
# exit, and the campaign loop that repeats it. mod_overseer.cpp branches on it
# at `leaderJob != "dungeon"` (the IDLE gate and the mid-run stand-down) and
# passes `leaderJob == "dungeon"` as the still-wanted flag at both run ends;
# test_jobs.py asserts those branches still exist, so this cannot drift back
# into a claim nobody checks.
#
# Getting this wrong is not cosmetic: `describe` is what the bridge says back
# in Discord, so a stale entry here had the overseer answering "NOT BUILT YET"
# to an order it was about to carry out.
# `train` JOINED THIS SET at infra#3338, and its drive is the one that does
# NOT live in mod_overseer.cpp - so the honesty rule this constant exists for
# needs restating rather than assuming. The worldserver already derives its own
# learn errands (StepTowardAssignment writes `learn_skill` through AimLearnAt)
# and then cannot act on one, because nothing in the C++ ever writes
# `travel_npc = 'profession trainer'`. trainjob.py is the drive: it picks the
# character with an outstanding trade and bridge._drive_train aims them there
# with travel.aim_statements, which is infra#3270's missing caller. So the
# branch this entry points at is a Python one, and tests/test_trainjob.py
# pins it exactly as ImplementedMatchesTheModule pins the two C++ ones.
#
# `craft` JOINED THIS SET at infra#3687, and it is the entry this constant's
# honesty rule was actually written about. The BLOCKED text removed below said
# "nothing in the worldserver can make an item" for as long as mod-overseer has
# been shipping a drive that makes them, so `describe` was answering NOT BUILT
# YET to the one order the family was already carrying out - the second time
# this file has done exactly what the `dungeon` paragraph above apologises for.
#
# The drive is mod_overseer.cpp's `DriveCraft` (src/mod_overseer.cpp:10910 at
# AC_OVERSEER_SHA=9dbbd1a8bb51, the SHA UPSTREAM-PINS.env deploys), called from
# the main poll at :5056 behind CRAFT_POLL_MS. `LoadCraftErrands` reads
# `overseer_roster.craft_spell` for every enabled row, DriveCraft skips anyone
# whose `job` is not `craft` - the module's own words are "job='craft' is a
# PERMISSION, not a hint", because an errand may sit on a row while its
# character is off questing - and casts what survives with
# `bot->CastSpell(bot, spellId, false)`, logging `overseer: '{}' crafted '{}'`.
# So this mode is not decoration on a column: it is the single switch between
# a standing errand being cast and being ignored.
#
# THE PYTHON HALF WAS ALREADY WHOLE, which is why only this line was missing.
# bridge._craft_once picks each crafter's recipe through craft.craft_errand and
# writes `craft_spell`; _assign_crafts re-asserts it every cycle so a
# worldserver restart cannot lose it; _craft_supply_once and craft_supply.py
# buy the vendor reagents it needs.
#
# ImplementedMatchesTheModule pins DriveCraft's gate and its column read as
# source TEXT, and pins REAL STATEMENTS on purpose - unlike the `dungeon`
# entry above, whose `leaderJob == "dungeon"` strings survive at the pinned SHA
# only inside a comment the module labels "compatibility markers for
# source-contract tests". A pin that a comment can satisfy has stopped being a
# pin; craft's name executable code or nothing.
#
# `town run` JOINED THIS SET for wow-overseer's scatter fix (mod-overseer#659).
# A campaign held "town first" for bag room used to wait under `quest`, and on
# wow-dev 2026-09-24 the quest drive flew the Alliance leader to Un'Goro while
# his members were 13,000 yards behind, and four Horde members cut off from
# their leader were granted `new rpg` and flew to three zones. The bridge now
# writes this job for the wait (bridge._hand_to_town, _keep_in_town), and the
# module keeps a leader with no errand and a cut-off follower with an empty
# column off `new rpg` for it, so the family stays where it is and only town
# errands walk the leader.
IMPLEMENTED = frozenset(
    {"quest", "dungeon", "train", "craft", "raid prep", "fish", "town run"}
)

# The job a campaign waiting in town puts the family on (#265, mod-overseer#659).
TOWN_RUN = "town run"

# What each wired mode actually MAKES HAPPEN, named so `describe` can say it.
# A mode in IMPLEMENTED with no entry here is a claim with no address, which
# is the drift the whole constant above exists to stop; test_jobs.py requires
# the two sets to match.
DRIVES = {
    "quest": "the quest drive runs as normal (mod_overseer.cpp, DriveQuests)",
    "dungeon": (
        "the leader's row arms the run coordinator - reset, stage, gather, "
        "cross, clear, exit and the campaign loop (mod-overseer#88, #144)"
    ),
    "train": (
        "trainjob.plan picks whoever has an outstanding trade and the bridge "
        "aims them at the nearest profession trainer, the family following; "
        "mod-overseer buys it there through the core's Trainer::TeachSpell"
    ),
    "craft": (
        "mod_overseer.cpp's DriveCraft casts the recipe named by each "
        "character's own overseer_roster.craft_spell, gated on job='craft'; "
        "bridge._craft_once and _assign_crafts keep that column pointed at "
        "the right recipe for the skill the character actually has, and "
        "craft_supply buys the vendor reagents it needs"
    ),
    "raid prep": (
        "raidprep.plan decides and the bridge's _drive_raid_prep runs the "
        "shipped mail, craft and guild-bank sub-passes: collect mail for "
        "reagents/recipes, re-assert craft spells for profession progress, "
        "deposit gold above float to the guild bank"
    ),
    "fish": (
        "mod_overseer.cpp's fishing drive (mod-overseer#448): a row whose job "
        "is 'fish' toggles the bots' own fishing AI, teaches Fishing from a "
        "trainer and records fish/skill events (mod_overseer.cpp, wantsFishing)"
    ),
    "town run": (
        "the family stays together in town: the quest drive stands down, the "
        "leader carries `new rpg` only while a town errand or a catch-up walks "
        "it and a follower cut off from it is not sent off on its own "
        "(mod_overseer.cpp, LeaderCarriesNewRpg and CutOffFollowerRoams, "
        "mod-overseer#659); the vendor, bank, mail and trainer passes do the "
        "rest, and the far walks (gathering, flights, the leveling route) wait"
    ),
}

# Why a particular mode cannot be set, where a bespoke sentence is worth more
# than the generic one. Every mode with no entry gets GENERIC_BLOCK, which is
# the same fact said less specifically - a bespoke sentence per unbuilt mode
# would be eight more promises this file cannot keep, which is the habit #3338
# asks it to stop.
#
# EMPTY ON PURPOSE, and worth more empty than it was full. Its only entry was
# `craft`, and by infra#3687 every clause of that entry had gone false. It
# said no command kind casts a tradeskill and then listed ten kinds; the live
# `overseer_command.kind` ENUM carries twenty (auction, mail, repair, buy,
# bind, hearth, summon, conjure, cast and guild were all added after that
# sentence was written - checked against the deployed schema, not a migration
# file, 2026-09-13). It said nothing in the worldserver can make an item while
# DriveCraft was casting recipes on the family's behalf every poll.
#
# THE LESSON IS ABOUT THE SHAPE, NOT THE TYPO. A bespoke refusal here is a
# detailed claim about another repo's code, and the more specific it is the
# faster it rots - this one named a function (`JobModes`), an enum, and a
# capability, and outlived all three. GENERIC_BLOCK says only what this
# repository can actually still see: that the column is written and only the
# quest gate reads it. So the bar for ever re-adding an entry here is a test
# that pins it against the module source, the same bar
# ImplementedMatchesTheModule holds a claim to in the opposite direction.
BLOCKED: dict = {}

GENERIC_BLOCK = (
    "no drive exists for it - DoJob validates the name and writes the "
    "column, and the only thing that reads the column back is the quest "
    'gate, which reads every non-quest value as "stop"'
)


def can_set(mode: str) -> bool:
    """Whether an order for `mode` may be written at all (infra#3338).

    THE ONE PREDICATE EVERY WRITE PATH MUST PASS THROUGH, and the reason it is
    a function rather than a bare `in` is that the caller must have somewhere
    to get the REASON from as well. This file has always known which modes are
    real; what was missing was anybody asking it at the moment an order was
    written, so `job='craft'` was accepted, stood the quest drive down, and
    idled the family with nothing in the log to say why.
    """
    return mode in IMPLEMENTED


def why_not(mode: str) -> str:
    """The refusal to say out loud, or '' when there is nothing to refuse.

    Never a bare "no". A refusal a person cannot act on is the same silence
    with a different shape, so this names the missing verb, names what setting
    it would actually do instead, and names what does work today.
    """
    if can_set(mode):
        return ""
    if mode not in MODES:
        return "%r is not a job mode. The vocabulary is: %s." % (
            mode,
            ", ".join(sorted(MODES)),
        )
    return (
        "Refusing to set job=%s: %s. Setting it would stand the quest drive "
        "down and put nothing in its place (infra#3338) - the family would go "
        "idle, not %s. Modes that drive something today: %s."
        % (mode, BLOCKED.get(mode, GENERIC_BLOCK), mode, ", ".join(sorted(IMPLEMENTED)))
    )


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
# includes the operator's own phrase from the issue ("its farming time") verbatim,
# because a recognizer that requires the formal noun and misses the sentence
# that prompted the whole epic would be a design that forgot its own ticket.
ALIASES = {
    "questing": "quest",
    "quests": "quest",
    "raiding": "raid prep",
    "raid ready": "raid prep",
    "raid preparation": "raid prep",
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
    if cleaned.startswith("dungeon:"):
        keyword = cleaned.split(":", 1)[1].strip()
        return f"dungeon:{keyword}" if keyword in DUNGEONS.values() else None
    if cleaned.startswith("dungeon "):
        suffix = cleaned[len("dungeon ") :]
        if suffix in ("run", "clear"):
            return "dungeon"
        keyword = DUNGEONS.get(suffix)
        return f"dungeon:{keyword}" if keyword else None
    return ALIASES.get(cleaned)


# "job <mode>" is the canonical, unambiguous form - it is also literally what
# gets delivered as the overseer_command row (kind='job', command=<mode>), so
# a person typing it is typing exactly what mod-overseer will read.
def _explicit(text: str) -> str | None:
    cleaned = " ".join(text.strip().lower().split())
    if not cleaned.startswith("job"):
        return None
    rest = cleaned[len("job") :].strip(" :=")
    return resolve(rest) if rest else None


def parse_order(text: str) -> str | None:
    """A mode order somewhere in free text, or None.

    Two shapes: the explicit "job <mode>" form, and the operator's natural register -
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
    if mode.startswith("dungeon:"):
        keyword = mode.split(":", 1)[1]
        return f"job set to {mode} - run {keyword}. This drives: {DRIVES['dungeon']}."
    if is_raid_job(mode):
        return (
            f"job set to {mode} - mod-overseer's raid run forms the raid from "
            "overseer_raid_seat, walks it to the door and in, and holds it at "
            "the entrance; it does not clear (mod-overseer#634)."
        )
    what = MODES.get(mode, "")
    if mode in IMPLEMENTED:
        # `.get` and not `[]`: DRIVES falling behind IMPLEMENTED is a bug, and
        # test_jobs.py fails on it by name - but it must not be a KeyError
        # raised through `describe`, which is what the console renders every
        # chip with and what Discord hears back for every order.
        drive = DRIVES.get(mode)
        return (
            f"job set to {mode} - {what}. This drives: {drive}."
            if drive
            else f"job set to {mode} - {what}."
        )
    return (
        f"job set to {mode} - {what}. NOT BUILT YET: this only stands the "
        f"quest drive down; nothing positive replaces it until {mode} is "
        "wired in mod-overseer (see infra#2834)."
    )
