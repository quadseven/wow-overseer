"""Every SQL constant the site and bridge read with parses as MySQL 8 (#1038).

The API tests read through realmread.Memory, which matches a SQL string and
never parses it, so a syntax error passed them and was found live: #1025's
gear read aliased a column `AS character`, a MySQL 8 reserved word, and
answered 503. This test parses every module-level `*_SQL` string in apiv2/
and the top-level modules with sqlglot's MySQL dialect (pinned in
tests/requirements.txt) and fails on a parse error or on a reserved word used
as a bare identifier or alias. CI needs no database.

A reserved word after a period (`gm.rank`) is legal MySQL and passes; a bare
one (`AS rank`, `FROM characters character`) needs backquotes.
"""

import ast
import importlib
import os
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.dialects.mysql import MySQL
except ImportError:  # the lane check's plain python3; CI installs it
    sqlglot = None

NO_SQLGLOT = "needs sqlglot (pip install -r tests/requirements.txt); CI installs it"

# Built at runtime with a string join: a list of ids spliced into another
# statement, not a statement itself, so nothing here can parse it alone.
JOINED = {
    "bridge._CAMPAIGN_MAP_IDS_SQL",
    "preraid._MAPS_SQL",
    "preraid._ZONES_SQL",
}

# A constant name on its own line at module level, counted from the raw text
# so a gap in the AST collector below shows up as a count mismatch.
NAME_LINE = re.compile(r"^(_?[A-Z][A-Z0-9_]*_SQL)\s*[:=]", re.M)


def source_files():
    return sorted(ROOT.glob("*.py")) + sorted((ROOT / "apiv2").glob("*.py"))


def module_name(path):
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def sql_assignments(path):
    """{name: value node} for module-level assignments to a `*_SQL` name."""
    found = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.endswith("_SQL"):
                found[target.id] = value
    return found


def is_join(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
    )


def load(name):
    """Import a module; the bridge only needs discord.Client to define Bridge."""
    if name != "bridge":
        return importlib.import_module(name)
    discord = types.ModuleType("discord")
    discord.Client = object
    with mock.patch.dict(sys.modules, {"discord": discord}):
        return importlib.import_module(name)


def bindable(sql):
    """The statement with its placeholders filled, as the driver would send it.

    `%%s` is a placeholder once a `% holes` pass has run; `{holes}` and
    `{names}` are `.format` slots for an IN list.
    """
    sql = re.sub(r"%%s|%\(\w+\)s|%s|%d", "0", sql)
    sql = sql.replace("%%", "%")
    return re.sub(r"\{\w*\}", "0", sql)


# What sqlglot accepts and MySQL refuses: a stray comma (`a, FROM`, `a,, b`,
# a split string that lost a column) and an empty ON.
LENIENT = (
    (
        re.compile(r",\s*(,|\)|FROM\b|WHERE\b|GROUP\b|ORDER\b|LIMIT\b)", re.I),
        "a comma before %s",
    ),
    (
        re.compile(
            r"\bON\s+((?:LEFT\s+|RIGHT\s+|INNER\s+)?JOIN|WHERE|GROUP|ORDER|LIMIT)\b|\bON\s*$",
            re.I,
        ),
        "an empty ON before %s",
    ),
)


def after_period(identifier):
    parent = identifier.parent
    if identifier.arg_key != "this":
        return False
    if isinstance(parent, exp.Column):
        return bool(parent.args.get("table"))
    if isinstance(parent, exp.Table):
        return bool(parent.args.get("db"))
    return False


def problems(sql):
    """What MySQL 8 would refuse in `sql`, as a list of messages."""
    sql = bindable(sql)
    for pattern, message in LENIENT:
        if match := pattern.search(sql):
            return ["does not parse: " + message % (match.group(1) or "the end")]
    try:
        trees = sqlglot.parse(sql, read="mysql")
    except sqlglot.errors.SqlglotError as err:
        return ["does not parse: %s" % str(err).splitlines()[0]]
    reserved = MySQL.Generator.RESERVED_KEYWORDS
    found = []
    for tree in trees:
        if tree is None:
            continue
        for ident in tree.find_all(exp.Identifier):
            if ident.quoted or ident.this.lower() not in reserved:
                continue
            if not after_period(ident):
                found.append("bare reserved word %r" % ident.this)
    return sorted(set(found))


def statements():
    """(label, sql) for every SQL constant, and the labels skipped as joined."""
    out, skipped = [], set()
    for path in source_files():
        assigned = sql_assignments(path)
        if not assigned:
            continue
        mod = module_name(path)
        module = load(mod)
        for name, node in assigned.items():
            label = "%s.%s" % (mod, name)
            if is_join(node):
                skipped.add(label)
                continue
            value = getattr(module, name)
            if isinstance(value, dict):
                out.extend(("%s[%r]" % (label, k), v) for k, v in value.items())
            else:
                out.append((label, value))
    return out, skipped


@unittest.skipUnless(sqlglot or os.environ.get("CI"), NO_SQLGLOT)
class SqlParseTest(unittest.TestCase):
    def setUp(self):
        if sqlglot is None:
            self.fail("sqlglot is not installed in CI; see tests/requirements.txt")

    def test_every_constant_parses_as_mysql(self):
        found, _ = statements()
        bad = {}
        for label, sql in found:
            if not isinstance(sql, str):
                bad[label] = ["is a %s, not a SQL string" % type(sql).__name__]
            elif issues := problems(sql):
                bad[label] = issues
        self.assertEqual({}, bad)

    def test_only_the_known_joins_are_skipped(self):
        _, skipped = statements()
        self.assertEqual(JOINED, skipped)

    def test_every_apiv2_constant_is_collected(self):
        found, skipped = statements()
        labels = {label.split("[")[0] for label, _ in found} | skipped
        for path in sorted((ROOT / "apiv2").glob("*.py")):
            mod = module_name(path)
            written = {"%s.%s" % (mod, n) for n in NAME_LINE.findall(path.read_text())}
            collected = {label for label in labels if label.rsplit(".", 1)[0] == mod}
            self.assertEqual(written, collected, path.name)
        apiv2 = {label for label in labels if label.startswith("apiv2.")}
        # A floor so a moved directory cannot pass by finding nothing.
        self.assertGreater(len(apiv2), 50)

    def test_a_bare_reserved_alias_fails(self):
        sql = "SELECT c.name AS character FROM characters c WHERE c.guid = %s"
        self.assertEqual(["bare reserved word 'character'"], problems(sql))
        self.assertEqual(
            ["bare reserved word 'character'"],
            problems("SELECT character.name FROM characters character"),
        )

    def test_a_syntax_error_fails(self):
        for sql in (
            "SELECT name FROM characters WHERE guid IN ({holes}",
            "SELECT name, FROM characters WHERE guid = %s",
            "SELECT name,, level FROM characters WHERE guid = %s",
            "SELECT c.name FROM characters c JOIN guild_member gm ON WHERE c.guid = %s",
            "SELECT name FROM characters WHERE",
        ):
            (issue,) = problems(sql)
            self.assertTrue(issue.startswith("does not parse"), (sql, issue))

    def test_a_qualified_or_quoted_reserved_word_passes(self):
        self.assertEqual([], problems("SELECT gm.rank FROM guild_member gm"))
        self.assertEqual([], problems("SELECT name AS `character` FROM characters"))
        self.assertEqual([], problems("SELECT * FROM t WHERE a LIKE %%s AND b IN (%s)"))


if __name__ == "__main__":
    unittest.main()
