"""Enrolling a second cohort, and proving the first one does not notice.

infra#4241. `overseer_roster` has five rows and nothing in this codebase can
give it a sixth: `bridge._ensure_roster` re-asserts names it already has,
`tools/seed_roster.py` prints the same two columns for a family that is a
hardcoded Python dict, and every other roster write is an UPDATE matching a
name that is already present. `enroll.py` is the write path that was missing.

WHAT THIS FILE HAS TO PROVE, AND WHY EACH HALF IS HARD ON ITS OWN.

  1. THE ROW IS COMPLETE. Every column of `overseer_roster` is NOT NULL with a
     DEFAULT, so an INSERT naming two of them is accepted and produces a row
     nobody decided. The suite reads the real migrations out of the pinned
     mod-overseer submodule, so a migration that adds a column fails here
     naming the column rather than shipping a row that inherited a default.
     One of those defaults is actively wrong for a new row and the test below
     reads BOTH values out of the source to say so.

  2. THE GATES HOLD. Enrollment is refused entirely on two facts about the
     deployed world, and the second is the one that binds today. The bridge is
     cohort-scoped (infra#4232, #4235, #4236, all merged); `mod_overseer.cpp`
     is not, and it is the half that logs characters in and groups them. The
     test that pins this reads the pinned submodule, so the day mod-overseer
     gains the reader is a failing test rather than a discovery.

  3. CAVE IS UNAFFECTED. Not asserted - measured, with the technique
     `tests/test_cohort_scope.py` built for infra#4221 and imported from it
     rather than copied. Cave's five real rows are put in a table, the real
     statements are lifted out of `bridge.py` and run over it, and the result
     is compared against the same run over a table with three enrolled rows
     added. The comparison is of Cave's rows only, cell by cell.

WHY SQLITE, AND THE SAME HONESTY `test_cohort_scope` STATES. `bridge.py`
imports discord and is not importable here by design, there is no MySQL in this
job, and the statements are simple enough that SQLite runs them with the two
documented substitutions that file's `_sqlite` asserts are total.

WHAT THIS DOES NOT COVER, ON PURPOSE. Whether Bonkers can travel. It cannot,
and `TheEnrolledCohortCannotTakeTheTravelColumn` below proves that rather than
assuming it - which is the honest state of the single-traveller question
infra#4221 left open and infra#4241 asked to answer. Making a second cohort
travel needs a leader model `bonds.py` does not have, and that is its own
issue, not this one.
"""

import importlib.util
import pathlib
import re
import sqlite3
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
# HERE is already the tests directory, so this is one hop to the repo root,
# where the mod-overseer submodule is checked out.
ROOT = HERE.parents[0]
SQL_DIR = ROOT / "mod-overseer" / "data" / "sql" / "characters" / "base"
MODULE = ROOT / "mod-overseer" / "src" / "mod_overseer.cpp"

sys.path.insert(0, str(HERE.parents[0]))
import enroll  # noqa: E402
import townslot  # noqa: E402

# THE HARNESS IS IMPORTED, NOT COPIED, and that is the point of importing it.
# `_statement`, `_assigned` and `_sqlite` lift the real SQL out of `bridge.py`
# and translate it; a second copy here would drift from the one infra#4221's
# own proof runs, and the two suites would then disagree about what the bridge
# emits while both stayed green. Reverting a scope clause in `bridge.py` must
# break this file for the same reason it breaks that one.
from test_cohort_scope import (  # noqa: E402
    _assigned,
    _sqlite,
    _statement,
)

# The adapter, loaded by path the way `test_verify_named_cohort` loads its own:
# `tools/` is not a package and its scripts are not importable by name. Only
# the pure read helpers are exercised, with a fake cursor - nothing here opens
# a connection, and `_connect` is never called.
_SPEC = importlib.util.spec_from_file_location(
    "enroll_cohort", HERE.parents[0] / "tools" / "enroll_cohort.py"
)
TOOL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(TOOL)


# --- reading the real schema out of the pinned submodule --------------------


def _sql_text() -> str:
    """Every roster migration, prose stripped, in filename order.

    Filename order is apply order: AzerothCore's updater runs this directory
    sorted, and the dated prefixes are what make that deterministic.

    THE PROSE HAS TO GO, AND EVERY LINE OF IT. These migrations carry far more
    explanation than DDL - the `family` one is a hundred lines of argument
    around a single ALTER - and that prose contains semicolons, quotes, the
    word `family` in English, and at least one worked EXAMPLE of an
    `ADD COLUMN` statement (2026_08_24_02_overseer_event.sql:92 offers
    ``ADD COLUMN `whatever` INT UNSIGNED NOT NULL DEFAULT 0`` as a
    demonstration). An earlier version of this reader kept any line carrying
    `ADD COLUMN` so that the guarded one-line ALTERs survived, and duly
    reported a column called `whatever`. Nothing is exempt: the guarded ALTERs
    live inside a double-quoted string and carry no `--` of their own, and no
    real DEFAULT in this directory sits behind one.
    """
    out = []
    for path in sorted(SQL_DIR.glob("*.sql")):
        for line in path.read_text(encoding="utf-8").splitlines():
            out.append(line.split("--", 1)[0])
    return "\n".join(out)


_ALTER_RE = re.compile(r"ALTER TABLE\s+`?(\w+)`?")
# The tail is bounded to its OWN LINE. `[^,"]*` was the first attempt and it is
# greedy over newlines, so one column's match ran on through the blank lines
# left by the stripped prose and swallowed the next `ADD COLUMN` whole -
# `finditer` is non-overlapping, so three columns vanished from a completeness
# check without a word. Every DEFAULT in these migrations sits on the same line
# as its ADD COLUMN, so the line is the honest bound.
_ADD_RE = re.compile(r"ADD COLUMN\s+`(\w+)`([^\n,\"]*)")
_DEFAULT_RE = re.compile(r"\bDEFAULT\s+('(?:[^']|'')*'|[^\s,]+)", re.I)
_CREATE_RE = re.compile(r"CREATE TABLE\s+`overseer_roster`\s*\((.*?)\n\)", re.S)
_CREATE_COL_RE = re.compile(r"^\s*`(\w+)`\s", re.M)


def declared_columns() -> dict[str, str | None]:
    """Every `overseer_roster` column the migrations declare, to its DEFAULT.

    The DEFAULT comes back as the SQL literal, quotes included, or None where
    the column has none - it is compared against another value read out of the
    same source, never against a value this file made up.

    BOTH DDL SHAPES ARE READ. The older migrations are plain `ALTER TABLE ...
    ADD COLUMN`; the newer guarded ones (`job`, `dungeon_runs_*`, `family`)
    hide the same ALTER inside a double-quoted string handed to PREPARE,
    because `ADD COLUMN IF NOT EXISTS` is a parse error on this pipeline's
    MySQL 8.4.11 and an unguarded re-apply crash-loops db-import. A reader that
    saw only one shape would silently miss half the table.

    EACH `ADD COLUMN` IS ATTRIBUTED TO ITS NEAREST PRECEDING `ALTER TABLE`
    RATHER THAN TO A STATEMENT SLICED AT THE NEXT SEMICOLON. Slicing was the
    obvious reading and it was wrong: `spec_tab`'s COMMENT contains a semicolon
    in ordinary English, so the statement appeared to end in the middle of
    itself and `trained_level` - plus all three of `professions`' siblings -
    went missing. Four columns silently absent from a completeness check is the
    exact failure that check exists to prevent, so the parse does not depend on
    knowing where a statement ends.
    """
    text = _sql_text()
    create = _CREATE_RE.search(text)
    assert create, "no CREATE TABLE overseer_roster in %s" % SQL_DIR
    columns: dict[str, str | None] = {}
    body = create.group(1)
    for name in _CREATE_COL_RE.findall(body):
        line = next(
            ln for ln in body.splitlines() if ln.strip().startswith("`%s`" % name)
        )
        found = _DEFAULT_RE.search(line)
        columns[name] = found.group(1) if found else None
    altered = [(m.start(), m.group(1)) for m in _ALTER_RE.finditer(text)]
    for add in _ADD_RE.finditer(text):
        owner = ""
        for pos, table in altered:
            if pos > add.start():
                break
            owner = table
        if owner != "overseer_roster":
            continue
        found = _DEFAULT_RE.search(add.group(2))
        columns[add.group(1)] = found.group(1) if found else None
    return columns


class TheRowIsComplete(unittest.TestCase):
    """Every column named, every value chosen, nothing left to a DDL default."""

    def test_the_declared_schema_is_the_one_enroll_knows_about(self):
        """A migration that adds a column fails here, naming the column.

        THE DIRECTION THAT MATTERS IS BOTH. A column in the migrations that
        `enroll` has never heard of is a row that would inherit a default
        nobody chose. A column in `enroll` that the migrations do not have is
        an INSERT that fails whole with ERROR 1054 the first time it is run.
        """
        declared = set(declared_columns())
        self.assertEqual(
            sorted(declared),
            sorted(enroll.ROSTER_COLUMNS),
            "enroll.ROSTER_COLUMNS disagrees with mod-overseer's migrations; "
            "a new roster column needs a deliberate value in "
            "enroll.ROSTER_DEFAULTS before anything may be enrolled",
        )

    def test_every_column_is_accounted_for_exactly_once(self):
        groups = (
            set(enroll.ROSTER_DEFAULTS),
            set(enroll.PER_CANDIDATE),
            set(enroll.DB_ASSIGNED),
        )
        union: set = set()
        for group in groups:
            self.assertEqual(union & group, set(), "a column is in two groups at once")
            union |= group
        self.assertEqual(sorted(union), sorted(enroll.ROSTER_COLUMNS))

    def test_the_insert_names_every_column_it_writes(self):
        named = set(re.findall(r"`(\w+)`", enroll.INSERT_SQL))
        self.assertEqual(
            named, set(enroll.ROSTER_COLUMNS) - set(enroll.DB_ASSIGNED) | {"family"}
        )
        # One placeholder per named column, so a column added to the list
        # without a value cannot produce a statement MySQL accepts.
        self.assertEqual(enroll.INSERT_SQL.count("%s"), len(named))

    def test_no_value_reaches_the_statement_text(self):
        """The SQL is a constant; every value travels bound.

        `enroll.statements` hands an adapter SQL to execute without the adapter
        needing to quote anything, so the property that makes that safe is
        worth pinning rather than assuming.
        """
        plan = _plan(["Mozkisdo"])
        ((sql, params),) = enroll.statements(plan)
        self.assertEqual(sql, enroll.INSERT_SQL)
        self.assertNotIn("Mozkisdo", sql)
        self.assertNotIn("Bonkers", sql)
        self.assertIn("Mozkisdo", params)
        self.assertIn("Bonkers", params)

    def test_the_dungeon_campaign_default_is_overridden_and_the_ddl_proves_it(self):
        """The one DDL default that is wrong for a new row.

        BOTH NUMBERS ARE READ OUT OF SOURCE. The 30 comes from the migration
        text, the 0 from `enroll.ROSTER_DEFAULTS`. A test that restated either
        would keep passing if the other changed, which is exactly how a row
        starts asking for a campaign nobody will run.
        """
        declared = declared_columns()
        self.assertEqual(
            declared["dungeon_runs_wanted"],
            "30",
            "the migration's default changed; re-read the "
            "argument in enroll.ROSTER_DEFAULTS before adjusting",
        )
        self.assertEqual(enroll.ROSTER_DEFAULTS["dungeon_runs_wanted"], 0)

    def test_the_job_default_is_overridden_away_from_the_driving_value(self):
        declared = declared_columns()
        self.assertEqual(declared["job"], "'quest'")
        self.assertNotEqual(enroll.ROSTER_DEFAULTS["job"], "quest")

    def test_an_enrolled_row_holds_no_aim_and_no_lead(self):
        row = enroll.row_for("Mozkisdo", "Bonkers")
        self.assertEqual(row["travel_npc"], "")
        self.assertEqual(row["drive_quest"], 0)
        self.assertEqual(row["lead"], 0)
        self.assertEqual(row["professions"], "")
        self.assertEqual(row["learn_skill"], 0)
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["family"], "Bonkers")


# --- the gates --------------------------------------------------------------


def _candidate(name: str, **kw) -> enroll.Candidate:
    facts = {"exists": True, "race": 2, "level": 60, "guild_id": 0, "cohort": None}
    facts.update(kw)
    return enroll.Candidate(name=name, **facts)


def _plan(names, **kw) -> enroll.Plan:
    """A plan with both gates open, so a test can vary one thing at a time."""
    facts = {
        "cohort": "Bonkers",
        "home_cohort": "Grug",
        "has_family_column": True,
        "module_reads_family": True,
    }
    facts.update(kw)
    people = [n if isinstance(n, enroll.Candidate) else _candidate(n) for n in names]
    return enroll.plan(people, **facts)


class TheGatesRefuseTheWholeBatch(unittest.TestCase):
    """Two facts about the deployed world, and neither is per-candidate."""

    def test_a_world_without_the_family_column_is_refused(self):
        """The degradation that is correct with one cohort and fatal with two.

        Every cohort-scoped statement in `bridge.py` resolves through
        `_cohort_of`, which catches MySQL 1054 and returns None, and every
        caller then emits the table-wide statement it emitted before the
        scoping work existed. Enrolling into such a world does not produce a
        scoped system with two cohorts in it. It produces the UNSCOPED one with
        two cohorts in it, which is every bug infra#4232/#4235/#4236 fixed,
        re-armed and silent.
        """
        plan = _plan(["Mozkisdo"], has_family_column=False)
        self.assertEqual(plan.blocked, enroll.GATE_NO_FAMILY_COLUMN)
        self.assertEqual(plan.rows, ())
        self.assertFalse(plan.will_write)

    def test_a_world_whose_module_ignores_the_column_is_refused(self):
        plan = _plan(["Mozkisdo"], module_reads_family=False)
        self.assertEqual(plan.blocked, enroll.GATE_MODULE_UNSCOPED)
        self.assertEqual(plan.rows, ())

    def test_a_blocked_plan_yields_no_statements_at_all(self):
        """The fail-closed half, and the one worth testing first.

        A caller that ignored `blocked` and executed whatever `statements`
        returned still writes nothing. That is what makes the gate a gate
        rather than a suggestion the adapter is trusted to read.
        """
        for gate in (
            {"has_family_column": False},
            {"module_reads_family": False},
            {"cohort": "Grug"},
            {"cohort": "x" * (enroll.MAX_COHORT + 1)},
        ):
            with self.subTest(**gate):
                plan = _plan(["Mozkisdo", "Biannise"], **gate)
                self.assertTrue(plan.blocked)
                self.assertEqual(enroll.statements(plan), ())

    def test_enrolling_into_the_home_cohort_is_refused(self):
        plan = _plan(["Mozkisdo"], cohort="Grug")
        self.assertEqual(plan.blocked, enroll.GATE_HOME_COHORT)

    def test_the_home_cohort_is_compared_as_read_not_as_a_literal(self):
        """A renamed world must refuse its own cohort too.

        `cast.py` renames the family in a validation world, so the head there
        is not spelled 'Grug' and the roster's `family` values are not either.
        A gate pinned to the literal would let somebody enrol straight into the
        live family of such a world. The comparison is against `home_cohort` as
        the adapter READ it, so it travels with the rename.
        """
        plan = _plan(["Mozkisdo"], cohort="Durn", home_cohort="Durn")
        self.assertEqual(plan.blocked, enroll.GATE_HOME_COHORT)
        # And the same name is perfectly enrollable when it is not home.
        plan = _plan(["Mozkisdo"], cohort="Durn", home_cohort="Grug")
        self.assertEqual(plan.blocked, "")

    def test_a_batch_larger_than_the_limit_is_refused_not_truncated(self):
        """infra#4241's own test plan: enrol a handful, not all of them.

        REFUSED RATHER THAN TRUNCATED. Enrolling the first N of a list somebody
        meant as a whole is a partial write that reads as a successful one, and
        the operator's count would be right while the roster's was not.
        """
        # Letters only: `enroll._NAME_RE` is WoW's own 2-12 letter rule, so a
        # fixture with a digit in it would be refused for the wrong reason and
        # this test would pass without exercising the cap at all.
        names = ["Name" + chr(ord("a") + i) for i in range(enroll.DEFAULT_LIMIT + 1)]
        plan = _plan(names)
        self.assertEqual(plan.blocked, enroll.GATE_OVER_LIMIT)
        self.assertEqual(plan.rows, ())
        # One fewer is fine, so the cap is the cap and not an off-by-one.
        self.assertEqual(len(_plan(names[:-1]).rows), enroll.DEFAULT_LIMIT)


# --- reading the pinned C++ -------------------------------------------------

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
# C++ concatenates adjacent string literals, and every SQL statement in the
# module is written that way - one literal per source line. Collapsing the
# `" "` joins first is what turns a query split over four lines into one
# string to search, instead of four fragments where `overseer_roster` is in one
# and the column names are in the next.
_JOIN_RE = re.compile(r'"\s*"', re.S)
_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _code(text: str) -> str:
    """The module's code with its prose removed and its literals joined.

    Same first step as `test_job_mode._code`, and for the same reason: this
    file is more comment than code, and a match against comment text is a test
    that passes on an explanation of the thing rather than on the thing.
    """
    text = _BLOCK_COMMENT_RE.sub("", text)
    text = "\n".join(line.split("//", 1)[0] for line in text.splitlines())
    return _JOIN_RE.sub("", text)


class TheModuleReadsTheRosterPerFamily(unittest.TestCase):
    """What the pinned module now does about a second cohort, read off its source.

    THIS CLASS WAS A TRIPWIRE AND IT WENT OFF, which is what it was for. It used
    to assert that no roster query in the module named `family` and that
    `KeepRosterGrouped` took every enabled row into one party, and its docstring
    said it was meant to fail the day mod-overseer gained a cohort-scoped read.
    mod-overseer#550-#553 are that day, so it is rewritten to pin the NEW truth
    rather than deleted: a test that could only ever report the old bad news
    would stop protecting anything the moment the news changed.

    What is pinned is what the module now guarantees, and, just as important,
    what it deliberately does NOT yet:

      * GUARANTEED: parties, quest drives and the one-campaign machinery
        (home binds, town trips, dungeon runs, guild founding) each read one
        family, never the whole table.
      * NOT YET: two families running their own dungeon campaigns at once. The
        dungeon run is still a single state machine, so a second family is
        driven for parties and quests and is not yet driven through dungeons.
    """

    def setUp(self):
        self.code = _code(MODULE.read_text(encoding="utf-8"))
        self.queries = [
            q for q in _LITERAL_RE.findall(self.code) if "overseer_roster" in q
        ]

    def test_the_family_column_is_read_by_a_query_of_its_own(self):
        """`family` is a LATE column, so it is read alone and never inside a
        drive's main roster query: an older schema then costs the second-family
        feature and nothing else (test_schema_degrade pins the other half)."""
        naming = [q for q in self.queries if "family" in q]
        self.assertTrue(naming, "no roster query names `family` any more")
        for query in naming:
            self.assertNotIn(
                "`lead`", query, "the family read has crept into a main roster query"
            )

    def test_keep_roster_grouped_partitions_by_family(self):
        """The read that used to conscript a second cohort into the first's party."""
        start = self.code.index("void KeepRosterGrouped()")
        body = self.code[start : start + 3500]
        self.assertIn("PartitionRosterByFamily", body)
        self.assertIn("KeepFamilyGrouped", body)

    def test_the_campaign_drives_read_one_family(self):
        """Home binds, town trips, dungeon runs and guild founding go through
        one census that returns a single family's roster."""
        uses = self.code.count("LoadCampaignRoster(")
        self.assertGreaterEqual(
            uses,
            5,
            "expected the census plus its four callers (home bind, town trip, "
            "dungeon run, guild founding); a caller has gone back to reading "
            "the whole table",
        )

    def test_the_quest_drive_runs_once_per_family(self):
        self.assertIn("DriveFamilyQuests(", self.code)
        start = self.code.index("void DriveQuests()")
        self.assertIn("PartitionRosterByFamily", self.code[start : start + 6000])

    def test_many_roster_reads_still_select_on_enabled_alone(self):
        """Not one read, a class of them, and most are correct as they are:
        event hooks that want every name. Scoping the rest is mod-overseer's own
        slice; this only notices if the class vanishes without anyone deciding."""
        unscoped = [
            q for q in self.queries if "FROM overseer_roster WHERE enabled = 1" in q
        ]
        self.assertGreater(
            len(unscoped),
            3,
            "the module's whole-table roster reads have largely gone; re-read "
            "enroll.plan's second gate",
        )


# --- the per-candidate refusals ---------------------------------------------


class TheCandidatesAreChecked(unittest.TestCase):
    def test_an_unknown_name_is_refused_rather_than_dropped(self):
        """A typo must not become a smaller batch that looks successful."""
        plan = _plan([_candidate("Nobody", exists=False)])
        self.assertEqual(plan.rows, ())
        self.assertEqual(
            [(r.name, r.reason) for r in plan.refused], [("Nobody", enroll.UNKNOWN)]
        )

    def test_an_alliance_character_is_refused(self):
        # race 1 is Human. A cross-faction cohort cannot found one guild.
        plan = _plan([_candidate("Alfred", race=1)])
        self.assertEqual(plan.rows, ())
        self.assertEqual(plan.refused[0].reason, enroll.NOT_HORDE)

    def test_a_character_already_in_a_guild_is_refused(self):
        plan = _plan([_candidate("Mozkisdo", guild_id=7)])
        self.assertEqual(plan.rows, ())
        self.assertEqual(plan.refused[0].reason, enroll.IN_A_GUILD)

    def test_a_row_belonging_to_another_cohort_is_never_rehomed(self):
        """Moving a row between cohorts changes three things at once.

        Which leader flag governs it, which scoped reads see it, and which
        party the module puts it in. An operator who means it can disable the
        row and enrol it afresh; this path will not do it by accident.
        """
        plan = _plan([_candidate("Grug", cohort="Grug")])
        self.assertEqual(plan.rows, ())
        self.assertEqual(plan.refused[0].reason, enroll.OTHER_COHORT)

    def test_re_enrolling_the_same_cohort_is_a_skip_and_writes_nothing(self):
        plan = _plan([_candidate("Mozkisdo", cohort="Bonkers")])
        self.assertEqual(plan.rows, ())
        self.assertEqual(plan.skipped[0].reason, enroll.ALREADY_HERE)
        self.assertEqual(enroll.statements(plan), ())
        self.assertEqual(plan.blocked, "")

    def test_a_name_twice_in_one_batch_is_one_row(self):
        plan = _plan(["Mozkisdo", "Mozkisdo"])
        self.assertEqual([r["name"] for r in plan.rows], ["Mozkisdo"])
        self.assertEqual(len(plan.skipped), 1)

    def test_something_that_is_not_a_character_name_is_refused(self):
        for bad in (
            "",
            "x",
            "Mozkisdo'; DROP TABLE overseer_roster; --",
            "Averyverylongname",
            "Moz kisdo",
            "Mozkisd0",
        ):
            with self.subTest(bad=bad):
                plan = _plan([_candidate(bad)])
                self.assertEqual(plan.rows, ())
                self.assertEqual(plan.refused[0].reason, enroll.NOT_A_NAME)

    def test_a_good_batch_survives_a_bad_neighbour(self):
        """One refusal does not cost the rest their turn, and the report says
        exactly which is which."""
        plan = _plan(["Mozkisdo", _candidate("Alfred", race=1), "Biannise"])
        self.assertEqual([r["name"] for r in plan.rows], ["Mozkisdo", "Biannise"])
        self.assertEqual([r.name for r in plan.refused], ["Alfred"])
        self.assertIn("2 to enrol", enroll.report(plan))
        self.assertIn("Alfred", enroll.report(plan))


# --- what actually lands in the table ---------------------------------------
#
# Cave's five rows as `acore_characters.overseer_roster` held them on wow-dev
# on 2026-09-19, read back with a SELECT and copied here. Not a plausible
# fixture: the point of the comparison below is that it is run against the real
# shape of the live table, including Grug holding an 'auctioneer' aim and a
# `craft_spell` on four of the five.
#
# `family` is NOT in this tuple because the live table has no such column. It
# is supplied by the fixture's own DEFAULT, exactly as mod-overseer#506's
# backfill supplies it, which is what makes CAVE below the right value.
CAVE = "Grug"

# name, enabled, lead, spec_tab, drive_quest, travel_npc, professions, job,
# dungeon_runs_wanted, craft_spell
LIVE_CAVE_ROWS = (
    ("Bork", 1, 0, 1, 0, "", "165,393", "quest", 25, 2881),
    ("Grog", 1, 0, 2, 0, "", "186,202", "quest", 25, 3918),
    ("Grug", 1, 1, 2, 0, "auctioneer", "164,186", "quest", 25, 2660),
    ("Og", 1, 0, 2, 0, "", "197,333", "quest", 25, 0),
    ("Ugga", 1, 0, 1, 0, "", "171,182", "quest", 25, 2330),
)

_CREATE = (
    "CREATE TABLE overseer_roster ("
    "  name TEXT PRIMARY KEY,"
    "  enabled INTEGER NOT NULL DEFAULT 1,"
    "  note TEXT NOT NULL DEFAULT '',"
    # `lead` is a reserved word in MySQL 8 (the LEAD() window function) and
    # every statement under test backticks it, so the fixture must accept that.
    "  `lead` INTEGER NOT NULL DEFAULT 0,"
    "  spec_tab INTEGER NOT NULL DEFAULT 255,"
    "  trained_level INTEGER NOT NULL DEFAULT 0,"
    "  drive_quest INTEGER NOT NULL DEFAULT 0,"
    "  travel_npc TEXT NOT NULL DEFAULT '',"
    "  professions TEXT NOT NULL DEFAULT '',"
    "  learn_skill INTEGER NOT NULL DEFAULT 0,"
    "  unlearn_skill INTEGER NOT NULL DEFAULT 0,"
    "  unlearn_max INTEGER NOT NULL DEFAULT 0,"
    "  job TEXT NOT NULL DEFAULT 'quest',"
    # 30, as the migration declares it, so that an enrollment which forgot to
    # override it would show up here as a 30 rather than as a 0.
    "  dungeon_runs_wanted INTEGER NOT NULL DEFAULT 30,"
    "  dungeon_runs_done INTEGER NOT NULL DEFAULT 0,"
    "  craft_spell INTEGER NOT NULL DEFAULT 0,"
    "  learn_fishing INTEGER NOT NULL DEFAULT 0,"
    # NOT NULL DEFAULT 'Grug', exactly as mod-overseer#506 declares it, which
    # is what backfills Cave's rows into one cohort with no statement to run.
    "  family TEXT NOT NULL DEFAULT 'Grug')"
)

_SEED = (
    "INSERT INTO overseer_roster (name, enabled, `lead`, spec_tab, "
    "drive_quest, travel_npc, professions, job, dungeon_runs_wanted, "
    "craft_spell) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

# The columns Cave's behaviour is compared on: EVERY column the fixture has.
# `created_at` is the only one left out, because the fixture does not carry it
# and a timestamp is the one value two runs are entitled to disagree about.
# Naming the rest exhaustively is what makes "bit-for-bit unchanged" a
# measurement rather than a claim about the columns somebody remembered.
_COMPARED = (
    "name, enabled, note, `lead`, spec_tab, trained_level, drive_quest, "
    "travel_npc, professions, learn_skill, unlearn_skill, unlearn_max, job, "
    "dungeon_runs_wanted, dungeon_runs_done, craft_spell, learn_fishing, family"
)


def _table(extra_rows=()) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute(_CREATE)
    db.executemany(_SEED, LIVE_CAVE_ROWS)
    for sql, params in extra_rows:
        db.execute(_sqlite(sql), params)
    return db


def _cave(db: sqlite3.Connection) -> list:
    return list(
        db.execute(
            # noqa anchored on the first line of the expression: ruff reports S608
            # at the START of a multi-line one. The only thing interpolated is
            # `_COMPARED`, a literal column list forty lines above; the cohort key
            # is bound.
            "SELECT %s FROM overseer_roster WHERE family = ? ORDER BY name"  # noqa: S608
            % _COMPARED,
            (CAVE,),
        )
    )


def _all(db: sqlite3.Connection) -> list:
    return list(db.execute("SELECT %s FROM overseer_roster ORDER BY name" % _COMPARED))  # noqa: S608 - `_COMPARED` is a literal column list in this file


# The three characters enrolled below are real, and were confirmed on wow-dev
# on 2026-09-19 to exist, to be level 60, to be Horde, to be guildless and to
# have no roster row: Mozkisdo (Orc warrior), Biannise (Undead priest),
# Knongul (Tauren druid). Which characters Bonkers ends up with is infra#4162's
# decision and not this file's; these are here so the fixture is a real
# enrollment rather than an imagined one.
BONKERS_NAMES = ("Mozkisdo", "Biannise", "Knongul")


def _enrollment():
    return enroll.statements(_plan(list(BONKERS_NAMES)))


class TheEnrollmentWritesWhatItSaysItWrites(unittest.TestCase):
    """Run the real statements and read the rows back, column by column."""

    def test_the_rows_land_with_every_column_set(self):
        db = _table(_enrollment())
        rows = list(
            db.execute(
                "SELECT %s FROM overseer_roster WHERE family = 'Bonkers' "  # noqa: S608 - `_COMPARED` is a literal column list in this file; 'Bonkers' is this test's own constant
                "ORDER BY name" % _COMPARED
            )
        )
        self.assertEqual([r[0] for r in rows], sorted(BONKERS_NAMES))
        columns = [c.strip().strip("`") for c in _COMPARED.split(",")]
        for row in rows:
            # strict=True, and it is not a lint appeasement: a SELECT that
            # returned fewer columns than `_COMPARED` names would otherwise
            # silently compare a prefix of the row and report every remaining
            # column as untested. This is a completeness check, so a length
            # mismatch has to be an error.
            got = dict(zip(columns, row, strict=True))
            want = enroll.row_for(got["name"], "Bonkers")
            for column, value in want.items():
                with self.subTest(name=got["name"], column=column):
                    self.assertEqual(got[column], value)
        db.close()

    def test_the_campaign_counter_lands_at_zero_not_at_the_ddl_default(self):
        """The fixture's DEFAULT is 30; a row that inherited it reads as 30.

        This is the test that would have caught an INSERT naming only (name,
        family), which is the shape `bridge._ensure_roster` uses and the one
        an enrollment path would most plausibly have copied.
        """
        db = _table(_enrollment())
        wanted = list(
            db.execute(
                "SELECT DISTINCT dungeon_runs_wanted FROM overseer_roster "
                "WHERE family = 'Bonkers'"
            )
        )
        self.assertEqual(wanted, [(0,)])
        # And Cave's own 25 is untouched, so this is an override and not a
        # table-wide clear wearing one as a disguise.
        cave = list(
            db.execute(
                "SELECT DISTINCT dungeon_runs_wanted FROM overseer_roster "
                "WHERE family = ?",
                (CAVE,),
            )
        )
        self.assertEqual(cave, [(25,)])
        db.close()

    def test_enrolling_twice_writes_three_rows_and_then_refuses(self):
        """The PRIMARY KEY is the backstop, and a duplicate is not swallowed.

        `INSERT`, not `INSERT IGNORE`: this runs once on a batch a person
        chose, after a plan that already asked the roster who has a row. An
        IGNORE would turn "somebody was enrolled between the plan and the
        write" into silence and make the operator's count a count of
        statements rather than of rows.
        """
        db = _table(_enrollment())
        self.assertEqual(len(_all(db)), len(LIVE_CAVE_ROWS) + 3)
        with self.assertRaises(sqlite3.IntegrityError):
            for sql, params in _enrollment():
                db.execute(_sqlite(sql), params)
        db.close()


class _Bonds:
    """Just enough of `bonds` for `_aim_traveller`'s cohort expression.

    `bridge.py` resolves that function's cohort as
    `_cohort_of(bonds.head_of_family())`, and evaluating the real expression
    means supplying the names it reaches for. Stubbed rather than imported
    because `bonds` resolves its family from the environment at import time and
    this file has no business setting that.
    """

    @staticmethod
    def head_of_family() -> str:
        return "Grug"


def _chain(func: str) -> tuple:
    """`bridge.py`'s OWN cohort derivation, evaluated end to end.

    WHY THE WHOLE CHAIN AND NOT JUST THE CLAUSE. The first version of these
    tests supplied `scope=" AND family = %s"` to `_statement` and asserted
    separately that the function assigns that clause when `cohort` is truthy.
    Both halves passed, and a deliberate mutation of `bridge.py` - replacing
    `cohort = _cohort_of(head)` with `cohort = None` - was caught by NEITHER,
    because the clause was still chosen correctly for a `cohort` the test had
    handed it. That is a check that can only report good news: it proves the
    statement is right and says nothing about whether the bridge builds it.

    So `cohort` is evaluated from the function's own expression with
    `_cohort_of` stubbed to answer, `scope` is evaluated from `cohort`, and the
    statement is built from both. Severing any link in that chain in
    `bridge.py` now changes what these tests run.
    """
    cohort = _assigned(
        func,
        "cohort",
        {"_cohort_of": lambda _name: CAVE, "bonds": _Bonds(), "head": "Grug"},
    )
    scope = _assigned(func, "scope", {"cohort": cohort})
    return cohort, scope


class CaveIsUnaffected(unittest.TestCase):
    """The before/after comparison, run rather than asserted.

    THE TECHNIQUE IS infra#4221's, and the statements are lifted out of
    `bridge.py` by the helpers imported from `test_cohort_scope`. Nothing below
    compares against SQL this file made up, so reverting a cohort scope in
    `bridge.py` fails these tests as well as that suite's.
    """

    def test_the_enrollment_itself_touches_no_cave_row(self):
        """It only ever INSERTs, and the rows it inserts are new ones."""
        before = _cave(_table())
        after = _cave(_table(_enrollment()))
        self.assertEqual(before, after)
        self.assertEqual(len(before), len(LIVE_CAVE_ROWS))

    def test_the_bridge_still_derives_its_cohort_from_the_roster(self):
        """The link a supplied `scope` cannot test: where `cohort` comes from.

        `_cohort_of` reads the row, and reading it is what makes the scope
        survive a world that renames the cast. A bridge that hardcoded the
        cohort, or stopped resolving one, passes every statement-shaped
        assertion and fails this.
        """
        for func in ("_mark_party_leader", "_aim_traveller"):
            with self.subTest(func=func):
                cohort, scope = _chain(func)
                self.assertEqual(cohort, CAVE)
                self.assertIn("family = %s", scope)
        # And the degradation is still the documented one: no column, no scope,
        # and today's exact statement.
        self.assertEqual(_assigned("_mark_party_leader", "scope", {"cohort": None}), "")
        self.assertEqual(_assigned("_aim_traveller", "scope", {"cohort": None}), "")

    def test_cave_keeps_its_leader_when_the_other_cohort_has_one(self):
        """`_mark_party_leader` had no WHERE clause at all before infra#4232.

        THE DAMAGE RUNS BOTH WAYS AND THE FIXTURE HAS TO SHOW BOTH. An enrolled
        row arrives with `lead = 0`, so a table-wide write that zeroed it would
        change nothing visible and a test comparing only Cave's rows would pass
        against the reverted bridge. This plants a leader on the enrolled
        cohort - the state that exists the day a second cohort gets one - and
        then runs Cave's own write over it. Two cohorts each zeroing the
        other's leader every protect cycle, with nothing logged, is the bug;
        this is what its absence looks like.
        """
        cohort, scope = _chain("_mark_party_leader")
        sql, params = _statement(
            "_mark_party_leader", 0, head="Grug", scope=scope, cohort=cohort
        )
        plain = _table()
        plain.execute(_sqlite(sql), params)
        mixed = _table(_enrollment())
        mixed.execute(
            "UPDATE overseer_roster SET `lead` = 1 WHERE name = ?", ("Mozkisdo",)
        )
        mixed.execute(_sqlite(sql), params)
        # Cave is unchanged by the presence of the other cohort...
        self.assertEqual(_cave(plain), _cave(mixed))
        # ...and Cave's write did not take the other cohort's leader away.
        leads = dict(
            mixed.execute(
                "SELECT name, `lead` FROM overseer_roster WHERE family = 'Bonkers'"
            )
        )
        self.assertEqual(leads, {"Mozkisdo": 1, "Biannise": 0, "Knongul": 0})
        plain.close()
        mixed.close()

    def test_a_cave_quest_aim_leaves_the_enrolled_rows_alone(self):
        """`_aim_traveller`'s clear-everyone-else half.

        Before infra#4232 it was `SET drive_quest = 0 WHERE drive_quest <> 0
        AND name NOT IN (<Cave>)`, so every Bonkers row was cleared every time
        Cave aimed at anything. Nothing logs a cleared aim; the character
        simply free-roams its own quest log again, which is the 937-yard
        scatter arriving in the other guild with no cause anywhere near it.
        """
        cohort, scope = _chain("_aim_traveller")
        mixed = _table(_enrollment())
        # Give one enrolled row an aim, so "left alone" is a value that could
        # visibly change rather than a zero that cannot.
        mixed.execute(
            "UPDATE overseer_roster SET drive_quest = 554 WHERE name = ?", ("Knongul",)
        )
        before = _cave(mixed)
        mixed.execute(
            # noqa on the first line of the expression, where ruff anchors a
            # multi-line S608. `scope` is not a value: it is the clause
            # `bridge._aim_traveller` itself chose, read out of its source by
            # `_chain`, and the cohort key it names is bound below.
            _sqlite(
                "UPDATE overseer_roster SET drive_quest = 0 "  # noqa: S608
                "WHERE drive_quest <> 0 AND name NOT IN (%s, %s)" + scope
            ),
            ("Grug", "Ugga", cohort),
        )
        self.assertEqual(_cave(mixed), before)
        kept = list(
            mixed.execute(
                "SELECT drive_quest FROM overseer_roster WHERE name = ?", ("Knongul",)
            )
        )
        self.assertEqual(kept, [(554,)])
        mixed.close()

    def test_the_no_holders_branch_also_spares_the_enrolled_rows(self):
        """The unconditional table-wide clear, which had no name bound at all.

        `_aim_traveller`'s other branch ran `SET drive_quest = 0 WHERE
        drive_quest <> 0` with nothing else, every time Cave aimed at nothing.
        """
        cohort, scope = _chain("_aim_traveller")
        mixed = _table(_enrollment())
        mixed.execute(
            "UPDATE overseer_roster SET drive_quest = 554 WHERE name = ?", ("Knongul",)
        )
        mixed.execute(
            _sqlite(
                "UPDATE overseer_roster SET drive_quest = 0 "  # noqa: S608 - `scope` is the clause bridge._aim_traveller chose, read out of its source by `_chain`; the cohort key is bound
                "WHERE drive_quest <> 0" + scope
            ),
            (cohort,),
        )
        kept = list(
            mixed.execute(
                "SELECT drive_quest FROM overseer_roster WHERE name = ?", ("Knongul",)
            )
        )
        self.assertEqual(kept, [(554,)])
        mixed.close()

    def test_caves_own_family_wide_read_returns_exactly_its_five(self):
        """The read side, which is what every drive is gated on.

        A read that came back with eight names would put the enrolled cohort
        inside `family_mode`, `standing_mode` and `should_activate` - three
        unanimity functions that return "no agreement" the instant two groups
        disagree, standing Cave's own drives down silently.
        """
        mixed = _table(_enrollment())
        names = [
            r[0]
            for r in mixed.execute(
                "SELECT name FROM overseer_roster WHERE enabled = 1 "
                "AND family = ? ORDER BY name",
                (CAVE,),
            )
        ]
        self.assertEqual(names, sorted(r[0] for r in LIVE_CAVE_ROWS))
        # The unscoped read is what the module still does, and it is why the
        # second gate exists. Stated here as a measured fact, not a warning.
        everyone = [
            r[0]
            for r in mixed.execute(
                "SELECT name FROM overseer_roster WHERE enabled = 1 ORDER BY name"
            )
        ]
        self.assertEqual(len(everyone), len(LIVE_CAVE_ROWS) + 3)
        mixed.close()


class TheAdapterNeverAsksForAColumnThatIsNotThere(unittest.TestCase):
    """The two crashes the first live dry run found, pinned so they stay found.

    NEITHER OF THESE WAS CAUGHT BY ANYTHING ABOVE, and that is why they are
    here. Every test in this file exercises `enroll.py`, which is pure and knew
    perfectly well that the gate was closed. The adapter asked the database
    `SELECT family` BEFORE the gate could refuse, so against wow-dev on
    2026-09-19 - a world that genuinely has no `family` column - the tool died
    twice with a PyMySQL traceback and error 1054. An operator's first contact
    with the enrollment path would have been a stack trace that reads like a
    broken tool, instead of the sentence naming the gate that is closed.

    THE FAKE CURSOR REFUSES THE COLUMN THE WAY MYSQL DOES. It raises on any
    statement naming `family`, so a fix that only reordered the calls without
    removing the question would still fail here.
    """

    class _Cursor:
        """A cursor for a world with no `family` column."""

        def __init__(self, rows=()):
            self.rows = list(rows)
            self.asked = []

        def execute(self, sql, params=()):
            self.asked.append(sql)
            if "family" in sql:
                raise AssertionError(
                    "the adapter asked for `family` on a world without it: %s" % sql
                )

        def fetchall(self):
            return list(self.rows)

        def fetchone(self):
            return self.rows[0] if self.rows else None

    def test_the_home_cohort_is_not_asked_for_when_it_cannot_be_answered(self):
        cur = self._Cursor()
        self.assertIsNone(TOOL.home_cohort(cur, "Grug", present=False))
        self.assertEqual(cur.asked, [])

    def test_the_roster_read_drops_the_column_it_cannot_select(self):
        cur = self._Cursor(
            [{"name": "Mozkisdo", "race": 2, "level": 60, "guild_id": 0}]
        )
        found = TOOL.candidates(cur, ["Mozkisdo"], present=False)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].exists)
        # A row exists but whose cohort is unknowable, which `enroll.plan`
        # refuses rather than treats as enrollable.
        self.assertEqual(found[0].cohort, "")
        plan = _plan([found[0]])
        self.assertEqual(plan.rows, ())
        self.assertEqual(plan.refused[0].reason, enroll.OTHER_COHORT)

    def test_the_column_is_still_read_when_the_world_has_it(self):
        """The guard is a guard and not a permanent amputation."""
        asked = []

        class Cursor(self._Cursor):
            def execute(self, sql, params=()):
                asked.append(sql)

        cur = Cursor([{"name": "Grug", "family": "Grug"}])
        self.assertEqual(TOOL.home_cohort(cur, "Grug", present=True), "Grug")
        self.assertIn("family", asked[0])


class TheEnrolledCohortCannotTakeTheTravelColumn(unittest.TestCase):
    """The single-traveller question infra#4221 left open, answered by proof.

    THE COLUMN IS NOT A COHORT'S, IT IS ONE CHARACTER'S. `townslot` arbitrates
    `overseer_roster.travel_npc` on exactly the character `bridge._head_now()`
    names, and `townslot.decide` refuses any other character outright. An
    enrolled row arrives with `lead = 0` and an empty aim, and `bonds.FAMILY`
    is a hardcoded Python dict with no entry for a second cohort, so nothing in
    this codebase can name an enrolled character as the leader.

    SO "DOES BONKERS SHARE CAVE'S COLUMN" HAS NO ANSWER YET, and this is what
    that looks like in code rather than in prose. A second cohort cannot
    contend for the column because it cannot have a traveller at all, and
    giving it one needs a leader model `bonds.py` does not have. That is the
    follow-up, not this change, and these tests are what make the claim
    checkable rather than a paragraph in a PR.
    """

    def test_an_enrolled_character_is_refused_the_traveller(self):
        decision = townslot.decide(
            claimant="guild bank",
            character="Mozkisdo",
            aim="banker",
            leader="Grug",
            column="",
            retaskable=(),
            holder=None,
            wants=[],
            last_served={},
            now=0.0,
        )
        self.assertEqual(decision.verdict, townslot.SLOT_NOT_THE_LEADER)
        self.assertFalse(decision.granted)
        self.assertFalse(decision.writes)

    def test_an_enrolled_row_registers_no_want_and_so_ranks_nowhere(self):
        """It cannot even queue, which is why #4227's ordering is untouched.

        infra#4227 fixed `_ahead_of` to rank a pass by its own recorded wait.
        That comparator runs between CLAIMANTS - pass names like 'guild bank'
        and 'flight' - inside one ledger, and has no notion of a cohort. An
        enrolled character never reaches it, so enrollment cannot make that
        starvation worse. The fix is cohort-agnostic already.
        """
        slot = townslot.Slot(releasable=lambda _aim: True)
        decision = slot.want(
            claimant="guild bank",
            character="Mozkisdo",
            aim="banker",
            leader="Grug",
            column="",
            retaskable=(),
            now=0.0,
        )
        self.assertEqual(decision.verdict, townslot.SLOT_NOT_THE_LEADER)
        self.assertEqual(slot.wants, [])

    def test_caves_own_claim_is_unchanged_by_the_enrolled_rows(self):
        """The same ledger, the same grant, with three more rows in the table.

        The ledger holds no roster state at all - `Slot` is keyed on claimant
        and reconciles against one leader's column - so this passing is the
        evidence that enrollment is inert here rather than merely harmless.
        """
        slot = townslot.Slot(releasable=lambda _aim: True)
        decision = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="",
            retaskable=(),
            now=0.0,
        )
        self.assertEqual(decision.verdict, townslot.SLOT_TAKE)
        self.assertEqual(decision.character, "Grug")

    def test_an_enrolled_row_holds_no_aim_for_the_ledger_to_adopt(self):
        """An unrecognised value in the column becomes an ORPHAN on the long
        lease (infra#4194), so a non-empty enrolled aim would be a lease
        nobody can out-wait. The row arrives empty, and `_reconcile` turns an
        empty column into None."""
        self.assertEqual(enroll.ROSTER_DEFAULTS["travel_npc"], "")
        self.assertIsNone(townslot._reconcile(None, leader="Grug", column="", now=0.0))


if __name__ == "__main__":
    unittest.main()
