"""REWARD_SQL names only real quest_template columns (#1854).

The catalogue tests stub every world read and key the stub on the SQL
text, so a wrong column name passes them and fails only against the realm
(`Unknown column 'RewardItem'`). This test reads each identifier out of
REWARD_SQL and checks it against the real column list in
`tests/fixtures/quest_template_columns.txt`.
"""

import pathlib
import re
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from _stub_modules import PYMYSQL, stub_modules  # noqa: E402

with stub_modules(pymysql=PYMYSQL):
    import questcatalogue as qc

FIXTURE = HERE / "tests" / "fixtures" / "quest_template_columns.txt"
TABLE = "acore_world.quest_template"
KEYWORDS = {"SELECT", "AS", "FROM", "WHERE", "IN", "UNION", "ALL"}


def real_columns() -> set:
    lines = FIXTURE.read_text(encoding="ascii").splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def named_columns(sql: str) -> set:
    """Every column identifier in a single-table query: keywords, the
    table, the `{ids}` placeholder and each `AS` alias removed."""
    text = sql.replace("{ids}", " ").replace(TABLE, " ")
    text = re.sub(r"\bAS\s+\w+", " ", text)
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)
    return {w for w in words if w.upper() not in KEYWORDS}


class RewardSqlColumns(unittest.TestCase):
    def test_fixture_is_the_real_table(self):
        columns = real_columns()
        self.assertIn("RewardItem1", columns)
        self.assertNotIn("RewardItem", columns)
        self.assertEqual(len(columns), 105)

    def test_reward_sql_reads_one_table(self):
        tables = set(re.findall(r"FROM\s+(\S+)", qc.REWARD_SQL))
        self.assertEqual(tables, {TABLE})

    def test_every_column_reward_sql_names_exists(self):
        unknown = sorted(named_columns(qc.REWARD_SQL) - real_columns())
        self.assertEqual(unknown, [], "REWARD_SQL names a column quest_template lacks")

    def test_reward_sql_reads_every_reward_slot(self):
        named = named_columns(qc.REWARD_SQL)
        for slot in range(1, 5):
            with self.subTest(slot=slot):
                self.assertIn("RewardItem%d" % slot, named)


if __name__ == "__main__":
    unittest.main()
