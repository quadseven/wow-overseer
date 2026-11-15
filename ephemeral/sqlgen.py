"""The only way the seed step writes SQL.

Every write statement is built here from a table and column names checked
against the schema, and re-verified by `verify_statement` before it runs.
The shapes allowed are exactly four (INSERT, REPLACE, UPDATE, DELETE), each
aimed at one table of the world's own character database, with literal values
only: no variables, no sub-selects, no other database, no comments, no second
statement. Nothing in a decree can widen that.
"""

import re
from dataclasses import dataclass

WRITE_DB = "acore_characters"
# Tables a seed never writes. A job goes in as an overseer_command row (a direct
# overseer_roster update was measured to have no effect), and the realm id is
# the baseline's (the worldserver only accepts 1 to 255).
NEVER_WRITTEN = {"overseer_roster", "overseer_command", "realmlist", "realmcharacters"}
_SAFE_STRING = re.compile(r"^[A-Za-z0-9 _.,:\-]*$")
_STRING = re.compile(r"'(?:[^'\\]|'')*'")
_BACKTICKED = re.compile(r"`([^`]*)`")
_ALLOWED_WORDS = {
    "INSERT", "INTO", "VALUES", "REPLACE", "UPDATE", "SET", "WHERE", "AND", "IN",
    "DELETE", "FROM", "NULL", "UNIX_TIMESTAMP",
}  # fmt: skip
_HEAD = re.compile(
    r"^(INSERT INTO|REPLACE INTO|UPDATE|DELETE FROM) `([A-Za-z0-9_]+)`\.`([A-Za-z0-9_]+)` "
)


class SeedError(Exception):
    """The decree cannot be seeded; the run is INVALID, never a pass."""


@dataclass(frozen=True)
class NowPlus:
    """UNIX_TIMESTAMP() + seconds: the only expression a value may be."""

    seconds: int


@dataclass(frozen=True)
class Stmt:
    op: str  # insert | replace | update | delete
    table: str
    sql: str

    def __str__(self):
        return self.sql


def quote(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise SeedError("a non-finite number cannot be seeded")
        return format(value, ".6f")
    if isinstance(value, NowPlus):
        if not isinstance(value.seconds, int) or value.seconds < 0:
            raise SeedError("NowPlus needs a non-negative integer")
        return (
            f"UNIX_TIMESTAMP() + {value.seconds}"
            if value.seconds
            else "UNIX_TIMESTAMP()"
        )
    if isinstance(value, str):
        if not _SAFE_STRING.match(value):
            raise SeedError(
                f"string value {value!r} has characters a seed may not write"
            )
        return "'" + value + "'"
    raise SeedError(f"cannot seed a value of type {type(value).__name__}")


class Builder:
    """Builds verified statements for the world's character database."""

    def __init__(self, schema):
        self.schema = schema

    def _table(self, table):
        if table in NEVER_WRITTEN:
            raise SeedError(f"a seed never writes {table}")
        cols = self.schema.columns(table, WRITE_DB)
        if cols is None:
            raise SeedError(f"unknown table {WRITE_DB}.{table}")
        return cols

    def _check_cols(self, table, names):
        cols = self._table(table)
        for n in names:
            if n not in cols:
                raise SeedError(f"table {table} has no column {n!r}")

    def _where(self, table, where):
        if not where:
            raise SeedError("a write needs a WHERE")
        self._check_cols(table, where)
        parts = []
        for col, val in where.items():
            if isinstance(val, (list, tuple)):
                if not val:
                    raise SeedError("empty IN list")
                parts.append(f"`{col}` IN (" + ", ".join(quote(v) for v in val) + ")")
            else:
                parts.append(f"`{col}` = {quote(val)}")
        return " WHERE " + " AND ".join(parts)

    def _finish(self, op, table, sql):
        stmt = Stmt(op, table, sql)
        verify_statement(stmt.sql, self.schema)
        return stmt

    def insert(self, table, row, replace=False):
        self._check_cols(table, row)
        cols = ", ".join(f"`{c}`" for c in row)
        vals = ", ".join(quote(v) for v in row.values())
        verb = "REPLACE INTO" if replace else "INSERT INTO"
        sql = f"{verb} `{WRITE_DB}`.`{table}` ({cols}) VALUES ({vals})"
        return self._finish("replace" if replace else "insert", table, sql)

    def update(self, table, values, where):
        self._check_cols(table, values)
        sets = ", ".join(f"`{c}` = {quote(v)}" for c, v in values.items())
        sql = f"UPDATE `{WRITE_DB}`.`{table}` SET {sets}{self._where(table, where)}"
        return self._finish("update", table, sql)

    def delete(self, table, where):
        sql = f"DELETE FROM `{WRITE_DB}`.`{table}`{self._where(table, where)}"
        return self._finish("delete", table, sql)


def verify_statement(sql, schema):
    """Raise SeedError unless `sql` is one allowed write to the character database.

    Run again, at execution time, on every statement: the builder is not trusted
    to be the only thing that can hand the executor a string.
    """
    m = _HEAD.match(sql)
    if not m:
        raise SeedError(
            "statement is not INSERT, REPLACE, UPDATE or DELETE on one qualified table"
        )
    op, db, table = m.groups()
    if db != WRITE_DB:
        raise SeedError(f"statement targets database {db!r}, not {WRITE_DB}")
    cols = schema.columns(table, WRITE_DB)
    if cols is None or table in NEVER_WRITTEN:
        raise SeedError(f"{WRITE_DB}.{table} is unknown or never written by a seed")
    bare = _without_strings(sql[m.end() :])
    _check_characters(bare)
    bare = _check_columns(bare, table, cols)
    _check_words(bare)
    if op.startswith(("UPDATE", "DELETE")) and " WHERE " not in " " + bare + " ":
        raise SeedError("UPDATE and DELETE need a WHERE")
    if re.search(r"[^0-9A-Za-z_ ,()=.+\-']", bare):
        raise SeedError("statement contains a character a seed may not write")
    return True


def _without_strings(rest):
    bare = _STRING.sub("''", rest)
    if "'" in bare.replace("''", ""):
        raise SeedError("unbalanced quote")
    return bare


def _check_characters(bare):
    for bad in (";", "@", "--", "/*", "*/", "#", "\\", '"'):
        if bad in bare:
            raise SeedError(f"statement contains {bad!r}")


def _check_columns(bare, table, cols):
    for ident in _BACKTICKED.findall(bare):
        if ident not in cols:
            raise SeedError(f"table {table} has no column {ident!r}")
    return _BACKTICKED.sub("", bare)


def _check_words(bare):
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", bare):
        if word.upper() not in _ALLOWED_WORDS:
            raise SeedError(f"word {word!r} is not allowed in a seed statement")
