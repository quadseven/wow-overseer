"""The Molten Core first-kill order that writes itself (mcorder.py).

What these pin:

  1. QUORUM MET, ORDER. Eligible seats at the quorum write the order.
  2. SHORT NAMES THE ROLE. One tank short says tanks, with the count.
  3. WAITS NAME WHAT IS AHEAD. A running campaign, an open Molten Core order
     or an order that ended inside its time box all wait.
  4. THE BRIDGE SEAM. With the flag off nothing is read or written; with it on
     the pass writes one first-kill queue row and no seat or job.
"""

import ast
import contextlib
import time
import types
import unittest

from test_raidfirstkill import _fourteen, _lineup, _rows
from test_raidrun import BRIDGE, _function

import campaignqueue
import mcorder
import raidrun
import spirerun

NOW = 1_000_000.0
QUORUM = (14, 2, 3)


def roster(drop_tank=False):
    lineup = _lineup()
    eligible = set(_fourteen(lineup))
    if drop_tank:
        tank = next(
            m["name"]
            for g in lineup["groups"]
            for m in g["members"]
            if m["role"] == "tank" and m["name"] in eligible
        )
        eligible.discard(tank)
    return raidrun.first_kill_roster(
        "moltencore", lineup, _rows(lineup, eligible), QUORUM
    )


def row(id_, keyword, status, position, source="overseer:campaign"):
    return {
        "id": id_,
        "keyword": keyword,
        "status": status,
        "position": position,
        "source": source,
    }


class TheDecision(unittest.TestCase):
    def test_quorum_met_orders(self):
        got = mcorder.decide([], None, NOW, roster(), QUORUM)
        self.assertEqual(mcorder.ORDER, got.action)
        self.assertEqual(0, got.slot.position)

    def test_one_tank_short_is_short_and_names_the_role(self):
        got = mcorder.decide([], None, NOW, roster(drop_tank=True), QUORUM)
        self.assertEqual(mcorder.SHORT, got.action)
        self.assertIn("1 tanks", got.line)
        self.assertIn("1 seats", got.line)
        self.assertNotIn("healers", got.line)

    def test_a_running_campaign_waits_and_is_named(self):
        rows = [row(1, "uldaman", "active", 0)]
        got = mcorder.decide(rows, None, NOW, roster(), QUORUM)
        self.assertEqual(mcorder.WAIT, got.action)
        self.assertIn("uldaman", got.line)

    def test_an_open_order_waits(self):
        rows = [row(1, "moltencore", "queued", 0, mcorder.SOURCE)]
        got = mcorder.decide(rows, None, NOW, roster(), QUORUM)
        self.assertEqual(mcorder.WAIT, got.action)

    def test_an_order_that_ended_inside_the_time_box_waits(self):
        last = spirerun.Last(NOW - 3600, False)
        got = mcorder.decide([], last, NOW, roster(), QUORUM)
        self.assertEqual(mcorder.WAIT, got.action)
        self.assertIn("did not clear", got.line)
        later = spirerun.Last(NOW - spirerun.AFTER_FAILURE_SECONDS - 1, False)
        self.assertEqual(
            mcorder.ORDER, mcorder.decide([], later, NOW, roster(), QUORUM).action
        )

    def test_the_flag_is_off_unless_set(self):
        self.assertFalse(mcorder.enabled({}))
        self.assertFalse(mcorder.enabled({mcorder.ENV: "0"}))
        self.assertTrue(mcorder.enabled({mcorder.ENV: "1"}))

    def test_the_order_row_is_a_first_kill_row(self):
        self.assertIn("first_kill", mcorder.ORDER_SQL)
        self.assertIn("first_kill", campaignqueue.FIRST_KILL_INSERT_SQL)


def load_pass(enabled, rows_of_roster):
    source = "\n\n".join(
        ast.get_source_segment(BRIDGE, _function(name))
        for name in ("_mc_say", "_mc_family")
    )
    sql = []

    class Cursor:
        rowcount = 1

        def execute(self, text, args=()):
            sql.append((text, args))

        def fetchone(self):
            return None

    class Conn:
        def cursor(self):
            return contextlib.nullcontext(Cursor())

    class Log:
        def info(self, *a, **k):
            pass

        warning = info

    on = types.SimpleNamespace(
        enabled=lambda: enabled,
        waiting=mcorder.waiting,
        decide=mcorder.decide,
        LAST_SQL=mcorder.LAST_SQL,
        ORDER_SQL=mcorder.ORDER_SQL,
        KEYWORD=mcorder.KEYWORD,
        SOURCE=mcorder.SOURCE,
        ORDER=mcorder.ORDER,
    )
    namespace = {
        "mcorder": on,
        "spirerun": spirerun,
        "raidrun": raidrun,
        "campaignqueue": campaignqueue,
        "time": time,
        "log": Log(),
        "_MC_SAID": {},
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "_mc_roster": lambda family, names: rows_of_roster,
    }
    exec(compile(source, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace["_mc_family"], sql


class TheBridgeSeam(unittest.TestCase):
    def test_flag_off_writes_and_reads_nothing(self):
        run, sql = load_pass(False, roster())
        self.assertFalse(run("Grug", {"names": ["Grug"]}, []))
        self.assertEqual([], sql)

    def test_flag_on_writes_one_first_kill_row_and_no_seat_or_job(self):
        run, sql = load_pass(True, roster())
        self.assertTrue(run("Grug", {"names": ["Grug"]}, []))
        writes = [(t, a) for t, a in sql if t.startswith("INSERT")]
        self.assertEqual(1, len(writes))
        text, args = writes[0]
        self.assertIn("overseer_dungeon_queue", text)
        self.assertIn("first_kill", text)
        self.assertEqual("moltencore", args[2])
        self.assertFalse(any("overseer_raid_seat" in t for t, _ in sql))

    def test_flag_on_but_short_writes_nothing(self):
        run, sql = load_pass(True, roster(drop_tank=True))
        self.assertFalse(run("Grug", {"names": ["Grug"]}, []))
        self.assertEqual([], [t for t, _ in sql if t.startswith("INSERT")])


if __name__ == "__main__":
    unittest.main()
