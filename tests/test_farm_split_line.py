"""The farm pass says why an individual family under the loop is not walked (#2498).

A family in the profession loop that is not gathering holds the farm orders
its members' own skills chose. The family-wide pass used to call that
"split across jobs ... until every member holds the same order" every pass,
which reads as a fault and is the wrong remedy: the members are meant to
differ, and the loop's gather phase is what walks them.
"""

import asyncio
import os
import types
import unittest
from unittest import mock

from test_family_crafting import FAKE_ASYNCIO, _load, _Log

import individual
import jobs
import profloop

ROWS = {
    "Ugga": "farm:herbalism",
    "Grug": "farm:mining",
    "Grog": "farm:mining",
    "Bork": "farm:2318",
    "Og": "farm:2318",
}
ENV = {individual.ENV: "Grug"}


def _run(phase, family="Grug", rows=ROWS, looped=True):
    log = _Log()
    ns = _load(
        ["_farm_job_now"],
        {
            "asyncio": FAKE_ASYNCIO,
            "individual": individual,
            "jobs": jobs,
            "log": log,
            "profloop": profloop,
            "farmjob": types.SimpleNamespace(in_reach=lambda seen, leader: []),
            "_standing_jobs": lambda key=None: dict(rows),
            "_family_leader": lambda c=None: "Grug",
            "_fetch_positions": lambda names: {},
            "_individual_family": lambda c=None: family,
            "_prof_loop_family": lambda key=None: "Grug" if looped else "",
            "_PROF_LOOPS": {"Grug": profloop.State(phase=phase)},
        },
    )
    me = types.SimpleNamespace(_farm_state={})
    cohort = types.SimpleNamespace(key="Grug", solo=False, leader="Grug")
    with mock.patch.dict(os.environ, ENV):
        got = asyncio.run(ns["_farm_job_now"](me, cohort))
    return got, log.lines


class TheSplitLineIsTruthful(unittest.TestCase):
    def test_a_looped_individual_family_outside_gather_names_the_loop(self):
        for phase in (profloop.TOWN, profloop.CRAFT, profloop.TRAIN):
            got, lines = _run(phase)
            self.assertIsNone(got)
            self.assertEqual(len(lines), 1)
            self.assertIn("profession loop", lines[0])
            self.assertIn(phase, lines[0])
            self.assertNotIn("until every member holds the same order", lines[0])

    def test_a_family_with_no_loop_keeps_the_old_line(self):
        got, lines = _run(profloop.TOWN, looped=False)
        self.assertIsNone(got)
        self.assertIn("until every member holds the same order", lines[0])

    def test_a_family_not_named_individual_keeps_the_old_line(self):
        got, lines = _run(profloop.TOWN, family="Zug")
        self.assertIsNone(got)
        self.assertIn("until every member holds the same order", lines[0])


if __name__ == "__main__":
    unittest.main()
