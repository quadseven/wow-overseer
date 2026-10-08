"""A class quest no creature starts names what does start it, or that nothing does.

The case is a live one, read 2026-10-08: every priest of two guilds was blocked
on a racial spell quest (Hex of Weakness, Desperate Prayer, Symbol of Hope) with
"has no giver creature in the world data". Those quests have no row in
creature_queststarter; the sentence now says whether a gameobject or an item
starts them, or that no start exists in the world data at all.
"""

import unittest

import classquest
from test_classquest import PRIEST, TROLL, givers, qrow, who

ROW = qrow(5000, "Hex of Weakness", reward=9035, races=1 << (TROLL - 1), sort=-262)


def blocked_by(start_rows=()):
    b = classquest.build(
        quest_rows=[ROW],
        giver_rows=givers(),
        spawn_rows=[],
        loot_rows=[],
        start_rows=start_rows,
    )
    return classquest.next_move(b, who(class_id=PRIEST, race=TROLL))


class TheStarters(unittest.TestCase):
    def test_a_quest_nothing_starts_is_dropped_not_blocked(self):
        # Retired in 3.3.5 (a trainer teaches the spell): a member owes nothing
        # for it, and is no longer blocked on it for good.
        move, blocked = blocked_by()
        self.assertIsNone(move)
        self.assertEqual(blocked, [])

    def test_an_item_that_starts_the_quest_is_named(self):
        move, blocked = blocked_by([{"quest": 5000, "kind": "item", "entry": 777}])
        self.assertIsNone(move)
        self.assertIn("started by item 777", blocked[0])
        self.assertNotIn("no gameobject or item", blocked[0])

    def test_a_gameobject_that_starts_the_quest_is_named(self):
        _move, blocked = blocked_by([{"quest": 5000, "kind": "gameobject", "entry": 9}])
        self.assertIn("started by gameobject 9", blocked[0])

    def test_the_bridge_reads_the_starters(self):
        self.assertIn("{quests}", classquest.STARTERS_SQL)
        self.assertIn("gameobject_queststarter", classquest.STARTERS_SQL)
        self.assertIn("startquest", classquest.STARTERS_SQL)


class TheOrphanedQuest(unittest.TestCase):
    """A racial priest spell quest nothing starts is no class quest (2026-10-08)."""

    def rows(self):
        return [
            dict(
                id=5634,
                title="Desperate Prayer",
                sort=-262,
                min_level=10,
                races=5,
                classes=0,
                prev=0,
                reward=19338,
                display=19338,
                grp=0,
                **{"npc%d" % i: 0 for i in range(1, 5)},
                **{"npc_count%d" % i: 0 for i in range(1, 5)},
                **{"item%d" % i: 0 for i in range(1, 7)},
                **{"item_count%d" % i: 0 for i in range(1, 7)},
                **{"provided%d" % i: 0 for i in range(5)},
            )
        ]

    def test_with_the_starters_read_an_orphan_is_dropped(self):
        book = classquest.build(self.rows(), [], [], [], start_rows=[])
        self.assertNotIn(5634, book.quests)

    def test_a_gameobject_or_item_start_keeps_it(self):
        start = [{"quest": 5634, "kind": "item", "entry": 1}]
        book = classquest.build(self.rows(), [], [], [], start_rows=start)
        self.assertIn(5634, book.quests)

    def test_without_the_read_nothing_is_dropped(self):
        book = classquest.build(self.rows(), [], [], [])
        self.assertIn(5634, book.quests)


if __name__ == "__main__":
    unittest.main()
