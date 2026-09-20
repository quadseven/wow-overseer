"""Three roster writes that had no cohort bound, and a second guild to prove it.

infra#4221. `overseer_roster` has held exactly one family's rows since the day
it was created, so a write that named no cohort was table-wide and correct at
the same time. Three writes in `bridge.py` drifted into having no per-character
bound at all, and the read-only audit on that epic found them:

    bridge.py  `UPDATE overseer_roster SET `lead` = IF(name = %s, 1, 0)`
               with NO WHERE CLAUSE OF ANY KIND, every protect cycle
    bridge.py  `... SET drive_quest = 0 WHERE drive_quest <> 0
                 AND name NOT IN (<this family>)`
    bridge.py  `... SET drive_quest = 0 WHERE drive_quest <> 0`

None of them has ever misbehaved, because there has never been a second
cohort's worth of rows for them to reach. That is the whole difficulty: there
is no failing production symptom to reproduce, no log line, nothing in a
dashboard. A cleared `lead` flag and a cleared `drive_quest` are both SILENT -
mod-overseer enforces whatever it last read, and a character with no aim simply
free-roams its own quest log again, which is the 937-yard scatter the aim
exists to prevent, arriving with no cause anywhere near it.

So this suite builds the second cohort the live table does not have yet, and
runs the statements against it in SQLite:

  * the shape these three had BEFORE the fix, spelled out below as historical
    constants, to show the corruption is real and not theoretical;
  * the shape `bridge.py` emits NOW, lifted out of its own source and evaluated
    with its own `scope` expression, to show the corruption is gone.

THE SECOND HALF IS WHAT MAKES THIS A TEST AND NOT A DEMONSTRATION. Reverting
any one of the three WHERE clauses makes the matching "leaves the other cohort
alone" test fail, because the SQL under test is read out of `bridge.py` rather
than restated here. Nothing below asserts against a string this file made up.

WHY SQLITE AND WHY THAT IS HONEST. `bridge.py` imports discord and is not
importable here by design (tests/test_quest_goal.py says so at its own seam),
there is no MySQL in this job - the whole matrix runs stdlib-only with no pip
install - and the statements are simple enough that SQLite executes them with
two documented substitutions and nothing else: `%s` becomes `?`, and MySQL's
`IF(a, b, c)` becomes the identical `iif(a, b, c)`. `_sqlite` asserts both
substitutions are total, so a statement that grew a third dialect-specific
construct fails here rather than being quietly half-translated. The WHERE
clauses these tests are about pass through untouched.

WHAT THIS DOES NOT COVER, on purpose. The twelve `NEEDS_COHORT_SCOPE` READ
sites the same audit classified are not touched by this change and are not
tested here. Neither is whether one bridge process should serve both cohorts
or one each, which is still open on infra#4221 and decides more of that epic
than the schema does.
"""
import ast
import builtins
import pathlib
import re
import sqlite3
import unittest

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


# --- the three statements as they stood before infra#4221 -------------------
#
# Verbatim, including the two trailing spaces the source's implicit string
# concatenation produced. They are here to be RUN, not to be compared against
# prose: the tests below execute them against a two-cohort table and assert
# they do the damage the audit said they would.

HISTORIC_LEAD = "UPDATE overseer_roster SET `lead` = IF(name = %s, 1, 0)"
HISTORIC_CLEAR_OTHERS = (
    "UPDATE overseer_roster SET drive_quest = 0 "
    "WHERE drive_quest <> 0 AND name NOT IN (%s)"
)
HISTORIC_CLEAR_ALL = (
    "UPDATE overseer_roster SET drive_quest = 0 WHERE drive_quest <> 0"
)


# --- reading the statements back out of bridge.py ---------------------------


def _bridge_source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(_bridge_source())):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _function_code(name: str) -> str:
    """The function's CODE, with its docstring removed.

    Same helper, and the same reason for it, as tests/test_quest_goal.py: an
    `ast.dump` that still contains the docstring lets an assertion pass off a
    prose mention of a SQL fragment long after the code stopped doing it. That
    has happened in this file's neighbourhood before.
    """
    node = _function(name)
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return "\n".join(ast.dump(stmt) for stmt in body)


def _evaluate(expr: ast.expr, names: dict):
    """Evaluate one expression lifted straight out of bridge.py.

    This is the point of the whole file. The statements are not string
    constants any more - each is built from a `scope` clause the function
    chooses - so a test that restated the finished SQL would be testing its own
    guess at the construction. Evaluating bridge.py's own expression with a
    supplied namespace means the tests below run exactly what the bridge runs,
    and a revert of the fix changes what they run.
    """
    tree = ast.Expression(body=expr)
    ast.fix_missing_locations(tree)
    code = compile(tree, "<bridge.py>", "eval")
    return eval(code, {"__builtins__": builtins}, dict(names))  # noqa: S307


def _assigned(func: str, target: str, names: dict):
    """The value `func` assigns to `target`, given `names`.

    Read rather than restated for the same reason as `_evaluate`: `scope` is
    the fix. A test that supplied its own " AND family = %s" would keep passing
    against a bridge that had stopped choosing one.
    """
    for stmt in ast.walk(_function(func)):
        if (isinstance(stmt, ast.Assign)
                and any(getattr(t, "id", "") == target for t in stmt.targets)):
            return _evaluate(stmt.value, names)
    raise AssertionError(
        "%s assigns no %s - the cohort clause is gone from bridge.py" % (func, target)
    )


def _executes(func: str) -> list:
    """Every `cur.execute(...)` in `func`, in source order."""
    calls = [
        node for node in ast.walk(_function(func))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    calls.sort(key=lambda node: (node.lineno, node.col_offset))
    return calls


def _statement(func: str, index: int, **names) -> tuple:
    """The SQL and the bound values of the `index`th execute in `func`."""
    call = _executes(func)[index]
    sql = _evaluate(call.args[0], names)
    params = tuple(_evaluate(call.args[1], names)) if len(call.args) > 1 else ()
    return sql, params


# --- running MySQL statements on SQLite -------------------------------------

_MYSQL_IF = re.compile(r"\bIF\s*\(")


def _sqlite(sql: str) -> str:
    """The same statement in the dialect this job has an engine for.

    Two substitutions, both asserted total. A statement that grew a third
    MySQL-only construct fails here instead of being silently half-translated
    into something that passes for a different reason than the one intended.
    """
    out = _MYSQL_IF.sub("iif(", sql).replace("%s", "?")
    assert "%s" not in out, "a placeholder survived translation: %r" % out
    assert not _MYSQL_IF.search(out), "an IF() survived translation: %r" % out
    return out


# The live cohort. Every row in `overseer_roster` today carries this value,
# because mod-overseer#506's column is NOT NULL DEFAULT 'Grug' and the ALTER
# backfills every existing row in one pass.
CAVE = "Grug"

# A second cohort, which no database has yet. Who is in it is deliberately not
# the point and is explicitly out of scope on infra#4221 - all that matters
# below is that a second family's rows exist at all.
OTHER = "Bonkers"

# name, lead, drive_quest, family
_TWO_COHORTS = (
    ("Grug", 1, 0, CAVE),
    ("Ugga", 0, 0, CAVE),
    ("Grog", 0, 0, CAVE),
    ("Bork", 0, 0, CAVE),
    ("Og", 0, 99, CAVE),
    ("Blammo", 1, 0, OTHER),
    ("Hexmama", 0, 554, OTHER),
    ("Moojuice", 0, 0, OTHER),
)

_ONE_COHORT = tuple(row for row in _TWO_COHORTS if row[3] == CAVE)


def _roster(rows) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE overseer_roster ("
        "  name TEXT PRIMARY KEY,"
        "  enabled INTEGER NOT NULL DEFAULT 1,"
        # Backticked here too: `lead` is a reserved word in MySQL 8 and the
        # statements under test quote it, so the fixture has to accept that.
        "  `lead` INTEGER NOT NULL DEFAULT 0,"
        "  drive_quest INTEGER NOT NULL DEFAULT 0,"
        # NOT NULL DEFAULT 'Grug', exactly as mod-overseer#506 declares it.
        "  family TEXT NOT NULL DEFAULT 'Grug')"
    )
    db.executemany(
        "INSERT INTO overseer_roster (name, `lead`, drive_quest, family) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    return db


def _dump(db: sqlite3.Connection) -> list:
    return list(db.execute(
        "SELECT name, `lead`, drive_quest, family FROM overseer_roster ORDER BY name"
    ))


def _cell(db: sqlite3.Connection, name: str, column: str) -> int:
    row = db.execute(
        "SELECT `lead`, drive_quest FROM overseer_roster WHERE name = ?", (name,)
    ).fetchone()
    return row[0] if column == "lead" else row[1]


class RosterCase(unittest.TestCase):
    """A two-cohort roster per test, closed when the test ends.

    Closed explicitly rather than left to the collector: an unclosed
    connection is a ResourceWarning on every run, and a suite whose output has
    warnings in it is a suite whose output stops being read.
    """

    def roster(self, rows=None) -> sqlite3.Connection:
        db = _roster(_TWO_COHORTS if rows is None else rows)
        self.addCleanup(db.close)
        return db


class TheHarnessCanActuallyRunTheseStatements(RosterCase):
    """A translation nobody checked is a green tick on an untested statement."""

    def test_the_sqlite_build_understands_the_conditional_assignment(self):
        """iif() arrived in SQLite 3.32 (2020). Asserted rather than skipped:
        a suite that quietly skips on an old engine is a check that can only
        report good news."""
        self.assertGreaterEqual(sqlite3.sqlite_version_info, (3, 32),
                                sqlite3.sqlite_version)

    def test_the_translation_of_the_leader_write_is_total(self):
        self.assertEqual(
            "UPDATE overseer_roster SET `lead` = iif(name = ?, 1, 0)",
            _sqlite(HISTORIC_LEAD),
        )

    def test_sqlite_refuses_a_statement_it_cannot_parse(self):
        """EXECUTION is what catches a third MySQL-only construct, not the two
        substitutions above, which are both global and cannot leave a remnant.
        Proven rather than assumed: an engine that accepted anything would make
        every execution below a report on nothing.
        """
        db = self.roster(_ONE_COHORT)
        with self.assertRaises(sqlite3.OperationalError):
            db.execute("UPDATE overseer_roster SET drive_quest = 0 "
                       "WHERE updated_at > NOW() - INTERVAL 60 SECOND")


class TheLeaderFlagWriteUsedToCrossCohorts(RosterCase):
    """`UPDATE overseer_roster SET `lead` = IF(name = %s, 1, 0)`, no WHERE.

    Every protect cycle, on every row in the table. With two cohorts present
    each one's cycle zeroes the other's leader, mod-overseer's
    KeepRosterGrouped enforces whichever write landed last, and nothing
    anywhere says that happened.
    """

    def test_the_old_statement_zeroes_the_other_cohorts_leader(self):
        db = self.roster()
        self.assertEqual(1, _cell(db, "Blammo", "lead"), "fixture precondition")

        db.execute(_sqlite(HISTORIC_LEAD), ("Ugga",))

        self.assertEqual(
            0, _cell(db, "Blammo", "lead"),
            "the unscoped write was supposed to reach into the other cohort - "
            "if it no longer does, this reproduction has stopped reproducing",
        )
        self.assertEqual(1, _cell(db, "Ugga", "lead"))
        self.assertEqual(0, _cell(db, "Grug", "lead"))

    def test_the_statement_the_bridge_emits_leaves_the_other_cohort_alone(self):
        scope = _assigned("_mark_party_leader", "scope", {"cohort": CAVE})
        sql, params = _statement(
            "_mark_party_leader", 0, head="Ugga", cohort=CAVE, scope=scope,
        )
        db = self.roster()

        db.execute(_sqlite(sql), params)

        self.assertEqual(
            1, _cell(db, "Blammo", "lead"),
            "the other cohort's leader flag was rewritten by this cohort's pass",
        )
        self.assertEqual(1, _cell(db, "Ugga", "lead"))
        self.assertEqual(0, _cell(db, "Grug", "lead"))

    def test_the_cohort_it_scopes_to_is_the_one_it_is_making_leader(self):
        """The invariant that makes this safe under an unscoped `_head_now`:
        the row set to 1 is always inside the set being zeroed, so no pass can
        leave a cohort with no leader at all."""
        scope = _assigned("_mark_party_leader", "scope", {"cohort": OTHER})
        sql, params = _statement(
            "_mark_party_leader", 0, head="Hexmama", cohort=OTHER, scope=scope,
        )
        db = self.roster()

        db.execute(_sqlite(sql), params)

        self.assertEqual(1, _cell(db, "Hexmama", "lead"))
        self.assertEqual(0, _cell(db, "Blammo", "lead"))
        self.assertEqual(1, _cell(db, "Grug", "lead"), "this cohort was not touched")


class TheQuestAimClearUsedToCrossCohorts(RosterCase):
    """`... WHERE drive_quest <> 0 AND name NOT IN (<this family>)`.

    `_holders_of` is bounded by OVERSEER_NOTABLE_NAMES, so the IN-list is this
    bridge's own family and only the NOT IN half reached outward: every other
    cohort's aim was blanked every time this family aimed at anything.
    """

    HOLDERS = ["Grog", "Ugga"]

    def _marks(self):
        return _assigned("_aim_traveller", "marks", {"holders": self.HOLDERS})

    def test_the_old_statement_blanks_the_other_cohorts_aim(self):
        db = self.roster()
        self.assertEqual(554, _cell(db, "Hexmama", "drive_quest"), "precondition")

        db.execute(
            _sqlite(HISTORIC_CLEAR_OTHERS % self._marks()), tuple(self.HOLDERS),
        )

        self.assertEqual(
            0, _cell(db, "Hexmama", "drive_quest"),
            "the unscoped clear was supposed to reach the other cohort",
        )
        self.assertEqual(0, _cell(db, "Og", "drive_quest"), "own cohort, not a holder")

    def test_the_statement_the_bridge_emits_leaves_the_other_cohort_alone(self):
        names = {
            "holders": self.HOLDERS,
            "cohort": CAVE,
            "marks": self._marks(),
        }
        names["scope"] = _assigned("_aim_traveller", "scope", names)
        names["scope_args"] = _assigned("_aim_traveller", "scope_args", names)
        sql, params = _statement("_aim_traveller", 1, **names)
        db = self.roster()

        db.execute(_sqlite(sql), params)

        self.assertEqual(
            554, _cell(db, "Hexmama", "drive_quest"),
            "this cohort's aim pass blanked the other cohort's quest aim",
        )
        self.assertEqual(
            0, _cell(db, "Og", "drive_quest"),
            "a non-holder in this cohort must still be cleared - that is what "
            "keeps an unaimed follower off its own quest log",
        )

    def test_the_aim_write_itself_is_still_bounded_by_name_and_nothing_else(self):
        """The audit classified this one KEY_SCOPED: `WHERE name IN (...)` over
        a list already bounded to this family. A cohort predicate here would be
        a second place for the rule to drift, and this change deliberately did
        not add one."""
        sql, _ = _statement(
            "_aim_traveller", 0,
            holders=self.HOLDERS, quest_id=3109, marks=self._marks(),
        )
        self.assertIn("WHERE name IN", sql)
        self.assertNotIn("family", sql)


class TheUnconditionalQuestAimClearUsedToCrossCohorts(RosterCase):
    """`... SET drive_quest = 0 WHERE drive_quest <> 0`, the no-holders branch.

    Table-wide and unconditional: every quest aim in every cohort, cleared
    because THIS family had nobody holding the quest it was aimed at.
    """

    def test_the_old_statement_blanks_every_aim_in_the_table(self):
        db = self.roster()

        db.execute(_sqlite(HISTORIC_CLEAR_ALL))

        self.assertEqual(0, _cell(db, "Hexmama", "drive_quest"),
                         "the unscoped clear was supposed to reach the other cohort")
        self.assertEqual(0, _cell(db, "Og", "drive_quest"))

    def test_the_statement_the_bridge_emits_leaves_the_other_cohort_alone(self):
        names = {"cohort": CAVE}
        names["scope"] = _assigned("_aim_traveller", "scope", names)
        names["scope_args"] = _assigned("_aim_traveller", "scope_args", names)
        sql, params = _statement("_aim_traveller", 2, **names)
        db = self.roster()

        db.execute(_sqlite(sql), params)

        self.assertEqual(
            554, _cell(db, "Hexmama", "drive_quest"),
            "this cohort having no holder cleared the other cohort's aim",
        )
        self.assertEqual(0, _cell(db, "Og", "drive_quest"),
                         "this cohort's own stale aim must still be cleared")


class AgainstTheOnlyCohortThatExistsTodayNothingChangesAtAll(RosterCase):
    """The regression risk this change has to answer, measured rather than
    argued.

    Every row in the live table carries the same `family` value, because the
    column is NOT NULL DEFAULT 'Grug' and the ALTER backfills in one pass. On
    such a table a predicate that selects that one value selects everything, so
    the scoped statement and the statement it replaced must leave the table in
    byte-identical states. These run both and compare the whole table.
    """

    def test_the_leader_write_is_a_no_op_change(self):
        old = self.roster(_ONE_COHORT)
        old.execute(_sqlite(HISTORIC_LEAD), ("Ugga",))

        scope = _assigned("_mark_party_leader", "scope", {"cohort": CAVE})
        sql, params = _statement(
            "_mark_party_leader", 0, head="Ugga", cohort=CAVE, scope=scope,
        )
        new = self.roster(_ONE_COHORT)
        new.execute(_sqlite(sql), params)

        self.assertEqual(_dump(old), _dump(new))

    def test_the_holder_clear_is_a_no_op_change(self):
        holders = ["Grog", "Ugga"]
        marks = _assigned("_aim_traveller", "marks", {"holders": holders})

        old = self.roster(_ONE_COHORT)
        old.execute(_sqlite(HISTORIC_CLEAR_OTHERS % marks), tuple(holders))

        names = {"holders": holders, "cohort": CAVE, "marks": marks}
        names["scope"] = _assigned("_aim_traveller", "scope", names)
        names["scope_args"] = _assigned("_aim_traveller", "scope_args", names)
        sql, params = _statement("_aim_traveller", 1, **names)
        new = self.roster(_ONE_COHORT)
        new.execute(_sqlite(sql), params)

        self.assertEqual(_dump(old), _dump(new))

    def test_the_unconditional_clear_is_a_no_op_change(self):
        old = self.roster(_ONE_COHORT)
        old.execute(_sqlite(HISTORIC_CLEAR_ALL))

        names = {"cohort": CAVE}
        names["scope"] = _assigned("_aim_traveller", "scope", names)
        names["scope_args"] = _assigned("_aim_traveller", "scope_args", names)
        sql, params = _statement("_aim_traveller", 2, **names)
        new = self.roster(_ONE_COHORT)
        new.execute(_sqlite(sql), params)

        self.assertEqual(_dump(old), _dump(new))


class UntilTheColumnShipsTheStatementsAreUnchangedCharacterForCharacter(
        unittest.TestCase):
    """No running world has the `family` column yet.

    Corrected in place (infra#4221): when this was written the submodule
    gitlink did not carry mod-overseer#506's SQL at all. infra#4234 has since
    pinned one that does - and that is still not a deployment, because
    `worldserver` and `db-import` are absent from `deploy.wow-image-tags.yml`,
    so the migration ships inert until the image is rebuilt and the running
    digest is checked by hand. The conclusion below is unchanged; only the
    reason it is true has moved one stage down the pipeline.

    So the path that actually executes in production today is the degraded one,
    and "degraded" has to mean today's statement exactly - not a narrower one,
    and above all not no write at all. A leaderless family, or a quest aim that
    can never be cleared, would be a far worse outcome than the cross-cohort
    bug this change closes.
    """

    def test_the_leader_write_falls_back_to_the_statement_it_replaced(self):
        scope = _assigned("_mark_party_leader", "scope", {"cohort": None})
        sql, params = _statement(
            "_mark_party_leader", 0, head="Ugga", cohort=None, scope=scope,
        )
        self.assertEqual(HISTORIC_LEAD, sql)
        self.assertEqual(("Ugga",), params)

    def test_the_holder_clear_falls_back_to_the_statement_it_replaced(self):
        holders = ["Grog", "Ugga"]
        names = {"holders": holders, "cohort": None}
        names["marks"] = _assigned("_aim_traveller", "marks", names)
        names["scope"] = _assigned("_aim_traveller", "scope", names)
        names["scope_args"] = _assigned("_aim_traveller", "scope_args", names)
        sql, params = _statement("_aim_traveller", 1, **names)
        self.assertEqual(HISTORIC_CLEAR_OTHERS % names["marks"], sql)
        self.assertEqual(tuple(holders), params)

    def test_the_unconditional_clear_falls_back_to_the_statement_it_replaced(self):
        names = {"cohort": None}
        names["scope"] = _assigned("_aim_traveller", "scope", names)
        names["scope_args"] = _assigned("_aim_traveller", "scope_args", names)
        sql, params = _statement("_aim_traveller", 2, **names)
        self.assertEqual(HISTORIC_CLEAR_ALL, sql)
        self.assertEqual((), params)


class TheCohortKeyIsReadOffTheRowAndNeverHardcoded(unittest.TestCase):
    """mod-overseer#506's migration insists on this in its own comments, and it
    is the one way to get this wrong that a two-cohort table would not catch.

    The column's DEFAULT is the literal 'Grug'. A validation world renames the
    cast (cast.py), so the head of the family there is spelled differently -
    and a statement pinned to the literal would match NO row in that world,
    which is the table-wide bug's mirror image and exactly as silent.
    """

    SCOPED = ("_cohort_of", "_mark_party_leader", "_aim_traveller")

    def test_the_helper_asks_the_row_which_cohort_it_is_in(self):
        code = _function_code("_cohort_of")
        self.assertIn("SELECT family FROM overseer_roster WHERE name = %s", code)

    def test_a_world_without_the_column_yields_no_cohort_rather_than_raising(self):
        """1054 is ER_BAD_FIELD_ERROR and 1146 a missing table. Matched on the
        code, never on the message text, which is localised - the same rule
        every other degrading reader in bridge.py follows."""
        code = _function_code("_cohort_of")
        self.assertIn("1054", code)
        self.assertIn("1146", code)
        self.assertIn("Constant(value=None)", code)

    def test_no_cohort_literal_is_written_into_any_of_the_three(self):
        for name in self.SCOPED:
            self.assertNotIn("'%s'" % CAVE, _function_code(name), name)

    def test_both_writers_actually_ask_for_a_cohort(self):
        """A helper nothing calls is the shape of fix that ships and does
        nothing."""
        for name in ("_mark_party_leader", "_aim_traveller"):
            self.assertIn("_cohort_of", _function_code(name), name)

    def test_the_quest_aim_pass_scopes_to_the_family_it_serves(self):
        code = _function_code("_aim_traveller")
        self.assertIn("head_of_family", code)


if __name__ == "__main__":
    unittest.main()
