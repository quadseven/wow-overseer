"""The class quest milestone counts the reward groups the seat's race may take.

The class chain view drops a reward group when no quest of it admits the
seat's race. The milestone must drop the same groups, or such a seat waits for
a reward it can never get.
"""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    from apiv2 import classchain, ragnaros

WARRIOR = 1
HUMAN, ORC = 1, 2
HUMAN_BIT, ORC_BIT = 1, 2


def quest(qid, reward, races=0):
    return {
        "id": qid,
        "title": "Quest %d" % qid,
        "sort": 0,
        "min_level": 10,
        "races": races,
        "classes": 1,
        "prev": 0,
        "exclusive": 0,
        "reward": reward,
        "display": 0,
        "grp": 0,
    }


# Reward 71: any race. 72: orcs only. 73: humans only. 74: sold by a trainer.
QUESTS = [
    quest(1, 71),
    quest(2, 72, races=ORC_BIT),
    quest(3, 73, races=HUMAN_BIT),
    quest(4, 74),
]
STARTED = {1, 2, 3, 4}


def book():
    return classchain.book_of(QUESTS, STARTED, [{"spell": 74}])


class TheMilestoneRace(unittest.TestCase):
    def test_done_once_every_group_the_race_can_take_is_rewarded(self):
        # The human can take rewards 71 and 73, not the orc-only 72.
        self.assertTrue(ragnaros._quest_done(book(), WARRIOR, {1, 3}, set(), HUMAN))

    def test_a_reward_known_by_spell_counts_as_rewarded(self):
        self.assertTrue(ragnaros._quest_done(book(), WARRIOR, {1}, {73}, HUMAN))

    def test_not_done_while_a_group_the_race_can_take_is_missing(self):
        self.assertFalse(ragnaros._quest_done(book(), WARRIOR, {1}, set(), HUMAN))
        self.assertFalse(ragnaros._quest_done(book(), WARRIOR, {3}, set(), HUMAN))

    def test_the_other_race_needs_its_own_groups(self):
        # The orc can take 71 and 72, not the human-only 73.
        self.assertTrue(ragnaros._quest_done(book(), WARRIOR, {1, 2}, set(), ORC))
        self.assertFalse(ragnaros._quest_done(book(), WARRIOR, {1, 3}, set(), ORC))

    def test_the_chain_view_and_the_milestone_agree(self):
        # The view lists exactly the human's takeable groups; rewarding the
        # last quest of each listed chain satisfies the milestone, and
        # leaving any one out does not.
        char = {"class_id": WARRIOR, "race": HUMAN, "level": 20}
        listed = classchain.chains(book(), char, {}, set(), set(), 0)
        self.assertEqual(sorted(c["title"] for c in listed), ["Quest 1", "Quest 3"])
        last = [c["steps"][-1]["id"] for c in listed]
        self.assertTrue(ragnaros._quest_done(book(), WARRIOR, set(last), set(), HUMAN))
        for skipped in last:
            rest = set(last) - {skipped}
            self.assertFalse(ragnaros._quest_done(book(), WARRIOR, rest, set(), HUMAN))
