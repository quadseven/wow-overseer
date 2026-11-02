"""The bridge side of the quest filing loop's first wait (#1720)."""

import time
import types
import unittest
from unittest import mock

from test_guildsocial_bridge import bridge

DAY = 86400.0


class DatabaseError(Exception):
    pass


class TheFirstPassWait(unittest.TestCase):
    def patched(self, read):
        return (
            mock.patch.object(
                bridge.pymysql,
                "err",
                types.SimpleNamespace(MySQLError=DatabaseError),
                create=True,
            ),
            mock.patch.object(bridge, "_read_last_quest_tickets_pass", read),
        )

    def test_an_unreadable_pass_time_holds_the_first_pass_a_full_cycle(self):
        # Elder on #1726: a sick database is no proof that no pass ran today.
        def read():
            raise DatabaseError("database unavailable")

        err, reader = self.patched(read)
        with err, reader, self.assertLogs(bridge.log, "ERROR"):
            self.assertEqual(bridge._quest_tickets_first_delay(DAY), DAY)

    def test_no_pass_recorded_waits_only_the_startup(self):
        err, reader = self.patched(lambda: None)
        with err, reader:
            self.assertEqual(bridge._quest_tickets_first_delay(DAY), 300.0)

    def test_a_pass_an_hour_ago_waits_the_rest_of_the_day(self):
        err, reader = self.patched(lambda: time.time() - 3600.0)
        with err, reader:
            delay = bridge._quest_tickets_first_delay(DAY)
        self.assertAlmostEqual(delay, DAY - 3600.0, delta=5.0)


if __name__ == "__main__":
    unittest.main()
