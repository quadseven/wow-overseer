"""The current-goal banner words an Idle member as the roster does (#2192)."""

import pathlib
import sys
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    import nowstatus
    import realmread
    from apiv2 import members
    from test_members_v2 import FakeConn

NOW_AT = 1_800_000_000
IDLE = {"doing": "Idle", "waiting": "no errand and no hold found", "line": "Idle."}


def session(level, leveled_at=None):
    leveled = [{"name": "Grug", "at": leveled_at}] if leveled_at else []
    rules = [
        (("FROM characters",), [{"name": "Grug", "level": level}]),
        (("overseer_level",), leveled),
        (("UNIX_TIMESTAMP() AS now_at",), [{"now_at": NOW_AT}]),
    ]
    return realmread.Session(lambda: FakeConn(rules, []))


class TheBannerReread(unittest.TestCase):
    def test_a_low_member_with_no_level_for_a_day_reads_stalled(self):
        with session(30) as rd:
            got = members.reread_idle(rd, "Grug", dict(IDLE, stalled_s=None))
        self.assertEqual(got["doing"], nowstatus.STALLED)
        self.assertEqual(got["stalled_s"], nowstatus.STALL_SECONDS)

    def test_a_member_that_just_leveled_reads_own_play(self):
        with session(30, NOW_AT - 600) as rd:
            got = members.reread_idle(rd, "Grug", dict(IDLE))
        self.assertEqual(got["doing"], nowstatus.OWN_PLAY)

    def test_a_member_doing_something_is_left_as_composed(self):
        busy = {"doing": "Walking", "line": "Walking."}
        with session(30) as rd:
            self.assertEqual(members.reread_idle(rd, "Grug", busy), busy)

    def test_a_failed_side_read_leaves_the_member_as_composed(self):
        down = mock.patch.object(
            members.guildrun, "active_names", side_effect=RuntimeError("down")
        )
        with session(30) as rd, down:
            self.assertEqual(members.reread_idle(rd, "Grug", dict(IDLE)), IDLE)


if __name__ == "__main__":
    unittest.main()
