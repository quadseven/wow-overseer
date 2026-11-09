"""A campaign withheld for bag room is a town hold whatever dungeon job the family carries.

Measured on the dev realm 2026-11-08 (#2049). The Zug and Grug families had
Blackrock Depths rows waiting and carried the bare `dungeon` job. `_town_first`
withheld both runs, because no member carried dungeon:blackrock-depths and
Grug and Ugga were short of 8 free slots. `_town_first_hold` read any job
starting with "dungeon" as an armed campaign, so the vendor pass judged the
trip at the floor of 3 and logged "no vendor trip is worth taking" for the
whole wait, although Grug (6 free, 4 sellable) and Ugga (7 free, 2 sellable)
would each have reached 8 on one trip.
"""

import ast
import pathlib
import unittest

import bag_pressure
import jobs

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
NAMES = ["Bork", "Grog", "Grug", "Og", "Ugga"]


def _source(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _hold(jobs_now, keywords=("blackrock-depths",)):
    ns = {
        "_campaign_jobs": lambda names: frozenset(
            jobs.dungeon_job(k) for k in keywords
        ),
        "_jobs_of": lambda names: {n: jobs_now for n in names},
        "_PACE_QUESTERS": set(),
    }
    module = ast.Module(body=[_source("_town_first_hold")], type_ignores=[])
    exec(  # noqa: S102 - bridge.py's own source
        compile(ast.fix_missing_locations(module), "bridge.py", "exec"), ns
    )
    return ns["_town_first_hold"]


def _campaign_jobs(rows):
    """`_campaign_jobs` over a fake cursor returning `rows`."""

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, args):
            self.sql = sql

        def fetchall(self):
            return rows

    class Conn(Cursor):
        def cursor(self):
            return Cursor()

    ns = {
        "_connect": Conn,
        "_CAMPAIGN_KEYWORDS_SQL": "%s",
        "jobs": jobs,
        "pymysql": None,
    }
    module = ast.Module(body=[_source("_campaign_jobs")], type_ignores=[])
    exec(  # noqa: S102 - bridge.py's own source
        compile(ast.fix_missing_locations(module), "bridge.py", "exec"), ns
    )
    return ns["_campaign_jobs"](NAMES)


class TheBareDungeonJobIsNotTheCampaign(unittest.TestCase):
    def test_the_bare_dungeon_job_is_a_town_hold(self):
        self.assertTrue(_hold("dungeon")(NAMES))

    def test_another_dungeons_job_is_a_town_hold(self):
        self.assertTrue(_hold("dungeon:uldaman")(NAMES))

    def test_the_campaigns_own_job_is_armed(self):
        self.assertFalse(_hold("dungeon:blackrock-depths")(NAMES))

    def test_the_second_queued_campaigns_job_is_armed_too(self):
        hold = _hold(
            "dungeon:lower-blackrock-spire",
            keywords=("blackrock-depths", "lower-blackrock-spire"),
        )
        self.assertFalse(hold(NAMES))

    def test_no_campaign_waiting_is_no_hold(self):
        self.assertFalse(_hold("dungeon", keywords=())(NAMES))

    def test_the_measured_family_takes_the_trip_under_the_hold(self):
        free = {"Bork": 12, "Grog": 12, "Grug": 6, "Og": 13, "Ugga": 7}
        sellable = {"Bork": 8, "Grog": 12, "Grug": 4, "Og": 6, "Ugga": 2}
        self.assertFalse(bag_pressure.family_town_run_needed(free, sellable=sellable))
        # The trip the 8-slot band asked for; the wait is 4 slots now (#2116).
        self.assertTrue(
            bag_pressure.town_first_trip_worth(
                free, sellable, resume=bag_pressure.CAMPAIGN_RESUME_FREE_SLOTS
            )
        )


class TheCampaignJobsRead(unittest.TestCase):
    def test_each_keyword_becomes_its_dungeon_job(self):
        got = _campaign_jobs(
            [{"keyword": "blackrock-depths"}, {"keyword": "lower-blackrock-spire"}]
        )
        self.assertEqual(
            got,
            frozenset({"dungeon:blackrock-depths", "dungeon:lower-blackrock-spire"}),
        )

    def test_an_unknown_keyword_writes_no_job(self):
        self.assertEqual(_campaign_jobs([{"keyword": "atlantis"}]), frozenset())

    def test_an_empty_keyword_is_the_bare_job(self):
        self.assertEqual(_campaign_jobs([{"keyword": ""}]), frozenset({"dungeon"}))


if __name__ == "__main__":
    unittest.main()
