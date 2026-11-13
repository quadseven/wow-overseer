"""A stranded member is not hearthed while its class quest walk is under way, and
a hearth the world refused as held is not written again inside the class
back-off (#2187).

The guild run loop sends every stranded guild member home by hearthstone. It
never read the class step, so the hearth cast held the character, the class walk
that arrived was refused as held, and the next cycle wrote another hearth while
the class walk waited out its back-off. The decisions are guildrun.class_walk_busy
and guildrun.hearth_backed_off, tested on rows written here; the bridge pass
that applies them is pinned as source. The members are invented.
"""

import pathlib
import unittest

import classquest
import guildjobs
import guildrun

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def walk(name, age):
    return {"name": name, "age": age}


def refused(name, detail, age=60, status="error"):
    return {"name": name, "status": status, "detail": detail, "age": age}


class AMemberWithAClassWalkInFlightIsNotHearthed(unittest.TestCase):
    def test_a_class_walk_asked_inside_the_window_holds_the_hearth(self):
        rows = [walk("Bonk", guildrun.CLASS_WALK_WINDOW_SECONDS - 1)]
        self.assertEqual(guildrun.class_walk_busy(rows), {"Bonk"})

    def test_the_member_is_sent_home_once_the_window_has_passed(self):
        rows = [walk("Bonk", guildrun.CLASS_WALK_WINDOW_SECONDS)]
        self.assertEqual(guildrun.class_walk_busy(rows), set())

    def test_one_members_walk_does_not_hold_another(self):
        rows = [walk("Bonk", 30), walk("Durg", guildrun.CLASS_WALK_WINDOW_SECONDS + 5)]
        self.assertEqual(guildrun.class_walk_busy(rows), {"Bonk"})

    def test_no_row_means_the_member_is_stranded_and_due(self):
        self.assertEqual(guildrun.class_walk_busy([]), set())
        self.assertEqual(guildrun.class_walk_busy(None), set())


class ARefusedAsHeldHearthWaitsTheClassBackOff(unittest.TestCase):
    def test_a_hearth_refused_as_held_is_not_written_again_inside_the_window(self):
        rows = [
            refused(
                "Bonk",
                classquest.HELD_REASON,
                age=guildrun.CLASS_WALK_WINDOW_SECONDS - 1,
            )
        ]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})

    def test_an_unchanged_hearth_waits_too(self):
        rows = [refused("Bonk", "", age=30, status="unchanged")]
        self.assertEqual(guildrun.hearth_backed_off(rows), {"Bonk"})

    def test_it_is_written_again_after_the_window(self):
        rows = [
            refused(
                "Bonk", classquest.HELD_REASON, age=guildrun.CLASS_WALK_WINDOW_SECONDS
            )
        ]
        self.assertEqual(guildrun.hearth_backed_off(rows), set())

    def test_other_refusals_keep_today(self):
        rows = [refused("Bonk", "character is moving", age=5)]
        self.assertEqual(guildrun.hearth_backed_off(rows), set())


class TheWindowIsTheClassBackOff(unittest.TestCase):
    def test_it_equals_the_held_back_off(self):
        self.assertEqual(
            guildrun.CLASS_WALK_WINDOW_SECONDS, classquest.HELD_BACKOFF_MINUTES * 60
        )

    def test_the_held_words_are_the_classquests(self):
        self.assertEqual(guildrun.HEARTH_HELD_WORDS, classquest.HELD_REASON)

    def test_the_sources_are_the_class_walks(self):
        for action in (classquest.ACTION, classquest.CROSS_ACTION):
            src = guildjobs.source_for(action, "Bonk")
            self.assertTrue(
                any(src.startswith(p) for p in guildrun.CLASS_WALK_SOURCE_PREFIXES), src
            )


class TheBridgePassSkipsThoseWithAWalk(unittest.TestCase):
    def setUp(self):
        body = BRIDGE[BRIDGE.index("def _hearth_stranded_guild_members") :]
        self.body = body[: body.index("\ndef ")]

    def test_it_reads_class_walk_rows_and_skips_those_members(self):
        self.assertIn("_GUILD_CLASS_WALKS", self.body)
        self.assertIn("guildrun.class_walk_busy(", self.body)
        sql = BRIDGE[BRIDGE.index("_GUILD_CLASS_WALKS = (") :]
        sql = sql[: sql.index("\n\n")]
        self.assertIn("source LIKE", sql)
        self.assertIn("guildrun.CLASS_WALK_WINDOW_SECONDS", sql)


if __name__ == "__main__":
    unittest.main()
