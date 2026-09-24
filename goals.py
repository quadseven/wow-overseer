"""Goal supervision for the wow-overseer bridge (infra#2601).

Pure decision module, same seam as core.py: goal-shaped text comes in and a
Goal comes out; a persisted goal row plus one observation comes in and typed
actions come out. Nothing here touches Discord, MySQL, or an LLM - bridge.py
persists the goals, observes the world, and applies the actions. That split
is what lets the supervisor be fully unit-tested against a fake store.

The reconcile contract that keeps a goal from spamming the world: strategy
commands are issued only when the stored state CHANGES (first sighting of
the character), never every cycle. Steady state is read-only. Progress is
recorded in the goal row itself, so a bridge restart resumes supervision
from the store with no in-memory carryover.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

import classic

# Profession -> SkillLine id (3.3.5a conventions). acore_world.skillline_dbc
# is EMPTY on this deployment (DBC data ships inside the client files), so
# these ids were verified live against acore_characters.character_skills
# instead: on 2026-08-21 every id below existed there across 100+ characters
# with profession-shaped value/max tiers (75/300 caps), which a wrong id
# (a class skill or a language) would not show.
SKILL_IDS = {
    "first aid": 129,
    "blacksmithing": 164,
    "leatherworking": 165,
    "alchemy": 171,
    "herbalism": 182,
    "cooking": 185,
    "mining": 186,
    "tailoring": 197,
    "engineering": 202,
    "enchanting": 333,
    "fishing": 356,
    "skinning": 393,
    # These two are NOT live-verified the way the rest are: nobody on this
    # realm holds either, which is precisely why the family's trade plan has to
    # name them (infra#2757). They are taken from the core's own enum at the
    # pinned SHA instead, which is a better source than a live row anyway -
    # SharedDefines.h:3218 (SKILL_JEWELCRAFTING) and :3235 (SKILL_INSCRIPTION),
    # in mod-playerbots/azerothcore-wotlk@efe123fa. Every id above matches that
    # same enum exactly, which is how the two sources were checked against each
    # other rather than assumed to agree.
    "jewelcrafting": 755,
    "inscription": 773,
}

# The classic ruleset's caps (classic.py): level 60 and skill 300, not the
# 3.3.5a client's 80 and 450. Targets outside these bounds are not goals: the
# parser stays conservative and lets the voice treat the text as ordinary words
# instead of persisting something this world will not allow.
MAX_LEVEL = classic.MAX_LEVEL
MAX_SKILL = classic.MAX_PROFESSION_SKILL

# Level goals report every level; skill points come one at a time, so skill
# goals report on crossing each step boundary instead of every point.
SKILL_MILESTONE_STEP = 25

# Cycles without progress before the strategy is issued again. A character
# that logs out and back in loses its strategies - PlayerbotAI::ResetStrategies
# runs on login and rebuilds them from defaults, and the autonomous ones are
# gated behind IsRandomBot(), which is false for named characters. The roster
# loop relogs anyone who drops, so a long goal WILL meet this. Issued once and
# never again, a goal would go quietly inert with its row still reading
# 'active'.
REASSERT_AFTER_CYCLES = 5

# How long a SKILL goal may make no progress at all before the supervisor says
# so out loud, counted in the same supervision cycles as REASSERT_AFTER_CYCLES.
#
# THE ARITHMETIC MATTERS MORE THAN THE NUMBER. bridge.GOAL_INTERVAL is 60
# seconds and `character_skills` is flushed on the worldserver's own
# PlayerSaveInterval of 900000 ms with PlayerSave.AdditionalSaves = 0, so
# FIFTEEN cycles can pass during which the skill really has risen and the table
# has simply not admitted it yet. Thirty is two full save intervals: the
# smallest value at which "the number has not moved" cannot be an artefact of
# the save clock. tests/test_goals.py reads bridge.py's own default out of the
# source and fails if that 60 ever changes without this constant moving with it.
#
# THE DRIFT ONLY EVER RUNS ONE WAY, which is why no extra margin is added on
# top. A stale read UNDER-reports the skill, so this counter climbs when it
# should have reset - the verdict therefore fires LATE and never early, and the
# cost of staleness is lateness rather than a false accusation. That is
# craft_rhythm's own staleness argument (see its SHORT_CASTS/STOCK_CASTS
# comment) applied to a different table, and it is the reason a threshold may be
# consulted here at all: it is an EXIT from the state the goal is already in,
# never a decision about which state to be in.
#
# A MULTIPLE OF REASSERT_AFTER_CYCLES, on purpose. Every cycle that speaks is
# therefore also a cycle that re-drives, so the sentence a person reads is
# always accompanied by a fresh decision rather than by a stale memory of one.
# tests/test_goals.py pins that divisibility.
SKILL_BARREN_CYCLES = 30

# A quest goal's target, always. Quest progress counts DOWN - quests.Progress
# .left is objectives REMAINING - while reconcile's completion test is
# `observed >= target`. Rather than invert the test for one kind (which would
# make every other branch read "unless it is a quest"), a quest goal is stored
# as "get to zero left" and OBSERVED as -left. Both then move the same
# direction as a level, and the only place the negation exists is
# observed_from_left() below and the two text functions that undo it.
QUEST_TARGET = 0

# Every kind an overseer_goal row may carry, and the column definition that
# admits them. ONE list: the enum and the code that writes into it drifting
# apart is the whole failure this constant exists to prevent.
#
# 'dungeon' joined this list once the council could actually decide one
# (infra dungeon-decision gap): a family-wide plan to run a named dungeon,
# stored the same way 'quest' is - see Goal.dungeon_keyword below and
# _persist_council_plan's comment on what each column holds for it.
GOAL_KINDS = ("level", "skill", "quest", "dungeon")
KIND_COLUMN = "ENUM(%s) NOT NULL" % ",".join("'%s'" % k for k in GOAL_KINDS)


def goal_migrations(kind_column_type: str, has_quest_id: bool) -> list:
    """The ALTERs overseer_goal needs to reach the shape this module writes.

    WHY THIS EXISTS AS A PURE FUNCTION. The bridge creates its own tables with
    CREATE TABLE IF NOT EXISTS, and IF NOT EXISTS IS A NO-OP ON AN EXISTING
    TABLE - including on every word of the column definitions inside it. The
    live overseer_goal was created with ENUM('level','skill'), so adding
    'quest' to that CREATE changes nothing at all on the live database: the
    INSERT is rejected with "Data truncated for column 'kind'", the council's
    quest decision is lost, and every test still passes because the test
    database is always fresh. That combination - silently dead in production,
    green in CI - is exactly what this codebase has been bitten by before, so
    the decision lives here where it can be tested against both shapes rather
    than inside an un-importable module.

    IDEMPOTENT BY CONSTRUCTION, not by trying and catching. Both inputs
    describe the CURRENT shape of the table, read from information_schema, so
    a table already in the target shape produces an empty list - and that is
    true of a fresh database, whose CREATE produced the final shape directly,
    just as much as of one that has been migrated once already. Feeding this
    function its own result twice is a no-op the second time, which is what
    the test asserts.

    An empty `kind_column_type` means the table does not exist yet (the
    information_schema lookup found nothing). CREATE TABLE is about to make it
    correctly, so there is nothing to alter.

    GENERALIZED FOR 'dungeon', RATHER THAN GIVEN A SECOND COPY OF THIS
    FUNCTION'S BODY. The check used to read `"'quest'" not in
    kind_column_type` because 'quest' was the only value this table had ever
    been asked to grow into after 'level' and 'skill'. Reading GOAL_KINDS
    itself instead of naming one value keeps this the SAME migration for
    every kind that has ever needed one, including the next one - the ALTER
    it emits already sets the full ENUM regardless of how many values were
    missing, so there is nothing to change about the statement, only about
    when it fires.
    """
    if not kind_column_type:
        # No `kind` column means no table (the caller's information_schema
        # lookup found nothing). Returning the ADD COLUMN here would emit an
        # ALTER against a table that does not exist yet - and it must return
        # BOTH or NEITHER, since a half-shaped answer is what a reader would
        # copy next time.
        return []
    out = []
    if any("'%s'" % kind not in kind_column_type for kind in GOAL_KINDS):
        out.append("ALTER TABLE overseer_goal MODIFY kind " + KIND_COLUMN)
    if not has_quest_id:
        # MySQL has no ADD COLUMN IF NOT EXISTS, which is why the caller looks
        # the column up rather than trying the ALTER and catching the failure -
        # catching it would also catch the failures worth seeing.
        out.append(
            "ALTER TABLE overseer_goal "
            "ADD COLUMN quest_id INT UNSIGNED NOT NULL DEFAULT 0"
        )
    return out


@dataclass(frozen=True)
class Goal:
    """A parsed goal, before persistence (no id/character/channel yet)."""

    # 'dungeon' is deliberately absent from this list: nobody TYPES a dungeon
    # goal into Discord the way they type "get to level 20" - parse_goal below
    # never produces one. A dungeon goal is council-only, persisted straight
    # to overseer_goal by bridge._persist_council_plan, which is also why this
    # dataclass carries no dungeon_keyword field of its own; see
    # _persist_council_plan's comment on where that value actually lives.
    kind: str  # 'level' | 'skill' | 'quest'
    target: int
    skill_name: str | None = None
    # kind='quest' only. The id mod-overseer aims a bot at; 0 everywhere else.
    quest_id: int = 0


@dataclass(frozen=True)
class CancelGoal:
    """The character is being told to stand down from its goals."""


# --- reconcile actions: what the bridge should do this cycle ---------------


@dataclass(frozen=True)
class StrategyCommand:
    """An overseer_command row that puts the bot on task (e.g. co +grind)."""

    target_name: str
    command: str


@dataclass(frozen=True)
class DriveQuest:
    """Aim the family's ONE traveller at a quest: "work quest <id> for <who>".

    DELIBERATELY NOT A StrategyCommand, and this is the crux of the ticket.
    strategy_for() returns `nc +grind` - "kill what is in front of you" - which
    never travels, and it is the exact instruction that has been overriding
    every quest decision the council has ever made. Five characters agreed to
    help Ugga finish Kobold Candles and then stood still: 0.0 yards in 45
    seconds, none in combat, 11 yards from the kobolds that drop the item.

    It carries no target NAME on purpose. The traveller is whoever holds the
    party lead, which is a fact the bridge owns (it writes overseer_roster.lead
    from bonds.head_of_family); a name chosen here would be a second opinion
    about leadership that could disagree with the first. `beneficiary` is who
    the family is doing this FOR, which is what the reports and thoughts say
    out loud - it is not who gets sent.
    """

    quest_id: int
    beneficiary: str


@dataclass(frozen=True)
class DriveDungeon:
    """Send the WHOLE family into a dungeon: job='dungeon:<keyword>' on every
    enabled roster row, plus the campaign cap that goes with it.

    FAMILY-WIDE ON PURPOSE, unlike DriveQuest. A quest aim names one traveller
    because only one character needs to hold and drive it; a dungeon run needs
    everybody in the party, the same way jobs.py's own job-schedule modes are
    fanned out to every enabled character (bridge._set_job) rather than to one
    name. `beneficiary` is who the council's plan named, kept for the report
    and the thought log - it is not who the job is written to.

    `keyword` is "" for the bare 'dungeon' job (whichever the module treats
    as its own default) and a wing name like 'scarlet-library' otherwise - the
    same string council.Proposal.keyword and Plan.keyword carry, unpacked from
    the goal row's skill_name column (see _persist_council_plan's comment on
    why that column is where it is stored).

    THE BAG-PRESSURE GATE LIVES OUTSIDE THIS MODULE. Whether the family's bags
    are already too full to loot a run is a live-world fact this pure module
    has no way to see; bridge.py checks it (bag_pressure.family_town_run_needed)
    before turning this action into a write, the same way it is the one place
    that can see whether a database write actually landed.
    """

    keyword: str
    wanted: int
    beneficiary: str


@dataclass(frozen=True)
class DriveSkill:
    """Put the family's PROFESSION machinery on one skill, not its combat one.

    THIS IS THE ACTION THAT REPLACES `nc +grind` FOR kind='skill', and it is a
    typed action rather than a StrategyCommand for exactly the reason DriveQuest
    is: a strategy command is a whisper to one bot's engine, and raising a
    profession is not something any engine does. `nc +grind` means "kill what is
    in front of you". Issued against a mining goal it produced the owner's own
    complaint word for word - "why are they fighting in tanaris instead of
    working on their professions like i told you to?" - and the family's most
    recent deaths are to Wastewander Assassins and Wastewander Shadow Mages in
    Tanaris, which is what that instruction looks like from the outside.

    IT CARRIES FACTS AND NOT A DECISION. Everything needed to CHOOSE is a live
    read this pure module cannot make - the skill's rank cap, what mode the
    family is standing in, whether a recipe bracket exists - so this action is
    the question, and skillgoal.plan (which may import professions and craft,
    as goals.py may not) is the answer. bridge._drive_skill is what puts the two
    together, the same division of labour DriveDungeon already has with its
    bag-pressure gate.

    `stalls` is how many consecutive supervision cycles the observed value has
    not moved for, and it rides in the action because skillgoal needs it to
    decide whether to add the "this drive is standing and starved" sentence.
    `speak` is whether THIS tick is one a person should be told about; see
    _reconcile_skill for the two cases that set it, and why a blocked goal must
    not narrate itself once a minute for ever.
    """

    skill_name: str
    skill_id: int
    target: int
    observed: int
    beneficiary: str
    stalls: int = 0
    speak: bool = False


@dataclass(frozen=True)
class MilestoneThought:
    """An overseer_thought row (source 'goal') marking progress."""

    character_name: str
    text: str


@dataclass(frozen=True)
class Report:
    """Progress or completion text for the Discord channel the goal came from."""

    text: str


@dataclass(frozen=True)
class RecordProgress:
    """Persist the observed value on the goal row; the store IS the memory.

    `stalls` counts consecutive cycles with no progress. It rides in the same
    field because the goal row is the only memory a restart preserves, and a
    counter held in the supervisor would reset every deploy - which is exactly
    when a strategy is most likely to have been lost.
    """

    goal_id: int
    value: int
    stalls: int = 0


@dataclass(frozen=True)
class MarkComplete:
    """Flip the goal to completed; it must never issue commands again."""

    goal_id: int


# Longest names first so 'leatherworking' cannot half-match anything shorter.
# Multi-word names ('first aid') tolerate any run of whitespace between words.
_PROF_ALT = "|".join(
    r"\s+".join(re.escape(word) for word in name.split())
    for name in sorted(SKILL_IDS, key=len, reverse=True)
)
_SKILL_RE = re.compile(
    rf"\b({_PROF_ALT})\b\s+(?:up\s+)?to\s+(\d{{1,3}})\b", re.IGNORECASE
)
_LEVEL_RE = re.compile(
    r"\b(?:reach|hit|make)\s+level\s+(\d{1,3})\b"
    r"|\b(?:get|level)(?:\s+up)?\s+to\s+(?:level\s+)?(\d{1,3})\b",
    re.IGNORECASE,
)
# "work quest 12", the verb from the design note. It lives HERE and not in
# voice.VOCABULARY: every entry there is a mod-playerbots chat command handed
# verbatim to a bot session, and `work quest` is not one - it would produce a
# command row the module passes to HandleCommand and mod-playerbots ignores,
# which is the "delivered but nothing happened" failure this epic keeps
# repeating. A trailing "for <someone>" is tolerated and ignored: the goal is
# already attached to the character the directive was addressed to.
_QUEST_RE = re.compile(r"\bwork\s+quest\s+(\d{1,6})\b", re.IGNORECASE)

# Bounded gap so 'forget'/'cancel' only binds to a nearby 'goal', not one
# three sentences away in an unrelated order.
_CANCEL_RE = re.compile(
    r"\b(?:forget|cancel|abandon|drop|scrap)\b[^.!?]{0,40}\bgoals?\b",
    re.IGNORECASE,
)


def parse_goal(text: str) -> Goal | CancelGoal | None:
    """Recognize a goal-shaped order inside a natural-language directive.

    Skill shapes are checked before level shapes so 'level your cooking to
    150' reads as a cooking goal, not a level goal. None means 'not a goal':
    the caller falls through to the normal voice path.
    """
    if _CANCEL_RE.search(text):
        return CancelGoal()
    m = _QUEST_RE.search(text)
    if m:
        quest_id = int(m.group(1))
        if quest_id > 0:
            # target 0 = "no objectives left". See QUEST_TARGET.
            return Goal("quest", QUEST_TARGET, None, quest_id)
        return None
    m = _SKILL_RE.search(text)
    if m:
        skill_name = " ".join(m.group(1).lower().split())
        target = int(m.group(2))
        if 1 <= target <= MAX_SKILL:
            return Goal("skill", target, skill_name)
        return None
    m = _LEVEL_RE.search(text)
    if m:
        target = int(m.group(1) or m.group(2))
        if 2 <= target <= MAX_LEVEL:
            return Goal("level", target)
    return None


def observed_from_left(left: int | None) -> int | None:
    """quests.Progress.left -> the value reconcile() compares against target.

    The negation lives here and nowhere else. `left` is objectives REMAINING,
    so it falls as the family makes progress, while every other observation in
    this module rises; reconcile completes on `observed >= target` and reports
    a milestone on `observed > last`. Negating once, at the edge, is what lets
    both of those keep meaning one thing.

    None passes through as None: a quest the character is not holding, or one
    with no countable objective, is not observable, and reconcile is required
    to stay quiet rather than command a character it cannot see.
    """
    if left is None:
        return None
    return -int(left)


def strategy_for(goal: Mapping) -> str:
    """The command that puts a character on task.

    NON-combat, and that is the whole point. This read 'co +grind' and could
    never work: mod-playerbots registers grind on the non-combat engine
    (AiFactory::AddDefaultNonCombatStrategies does
    `nonCombatEngine->addStrategy("grind")`), so sending it down the combat
    channel adds nothing to the engine that moves the character. The command
    still delivered, the goal still reported healthy, and the bot stood
    exactly where it spawned.

    Measured on the live server, same character, 90 seconds each:

        Ugga before        -8950,-132
        after 'co +grind'  -8950,-132   not one unit
        after 'nc +grind'  -8990,-103

    SKILL GOALS NO LONGER RIDE THIS STRATEGY, AND ASKING FOR ONE IS AN ERROR
    (infra#3731). This docstring used to end here:

        "Skill goals ride the same strategy: gathering and combat skills rise
        while grinding, and no profession-specific strategy exists to issue
        instead - the supervisor's job is staying on task and reporting, not
        crafting rotations (out of scope on infra#2601)."

    Both halves of that were true when it was written and neither is now. There
    IS a profession-specific drive - mod-overseer's DriveCraft casts real
    tradeskill spells behind a job='craft' permission, craft.RECIPES picks the
    bracket, craft_rhythm alternates gathering against crafting - and "the
    supervisor's job is staying on task" turned out to be the problem rather
    than the defence: `nc +grind` IS a task, it is just the wrong one. A goal of
    "get Grug's mining to 75" issued it, Grug walked to Tanaris and fought
    Wastewander Assassins until they killed him, and the goal row went on
    reporting itself healthy because a goal that neither completes nor errors
    looks exactly like a goal that is merely slow. That is the owner's own
    complaint, three times over, and it was this line.

    So `reconcile` routes kind='skill' to `_reconcile_skill` before it can ever
    reach here, and this function REFUSES a skill goal rather than returning
    something plausible. A silent wrong answer is what cost the months; a raised
    ValueError is caught and logged per-goal by bridge._supervise_goals, so the
    blast radius is one goal and the evidence is in the log. The measurements
    above stay because they are the reason this string is `nc` and not `co`,
    which is a fact about the engine and is still true for every kind that does
    grind.
    """
    if str(goal.get("kind") or "") == "skill":
        raise ValueError(
            "a skill goal must never be given a combat strategy - see "
            "_reconcile_skill and skillgoal.plan. This is infra#3731: 'nc "
            "+grind' against a profession goal is what sent the family to "
            "fight in Tanaris instead of working their trades."
        )
    return "nc +grind"


# The strategy that gives a character a LIFE rather than a task. `grind` means
# "kill what is in front of you", which is why it worked at level 1 in a
# starting zone and stopped working at level 7: nothing moves these characters
# to level-appropriate content, because RandomPlayerbotMgr's teleporting only
# ever applies to bots in its own pool and named characters are not in it.
#
# Measured live, same spot, 150 seconds, one on each strategy:
#
#     Grog  'new rpg'  -8800 -> -8924   travelled 124 yards
#     Ugga  'grind'    -8800 -> -8797   moved 3
#
# `new rpg` travels, takes quests and visits vendors, and the two coexist:
# Bork had both and was the only character in the family with a quest log.
LIFE_STRATEGY = "nc +new rpg"

# Self-preservation. FleeStrategy gives `panic` and `critical health`, neither
# of which any of them had - AiFactory adds `flee` for nobody, random bot or
# not, so it is opt-in through a command or it does not exist.
#
# Do not expect miracles: `outnumbered` is an upstream no-op (GenericTriggers
# assigns foePower inside the attacker loop instead of accumulating it, so only
# the last attacker counts), and FleeAction backs up FleeDistance yards rather
# than escaping. It is still the difference between dying at 20 percent and
# dying at 0.
FLEE_STRATEGY = "co +flee"


def returned_to_ai(previous, current) -> frozenset:
    """Who has just come back under AI control since the last look.

    THE STRATEGY DOES NOT SURVIVE A RELOG. PlayerbotAI::ResetStrategies runs on
    login and rebuilds from AiFactory, where `new rpg` sits behind the
    IsRandomBot gate - permanently false for named characters. So it is never
    a default for this family: it exists only because the life loop grants it,
    and every re-login silently takes it away again.

    The cost is worst on the leader. Four followers are welded to him by
    `follow`, so a leader with nothing driving him does not merely idle - he
    stops the whole family, and they stand in a heap around him looking for
    all the world like a pathfinding bug. Measured live: eight minutes of
    stillness inside one PROTECT_CYCLE_SECONDS, self-healing at the next
    sweep, which is exactly why it went unseen. It has been latent behind
    every relog the module has ever done.

    `previous is None` means FIRST LOOK and returns nothing. At startup every
    character looks like a return, and the protect cycle already covers that
    case - firing here as well would re-issue to everyone on every restart.
    """
    if previous is None:
        return frozenset()
    return frozenset(current) - frozenset(previous)


# THE PAIR THAT PICKS A NODE UP, WHICH NOTHING IN THIS REPOSITORY HAS EVER
# GRANTED (infra#3731).
#
# `new rpg` ROAMS BUT IT DOES NOT GATHER. mod-overseer's reading of
# NewRpgStatusUpdateAction (mod_overseer.cpp:14526-14532, :17706-17712) names
# the whole status set - IDLE, GO_GRIND, GO_CAMP, WANDER_RANDOM, WANDER_NPC,
# DO_QUEST, TRAVEL_FLIGHT - and not one of them picks a resource node. A herb
# or an ore vein is reached by two upstream strategies working as a pair, and
# mod_overseer.cpp:1867-1875 spells out why both are needed:
#
#     gather  "timer" -> "add gathering loot" 5.0
#     loot    "loot available" -> "loot" 6.0, "far from loot target" ->
#             "move to loot" 7.0, "can loot" -> "open loot" 8.0
#     `gather` is what puts a herb or ore node INTO the loot stack and `loot`
#     is what WALKS to it, so taking one and leaving the other leaves half of
#     the measured behaviour in place. They are one diverter with two names.
#
# MEASURED AGAINST THE LIVE COMMAND TABLE, 2026-09-13: `nc +gather` has been
# issued five times in three weeks and every one is a hand-typed operator row;
# `nc +loot` has NEVER been issued, to anybody, once. So the family has been
# ordered out to gather while carrying at most half of the only mechanism that
# collects anything, and usually neither half. What that looks like after
# weeks of it: Grog's Mining 1/75 and zero Rough Stone, Bork's Skinning 12/75
# and zero Ruined Leather Scraps, Grug's Mining 8/75 and zero Rough Stone.
#
# AND IT HAS TO BE RE-ASSERTED, WHICH IS THIS FUNCTION'S WHOLE PURPOSE.
# PlayerbotAI::ResetStrategies rebuilds from AiFactory on every login, and
# RandomPlayerbotMgr::OnPlayerLogout calls it on each follower every time the
# client closes; `follow` survives that because it is an unconditional default
# (AiFactory.cpp:584), and these two do not. A hand-typed grant is therefore
# not a fix, it is a fix with an expiry date nobody sees.
#
# `nc`, NOT `co`, AND THE DIFFERENCE IS NOT COSMETIC. Both are registered on
# the non-combat engine (LootNonCombatStrategy.cpp), which is `strategy_for`'s
# measured `co +grind` lesson said about a different strategy: a command down
# the wrong channel is delivered cleanly, reports success, and adds nothing to
# the engine that moves the character. `voice.py` currently documents a
# `co +loot` phrase that cannot work for exactly that reason.
GATHER_STRATEGIES = ("nc +gather", "nc +loot")


def life_strategies(
    *,
    leads: bool,
    aimed: bool = False,
    travelling: bool = False,
    gathering: bool = False,
    in_town: bool = False,
) -> list:
    """What keeps this character playing, given whether it leads the party.

    ONE character travels and the rest follow. That asymmetry is the whole
    point, and it is why this is a function rather than a constant.

    `follow` was inert for every one of them. It resolves through a formation
    value, the value was `chaos`, and ChaosFormation::GetLocation() opens with
    GetMaster() - which is null for a party of masterless bots. So it returned
    no location and FollowAction reported itself useless. They had followed
    nobody, ever.

    Even repaired it would have lost: `follow` runs at relevance 1.0 while
    `new rpg`'s actions run 3.0 to 11.0, so a follower given both wanders every
    single tick. Taking `new rpg` OFF the followers is what lets following
    happen at all - measured live, the family went from a 937-yard spread to
    four of them standing within three yards of each other.

    The cost of getting this wrong the other way is the thing the operator actually
    complained about: the healer 600 yards away in her own fight, three fights
    in three sub-zones, and Grug charging three mobs with nobody to heal him.

    `travelling` MEANS SOMEBODY ELSE OWNS THE TASK. A character part-way
    through an errand already has a job, and the module has stood down
    everything that would pull it off that job for the duration - see
    ESCORT_DIVERT_STRATEGIES in mod_overseer.cpp. Handing the task strategy
    back mid-errand is this function granting a second task, and the two then
    fight: the module takes it off on its poll, this pass puts it back on
    the roster cadence, and the character makes no progress in either
    direction.

    Measured live on infra#3423, and the module catches it itself:

        'Og' had grind put back on its non-combat engine while it was
        travelling to 'at:1:-705,-2045,66.45' - taken off again. Something
        is granting strategies to a character that is mid-escort

    "Something" was this function. Twice in three hours.

    THE DAMAGE IS BOUNDED, and saying so is part of the fix being honest.
    The module re-asserts its stand-down on every travel poll rather than once
    at the start of the trip, so a second writer costs a few seconds of the
    wrong strategy rather than the errand. This was first reported as the
    cause of a dungeon campaign stuck at 0 of 100, and it was not: the module
    tests that hypothesis on its own correction ladder and prints "nothing had
    come back on, so this is not what is holding it". That campaign was failing
    on terrain and on a run that opens with no distance gate
    (quadseven/mod-overseer#305). This is worth fixing because two writers
    should not both answer one question, not because it was the outage.

    ONLY THE TASK STRATEGY IS WITHHELD, and that is the whole of the change.
    `new rpg` and `follow` are how the errand travels at all and the module
    deliberately never touches either; `flee` is how it survives what finds it
    on the way. Withholding the whole set instead would be a worse bug than
    the one it fixes: the module restores ONLY what it stood down, and it
    never stands down - and never grants - those three. They exist solely
    because this loop grants them, and ResetStrategies takes them away on
    every relog. A character that relogged mid-errand would come back with no
    strategy at all and nobody to give it one, which is infra#3409 restored.

    This is infra#3410 one layer along. That fix made a travel errand count as
    an aim, so a traveller keeps the strategy that MOVES it. This one stops
    the same pass also granting the one that FIGHTS it.

    `gathering` MEANS THE FAMILY IS OUT TO COLLECT SOMETHING, and it is the
    one parameter here that adds rather than withholds. Every branch above
    decides what MOVES a character; none of them has ever decided what lets it
    PICK SOMETHING UP, and until infra#3731 nothing anywhere did - see
    GATHER_STRATEGIES for the measurement, which is that `nc +loot` has never
    been issued to anybody in the history of this realm. It is orthogonal to
    `leads`, `aimed` and `travelling` by construction, which is why it is a
    fifth flag and not a fifth branch: the leader on a gathering trip needs to
    be able to loot a node exactly as much as the follower beside it does.
    """
    if in_town and not travelling:
        return _in_town_strategies(leads)
    return _with_gathering(
        _life_strategies(leads=leads, aimed=aimed, travelling=travelling),
        gathering,
    )


def _in_town_strategies(leads: bool) -> list:
    """Nobody travels on its own while the family's campaign waits in town.

    `in_town` IS THE `town run` JOB (mod-overseer#659), and it withholds the
    wander strategy from the leader as well as the followers. A leader with
    `new rpg` and no errand is handed a random status by upstream on its next
    tick - a flight to another zone among them - and on wow-dev 2026-09-24
    the questing rule flew the Alliance leader 13,000 yards from his family
    while its campaign waited on a vendor. mod-overseer takes the strategy off
    such a leader itself; granting it here every roster cycle would only
    reopen that window each time. A town errand makes the leader
    `travelling`, which keeps the ordinary leader branch, so the walk to the
    vendor still carries the strategy that moves it.

    A follower keeps `follow`, as in the unaimed branch: aimed or not, it
    has nowhere of its own to be while the family waits. Everybody keeps
    `flee`. The leader is not handed `follow`; it is its own master.
    """
    if leads:
        return ["nc -new rpg", FLEE_STRATEGY]
    return ["nc -new rpg", "nc +follow", FLEE_STRATEGY]


def _with_gathering(base: list, gathering: bool) -> list:
    """Append the node-collecting pair, or leave the set exactly as it was.

    APPENDED RATHER THAN WOVEN IN, so that `gathering=False` returns the list
    that shipped before this parameter existed, byte for byte, on every one of
    the four branches. That is what `test_gathering_is_purely_additive` pins:
    a parameter that changes the answer for a caller that did not pass it is
    the quiet regression this family of functions cannot afford, and the
    default argument is the safe one for infra#2812's reason.

    AFTER THE REST, WHICH MATTERS FOR THE FOLLOWER BRANCHES ONLY. Commands are
    delivered in list order and the unaimed branch opens with `nc -new rpg`; a
    gather grant ahead of it would spend a tick with the wander strategy still
    on and the node-chaser newly added, which is the one combination that
    genuinely does scatter a follower. Adding at the end means every branch
    has already settled the wander question before anything starts walking to
    a node.

    NOT GRANTED WHILE THE FAMILY IS CRAFTING, which is the caller's business
    and is said here because it is the reason this is a parameter rather than
    a constant added to every set. `gather` and `loot` sit at relevance 5.0 to
    8.0 against `follow`'s 1.0, so they pull a character off formation by
    design - which is the point on a gathering trip and is a character
    wandering away from an anvil on a crafting one. mod-overseer strips both
    for the duration of any travel errand for the same reason
    (ESCORT_DIVERT_STRATEGIES, mod_overseer.cpp:1922-1925) and hands back only
    what it observed coming off, so a grant that this loop keeps re-asserting
    is restored correctly and one that it does not is lost for good.
    """
    if not gathering:
        return base
    return base + [cmd for cmd in GATHER_STRATEGIES if cmd not in base]


def _life_strategies(*, leads: bool, aimed: bool, travelling: bool) -> list:
    """The set as it was before `gathering` existed. See `life_strategies`."""
    if leads:
        if travelling:
            # The errand is the task. Everything else the leader branch hands
            # out is life support, and stays.
            return [LIFE_STRATEGY, FLEE_STRATEGY]
        return [LIFE_STRATEGY, strategy_for({"kind": "level"}), FLEE_STRATEGY]
    if aimed:
        # THE AIM HAS TO CARRY THE STRATEGY THAT READS IT. `rpgInfo` is
        # consumed only by NewRpgDoQuestAction, which is reachable only through
        # the `do quest status` trigger node, which is registered only by
        # NewRpgStrategy. Strip `new rpg` and the aim is a populated column
        # nobody reads - which is precisely what happened: drive_quest=60 was
        # set on Ugga, Og and Grog and not one of them had the strategy, so the
        # whole chain from council to movement ended in silence.
        #
        # `follow` STAYS. It runs at relevance 1.0 against every rpg action's
        # 3.0-11.0, so it cannot pull an aimed character off its quest; it is
        # the fallback for when the rpg action idles, which is what stops a
        # traveller with nothing left to do from standing in a field.
        #
        # This is not a relaxation of the rule below - it is the rule the
        # measurements always implied. An UNAIMED follower carrying `new rpg`
        # free-roams its own quest log: that is the 937-yard scatter. An AIMED
        # one walks to a destination it shares with everyone else aimed at the
        # same quest, measured in the dev world at a 253-yard spread.
        return [LIFE_STRATEGY, "nc +follow", FLEE_STRATEGY]
    # Order matters: drop the wander before asking them to follow, so there is
    # no tick where both are set and the follower drifts off again.
    return ["nc -new rpg", "nc +follow", FLEE_STRATEGY]


def already_working(
    kind: str, target: int, active: list, *, quest_id: int = 0, keyword: str = ""
) -> bool:
    """Is this character already pursuing exactly this goal?

    A function rather than a check at the call site so the rule can be tested
    on its own. The council meets hourly and keeps reaching the same conclusion
    while the work is still in progress; replacing the goal each time wiped
    last_report, restarting the progress record AND the stall counter that
    re-issues a lost strategy. Four cancelled duplicates of one goal sat in the
    table before it was noticed, and the supervisor never once got far enough
    to re-assert.
    """
    if kind == "quest":
        # EVERY quest goal has target 0, so comparing targets would report
        # "already working" for any quest at all the moment one was active -
        # the council's next decision would be swallowed, silently, and the
        # family would keep driving yesterday's quest. The id is the identity.
        return any(
            row.get("kind") == "quest"
            and int(row.get("quest_id") or 0) == int(quest_id)
            for row in active
        )
    if kind == "dungeon":
        # EVERY dungeon goal shares the same target (DUNGEON_RUNS_WANTED), so
        # comparing targets here has the identical failure the quest branch
        # above already fixed once: "already working" would read true for
        # ANY dungeon at all, and a council that moved on from the graveyard
        # to the cathedral would find its new decision silently swallowed by
        # the old one. skill_name carries the keyword (see
        # _persist_council_plan) and is the identity here, the same role
        # quest_id plays for a quest.
        return any(
            row.get("kind") == "dungeon"
            and str(row.get("skill_name") or "") == str(keyword or "")
            for row in active
        )
    return any(
        row.get("kind") == kind and int(row.get("target", -1)) == int(target)
        for row in active
    )


def _dungeon_name(keyword: str) -> str:
    # The keyword IS the name, hyphens aside - this module has no dungeon
    # catalogue of its own (achievements.py is where dungeon names actually
    # live) and reusing council.py's own SCARLET_WINGS vocabulary here would
    # be a second answer able to disagree with the first. "" is the bare
    # 'dungeon' job, which names no specific place.
    return keyword.replace("-", " ") if keyword else "a dungeon"


def _describe(kind: str, skill_name: str | None, target: int, quest_id: int = 0) -> str:
    if kind == "skill":
        return f"{skill_name} {target}"
    if kind == "quest":
        # The id, not the title. A title would have to be stored somewhere,
        # and the only spare column is skill_name - one column meaning two
        # things is how a schema starts lying. The council's own sentence is
        # already in the goal's reason and says the title out loud.
        return f"quest {quest_id}"
    if kind == "dungeon":
        # skill_name carries the job keyword here, not a skill - see
        # _persist_council_plan's comment on why that column holds it. A
        # dedicated column would be the honest fix; this module reuses the
        # one spare column the schema already has, same as 'quest' does.
        return f"{_dungeon_name(skill_name or '')}, {target} run{'s' if target != 1 else ''}"
    return f"level {target}"


def describe(goal: Goal) -> str:
    return _describe(goal.kind, goal.skill_name, goal.target, goal.quest_id)


def ack_text(name: str, goal: Goal) -> str:
    return (
        f"{name} accepts the charge: {describe(goal)}. "
        "I will keep watch and report progress here."
    )


def cancel_text(name: str, cancelled: int) -> str:
    if cancelled == 0:
        return f"{name} has no active goal to forget."
    plural = "s" if cancelled > 1 else ""
    return f"{name} stands down: {cancelled} goal{plural} cancelled."


def milestone_text(row: Mapping, observed: int) -> str:
    what = _describe(
        row["kind"],
        row.get("skill_name"),
        int(row["target"]),
        int(row.get("quest_id") or 0),
    )
    if row["kind"] == "quest":
        left = -int(observed)
        plural = "" if left == 1 else "s"
        return (
            f"{row['character_name']} advances: {left} objective{plural} "
            f"left on {what}."
        )
    if row["kind"] == "dungeon":
        # The FAMILY advances, not the beneficiary alone - a dungeon run needs
        # everybody, and the character_name on the row is who the council
        # named, not who is running it (see DriveDungeon's docstring).
        return f"The family advances: {observed} of {int(row['target'])} runs done on {what}."
    if row["kind"] == "skill":
        return f"{row['character_name']} advances: {row['skill_name']} {observed}, aiming for {what}."
    remaining = int(row["target"]) - observed
    return f"{row['character_name']} advances: level {observed}, {remaining} to go toward {what}."


def completion_text(row: Mapping, observed: int) -> str:
    what = _describe(
        row["kind"],
        row.get("skill_name"),
        int(row["target"]),
        int(row.get("quest_id") or 0),
    )
    if row["kind"] == "quest":
        # "Objectives done", NOT "quest finished". The turn-in is a separate
        # act the bot does for itself, and claiming the quest is complete here
        # would be the overseer over-reporting - the one thing this service
        # must never do.
        return (
            f"Goal complete: {row['character_name']} has no objectives "
            f"left on {what} and can hand it in."
        )
    if row["kind"] == "dungeon":
        return f"Goal complete: the family finished its campaign on {what}."
    return f"Goal complete: {row['character_name']} reached {what} (now at {observed})."


def _read_report(row: Mapping) -> tuple:
    """(last observed value, consecutive stalled cycles) from the goal row.

    Stored as "<value>" or "<value>/<stalls>". The bare form is what rows
    written before the stall counter existed look like, and it still reads
    correctly - a migration for one integer would be a schema change the
    module owns for no behavioral gain.
    """
    raw = row.get("last_report")
    if raw is None or not str(raw).strip():
        return None, 0
    text = str(raw).strip()
    value, _, stalls = text.partition("/")
    try:
        return int(value), int(stalls) if stalls else 0
    except ValueError:
        # A corrupt record must not wedge the goal; treat as first sighting.
        return None, 0


def _last_progress(row: Mapping) -> int | None:
    return _read_report(row)[0]


def _milestone_crossed(kind: str, last: int, observed: int) -> bool:
    if kind == "skill":
        return observed // SKILL_MILESTONE_STEP > last // SKILL_MILESTONE_STEP
    if kind == "quest":
        # Every objective closed is worth saying - "one more candle" is the
        # whole texture of what the family is doing, and there are only ever a
        # handful of them per quest, so this cannot become a flood.
        return observed > last
    return observed > last


def reconcile(row: Mapping, observed: int | None) -> list:
    """One supervision cycle for one goal row: state in, actions out.

    `row` is the persisted overseer_goal row (the ONLY memory - restarts
    must change nothing), `observed` the character's current level or skill
    value, or None when it cannot be seen (offline snapshot, unlearned
    skill). The action order matters: MarkComplete comes after the Report
    so a failed Discord send retries the announcement next cycle rather
    than completing silently.
    """
    if row.get("status") != "active":
        return []
    if observed is None:
        # Nothing visible to reconcile against; keep quiet rather than
        # command a character we cannot see. The next cycle retries.
        return []
    if row.get("kind") == "quest":
        # Its own branch, deliberately, rather than teaching the level branch
        # below to mean two things. It differs in the two ways that matter -
        # the action is an aim and not a strategy, and the aim is a LEASE that
        # expires whether or not progress is being made.
        return _reconcile_quest(row, observed)
    if row.get("kind") == "dungeon":
        # Its own branch for the same reason quest gets one: the action is a
        # family-wide job write, not a per-character strategy, and it is a
        # LEASE for the same reason a quest aim is - see DriveDungeon and
        # _reconcile_dungeon's docstrings.
        return _reconcile_dungeon(row, observed)
    if row.get("kind") == "skill":
        # Its own branch, and the branch that used to be missing. Falling
        # through to the level branch below is what made every skill goal issue
        # `nc +grind` - see strategy_for's docstring for what that cost and
        # _reconcile_skill for what replaces it.
        return _reconcile_skill(row, observed)
    name = row["character_name"]
    goal_id = int(row["id"])
    target = int(row["target"])
    if observed >= target:
        text = completion_text(row, observed)
        return [MilestoneThought(name, text), Report(text), MarkComplete(goal_id)]
    last, stalls = _read_report(row)
    if last is None:
        # First sighting: put the bot on task. Recording the observation is
        # what stops this re-issuing every cycle from here on.
        return [
            StrategyCommand(name, strategy_for(row)),
            RecordProgress(goal_id, observed),
        ]
    if observed == last:
        # No progress. Usually just a slow grind, but it is also exactly what a
        # lost strategy looks like, and the two are indistinguishable from
        # here - so re-assert on a cadence rather than trying to tell them
        # apart. The command is idempotent; issuing it to a bot already
        # grinding costs one whisper.
        if stalls + 1 >= REASSERT_AFTER_CYCLES:
            return [
                StrategyCommand(name, strategy_for(row)),
                RecordProgress(goal_id, observed),
            ]
        return [RecordProgress(goal_id, observed, stalls + 1)]
    actions: list = []
    if observed > last and _milestone_crossed(row["kind"], last, observed):
        text = milestone_text(row, observed)
        actions.append(MilestoneThought(name, text))
        actions.append(Report(text))
    actions.append(RecordProgress(goal_id, observed))
    return actions


def _reconcile_quest(row: Mapping, observed: int) -> list:
    """One supervision cycle for a kind='quest' goal.

    `observed` is -left (see observed_from_left), so it rises toward
    QUEST_TARGET = 0 exactly like a level rises toward its target, and the
    completion and milestone tests below read the same direction as everywhere
    else in this module.

    WHY THE AIM IS RE-ISSUED ON A CLOCK RATHER THAN ON A STALL. The level
    branch re-asserts only when nothing has moved, because a lost strategy and
    a slow grind are indistinguishable from here. A quest aim is different and
    worse: mod-playerbots' RPG_DO_QUEST status self-expires after
    statusDoQuestDuration = 30 minutes, and once it goes IDLE the bot re-rolls
    its own status - including picking a RANDOM quest out of its log. So the
    aim decays on a timer even while the family is making excellent progress,
    and a stall-triggered re-assert would never fire in exactly the case where
    everything looks healthiest. It is a lease, so it is renewed.

    The stall field on the goal row is reused as the lease counter. It is the
    only memory a restart preserves, and a counter held in the supervisor
    would reset on every deploy - which is precisely when an aim is most
    likely to have been lost.
    """
    name = row["character_name"]
    goal_id = int(row["id"])
    quest_id = int(row.get("quest_id") or 0)
    if observed >= QUEST_TARGET:
        text = completion_text(row, observed)
        return [MilestoneThought(name, text), Report(text), MarkComplete(goal_id)]

    last, leases = _read_report(row)
    # First sighting renews too: that is the aim actually being placed.
    renew = last is None or leases + 1 >= REASSERT_AFTER_CYCLES

    actions: list = []
    if renew and quest_id:
        actions.append(DriveQuest(quest_id=quest_id, beneficiary=name))
    if last is not None and _milestone_crossed("quest", last, observed):
        text = milestone_text(row, observed)
        actions.append(MilestoneThought(name, text))
        actions.append(Report(text))
    actions.append(RecordProgress(goal_id, observed, 0 if renew else leases + 1))
    return actions


def _reconcile_skill(row: Mapping, observed: int) -> list:
    """One supervision cycle for a kind='skill' goal (infra#3731).

    `observed` is `character_skills.value`, which rises toward `target` exactly
    as a level does, so the completion and milestone tests below need no
    negation the way a quest's do.

    RE-ASSERTED ON A STALL RATHER THAN ON A CLOCK, AND THAT IS THE OPPOSITE OF
    WHAT quest AND dungeon DO. The argument for a lease there is that the thing
    being renewed decays while progress looks healthy - mod-playerbots'
    RPG_DO_QUEST status self-expires after thirty minutes whether or not the
    family is doing well - so a stall-triggered renewal would never fire in
    exactly the case that needs it. A profession drive is not like that. The
    only thing that stops it is the family leaving the gather/craft rhythm, and
    leaving the rhythm ALWAYS stops the skill rising. So "the number has not
    moved" is a complete detector here, and it is a strictly better one than a
    clock: it never re-issues into a family that is already working.

    ONE COUNTER, TWO THRESHOLDS, AND IT IS NEVER RESET BY A RE-ASSERT. The level
    branch zeroes `stalls` when it re-issues, which is correct there because the
    counter's only job is pacing the re-issue. Here the same counter also has to
    reach SKILL_BARREN_CYCLES to say "this has been still for half an hour", and
    a counter zeroed by its own re-assert can never reach thirty. So it counts
    consecutive cycles without progress, full stop, and only real progress
    clears it; the two thresholds read it with `%` instead of `>=`.

    `observed != last` AND NOT `observed > last` IS THE PROGRESS TEST. A skill
    value cannot fall in the engine, so a fall means the read changed underneath
    us - a different character row, a reset, a bad join. Treating that as
    "stalled" would hold a counter high on the strength of a reading nobody
    trusts; treating it as movement re-opens the question next cycle, which is
    the conservative direction.

    WHAT IT DOES NOT DO IS DECIDE. `DriveSkill` carries facts; skillgoal.plan
    turns them into a job mode or into a refusal, because that needs
    professions.py and craft.py and this module is underneath both of them. See
    DriveSkill's own docstring.
    """
    name = row["character_name"]
    goal_id = int(row["id"])
    target = int(row["target"])
    skill_name = str(row.get("skill_name") or "")
    if observed >= target:
        text = completion_text(row, observed)
        return [MilestoneThought(name, text), Report(text), MarkComplete(goal_id)]

    skill_id = int(SKILL_IDS.get(skill_name, 0))
    if not skill_id:
        # A skill goal naming something SKILL_IDS does not have cannot be
        # observed either (bridge._observe_goal returns None for it and
        # reconcile never reaches this function), so this is unreachable by the
        # live path. It is written out anyway rather than assumed away: the
        # honest answer to "drive a skill I have no id for" is to record what
        # was seen and command nobody, never to fall through to a strategy.
        return [RecordProgress(goal_id, observed)]

    last, stalls = _read_report(row)
    if last is None:
        stalls = 0
    elif observed != last:
        stalls = 0
    else:
        stalls += 1

    # First sighting always drives - that is the goal actually being placed.
    # After that, only a run of stalled cycles does.
    drive = last is None or (stalls > 0 and stalls % REASSERT_AFTER_CYCLES == 0)
    speak = last is None or (stalls > 0 and stalls % SKILL_BARREN_CYCLES == 0)

    actions: list = []
    if drive:
        actions.append(
            DriveSkill(
                skill_name=skill_name,
                skill_id=skill_id,
                target=target,
                observed=observed,
                beneficiary=name,
                stalls=stalls,
                speak=speak,
            )
        )
    if last is not None and _milestone_crossed("skill", last, observed):
        text = milestone_text(row, observed)
        actions.append(MilestoneThought(name, text))
        actions.append(Report(text))
    actions.append(RecordProgress(goal_id, observed, stalls))
    return actions


def _reconcile_dungeon(row: Mapping, observed: int) -> list:
    """One supervision cycle for a kind='dungeon' goal.

    `observed` is dungeon_runs_done, read the same direction as a level: it
    rises toward `target` (DUNGEON_RUNS_WANTED, council.py), so the
    completion and milestone tests below need no negation the way a quest's
    do.

    RE-ASSERTED ON A CLOCK, LIKE A QUEST AIM AND FOR THE SAME REASON: the job
    this goal depends on can be knocked off the roster without the campaign
    itself having failed - a relog resets overseer_roster strategies, and
    mod-overseer's own bag-pressure evacuation (#423/#424/#430) will pull the
    family out of a run their bags cannot hold any more. A stall-triggered
    re-assert would never fire in exactly the case where the campaign is
    healthiest, same argument _reconcile_quest already makes.

    THE ACTION IS EMITTED UNCONDITIONALLY ON THE LEASE CLOCK. Whether writing
    it is safe THIS cycle - bags not already near-full - is a live-world fact
    this pure module cannot see; bridge.py checks it before turning the
    action into a write (see DriveDungeon's docstring). A skipped write here
    would also skip the lease renewal that is the only thing standing between
    a healthy campaign and a silently stale job.
    """
    name = row["character_name"]
    goal_id = int(row["id"])
    target = int(row["target"])
    keyword = str(row.get("skill_name") or "")
    if observed >= target:
        text = completion_text(row, observed)
        return [MilestoneThought(name, text), Report(text), MarkComplete(goal_id)]

    last, leases = _read_report(row)
    renew = last is None or leases + 1 >= REASSERT_AFTER_CYCLES

    actions: list = []
    if renew:
        actions.append(DriveDungeon(keyword=keyword, wanted=target, beneficiary=name))
    if last is not None and _milestone_crossed("dungeon", last, observed):
        text = milestone_text(row, observed)
        actions.append(MilestoneThought(name, text))
        actions.append(Report(text))
    actions.append(RecordProgress(goal_id, observed, 0 if renew else leases + 1))
    return actions
