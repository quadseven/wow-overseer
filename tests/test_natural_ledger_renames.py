"""The natural ledger follows a rename (2026-10-09).

The module writes the name a character had when it was reset; the approved
lineup renamed 114 guild members afterwards, and a read by that name found 28
of 142 members natural. The read joins by guid and answers the current name.
The query runs here against an in-memory SQLite copy of the two tables.
"""

import sqlite3
import unittest

import natural
from test_guildsocial_bridge import bridge


def ledger(rows, characters):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE overseer_naturalized (guid INT, part TEXT, name TEXT)")
    db.execute("CREATE TABLE characters (guid INT, name TEXT)")
    db.executemany("INSERT INTO overseer_naturalized VALUES (?, ?, ?)", rows)
    db.executemany("INSERT INTO characters VALUES (?, ?)", characters)
    cur = db.execute(bridge._NATURALIZED_SQL)
    cols = [d[0] for d in cur.description]
    return bridge._naturalized_rows(
        dict(zip(cols, r, strict=True)) for r in cur.fetchall()
    )


class TheLedgerFollowsRenames(unittest.TestCase):
    def test_a_renamed_member_is_read_under_its_name_now(self):
        rows = ledger([(1372, "reset", "Aalall")], [(1372, "Brug")])
        parts = natural.parts_by_name(rows)
        self.assertEqual(parts, {"Brug": {"reset"}})
        self.assertEqual(natural.contributors(["Brug"], [], parts, set()), {"Brug"})

    def test_an_unrenamed_member_is_unchanged(self):
        rows = ledger([(1, "reset", "Adalok")], [(1, "Adalok")])
        self.assertEqual(natural.parts_by_name(rows), {"Adalok": {"reset"}})

    def test_a_deleted_character_keeps_the_written_name(self):
        rows = ledger([(9, "reset", "Gone")], [])
        self.assertEqual(natural.parts_by_name(rows), {"Gone": {"reset"}})

    def test_the_old_name_no_longer_counts(self):
        rows = ledger([(1372, "reset", "Aalall")], [(1372, "Brug")])
        parts = natural.parts_by_name(rows)
        self.assertEqual(
            natural.contributors(["Aalall"], [], parts, set()), frozenset()
        )


if __name__ == "__main__":
    unittest.main()
