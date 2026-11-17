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
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    HERE = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    import deathloop
    import guildjobs
    import guildlevel
    import guildroute
    import levelroute
    from apiv2 import health, members

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


# ---- a slow loop: a dozen deaths in one zone in a day (#2615) --------------------

BARRENS = 17


def slow_deaths(n, every=45, start=10, **kw):
    """`n` deaths `every` minutes apart, never five within one hour."""
    kw.setdefault("zone", BARRENS)
    kw.setdefault("killer", "Orgrimmar Grunt")
    return deaths(n, every=every, start=start, **kw)


class ASlowLoop(unittest.TestCase):
    def test_thirty_two_deaths_in_one_zone_in_a_day_is_a_loop(self):
        rows = slow_deaths(32)
        self.assertLessEqual(rows[-1]["age"], deathloop.SLOW_WINDOW_SECONDS)
        loop = deathloop.loops(rows, {"Clunk": 21}, slow=True)["Clunk"]
        self.assertEqual((loop.zone, loop.deaths, loop.level), (BARRENS, 32, 21))
        self.assertTrue(loop.slow)
        self.assertEqual(loop.killer, "Orgrimmar Grunt")
        self.assertEqual(loop.first_age, rows[-1]["age"])
        self.assertEqual(
            loop.blocker(),
            "Died 32 times in The Barrens in a day, mostly to Orgrimmar Grunt, "
            "with no level gained.",
        )

    def test_the_hourly_rule_alone_does_not_see_it(self):
        self.assertEqual(deathloop.loops(slow_deaths(32), {"Clunk": 21}), {})

    def test_the_threshold_is_twelve_deaths_inside_the_day(self):
        at = deathloop.SLOW_MIN_DEATHS
        found = deathloop.loops(slow_deaths(at, every=100), {"Clunk": 21}, slow=True)
        self.assertEqual(found["Clunk"].deaths, at)
        under = deathloop.loops(
            slow_deaths(at - 1, every=100), {"Clunk": 21}, slow=True
        )
        self.assertEqual(under, {})
        # Twelve deaths, the oldest past the day: eleven count.
        spread = deathloop.loops(slow_deaths(at, every=131), {"Clunk": 21}, slow=True)
        self.assertEqual(spread, {})

    def test_deaths_in_other_zones_do_not_add_up(self):
        rows = slow_deaths(8) + slow_deaths(8, start=30, zone=REDRIDGE)
        self.assertEqual(deathloop.loops(rows, {"Clunk": 21}, slow=True), {})

    def test_a_level_gained_clears_it(self):
        self.assertEqual(deathloop.loops(slow_deaths(32), {"Clunk": 22}, slow=True), {})
        # Deaths at the level before the gain do not count toward the dozen.
        rows = slow_deaths(6, level=22) + slow_deaths(20, start=300, level=21)
        self.assertEqual(deathloop.loops(rows, {"Clunk": 22}, slow=True), {})

    def test_it_clears_on_the_quiet_clock(self):
        quiet = deathloop.QUIET_SECONDS // MINUTE
        self.assertEqual(
            deathloop.loops(slow_deaths(20, start=quiet + 1), {"Clunk": 21}, slow=True),
            {},
        )
        self.assertIn(
            "Clunk",
            deathloop.loops(slow_deaths(20, start=quiet - 1), {"Clunk": 21}, slow=True),
        )

    def test_an_hourly_loop_keeps_its_own_sentence_and_window(self):
        rows = deaths(6) + slow_deaths(20, start=120, zone=REDRIDGE)
        loop = deathloop.loops(rows, {"Clunk": 21}, slow=True)["Clunk"]
        self.assertFalse(loop.slow)
        self.assertEqual(loop.deaths, 6)
        self.assertIn("within an hour", loop.blocker())

    def test_the_longer_read_does_not_widen_the_hourly_rule(self):
        # Five deaths in an hour, twenty hours ago, and one death since: the
        # three-hour read never held that old window, so the day-long read
        # must not call it an hourly loop either.
        rows = [death(5)] + deaths(5, start=20 * 60)
        self.assertEqual(deathloop.loops(rows, {"Clunk": 21}, slow=True), {})

    def test_the_slow_read_covers_the_day_and_the_quiet_clock(self):
        self.assertEqual(deathloop.SLOW_MIN_DEATHS, 12)
        self.assertEqual(deathloop.SLOW_WINDOW_SECONDS, 24 * 3600)
        self.assertEqual(
            deathloop.SLOW_READ_SECONDS,
            deathloop.SLOW_WINDOW_SECONDS + deathloop.QUIET_SECONDS,
        )

    def test_the_stuck_reader_lists_a_slow_loop_with_its_own_sentence(self):
        view = members.stuck_view(roster(slow_deaths(32)))
        rows = {r["name"]: r for r in view["members"]}
        self.assertIn("Clunk", rows)
        clunk = rows["Clunk"]
        self.assertEqual(clunk["kind"], "death-loop")
        self.assertEqual(clunk["step"], "Dying in The Barrens")
        self.assertIn("Died 32 times in The Barrens in a day", clunk["blocker"])
        self.assertEqual(clunk["since"], NOW - (10 + 31 * 45) * MINUTE)

    def test_the_stuck_reader_reads_the_day_and_says_so(self):
        source = (HERE / "apiv2" / "members.py").read_text(encoding="utf-8")
        self.assertIn("deathloop.SLOW_READ_SECONDS", source)
        self.assertIn("twelve or more deaths in one zone within a day", members.BASIS)


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


# ---- the loop clears once the member has left the zone (#2152) ------------------


def roster_at(rows, zone_id, life="alive", level=21):
    """The roster with Clunk's fresh snapshot standing in `zone_id`."""
    guild = [dict(GUILD[0]), dict(GUILD[1], level=level)]
    readings = {
        "Grug": {"online": True, "life": "alive", "fresh_at": NOW},
        "Clunk": {"online": True, "life": life, "fresh_at": NOW},
    }
    snaps = (
        []
        if zone_id is None
        else [
            {
                "name": "Clunk",
                "zone_id": zone_id,
                "map_id": EASTERN_KINGDOMS,
                "in_combat": False,
            }
        ]
    )
    return members.build(
        {"Grug": ["Grug"]},
        guild,
        [],
        snaps,
        [],
        {},
        NOW,
        readings=readings,
        deaths=rows,
    )


class TheLoopClearsOnceTheMemberLeaves(unittest.TestCase):
    def test_a_member_standing_in_another_zone_is_not_listed(self):
        view = members.stuck_view(roster_at(deaths(6), WESTFALL))
        self.assertEqual(view["members"], [])

    def test_the_roster_row_itself_is_not_stuck(self):
        built = roster_at(deaths(6), WESTFALL)
        row = {r["name"]: r for r in built["members"]}["Clunk"]
        self.assertFalse(row["stuck"])
        self.assertEqual(row["stuck_kind"], "")
        self.assertEqual(row["blocker"], "")

    def test_a_member_still_in_the_zone_is_listed(self):
        view = members.stuck_view(roster_at(deaths(6), REDRIDGE))
        rows = {r["name"]: r for r in view["members"]}
        self.assertEqual(rows["Clunk"]["kind"], "death-loop")
        self.assertIn("Redridge Mountains", rows["Clunk"]["blocker"])

    def test_without_a_snapshot_the_loop_still_lists(self):
        view = members.stuck_view(roster_at(deaths(6), None))
        self.assertEqual([r["name"] for r in view["members"]], ["Clunk"])

    def test_a_ghost_in_another_zone_is_not_listed_as_dying_in_the_loop_zone(self):
        view = members.stuck_view(roster_at(deaths(6), WETLANDS, life="ghost"))
        self.assertEqual(view["members"], [])

    def test_one_member_leaving_does_not_clear_another_still_in_its_loop(self):
        rows = deaths(6) + deaths(5, name="Grug", level=30)
        built = members.build(
            {"Grug": ["Grug"]},
            [dict(GUILD[0]), dict(GUILD[1])],
            [],
            [
                {
                    "name": "Clunk",
                    "zone_id": WESTFALL,
                    "map_id": EASTERN_KINGDOMS,
                    "in_combat": False,
                },
                {
                    "name": "Grug",
                    "zone_id": REDRIDGE,
                    "map_id": EASTERN_KINGDOMS,
                    "in_combat": False,
                },
            ],
            [],
            {},
            NOW,
            readings={
                "Grug": {"online": True, "life": "alive", "fresh_at": NOW},
                "Clunk": {"online": True, "life": "alive", "fresh_at": NOW},
            },
            deaths=rows,
        )
        view = members.stuck_view(built)
        self.assertEqual([r["name"] for r in view["members"]], ["Grug"])
        self.assertEqual(view["members"][0]["kind"], "death-loop")

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

    def test_a_passing_level_refusal_retries_the_escape_after_five_minutes(self):
        for age, expected in (
            (4, []),
            (5, [guildlevel.ACTION]),
            (101, [guildlevel.ACTION]),
        ):
            with self.subTest(age=age):
                recent = (
                    guildjobs.Recent("Clunk", "hearth", 21, "applied"),
                    guildjobs.Recent(
                        "Clunk",
                        guildlevel.ACTION,
                        age,
                        "error",
                        retryable=True,
                        refusal="character is held by another verb",
                    ),
                )
                steps = steps_of(
                    plan([member()], loops={"Clunk": loop()}, recent=recent)
                )
                self.assertEqual([step.action for step in steps], expected)
                for step in steps:
                    self.assertNotIn(
                        "creature:%d " % spawn_of("redridge"), step.rows[0].command
                    )

    def test_other_level_results_keep_the_normal_cooldown(self):
        for status, retryable, refusal in (
            ("pending", True, "character is held by another verb"),
            ("applied", True, "character is held by another verb"),
            ("error", False, "character is held by another verb"),
            ("error", True, "ground that does not hold"),
            ("error", True, "unrecognized refusal"),
        ):
            with self.subTest(status=status, retryable=retryable, refusal=refusal):
                recent = (
                    guildjobs.Recent("Clunk", "hearth", 21, "applied"),
                    guildjobs.Recent(
                        "Clunk",
                        guildlevel.ACTION,
                        101,
                        status,
                        retryable=retryable,
                        refusal=refusal,
                    ),
                )
                self.assertEqual(
                    steps_of(plan([member()], loops={"Clunk": loop()}, recent=recent)),
                    [],
                )

    def test_a_temporary_hold_also_retries_an_ordinary_level_walk(self):
        here = member(level=21, zone_id=ELWYNN, x=-9000.0, y=100.0)
        recent = (
            guildjobs.Recent(
                "Clunk",
                guildlevel.ACTION,
                5,
                "error",
                retryable=True,
                reason="character is in combat",
            ),
        )
        self.assertEqual(
            [step.action for step in steps_of(plan([here], recent=recent))],
            [guildlevel.ACTION],
        )

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
        self.assertIn("deathloop.judge(death_rows, levels)", bridge)
        self.assertIn('facts["death_loops"]', bridge)
        self.assertIn('loops=facts.get("death_loops"),', bridge)


# ---- the pre-loop risk read (#2591) --------------------------------------------


class TheRiskRead(unittest.TestCase):
    def test_two_deaths_to_the_same_killer_within_30_minutes_is_a_risk(self):
        rows = [death(2, zone=WETLANDS), death(20, zone=ELWYNN)]
        found = deathloop.risks(rows, {"Clunk": 21})
        risk = found["Clunk"]
        self.assertEqual(risk.deaths, 2)
        self.assertEqual(risk.killer, "Great Goretusk")
        self.assertIn("same killer", risk.trigger)
        self.assertIn("no level gained", risk.reason())

    def test_two_deaths_in_the_same_zone_within_30_minutes_is_a_risk(self):
        rows = [death(2, killer="Redridge Mongrel"), death(25, killer="Tarantula")]
        found = deathloop.risks(rows, {"Clunk": 21})
        self.assertEqual(found["Clunk"].zone, REDRIDGE)
        self.assertIn("same zone", found["Clunk"].trigger)

    def test_three_deaths_across_zones_within_an_hour_is_a_risk(self):
        rows = [
            death(2, zone=WETLANDS, killer="Mottled Raptor"),
            death(25, zone=ELWYNN, killer="Riverpaw Gnoll"),
            death(50, killer="Tarantula"),
        ]
        found = deathloop.risks(rows, {"Clunk": 21})
        self.assertEqual(found["Clunk"].deaths, 3)
        self.assertIn("an hour", found["Clunk"].trigger)

    def test_scattered_single_deaths_are_not_a_risk(self):
        rows = [death(2, zone=WETLANDS, killer="Mottled Raptor"), death(50)]
        self.assertEqual(deathloop.risks(rows, {"Clunk": 21}), {})
        apart = [death(2), death(45)]
        self.assertEqual(deathloop.risks(apart, {"Clunk": 21}), {})

    def test_deaths_followed_by_a_level_gain_are_not_a_risk(self):
        rows = [death(2), death(20)]
        self.assertEqual(deathloop.risks(rows, {"Clunk": 22}), {})
        gained = [death(2, level=22), death(20, level=21)]
        self.assertEqual(deathloop.risks(gained, {"Clunk": 22}), {})

    def test_a_formed_loop_leaves_its_zone_avoided_until_a_level_gain(self):
        old = deaths(6, start=150, level=21)
        self.assertEqual(deathloop.loops(old, {"Clunk": 21}), {})
        self.assertEqual(
            deathloop.avoided_zones(old, {"Clunk": 21}), {"Clunk": {REDRIDGE}}
        )
        self.assertEqual(deathloop.avoided_zones(old, {"Clunk": 22}), {})


class ThePlannerIntervenesAtRisk(unittest.TestCase):
    def test_an_at_risk_member_in_the_risk_zone_gets_the_intervention_first(self):
        risk = deathloop.risks(deaths(2, level=17), {"Clunk": 17})
        result = plan([member()], risks=risk)
        steps = steps_of(result)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].action, "hearth")
        self.assertIn("town errand", steps[0].said)
        self.assertIn("prevention", result.lines["Clunk"])
        self.assertIn("same killer", result.lines["Clunk"])

    def test_a_healthy_member_is_planned_as_before(self):
        self.assertEqual(steps_of(plan([member()], risks={})), [])
        self.assertEqual(steps_of(plan([member()])), [])

    def test_a_post_loop_member_is_not_routed_back_into_the_loop_zone(self):
        here = member(level=21, zone_id=ELWYNN, x=-9000.0, y=100.0)
        normal = steps_of(plan([here]))
        self.assertIn("creature:%d " % spawn_of("redridge"), normal[0].rows[0].command)
        avoided = deathloop.avoided_zones(deaths(6, start=150, level=21), {"Clunk": 21})
        looped = steps_of(plan([here], avoided=avoided))
        for step in looped:
            for row in step.rows:
                self.assertNotIn("creature:%d " % spawn_of("redridge"), row.command)


# ---- a loop in a dungeon or a door area names its place (#1881) ------------------

ZUL_FARRAK_ZONE, ZUL_FARRAK_MAP = 1176, 209
SCARLET_ENCLAVE_ZONE, EBON_HOLD_MAP = 4298, 609


class ALoopOutsideTheDrawnZonesIsNamed(unittest.TestCase):
    """The health finding read "Dying in somewhere this page cannot place" for
    members dying in Zul'Farrak, in a dungeon's door area and at the Death Knight
    start: zones.json draws no rectangles there, so the reader named nothing."""

    def loop_in(self, zone, map_id):
        rows = [
            dict(death(a, zone=zone, level=40), map=map_id)
            for a in (10, 14, 18, 22, 26)
        ]
        return deathloop.loops(rows, {"Clunk": 40})["Clunk"]

    def test_a_loop_inside_a_dungeon_names_the_dungeon(self):
        loop = self.loop_in(ZUL_FARRAK_ZONE, ZUL_FARRAK_MAP)
        self.assertEqual("Zul'Farrak", loop.place)
        self.assertEqual("Dying in Zul'Farrak", members.loop_blocker(loop, NOW)["step"])

    def test_a_loop_in_a_door_area_or_the_death_knight_start_is_named(self):
        self.assertEqual("Uldaman", self.loop_in(1337, EASTERN_KINGDOMS).place)
        self.assertEqual("Blackrock Mountain", self.loop_in(25, EASTERN_KINGDOMS).place)
        self.assertEqual(
            "Plaguelands: The Scarlet Enclave",
            self.loop_in(SCARLET_ENCLAVE_ZONE, EBON_HOLD_MAP).place,
        )

    def test_an_id_nothing_names_still_says_so(self):
        self.assertEqual(
            "somewhere this page cannot place",
            self.loop_in(999999, EASTERN_KINGDOMS).place,
        )

    def test_the_drawn_zones_are_named_as_before(self):
        self.assertEqual("Redridge Mountains", levelroute.zone_name(REDRIDGE))
        self.assertEqual("Redridge Mountains", levelroute.zone_name(REDRIDGE, 0))


if __name__ == "__main__":
    unittest.main()
