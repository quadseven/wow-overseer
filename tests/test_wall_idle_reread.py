"""The watch wall words an Idle member as the roster does (#2192)."""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    import watchwall
    from apiv2 import members
    import realmread
    from test_idle_reread_leader import session
    from test_members_v2 import FakeConn
    from test_roster_idle_reading import NOW, HOUR, roster, rules

MEMBER = {"name": "Grug", "present": True, "broadcast_url": "x", "playable": True}


def reread(name, now):
    return dict(now, doing="Stalled", line="Stalled.", seen=name)


class TheWallReread(unittest.TestCase):
    def test_a_reread_changes_an_idle_tile(self):
        wall = watchwall.build_wall([MEMBER], facts={}, reread=reread)
        self.assertEqual(wall["tiles"][0]["now"]["doing"], "Stalled")
        self.assertEqual(wall["tiles"][0]["now"]["seen"], "Grug")

    def test_no_reread_leaves_the_composed_sentence(self):
        wall = watchwall.build_wall([MEMBER], facts={})
        self.assertEqual(wall["tiles"][0]["now"]["doing"], "Idle")

    def test_heads_pass_the_reread_to_the_wall(self):
        built = [("a", {"members": [MEMBER]})]
        got = watchwall.build_heads(built, facts={}, reread=reread)
        self.assertEqual(got["wall"]["tiles"][0]["now"]["doing"], "Stalled")

    def test_the_wall_and_the_banner_word_a_moved_member_the_same(self):
        facts = {}
        with session(30) as rd:
            composed = watchwall.nowstatus.compose(MEMBER, {})
            banner = members.reread_idle(rd, "Grug", composed)
            wall = watchwall.build_wall(
                [MEMBER],
                facts=facts,
                reread=lambda name, now: members.reread_idle(rd, name, now),
            )
        self.assertNotEqual(banner["doing"], "Idle")
        self.assertEqual(wall["tiles"][0]["now"], banner)

    def test_the_roster_the_banner_and_the_wall_word_a_moved_member_the_same(self):
        levelled = [("Reed", NOW - 30 * HOUR)]
        by, _ = roster(levelled=levelled)
        member = dict(MEMBER, name="Reed")
        with realmread.Session(lambda: FakeConn(rules(levelled=levelled), [])) as rd:
            def reread(name, now):
                return members.reread_idle(rd, name, now)

            composed = watchwall.nowstatus.compose(member, {})
            banner = reread("Reed", composed)
            wall = watchwall.build_wall([member], facts={}, reread=reread)
        tile = wall["tiles"][0]["now"]
        self.assertEqual(tile, banner)
        for key in ("doing", "stalled_s"):
            self.assertEqual(by["Reed"][key], banner[key])
            self.assertEqual(by["Reed"][key], tile[key])


if __name__ == "__main__":
    unittest.main()
