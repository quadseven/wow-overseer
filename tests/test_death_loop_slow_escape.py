"""A day-scale death loop gets the escape too (#2152, #2615).

WHY THIS EXISTS. The stuck list began judging the slow loop (twelve deaths in
one zone inside a day, #2802), but the guild jobs pass read only the newest
three hours of deaths and judged only the hourly rule, so a member dying one
or two times an hour in Silithus was listed as looping and still handed the
ordinary rungs, with no escape and no reason line. The pass now reads the day
and judges the slow rule, and the escape treats a slow loop as any other.
"""

import dataclasses
import pathlib
import re
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    HERE = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    import deathloop
    from test_guildjobs_death_loop_home import (
        EASTERN_KINGDOMS,
        ELWYNN,
        GOLDSHIRE_INN,
        NAME,
        hearth_steps,
        loop_of,
        member,
        plan,
    )

BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def function_source(name):
    start = BRIDGE.index("def %s(" % name)
    end = BRIDGE.index("\ndef ", start + 1)
    return BRIDGE[start:end]


def slow_rows(count=14, zone=1377, level=60):
    return [
        {
            "name": NAME,
            "zone": zone,
            "map": 1,
            "level": level,
            "killer": "Twilight Geolord",
            "age": 600 + i * 45 * 60,
        }
        for i in range(count)
    ]


class TheJobsPassReadsTheDay(unittest.TestCase):
    def test_the_job_deaths_read_covers_the_slow_window(self):
        body = function_source("_job_deaths")
        self.assertIn("deathloop.SLOW_READ_SECONDS", body)
        self.assertNotIn("deathloop.READ_SECONDS", body)

    def test_the_job_facts_judge_the_slow_rule(self):
        body = function_source("_fetch_job_facts")
        self.assertTrue(
            re.search(r"deathloop\.loops\(.{0,200}?slow=True", body, re.S),
            "the guild jobs facts must judge slow loops",
        )

    def test_the_death_ask_planning_read_is_unchanged(self):
        # The social pass keeps its own three hour read and hourly rule.
        self.assertEqual(1, BRIDGE.count("(*names, deathloop.READ_SECONDS))"))

    def test_a_slow_loop_is_what_those_rows_make(self):
        found = deathloop.loops(slow_rows(), {NAME: 60}, slow=True)
        self.assertTrue(found[NAME].slow)
        self.assertEqual(found[NAME].zone, 1377)
        self.assertEqual({}, deathloop.loops(slow_rows(), {NAME: 60}))


class TheEscapeTakesASlowLoop(unittest.TestCase):
    def test_a_member_in_a_slow_loop_zone_hearths_first(self):
        m = member(
            NAME,
            rewarded=frozenset(),
            home_map=EASTERN_KINGDOMS,
            home_x=GOLDSHIRE_INN[0],
            home_y=GOLDSHIRE_INN[1],
            home_zone=ELWYNN,
        )
        loop = dataclasses.replace(loop_of(), slow=True, deaths=24)
        result = plan([m], loops={NAME: loop})
        self.assertEqual([s.holder for s in hearth_steps(result)], [NAME])
        self.assertIn("died 24 times in Hillsbrad Foothills in a day", loop.reason())


if __name__ == "__main__":
    unittest.main()
