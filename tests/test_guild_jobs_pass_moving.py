"""The guild jobs pass reads who is walking onto frozen members (#2152, #2401).

The pass assigned `m.moving` on a frozen guildjobs.Member, so every pass raised
FrozenInstanceError before it planned: no job, and no death loop flag, was ever
written.
"""

import unittest

import guildjobs
from test_guildsocial_bridge import bridge


def member(name):
    return guildjobs.Member(name, "G", "member", level=10, online=True)


class ReadMoving(unittest.TestCase):
    def test_walking_members_are_marked_without_assigning(self):
        got = bridge._read_moving([member("A"), member("B")], frozenset({"A"}))
        self.assertEqual([(m.name, m.moving) for m in got], [("A", True), ("B", False)])

    def test_the_members_read_are_left_as_they_were(self):
        original = member("A")
        bridge._read_moving([original], frozenset({"A"}))
        self.assertFalse(original.moving)

    def test_no_members_is_an_empty_list(self):
        self.assertEqual(bridge._read_moving([], frozenset()), [])


if __name__ == "__main__":
    unittest.main()
