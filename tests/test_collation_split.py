"""A join between two overseer tables must say which collation it means.

infra#3173. The `overseer_*` tables are created by mod-overseer across many
migrations and do not share one collation. Measured on BOTH realms on
2026-09-02, reading information_schema.TABLES directly:

    utf8mb4_unicode_ci   overseer_roster, overseer_event, overseer_death
    utf8mb4_0900_ai_ci   overseer_snapshot, overseer_trade, overseer_command,
                         overseer_thought, overseer_goal, overseer_chat,
                         overseer_chat_watch, overseer_stream,
                         overseer_dungeon_run, overseer_sample

MySQL will not compare a string column from the first group against one from
the second. Both operands are IMPLICIT coercibility, neither outranks the
other, and the server raises 1267 ("Illegal mix of collations") and fails the
WHOLE statement. So the failure is not a missing row, it is every row, on every
execution, forever. The bridge's `_errand_traveller` carried exactly that join
and raised six times in twenty minutes on dev, taking the protect cycle and the
life recheck with it.

The fix is an explicit `COLLATE` on the predicate: EXPLICIT coercibility (0)
outranks both IMPLICIT sides (2) and settles the comparison for the whole
expression. The fix is one word long, which is precisely why it needs a guard -
the next join across the split will be written the natural way by somebody who
has never heard of any of this, and it will look right in review and fail in
production.

WHY THIS IS A CONTRACT OVER SOURCE TEXT rather than a query against a database.
This directory's suites are stdlib-only and run with NO pip install (see
check.python-units.yml's scope note); bridge.py imports `discord` and `pymysql`
at module level and there is no MySQL in CI. So the SQL is read out of the
source with `ast` and checked as text, the same shape test_headless_bridge.py
uses for the bridge and test_quest_aim.py uses for the C++.

`characters` IS DELIBERATELY EXEMPT AND MUST STAY THAT WAY. characters.name is
utf8mb4_bin; a binary collation already outranks either overseer group on its
own, so those joins have never raised and need nothing. Forcing
utf8mb4_unicode_ci onto one would turn an exact-match join into a case- and
accent-insensitive one, which is a behaviour change wearing a bug fix's
clothes.
"""

import ast
import pathlib
import re
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PACKAGE / "bridge.py"

# Every table these scripts query whose collation matters, and what it actually
# is. Read from information_schema on wow-dev and wow on 2026-09-02; a table
# added here without being read from the live schema is a guess, and a guess is
# worse than no entry at all because it silences the sweep below.
COLLATIONS = {
    "overseer_roster": "utf8mb4_unicode_ci",
    "overseer_naturalized": "utf8mb4_unicode_ci",
    "overseer_event": "utf8mb4_unicode_ci",
    "overseer_death": "utf8mb4_unicode_ci",
    "overseer_snapshot": "utf8mb4_0900_ai_ci",
    "overseer_trade": "utf8mb4_0900_ai_ci",
    "overseer_command": "utf8mb4_0900_ai_ci",
    "overseer_thought": "utf8mb4_0900_ai_ci",
    "overseer_goal": "utf8mb4_0900_ai_ci",
    "overseer_chat": "utf8mb4_0900_ai_ci",
    "overseer_chat_watch": "utf8mb4_0900_ai_ci",
    "overseer_stream": "utf8mb4_0900_ai_ci",
    "overseer_dungeon_run": "utf8mb4_0900_ai_ci",
    "overseer_sample": "utf8mb4_0900_ai_ci",
    # NOT READ FROM A LIVE SCHEMA, AND NOT A GUESS EITHER: this table does not
    # exist on any realm yet, because it is created by SQL a worldserver has to
    # be rolled onto first. Its collation is NAMED in its own CREATE TABLE
    # (COLLATE=utf8mb4_unicode_ci) rather than inherited, so it is fixed by the
    # DDL rather than by whichever server default applied on the day a realm was
    # built. Verified by running that exact DDL against a live MySQL 8.4 in a
    # scratch schema: the named form came out utf8mb4_unicode_ci and the bare
    # `DEFAULT CHARSET=utf8mb4` form came out utf8mb4_0900_ai_ci, which is where
    # the split above comes from in the first place.
    "overseer_build": "utf8mb4_unicode_ci",
    # Bridge-owned (#95), and fixed the same way: its CREATE TABLE in
    # bridge._ensure_jev_store NAMES utf8mb4_0900_ai_ci, the collation every
    # other bridge-owned table carries, rather than inheriting a default.
    "overseer_jev_judgment": "utf8mb4_0900_ai_ci",
    # Bridge-owned (#209), named in campaignqueue.CREATE_SQL the same way.
    "overseer_dungeon_queue": "utf8mb4_0900_ai_ci",
    # Bridge-owned (the Bags tab's week), named in
    # bridge._ensure_economy_store the same way overseer_jev_judgment is.
    "overseer_economy_sample": "utf8mb4_0900_ai_ci",
    # Module-owned (mod-overseer#616), named in its own CREATE TABLE
    # (COLLATE=utf8mb4_unicode_ci) exactly as overseer_build is above.
    "overseer_dungeon_run_event": "utf8mb4_unicode_ci",
    # Module-owned (mod-overseer#634, 2026_09_23_01_overseer_raid_seat.sql),
    # named in its own CREATE TABLE the same way. The bridge only writes it.
    "overseer_raid_seat": "utf8mb4_unicode_ci",
    # Module-owned (2026_09_25_10_overseer_raid_spec.sql), named in its own
    # CREATE TABLE the same way. The bridge only writes it.
    "overseer_raid_spec": "utf8mb4_unicode_ci",
    # Module-owned (2026_09_24_00_overseer_run_recovery.sql), named in its own
    # CREATE TABLE the same way. The bridge only reads and answers it.
    "overseer_run_recovery": "utf8mb4_unicode_ci",
    # Module-owned (mod-overseer#642, 2026_09_24_01_overseer_loot_council.sql),
    # named in its own CREATE TABLE the same way. The bridge answers its rows.
    "overseer_loot_council": "utf8mb4_unicode_ci",
    # Module-owned (2026_09_24_06_overseer_keep.sql), named in its own CREATE
    # TABLE the same way. The bridge reads it, joined to `characters` by name.
    "overseer_keep": "utf8mb4_unicode_ci",
    # Not an overseer table, and the reason every join to it is safe. A binary
    # collation wins against any non-binary one of the same charset without
    # anybody writing COLLATE.
    "characters": "utf8mb4_bin",
}

BINARY = "utf8mb4_bin"

# Collation is a property of TEXT, and half the columns in these tables are not
# text. `t.skill_id = r.learn_skill` puts an INT from overseer_trade against an
# INT from overseer_roster and MySQL does not care in the slightest - flagging
# it would train the next reader to add COLLATE where it means nothing, and to
# stop believing the sweep. So the precise check below only fires on a pair of
# columns known to carry a collation.
#
# Read from information_schema.COLUMNS on wow-dev on 2026-09-02: every column of
# an overseer table whose COLLATION_NAME is not NULL. `characters` needs no
# entry - it is utf8mb4_bin, which settles any comparison it is part of before
# the column ever matters.
STRING_COLUMNS = {
    "overseer_chat": frozenset(
        {"channel", "channel_name", "heard_by", "sender_name", "text"}
    ),
    "overseer_chat_watch": frozenset({"channels", "name"}),
    "overseer_naturalized": frozenset({"name", "part"}),
    "overseer_command": frozenset(
        {
            "channel",
            "claimed_by",
            "command",
            "detail",
            "kind",
            "result",
            "source",
            "status",
            "target_arg",
            "target_name",
        }
    ),
    "overseer_death": frozenset(
        {
            "character_name",
            "group_leader",
            "job",
            "killer_name",
            "killer_type",
            "travel_target",
        }
    ),
    "overseer_dungeon_run": frozenset({"ended_reason", "leader_name", "state"}),
    # From its own DDL (mod-overseer#616): every VARCHAR column.
    "overseer_dungeon_run_event": frozenset(
        {
            "character_name",
            "detail",
            "family",
            "kind",
            "leader_name",
            "phase",
            "portal",
        }
    ),
    # From its own DDL: every VARCHAR and ENUM column.
    "overseer_run_recovery": frozenset(
        {
            "answer",
            "answered_by",
            "applied",
            "applied_by",
            "facts",
            "failure",
            "family",
            "heuristic",
            "heuristic_why",
            "kind",
            "leader_name",
            "options",
            "status",
        }
    ),
    "overseer_event": frozenset({"character_name", "detail", "kind", "subject_name"}),
    "overseer_goal": frozenset(
        {"channel_id", "character_name", "kind", "last_report", "skill_name", "status"}
    ),
    "overseer_roster": frozenset({"job", "name", "note", "professions", "travel_npc"}),
    "overseer_sample": frozenset({"character_name"}),
    # name/value rows rather than a column per fact, so this list is the whole
    # table and cannot grow when the module reports something new.
    "overseer_build": frozenset({"name", "source", "value"}),
    "overseer_snapshot": frozenset({"name"}),
    "overseer_stream": frozenset({"character", "delivery", "detail", "mode", "state"}),
    "overseer_thought": frozenset({"character_name", "source", "text"}),
    "overseer_trade": frozenset(
        {"character_name", "reason", "skill_name", "status", "verb"}
    ),
    # From its own DDL (bridge._ensure_jev_store): every VARCHAR column.
    "overseer_jev_judgment": frozenset(
        {
            "acted",
            "facts",
            "heuristic",
            "heuristic_why",
            "holder",
            "item_name",
            "jev",
            "kind",
            "mode",
            "model",
            "probabilities",
            "status",
            "subject",
        }
    ),
    "overseer_dungeon_queue": frozenset({"family", "keyword", "status", "source"}),
    # From its own DDL (bridge._ensure_economy_store): every VARCHAR column.
    "overseer_economy_sample": frozenset({"kind", "subject"}),
    # From its own DDL (mod-overseer's 2026_09_23_01): every VARCHAR column.
    # And 2026_09_24_03's `duty`.
    "overseer_raid_seat": frozenset({"duty", "family", "keyword", "name", "role"}),
    # From its own DDL (mod-overseer's 2026_09_25_10): every VARCHAR column.
    "overseer_raid_spec": frozenset({"duty", "guild", "name", "tree"}),
    # From its own DDL (mod-overseer's 2026_09_24_06): every VARCHAR column.
    "overseer_keep": frozenset({"character_name", "reason"}),
    # From its own DDL (mod-overseer's 2026_09_24_01): every VARCHAR column.
    "overseer_loot_council": frozenset(
        {
            "council_key",
            "kind",
            "family",
            "source",
            "item_name",
            "heuristic",
            "heuristic_why",
            "status",
            "recipient",
            "reason",
            "decided_by",
            "given_to",
            "outcome",
        }
    ),
}

# Words that can follow a table name and are not an alias.
NOT_AN_ALIAS = frozenset(
    {
        "as",
        "on",
        "using",
        "where",
        "set",
        "group",
        "order",
        "having",
        "limit",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "cross",
        "straight_join",
        "union",
        "values",
        "select",
        "for",
        "into",
        "natural",
        "partition",
    }
)

# `FROM overseer_trade t`, `JOIN overseer_roster AS r`, `FROM characters c`.
_SOURCE_TABLE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?"
    r"(?:\s+(?:AS\s+)?`?([A-Za-z_][A-Za-z0-9_]*)`?)?",
    re.IGNORECASE,
)

# `t.character_name COLLATE utf8mb4_unicode_ci = r.name`, either side collated.
_COMPARISON = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\.`?([A-Za-z_][A-Za-z0-9_]*)`?"
    r"(\s+COLLATE\s+\w+)?"
    r"\s*=\s*"
    r"\b([A-Za-z_][A-Za-z0-9_]*)\.`?([A-Za-z_][A-Za-z0-9_]*)`?"
    r"(\s+COLLATE\s+\w+)?",
    re.IGNORECASE,
)

_LOOKS_LIKE_SQL = re.compile(
    r"\b(?:SELECT|INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER)\b"
)


def _docstring_ids(tree: ast.AST) -> set:
    """Node ids of every docstring, so prose that quotes SQL is not read as SQL.

    Several modules here explain their own queries at length in the docstring
    above them, quoting the very join this file is looking for. A comment is
    invisible to `ast` and needs no handling; a docstring is a string constant
    like any other and would otherwise be swept as if it were executed.
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            out.add(id(body[0].value))
    return out


def _sources() -> list:
    """Every shipped .py in the package, tests excluded."""
    return [p for p in sorted(PACKAGE.rglob("*.py")) if "tests" not in p.parts]


def _statements() -> list:
    """(path, lineno, sql) for every SQL string literal the scripts execute.

    Implicitly concatenated literals arrive already joined - `ast` folds them
    into one Constant - which is what makes a multi-line query readable as one
    statement even though the source spells it over eight lines.
    """
    out = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstring_ids(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or id(node) in skip:
                continue
            text = " ".join(node.value.split())
            if _LOOKS_LIKE_SQL.search(text) or " JOIN " in text.upper():
                out.append((path, node.lineno, text))
    return out


def _aliases(sql: str) -> dict:
    """alias (and bare table name) -> table, for one statement."""
    out = {}
    for table, alias in _SOURCE_TABLE.findall(sql):
        out[table.lower()] = table.lower()
        if alias and alias.lower() not in NOT_AN_ALIAS:
            out[alias.lower()] = table.lower()
    return out


def _clashing_predicates(sql: str) -> list:
    """Every `a.col = b.col` in `sql` that crosses the split uncollated.

    A binary collation on either side settles the comparison by itself, and an
    explicit COLLATE on either side settles it deliberately. Anything else that
    puts a utf8mb4_unicode_ci STRING column against a utf8mb4_0900_ai_ci one is
    a 1267 waiting for the first cycle that runs it.

    Deliberately narrow: it understands `a.col = b.col` and nothing else. The
    statement-level sweep beside it is the backstop for the shapes it cannot
    read - subqueries, IN lists, EXISTS, UNION - and for a string column added
    to a table after STRING_COLUMNS was written.
    """
    bad = []
    aliases = _aliases(sql)
    for left, lcol, lcollate, right, rcol, rcollate in _COMPARISON.findall(sql):
        ltable = aliases.get(left.lower(), "")
        rtable = aliases.get(right.lower(), "")
        pair = {COLLATIONS.get(ltable, ""), COLLATIONS.get(rtable, "")}
        if "" in pair or len(pair) == 1 or BINARY in pair:
            continue
        if lcol.lower() not in STRING_COLUMNS.get(ltable, frozenset()):
            continue
        if rcol.lower() not in STRING_COLUMNS.get(rtable, frozenset()):
            continue
        if lcollate or rcollate:
            continue
        bad.append("%s.%s = %s.%s" % (left, lcol, right, rcol))
    return bad


def _tables_spanned(sql: str) -> set:
    """The collations of the overseer tables one statement names."""
    return {
        COLLATIONS[table]
        for table in _aliases(sql).values()
        if table in COLLATIONS and table.startswith("overseer_")
    }


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    indent = len(src[:start].split("\n")[-1])
    lines = src[start:].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.strip() and not line.startswith(" " * (indent + 1)):
            break
        out.append(line)
    return "\n".join(out)


class TheErrandJoinNamesItsCollation(unittest.TestCase):
    """The one join in the tree that crosses the split, and the one that fell
    over. `_errand_traveller` is the first question both the protect cycle and
    the life recheck ask, so its failure was never local to itself."""

    def test_the_trade_side_carries_an_explicit_collate(self):
        sql = [s for _, _, s in _statements() if "overseer_trade t" in s]
        self.assertEqual(len(sql), 1, "expected exactly one errand join")
        self.assertIn("t.character_name COLLATE utf8mb4_unicode_ci = r.name", sql[0])

    def test_the_collate_is_written_on_the_0900_side(self):
        """overseer_roster.name is already utf8mb4_unicode_ci, so collating the
        OTHER operand leaves the roster's own index usable and converts only
        the joined column. Collating r.name would work and cost the index."""
        sql = [s for _, _, s in _statements() if "overseer_trade t" in s][0]
        self.assertNotIn("r.name COLLATE", sql)

    def test_the_predicate_sweep_finds_nothing_wrong_with_it(self):
        sql = [s for _, _, s in _statements() if "overseer_trade t" in s][0]
        self.assertEqual([], _clashing_predicates(sql))


class NoJoinCrossesTheSplitUncollated(unittest.TestCase):
    """The guard the issue asks for: a join written the old way fails the suite
    rather than production."""

    def test_no_predicate_compares_the_two_groups_without_a_collation(self):
        offenders = []
        for path, lineno, sql in _statements():
            for predicate in _clashing_predicates(sql):
                offenders.append("%s:%d  %s" % (path.name, lineno, predicate))
        self.assertEqual(
            [],
            offenders,
            "These compare a utf8mb4_unicode_ci column against a "
            "utf8mb4_0900_ai_ci one, which MySQL refuses with error 1267 and "
            "which fails the WHOLE statement, not one row. Write "
            "`COLLATE utf8mb4_unicode_ci` after the operand from the "
            "utf8mb4_0900_ai_ci table - see the block comment above "
            "_errand_traveller in bridge.py (infra#3173): " + "; ".join(offenders),
        )

    def test_no_statement_names_both_groups_without_collating_something(self):
        """The blunt half, and it is here because the precise half above only
        understands `a.col = b.col`. A subquery, an IN list, an EXISTS or a
        UNION can cross the split too, and each raises the same 1267."""
        offenders = []
        for path, lineno, sql in _statements():
            if len(_tables_spanned(sql)) > 1 and "COLLATE" not in sql.upper():
                offenders.append("%s:%d  %s" % (path.name, lineno, sql[:120]))
        self.assertEqual(
            [],
            offenders,
            "A statement naming tables from both collation groups and never "
            "saying COLLATE: " + "; ".join(offenders),
        )

    def test_the_sweep_would_have_caught_the_query_that_broke(self):
        """Without this the two sweeps above could be vacuously green - a
        checker that finds nothing is indistinguishable from a checker that
        cannot find anything. This is the exact SQL that was raising 1267 in
        both namespaces before infra#3173."""
        old = (
            "SELECT r.name FROM overseer_roster r "
            "JOIN overseer_trade t ON t.character_name = r.name "
            "WHERE r.enabled = 1 ORDER BY t.id LIMIT 1"
        )
        self.assertEqual(["t.character_name = r.name"], _clashing_predicates(old))
        self.assertEqual(
            {"utf8mb4_unicode_ci", "utf8mb4_0900_ai_ci"}, _tables_spanned(old)
        )

    def test_the_sweep_ignores_a_pair_of_numbers(self):
        """`t.skill_id = r.learn_skill` crosses the same two tables and is
        perfectly legal: neither column carries a collation. Flagging it would
        teach the next reader to sprinkle COLLATE where it does nothing, and
        then to ignore the sweep when it is right."""
        numeric = (
            "SELECT 1 FROM overseer_roster r JOIN overseer_trade t "
            "ON t.skill_id = r.learn_skill"
        )
        self.assertEqual([], _clashing_predicates(numeric))

    def test_the_sweep_accepts_the_collation_on_either_operand(self):
        """Both spellings are correct SQL and both settle the predicate. The
        sweep must not push anybody towards one by rejecting the other."""
        left = (
            "SELECT 1 FROM overseer_roster r JOIN overseer_trade t "
            "ON t.character_name COLLATE utf8mb4_unicode_ci = r.name"
        )
        right = (
            "SELECT 1 FROM overseer_roster r JOIN overseer_trade t "
            "ON t.character_name = r.name COLLATE utf8mb4_0900_ai_ci"
        )
        self.assertEqual([], _clashing_predicates(left))
        self.assertEqual([], _clashing_predicates(right))

    def test_the_sweep_reads_real_statements(self):
        """A guard over an empty list is not a guard. These scripts run a lot
        of SQL; if the collector ever stops finding it, every assertion above
        goes quietly green."""
        found = _statements()
        self.assertGreater(len(found), 40)
        self.assertTrue(any("overseer_roster" in s for _, _, s in found))


class EveryTableQueriedHasARecordedCollation(unittest.TestCase):
    """A table nobody has looked up is a hole in the sweep, not an exemption."""

    def test_no_overseer_table_is_queried_without_one(self):
        unknown = set()
        for _, _, sql in _statements():
            for table in _aliases(sql).values():
                if table.startswith("overseer_") and table not in COLLATIONS:
                    unknown.add(table)
        self.assertEqual(
            set(),
            unknown,
            "These overseer tables are queried but their collation is not "
            "recorded in COLLATIONS, so no join to them can be checked. Read "
            "it from information_schema.TABLES on both realms and add it: "
            + ", ".join(sorted(unknown)),
        )

    def test_every_overseer_table_has_its_string_columns_recorded(self):
        """COLLATIONS says which side of the split a table is on;
        STRING_COLUMNS says which of its columns the split can even reach. A
        table in one and missing from the other makes the precise sweep skip
        every predicate that touches it, silently."""
        overseer = {t for t in COLLATIONS if t.startswith("overseer_")}
        self.assertEqual(set(), overseer - set(STRING_COLUMNS))
        self.assertEqual(set(), set(STRING_COLUMNS) - overseer)
        for table, columns in STRING_COLUMNS.items():
            self.assertTrue(columns, "%s has no string columns recorded" % table)

    def test_the_two_groups_are_both_populated(self):
        """If somebody ever normalises the tables the split is gone and this
        whole file can go with it. Until then, both halves must be real."""
        groups = set(COLLATIONS.values())
        self.assertIn("utf8mb4_unicode_ci", groups)
        self.assertIn("utf8mb4_0900_ai_ci", groups)


class TheCharactersJoinsAreLeftAlone(unittest.TestCase):
    """characters.name is utf8mb4_bin and wins on its own. Collating it would
    be a silent behaviour change: an exact-match join becoming a case- and
    accent-insensitive one, in a family where names are the only key."""

    def test_no_join_to_characters_forces_a_collation_onto_it(self):
        offenders = []
        for path, lineno, sql in _statements():
            aliases = _aliases(sql)
            if "characters" not in aliases.values():
                continue
            for left, _, lcollate, right, _, rcollate in _COMPARISON.findall(sql):
                pair = {aliases.get(left.lower()), aliases.get(right.lower())}
                if "characters" in pair and (lcollate or rcollate):
                    offenders.append("%s:%d" % (path.name, lineno))
        self.assertEqual([], offenders, "; ".join(offenders))

    def test_the_snapshot_join_still_needs_no_collate(self):
        """The join the sweep must NOT flag, named explicitly so a future
        tightening of the rule cannot start demanding COLLATE everywhere."""
        sql = (
            "SELECT c.name FROM characters c "
            "LEFT JOIN overseer_snapshot s ON s.name = c.name"
        )
        self.assertEqual([], _clashing_predicates(sql))


class AnUnexpectedDatabaseErrorDoesNotEndTheCycle(unittest.TestCase):
    """The second half of infra#3173. The COLLATE stops THIS 1267; nothing
    stops the next unexpected error, and re-raising it is what turned one bad
    query into a whole abandoned cycle."""

    def test_the_errand_lookup_no_longer_re_raises(self):
        body = _block("def _errand_traveller() -> str:")
        self.assertNotIn("\n            raise", body)

    def test_it_catches_every_database_error_and_only_database_errors(self):
        """pymysql.err.MySQLError is the base of the whole family, so a
        connection error, a 1267 and a 1054 all land here. It is NOT `except
        Exception` - a TypeError in this function is a bug in this function and
        must still reach the loop's handler as one."""
        body = _block("def _errand_traveller() -> str:")
        self.assertIn("except pymysql.err.MySQLError as exc:", body)
        self.assertNotIn("except Exception", body)

    def test_it_logs_the_traceback_at_error_rather_than_swallowing(self):
        """`log.exception` writes at ERROR with the traceback, every cycle it
        happens. Degrading quietly here would trade one visible outage for an
        invisible one, which is the worse of the two."""
        body = _block("def _errand_traveller() -> str:")
        self.assertIn("log.exception(", body)

    def test_the_schema_drift_codes_still_degrade_silently(self):
        """1054 and 1146 mean the errand machinery is simply not deployed on
        this realm. That is a known, expected shape and was never noise worth
        logging every twenty seconds."""
        body = _block("def _errand_traveller() -> str:")
        self.assertIn("exc.args[0] in (1054, 1146)", body)

    def test_the_answer_it_degrades_to_is_nobody(self):
        """`_head_now` falls back to bonds.head_of_family(), the resting state,
        and the rest of the cycle - professions, spec tabs, randomize guards,
        strategies - still runs."""
        body = _block("def _errand_traveller() -> str:")
        self.assertGreaterEqual(body.count('return ""'), 2)
        self.assertIn("bonds.head_of_family()", _block("def _head_now() -> str:"))


class TheReasonIsWrittenWhereAJoinAuthorWillReadIt(unittest.TestCase):
    """A one-word fix with no explanation beside it gets removed by the next
    person who tidies the query up."""

    def test_the_block_above_the_join_names_the_error_and_both_collations(self):
        src = BRIDGE.read_text(encoding="utf-8")
        head = src[: src.index("def _errand_traveller() -> str:")]
        block = head[head.rindex("# THE overseer_") :]
        for needed in (
            "1267",
            "utf8mb4_unicode_ci",
            "utf8mb4_0900_ai_ci",
            "utf8mb4_bin",
            "infra#3173",
        ):
            self.assertIn(needed, block)

    def test_it_says_which_side_to_collate(self):
        src = BRIDGE.read_text(encoding="utf-8")
        head = src[: src.index("def _errand_traveller() -> str:")]
        block = head[head.rindex("# THE overseer_") :]
        self.assertIn("COLLATE utf8mb4_unicode_ci", block)
        self.assertIn("test_collation_split.py", block)

    def test_it_warns_off_the_characters_join(self):
        src = BRIDGE.read_text(encoding="utf-8")
        head = src[: src.index("def _errand_traveller() -> str:")]
        block = head[head.rindex("# THE overseer_") :]
        self.assertIn("characters.name is utf8mb4_bin", block)


if __name__ == "__main__":
    unittest.main()
