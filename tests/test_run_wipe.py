"""A party wiping inside a live guild run is a run wipe, counted and labelled.

Measured on the dev realm on 2026-11-18: five level 60 members of one guild
died 28 times in 83 minutes to Scholomance trash inside one guild run that was
still going. The death-loop reader listed them as "Dying in Scholomance", the
same line as a lone bot that keeps walking into a zone. They are still stuck, so
they are still counted, but the cause is the run's and the reader names it:
"run wipe (run N)", its own kind, its own line in the digest.
"""

import inspect
import pathlib
import sys
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    HERE = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    import deathloop
    import guildrun
    from apiv2 import health, members


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    from _stub_modules import fresh_import

    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()

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
    {"name": "Brann", "level": 60, "guild": "Cave", "rank": 3},
]


def roster(rows, run_of=None):
    readings = {
        "Grug": {"online": True, "life": "alive", "fresh_at": NOW},
        "Clunk": {"online": True, "life": "alive", "fresh_at": NOW},
        "Brann": {"online": True, "life": "alive", "fresh_at": NOW},
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

    def test_a_run_that_clears_is_untouched_on_the_next_pass(self):
        runs = {"Clunk": RUN, "Brann": RUN}
        self.assertEqual(list(deathloop.run_step_downs(self.tagged(runs))), [RUN])
        # Next pass: the run cleared, so only one member still has the deaths
        # of a loop and the other has none in the window.
        rows = [dict(d, name="Clunk") for d in five()]
        found = deathloop.tag_runs(deathloop.loops(rows, {n: 60 for n in runs}), runs)
        self.assertEqual(list(found), ["Clunk"])
        self.assertEqual(deathloop.run_step_downs(found), {})
        # And once no member dies at all, nothing is grouped.
        cleared = deathloop.tag_runs(deathloop.loops([], {n: 60 for n in runs}), runs)
        self.assertEqual(deathloop.run_step_downs(cleared), {})

    def test_two_runs_are_judged_apart(self):
        found = self.tagged({"Clunk": RUN, "Brann": RUN + 1})
        self.assertEqual(deathloop.run_step_downs(found), {})
        self.assertEqual(deathloop.run_step_downs(None), {})

    def test_threshold_run_is_abandoned_once_and_its_members_get_the_escape(self):
        rows = []
        names = ("Clunk", "Brann")
        for name in names:
            rows.extend(dict(d, name=name) for d in five())
        run_rows = [
            {"id": RUN, "members": "Clunk:tank:warrior:60,Brann:healer:priest:60"}
        ]
        decisions = bridge._run_wipe_decisions(run_rows, rows, {n: 60 for n in names})
        persisted = {"state": "inside", "outcome": "", "why": ""}

        class Cursor:
            rowcount = 0

            def execute(self, sql, params=()):
                if "UPDATE overseer_guild_run" not in sql:
                    raise AssertionError(sql)
                reason, run_id = params
                if run_id == RUN and persisted["state"] == "inside":
                    persisted.update(state="ended", outcome="abandoned", why=reason)
                    self.rowcount = 1
                else:
                    self.rowcount = 0

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Connection:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with (
            mock.patch.object(bridge, "_connect", Connection),
            mock.patch.object(bridge.log, "info") as logged,
        ):
            first = bridge._write_run_wipe_stepdowns(decisions)
            second = bridge._write_run_wipe_stepdowns(decisions)

        self.assertEqual([step.run for step in first], [RUN])
        self.assertEqual(second, [])
        self.assertEqual(persisted["state"], "ended")
        self.assertEqual(persisted["outcome"], "abandoned")
        self.assertEqual(persisted["why"], first[0].reason())
        self.assertEqual(logged.call_count, 1)
        self.assertIn("stepped down", logged.call_args.args[0])

        keyword = next(
            key
            for key, door in bridge.campaignplan.BY_KEYWORD.items()
            if int(door.map_id) == MAP
        )

        class CandidateCursor:
            rows = []

            def execute(self, sql, params=()):
                if "SELECT id, keyword, members, why FROM overseer_guild_run" in sql:
                    self.rows = [
                        {
                            "id": RUN,
                            "keyword": keyword,
                            "members": run_rows[0]["members"],
                            "why": persisted["why"],
                        }
                    ]
                elif "SELECT members FROM overseer_guild_run WHERE state IN" in sql:
                    self.rows = []
                elif "SELECT leader_name, members FROM overseer_dungeon_run" in sql:
                    self.rows = []
                elif "FROM overseer_snapshot s JOIN characters c" in sql:
                    self.rows = [
                        {
                            "name": name,
                            "map_id": MAP,
                            "health": 100,
                            "in_combat": 0,
                            "group_leader": 0,
                            "has_corpse": 0,
                        }
                        for name in names
                    ]
                elif "FROM overseer_command WHERE kind = 'hearth'" in sql:
                    self.rows = []
                else:
                    raise AssertionError(sql)

            def fetchall(self):
                return list(self.rows)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class CandidateConnection:
            def cursor(self):
                return CandidateCursor()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch.object(bridge, "_connect", CandidateConnection):
            candidates = bridge._run_wipe_escape_candidates()
        self.assertEqual({row["name"] for row in candidates}, set(names))
        escapes = [
            bridge._run_wipe_escape_step(row["run"], row["name"], row["reason"])
            for row in candidates
        ]
        self.assertEqual({step.holder for step in escapes}, set(names))
        for escape in escapes:
            self.assertEqual(escape.rows[0].kind, "hearth")
            self.assertEqual(escape.rows[0].command, "use")
            self.assertEqual(
                escape.rows[0].source,
                "guildjobs:hearth:" + escape.holder,
            )

        active_view = members.stuck_view(roster(rows, {name: RUN for name in names}))
        self.assertEqual(active_view["digest"]["run_wipes"], len(names))
        stepped_down_view = members.stuck_view(roster(rows, {}))
        self.assertEqual(stepped_down_view["digest"]["run_wipes"], 0)
        self.assertEqual(
            {row["kind"] for row in stepped_down_view["members"]}, {"death-loop"}
        )
        quiet_rows = [
            dict(row, age=row["age"] + deathloop.QUIET_SECONDS + 1) for row in rows
        ]
        quiet_view = members.stuck_view(roster(quiet_rows, {}))
        self.assertEqual(quiet_view["digest"]["count"], 0)

        loop_source = inspect.getsource(bridge.Bridge._guild_run_loop)
        self.assertIn("self._start_run_wipe_escapes(escapes)", loop_source)


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
