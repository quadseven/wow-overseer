"""Patch 0023 prunes guild advertisements from ai_playerbot_texts (#1640).

The guild-ad prune first landed as an unapplied SQL file under
data/sql/playerbots, which nothing reads; it now ships as a playerbots patch
in the module repository, where the module's own database updater reads it.
This test pins that the patch deletes rows 741 and 743 (and any other
suggest_something line that advertises for a guild) and that it applies to
the pinned fork.
"""

import os
import pathlib
import re
import shutil
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

    def test_patch_deletes_rows_741_and_743(self):
        self.assertIn(
            "DELETE FROM `ai_playerbot_texts` WHERE `id` IN (741, 743);", self.sql
        )

    def test_patch_audits_suggest_something_guild_ads(self):
        self.assertIn("name` = 'suggest_something'", self.sql)
        self.assertIn("looking for guild", self.sql)
        self.assertIn("join a good guild", self.sql)

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
