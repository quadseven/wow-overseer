"""The six roster reads that name a character and then act on it.

infra#4221, and the second half of the change infra#4232 started. That one
scoped the three roster WRITES that had no cohort bound. This one scopes six of
the twelve READS the same audit classified `NEEDS_COHORT_SCOPE`, chosen because
each of them produces a NAME and something in the same cycle then writes for
that name:

    _fetch_enabled_names   the job fan-out list; _set_job inserts one
                           overseer_command row per name returned
    _errand_holders        the candidate list _release_trade_errand blanks
                           travel_npc on
    _errand_traveller      ORDER BY t.id LIMIT 1, and the one row it returns
                           becomes the family's leader and carries `new rpg`
    _train_members         family_mode() over these rows; mixed cohorts return
                           '' and trainjob.plan refuses for ever
    _raidprep_members      raidprep's own copy of family_mode, same failure
    _learn_aim_rows        reads `lead` and travel_npc, then learnaim writes
                           travel_npc and learn_skill back

None of them has ever misbehaved, because `overseer_roster` has never held a
second cohort's rows. That is the difficulty: there is no production symptom to
reproduce, no log line, nothing in a dashboard. So this suite builds the second
cohort the live table does not have and runs both shapes against it in SQLite:

  * the shape each read had BEFORE this change, spelled out below as historical
    constants, to show the contamination is real and not theoretical;
  * the shape `bridge.py` emits NOW, lifted out of its own source and evaluated
    with its own `scope` expression, to show it is gone.

THE SECOND HALF IS WHAT MAKES THIS A TEST AND NOT A DEMONSTRATION, and it is
the same discipline tests/test_cohort_scope.py established: reverting any one
of the six WHERE clauses makes the matching "leaves the other cohort alone"
test fail, because the SQL under test is read out of `bridge.py` rather than
restated here. Nothing below asserts against a string this file made up.

THE HARNESS IS IMPORTED, NOT COPIED. `test_cohort_scope` already owns the AST
lifting, the MySQL-to-SQLite translation and the two cohort names, and a second
copy of them would be a second place for the rule to drift - which is the exact
argument infra#4221 makes for one cohort column over a forked schema. Importing
one test module from another is the precedent test_raidcraft.py sets.

WHY SQLITE AND WHY THAT IS HONEST. `bridge.py` imports discord and is not
importable here by design, there is no MySQL in this job - the whole matrix runs
stdlib-only with no pip install - and the statements are simple enough to
translate with substitutions that are each asserted to have applied. A statement
that grew a construct the translation does not know about fails here, either on
the assertion or on SQLite refusing to parse it, rather than being quietly
half-translated into something that passes for a different reason.

WHAT THIS DOES NOT COVER, on purpose. The other six NEEDS_COHORT_SCOPE reads
are a separate change in the same batch (`_crafting_roster`, `_standing_jobs`,
`_standing_travel_aims`, `_activate_training`, `_roster_jobs`,
`_forge_errands`). `_aimed_names` and `_travelling_names` are deliberately NOT
scoped at all and are not tested here - the audit is explicit that scoping them
reintroduces infra#3423, the nineteen-minutes-motionless bug. And whether one
bridge process should serve both cohorts or one each is still open on
infra#4221; it decides whether `overseer_trade` and `overseer_goal` need
columns of their own, and it does not change whether these six reads are right.
"""

import ast
import re
import sqlite3
import unittest

from test_cohort_scope import (
    CAVE,
    OTHER,
    _assigned,
    _bridge_source,
    _evaluate,
    _function_code,
    _sqlite,
    _statement,
)

# ---------------------------------------------------------------------------
# The six statements as they stood before this change.
#
# Verbatim, including the single spaces the source's implicit string
# concatenation produced. They are here to be RUN, not to be compared against
# prose: the tests below execute them against a two-cohort table and assert
# they do the damage the audit said they would.

HISTORIC_ENABLED_NAMES = "SELECT name FROM overseer_roster WHERE enabled = 1"

HISTORIC_TRAIN_MEMBERS = (
    "SELECT name, job, professions, learn_skill FROM overseer_roster WHERE enabled = 1"
)

HISTORIC_RAIDPREP_MEMBERS = (
    "SELECT name, job, professions, level FROM overseer_roster WHERE enabled = 1"
)

HISTORIC_LEARN_AIM_ROWS = (
    "SELECT name, `lead`, professions, travel_npc, learn_skill "
    "FROM overseer_roster WHERE enabled = 1"
)

HISTORIC_ERRAND_TRAVELLER = (
    "SELECT r.name FROM overseer_roster r "
    "JOIN overseer_trade t "
    "  ON t.character_name COLLATE utf8mb4_unicode_ci = r.name "
    "WHERE r.enabled = 1 AND r.learn_skill <> 0 "
    "AND t.verb = 'learn' AND t.skill_id = r.learn_skill "
    "AND t.status = 'planned' "
    "AND t.decided_at > NOW() - INTERVAL %s HOUR "
    "ORDER BY t.id LIMIT 1"
)

# `_errand_holders` builds its statement from a module constant, so the
# historical shape is that constant with its name-list interpolated and nothing
# appended. Read out of bridge.py rather than restated, for the same reason as
# everything else here: a test that spelled out the finished SQL would be
# testing its own guess at the construction.

ERRAND_LEAD_HOURS = 6.0


def _module_constant(name: str):
    """The value bridge.py assigns to a module-level constant.

    `_assigned` walks a FunctionDef and `_ERRAND_HOLDERS_SQL` is not inside
    one. Same principle though: read it rather than restate it, so a change to
    the constant reaches these tests instead of being shadowed by a copy.
    """
    for node in ast.parse(_bridge_source()).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == name for t in node.targets
        ):
            return _evaluate(node.value, {})
    raise AssertionError("%s is not a module-level constant in bridge.py" % name)


# ---------------------------------------------------------------------------
# Two more dialect substitutions, for the one statement that needs them.
#
# `_errand_traveller` is the only read here that joins, and its join carries
# the COLLATE that keeps the utf8mb4_unicode_ci / utf8mb4_0900_ai_ci split from
# raising MySQL 1267 every cycle. SQLite has neither collation nor INTERVAL, so
# both are rewritten - and EACH SUBSTITUTION ASSERTS IT APPLIED. A statement
# that stopped carrying the COLLATE, or whose freshness bound changed shape,
# fails here rather than being translated into something else that passes.
#
# The clause these tests are about passes through all of this untouched.

_COLLATE = re.compile(r"\s+COLLATE\s+utf8mb4_unicode_ci\b")
_INTERVAL = re.compile(r"NOW\(\)\s*-\s*INTERVAL\s*\?\s*HOUR")


def _sqlite_join(sql: str) -> str:
    out = _sqlite(sql)
    out, collated = _COLLATE.subn("", out)
    assert collated == 1, "expected exactly one COLLATE to rewrite: %r" % sql
    out, bounded = _INTERVAL.subn(
        "datetime('now', '-' || ? || ' hours')",
        out,
    )
    assert bounded == 1, "expected exactly one INTERVAL bound to rewrite: %r" % sql
    return out


# ---------------------------------------------------------------------------
# The two-cohort roster.
#
# CAVE is the value every row in the live table carries, because
# mod-overseer#506's column is NOT NULL DEFAULT 'Grug' and the ALTER backfills
# every existing row in one pass. OTHER is a second cohort no database has yet.
# Who is in it is deliberately not the point and is explicitly out of scope on
# infra#4221 - all that matters below is that a second family's rows exist.

# name, enabled, lead, job, professions, learn_skill, level, travel_npc, family
_TWO_COHORTS = (
    ("Grug", 1, 1, "quest", "blacksmithing", 164, 60, "", CAVE),
    ("Ugga", 1, 0, "quest", "tailoring", 0, 60, "", CAVE),
    ("Grog", 1, 0, "quest", "mining", 0, 60, "vendor", CAVE),
    ("Bork", 1, 0, "quest", "skinning", 0, 60, "", CAVE),
    ("Og", 1, 0, "quest", "alchemy", 0, 60, "", CAVE),
    # Disabled, and in this cohort: proves `enabled = 1` is still doing its own
    # job and has not been replaced by the cohort predicate.
    ("Snik", 0, 0, "quest", "herbalism", 0, 60, "", CAVE),
    ("Blammo", 1, 1, "craft", "engineering", 202, 41, "", OTHER),
    ("Hexmama", 1, 0, "raid prep", "enchanting", 0, 44, "vendor", OTHER),
    ("Moojuice", 1, 0, "gather", "leatherworking", 0, 38, "", OTHER),
)

_ONE_COHORT = tuple(row for row in _TWO_COHORTS if row[8] == CAVE)

_CAVE_ENABLED = sorted(r[0] for r in _TWO_COHORTS if r[8] == CAVE and r[1])
_ALL_ENABLED = sorted(r[0] for r in _TWO_COHORTS if r[1])

# id, character_name, verb, skill_id, status, decided_at
#
# THE OTHER COHORT'S ROW HAS THE LOWER id, WHICH IS THE WHOLE POINT for
# `_errand_traveller`: it orders by `t.id` and takes one row. A Bonkers errand
# decided before this family's simply wins the lead.
_TRADES = (
    (11, "Blammo", "learn", 202, "planned"),
    (12, "Grug", "learn", 164, "planned"),
)


def _roster(rows=None) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE overseer_roster ("
        "  name TEXT PRIMARY KEY,"
        "  enabled INTEGER NOT NULL DEFAULT 1,"
        # Backticked here too: `lead` is a reserved word in MySQL 8 and the
        # statement under test quotes it, so the fixture has to accept that.
        "  `lead` INTEGER NOT NULL DEFAULT 0,"
        "  job TEXT NOT NULL DEFAULT '',"
        "  professions TEXT NOT NULL DEFAULT '',"
        "  learn_skill INTEGER NOT NULL DEFAULT 0,"
        "  level INTEGER NOT NULL DEFAULT 0,"
        "  travel_npc TEXT NOT NULL DEFAULT '',"
        # NOT NULL DEFAULT 'Grug', exactly as mod-overseer#506 declares it.
        "  family TEXT NOT NULL DEFAULT 'Grug')"
    )
    db.executemany(
        "INSERT INTO overseer_roster "
        "(name, enabled, `lead`, job, professions, learn_skill, level, "
        " travel_npc, family) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        _TWO_COHORTS if rows is None else rows,
    )
    db.execute(
        "CREATE TABLE overseer_trade ("
        "  id INTEGER PRIMARY KEY,"
        "  character_name TEXT NOT NULL,"
        "  verb TEXT NOT NULL,"
        "  skill_id INTEGER NOT NULL,"
        "  status TEXT NOT NULL,"
        "  decided_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    db.executemany(
        "INSERT INTO overseer_trade "
        "(id, character_name, verb, skill_id, status) VALUES (?, ?, ?, ?, ?)",
        _TRADES,
    )
    return db


# Which intermediate locals each function assigns on the way to its statement.
# READ OUT OF bridge.py IN THIS ORDER rather than supplied, which is the whole
# point of the harness: a test that handed in its own " AND family = %s" would
# keep passing against a bridge that had stopped choosing one.
#
# `cohort` is the one local NOT read back, because reading it would run
# `_cohort_of` and that needs a database. It is supplied instead, which is also
# how both cohorts and the degraded case are reached.
_ASSIGNS = {
    "_errand_holders": ("placeholders", "scope", "scope_args", "sql"),
}
_DEFAULT_ASSIGNS = ("scope", "scope_args")


def _emit(func: str, index: int = 0, cohort=CAVE, **extra):
    """The SQL and bound params `bridge.py` emits for `func`, at `cohort`."""
    names = dict(extra)
    names["cohort"] = cohort
    for target in _ASSIGNS.get(func, _DEFAULT_ASSIGNS):
        names[target] = _assigned(func, target, names)
    return _statement(func, index, **names)


class RosterCase(unittest.TestCase):
    """A two-cohort roster per test, closed when the test ends.

    Closed explicitly rather than left to the collector: an unclosed connection
    is a ResourceWarning on every run, and a suite whose output has warnings in
    it is a suite whose output stops being read.
    """

    def roster(self, rows=None) -> sqlite3.Connection:
        db = _roster(rows)
        self.addCleanup(db.close)
        return db

    def names(self, db, sql, params=()) -> list:
        return sorted(str(row[0]) for row in db.execute(sql, params))

    def scoped(self, func: str, index: int = 0, cohort=CAVE, **extra):
        return _emit(func, index, cohort, **extra)


class TheJobFanOutListUsedToCrossCohorts(RosterCase):
    """`SELECT name FROM overseer_roster WHERE enabled = 1`, the worst of the
    twelve.

    What comes back is fanned out into WRITES - one `overseer_command` row per
    name from `_set_job`, `dungeon_runs_wanted` per name from the campaign
    path. Unscoped, one operator's `job train` for this family queues a job
    command for every character in the other guild too.
    """

    def test_the_old_statement_returns_the_other_cohorts_characters(self):
        db = self.roster()

        got = self.names(db, _sqlite(HISTORIC_ENABLED_NAMES))

        self.assertEqual(
            _ALL_ENABLED,
            got,
            "the unscoped read was supposed to return both cohorts - if it no "
            "longer does, this reproduction has stopped reproducing",
        )
        self.assertIn("Blammo", got)

    def test_the_statement_the_bridge_emits_returns_only_this_cohort(self):
        sql, params = self.scoped("_fetch_enabled_names")
        db = self.roster()

        got = self.names(db, _sqlite(sql), params)

        self.assertEqual(_CAVE_ENABLED, got)
        self.assertNotIn(
            "Blammo",
            got,
            "a job order for this family would have been written for the other "
            "guild's characters as well",
        )

    def test_the_disabled_row_is_still_excluded(self):
        """The cohort predicate is added to `enabled = 1`, not instead of it.
        A scoped read that started returning disabled rows would put a
        character nobody is driving back into every job fan-out."""
        sql, params = self.scoped("_fetch_enabled_names")
        db = self.roster()

        self.assertNotIn("Snik", self.names(db, _sqlite(sql), params))

    def test_the_other_cohort_can_ask_the_same_question_and_get_its_own(self):
        """The predicate is a value, not a side. A second bridge - or this one
        after the one-process-per-cohort question resolves - gets the other
        cohort's five by binding the other cohort's name, with no second
        statement anywhere."""
        sql, params = self.scoped("_fetch_enabled_names", cohort=OTHER)
        db = self.roster()

        self.assertEqual(
            ["Blammo", "Hexmama", "Moojuice"],
            self.names(db, _sqlite(sql), params),
        )


class TheErrandHolderListUsedToCrossCohorts(RosterCase):
    """`... AND travel_npc = %s AND name IN (...)`, feeding a release.

    The `IN` list is bounded to this family TODAY, by
    OVERSEER_NOTABLE_NAMES. That one flat environment variable also drives
    reroll protection, the story filter and the chat watch list, so the day a
    second guild is added to any of those four it is added to all four and this
    list widens. What comes back is then handed to `_release_trade_errand`,
    which blanks `travel_npc` - so a widened list is a read that becomes a
    write into the other cohort's column.
    """

    # The widened list: what `_protected_guids()` yields once a second cohort
    # is enrolled in the same env var. The premise of the reproduction, stated
    # rather than assumed.
    NAMES = ["Grog", "Hexmama"]

    def _historic(self):
        placeholders = _assigned(
            "_errand_holders", "placeholders", {"names": self.NAMES}
        )
        return _module_constant("_ERRAND_HOLDERS_SQL") % placeholders

    def _emitted(self, cohort=CAVE, names=None):
        return _emit(
            "_errand_holders",
            0,
            cohort,
            travel_npc="vendor",
            names=self.NAMES if names is None else names,
            _ERRAND_HOLDERS_SQL=_module_constant("_ERRAND_HOLDERS_SQL"),
        )

    def test_the_old_statement_offers_up_the_other_cohorts_holder(self):
        db = self.roster()

        got = self.names(
            db,
            _sqlite(self._historic()),
            ("vendor", *self.NAMES),
        )

        self.assertEqual(
            ["Grog", "Hexmama"],
            got,
            "the unscoped read was supposed to offer both cohorts' holders to "
            "the release - if it no longer does, this stopped reproducing",
        )

    def test_the_statement_the_bridge_emits_offers_only_this_cohorts_holder(self):
        sql, params = self._emitted()
        db = self.roster()

        got = self.names(db, _sqlite(sql), params)

        self.assertEqual(["Grog"], got)
        self.assertNotIn(
            "Hexmama",
            got,
            "the other cohort's vendor errand was about to be handed back by "
            "this cohort's economy pass",
        )

    def test_the_cohort_clause_is_appended_after_the_interpolation(self):
        """`scope` must never be an operand of the `%`. A cohort name carrying
        a `%` would otherwise be read as a format specifier, which is a
        different bug in the same statement - and the one shape of this fix
        that a two-cohort table full of ordinary names would not catch."""
        code = _function_code("_errand_holders")
        self.assertIn("_ERRAND_HOLDERS_SQL", code)

        sql, _ = self._emitted()

        self.assertTrue(sql.endswith(" AND family = %s"), sql)
        self.assertEqual(1, sql.count("AND family = %s"), sql)

    def test_a_cohort_name_containing_a_percent_survives_assembly(self):
        """Run rather than reasoned about. If `scope` were inside the `%`
        operand this raises ValueError or silently mangles the clause."""
        sql, params = self._emitted(cohort="100%s Grug")

        self.assertTrue(sql.endswith(" AND family = %s"), sql)
        self.assertEqual("100%s Grug", params[-1])


class TheErrandLeadUsedToCrossCohorts(RosterCase):
    """`ORDER BY t.id LIMIT 1` across both cohorts.

    The one row this returns becomes the family's leader: `_head_now` gives it
    `new rpg`, `_mark_party_leader` writes its `lead` flag and the other four
    follow it. A second guild's learn errand created earlier simply has the
    lower `overseer_trade.id` and wins.

    Every other unscoped read on this epic stands something down or widens a
    pool. This one answers the wrong question with a straight face: one row
    came back, a traveller was named, the family followed it to another
    continent.
    """

    def test_the_old_statement_hands_the_lead_to_the_other_guild(self):
        db = self.roster()

        got = self.names(
            db,
            _sqlite_join(HISTORIC_ERRAND_TRAVELLER),
            (ERRAND_LEAD_HOURS,),
        )

        self.assertEqual(
            ["Blammo"],
            got,
            "the unscoped join was supposed to let the lower trade id win "
            "across cohorts - if it no longer does, this stopped reproducing",
        )

    def test_the_statement_the_bridge_emits_keeps_the_lead_in_this_cohort(self):
        sql, params = self.scoped(
            "_errand_traveller",
            ERRAND_LEAD_HOURS=ERRAND_LEAD_HOURS,
        )
        db = self.roster()

        got = self.names(db, _sqlite_join(sql), params)

        self.assertEqual(
            ["Grug"],
            got,
            "this family's lead was handed to a character in the other guild",
        )

    def test_the_freshness_bound_still_excludes_a_stale_errand(self):
        """The cohort clause is added ahead of ORDER BY, so the INTERVAL bound
        and the LIMIT both still apply. A scoped statement that had lost either
        would reorganise the family around an errand nothing can finish."""
        db = self.roster()
        db.execute("UPDATE overseer_trade SET decided_at = datetime('now', '-30 days')")
        sql, params = self.scoped(
            "_errand_traveller",
            ERRAND_LEAD_HOURS=ERRAND_LEAD_HOURS,
        )

        self.assertEqual([], self.names(db, _sqlite_join(sql), params))


class TheTrainRosterUsedToCrossCohorts(RosterCase):
    """`family_mode()` over these rows, which is the function the epic is named
    after.

    A second cohort's rows can only ever disagree - the two families are driven
    by different orders - so `family_mode` returns `''` for ever and
    `trainjob.plan` refuses with "The family's job is not agreed across the
    roster." Training stops for THIS family because of a job somebody else's
    character is on.
    """

    def _jobs(self, db, sql, params=()) -> set:
        return {str(row[1]) for row in db.execute(sql, params)}

    def test_the_old_statement_makes_the_family_job_unagreed(self):
        db = self.roster()

        modes = self._jobs(db, _sqlite(HISTORIC_TRAIN_MEMBERS))

        self.assertGreater(
            len(modes),
            1,
            "the unscoped read was supposed to mix jobs across cohorts, which "
            "is what makes family_mode return '' - if it no longer does, this "
            "reproduction has stopped reproducing",
        )

    def test_the_statement_the_bridge_emits_sees_one_agreed_job(self):
        sql, params = self.scoped("_train_members")
        db = self.roster()

        self.assertEqual(
            {"quest"},
            self._jobs(db, _sqlite(sql), params),
            "a job in the other guild was deciding whether this family's job "
            "counts as agreed",
        )

    def test_it_returns_this_cohorts_rows_and_no_others(self):
        sql, params = self.scoped("_train_members")
        db = self.roster()

        self.assertEqual(_CAVE_ENABLED, self.names(db, _sqlite(sql), params))


class TheRaidPrepRosterUsedToCrossCohorts(RosterCase):
    """`raidprep`'s own near-verbatim copy of `family_mode`, same failure.

    It reads `level` rather than `learn_skill`, which makes the cross-cohort
    answer worse rather than better: the other guild's levels decide whether
    THIS family is judged ready to prepare for a raid.
    """

    def test_the_old_statement_mixes_both_guilds_levels_in(self):
        db = self.roster()

        levels = {int(row[3]) for row in db.execute(_sqlite(HISTORIC_RAIDPREP_MEMBERS))}

        self.assertIn(
            41,
            levels,
            "the unscoped read was supposed to bring the other cohort's levels "
            "into this family's readiness answer",
        )

    def test_the_statement_the_bridge_emits_reads_only_this_cohorts_levels(self):
        sql, params = self.scoped("_raidprep_members")
        db = self.roster()

        rows = list(db.execute(_sqlite(sql), params))

        self.assertEqual({60}, {int(row[3]) for row in rows})
        self.assertEqual({"quest"}, {str(row[1]) for row in rows})
        self.assertEqual(_CAVE_ENABLED, sorted(str(row[0]) for row in rows))


class TheLearnAimRosterUsedToCrossCohorts(RosterCase):
    """Reads `lead`, `professions`, `travel_npc` and `learn_skill` for every
    enabled row, and `learnaim` then WRITES the last two back.

    This function's own docstring already argued for scoping it, before there
    was a second cohort to argue about: it fails closed on 1054/1146 because
    "a HALF-read roster would make a live errand look derived and an unsettled
    one look settled". A cross-cohort read is that half-read with extra steps -
    every row is correct in itself and the SET is still wrong.

    The `lead` column is the sharpest part. `learnaim` uses it to tell the one
    character that can walk from the four that cannot, and with two cohorts
    present there are two rows flagged `lead` and only one is this family's.
    """

    def _leads(self, db, sql, params=()) -> list:
        return sorted(str(row[0]) for row in db.execute(sql, params) if row[1])

    def test_the_old_statement_sees_two_leaders(self):
        db = self.roster()

        self.assertEqual(
            ["Blammo", "Grug"],
            self._leads(db, _sqlite(HISTORIC_LEARN_AIM_ROWS)),
            "the unscoped read was supposed to see both cohorts' leader flags - "
            "if it no longer does, this reproduction has stopped reproducing",
        )

    def test_the_statement_the_bridge_emits_sees_one_leader(self):
        sql, params = self.scoped("_learn_aim_rows")
        db = self.roster()

        self.assertEqual(["Grug"], self._leads(db, _sqlite(sql), params))

    def test_the_other_cohorts_live_errand_is_not_in_the_write_set(self):
        """Hexmama is carrying `travel_npc = 'vendor'`. Unscoped she is in the
        set learnaim plans over, and the plan writes that column."""
        sql, params = self.scoped("_learn_aim_rows")
        db = self.roster()

        self.assertNotIn(
            "Hexmama",
            self.names(db, _sqlite(sql), params),
        )
        self.assertIn("Hexmama", self.names(db, _sqlite(HISTORIC_LEARN_AIM_ROWS)))


class AgainstTheOnlyCohortThatExistsTodayNothingChangesAtAll(RosterCase):
    """The regression risk this change has to answer, measured rather than
    argued.

    Every row in the live table will carry the same `family` value, because the
    column is NOT NULL DEFAULT 'Grug' and the ALTER backfills in one pass. On
    such a table a predicate that selects that one value selects everything, so
    the scoped read and the read it replaced must return exactly the same rows.
    These run both and compare.
    """

    CASES = (
        ("_fetch_enabled_names", HISTORIC_ENABLED_NAMES, {}),
        ("_train_members", HISTORIC_TRAIN_MEMBERS, {}),
        ("_raidprep_members", HISTORIC_RAIDPREP_MEMBERS, {}),
        ("_learn_aim_rows", HISTORIC_LEARN_AIM_ROWS, {}),
    )

    def test_each_plain_read_returns_the_same_rows_as_before(self):
        for func, historic, extra in self.CASES:
            with self.subTest(func=func):
                old = self.roster(_ONE_COHORT)
                before = list(old.execute(_sqlite(historic)))

                sql, params = self.scoped(func, **extra)
                new = self.roster(_ONE_COHORT)

                self.assertEqual(before, list(new.execute(_sqlite(sql), params)))
                self.assertTrue(before, "the fixture must return rows at all")

    def test_the_errand_lead_picks_the_same_character_as_before(self):
        old = self.roster(_ONE_COHORT)
        before = list(
            old.execute(_sqlite_join(HISTORIC_ERRAND_TRAVELLER), (ERRAND_LEAD_HOURS,))
        )

        sql, params = self.scoped(
            "_errand_traveller", ERRAND_LEAD_HOURS=ERRAND_LEAD_HOURS
        )
        new = self.roster(_ONE_COHORT)

        self.assertEqual(before, list(new.execute(_sqlite_join(sql), params)))
        self.assertEqual([("Grug",)], before)

    def test_the_errand_holder_list_returns_the_same_holders_as_before(self):
        names = ["Grog", "Ugga"]
        placeholders = _assigned("_errand_holders", "placeholders", {"names": names})
        constant = _module_constant("_ERRAND_HOLDERS_SQL")

        old = self.roster(_ONE_COHORT)
        before = list(old.execute(_sqlite(constant % placeholders), ("vendor", *names)))

        sql, params = _emit(
            "_errand_holders",
            0,
            CAVE,
            travel_npc="vendor",
            names=names,
            _ERRAND_HOLDERS_SQL=constant,
        )
        new = self.roster(_ONE_COHORT)

        self.assertEqual(before, list(new.execute(_sqlite(sql), params)))
        self.assertEqual([("Grog",)], before)


class UntilTheColumnShipsTheStatementsAreUnchangedCharacterForCharacter(
    unittest.TestCase
):
    """NO RUNNING WORLD HAS THE `family` COLUMN YET.

    mod-overseer#506 is merged and infra#4234 has pinned the submodule to a
    gitlink that carries its SQL. Neither of those is a deployment: `worldserver`
    and `db-import` are absent from `deploy.wow-image-tags.yml`, so the
    migration ships inert with nothing red until the image is rebuilt and the
    running digest is checked by hand.

    So the path that actually executes in production today is the degraded one,
    and "degraded" has to mean today's statement exactly - not a narrower one,
    and above all not no read at all. A family that could not be fanned out to,
    a lead that could never be borrowed, or a `learnaim` pass that saw an empty
    roster would each be a far worse outcome than the cross-cohort bug this
    change closes, and would be the price of a schema that has not shipped
    rather than of anything anyone did wrong.

    `_cohort_of` returns None on 1054/1146. These assert what each read then
    emits, character for character. Three of them, as infra#4232 did it, plus
    one per remaining site - the negative case matters as much as the positive
    one and there is no reason to prove it for only half the change.
    """

    DEGRADED = (
        ("_fetch_enabled_names", 0, HISTORIC_ENABLED_NAMES, (), {}),
        ("_train_members", 0, HISTORIC_TRAIN_MEMBERS, (), {}),
        ("_raidprep_members", 0, HISTORIC_RAIDPREP_MEMBERS, (), {}),
        ("_learn_aim_rows", 0, HISTORIC_LEARN_AIM_ROWS, (), {}),
        (
            "_errand_traveller",
            0,
            HISTORIC_ERRAND_TRAVELLER,
            (ERRAND_LEAD_HOURS,),
            {"ERRAND_LEAD_HOURS": ERRAND_LEAD_HOURS},
        ),
    )

    def _degraded(self, func: str, index: int = 0, **extra):
        return _emit(func, index, None, **extra)

    def test_each_read_falls_back_to_the_statement_it_replaced(self):
        for func, index, historic, params, extra in self.DEGRADED:
            with self.subTest(func=func):
                sql, got = self._degraded(func, index, **extra)
                self.assertEqual(historic, sql)
                self.assertEqual(params, got)

    def test_the_errand_holder_list_falls_back_to_the_statement_it_replaced(self):
        names = ["Grog", "Ugga"]
        constant = _module_constant("_ERRAND_HOLDERS_SQL")
        placeholders = _assigned("_errand_holders", "placeholders", {"names": names})

        sql, params = self._degraded(
            "_errand_holders",
            travel_npc="vendor",
            names=names,
            _ERRAND_HOLDERS_SQL=constant,
        )

        self.assertEqual(constant % placeholders, sql)
        self.assertEqual(("vendor", *names), params)

    def test_a_degraded_read_still_returns_the_whole_family(self):
        """The assertion above is on the text. This one runs it: an empty
        result on a world without the column would stand every one of these
        passes down, which is the failure mode this degradation exists to
        avoid."""
        sql, params = self._degraded("_fetch_enabled_names", 0)
        db = _roster(_ONE_COHORT)
        self.addCleanup(db.close)

        got = sorted(str(row[0]) for row in db.execute(_sqlite(sql), params))

        self.assertEqual(_CAVE_ENABLED, got)


class TheCohortKeyIsReadOffTheRowAndNeverHardcoded(unittest.TestCase):
    """mod-overseer#506's migration insists on this in its own comments, and it
    is the one way to get this wrong that a two-cohort table would not catch.

    The column's DEFAULT is the literal 'Grug'. A validation world renames the
    cast (cast.py), so the head of the family there is spelled differently, and
    a statement pinned to the literal would match NO row in that world - which
    is the unscoped bug's mirror image and exactly as silent.
    """

    SCOPED = (
        "_fetch_enabled_names",
        "_errand_holders",
        "_errand_traveller",
        "_train_members",
        "_raidprep_members",
        "_learn_aim_rows",
    )

    def test_every_one_of_the_six_asks_which_cohort_it_is_in(self):
        """A helper nothing calls is the shape of fix that ships and does
        nothing."""
        for name in self.SCOPED:
            self.assertIn("_cohort_of", _function_code(name), name)

    def test_every_one_of_the_six_resolves_it_from_the_head_of_the_family(self):
        """One identity, one rule. The head is the one name this process is
        certain is on the roster, and it is the same identity `_aim_traveller`
        already binds - so if the one-process-per-cohort question resolves the
        other way there is exactly one expression to change."""
        for name in self.SCOPED:
            self.assertIn("head_of_family", _function_code(name), name)

    def test_no_cohort_literal_is_written_into_any_of_the_six(self):
        for name in self.SCOPED:
            self.assertNotIn("'%s'" % CAVE, _function_code(name), name)
            self.assertNotIn("'%s'" % OTHER, _function_code(name), name)

    def test_the_two_deferred_reads_are_left_exactly_as_they_were(self):
        """`_aimed_names` and `_travelling_names` are NEEDS_COHORT_SCOPE and
        deliberately not scoped. Both are pure membership sets consumed by
        `name in <set>`, so extra names are inert - but scoping them means a
        character on an errand stops counting as aimed, and the strategy pass
        takes `new rpg` straight back off it. That is verbatim infra#3423, the
        nineteen-minutes-motionless bug. Asserted rather than left to a comment:
        a later sweep of "the remaining roster reads" would otherwise scope
        them for tidiness and reintroduce it.

        Matched on the CLAUSE and on the helper, not on the word "family":
        `_aimed_names` already says "the family falls back to leader-only
        travel" in its own 1054 warning, and an assertion that tripped on prose
        would have to be loosened by the next person to touch it."""
        for name in ("_aimed_names", "_travelling_names"):
            code = _function_code(name)
            self.assertNotIn("_cohort_of", code, name)
            self.assertNotIn("family = ", code, name)


if __name__ == "__main__":
    unittest.main()
