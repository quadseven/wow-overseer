"""A member dying five times an hour in one zone is stuck and leaves the zone (#1464).

Measured on the dev realm on 2026-10-25: Cave's lowest member, a level 21
priest, died 167 times in a day in Redridge Mountains and the Wetlands, mostly
to Great Goretusks under its level, and stayed level 21. /api/v2/stuck listed
two other members and not it, so no health finding or rescue started, and no
step walked it out of the zone. These tests hold the two halves of the fix:
the stuck reader lists a death loop (kind death-loop), and the guild jobs pass
sends the member to town and plans no quest in that zone while it lasts.
"""

import pathlib
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import deathloop  # noqa: E402
import guildjobs  # noqa: E402
import guildlevel  # noqa: E402
import guildroute  # noqa: E402
import levelroute  # noqa: E402
from apiv2 import health, members  # noqa: E402

NOW = 1_800_000_000
MINUTE = 60
REDRIDGE, WETLANDS, ELWYNN, WESTFALL, LOCH_MODAN = 44, 11, 12, 40, 38
EASTERN_KINGDOMS, HUMAN, PRIEST = 0, 1, 5


def death(age_minutes, zone=REDRIDGE, level=21, killer="Great Goretusk", name="Clunk"):
    return {
        "name": name,
        "zone": zone,
        "map": EASTERN_KINGDOMS,
        "level": level,
        "killer": killer,
        "age": int(age_minutes * MINUTE),
    }


def deaths(n, every=10, start=2, **kw):
    """`n` deaths, the newest `start` minutes ago, `every` minutes apart."""
    return [death(start + i * every, **kw) for i in range(n)]


# ---- what a death loop is -------------------------------------------------------


class WhatALoopIs(unittest.TestCase):
    def test_five_deaths_in_one_zone_within_an_hour_at_one_level_is_a_loop(self):
        rows = deaths(4) + [death(44, killer="Redridge Mongrel")]
        found = deathloop.loops(rows, {"Clunk": 21})
        loop = found["Clunk"]
        self.assertEqual((loop.zone, loop.deaths, loop.level), (REDRIDGE, 5, 21))
        self.assertEqual(loop.killer, "Great Goretusk")
        self.assertEqual(loop.place, "Redridge Mountains")
        self.assertEqual(
            loop.blocker(),
            "Died 5 times in Redridge Mountains within an hour, mostly to Great "
            "Goretusk, with no level gained.",
        )

    def test_four_deaths_is_not(self):
        self.assertEqual(deathloop.loops(deaths(4), {"Clunk": 21}), {})

    def test_five_deaths_spread_over_more_than_an_hour_is_not(self):
        self.assertEqual(deathloop.loops(deaths(5, every=16), {"Clunk": 21}), {})

    def test_five_deaths_split_across_two_zones_is_not(self):
        rows = deaths(3) + deaths(2, start=5, zone=WETLANDS)
        self.assertEqual(deathloop.loops(rows, {"Clunk": 21}), {})

    def test_a_level_gained_since_is_not(self):
        self.assertEqual(deathloop.loops(deaths(5), {"Clunk": 22}), {})

    def test_a_level_gained_inside_the_hour_is_not(self):
        rows = deaths(3, level=22) + deaths(2, start=35, level=21)
        self.assertEqual(deathloop.loops(rows, {"Clunk": 22}), {})

    def test_two_hours_without_dying_clears_it(self):
        old = deaths(6, start=deathloop.QUIET_SECONDS // MINUTE + 1)
        self.assertEqual(deathloop.loops(old, {"Clunk": 21}), {})
        recent = deaths(6, start=deathloop.QUIET_SECONDS // MINUTE - 5)
        self.assertIn("Clunk", deathloop.loops(recent, {"Clunk": 21}))

    def test_the_newest_loop_zone_is_named(self):
        rows = deaths(5, start=70, zone=WETLANDS) + deaths(5, start=2)
        self.assertEqual(deathloop.loops(rows, {"Clunk": 21})["Clunk"].zone, REDRIDGE)

    def test_the_window_start_is_the_current_loops_first_death(self):
        # Older deaths in the zone, more than an hour before the newest, and a
        # newer death elsewhere: the loop starts at its own window's first death.
        rows = deaths(5, every=8) + deaths(2, start=100) + [death(1, zone=WETLANDS)]
        loop = deathloop.loops(rows, {"Clunk": 21})["Clunk"]
        self.assertEqual((loop.first_age, loop.last_age), (34 * MINUTE, 2 * MINUTE))

    def test_the_read_covers_a_window_that_ended_two_hours_ago(self):
        self.assertEqual(
            deathloop.READ_SECONDS, deathloop.WINDOW_SECONDS + deathloop.QUIET_SECONDS
        )
        self.assertIn("FROM overseer_death", deathloop.SQL)
        self.assertIn("TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age", deathloop.SQL)


# ---- the quiet clock is the loop zone's own (#1569) ------------------------------


FERALAS, DUSKWOOD, STRANGLETHORN = 357, 10, 33


def feralas_loop(shift=0):
    """A Feralas loop from 178 to 161 minutes ago (a 17-minute loop read
    about three hours after it began), then one death in each of three other
    zones. `shift` minutes come off every age: the same deaths read earlier."""
    loop = [
        death(age - shift, zone=FERALAS, level=44) for age in (161, 165, 170, 174, 178)
    ]
    elsewhere = [
        death(140 - shift, zone=DUSKWOOD, level=44, killer="Nightbane Worgen"),
        death(90 - shift, zone=STRANGLETHORN, level=44, killer="Bloodscalp Hunter"),
        death(30 - shift, zone=WETLANDS, level=44, killer="Mottled Raptor"),
    ]
    return loop + elsewhere


class TheQuietClockIsTheZones(unittest.TestCase):
    def test_a_loop_left_behind_clears_after_the_quiet_time_despite_deaths_elsewhere(
        self,
    ):
        self.assertEqual(deathloop.loops(feralas_loop(), {"Clunk": 44}), {})

    def test_before_the_quiet_time_it_is_still_listed(self):
        found = deathloop.loops(feralas_loop(shift=60), {"Clunk": 44})
        self.assertEqual(found["Clunk"].zone, FERALAS)

    def test_a_member_still_dying_in_the_loop_zone_stays_listed(self):
        rows = feralas_loop() + [death(20, zone=FERALAS, level=44)]
        loop = deathloop.loops(rows, {"Clunk": 44})["Clunk"]
        self.assertEqual((loop.zone, loop.deaths), (FERALAS, 5))
        self.assertEqual(loop.first_age, 178 * MINUTE)

    def test_the_stuck_entry_since_is_the_loop_windows_start(self):
        loop = deathloop.loops(feralas_loop(shift=60), {"Clunk": 44})["Clunk"]
        entry = members.loop_blocker(loop, NOW)
        self.assertEqual(entry["since"], NOW - (178 - 60) * MINUTE)
        self.assertEqual(entry["step"], "Dying in Feralas")


# ---- the stuck reader lists it ---------------------------------------------------


GUILD = [
    {"name": "Grug", "guild_name": "Cave", "level": 30, "class_id": 1, "race": 2},
    {"name": "Clunk", "guild_name": "Cave", "level": 21, "class_id": 5, "race": 1},
]


def roster(rows, life="alive", level=21):
    guild = [dict(GUILD[0]), dict(GUILD[1], level=level)]
    readings = {
        "Grug": {"online": True, "life": "alive", "fresh_at": NOW},
        "Clunk": {"online": True, "life": life, "fresh_at": NOW},
    }
    return members.build(
        {"Grug": ["Grug"]},
        guild,
        [],
        [],
        [],
        {},
        NOW,
        readings=readings,
        deaths=rows,
    )


class TheStuckReaderListsIt(unittest.TestCase):
    def test_a_member_in_a_death_loop_is_listed_with_its_zone_count_and_killer(self):
        view = members.stuck_view(roster(deaths(7, every=8)))
        rows = {r["name"]: r for r in view["members"]}
        self.assertIn("Clunk", rows)
        clunk = rows["Clunk"]
        self.assertEqual(clunk["kind"], "death-loop")
        self.assertIn("Died 7 times in Redridge Mountains", clunk["blocker"])
        self.assertIn("mostly to Great Goretusk", clunk["blocker"])
        self.assertIn("no level gained", clunk["blocker"])
        # First seen at the window's first death, 2 + 6 * 8 minutes ago.
        self.assertEqual(clunk["since"], NOW - (2 + 6 * 8) * MINUTE)

    def test_a_ghost_in_the_loop_is_listed_too(self):
        view = members.stuck_view(roster(deaths(5), life="ghost"))
        self.assertEqual([r["kind"] for r in view["members"]], ["death-loop"])

    def test_four_deaths_or_a_level_gained_is_not_listed(self):
        for rows, level in ((deaths(4), 21), (deaths(5), 22)):
            view = members.stuck_view(roster(rows, level=level))
            self.assertNotIn("Clunk", [r["name"] for r in view["members"]])

    def test_no_death_rows_lists_nobody(self):
        self.assertEqual(members.stuck_view(roster([]))["members"], [])
        self.assertEqual(members.stuck_view(roster(None))["members"], [])

    def test_the_read_and_the_basis_name_it(self):
        source = (HERE / "apiv2" / "members.py").read_text(encoding="utf-8")
        self.assertIn("deathloop.SQL.format(holes=h)", source)
        self.assertIn("five or more deaths", members.BASIS)

    def test_a_health_finding_files_it_under_deaths(self):
        self.assertEqual(health.STUCK_AREAS["death-loop"], "deaths")


# ---- the guild jobs pass sends it to town and out of the zone --------------------


def quests_in(zone, low, high, start):
    return [
        {
            "quest": start + i,
            "zone": zone,
            "level": level,
            "min_level": max(level - 4, 1),
            "races": 0,
            "classes": 0,
        }
        for i, level in enumerate(range(low, high + 1))
    ]


QUESTS = tuple(
    quests_in(WESTFALL, 10, 20, 1000)
    + quests_in(LOCH_MODAN, 12, 18, 2000)
    + quests_in(REDRIDGE, 15, 25, 3000)
)
ALL_HUBS = levelroute.HUBS + levelroute.STARTING_LAND_HUBS


def master_rows():
    return [
        {
            "guid": 90000 + i,
            "map_id": hub.point[0],
            "x": hub.point[1] + 5.0,
            "y": hub.point[2],
            "name": "%s flight master" % hub.name,
            "enemy_group": 0,
        }
        for i, hub in enumerate(ALL_HUBS)
    ]


def spawn_of(key):
    return 90000 + [h.key for h in ALL_HUBS].index(key)


def world():
    return guildlevel.world(QUESTS, master_rows())


def member(**over):
    redridge = levelroute.BY_KEY["redridge"].point
    base = dict(
        name="Clunk",
        guild="Cave",
        role=guildjobs.RAIDER,
        level=17,
        class_id=PRIEST,
        race=HUMAN,
        online=True,
        map_id=EASTERN_KINGDOMS,
        x=redridge[1] + 300.0,
        y=redridge[2],
        zone_id=REDRIDGE,
        money=0,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


def loop(level=17):
    return deathloop.loops(deaths(6, level=level), {"Clunk": level})["Clunk"]


def plan(members_, **kw):
    kw.setdefault("masters", {"Cave": "Grug"})
    kw.setdefault("leveling", world())
    kw.setdefault("cap", guildroute.FAR_WALK_YARDS)
    return guildjobs.plan(members_, **kw)


def steps_of(result):
    return [s for s in result.steps if s.holder == "Clunk"]


class ThePassLeavesTheZone(unittest.TestCase):
    def test_redridge_fits_so_with_no_loop_nothing_walks_it_out(self):
        self.assertEqual(steps_of(plan([member()])), [])
        self.assertEqual(steps_of(plan([member()], loops={})), [])

    def test_in_the_loop_its_next_job_is_a_town_errand(self):
        result = plan([member()], loops={"Clunk": loop()})
        steps = steps_of(result)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.action, "hearth")
        self.assertEqual([(r.kind, r.command) for r in step.rows], [("hearth", "use")])
        self.assertIn("town errand", step.said)
        self.assertIn("died 6 times in Redridge Mountains", step.said)
        self.assertEqual(result.lines["Clunk"], step.said)

    def test_with_the_hearth_cooling_it_walks_to_a_hub_of_another_zone(self):
        recent = (guildjobs.Recent("Clunk", "hearth", 10, "applied"),)
        steps = steps_of(plan([member()], loops={"Clunk": loop()}, recent=recent))
        self.assertEqual([s.action for s in steps], [guildlevel.ACTION])
        command = steps[0].rows[0].command
        self.assertNotIn("creature:%d " % spawn_of("redridge"), command)
        self.assertIn("died 6 times in Redridge Mountains", steps[0].said)

    def test_with_no_way_out_no_quest_of_the_zone_is_planned(self):
        recent = (
            guildjobs.Recent("Clunk", "hearth", 10, "applied"),
            guildjobs.Recent("Clunk", guildlevel.ACTION, 10, "applied"),
        )
        result = plan([member()], loops={"Clunk": loop()}, recent=recent)
        self.assertEqual(steps_of(result), [])
        self.assertIn("plans no quest in Redridge Mountains", result.lines["Clunk"])

    def test_the_level_walk_never_chooses_the_loop_zone(self):
        # Level 21 out of Elwynn: Redridge is the only hub of the three that
        # fits, so with the loop no hub is chosen there.
        here = member(level=21, zone_id=ELWYNN, x=-9000.0, y=100.0)
        normal = steps_of(plan([here]))
        self.assertIn("creature:%d " % spawn_of("redridge"), normal[0].rows[0].command)
        looped = steps_of(plan([here], loops={"Clunk": loop(21)}))
        for step in looped:
            for row in step.rows:
                self.assertNotIn("creature:%d " % spawn_of("redridge"), row.command)

    def test_once_the_loop_clears_planning_is_as_before(self):
        cleared = deathloop.loops(deaths(6, level=17), {"Clunk": 18})
        self.assertEqual(cleared, {})
        self.assertEqual(steps_of(plan([member()], loops=cleared)), [])

    def test_the_bridge_reads_the_deaths_and_hands_the_loops_to_the_plan(self):
        bridge = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertIn('facts["death_loops"] = deathloop.loops(', bridge)
        self.assertIn('loops=facts.get("death_loops"))', bridge)
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(" deathloop.py ", dockerfile)


if __name__ == "__main__":
    unittest.main()
