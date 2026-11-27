"""Patch 0023 prunes guild advertisements from ai_playerbot_texts (#1640).

The guild-ad prune first landed as an unapplied SQL file under
data/sql/playerbots, which nothing reads; it now ships as a playerbots patch
in the module repository, where the module's own database updater reads it.
These tests replay the patch's SQL to check that it removes guild ads without
deleting unrelated suggestions that reuse the old seed IDs.
"""

import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERIES_DIR = ROOT / "patches" / "mod-playerbots"
PATCH = SERIES_DIR / "0023-prune-guild-ads-from-ai-playerbot-texts.patch"
SERIES = (
    "0004-loot-needs-a-free-bag-slot.patch",
    "0005-wander-npc-can-be-aimed.patch",
    "0016-a-mage-only-conjures-food-at-a-usable-rank.patch",
    "0017-casters-hold-on-a-majordomo-add-with-magic-reflection.patch",
    "0018-melee-step-off-a-majordomo-add-with-damage-shield.patch",
    "0019-majordomo-healers-are-the-first-target-elites-after.patch",
    "0020-the-tank-retakes-the-majordomo-adds-it-held-after-teleport-target.patch",
    "0021-majordomo-add-holds-also-apply-to-area-target-selection.patch",
    "0022-sulfuron-priests-first-interrupts-and-a-bomb-follower.patch",
    PATCH.name,
)


def added_for(text, filename):
    for m in re.finditer(
        r"^diff --git a/(\S+) b/.*?(?=^diff --git |\Z)", text, re.M | re.S
    ):
        if m.group(1).endswith("/" + filename):
            lines = [
                line[1:]
                for line in m.group(0).splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            return "\n".join(lines)
    raise AssertionError("patch does not touch " + filename)


class GuildAdsPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.sql = added_for(cls.text, "2026_11_10_00_ai_playerbot_guild_ads.sql")

    def test_patch_is_numbered_after_0022_and_ascii(self):
        self.assertTrue(PATCH.name.startswith("0023-"))
        self.text.encode("ascii")

    def seed(self, *rows):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute(
            "CREATE TABLE ai_playerbot_texts "
            "(id INTEGER PRIMARY KEY, name TEXT COLLATE NOCASE, text TEXT)"
        )
        db.executemany("INSERT INTO ai_playerbot_texts VALUES (?, ?, ?)", rows)
        return db

    def test_patch_prunes_seed_ads_and_new_matches_on_replay(self):
        db = self.seed(
            (741, "suggest_something", "%my_role is looking for guild."),
            (743, "suggest_something", "%my_role wants to join a good guild."),
            (801, "suggest_something", "any guilds willing to carry %my_role?"),
            (816, "suggest_something", "any leveling guilds out there?"),
            (2001, "suggest_something", "  %MY_ROLE IS LOOKING FOR GUILD?!  "),
            (2002, "suggest_something", "Any leveling guilds out there"),
            (2003, "suggest_something", "Let's run a dungeon."),
        )
        for _ in range(2):
            db.executescript(self.sql)
            self.assertEqual(
                [(2003,)], db.execute("SELECT id FROM ai_playerbot_texts").fetchall()
            )

    def test_patch_preserves_reused_ids_without_a_matching_class_and_text(self):
        preserved = (
            (741, "suggest_something", "Let's run a dungeon."),
            (743, "another_class", "%my_role wants to join a good guild."),
            (2001, "SUGGEST_SOMETHING", "any leveling guilds out there?"),
        )
        db = self.seed(*preserved)
        db.executescript(self.sql)
        self.assertEqual(
            list(preserved),
            db.execute(
                "SELECT id, name, text FROM ai_playerbot_texts ORDER BY id"
            ).fetchall(),
        )

    def test_patch_preserves_harmless_surrounding_text(self):
        db = self.seed(
            (
                2101,
                "suggest_something",
                "Players often join a good guild after leveling.",
            ),
            (
                2102,
                "suggest_something",
                "%my_role is looking for guild. That is an old quote.",
            ),
            (
                2103,
                "suggest_something",
                "A player said: any leveling guilds out there?",
            ),
        )
        db.executescript(self.sql)
        self.assertEqual(
            [(2101,), (2102,), (2103,)],
            db.execute("SELECT id FROM ai_playerbot_texts ORDER BY id").fetchall(),
        )

    def test_series_files_exist_in_order(self):
        for name in SERIES:
            self.assertTrue((SERIES_DIR / name).is_file(), name)

    @unittest.skipUnless(
        os.environ.get("PLAYERBOTS_SRC"),
        "set PLAYERBOTS_SRC to a checkout of the pinned fork for the real check",
    )
    def test_series_applies_in_order_to_the_pinned_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "fork"
            shutil.copytree(os.environ["PLAYERBOTS_SRC"], tree)
            for name in SERIES:
                result = subprocess.run(
                    ["git", "apply", str(SERIES_DIR / name)],
                    cwd=tree,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, result.returncode, name + ": " + result.stderr)


if __name__ == "__main__":
    unittest.main()
