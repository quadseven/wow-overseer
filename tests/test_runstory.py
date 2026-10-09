"""Why a run wiped, failed or cleared, in plain words (runstory).

The Guild tab's card for a wiped run said only "everybody inside is dead" and
its counts. These fixtures rebuild two runs from the rows that would hold them:
a Wailing Caverns wipe at the bottom of the dungeon's range with one level 17
healer, two members lost on the way in, a boss that dropped both rogues and a
last fight that took the other three; and a clean Ragefire Chasm clear the
finder called finished after 2 of 4 bosses.
"""

import pathlib
import re
import sys
import unittest
from datetime import datetime, timedelta

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import runstory  # noqa: E402
import runtimeline  # noqa: E402

PAGE = (HERE / "classic.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

ANACONDRA = 3671
ZONES = {17: "The Barrens", 718: "Wailing Caverns"}
FORMED = datetime(2026, 10, 5, 11, 0, 0)


def death(name, level, map_id, zone, killer, entry, at, kind="creature"):
    return {
        "character_name": name,
        "level": level,
        "map": map_id,
        "zone": zone,
        "killer_name": killer,
        "killer_type": kind,
        "killer_entry": entry,
        "created_at": at,
    }


def wipe_222() -> dict:
    return {
        "id": 222,
        "guild": "Bonkers",
        "keyword": "wailing",
        "state": "ended",
        "outcome": "wiped",
        "why": "everybody inside is dead",
        "members": "Grumkar:tank:warrior:19,Mendi:healer:druid:17,"
        "Bazmoth:dps:mage:18,Atkermi:dps:rogue:18,Shivv:dps:rogue:19",
        "deaths": 5,
        "seconds_inside": 37 * 60,
        "bosses_done": 1,
        "bosses_total": 7,
        "created_at": FORMED,
        "ended_at": FORMED + timedelta(minutes=45),
    }


def at(minutes, seconds=0):
    return FORMED + timedelta(minutes=minutes, seconds=seconds)


DEATHS_222 = [
    # On the way in, in The Barrens, before the finder took the group in.
    death("Bazmoth", 18, 1, 17, "Savannah Prowler", 3425, at(2, 10)),
    death("Atkermi", 18, 1, 17, "Kolkar Pack Runner", 3274, at(3, 40)),
    # Inside: the boss drops both rogues, then the last three go together.
    death("Atkermi", 18, 43, 718, "Lady Anacondra", ANACONDRA, at(25, 0)),
    death("Shivv", 19, 43, 718, "Lady Anacondra", ANACONDRA, at(25, 3)),
    death("Mendi", 17, 43, 718, "Druid of the Fang", 3840, at(44, 0)),
    death("Bazmoth", 18, 43, 718, "Deviate Viper", 5755, at(44, 4)),
    death("Grumkar", 19, 43, 718, "Deviate Viper", 5755, at(44, 9)),
    # Hours earlier, questing: not this run.
    death("Bazmoth", 18, 1, 17, "Plainstrider", 44, FORMED - timedelta(hours=2)),
    # Somebody else's death in the window: not this group.
    death("Stranger", 18, 43, 718, "Deviate Viper", 5755, at(30)),
]


def clear_220() -> dict:
    return {
        "id": 220,
        "guild": "Cave",
        "keyword": "ragefire",
        "state": "ended",
        "outcome": "cleared",
        "why": "the finder says the dungeon is finished",
        "members": "Og:tank:warrior:16,Ugga:healer:priest:15,Bork:dps:mage:17,"
        "Grog:dps:hunter:16,Grug:dps:rogue:17",
        "deaths": 0,
        "seconds_inside": 25 * 60,
        "bosses_done": 2,
        "bosses_total": 4,
        "created_at": "2026-10-05 10:00:00",
        "ended_at": "2026-10-05 10:30:00",
    }


EM_DASH = chr(0x2014)


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=\.)\s+", text.strip()) if s])


class TheWailingCavernsWipe(unittest.TestCase):
    """Run 222: Bonkers, levels 17 to 19, one level 17 healer."""

    def setUp(self):
        self.told = runstory.guild_story(wipe_222(), DEATHS_222, {ANACONDRA}, ZONES)

    def test_the_story_reads_like_a_guild_chat_recap(self):
        self.assertEqual(
            self.told["story"],
            "Went into Wailing Caverns at levels 17 to 19, the bottom of its 17 to "
            "24 range, with one level 17 healer. Lost Bazmoth and Atkermi on the "
            "way in, to a Savannah Prowler and a Kolkar Pack Runner in The Barrens. "
            "Got 1 of 7 bosses down, and Lady Anacondra dropped both rogues within "
            "3 seconds. The last three went down together to a Druid of the Fang "
            "and Deviate Vipers.",
        )

    def test_the_cause_marks_the_judgments_as_likely(self):
        self.assertEqual(
            self.told["cause"],
            "Likely cause: under-leveled for the elites, a lone level 17 healer "
            "and burst from Lady Anacondra.",
        )

    def test_the_tags_count_every_cause(self):
        self.assertEqual(
            self.told["causes"],
            [
                "under_levelled",
                "single_healer",
                "boss_burst",
                "pack_wipe",
                "died_on_the_way",
            ],
        )
        for tag in self.told["causes"]:
            self.assertIn(tag, runstory.TAGS)

    def test_it_is_short_plain_ascii(self):
        for text in (self.told["story"], self.told["cause"]):
            self.assertTrue(text.isascii(), text)
            self.assertNotIn(EM_DASH, text)
            self.assertNotIn("_", text)
        self.assertLessEqual(sentences(self.told["story"]), 4)
        self.assertGreaterEqual(sentences(self.told["story"]), 2)

    def test_deaths_outside_the_run_or_the_group_are_not_told(self):
        self.assertNotIn("Plainstrider", self.told["story"])
        self.assertNotIn("Stranger", self.told["story"])

    def test_without_death_records_it_says_so_rather_than_guessing(self):
        told = runstory.guild_story(wipe_222(), [], {ANACONDRA}, ZONES)
        self.assertIn("no death record says to what", told["story"])
        self.assertNotIn("Anacondra", told["story"])
        # The levels and the seats are still rows, so those causes stand.
        self.assertEqual(told["causes"], ["under_levelled", "single_healer"])

    def test_a_wipe_nothing_explains_says_it_is_not_clear(self):
        run = wipe_222()
        run["members"] = (
            "Grumkar:tank:warrior:21,Mendi:healer:druid:21,"
            "Bazmoth:dps:mage:21,Atkermi:dps:rogue:21,Shivv:dps:rogue:21"
        )
        told = runstory.guild_story(run, [], {ANACONDRA}, ZONES)
        self.assertEqual(told["causes"], ["unexplained"])
        self.assertEqual(told["cause"], "Cause: not clear from the death records.")

    def test_a_boss_is_only_a_boss_when_its_entry_says_so(self):
        told = runstory.guild_story(wipe_222(), DEATHS_222, frozenset(), ZONES)
        self.assertNotIn("boss_burst", told["causes"])


class TheRagefireClear(unittest.TestCase):
    """Run 220: Ragefire, nobody died, 2 of 4 bosses, the finder called it."""

    def setUp(self):
        self.told = runstory.guild_story(clear_220(), [], frozenset(), {})

    def test_the_story(self):
        self.assertEqual(
            self.told["story"],
            "Cleared Ragefire Chasm in 25 minutes at levels 15 to 17 with nobody "
            "dying. The finder called it finished after 2 of 4 bosses.",
        )

    def test_the_cause_is_the_finders_word_and_no_failure_tag(self):
        self.assertEqual(
            self.told["cause"], "Cleared: the finder says the dungeon is finished."
        )
        self.assertEqual(self.told["causes"], [])


class TheRunsThatNeverWentIn(unittest.TestCase):
    def run_of(self, outcome, why):
        run = clear_220()
        run.update(outcome=outcome, why=why, seconds_inside=0, bosses_done=0)
        return runstory.guild_story(run, [], frozenset(), {})

    def test_a_refusal_over_combat_names_the_member(self):
        told = self.run_of("refused", "'Grog' is in combat")
        self.assertEqual(told["causes"], ["refused_in_combat"])
        self.assertIn("Grog is in combat", told["story"])
        self.assertTrue(told["cause"].startswith("Cause: "))

    def test_a_lost_run_is_a_likely_restart(self):
        told = self.run_of("lost", "no outcome from the worldserver within 180 minutes")
        self.assertEqual(told["causes"], ["restart_lost"])
        self.assertTrue(told["cause"].startswith("Likely cause: "))

    def test_not_entered_says_why_in_minutes(self):
        told = self.run_of("not entered", "nothing took the group in within 900s")
        self.assertEqual(told["causes"], ["never_entered"])
        self.assertIn("within 15 minutes", told["story"])

    def test_a_run_still_out_has_no_story(self):
        run = clear_220()
        run["state"] = "inside"
        self.assertEqual(runstory.guild_story(run, [], frozenset(), {})["story"], "")


class TheReadWindows(unittest.TestCase):
    def test_overlapping_runs_share_one_window_and_names_are_the_members(self):
        a, b = wipe_222(), wipe_222()
        b["created_at"] = FORMED + timedelta(minutes=30)
        b["ended_at"] = FORMED + timedelta(minutes=80)
        names, spans = runstory.death_scope([a, b, clear_220()])
        self.assertIn("Atkermi", names)
        self.assertIn("Ugga", names)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[1][0], FORMED - timedelta(seconds=runstory.LEAD_SECONDS))


class AFamilyRun(unittest.TestCase):
    """A family's Wailing Caverns run from the timeline's rows and its deaths."""

    ROWS = [
        {
            "id": 1,
            "family": "Grug",
            "kind": "phase",
            "phase": "GATHERING",
            "detail": "IDLE -> GATHERING (wailing, run 3 of campaign 9)",
            "campaign_id": 9,
            "run_number": 3,
            "portal": "wailing",
            "age_seconds": 3000,
        },
        {
            "id": 2,
            "family": "Grug",
            "kind": "phase",
            "phase": "STAGED_INSIDE",
            "detail": "ENTER -> STAGED_INSIDE",
            "campaign_id": 9,
            "run_number": 3,
            "age_seconds": 2400,
        },
        {
            "id": 3,
            "family": "Grug",
            "kind": "boss",
            "phase": "CLEARING",
            "detail": "1 encounter credited, 1 in all (mask 0 -> 1)",
            "campaign_id": 9,
            "run_number": 3,
            "age_seconds": 1800,
        },
        {
            "id": 4,
            "family": "Grug",
            "kind": "ended",
            "phase": "CLEARING",
            "detail": "wipe: everybody is dead",
            "campaign_id": 9,
            "run_number": 3,
            "age_seconds": 600,
        },
    ]
    DEATHS = [
        {
            "character_name": n,
            "level": 18,
            "map": 43,
            "zone": 718,
            "killer_name": "Lady Anacondra",
            "killer_type": "creature",
            "killer_entry": ANACONDRA,
            "age_seconds": age,
        }
        for n, age in (("Grug", 640), ("Bork", 637), ("Og", 635))
    ]

    def test_the_timeline_card_carries_the_story(self):
        out = runtimeline.build_run_timeline(
            self.ROWS,
            {"Grug": ["Grug", "Bork", "Og"]},
            deaths=self.DEATHS,
            bosses=frozenset({ANACONDRA}),
            zones=ZONES,
            runs_per_family=4,
        )
        card = out["families"][0]["runs"][0]
        self.assertEqual(
            card["story"],
            "Went into Wailing Caverns and got one boss down. Lady Anacondra "
            "dropped Grug, Bork and Og within 5 seconds.",
        )
        self.assertEqual(card["causes"], ["boss_burst"])
        self.assertEqual(card["cause"], "Likely cause: burst from Lady Anacondra.")

    def test_a_run_with_no_end_and_a_newer_run_was_lost(self):
        rows = [dict(r) for r in self.ROWS[:3]] + [
            dict(self.ROWS[0], id=9, age_seconds=100, run_number=4)
        ]
        out = runtimeline.build_run_timeline(
            rows, {"Grug": ["Grug"]}, runs_per_family=4
        )
        older = out["families"][0]["runs"][1]
        self.assertEqual(older["causes"], ["restart_lost"])
        newest = out["families"][0]["runs"][0]
        self.assertEqual(newest["story"], "")


class TheSiteDrawsIt(unittest.TestCase):
    def test_the_guild_card_the_timeline_and_the_chat_print_it(self):
        for start, end in (
            ("function gdCard", "function gdList"),
            ("function rtlRender", "async function pollRunTimeline"),
            ("function gcOutcome", "function gcMessage"),
        ):
            block = PAGE[PAGE.index(start) : PAGE.index(end)]
            self.assertIn("run.story", block, start)
            self.assertIn("run.cause", block, start)

    def test_the_endpoints_tell_the_stories(self):
        handler = SERVER[
            SERVER.index("def _guild_runs") : SERVER.index("def _guild_chat")
        ]
        self.assertIn('_guild_run_stories(cur, payload["recent"])', handler)
        chat = SERVER[SERVER.index("def _fetch_guild_chat") :]
        self.assertIn("_guild_run_stories(cur,", chat[: chat.index("\n\n\n")])
        timeline = SERVER[
            SERVER.index("def _run_timeline") : SERVER.index("def _recap")
        ]
        self.assertIn('deaths=fetched["deaths"]', timeline)

    def test_the_module_is_copied_into_the_container(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("runstory.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
