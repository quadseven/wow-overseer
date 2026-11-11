"""A stranded member refused for its hearthstone's cooldown waits to be asked
again (#2183).

The guild run loop sends every stranded guild member home by hearthstone, and
the once-an-hour spacing counts only hearths that went through. A refusal is an
error row, so a member whose stone was on cooldown was due again on the very
next cycle, for as long as it stayed stranded. The decision to ask again is
guildrun.hearth_backed_off, tested on rows written here; the bridge pass that
asks is pinned as source. The members are invented.
"""

import pathlib
import unittest

import guildrun
import jev_movement
import modsource

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
MODULE = modsource.read(modsource.MODULE, errors="replace")

COOLDOWN = "hearthstone is on cooldown"


def newest(name, status="error", detail=COOLDOWN, age=60):
    return {"name": name, "status": status, "detail": detail, "age": age}


class ACooldownRefusalIsNotAskedAgainAtOnce(unittest.TestCase):
    def test_a_member_refused_for_the_cooldown_is_held_inside_the_back_off(self):
        rows = [newest("Bonk", age=guildrun.HEARTH_BACKOFF_SECONDS - 1)]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})

    def test_it_is_due_again_when_the_back_off_has_passed(self):
        rows = [newest("Bonk", age=guildrun.HEARTH_BACKOFF_SECONDS)]
        self.assertEqual(guildrun.hearth_backed_off(rows), set())

    def test_one_member_held_does_not_hold_another(self):
        rows = [
            newest("Bonk", age=30),
            newest("Durg", age=guildrun.HEARTH_BACKOFF_SECONDS + 1),
        ]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})

    def test_the_words_are_read_inside_a_longer_detail(self):
        rows = [newest("Bonk", detail="refused: %s (4 min left)" % COOLDOWN)]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})


class OtherAnswersKeepToday(unittest.TestCase):
    def test_a_refusal_that_is_not_the_cooldown_is_asked_again_at_once(self):
        for words in ("character is moving", "character is already casting"):
            rows = [newest("Bonk", detail=words, age=5)]
            self.assertEqual(guildrun.hearth_backed_off(rows), set(), words)

    def test_a_hearth_that_went_through_is_not_a_back_off(self):
        rows = [newest("Bonk", status="applied", detail="", age=5)]
        self.assertEqual(guildrun.hearth_backed_off(rows), set())

    def test_no_row_means_due(self):
        self.assertEqual(guildrun.hearth_backed_off([]), set())


class TheBackOffIsBoundedAndPinned(unittest.TestCase):
    def test_it_never_outlasts_the_stones_own_cooldown(self):
        self.assertGreater(guildrun.HEARTH_BACKOFF_SECONDS, 0)
        self.assertLessEqual(
            guildrun.HEARTH_BACKOFF_SECONDS, jev_movement.HEARTH_COOLDOWN_SECONDS
        )

    def test_the_refusal_words_are_the_modules(self):
        self.assertEqual(guildrun.HEARTH_COOLDOWN_WORDS, COOLDOWN)
        self.assertIn('refuse("%s")' % guildrun.HEARTH_COOLDOWN_WORDS, MODULE)


class TheBridgePassAsksOnlyThoseNotBackedOff(unittest.TestCase):
    def setUp(self):
        body = BRIDGE[BRIDGE.index("def _hearth_stranded_guild_members") :]
        self.body = body[: body.index("\ndef ")]

    def test_it_reads_each_due_members_newest_hearth_row_for_its_own_source(self):
        sql = BRIDGE[BRIDGE.index("_GUILD_HEARTH_NEWEST = (") :]
        sql = sql[: sql.index("\n\n")]
        self.assertIn("kind = 'hearth'", sql)
        self.assertIn("source = %s", sql)
        self.assertIn("MAX(id)", sql)
        self.assertIn("guildrun.HEARTH_BACKOFF_SECONDS", sql)
        self.assertIn("_GUILD_HEARTH_NEWEST", self.body)
        self.assertIn("guildrun.SOURCE", self.body)

    def test_it_skips_the_backed_off_and_keeps_the_hourly_spacing(self):
        self.assertIn("guildrun.hearth_backed_off(", self.body)
        self.assertIn("_MOVEMENT_HEARTHED", self.body)
        self.assertIn("_insert_hearth(name, guildrun.SOURCE)", self.body)


if __name__ == "__main__":
    unittest.main()
