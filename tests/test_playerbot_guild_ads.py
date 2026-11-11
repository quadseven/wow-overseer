"""Guild-seeking bot speech must not survive in suggest_something (#1640).

The speech templates live in a database table, ai_playerbot_texts, seeded
from the playerbots module tree at the pin recorded as AC_MODULE_SHA in
UPSTREAM-PINS.env. The fixture rows below are the suggest_something rows
of that seed (data/sql/playerbots/base/ai_playerbot_texts.sql at the pin)
whose English text is a guild advertisement or a guild search: a speaker
that already has a guild saying one of these in guild chat asserts a
state it is not in.

The fix is a SQL update file for the worldserver DB updater, in the same
updates directory the playerbots tree uses, so applying it prunes the
live rows and a later seed import is not the only record of the change.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATES = ROOT / "data" / "sql" / "playerbots" / "updates"

# (id, English text) from the seed at the pin, class suggest_something.
GUILD_SEEKING = (
    (741, "%my_role is looking for guild."),
    (743, "%my_role wants to join a good guild."),
    (801, "any guilds willing to carry %my_role?"),
    (816, "any leveling guilds out there?"),
)
FIXTURE_IDS = {row_id for row_id, _ in GUILD_SEEKING}

SEEKING = re.compile(
    r"looking for (a )?guild|join a .*guild|guilds willing|leveling guilds",
    re.IGNORECASE,
)


def _statements():
    """The SQL statements in the updates directory, comments stripped."""
    if not UPDATES.is_dir():
        return []
    out = []
    for path in sorted(UPDATES.glob("*.sql")):
        raw = path.read_bytes()
        text = "\n".join(
            line
            for line in raw.decode("ascii").splitlines()
            if not line.lstrip().startswith("--")
        )
        out.extend(s.strip() for s in text.split(";") if s.strip())
    return out


def _ids_in(fragment):
    ids = set()
    for group in re.findall(r"\bIN\s*\(([^)]*)\)", fragment, re.IGNORECASE):
        ids.update(int(n) for n in re.findall(r"\d+", group))
    ids.update(int(n) for n in re.findall(r"\bid\s*=\s*(\d+)", fragment))
    return ids


def _addressed():
    """id -> ('delete', None) or ('update', new_text), from the update SQL."""
    found = {}
    for stmt in _statements():
        if "ai_playerbot_texts" not in stmt:
            continue
        if re.match(r"(?is)\s*DELETE\b", stmt):
            for row_id in _ids_in(stmt):
                found[row_id] = ("delete", None)
        elif re.match(r"(?is)\s*UPDATE\b", stmt):
            match = re.search(r"\btext\s*=\s*'([^']*)'", stmt, re.IGNORECASE)
            for row_id in _ids_in(stmt):
                found[row_id] = ("update", match.group(1) if match else None)
    return found


class GuildAdsPrunedTest(unittest.TestCase):
    def test_an_update_file_sits_in_the_playerbots_updates_directory(self):
        self.assertTrue(UPDATES.is_dir(), "no data/sql/playerbots/updates/")
        self.assertTrue(
            list(UPDATES.glob("*.sql")), "the updates directory holds no SQL"
        )

    def test_every_guild_seeking_row_is_pruned(self):
        found = _addressed()
        for row_id, text in GUILD_SEEKING:
            with self.subTest(row_id=row_id, text=text):
                self.assertIn(
                    row_id,
                    found,
                    f"seed row {row_id} ({text!r}) is not deleted or rewritten",
                )

    def test_no_pruned_row_is_rewritten_to_another_guild_search(self):
        for row_id, (kind, new_text) in _addressed().items():
            if kind != "update":
                continue
            with self.subTest(row_id=row_id):
                self.assertIsNotNone(new_text)
                self.assertNotRegex(new_text, SEEKING)
                self.assertNotIn(new_text, [t for _, t in GUILD_SEEKING])

    def test_the_update_touches_no_other_text_rows(self):
        self.assertEqual(set(_addressed()), FIXTURE_IDS)

    def test_each_pruning_statement_is_scoped_to_suggest_something(self):
        for stmt in _statements():
            if "ai_playerbot_texts" not in stmt:
                continue
            if not (_ids_in(stmt) & FIXTURE_IDS):
                continue
            self.assertIn(
                "suggest_something",
                stmt,
                f"a pruning statement is not guarded to the class: {stmt}",
            )


if __name__ == "__main__":
    unittest.main()
