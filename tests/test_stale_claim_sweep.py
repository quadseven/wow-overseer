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
        self.assertEqual([a for _s, a in _sweep()], [(300,), (300,)])


if __name__ == "__main__":
    unittest.main()
