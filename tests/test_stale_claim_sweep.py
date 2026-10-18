"""The stale-claim sweep leaves a guild run's row to the module that owns it.

`_expire_stale_claims` turns every 'verifying' row older than
CLAIM_STALE_SECONDS into an error. That is right for a read-back the module
lost at a restart, and wrong for a guild run's `finder-run` row: that row stays
'verifying' for the whole run (an hour or more on the dev realm on 2026-10-10)
and the module re-adopts it from the table after a worldserver restart
(mod-overseer #896), touching it only once while the members log back in, which
can take fifteen minutes. A sweep in that window errors a run the module is
still driving; the module's own write-back is guarded on 'verifying' and then
writes nothing, so the bridge counts the run lost while its five members stay
in the dungeon's group.
"""

import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

from unittest import mock  # noqa: E402

from test_guildsocial_bridge import _Conn, bridge  # noqa: E402


def _sweep():
    sql = []
    with mock.patch.object(bridge, "_connect", lambda: _Conn(sql)):
        bridge._expire_stale_claims(300)
    return sql


class TheSweepSparesGuildRuns(unittest.TestCase):
    def test_the_verifying_sweep_spares_finder_run_rows(self):
        verifying = [s for s, _a in _sweep() if "status = 'verifying'" in s]
        self.assertEqual(len(verifying), 1)
        self.assertIn(
            "AND NOT (kind = 'guild' AND command LIKE 'finder-run %%')",
            verifying[0],
        )

    def test_the_claimed_sweep_is_unchanged(self):
        claimed = [s for s, _a in _sweep() if "status = 'claimed'" in s]
        self.assertEqual(len(claimed), 1)
        self.assertNotIn("finder-run", claimed[0])

    def test_both_sweeps_still_take_the_window(self):
        self.assertEqual([a[-1] for _s, a in _sweep()], [300, 300])


class TheSweepSaysItWasARestart(unittest.TestCase):
    """#789: only a worldserver that is gone leaves a row claimed or verifying
    this long, so both details start with the restart word and a pass that
    backs off a refusal asks again instead."""

    def test_both_details_start_with_restart(self):
        details = [a[0] for _s, a in _sweep()]
        self.assertEqual(len(details), 2)
        for detail in details:
            with self.subTest(detail=detail):
                self.assertTrue(detail.startswith("restart: "))
                self.assertTrue(bridge.core.ended_by_restart("error", detail))
                self.assertLessEqual(len(detail), 255)

    def test_the_details_are_bound_not_inlined(self):
        for sql, _a in _sweep():
            with self.subTest(sql=sql):
                self.assertIn("detail = %s ", sql)

    def test_a_refusal_is_not_a_restart(self):
        import core

        self.assertFalse(core.ended_by_restart("error", "not a retirable bot"))
        self.assertFalse(core.ended_by_restart("error", None))
        self.assertFalse(core.ended_by_restart("applied", "restart: claim expired"))
        self.assertTrue(core.ended_by_restart("error", "restart: claim expired"))


if __name__ == "__main__":
    unittest.main()
