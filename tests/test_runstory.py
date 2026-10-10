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
import types
import unittest
from unittest import mock
from datetime import datetime, timedelta

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import runstory  # noqa: E402
import runtimeline  # noqa: E402

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
            "24 range. Lost Bazmoth and Atkermi on the "
            "way in, to a Savannah Prowler and a Kolkar Pack Runner in The Barrens. "
            "Got 1 of 7 bosses down, and Lady Anacondra dropped both rogues within "
            "3 seconds. The last three went down together to a Druid of the Fang "
            "and Deviate Vipers.",
        )

    def test_the_cause_marks_the_judgments_as_likely(self):
        self.assertEqual(
            self.told["cause"],
            "Likely cause: under-leveled for the elites, a Druid of the Fang "
            "killed the healer first and burst from Lady Anacondra.",
        )

    def test_the_tags_count_every_cause(self):
        self.assertEqual(
            self.told["causes"],
            [
                "under_levelled",
                "healer_died_first",
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
        # The levels are still rows, so that cause stands; one healer is no cause.
        self.assertEqual(told["causes"], ["under_levelled"])

    def test_a_wipe_nothing_explains_says_the_cause_was_not_measured(self):
        run = wipe_222()
        run["members"] = (
            "Grumkar:tank:warrior:21,Mendi:healer:druid:21,"
            "Bazmoth:dps:mage:21,Atkermi:dps:rogue:21,Shivv:dps:rogue:21"
        )
        told = runstory.guild_story(run, [], {ANACONDRA}, ZONES)
        self.assertEqual(told["causes"], ["unexplained"])
        self.assertEqual(told["cause"], "Cause not measured.")

    def test_a_boss_is_only_a_boss_when_its_entry_says_so(self):
        told = runstory.guild_story(wipe_222(), DEATHS_222, frozenset(), ZONES)
        self.assertNotIn("boss_burst", told["causes"])


# --- The Deadmines runs of 2026-10-10 (#721 put their healers at the bosses'
# level 20). Their cards said "Likely cause: a lone level 20 healer.", which
# names no fault: one healer is the classic five-man group. The fixtures are
# the members and overseer_death rows of runs 482, 465, 493, 472 and 473.

DEADMINES = 36
DM_BOSSES = {36: 20}
SHREDDER = ("Sneed's Shredder", 642)
WOODCARVER = ("Goblin Woodcarver", 641)
CRAFTSMAN = ("Goblin Craftsman", 1731)


def dm_run(rid, outcome, members, created, ended, inside, deaths, done):
    return {
        "id": rid,
        "guild": "Bonkers",
        "keyword": "deadmines",
        "state": "ended",
        "outcome": outcome,
        "why": (
            "inside for 7200s"
            if outcome == "timed out"
            else "everybody inside is dead, and nobody was back alive inside 901s "
            "after the wipe"
        ),
        "members": members,
        "deaths": deaths,
        "seconds_inside": inside,
        "bosses_done": done,
        "bosses_total": 7,
        "created_at": created,
        "ended_at": ended,
    }


def dm_death(name, level, killer, when, map_id=DEADMINES, zone=1581):
    return death(name, level, map_id, zone, killer[0], killer[1], when)


RUN_482 = dm_run(
    482,
    "wiped",
    "Durg:tank:warrior:23,Dunga:healer:priest:20,Brakk:dps:shaman:25,"
    "Eggrok:dps:mage:24,Rubba:dps:mage:23",
    "2026-10-10 10:05:53",
    "2026-10-10 10:46:18",
    2364,
    11,
    1,
)
DEATHS_482 = [
    dm_death("Durg", 23, ("Defias Overseer", 634), "2026-10-10 10:14:14"),
    dm_death("Durg", 23, SHREDDER, "2026-10-10 10:29:30"),
    dm_death("Dunga", 20, SHREDDER, "2026-10-10 10:29:45"),
    dm_death("Brakk", 25, WOODCARVER, "2026-10-10 10:30:03"),
    dm_death("Rubba", 23, SHREDDER, "2026-10-10 10:30:09"),
    dm_death("Eggrok", 24, SHREDDER, "2026-10-10 10:30:18"),
    dm_death("Durg", 23, SHREDDER, "2026-10-10 10:33:55"),
    dm_death("Durg", 23, SHREDDER, "2026-10-10 10:36:34"),
    dm_death("Durg", 23, WOODCARVER, "2026-10-10 10:39:26"),
    dm_death("Durg", 23, SHREDDER, "2026-10-10 10:42:06"),
    dm_death("Durg", 23, SHREDDER, "2026-10-10 10:44:54"),
]

RUN_465 = dm_run(
    465,
    "wiped",
    "Crag:tank:warrior:23,Jyngruntua:healer:paladin:20,Rubba:dps:mage:23,"
    "Stakk:dps:mage:22,Totta:dps:mage:23",
    "2026-10-10 04:32:49",
    "2026-10-10 05:02:57",
    1795,
    10,
    1,
)
DEATHS_465 = [
    dm_death("Crag", 23, WOODCARVER, "2026-10-10 04:47:16"),
    dm_death("Totta", 23, WOODCARVER, "2026-10-10 04:47:25"),
    dm_death("Stakk", 22, WOODCARVER, "2026-10-10 04:47:37"),
    dm_death("Rubba", 23, WOODCARVER, "2026-10-10 04:47:46"),
] + [
    dm_death("Crag", 23, WOODCARVER, "2026-10-10 %s" % t)
    for t in ("04:51:38", "04:54:18", "04:57:00", "04:59:40", "05:02:20")
]

RUN_493 = dm_run(
    493,
    "wiped",
    "Crag:tank:warrior:24,Dunga:healer:priest:20,Cronk:dps:shaman:24,"
    "Bonk:dps:paladin:25,Drogg:dps:paladin:25",
    "2026-10-10 13:06:02",
    "2026-10-10 13:49:38",
    2599,
    10,
    2,
)
DEATHS_493 = [
    dm_death("Crag", 24, SHREDDER, "2026-10-10 13:20:52"),
    dm_death("Crag", 24, CRAFTSMAN, "2026-10-10 13:33:40"),
    dm_death("Dunga", 20, CRAFTSMAN, "2026-10-10 13:33:40"),
    dm_death("Cronk", 24, CRAFTSMAN, "2026-10-10 13:34:13"),
    dm_death("Bonk", 25, ("Gilnid", 1763), "2026-10-10 13:34:16"),
    dm_death("Drogg", 25, CRAFTSMAN, "2026-10-10 13:34:22"),
    dm_death("Crag", 24, CRAFTSMAN, "2026-10-10 13:37:47"),
    dm_death("Crag", 24, CRAFTSMAN, "2026-10-10 13:41:33"),
    dm_death("Crag", 24, CRAFTSMAN, "2026-10-10 13:45:19"),
    dm_death("Crag", 24, ("Goblin Engineer", 622), "2026-10-10 13:49:08"),
]

RUN_472 = dm_run(
    472,
    "timed out",
    "Crag:tank:warrior:23,Dunga:healer:priest:20,Stakk:dps:mage:22,"
    "Bluk:dps:shaman:25,Brakk:dps:shaman:25",
    "2026-10-10 06:36:48",
    "2026-10-10 08:37:47",
    7202,
    0,
    3,
)
# Dunga died in Loch Modan, ungrouped, three and a half minutes before the run
# was formed: no part of the run, and not on any way into the Deadmines.
DEATHS_472 = [
    dm_death(
        "Dunga",
        20,
        ("Stonesplinter Digger", 1197),
        "2026-10-10 06:33:12",
        map_id=0,
        zone=38,
    )
]

RUN_473 = dm_run(
    473,
    "timed out",
    "Durg:tank:warrior:22,Ortimo:healer:paladin:20,Oot:dps:warlock:18,"
    "Rubba:dps:mage:23,Tugga:dps:shaman:26",
    "2026-10-10 07:02:42",
    "2026-10-10 09:03:09",
    7203,
    0,
    3,
)


def dm_story(run, deaths, boss_levels=DM_BOSSES):
    return runstory.guild_story(
        run, deaths, frozenset(), {38: "Loch Modan"}, boss_levels
    )


class TheDeadminesCausesNameRealFaults(unittest.TestCase):
    """One healer is the normal group: no card may blame it."""

    RUNS = (
        (RUN_482, DEATHS_482),
        (RUN_465, DEATHS_465),
        (RUN_493, DEATHS_493),
        (RUN_472, DEATHS_472),
        (RUN_473, []),
    )

    def test_no_card_blames_a_lone_healer(self):
        for run, deaths in self.RUNS:
            told = dm_story(run, deaths)
            for text in (told["story"], told["cause"]):
                self.assertNotRegex(text, r"\blone\b", run["id"])
                self.assertNotIn("one level 20 healer", text, run["id"])
            self.assertNotIn("single_healer", told["causes"], run["id"])
            self.assertNotIn("single_healer", runstory.TAGS)

    def test_482_the_tank_died_first_and_then_alone_five_more_times(self):
        told = dm_story(RUN_482, DEATHS_482)
        self.assertEqual(
            told["cause"],
            "Cause: the tank died alone 5 more times after the wipe; likely a "
            "Sneed's Shredder killed the tank first and a pull too big for the group.",
        )
        self.assertEqual(
            told["causes"], ["died_alone_after", "tank_died_first", "pack_wipe"]
        )
        # The last fight told is the wipe, not the tank's fifth death alone.
        self.assertIn("The last three went down together", told["story"])
        self.assertIn(
            "After the wipe only Durg died again, 5 more times", told["story"]
        )

    def test_465_the_healer_outlived_the_wipe(self):
        told = dm_story(RUN_465, DEATHS_465)
        self.assertTrue(
            told["cause"].startswith(
                "Cause: the tank died alone 5 more times after the wipe; likely a "
                "Goblin Woodcarver killed the tank first while the healer lived"
            ),
            told["cause"],
        )

    def test_493_the_tank_and_the_healer_went_first_together(self):
        told = dm_story(RUN_493, DEATHS_493)
        self.assertIn(
            "Goblin Craftsmen killed the tank and the healer first", told["cause"]
        )
        self.assertIn("the tank died alone 4 more times", told["cause"])
        self.assertNotIn("Goblin Engineer", told["story"].split("After the wipe")[0])

    def test_472_ran_out_of_time_and_a_death_before_it_formed_is_not_its(self):
        told = dm_story(RUN_472, DEATHS_472)
        self.assertEqual(
            told["cause"], "Cause: the run ran out of time after 3 of 7 bosses."
        )
        self.assertEqual(told["causes"], ["timed_out"])
        self.assertNotIn("Loch Modan", told["story"])

    def test_473_names_the_seat_below_the_bosses_level(self):
        told = dm_story(RUN_473, [])
        self.assertEqual(
            told["cause"],
            "Cause: the run ran out of time after 3 of 7 bosses; likely one seat "
            "below the bosses' level 20.",
        )
        self.assertIn("with Oot below the bosses' level 20", told["story"])

    def test_many_low_seats_are_counted_not_listed(self):
        run = dict(RUN_473)
        run["members"] = (
            "Durg:tank:warrior:19,Ortimo:healer:paladin:19,Oot:dps:warlock:18,"
            "Rubba:dps:mage:23,Tugga:dps:shaman:26"
        )
        told = dm_story(run, [])
        self.assertIn("with three seats below the bosses' level 20", told["story"])
        self.assertNotIn("Oot", told["story"])
        self.assertIn("likely three seats below the bosses' level 20", told["cause"])

    def test_without_the_bosses_level_no_seat_is_called_low(self):
        told = dm_story(RUN_473, [], boss_levels=None)
        self.assertEqual(told["causes"], ["timed_out"])

    def test_a_wipe_with_no_death_rows_says_cause_not_measured(self):
        told = dm_story(RUN_482, [])
        self.assertEqual(told["cause"], "Cause not measured.")

    def test_the_site_reads_the_bosses_level_for_the_stories(self):
        stories = SERVER[
            SERVER.index("def _guild_run_stories") : SERVER.index(
                "# THE GUILD CHAT FEED"
            )
        ]
        self.assertIn("guildrun.BOSS_LEVELS_SQL", SERVER)
        self.assertIn("_run_boss_levels(cur)", stories)


class TheSiteReadsTheBossesLevelOnce(unittest.TestCase):
    def setUp(self):
        sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
        import map_server

        self.ms = map_server
        self.ms._RUN_BOSS_LEVELS.clear()
        self.addCleanup(self.ms._RUN_BOSS_LEVELS.clear)
        self.reads = []

    def guard(self, rows):
        def wide(cur, sql, params=(), fallback="", what=""):
            self.reads.append(sql)
            return rows

        return mock.patch.object(self.ms, "_wide_guarded", wide)

    def test_it_reads_the_levels_once_and_logs_them(self):
        with self.guard([{"map_id": 36, "level": 20}, {"map_id": 43, "level": 20}]):
            with self.assertLogs("wow-map", "INFO") as logs:
                self.assertEqual(self.ms._run_boss_levels(None), {36: 20, 43: 20})
            self.assertEqual(self.ms._run_boss_levels(None), {36: 20, 43: 20})
        self.assertEqual(len(self.reads), 1)
        self.assertIn("the Deadmines' 20", logs.output[0])

    def test_an_empty_read_is_tried_again(self):
        with self.guard([]):
            self.assertEqual(self.ms._run_boss_levels(None), {})
            self.assertEqual(self.ms._run_boss_levels(None), {})
        self.assertEqual(len(self.reads), 2)


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
        # A death before the run was formed is not part of it.
        self.assertEqual(spans[1][0], FORMED)


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
