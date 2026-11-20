"""The watch wall words an Idle member as the roster does (#2192)."""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    import watchwall
    from apiv2 import members
    from test_idle_reread_leader import session

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


if __name__ == "__main__":
    unittest.main()
