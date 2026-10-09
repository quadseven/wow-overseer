"""A finished variant closes its exclusive-group siblings (wow-overseer #675).

Read 2026-10-08: two Alliance warriors, a dwarf and a gnome, had rewarded
Muren Stormpike (1679, races 68, given by an Ironforge-side trainer) and held
Vejrek (1678) at status 3, yet were sent across the continent to take A
Warrior's Training (1638, Stormwind) for the same spell. 1679 and 1638 share
ExclusiveGroup 1638: the game offers only one, so 1638 is closed to them.
"""

import unittest

import classquest
from test_classquest import EASTERN, WARRIOR, qrow, who

DWARF, HUMAN = 3, 1
GRANIS = dict(guid=196, entry=1229, map_id=0, x=-5606.0, y=-530.0, name="Granis")
ILSA = dict(guid=79778, entry=5480, map_id=0, x=-8689.0, y=326.0, name="Ilsa Corbin")
MUREN = dict(guid=2018, entry=6114, map_id=0, x=-5046.0, y=-1273.0, name="Muren")
ALLIANCE = 1101 | 68


def rows():
    return [
        qrow(1638, "A Warrior's Training", races=1101, exclusive=1638),
        qrow(1679, "Muren Stormpike", races=68, exclusive=1638),
        qrow(
            1678, "Vejrek", races=68, prev=1679, reward=8121, item1=6799, item_count1=1
        ),
        qrow(1665, "Bartleby's Mug", races=1101, prev=1640, reward=8121),
        qrow(1640, "Beat Bartleby", races=1101, prev=1638),
    ]


def givers():
    out = []
    for quest, role, spawn in (
        (1638, "start", ILSA),
        (1679, "start", GRANIS),
        (1679, "end", MUREN),
        (1678, "start", MUREN),
        (1678, "end", MUREN),
    ):
        out.append(dict(spawn, quest=quest, role=role))
    return out


def book():
    return classquest.build(
        quest_rows=rows(), giver_rows=givers(), spawn_rows=[], loot_rows=[]
    )


def dwarf(**over):
    base = dict(
        race=DWARF, class_id=WARRIOR, map_id=EASTERN, x=-5300.0, y=-2889.0, level=17
    )
    base.update(over)
    return who(**base)


class TheExclusiveGroup(unittest.TestCase):
    def test_the_group_is_read_from_the_addon_row(self):
        self.assertIn("ExclusiveGroup", classquest.QUESTS_SQL)
        self.assertEqual(book().quests[1638].exclusive, 1638)
        self.assertEqual(book().quests[1678].exclusive, 0)

    def test_a_rewarded_sibling_closes_the_far_variant(self):
        m = dwarf(quest_log={1678: 3}, quests_done=frozenset({1679}))
        move, blocked = classquest.next_move(book(), m)
        for text in blocked:
            self.assertNotIn("Ilsa", text)
            self.assertNotIn("Warrior's Training", text)
        if move is not None:
            self.assertNotEqual(move.quest, 1638)

    def test_the_far_variant_is_never_the_move_while_the_near_one_is_held_off(self):
        m = dwarf(quest_log={1678: 3}, quests_done=frozenset({1679}))
        move, blocked = classquest.next_move(book(), m, held_off=frozenset({1678}))
        self.assertIsNone(move)
        self.assertTrue(blocked)
        self.assertIn("Vejrek", blocked[0])

    def test_an_untouched_dwarf_still_may_take_either(self):
        m = dwarf(x=-8700.0, y=320.0)
        move, _ = classquest.next_move(book(), m)
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, 1638))

    def test_a_held_far_variant_closes_the_near_chain(self):
        m = dwarf(quest_log={1638: 3})
        options = classquest._variant_move(book(), m, 1678)
        self.assertIsNone(options)


if __name__ == "__main__":
    unittest.main()
