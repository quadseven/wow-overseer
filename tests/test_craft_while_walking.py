"""A member read as walking is given no craft step (#2401).

The module refuses a cast while a character walks ("character is moving"), so
a craft row written then comes back an error. A member read away from where
the pass before it anchored it is held back; the pass after, standing, crafts.
"""

import unittest

import guildjobs
import standstill
from test_guildjobs_craft_room import medic
from test_guildjobs import only_step, plan


def at(name, x, y, map_id=0):
    return guildjobs.Member(
        name, "G", "member", level=10, online=True, map_id=map_id, x=x, y=y
    )


class AMemberOnTheMoveIsGivenNoCraft(unittest.TestCase):
    def test_a_standing_member_crafts(self):
        step = only_step(plan([medic(1, moving=False)]), "Medic")
        self.assertEqual(step.action, "craft")

    def test_a_walking_member_is_given_no_craft(self):
        step = only_step(plan([medic(1, moving=True)]), "Medic")
        self.assertTrue(step is None or step.action != "craft")

    def test_the_hold_is_not_a_make_room_step_either(self):
        step, note = guildjobs._craft_or_room(
            medic(0, moving=True), None, (), 3, {}, ""
        )
        self.assertIsNone(step)
        self.assertEqual(note, "")


class WalkingIsReadFromTheAnchor(unittest.TestCase):
    def setUp(self):
        self.anchors = standstill.track({}, [at("A", 0, 0), at("B", 0, 0)], 0)

    def test_a_member_far_from_its_anchor_is_walking(self):
        got = standstill.walking(self.anchors, [at("A", 500, 0), at("B", 1, 1)])
        self.assertEqual(got, frozenset({"A"}))

    def test_a_member_on_another_map_or_with_no_anchor_is_not_named(self):
        got = standstill.walking(self.anchors, [at("A", 500, 0, 1), at("C", 9, 9)])
        self.assertEqual(got, frozenset())


if __name__ == "__main__":
    unittest.main()
