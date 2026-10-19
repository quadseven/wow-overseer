"""How a character that already exists becomes a row in `overseer_roster`.

THE TABLE HAS NEVER HAD A WRITER THAT COULD ADD SOMEBODY NEW (infra#4241).
`bridge._ensure_roster` is one `INSERT IGNORE INTO overseer_roster (name, note)`
over `OVERSEER_NOTABLE_NAMES`, so it can only ever re-assert the five rows that
are already there; `tools/seed_roster.py` prints the same two columns for a
family taken from `bonds.FAMILY`, a hardcoded Python dict. Every other write
path in `bridge.py` is an UPDATE matching a name that is already present. So
the live table holds exactly five rows, all Cave's, and nothing in this
codebase can make it hold a sixth. That is the gap this module closes: given
characters that already exist in the world, it decides which of them may join a
cohort and what every column of their new row must say.

WHAT IT REFUSES TO DO, AND THE ORDER THOSE REFUSALS MATTER IN. It creates no
accounts and no characters: `Player::Create` is only wired into
`RandomPlayerbotFactory` in this pinned core, so a character is made by a
person at a game client and never server-side (see `tools/seed_roster.py` and
quadseven/infra's `production/oke/manifests/wow-dev/README.md`). It never re-homes a row that already
belongs to another cohort. And it refuses the whole enrollment, not merely a
candidate, when the world cannot yet tell two cohorts apart - see THE TWO
GATES below, which is the part of this file worth reading first.

PURE, LIKE `townslot` AND `bonkers`, FOR THE SAME REASON (infra#2597). Every
fact comes in as an argument and a plan comes out; the adapter
(`tools/enroll_cohort.py`) reads the world and executes. That split is what
lets the stdlib suite run the real statements against a real two-cohort table
instead of against a description of one.
"""

from __future__ import annotations

import dataclasses
import re

from core import _HORDE_RACES

# Reused rather than restated. `family.py` already imports this set from
# `core` for exactly this question, and a third copy of "which races are
# Horde" is a third thing to get wrong when a race is added.
HORDE_RACES = frozenset(_HORDE_RACES)

# WoW enforces 2-12 letters, and `overseer_roster.name` is VARCHAR(12). The
# same shape `core._NAME_RE` applies to anything that reaches SQL.
_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

# `overseer_roster.family` is VARCHAR(24), sized in mod-overseer#506 to hold
# either a character name (12) or a guild name (24, GUILD_NAME_MAX). A cohort
# key longer than the column is ERROR 1406, which MySQL raises rather than
# truncating - a refused INSERT, not a short one (infra#429).
MAX_COHORT = 24

# ENROLL A HANDFUL, NOT A GUILD. infra#4241's own test plan says to enroll a
# small number first, and the reason is in the two gates below: the module half
# of the control plane still reads every enabled row as one party, so the blast
# radius of getting this wrong scales with the batch. The cap is a refusal
# rather than a truncation, because silently enrolling the first N of a list
# somebody meant as a whole is the shape of bug this package keeps paying for.
DEFAULT_LIMIT = 8


# --- every column of a new row, and why it says what it says ----------------
#
# NOT THE DDL DEFAULTS, AND THE DIFFERENCE IS LOAD-BEARING. Every column below
# is NOT NULL with a DEFAULT, so an INSERT naming only (name, family) would be
# accepted and would produce a row nobody decided the contents of. One of those
# defaults is actively wrong for an enrolled row - see `dungeon_runs_wanted` -
# and the rest are right for a reason that has to be written down once rather
# than rediscovered per column. Naming all of them also means a migration that
# adds a column fails `tests/test_enroll.py` instead of quietly inheriting a
# default nobody chose (see ROSTER_COLUMNS).

ROSTER_DEFAULTS: dict[str, object] = {
    # 1 IS THE POINT OF ENROLLING AT ALL. `enabled = 0` is how a row is parked
    # by hand, and every read on both sides of the wire is `WHERE enabled = 1`,
    # so a disabled row is a row the control plane cannot see - which fails the
    # only acceptance criterion enrollment has. It is also the value that makes
    # the gates below mandatory rather than advisory: `enabled` is precisely
    # what mod-overseer's own unscoped reads select on.
    "enabled": 1,
    # Operator-facing, and it names the ticket rather than the cohort: the
    # cohort is in `family`, and a note that repeated it would be a second
    # place for it to disagree. VARCHAR(255), so this is nowhere near the cap.
    "note": "enrolled cohort member (infra#4241)",
    # NOBODY LEADS A COHORT THIS PROCESS CANNOT CHOOSE A LEADER FOR.
    # `bridge._mark_party_leader` writes `lead = IF(name = %s, 1, 0)` scoped to
    # the HEAD'S cohort, and the head comes from `bonds.head_of_family()`,
    # which is `max()` over a hardcoded Python dict of Cave's five. A second
    # cohort has no entry in it (infra#4221's audit, finding 3b), so nothing in
    # this codebase can choose, revise or clear a `lead` flag outside Cave. A
    # row enrolled with `lead = 1` would therefore be a leader no pass can ever
    # unset, and mod-overseer's KeepRosterGrouped enforces whatever it last
    # read. 0 is the only value that stays true.
    "lead": 0,
    # 255 is the DDL default and it means "no talent tree chosen". `bonds`
    # supplies `spec_tabs()` for Cave and has nothing to say about anybody
    # else, so choosing a tree here would be this module inventing an opinion
    # about a character it knows one row about.
    "spec_tab": 255,
    "trained_level": 0,
    # NO QUEST AIM. `seed_roster.py` gives the whole argument: only the
    # traveller is ever aimed, an aimed follower carries `new rpg` at relevance
    # 3.0-11.0 against follow's 1.0 and free-roams its own quest log, and
    # aiming five at once scattered the family across 937 yards and killed one
    # of them (infra#2812). An enrolled cohort has no traveller at all, so 0 is
    # the only aim that is true.
    "drive_quest": 0,
    # THE TRAVEL COLUMN ITSELF, AND IT MUST ARRIVE EMPTY. `townslot` arbitrates
    # exactly this string, and `townslot._reconcile` turns any value it does
    # not recognise into `Holder(claimant="", since=now)` - an ORPHAN on the
    # 1200s lease, with the clock starting again. Enrolling a non-empty aim
    # would manufacture orphans the ledger cannot out-wait (infra#4194), for
    # errands nobody issued.
    "travel_npc": "",
    # PERMISSION, NOT AN INSTRUCTION, and an empty one. `seed_roster.py`:
    # "the module will only ever learn a skill named there and will never
    # unlearn one that is, which is what makes a later wrong instruction
    # harmless". Empty is the safe end of that: a cohort whose professions
    # nobody has decided cannot be sent to a trainer by accident.
    "professions": "",
    # NO STANDING TRADE ERRAND. These three are an errand - go to this trainer
    # and do this thing - and `seed_roster.py` refuses to seed them for the
    # reason that applies here twice over: an errand seeded from a table rather
    # than observed from `character_skills` is an instruction to buy something
    # the character may already own. 0 is "no errand".
    "learn_skill": 0,
    "unlearn_skill": 0,
    "unlearn_max": 0,
    # THE ONE VALUE WIRED TO A BEHAVIOUR CHANGE IS THE ONE NOT CHOSEN HERE.
    # The column's own comment: "Only quest is wired to a behaviour change
    # today; every other value stands the quest drive down and nothing yet
    # replaces it." The DDL default is 'quest', so an INSERT that did not name
    # this column would set a cohort with no leader and no traveller driving
    # quests - every member free-roaming its own log, which is the 937-yard
    # scatter with nothing to converge on. 'rest' stands that drive down.
    #
    # AND THE HONEST CAVEAT, because 'rest' is not 'motionless': the playerbot
    # AI still wanders a resting character, and those deaths log as
    # driver=unattributed. Measured on this realm, moving a family to 'rest'
    # took the death rate from 10.5/hr to 4.6/hr, not to zero. It is the
    # quietest value available, not a stop button.
    "job": "rest",
    # THE ONE DDL DEFAULT THAT IS ACTIVELY WRONG FOR A NEW ROW, and the reason
    # this dict names every column instead of the interesting ones. The default
    # is 30. The column's own comment says the coordinator "asks whether done
    # >= wanted before it begins one", so a row created at 30 is a row that has
    # asked for thirty dungeon runs. An enrolled cohort has no party, no leader
    # and no campaign, and infra#4221's audit recorded that the writer of
    # `dungeon_runs_done` lives in mod-overseer and "is written to EVERY
    # enabled roster row alike" - unscoped, on the module side, which no PR in
    # that epic touched. So a row left at 30 both asks for a campaign nobody
    # will run and has its progress counter advanced by somebody else's runs.
    # 0 stops the campaign outright, which is the truthful state.
    "dungeon_runs_wanted": 0,
    "dungeon_runs_done": 0,
    # No queued craft. `bridge._forge_errands` selects `craft_spell > 0` and
    # aims a forge errand at what it finds; 0 is what keeps a new row out of
    # that pass's candidate list on its own merits rather than on the cohort
    # scope alone.
    "craft_spell": 0,
    "learn_fishing": 0,
}

# The columns the enrollment supplies per candidate rather than by default.
PER_CANDIDATE: tuple[str, ...] = ("name", "family")

# The columns the database fills in on its own.
DB_ASSIGNED: tuple[str, ...] = ("created_at",)

# EVERY COLUMN `overseer_roster` HAS, as of mod-overseer's migrations in
# data/sql/characters/base. Declared here so that `tests/test_enroll.py` can
# assert three separate things: that this list matches the migrations actually
# in the pinned submodule, that every column in it is accounted for by exactly
# one of the three groups above, and that the INSERT this module builds names
# all of them. A migration that adds a column then fails the suite naming the
# column, instead of shipping a row that silently inherited a default.
ROSTER_COLUMNS: tuple[str, ...] = (
    "name",
    "family",
    "enabled",
    "note",
    "created_at",
    "lead",
    "spec_tab",
    "trained_level",
    "drive_quest",
    "travel_npc",
    "professions",
    "learn_skill",
    "unlearn_skill",
    "unlearn_max",
    "job",
    "dungeon_runs_wanted",
    "dungeon_runs_done",
    "craft_spell",
    "learn_fishing",
)


# --- the refusals -----------------------------------------------------------
#
# Strings rather than an enum, for the reason `townslot` gives for its own
# verdicts: they appear in log lines and in test assertions, and a name that
# reads the same in both is worth more than type machinery here.

# Whole-plan refusals. These stop the enrollment, not a candidate.
GATE_NO_FAMILY_COLUMN = "the world cannot tell two cohorts apart"
GATE_MODULE_UNSCOPED = "the module still reads the roster as one party"
GATE_OVER_LIMIT = "too many at once"
GATE_BAD_COHORT = "the cohort key is not usable"
GATE_HOME_COHORT = "that is the cohort this process already drives"

# Per-candidate refusals.
NOT_A_NAME = "not a character name"
UNKNOWN = "no such character"
NOT_HORDE = "not Horde"
IN_A_GUILD = "already in a guild"
OTHER_COHORT = "already enrolled in another cohort"

# Not a refusal. An idempotent re-run finds its own rows and says so.
ALREADY_HERE = "already enrolled in this cohort"


@dataclasses.dataclass(frozen=True)
class Candidate:
    """What the adapter observed about one character, and nothing more.

    `guild_id` is 0 for guildless, which is what a LEFT JOIN onto
    `guild_member` yields. `cohort` is the `family` value of this character's
    existing `overseer_roster` row, or None when it has no row - the ordinary
    case, and the only one that can be enrolled.

    `exists` is separate from the rest on purpose: a name the realm has never
    heard of arrives here with everything else at its zero value, and a plan
    that could not tell that apart from a level-1 guildless Horde character
    would enrol a typo.
    """

    name: str
    exists: bool = False
    race: int = 0
    level: int = 0
    guild_id: int = 0
    cohort: str | None = None


@dataclasses.dataclass(frozen=True)
class Refusal:
    """One candidate that will not be enrolled, and the sentence saying why."""

    name: str
    reason: str


@dataclasses.dataclass(frozen=True)
class Plan:
    """What the adapter should write, what it will skip, and what it refused.

    `blocked` is the whole-plan gate, and it is checked FIRST: when it is set,
    `rows` is empty no matter how good the candidates were. That ordering is
    the fail-closed one, and `tests/test_enroll.py` pins it.
    """

    cohort: str
    rows: tuple[dict, ...] = ()
    skipped: tuple[Refusal, ...] = ()
    refused: tuple[Refusal, ...] = ()
    blocked: str = ""

    @property
    def will_write(self) -> bool:
        return not self.blocked and bool(self.rows)


def row_for(name: str, cohort: str) -> dict:
    """The complete row one enrolled character gets.

    Every column by name, in `ROSTER_COLUMNS` order minus the ones the database
    fills in. Built here rather than in `statements` so a test can read one row
    without parsing SQL.
    """
    row = {"name": name, "family": cohort}
    row.update(ROSTER_DEFAULTS)
    return row


# A verdict that means "nothing to do", not "you may not". Kept as a set so
# `plan` routes by membership rather than by a second `==` that could drift
# from `_verdict`'s own vocabulary.
_SKIPS = frozenset({ALREADY_HERE})


def blocked_by(
    *,
    cohort: str,
    home_cohort: str | None,
    has_family_column: bool,
    module_reads_family: bool,
    count: int,
    limit: int,
) -> str:
    """The whole-batch gates, in the order they are checked, or '' to proceed.

    SPLIT OUT OF `plan` RATHER THAN INLINE, so that "what stops the whole
    enrollment" and "which of these characters qualifies" are two things to
    read instead of one - the same division `townslot` draws between `decide`'s
    guards and `_free_column`'s turn-taking.

    THE ORDER IS NOT ARBITRARY. A malformed cohort key is checked before
    anything is compared against it; the home cohort before the deploy gates,
    so that "you are enrolling into the live family" is the answer an operator
    gets even on a world where the deploy has not happened; and the batch size
    last, because it is the only one a person can fix by asking for less.
    """
    if not cohort or len(cohort) > MAX_COHORT or not cohort.isascii():
        return GATE_BAD_COHORT
    if home_cohort and cohort == home_cohort:
        # Enrolling into the cohort this process already drives would hand
        # `bonds`-derived machinery characters it has no entry for: they would
        # be inside every family-wide scope, and `family_mode` would see rows
        # that cannot agree with the five it knows about. A second cohort is
        # the whole point; a bigger first one is a different change.
        return GATE_HOME_COHORT
    if not has_family_column:
        return GATE_NO_FAMILY_COLUMN
    if not module_reads_family:
        return GATE_MODULE_UNSCOPED
    if count > max(0, int(limit)):
        return GATE_OVER_LIMIT
    return ""


def verdict(candidate: Candidate, cohort: str) -> str:
    """Why this one character cannot be enrolled, or '' when it can.

    ONE CANDIDATE, NO BATCH STATE. Duplicate detection needs to know what the
    batch has already seen and therefore stays in `plan`; everything here is a
    question about the character alone, which is what makes each answer a fact
    rather than a position in a list.
    """
    name = (candidate.name or "").strip()
    if not _NAME_RE.match(name):
        return NOT_A_NAME
    if not candidate.exists:
        return UNKNOWN
    if candidate.race not in HORDE_RACES:
        return NOT_HORDE
    if candidate.guild_id:
        # A guild is the thing this cohort is being assembled to found
        # (infra#4239), and a character that is already in one cannot sign a
        # charter for another.
        return IN_A_GUILD
    if candidate.cohort == cohort:
        return ALREADY_HERE
    if candidate.cohort is not None:
        # RE-HOMING IS A DIFFERENT DECISION AND THIS IS NOT IT. Moving a row
        # between cohorts changes which leader flag governs it, which scoped
        # reads see it, and which party the module puts it in, all at once and
        # with nothing watching. An operator who means it can disable the row
        # and enrol it afresh.
        return OTHER_COHORT
    return ""


def plan(
    candidates,
    *,
    cohort: str,
    home_cohort: str | None,
    has_family_column: bool,
    module_reads_family: bool,
    limit: int = DEFAULT_LIMIT,
) -> Plan:
    """Who may be enrolled into `cohort`, and what stops the whole batch.

    THE TWO GATES, AND WHY NEITHER IS OPTIONAL. Both are facts about the
    deployed world rather than about the candidates, so both refuse the plan
    entire rather than a row of it.

    `has_family_column` is whether `overseer_roster` has the `family` column
    that mod-overseer#506 added. Every cohort-scoped statement in `bridge.py`
    resolves its scope through `_cohort_of`, which catches MySQL 1054 and
    returns None, and every caller then emits the table-wide statement it
    emitted before the scoping work existed. That degradation is correct with
    one cohort and catastrophic with two: it is exactly the set of bugs
    infra#4232, #4235 and #4236 fixed, re-armed. Enrolling into a world without
    the column does not produce a scoped system, it produces the unscoped one
    with a second cohort in it.

    `module_reads_family` is the half that is easy to forget. The BRIDGE has
    been cohort-aware for a while; `mod_overseer.cpp` was not. It carried about
    twenty `SELECT ... FROM overseer_roster WHERE enabled = 1` reads and no query
    in it named `family` - mod-overseer#506 shipped the column with no reader,
    deliberately and in as many words. `KeepRosterGrouped` was one of those
    reads: it took every enabled row, ordered by `lead`, and kept them in one
    permanent party, so a second cohort's rows enrolled into such a world were
    not merely unscoped, they were conscripted into the first cohort's party on
    every poll - which for a Horde cohort and an Alliance family is a party the
    core will not form, attempted for ever.

    mod-overseer#550-#553 changed that for the parts that matter to a cohort
    that has to be PLAYED: parties form per family, the quest drive runs once
    per family, and the one-campaign machinery (home binds, town trips, dungeon
    runs, guild founding) reads exactly one family and cannot be handed another
    family's characters. What it does NOT do yet is run two dungeon campaigns at
    once - that is one state machine - so a second cohort enrolled today is
    driven for parties and quests, not through dungeons. The flag is still an
    explicit operator assertion about the DEPLOYED module, not about the
    submodule this repository is pinned to; the source-reading tests below pin
    what the pin does, and only the operator knows what is rolled.

    So enrollment is gated on the deploy, and says so, rather than being
    something that works and then quietly breaks the family it was told not to
    touch. An operator who has rolled both halves passes both flags; nobody
    else can.
    """
    cohort = (cohort or "").strip()
    wanted = list(candidates)
    blocked = blocked_by(
        cohort=cohort,
        home_cohort=home_cohort,
        has_family_column=has_family_column,
        module_reads_family=module_reads_family,
        count=len(wanted),
        limit=limit,
    )
    if blocked:
        return Plan(cohort=cohort, blocked=blocked)

    rows: list[dict] = []
    skipped: list[Refusal] = []
    refused: list[Refusal] = []
    seen: set[str] = set()
    for candidate in wanted:
        name = (candidate.name or "").strip()
        if name and name in seen:
            # A name twice in one batch is one row, not two. The PRIMARY KEY
            # would refuse the second anyway; saying so here means the count
            # the operator reads is the count that lands.
            skipped.append(Refusal(name=name, reason=ALREADY_HERE))
            continue
        reason = verdict(candidate, cohort)
        if not reason:
            seen.add(name)
            rows.append(row_for(name, cohort))
        elif reason in _SKIPS:
            seen.add(name)
            skipped.append(Refusal(name=name, reason=reason))
        else:
            # The RAW name, not the stripped one: a refusal for not being a
            # character name has to show the operator what they actually typed.
            refused.append(Refusal(name=candidate.name, reason=reason))

    return Plan(
        cohort=cohort, rows=tuple(rows), skipped=tuple(skipped), refused=tuple(refused)
    )


# INSERT, NOT INSERT IGNORE, AND THAT IS THE OPPOSITE CHOICE TO
# `bridge._ensure_roster`. That function re-asserts the same five rows every
# cycle and must not undo a row somebody parked by hand, so IGNORE is right
# there. This runs once, on a batch a person chose, after a plan that has
# already asked the roster which of them have rows. An IGNORE here would turn
# "this character was enrolled between the plan and the write" into silence,
# and the count the operator reads would be a count of statements rather than
# of rows. A duplicate key is a real answer and belongs in the open.
_COLUMNS = tuple(c for c in ROSTER_COLUMNS if c not in DB_ASSIGNED)
INSERT_SQL = (
    # noqa anchored on the FIRST line of the expression, not on a line that
    # carries a `+` or a `%`: ruff reports S608 at the START of a multi-line
    # expression, so a marker further down does not silence it. `bridge.py`
    # records the same gotcha next to `_BOT_HELD_SQL`.
    "INSERT INTO overseer_roster ("  # noqa: S608 - the only thing interpolated is a column NAME from ROSTER_COLUMNS, a literal tuple thirty lines above; every VALUE travels as a bound parameter and test_enroll.test_no_value_reaches_the_statement_text pins that
    + ", ".join("`%s`" % c for c in _COLUMNS)
    + ") VALUES ("
    + ", ".join(["%s"] * len(_COLUMNS))
    + ")"
)


def statements(plan_: Plan) -> tuple[tuple[str, tuple], ...]:
    """The (sql, params) pairs that enact `plan_`, or nothing at all.

    FULLY PARAMETERIZED, AND THE SQL IS A CONSTANT. `INSERT_SQL` is built once
    from `ROSTER_COLUMNS`, which is a literal in this file; nothing a candidate
    or a cohort key carries ever reaches the statement text. That is the same
    rule `bridge.py` follows for its own dynamic IN-lists, and it is why this
    module can hand an adapter SQL to execute without the adapter needing to
    quote anything.

    A blocked plan yields no statements. That is the fail-closed half of the
    gates and the thing worth testing first: a caller that ignored `blocked`
    and executed whatever came back still writes nothing.
    """
    if plan_.blocked:
        return ()
    return tuple((INSERT_SQL, tuple(row[c] for c in _COLUMNS)) for row in plan_.rows)


def report(plan_: Plan) -> str:
    """One sentence an operator reads before anything is written."""
    if plan_.blocked:
        return "enrollment into %r is refused: %s" % (plan_.cohort, plan_.blocked)
    parts = ["%d to enrol into %r" % (len(plan_.rows), plan_.cohort)]
    if plan_.skipped:
        parts.append(
            "%d already there (%s)"
            % (len(plan_.skipped), ", ".join(r.name for r in plan_.skipped))
        )
    if plan_.refused:
        parts.append(
            "%d refused (%s)"
            % (
                len(plan_.refused),
                ", ".join("%s: %s" % (r.name, r.reason) for r in plan_.refused),
            )
        )
    return "; ".join(parts)
