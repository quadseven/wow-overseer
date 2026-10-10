"""The Chronicle's page contract, asserted against index.html as source the
way test_family_tab.py and test_armory_tab.py do - map_server.py imports
pymysql and the page has no other test seam.

THIS SUITE WAS test_achievements_tab.py. The view was renamed rather than
duplicated: same endpoint, same module, a stat strip and cards in place of a
rail with dots on it. The assertions that moved with it are the ones about
WHERE the code sits and about the page deciding nothing; the ones that are
new are about the four things a card no longer composes for itself.

Three of these are about placement. The Family tests slice the page from
their banner to loadZones().then( (script) and to the end of the stylesheet
(CSS); the Armory tests slice from their banner to </script>. Code dropped
into either window is swept into assertions about a different view, so this
view's block lives between the map's intervals and the Council banner, and
its CSS above the Family banner.

Tickets: infra#2597, mod-overseer#88, mod-overseer#152.
"""

import pathlib
import unittest

import achievements

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
CSS_BANNER = "/* --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
NEXT = "// --- the Council (infra#2597)"
NEXT_CSS = "/* --- the Council (infra#2597)"


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    THE GUARDS BELOW HAD TO BE ASKED OF THE CODE AND NOT OF THE FILE, and
    finding that out is the reason this exists: the first run of
    test_the_body_and_the_line_are_not_composed_here failed on the block's own
    banner, which quotes "led by Grug, 21m in the instance" as the example of
    the sentence that moved into Python. A guard that a comment can trip is a
    guard that gets weakened until it passes.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )


class TheChronicle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_a_missing_run_table_degrades_rather_than_failing(self):
        """The live realm's schema predates overseer_dungeon_run. Error 1146
        on that one query must leave quests and levels standing."""
        runs = self.server[self.server.index("def _fetch_family_runs") :]
        runs = runs[: runs.index("def _fetch_achievements")]
        self.assertIn("1146", runs)
        self.assertIn("return []", runs)

    def test_no_em_dashes(self):
        for name in (
            "achievements.py",
            "council.py",
            "eye.py",
            "map_server.py",
            "tests/test_achievements.py",
            "tests/test_chronicle_tab.py",
            "lootstory.py",
            "tests/test_lootstory.py",
        ):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )


class TheModuleOwnsTheWordsAndTheHues(unittest.TestCase):
    """The other half of the same contract, asked of achievements.py."""

    def test_every_kind_has_a_word_and_a_hue(self):
        for kind in (
            achievements.RUN,
            achievements.QUEST,
            achievements.LEVEL,
            achievements.FIRST,
        ):
            self.assertIn(kind, achievements.KIND_WORDS, kind)
            self.assertIn(kind, achievements.KIND_HUES, kind)


class BothFamiliesAndNoGearInTheWay(unittest.TestCase):
    """#135: the Chronicle told one family's story, and a loot board for the
    last dungeon filled most of the screen above it."""

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_a_familys_runs_are_its_own(self):
        runs = self.server[self.server.index("def _fetch_family_runs") :]
        runs = runs[: runs.index("def _fetch_achievements")]
        self.assertIn("WHERE leader_name IN ({holes})", runs)
        self.assertIn("run_rows = _fetch_family_runs(cur, names, holes)", self.server)


class NotableLootIsTheModulesSentence(unittest.TestCase):
    """mod-overseer#567: every rare, epic and legendary item the families'
    guilds looted, who it went to and when it went on. The sentence is
    lootstory.py's; this block draws it."""

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_a_missing_story_column_degrades_rather_than_failing(self):
        fetch = self.server[self.server.index("def _fetch_loot") :]
        fetch = fetch[: fetch.index("\ndef ")]
        self.assertIn("_guarded(", fetch)
        self.assertIn('fallback=base.format(story="")', fetch)


if __name__ == "__main__":
    unittest.main()
