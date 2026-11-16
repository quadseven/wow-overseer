"""When the Watcher's order ends it must not stay inside a dungeon.

An observer left standing in an instance copy keeps the copy loaded and makes
the core refuse the group's reset (InstanceMap::Reset fails while any player,
a GM included, is inside). So the end of an order, whether cleared, lapsed or
never given after a restart, hops the Watcher out and drops its instance
binds, once, and then leaves it alone.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import director as d

W = d.WATCHER_NAME
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def spot(map_id=0, inst=0, grp=0):
    return d.Spot(W, map_id, inst, 0.0, 0.0, 0.0, False, grp)


class Retreat(unittest.TestCase):
    def test_inside_an_instance_it_hops_out_first(self):
        got = d.retreat(spot(34, 7), now=100.0)
        self.assertEqual((got.action, got.commands), (d.RETREAT, (d.HOP_COMMAND,)))

    def test_a_dungeon_map_with_no_instance_id_yet_still_counts_as_inside(self):
        got = d.retreat(spot(min(d.INSTANCE_MAPS), 0), now=100.0)
        self.assertEqual(got.commands, (d.HOP_COMMAND,))

    def test_outside_it_drops_the_binds_once(self):
        got = d.retreat(spot(0, 0), now=100.0)
        self.assertEqual((got.action, got.commands), (d.RETREAT, (d.UNBIND_COMMAND,)))
        done = d.retreat(spot(0, 0), now=200.0, unbound=True)
        self.assertEqual((done.action, done.code), (d.HOLD, d.R_AT_REST))
        self.assertEqual(done.commands, ())

    def test_an_offline_watcher_is_not_at_rest(self):
        got = d.retreat(None, now=100.0)
        self.assertEqual((got.action, got.code), (d.HOLD, d.R_WATCHER_OFFLINE))

    def test_it_waits_out_the_gap_between_moves(self):
        got = d.retreat(spot(34, 7), now=100.0, moves=[100.0 - d.MIN_APPEAR_GAP + 1])
        self.assertEqual((got.action, got.code), (d.HOLD, d.R_RATE))
        later = d.retreat(spot(34, 7), now=100.0, moves=[100.0 - d.MIN_APPEAR_GAP - 1])
        self.assertEqual(later.action, d.RETREAT)

    def test_every_line_it_queues_is_on_the_observer_allow_list(self):
        for w in (spot(34, 7), spot(0, 0)):
            self.assertTrue(d.commands_ok(d.retreat(w, now=1.0).commands))

    def test_a_grouped_watcher_is_still_moved_out(self):
        # A hop out is the way a stray group stops mattering; refusing here
        # would leave it inside for good.
        got = d.retreat(spot(34, 7, grp=9), now=100.0)
        self.assertEqual(got.commands, (d.HOP_COMMAND,))


class RestMemory(unittest.TestCase):
    def test_the_idle_check_is_spaced_out(self):
        m = d.Memory()
        self.assertTrue(m.rest_due(100.0))
        m.rest_checked(100.0)
        self.assertFalse(m.rest_due(100.0 + d.REST_CHECK_SECONDS - 1))
        self.assertTrue(m.rest_due(100.0 + d.REST_CHECK_SECONDS))

    def test_a_watcher_at_rest_is_not_checked_again(self):
        m = d.Memory()
        m.at_rest = True
        self.assertFalse(m.rest_due(10**9))

    def test_a_live_order_rearms_the_retreat(self):
        m = d.Memory(at_rest=True, unbound=True)
        m.order_active()
        self.assertEqual((m.at_rest, m.unbound), (False, False))
        self.assertTrue(m.rest_due(100.0))


class Wiring(unittest.TestCase):
    """The loop calls it. Read as text: the bridge is not imported by tests."""

    def test_an_ended_order_reaches_the_retreat(self):
        with open(os.path.join(HERE, "bridge.py"), encoding="utf8") as fh:
            src = fh.read()
        body = src[src.index("async def _watch_once") : src.index("# --- job schedule")]
        self.assertIn("_watch_rest(memory)", body)
        self.assertIn("director.retreat(", src)
        self.assertIn("memory.order_active()", body)


if __name__ == "__main__":
    unittest.main()
