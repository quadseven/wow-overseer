"""The site's reads of overseer_guild_run, owned by guildrun (#734).

Six SQL strings in map_server and apiv2 read the table, two of them a copy of
one 28-column list, and the app worked out a run's state from `state`,
`status` or `outcome`. Now guildrun owns the column list, every read, the run
view and its stories, and the view pins one state field, `run_state`.

The reader here is a fake cursor that answers only the reads it was given:
any other statement fails the test, so a renamed or extra read cannot pass
by reading nothing.
"""

import datetime
import pathlib
import re
import shutil
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import guildrun  # noqa: E402
from test_measured_views import render  # noqa: E402

FORMED = datetime.datetime(2026, 10, 8, 10, 0, 0)

ROW = {
    "id": 398,
    "guild": "Cave",
    "band": "20-25",
    "composition": "spec-tank/spec-healer",
    "keyword": "deadmines",
    "tank": "Grug",
    "members": "Grug:tank:warrior:24,Ugga:healer:priest:23,Og:damage:mage:23",
    "dungeon_by": "heuristic",
    "dungeon_jev": None,
    "dungeon_confidence": None,
    "composition_by": "heuristic",
    "composition_jev": None,
    "composition_confidence": None,
    "prior_rate": None,
    "prior_runs": 0,
    "state": "ended",
    "outcome": "wiped",
    "why": "the group wiped",
    "deaths": 3,
    "seconds_inside": 1500,
    "bosses_done": 2,
    "bosses_total": 7,
    "loot_items": 4,
    "loot_notable": "",
    "ilvl_gained": 0,
    "levels_gained": 0,
    "created_at": FORMED,
    "ended_at": FORMED + datetime.timedelta(minutes=30),
    "created_unix": 1791453600,
    "ended_unix": 1791455400,
}

DEATH = {
    "character_name": "Grug",
    "level": 24,
    "map": 36,
    "zone": 1581,
    "killer_name": "Rhahk'Zor",
    "killer_type": "creature",
    "killer_entry": 644,
    "created_at": FORMED + datetime.timedelta(minutes=20),
}


class Missing(Exception):
    """What the driver raises for a table this world does not have."""

    def __init__(self):
        super().__init__(1146, "Table 'overseer_guild_run' doesn't exist")


class NoColumn(Exception):
    """What the driver raises for a column this world's table does not have."""

    def __init__(self):
        super().__init__(1054, "Unknown column 'proposer' in 'field list'")


class Reader:
    """A cursor that answers only the reads it was given.

    `answers` maps a fragment of a statement to the rows it returns (or an
    exception it raises). A statement no fragment matches fails the test."""

    def __init__(self, answers):
        self.answers = answers
        self.reads = []
        self._rows = []

    def execute(self, sql, params=()):
        for fragment, rows in self.answers.items():
            if fragment in sql:
                self.reads.append((fragment, sql, tuple(params)))
                if callable(rows):
                    rows = rows(sql)
                if isinstance(rows, Exception):
                    raise rows
                self._rows = [dict(r) for r in rows]
                return
        raise AssertionError("a read nobody expected: " + sql)

    def fetchall(self):
        return self._rows

    def read(self, fragment):
        return [r for r in self.reads if r[0] == fragment]


RUNS = "FROM overseer_guild_run"
DEATHS = "FROM overseer_death"
BOSSES = "SELECT DISTINCT creditEntry"
LEVELS = "MAX(ct.maxlevel)"


def story_reads(deaths=(DEATH,)):
    return {
        DEATHS: list(deaths),
        BOSSES: [{"creditEntry": 644}],
        LEVELS: [{"map_id": 36, "level": 20}],
    }


class TheRunState(unittest.TestCase):
    """One field says where a run is: queued, inside, or how it came back."""

    def state_of(self, **row):
        return guildrun.run_view(dict(ROW, **row))["run_state"]

    def test_a_run_in_flight_is_its_state(self):
        self.assertEqual(self.state_of(state="queued", outcome=""), "queued")
        self.assertEqual(self.state_of(state="inside", outcome=""), "inside")

    def test_a_run_that_came_back_is_its_outcome(self):
        self.assertEqual(self.state_of(state="ended", outcome="cleared"), "cleared")
        self.assertEqual(self.state_of(state="ended", outcome="wiped"), "wiped")
        self.assertEqual(
            self.state_of(state="ended", outcome="not entered"), "not entered"
        )

    def test_an_ended_run_without_a_known_outcome_is_lost(self):
        # The bridge's own rule (outcome_from_row): no known outcome is lost.
        self.assertEqual(self.state_of(state="ended", outcome=""), "lost")
        self.assertEqual(self.state_of(state="ended", outcome="sweep"), "lost")

    def test_the_old_fields_stay_for_compatibility(self):
        view = guildrun.run_view(dict(ROW))
        self.assertEqual(
            (view["state"], view["outcome"], view["status"]),
            ("ended", "wiped", "wiped"),
        )

    def test_the_board_carries_it_on_both_lists(self):
        page = guildrun.page([dict(ROW, id=2, state="inside", outcome=""), ROW])
        self.assertEqual(page["active"][0]["run_state"], "inside")
        self.assertEqual(page["recent"][0]["run_state"], "wiped")


class OneRunById(unittest.TestCase):
    def test_an_ended_run_is_its_view_with_its_story(self):
        reader = Reader({RUNS: [ROW], **story_reads()})
        run = guildrun.by_id(reader, 398)
        self.assertEqual(run["id"], 398)
        self.assertEqual(run["title"], "Cave - The Deadmines")
        self.assertEqual(run["members"][0]["name"], "Grug")
        self.assertEqual(run["run_state"], "wiped")
        self.assertIn("Rhahk'Zor", run["story"])
        ((_f, _sql, params),) = reader.read(RUNS)
        self.assertEqual(params[0], 398)

    def test_a_run_still_inside_reads_no_story(self):
        # Only the run is answered: a deaths read would fail the test.
        reader = Reader({RUNS: [dict(ROW, state="inside", outcome="")]})
        run = guildrun.by_id(reader, 398)
        self.assertEqual(run["run_state"], "inside")
        self.assertNotIn("story", run)

    def test_an_id_the_table_does_not_hold_is_none(self):
        self.assertIsNone(guildrun.by_id(Reader({RUNS: []}), 12345))

    def test_a_world_without_the_table_holds_no_run(self):
        self.assertIsNone(guildrun.by_id(Reader({RUNS: Missing()}), 398))

    def test_any_other_fault_reaches_the_caller(self):
        with self.assertRaises(ConnectionError):
            guildrun.by_id(Reader({RUNS: ConnectionError("gone")}), 398)


class TheRecentRuns(unittest.TestCase):
    def test_one_guilds_runs_newest_first_bounded(self):
        older = dict(ROW, id=397)
        reader = Reader({RUNS: [ROW, older]})
        rows = guildrun.recent(reader, guild="Cave", n=5000)
        self.assertEqual([r["id"] for r in rows], [398, 397])
        ((_f, sql, params),) = reader.read(RUNS)
        self.assertEqual(params, ("Cave", 5000))
        self.assertIn("WHERE guild = %s", sql)
        self.assertIn("ORDER BY id DESC LIMIT %s", sql)

    def test_every_guilds_runs_by_default_thirty(self):
        reader = Reader({RUNS: [ROW]})
        guildrun.recent(reader)
        ((_f, sql, params),) = reader.read(RUNS)
        self.assertEqual(params, (30,))
        self.assertNotIn("guild =", sql)

    def test_rows_carry_unix_times_from_the_database_clock(self):
        reader = Reader({RUNS: [ROW]})
        guildrun.recent(reader)
        ((_f, sql, _p),) = reader.read(RUNS)
        self.assertIn("UNIX_TIMESTAMP(created_at) AS created_unix", sql)
        self.assertIn("UNIX_TIMESTAMP(ended_at) AS ended_unix", sql)

    def test_a_world_without_the_table_has_none(self):
        self.assertEqual(guildrun.recent(Reader({RUNS: Missing()})), [])


class WhoAsked(unittest.TestCase):
    """A run formed from a guild-chat ask names its asker (`proposer`)."""

    def test_the_asker_is_read_and_named(self):
        asked = dict(ROW, proposer="Durg", dungeon_by=guildrun.ASKED, state="inside")
        reader = Reader({RUNS: [asked]})
        run = guildrun.by_id(reader, 398)
        self.assertEqual(run["lines"][0], "dungeon: Durg asked for it in guild chat")
        ((_f, sql, _p),) = reader.read(RUNS)
        self.assertIn("proposer", sql)

    def test_a_table_without_the_column_reads_the_rest(self):
        def answer(sql):
            return NoColumn() if "proposer" in sql else [ROW]

        reader = Reader({RUNS: answer})
        self.assertEqual([r["id"] for r in guildrun.recent(reader)], [398])
        first, thin = reader.read(RUNS)
        self.assertIn("proposer", first[1])
        self.assertNotIn("proposer", thin[1])
        self.assertEqual(first[2], thin[2])


class TheOtherReads(unittest.TestCase):
    def test_runs_by_their_ids(self):
        reader = Reader({RUNS: [ROW]})
        self.assertEqual([r["id"] for r in guildrun.by_ids(reader, [398, 12])], [398])
        ((_f, sql, params),) = reader.read(RUNS)
        self.assertIn("WHERE id IN (%s, %s)", sql)
        self.assertEqual(params[:2], (398, 12))

    def test_no_ids_is_no_read(self):
        self.assertEqual(guildrun.by_ids(Reader({}), []), [])

    def test_the_runs_that_came_back_from_inside(self):
        reader = Reader({RUNS: [ROW]})
        guildrun.came_back(reader, ["Cave", "Bonkers"], days=7, n=200)
        ((_f, sql, params),) = reader.read(RUNS)
        self.assertIn("guild IN (%s, %s)", sql)
        self.assertIn("ended_at >= NOW() - INTERVAL %s DAY", sql)
        self.assertEqual(params, ("Cave", "Bonkers", 7, *guildrun.WENT_IN, 200))

    def test_runs_matching_a_search(self):
        reader = Reader({RUNS: [ROW]})
        guildrun.matching(reader, ["deadmines"], "%grug%", 40)
        ((_f, sql, params),) = reader.read(RUNS)
        self.assertIn("keyword IN (%s) OR LOWER(members) LIKE %s", sql)
        self.assertEqual(params, ("deadmines", "%grug%", 40))

    def test_a_search_with_no_dungeon_reads_members_only(self):
        reader = Reader({RUNS: []})
        guildrun.matching(reader, [], "%grug%", 40)
        ((_f, sql, params),) = reader.read(RUNS)
        self.assertNotIn("keyword IN", sql)
        self.assertEqual(params, ("%grug%", 40))


class TheStories(unittest.TestCase):
    def setUp(self):
        guildrun._BOSS_LEVELS.clear()
        self.addCleanup(guildrun._BOSS_LEVELS.clear)

    def test_ended_runs_get_a_story_and_runs_out_do_not(self):
        out = dict(ROW, id=399, state="inside", outcome="")
        runs = [guildrun.run_view(ROW), guildrun.run_view(out)]
        reader = Reader(story_reads())
        self.assertIs(guildrun.with_stories(reader, runs), runs)
        self.assertIn("Rhahk'Zor", runs[0]["story"])
        self.assertTrue(runs[0]["cause"])
        self.assertEqual(runs[1]["story"], "")

    def test_only_the_members_deaths_inside_the_window_are_read(self):
        reader = Reader(story_reads())
        guildrun.with_stories(reader, [guildrun.run_view(ROW)])
        ((_f, _sql, params),) = reader.read(DEATHS)
        self.assertEqual(params[:3], ("Grug", "Og", "Ugga"))
        self.assertEqual(params[3], FORMED)

    def test_the_bosses_level_is_read_once_and_logged(self):
        reader = Reader(story_reads())
        with self.assertLogs("wow-map", "INFO") as logs:
            guildrun.with_stories(reader, [guildrun.run_view(ROW)])
        guildrun.with_stories(reader, [guildrun.run_view(ROW)])
        self.assertEqual(len(reader.read(LEVELS)), 1)
        self.assertIn("the Deadmines' 20", logs.output[0])

    def test_no_runs_read_nothing(self):
        self.assertEqual(guildrun.with_stories(Reader({}), []), [])

    def test_an_empty_bosses_level_read_is_tried_again(self):
        reader = Reader(dict(story_reads(), **{LEVELS: []}))
        guildrun.with_stories(reader, [guildrun.run_view(ROW)])
        guildrun.with_stories(reader, [guildrun.run_view(ROW)])
        self.assertEqual(len(reader.read(LEVELS)), 2)

    def test_a_raw_row_is_told_the_same_as_its_view(self):
        row = {
            k: ROW[k]
            for k in (
                "id",
                "state",
                "outcome",
                "members",
                "keyword",
                "why",
                "deaths",
                "seconds_inside",
                "bosses_done",
                "bosses_total",
                "created_at",
                "ended_at",
            )
        }
        view = guildrun.run_view(ROW)
        guildrun.with_stories(Reader(story_reads()), [row])
        guildrun.with_stories(Reader(story_reads()), [view])
        self.assertEqual(row["story"], view["story"])


SITE = [HERE / "map_server.py", *sorted((HERE / "apiv2").glob("*.py"))]


class OneOwner(unittest.TestCase):
    def test_no_site_module_but_guildrun_reads_the_table(self):
        readers = [
            p.name
            for p in SITE
            if re.search(r"FROM\s+overseer_guild_run\b", p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(readers, [])

    def test_the_column_list_is_written_once(self):
        found = [
            p.name
            for p in [HERE / "guildrun.py", *SITE]
            if "composition_confidence, prior_rate, prior_runs"
            in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(found, ["guildrun.py"])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheAppReadsThePinnedState(unittest.TestCase):
    def test_a_run_card_says_its_run_state(self):
        # The old fields disagree with run_state here: only run_state is read.
        got = render(
            "views/_runs.js",
            """
console.log(JSON.stringify([
  M.runState({run_state: "lost", state: "ended", outcome: "", status: ""}).text,
  M.runState({run_state: "inside", state: "queued", status: "queued"}).text,
  M.runState({run_state: "cleared", state: "ended", outcome: ""}).tone,
]));""",
        )
        self.assertEqual(got, ["lost", "inside now", "ok"])

    def test_the_now_page_counts_runs_inside_by_run_state(self):
        got = render(
            "views/now/data.js",
            """
const read = {data: {active: [
  {id: 1, run_state: "inside", state: "queued", status: "queued"},
  {id: 2, run_state: "queued", state: "inside", status: "inside"},
]}, at: 1, error: null};
console.log(JSON.stringify(M.runsInside(read).map((r) => r.id)));""",
        )
        self.assertEqual(got, [1])

    def test_a_search_hit_says_its_run_state(self):
        got = render(
            "searchv2.js",
            """
const run = {id: 7, place: "The Deadmines", guild: "Cave", run_state: "lost",
  state: "ended", outcome: "", bosses_total: 0, when: "2026-10-09 19:00:00"};
const runs = M.groups({runs: [run]}).find((g) => g.label === "Runs");
console.log(JSON.stringify(runs.rows[0].sub));""",
        )
        self.assertEqual(got, "Cave | lost | 2026-10-09 19:00")


if __name__ == "__main__":
    unittest.main()
