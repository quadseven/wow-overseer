"""A junk sale that is not served does not end the supply trip (ticket 2621).

Read on the dev realm: supply walks kept arriving at the vendor after the guild
loot policy landed, yet the buy rows after them stopped being written. The trip
opens with sell rows for junk; the policy refuses a sell row for a stack it
files for another route, and a refused row is not written, so `_run_step_row`
answered False and `_run_job_step` ended the step before the first buy.
"""

import asyncio
import unittest

import guildjobs
import restsupply
from test_guildsocial_bridge import bridge
from test_classquest_follow_up import _Loop


def row(kind, command):
    return guildjobs.guildcorps.Row(kind, command, "", "guildjobs:supply:Femur")


def step_of(action=restsupply.ACTION):
    rows = (
        row("sell", "guid:1"),
        row("sell", "guid:2"),
        row("buy", "entry:8950 count:4 max:2000"),
        row("buy", "entry:8950 count:4 max:2000"),
    )
    return guildjobs.guildcorps.Step("Femur", action, 8950, "Femur buys", rows=rows)


def run(step, refused):
    loop = _Loop()
    ran = []

    async def one(this_step, this_row, cap):
        ran.append(this_row.command)
        return this_row.command not in refused

    loop._run_step_row = one
    asyncio.run(loop._run_job_step(step, 5000.0))
    return ran


class TheTripGoesOn(unittest.TestCase):
    def test_a_refused_sale_leaves_the_buys_to_run(self):
        ran = run(step_of(), {"guid:1", "guid:2"})
        self.assertEqual(ran.count("entry:8950 count:4 max:2000"), 2, ran)

    def test_a_refused_buy_still_ends_the_trip(self):
        ran = run(step_of(), {"entry:8950 count:4 max:2000"})
        self.assertEqual(ran.count("entry:8950 count:4 max:2000"), 1, ran)

    def test_another_step_still_ends_at_a_refused_sale(self):
        ran = run(step_of("gear"), {"guid:1"})
        self.assertEqual(ran, ["guid:1"])


if __name__ == "__main__":
    unittest.main()
