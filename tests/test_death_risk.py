"""Death-loop prevention: intervene before the fifth death (#2591).

WHY THIS EXISTS. The death-loop detector (deathloop.loops, #1464) names a
loop only at five deaths in one zone within an hour, so deaths one through
four are invisible to the planner: a member visibly heading into a loop —
repeated deaths to the same killer, no level gained — gets no intervention
until the loop has fully formed, and the escape then relocates it into the
next zone, where the same behaviour starts a new loop. These tests hold the
prevention layer: a risk read beside the loop read (deathloop.risk), a
planner intervention at risk beside death_loop_first (guildjobs.plan's
`risks`), the loop zone staying avoided after the loop goes quiet
(guildjobs.plan's `avoid`, off deathloop.avoided), and the stuck read
carrying an at-risk count distinct from the loop count.
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
    from apiv2 import members

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


# ---- the risk read --------------------------------------------------------------


class TheRiskRead(unittest.TestCase):
    def test_two_deaths_to_the_same_killer_inside_30_minutes_is_a_risk(self):
        rows = [death(2, zone=WETLANDS), death(20)]
        risk = deathloop.risk(rows, {"Clunk": 21})["Clunk"]
        self.assertEqual(risk.trigger, "killer")
        self.assertEqual(risk.killer, "Great Goretusk")
        self.assertEqual(risk.deaths, 2)
        self.assertEqual(risk.level, 21)
        # The risk zone is where the newest of those deaths happened.
        self.assertEqual(risk.zone, WETLANDS)

    def test_two_deaths_in_the_same_zone_inside_30_minutes_is_a_risk(self):
        rows = [death(2, killer="Redridge Mongrel"), death(25, killer="Tarl Mill")]
        risk = deathloop.risk(rows, {"Clunk": 21})["Clunk"]
        self.assertEqual(risk.trigger, "zone")
        self.assertEqual(risk.zone, REDRIDGE)
        self.assertEqual(risk.deaths, 2)

    def test_three_deaths_across_any_zones_inside_an_hour_is_a_risk(self):
        rows = [
            death(2, zone=WETLANDS, killer="Mottled Raptor"),
            death(30, zone=ELWYNN, killer="Defias Bandit"),
            death(55, killer="Redridge Mongrel"),
        ]
        risk = deathloop.risk(rows, {"Clunk": 21})["Clunk"]
        self.assertEqual(risk.trigger, "deaths")
        self.assertEqual(risk.deaths, 3)

    def test_scattered_single_deaths_are_not_a_risk(self):
        rows = [death(2, zone=WETLANDS, killer="Mottled Raptor")]
        self.assertEqual(deathloop.risk(rows, {"Clunk": 21}), {})
        rows.append(death(50, killer="Defias Bandit"))
        self.assertEqual(deathloop.risk(rows, {"Clunk": 21}), {})

    def test_two_deaths_to_the_same_killer_over_30_minutes_apart_are_not(self):
        rows = [death(2, zone=WETLANDS), death(40)]
        self.assertEqual(deathloop.risk(rows, {"Clunk": 21}), {})

    def test_deaths_followed_by_a_level_gain_are_not_a_risk(self):
        rows = [death(2, zone=WETLANDS), death(20)]
        self.assertEqual(deathloop.risk(rows, {"Clunk": 22}), {})

    def test_a_level_gain_between_deaths_resets_the_count(self):
        # Two same-killer deaths at 21, then a gain and one more at 22: the
        # deaths at the member's level now are a run of one.
        rows = [death(2, level=22), death(50), death(55)]
        self.assertEqual(deathloop.risk(rows, {"Clunk": 22}), {})

    def test_the_risk_reason_names_the_trigger(self):
        rows = [death(2, zone=WETLANDS), death(20)]
        risk = deathloop.risk(rows, {"Clunk": 21})["Clunk"]
        self.assertEqual(
            risk.blocker(),
            "Died 2 times to Great Goretusk within 30 minutes, with no level gained.",
        )


# ---- a formed loop leaves its zone avoided --------------------------------------


class TheAvoidedZones(unittest.TestCase):
    def loop_rows(self, start):
        return [death(start + i * 8) for i in range(6)]

    def test_a_formed_loop_leaves_its_zone_avoided_after_the_quiet_window(self):
        rows = self.loop_rows(start=200)
        # The loop itself has cleared: its newest death is past the quiet.
        self.assertEqual(deathloop.loops(rows, {"Clunk": 21}), {})
        self.assertEqual(deathloop.avoided(rows, {"Clunk": 21}), {"Clunk": (REDRIDGE,)})

    def test_a_level_gain_lifts_the_avoidance(self):
        rows = self.loop_rows(start=200)
        self.assertEqual(deathloop.avoided(rows, {"Clunk": 22}), {})

    def test_deaths_that_never_formed_a_loop_avoid_nothing(self):
        rows = [death(200 + i * 8) for i in range(4)]
        self.assertEqual(deathloop.avoided(rows, {"Clunk": 21}), {})

    def test_a_live_loops_zone_is_avoided_too(self):
        rows = self.loop_rows(start=2)
        self.assertEqual(deathloop.avoided(rows, {"Clunk": 21}), {"Clunk": (REDRIDGE,)})


# ---- the planner intervenes at risk ---------------------------------------------

GOLDSHIRE = (-9459.0, 43.0)


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
        level=21,
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


def bound_in_elwynn(**over):
    return member(
        home_map=EASTERN_KINGDOMS,
        home_x=GOLDSHIRE[0],
        home_y=GOLDSHIRE[1],
        home_zone=ELWYNN,
        **over,
    )


def risk(level=21):
    rows = [death(2, level=level), death(20, level=level)]
    return deathloop.risk(rows, {"Clunk": level})["Clunk"]


def loop(level=21):
    rows = [death(2 + i * 8, level=level) for i in range(6)]
    return deathloop.loops(rows, {"Clunk": level})["Clunk"]


def plan(members_, **kw):
    kw.setdefault("masters", {"Cave": "Grug"})
    kw.setdefault("leveling", world())
    kw.setdefault("cap", guildroute.FAR_WALK_YARDS)
    return guildjobs.plan(members_, **kw)


def steps_of(result):
    return [s for s in result.steps if s.holder == "Clunk"]


class TheIntervention(unittest.TestCase):
    def test_an_at_risk_member_in_the_zone_hearths_home_ahead_of_quests(self):
        result = plan([member()], risks={"Clunk": risk()})
        steps = steps_of(result)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.action, "hearth")
        self.assertEqual([(r.kind, r.command) for r in step.rows], [("hearth", "use")])
        self.assertIn("town errand", step.said)
        self.assertIn("died 2 times to Great Goretusk within 30 minutes", step.said)
        # One line names the intervention and its trigger.
        self.assertTrue(
            any("death-risk intervention" in n for n in result.notes), result.notes
        )

    def test_the_hearth_walks_on_to_a_hub_one_band_lower(self):
        # At 21 no hub outside Redridge fits at all (the loop's own onward
        # walk is refused, below); one band lower, Westfall fits.
        result = plan([bound_in_elwynn()], risks={"Clunk": risk()})
        steps = steps_of(result)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step.action, "hearth")
        self.assertEqual(len(step.rows), 2, step.rows)
        walk = step.rows[1]
        self.assertIn("creature:%d " % spawn_of("westfall"), walk.command)
        self.assertIn("then walks on to", step.said)

    def test_the_loops_own_onward_walk_is_not_band_lowered(self):
        # The contrast: a formed loop's hearth at 21 walks on nowhere,
        # because at the member's own level no other hub fits.
        result = plan([bound_in_elwynn()], loops={"Clunk": loop()})
        steps = steps_of(result)
        self.assertEqual(len(steps), 1)
        self.assertEqual(
            [(r.kind, r.command) for r in steps[0].rows], [("hearth", "use")]
        )

    def test_a_healthy_member_is_planned_as_before(self):
        here = member(level=17)
        self.assertEqual(steps_of(plan([here])), [])
        self.assertEqual(steps_of(plan([here], risks={})), [])
        self.assertEqual(steps_of(plan([here], risks={"Grug": risk()})), [])

    def test_an_at_risk_member_out_of_the_zone_is_not_walked_back_into_it(self):
        here = member(zone_id=ELWYNN, x=-9000.0, y=100.0)
        normal = steps_of(plan([here]))
        self.assertIn("creature:%d " % spawn_of("redridge"), normal[0].rows[0].command)
        guarded = steps_of(plan([here], risks={"Clunk": risk()}))
        for step in guarded:
            for row in step.rows:
                self.assertNotIn("creature:%d " % spawn_of("redridge"), row.command)

    def test_the_level_walk_that_avoids_the_zone_names_the_intervention(self):
        # Out of the zone the intervention is the steered level walk itself:
        # its line names the intervention, as the in-zone returns do.
        here = member(zone_id=ELWYNN, x=-9000.0, y=100.0)
        result = plan([here], risks={"Clunk": risk()})
        self.assertTrue(
            any("death-risk intervention" in n for n in result.notes), result.notes
        )

    def test_with_no_way_out_no_quest_of_the_risk_zone_is_planned(self):
        recent = (
            guildjobs.Recent("Clunk", "hearth", 10, "applied"),
            guildjobs.Recent("Clunk", guildlevel.ACTION, 10, "applied"),
        )
        result = plan([member()], risks={"Clunk": risk()}, recent=recent)
        self.assertEqual(steps_of(result), [])
        self.assertIn("plans no quest in Redridge Mountains", result.lines["Clunk"])
        self.assertIn("death-risk intervention", result.lines["Clunk"])


class ThePostLoopAvoidance(unittest.TestCase):
    def test_a_post_loop_member_is_not_walked_back_into_the_loop_zone(self):
        here = member(zone_id=ELWYNN, x=-9000.0, y=100.0)
        normal = steps_of(plan([here]))
        self.assertIn("creature:%d " % spawn_of("redridge"), normal[0].rows[0].command)
        guarded = steps_of(plan([here], avoid={"Clunk": (REDRIDGE,)}))
        for step in guarded:
            for row in step.rows:
                self.assertNotIn("creature:%d " % spawn_of("redridge"), row.command)


# ---- the stuck read counts the inflow --------------------------------------------

GUILD = [
    {"name": "Grug", "guild_name": "Cave", "level": 30, "class_id": 1, "race": 2},
    {"name": "Clunk", "guild_name": "Cave", "level": 21, "class_id": 5, "race": 1},
]


def roster(rows):
    readings = {
        "Grug": {"online": True, "life": "alive", "fresh_at": NOW},
        "Clunk": {"online": True, "life": "alive", "fresh_at": NOW},
    }
    return members.build(
        {"Grug": ["Grug"]},
        [dict(g) for g in GUILD],
        [],
        [],
        [],
        {},
        NOW,
        readings=readings,
        deaths=rows,
    )


class TheStuckReadCountsTheRisk(unittest.TestCase):
    def test_an_at_risk_member_counts_and_is_not_a_stuck_loop(self):
        built = roster([death(2), death(20)])
        self.assertEqual(built["at_risk"], ["Clunk"])
        view = members.stuck_view(built)
        self.assertEqual(view["at_risk"], 1)
        self.assertEqual(view["at_risk_members"], ["Clunk"])
        self.assertNotIn("Clunk", [r["name"] for r in view["members"]])

    def test_a_member_in_a_loop_is_not_counted_at_risk(self):
        built = roster([death(2 + i * 8) for i in range(6)])
        self.assertEqual(built["at_risk"], [])
        view = members.stuck_view(built)
        self.assertEqual(view["at_risk"], 0)
        self.assertEqual([r["kind"] for r in view["members"]], ["death-loop"])

    def test_no_deaths_no_risk(self):
        self.assertEqual(roster([])["at_risk"], [])
        self.assertEqual(members.stuck_view(roster([]))["at_risk"], 0)


if __name__ == "__main__":
    unittest.main()
