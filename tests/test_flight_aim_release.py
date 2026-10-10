"""A flight aim the bridge has given up on, or no longer remembers, is cleared.

The bridge counts discovery walks in memory (`_flight_attempts`). Two things
left the aim standing in `travel_npc` after that count stopped mattering: a node
given up on after FLIGHT_LEARN_ATTEMPTS walks, and a bridge restart that
forgot the count while the aim was still in the column. The module walked it
again either way. Refs #816.
"""

import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

from unittest import mock  # noqa: E402

from test_guildsocial_bridge import _Conn, bridge  # noqa: E402


def _bare():
    b = object.__new__(bridge.Bridge)
    b._flight_attempts = {}
    b._flight_aims_swept = False
    return b


class TheAimIsClearedByCompareAndSwap(unittest.TestCase):
    def test_release_names_the_exact_aim(self):
        sql = []
        with mock.patch.object(bridge, "_connect", lambda: _Conn(sql)):
            self.assertTrue(bridge._release_flight_aim("Grug", 40))
        text, args = sql[0]
        self.assertIn("SET travel_npc = ''", text)
        self.assertIn("travel_npc = %s", text)
        self.assertEqual(args, ("Grug", "flight master:40"))

    def test_release_of_any_flight_aim_after_a_restart(self):
        sql = []
        with mock.patch.object(bridge, "_connect", lambda: _Conn(sql)):
            bridge._release_any_flight_aim("Grug")
        text, args = sql[0]
        self.assertIn("travel_npc LIKE %s", text)
        self.assertEqual(args, ("Grug", "flight master:%"))


class TheGivenUpNodesAreReleased(unittest.TestCase):
    def test_a_spent_node_loses_its_aim(self):
        b = _bare()
        b._flight_aims_swept = True
        b._flight_attempts = {
            40: (bridge.FLIGHT_LEARN_ATTEMPTS, None),
            41: (1, None),
        }
        with mock.patch.object(bridge, "_release_flight_aim") as rel:
            b._release_spent_flight_aims("Grug")
        rel.assert_called_once_with("Grug", 40)

    def test_a_fresh_process_clears_whatever_flight_aim_stands_once(self):
        b = _bare()
        with mock.patch.object(bridge, "_release_any_flight_aim") as rel:
            b._release_spent_flight_aims("Grug")
            b._release_spent_flight_aims("Grug")
        rel.assert_called_once_with("Grug")


if __name__ == "__main__":
    unittest.main()
