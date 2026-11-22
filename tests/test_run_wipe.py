"""A party wiping inside a live guild run is a run wipe, counted and labelled.

Measured on the dev realm on 2026-11-18: five level 60 members of one guild
died 28 times in 83 minutes to Scholomance trash inside one guild run that was
still going. The death-loop reader listed them as "Dying in Scholomance", the
same line as a lone bot that keeps walking into a zone. They are still stuck, so
they are still counted, but the cause is the run's and the reader names it:
"run wipe (run N)", its own kind, its own line in the digest.
"""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    HERE = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    import deathloop
    import guildrun
    from apiv2 import health, members

NOW = 1_800_000_000
MINUTE = 60
ZONE, MAP = 2057, 289
RUN = 6257


def death(age_minutes, name="Clunk", level=60, killer="Diseased Ghoul"):
    return {
        "name": name,
        "zone": ZONE,
        "map": MAP,
        "level": level,
        "killer": killer,
        "age": int(age_minutes * MINUTE),
    }


def five():
    return [death(2 + i * 8) for i in range(5)]


GUILD = [
    {"name": "Grug", "level": 60, "guild": "Cave", "rank": 0},
    {"name": "Clunk", "level": 60, "guild": "Cave", "rank": 3},
]


def roster(rows, run_of=None):
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
        run_of=run_of,
    )


class TheLoopCarriesItsRun(unittest.TestCase):
    def test_a_loop_in_a_run_says_run_wipe_with_the_run_number(self):
        loop = deathloop.loops(five(), {"Clunk": 60})["Clunk"]
        self.assertEqual(loop.run, 0)
        tagged = deathloop.tag_runs({"Clunk": loop}, {"Clunk": RUN})["Clunk"]
        self.assertEqual(tagged.run, RUN)
        self.assertTrue(tagged.reason().startswith("run wipe (run 6257): died 5 times"))
        self.assertEqual((tagged.deaths, tagged.zone), (loop.deaths, loop.zone))

    def test_a_loop_outside_a_run_reads_as_ever(self):
        loop = deathloop.loops(five(), {"Clunk": 60})["Clunk"]
        self.assertEqual(deathloop.tag_runs({"Clunk": loop}, {}), {"Clunk": loop})
        self.assertEqual(deathloop.tag_runs({"Clunk": loop}, None), {"Clunk": loop})
        self.assertTrue(loop.reason().startswith("died 5 times"))

    def test_tagging_does_not_drop_or_add_loops(self):
        loop = deathloop.loops(five(), {"Clunk": 60})["Clunk"]
        out = deathloop.tag_runs({"Clunk": loop}, {"Other": 9})
        self.assertEqual(list(out), ["Clunk"])
        self.assertEqual(out["Clunk"].run, 0)


class RunStepDownDecision(unittest.TestCase):
    def tagged(self, runs):
        rows = []
        for name in runs:
            rows += [dict(d, name=name) for d in five()]
        found = deathloop.loops(rows, {n: 60 for n in runs})
        return deathloop.tag_runs(found, runs)

    def test_two_looping_members_of_one_run_give_one_step_down(self):
        found = self.tagged({"Clunk": RUN, "Brann": RUN})
        out = deathloop.run_step_downs(found)
        self.assertEqual(list(out), [RUN])
        self.assertEqual(out[RUN].members, ("Brann", "Clunk"))
        self.assertEqual(out[RUN].zone, ZONE)
        self.assertTrue(out[RUN].reason().startswith("run wipe (run 6257): 2 members"))

    def test_one_looping_member_of_a_run_gives_nothing(self):
        self.assertEqual(deathloop.run_step_downs(self.tagged({"Clunk": RUN})), {})

    def test_loops_outside_a_run_are_never_grouped(self):
        self.assertEqual(
            deathloop.run_step_downs(self.tagged({"Clunk": 0, "Brann": 0})), {}
        )

    def test_two_runs_are_judged_apart(self):
        found = self.tagged({"Clunk": RUN, "Brann": RUN + 1})
        self.assertEqual(deathloop.run_step_downs(found), {})
        self.assertEqual(deathloop.run_step_downs(None), {})


class TheStuckReaderNamesTheWipe(unittest.TestCase):
    def test_a_member_in_a_live_run_is_listed_as_a_run_wipe_and_still_counted(self):
        view = members.stuck_view(roster(five(), {"Clunk": RUN}))
        rows = {r["name"]: r for r in view["members"]}
        self.assertEqual(rows["Clunk"]["kind"], "run-wipe")
        self.assertEqual(rows["Clunk"]["step"], "Run wipe (run 6257) in Scholomance")
        self.assertTrue(
            rows["Clunk"]["blocker"].startswith("Run wipe (run 6257): died 5 times")
        )
        self.assertEqual(view["digest"]["count"], 1)

    def test_the_digest_gives_wipes_their_own_line(self):
        view = members.stuck_view(roster(five(), {"Clunk": RUN}))
        digest = view["digest"]
        self.assertEqual(digest["run_wipes"], 1)
        self.assertTrue(digest["causes"][0]["cause"].startswith("run-wipe: "))

    def test_without_a_run_it_stays_a_death_loop(self):
        view = members.stuck_view(roster(five(), {}))
        row = view["members"][0]
        self.assertEqual(row["kind"], "death-loop")
        self.assertEqual(row["step"], "Dying in Scholomance")
        self.assertEqual(view["digest"]["run_wipes"], 0)

    def test_a_wipe_is_the_members_own_blocker_not_a_followers(self):
        self.assertTrue(members._asking({"kind": deathloop.RUN_KIND}))

    def test_the_roster_read_hands_the_runs_to_build(self):
        source = (HERE / "apiv2" / "members.py").read_text(encoding="utf-8")
        self.assertIn("guildrun.inside_runs(rd)", source)
        self.assertIn('f.get("run_of")', source)


class TheHealthReadFilesWipesUnderDeaths(unittest.TestCase):
    def test_a_run_wipe_is_a_deaths_finding_on_its_own_step(self):
        self.assertEqual(health.STUCK_AREAS.get("run-wipe"), "deaths")
        view = members.stuck_view(roster(five(), {"Clunk": RUN}))
        found = health.stuck_findings(
            {"members": [dict(view["members"][0], since=NOW - 3 * 3600)]}, NOW
        )
        self.assertEqual(len(found), 1)
        self.assertIn("Run wipe", found[0]["title"])
        self.assertEqual(found[0]["area"], "deaths")


class FakeReader:
    def __init__(self, rows):
        self.rows_ = rows
        self.sql = ""

    def rows(self, sql, params=(), fallback="", what=""):
        self.sql = sql
        return self.rows_


class TheRunsAMemberIsInside(unittest.TestCase):
    def test_inside_runs_maps_each_member_to_its_run(self):
        reader = FakeReader(
            [
                {"id": 6258, "members": "Hurk:tank:warrior:45,Fumma:healer:priest:43"},
                {"id": 6257, "members": "Gronk:tank:warrior:60,Hurk:dps:warrior:45"},
            ]
        )
        got = guildrun.inside_runs(reader)
        self.assertEqual(got["Gronk"], 6257)
        # Rows come newest first: the newest run a member is in wins.
        self.assertEqual(got["Hurk"], 6258)
        self.assertEqual(got["Fumma"], 6258)
        self.assertIn("'inside'", reader.sql)
        self.assertNotIn("'queued'", reader.sql)

    def test_a_row_with_no_id_names_no_run(self):
        reader = FakeReader([{"members": "Gronk:tank:warrior:60"}])
        self.assertEqual(guildrun.inside_runs(reader), {})


if __name__ == "__main__":
    unittest.main()
