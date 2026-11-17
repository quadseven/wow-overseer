"""The merged pre-loop intervention runs, and its avoidance expires (#2591, #2663).

WHY THIS EXISTS. guildjobs.plan takes risks= and avoided=, and the bridge
passed neither, so the intervention at risk and the avoided zones had no
caller. The bridge now passes both from one judgement (deathloop.judge). The
avoidance is bounded: a level gain clears it, and so does a day without a
death in the zone, because a level-60 member never gains a level.
"""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    HERE = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    import deathloop
    from test_deathloop import death, deaths, member, plan, steps_of

BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
HOUR = 60


class TheBridgePassesWhatTheModuleJudges(unittest.TestCase):
    def test_the_plan_call_takes_risks_and_avoided(self):
        call = BRIDGE[BRIDGE.index("plan = guildjobs.plan(") :]
        call = call[: call.index("plan_started") if "plan_started" in call else 4000]
        call = call[: call.index("log.info(")]
        for word in (
            'risks=facts.get("death_risks")',
            'avoided=facts.get("death_avoided")',
        ):
            self.assertIn(word, call)

    def test_the_facts_come_from_the_one_judgement(self):
        self.assertIn("deathloop.judge(death_rows, levels)", BRIDGE)


class TheJudgement(unittest.TestCase):
    def test_it_returns_loops_risks_and_avoided_together(self):
        rows = deaths(2, level=17) + deaths(6, start=150, level=21, zone=11)
        loops, risks, avoided = deathloop.judge(rows, {"Clunk": 17})
        self.assertIn("Clunk", risks)
        self.assertEqual({}, loops)
        self.assertEqual({}, avoided)  # the level 21 deaths are not at level 17

    def test_a_risk_is_judged_from_the_newest_hour_only(self):
        old = [death(200, killer="Boar"), death(205, killer="Boar")]
        self.assertEqual({}, deathloop.judge(old, {"Clunk": 21})[1])
        new = [death(20, killer="Boar"), death(25, killer="Boar")]
        self.assertIn("Clunk", deathloop.judge(new, {"Clunk": 21})[1])

    def test_the_planner_runs_the_intervention_on_the_judged_risk(self):
        _loops, risks, avoided = deathloop.judge(deaths(2, level=17), {"Clunk": 17})
        result = plan([member()], risks=risks, avoided=avoided)
        self.assertEqual("hearth", steps_of(result)[0].action)


class TheAvoidanceExpires(unittest.TestCase):
    def test_it_holds_inside_the_bound(self):
        rows = deaths(6, start=150, level=21)
        self.assertEqual({"Clunk": {44}}, deathloop.judge(rows, {"Clunk": 21})[2])

    def test_it_ends_a_day_after_the_newest_death_in_the_zone(self):
        day = deathloop.AVOID_SECONDS // 60
        edge = deaths(6, start=day, level=21)
        self.assertEqual({"Clunk": {44}}, deathloop.avoided_zones(edge, {"Clunk": 21}))
        gone = deaths(6, start=day + 1, level=21)
        self.assertEqual({}, deathloop.avoided_zones(gone, {"Clunk": 21}))

    def test_a_level_gain_still_clears_it(self):
        rows = deaths(6, start=150, level=21)
        self.assertEqual({}, deathloop.avoided_zones(rows, {"Clunk": 22}))

    def test_the_read_covers_the_bound(self):
        self.assertLessEqual(deathloop.AVOID_SECONDS, deathloop.SLOW_READ_SECONDS)


if __name__ == "__main__":
    unittest.main()
