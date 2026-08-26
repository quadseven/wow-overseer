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
}

# 3.3.5a caps. Targets outside these bounds are not goals: the parser stays
# conservative and lets the voice treat the text as ordinary words instead
# of persisting something unreachable.
MAX_LEVEL = 80
MAX_SKILL = 450

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
GOAL_KINDS = ("level", "skill", "quest")
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
    """
    if not kind_column_type:
        # No `kind` column means no table (the caller's information_schema
        # lookup found nothing). Returning the ADD COLUMN here would emit an
        # ALTER against a table that does not exist yet - and it must return
        # BOTH or NEITHER, since a half-shaped answer is what a reader would
        # copy next time.
        return []
    out = []
    if "'quest'" not in kind_column_type:
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

    Skill goals ride the same strategy: gathering and combat skills rise while
    grinding, and no profession-specific strategy exists to issue instead -
    the supervisor's job is staying on task and reporting, not crafting
    rotations (out of scope on infra#2601).
    """
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


def life_strategies(*, leads: bool, aimed: bool = False) -> list:
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

    The cost of getting this wrong the other way is the thing Evan actually
    complained about: the healer 600 yards away in her own fight, three fights
    in three sub-zones, and Grug charging three mobs with nobody to heal him.
    """
    if leads:
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


def already_working(kind: str, target: int, active: list, *, quest_id: int = 0) -> bool:
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
    return any(
        row.get("kind") == kind and int(row.get("target", -1)) == int(target)
        for row in active
    )


def _describe(kind: str, skill_name: str | None, target: int, quest_id: int = 0) -> str:
    if kind == "skill":
        return f"{skill_name} {target}"
    if kind == "quest":
        # The id, not the title. A title would have to be stored somewhere,
        # and the only spare column is skill_name - one column meaning two
        # things is how a schema starts lying. The council's own sentence is
        # already in the goal's reason and says the title out loud.
        return f"quest {quest_id}"
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
    what = _describe(row["kind"], row.get("skill_name"), int(row["target"]),
                     int(row.get("quest_id") or 0))
    if row["kind"] == "quest":
        left = -int(observed)
        plural = "" if left == 1 else "s"
        return (f"{row['character_name']} advances: {left} objective{plural} "
                f"left on {what}.")
    if row["kind"] == "skill":
        return f"{row['character_name']} advances: {row['skill_name']} {observed}, aiming for {what}."
    remaining = int(row["target"]) - observed
    return f"{row['character_name']} advances: level {observed}, {remaining} to go toward {what}."


def completion_text(row: Mapping, observed: int) -> str:
    what = _describe(row["kind"], row.get("skill_name"), int(row["target"]),
                     int(row.get("quest_id") or 0))
    if row["kind"] == "quest":
        # "Objectives done", NOT "quest finished". The turn-in is a separate
        # act the bot does for itself, and claiming the quest is complete here
        # would be the overseer over-reporting - the one thing this service
        # must never do.
        return (f"Goal complete: {row['character_name']} has no objectives "
                f"left on {what} and can hand it in.")
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
