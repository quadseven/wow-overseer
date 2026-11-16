"""The realm's table and column names, and a read-only SQL checker built on them.

`data/acore_schema.json` is a snapshot of information_schema for the three
game databases (table -> ordered column list). Lint and the seed compiler both
check names against it, so a decree cannot carry a mistyped column. In a world
the seed step builds a `Schema` from the live database instead
(`Schema.from_rows`), which is what catches drift between the snapshot and the
image under test.
"""

import json
import pathlib
import re

# The package ships its own snapshot (it is built into a separate image), so the
# path stays beside the code rather than under the bridge's shared data root.
SNAPSHOT_NAME = "acore_schema.json"
DEFAULT_PATH = pathlib.Path(__file__).resolve().parent / "data" / SNAPSHOT_NAME
DEFAULT_DB = "acore_characters"
GAME_DBS = ("acore_characters", "acore_world", "acore_playerbots")


class Schema:
    def __init__(self, tables):
        # {db: {table: [columns]}}
        self.tables = tables

    @classmethod
    def load(cls, path=None):
        with open(path or DEFAULT_PATH, encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_rows(cls, rows):
        """Build from (db, table, column) rows read out of information_schema."""
        tables = {}
        for db, table, column in rows:
            tables.setdefault(db, {}).setdefault(table, []).append(column)
        return cls(tables)

    def columns(self, table, db=DEFAULT_DB):
        return self.tables.get(db, {}).get(table)

    def has_table(self, table, db=DEFAULT_DB):
        return self.columns(table, db) is not None

    def has_column(self, table, column, db=DEFAULT_DB):
        cols = self.columns(table, db)
        return cols is not None and column in cols

    def find_table(self, table):
        """Unqualified lookup: the default database first, then the others."""
        for db in (DEFAULT_DB, "acore_world", "acore_playerbots"):
            if self.has_table(table, db):
                return db
        return None


_KEYWORDS = set(
    """select from where and or not in is null like between join left right inner outer cross
    on as group by order having limit offset distinct all union exists true false case when
    then else end asc desc interval using natural straight_join div mod xor regexp rlike
    current_timestamp second minute hour day week month year with rollup separator
    escape binary unsigned signed""".split()
)
_FORBIDDEN = set(
    """insert update delete replace drop alter create truncate grant revoke set call load
    into outfile dumpfile handler lock unlock rename prepare execute use show describe
    explain optimize analyze flush kill sleep benchmark get_lock load_file""".split()
)
_FROM_ENDERS = {
    "where",
    "group",
    "order",
    "having",
    "limit",
    "union",
    "on",
    "using",
    "select",
}
_ALIAS_STOP = _KEYWORDS | {"set"}

_TOKEN = re.compile(
    r"""\s+|(?P<str>'(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*")|(?P<var>@[A-Za-z_][A-Za-z0-9_]*)
    |(?P<num>\d+(?:\.\d+)?)|(?P<id>`[^`]+`|[A-Za-z_][A-Za-z0-9_$]*)|(?P<op>.)""",
    re.X,
)


def _tokens(sql):
    out = []
    pos = 0
    while pos < len(sql):
        m = _TOKEN.match(sql, pos)
        pos = m.end()
        kind = m.lastgroup
        if kind is None:
            continue
        text = m.group(kind)
        if kind == "id" and text.startswith("`"):
            text = text[1:-1]
            out.append(("id", text, True))
        else:
            out.append((kind, text, False))
    return out


def check_select(sql, schema, known_vars=None):
    """Problems with a read-only SELECT, as a list of strings (empty = fine).

    Checks: one SELECT statement, no comments, no write or file keywords, every
    table exists, every column exists in a table the query names, and (when
    `known_vars` is given) every @variable is one the judge defines.
    """
    body = sql.strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if not re.match(r"(?is)^select\b", body):
        return ["SQL must be a single SELECT statement"]
    toks = _tokens(body)
    problems = _syntax_problems(body, toks, known_vars)
    aliases, skip = _collect_tables(toks, schema, problems)
    problems.extend(_column_problems(toks, schema, aliases, skip))
    problems.extend(_vacuous_problems(toks, aliases))
    return sorted(set(problems))


def _vacuous_problems(toks, aliases):
    """An observation must look at the world: a known table, or seeded state.

    `SELECT 1` is true whatever happened, so a decree made of such queries would
    pass without observing anything. `@t0` alone is only a clock.
    """
    state_vars = [t for t in toks if t[0] == "var" and t[1] != "@t0"]
    if aliases or state_vars:
        return []
    return ["observation reads no table and no seeded variable, so it cannot fail"]


def _syntax_problems(body, toks, known_vars):
    problems = []
    non_str = "".join(t[1] if t[0] != "str" else "''" for t in toks)
    if ";" in non_str:
        problems.append("SQL must be a single statement (found ';')")
    stripped = re.sub(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"", "''", body)
    if "--" in stripped or "/*" in stripped or "#" in stripped:
        problems.append("SQL comments are not allowed")
    for kind, text, quoted in toks:
        if kind == "id" and not quoted and text.lower() in _FORBIDDEN:
            problems.append(f"keyword {text.upper()} is not allowed in an observation")
        if kind == "var" and known_vars is not None and not known_vars(text[1:]):
            problems.append(f"unknown variable {text}")
    return problems


def _is_word(tok, *words):
    return tok[0] == "id" and not tok[2] and tok[1].lower() in words


def _collect_tables(toks, schema, problems):
    """Every table the query names: ({alias or table: (db, table)}, token indexes of the refs)."""
    aliases = {}
    skip = set()
    in_from = False
    i = 0
    while i < len(toks):
        tok = toks[i]
        starts_ref = _is_word(tok, "from", "join") or (
            in_from and tok[0] == "op" and tok[1] == ","
        )
        if starts_ref:
            in_from = True
            end = _table_ref(toks, i + 1, schema, aliases, problems)
            skip.update(range(i + 1, end))
            i = end
            continue
        if _is_word(tok, *_FROM_ENDERS) or (tok[0] == "op" and tok[1] == ")"):
            in_from = False
        i += 1
    return aliases, skip


def tables_read(sql, schema):
    """The set of (database, table) a SELECT actually reads: its FROM and JOIN refs.

    A table name inside a string, a function argument, a column or an alias is
    not a read, so it never appears here. Unknown tables are left out.
    """
    body = sql.strip().rstrip(";")
    aliases, _ = _collect_tables(_tokens(body), schema, [])
    return set(aliases.values())


def _select_aliases(toks):
    return {
        toks[j + 1][1].lower() for j in range(len(toks) - 1) if _is_word(toks[j], "as")
    }


def _column_problems(toks, schema, aliases, skip):
    problems = []
    select_aliases = _select_aliases(toks)
    all_cols = set()
    for db, table in aliases.values():
        all_cols.update(schema.columns(table, db) or [])
    j = 0
    while j < len(toks):
        if j in skip:
            j += 1
            continue
        step, problem = _column_ref(toks, j, schema, aliases, all_cols, select_aliases)
        if problem:
            problems.append(problem)
        j += step
    return problems


def _is_op(tok, text):
    return tok is not None and tok[0] == "op" and tok[1] == text


def _column_ref(toks, j, schema, aliases, all_cols, select_aliases):
    """Check the token at j. Returns (tokens consumed, problem or None)."""
    kind, text, quoted = toks[j]
    nxt = toks[j + 1] if j + 1 < len(toks) else None
    prev = toks[j - 1] if j > 0 else None
    if kind != "id" or _is_op(prev, ".") or _is_op(nxt, "("):
        return 1, None  # not a name, the tail of a qualified name, or a function call
    if _is_op(nxt, ".") and j + 2 < len(toks):
        return _qualified_ref(toks, j, schema, aliases)
    problem = _bare_problem(text, quoted, prev, aliases, all_cols, select_aliases)
    return 1, problem


def _bare_problem(text, quoted, prev, aliases, all_cols, select_aliases):
    low = text.lower()
    if not quoted and (low in _KEYWORDS or low in _FORBIDDEN):
        return None
    if prev and _is_word(prev, "as", "from", "join"):
        return None
    if low in select_aliases or text in aliases or text in all_cols:
        return None
    if aliases:
        return f"no referenced table has a column {text!r}"
    if not quoted:
        return f"{text!r} is not a column of any table (no FROM clause)"
    return None


def _qualified_ref(toks, j, schema, aliases):
    """`alias.column`, `db.table` (a FROM entry) or `db.table.column`."""
    qualifier, second = toks[j][1], toks[j + 2][1]
    three = j + 4 < len(toks) and _is_op(toks[j + 3], ".")
    if qualifier in GAME_DBS and three:
        return 5, _three_part_problem(qualifier, second, toks[j + 4][1], schema)
    return 3, _qualified_problem(qualifier, second, schema, aliases)


def _three_part_problem(db, table, col, schema):
    if not schema.has_table(table, db):
        return f"unknown table {db}.{table}"
    if col != "*" and not schema.has_column(table, col, db):
        return f"table {db}.{table} has no column {col!r}"
    return None


def _qualified_problem(qualifier, col, schema, aliases):
    if qualifier in aliases:
        db, table = aliases[qualifier]
        if col != "*" and not schema.has_column(table, col, db):
            return f"table {db}.{table} has no column {col!r}"
        return None
    if qualifier in GAME_DBS:
        return (
            f"{qualifier}.{col} is not a table.column: name the table (db.table.column)"
        )
    return f"unknown table or alias {qualifier!r}"


def _table_ref(toks, i, schema, aliases, problems):
    """Parse `[db.]table [[AS] alias]` at toks[i]. Returns (next index, opaque)."""
    if i >= len(toks):
        problems.append("dangling FROM or JOIN")
        return i
    kind, text, _ = toks[i]
    if kind == "op" and text == "(":
        problems.append(
            "a derived table (FROM (SELECT ...)) is not supported in an observation; join the table"
        )
        return i + 1
    db = None
    table = text
    if i + 2 < len(toks) and toks[i + 1][1] == "." and toks[i + 1][0] == "op":
        db, table = text, toks[i + 2][1]
        i += 2
    i += 1
    if db is None:
        db = schema.find_table(table)
        if db is None:
            problems.append(f"unknown table {table!r}")
            db = DEFAULT_DB
    else:
        if db not in GAME_DBS:
            problems.append(f"database {db!r} is not a game database")
        elif not schema.has_table(table, db):
            problems.append(f"unknown table {db}.{table}")
    alias = table
    if i < len(toks) and toks[i][0] == "id" and toks[i][1].lower() == "as":
        i += 1
    if i < len(toks) and toks[i][0] == "id" and toks[i][1].lower() not in _ALIAS_STOP:
        alias = toks[i][1]
        i += 1
    aliases[alias] = (db, table)
    aliases.setdefault(table, (db, table))
    return i
