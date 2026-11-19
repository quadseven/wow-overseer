"""A death knight on the start map is sent the class walk, which carries the
module's gryphon click, whether or not it has a spell to buy."""

import unittest

import classquest
import classtrain
import guildroute


def knight(name="Knight", money=0, class_id=classquest.DEATH_KNIGHT):
    return classtrain.Trainee(
        name, "Guild", 60, money, classtrain.Due(), True, class_id=class_id
    )


def walker(name, map_id):
    return guildroute.Walker(
        name=name, map_id=map_id, unwalkable="", by_row=True, aim="at:0:1,2,3"
    )


class KnightGryphonWalk(unittest.TestCase):
    def plan(self, trainee, map_id, recent=(), busy=()):
        return classtrain.plan(
            [trainee], {trainee.name: walker(trainee.name, map_id)}, set(recent), set(busy)
        )

    def test_penniless_knight_on_start_map_gets_the_class_walk(self):
        walks, _ = self.plan(knight(), classquest.DEATH_KNIGHT_START_MAP)
        self.assertEqual([w.name for w in walks], ["Knight"])
        self.assertTrue(walks[0].gryphon)
        self.assertTrue(walks[0].command.startswith(classtrain.VERB))

    def test_stranded_refusal_history_does_not_block_it(self):
        walks, _ = classtrain.plan(
            [knight()], {"Knight": walker("Knight", 609)}, set(), set(),
            stranded={"Knight": 609},
        )
        self.assertEqual(len(walks), 1)

    def test_knight_elsewhere_is_not_walked_without_a_spell(self):
        walks, _ = self.plan(knight(), 0)
        self.assertEqual(walks, [])

    def test_other_class_on_start_map_is_not_walked(self):
        walks, _ = self.plan(knight(class_id=8), 609)
        self.assertEqual(walks, [])

    def test_cooldown_and_busy_hold_it(self):
        self.assertEqual(self.plan(knight(), 609, recent=["Knight"])[0], [])
        self.assertEqual(self.plan(knight(), 609, busy=["Knight"])[0], [])


if __name__ == "__main__":
    unittest.main()
