"""No playerbots SQL update may sit in this repository unapplied (#2252).

The guild-ad prune of ai_playerbot_texts first landed here as
data/sql/playerbots/updates/2026_11_10_00_ai_playerbot_guild_ads.sql, but
no realm roll or bridge ship reads data/sql: the bridge image copies data/
for the gear lists only, and the roll builds from module trees that do not
include this repository. A file there passes every check while the live
rows stay unchanged.

The prune now ships as a playerbots patch in the module repository, where
the module's own database updater reads it. This test keeps the trap shut:
a playerbots SQL file added under data/sql fails here, with a pointer to
where it belongs.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNREAD_SQL_DIR = ROOT / "data" / "sql" / "playerbots"


class NoUnappliedPlayerbotsSql(unittest.TestCase):
    def test_no_playerbots_sql_file_sits_where_nothing_applies_it(self):
        stray = (
            sorted(str(p.relative_to(ROOT)) for p in UNREAD_SQL_DIR.rglob("*.sql"))
            if UNREAD_SQL_DIR.exists()
            else []
        )
        self.assertEqual(
            stray,
            [],
            "nothing applies SQL under data/sql/playerbots; carry the change "
            "as a playerbots patch in the module repository instead",
        )


if __name__ == "__main__":
    unittest.main()
