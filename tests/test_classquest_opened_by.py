"""A quest another quest's NextQuestID opens is taken only after that one (#781).

Read live 2026-10-20: no dwarf or human paladin of the two guilds had Redemption
(7328) 16 hours after the Tome of Divinity fixes went live. Every take the
class step wrote at the head of the chain was refused by the world: Gakk (a
level 38 dwarf) walked to Tiza Battleforge and wrote `take quest:1647` three
times, Hokk (a level 39 human) walked to Duthorian Rall and wrote `take
quest:1643` three times, and the module answered each "not eligible (level,
race, class, prerequisite or exclusive group)".

The rows below are acore_world's. The Tome of Divinity (1647) has no
PrevQuestID, so the book started the dwarf's chain there. But the core reads a
quest's NextQuestID too (ObjectMgr::LoadQuests adds the quest to its next
quest's prevQuests), and 1646, 2997, 2999 and 3000 all name 1647 as their
next quest: 1647 is offered only once one of them is rewarded
(Player::SatisfyQuestPreviousQuest). 2997, 2999 and 3000 are the "Tome of
Divinity" errands three paladin trainers give a dwarf (one of ExclusiveGroup
2997), each handed in to Tiza; 1646 is started by an item (6916). The human
chain is the same shape: 2998 and 3681 (and the item quest 1642) open 1643.
"""

import unittest

import classquest
from test_classquest import EASTERN, qrow, who

PALADIN, HUMAN, DWARF = 2, 1, 3
DWARF_MASK, HUMAN_MASK = 4, 1

# Spawn rows (creature guid, entry, map 0) of the givers and enders.
TIZA = dict(
    guid=1775, entry=6179, map_id=0, x=-4633.5, y=-932.0, name="Tiza Battleforge"
)
BRANDUR = dict(
    guid=1781, entry=5149, map_id=0, x=-4601.7, y=-896.5, name="Brandur Ironhammer"
)
BROMOS = dict(
    guid=194, entry=1232, map_id=0, x=-5586.8, y=-542.2, name="Bromos Grummner"
)
GRAYSON = dict(
    guid=5000,
    entry=928,
    map_id=0,
    x=-8577.0,
    y=881.7,
    name="Lord Grayson Shadowbreaker",
)
JOHN = dict(guid=108, entry=6175, map_id=0, x=-5015.2, y=-1054.0, name="John Turner")


def tome(qid, title, **over):
    base = dict(sort=-141, classes=PALADIN, min_level=12, races=DWARF_MASK)
    base.update(over)
    return qrow(qid, title, **base)


def rows():
    return [
        tome(1646, "The Tome of Divinity", next=1647),
        tome(2997, "Tome of Divinity", next=1647, exclusive=2997),
        tome(2999, "Tome of Divinity", next=1647, exclusive=2997),
        tome(3000, "Tome of Divinity", next=1647, exclusive=2997),
        tome(1647, "The Tome of Divinity"),
        tome(1648, "The Tome of Divinity", prev=1647, reward=7328, display=7329),
    ]


def givers():
    out = []
    for quest, role, spawn in (
        (2997, "start", BROMOS),
        (2997, "end", TIZA),
        (2999, "start", BRANDUR),
        (2999, "end", TIZA),
        (3000, "start", GRAYSON),
        (3000, "end", TIZA),
        (1646, "end", TIZA),
        (1647, "start", TIZA),
        (1647, "end", JOHN),
        (1648, "start", JOHN),
        (1648, "end", JOHN),
    ):
        out.append(dict(spawn, quest=quest, role=role))
    return out


def book():
    return classquest.build(
        quest_rows=rows(),
        giver_rows=givers(),
        spawn_rows=[],
        loot_rows=[],
        start_rows=[{"quest": 1646, "kind": "item", "entry": 6916}],
    )


def gakk(**over):
    # Gakk stood in Ironforge's Hall of Mysteries, beside Tiza, when it was
    # refused.
    base = dict(
        name="Gakk",
        class_id=PALADIN,
        race=DWARF,
        level=38,
        map_id=EASTERN,
        x=-4620.0,
        y=-920.0,
        zone_id=1537,
    )
    base.update(over)
    return who(**base)


class TheOpeningQuests(unittest.TestCase):
    def test_the_next_quest_id_is_read_from_the_addon_row(self):
        self.assertIn("NextQuestID", classquest.QUESTS_SQL)
        self.assertEqual(book().quests[1647].after, (1646, 2997, 2999, 3000))
        self.assertEqual(book().quests[2997].after, ())

    def test_the_take_of_a_quest_nothing_opened_yet_is_not_written(self):
        move, _blocked = classquest.next_move(book(), gakk())
        self.assertIsNotNone(move)
        self.assertNotEqual(move.quest, 1647)

    def test_the_nearest_opener_a_creature_gives_is_taken_first(self):
        move, blocked = classquest.next_move(book(), gakk())
        self.assertEqual(blocked, [])
        self.assertEqual(move.kind, classquest.TAKE)
        self.assertEqual(move.quest, 2999)
        self.assertEqual(move.spot.name, "Brandur Ironhammer")
        self.assertIn("for spell 7328/7329", move.said)

    def test_an_opener_in_the_log_is_handed_in(self):
        move, _blocked = classquest.next_move(
            book(), gakk(quest_log={2997: classquest.STATUS_COMPLETE})
        )
        self.assertEqual(move.kind, classquest.TURN_IN)
        self.assertEqual(move.quest, 2997)
        self.assertEqual(move.spot.name, "Tiza Battleforge")

    def test_a_rewarded_opener_opens_the_chain(self):
        move, _blocked = classquest.next_move(
            book(), gakk(quests_done=frozenset({3000}))
        )
        self.assertEqual(move.kind, classquest.TAKE)
        self.assertEqual(move.quest, 1647)

    def test_a_held_chain_quest_is_worked_without_the_opener(self):
        move, _blocked = classquest.next_move(
            book(), gakk(quest_log={1647: classquest.STATUS_COMPLETE})
        )
        self.assertEqual(move.kind, classquest.TURN_IN)
        self.assertEqual(move.quest, 1647)

    def test_a_member_no_opener_admits_is_not_sent_to_the_locked_take(self):
        human = gakk(race=HUMAN)
        b = classquest.build(
            quest_rows=[
                *rows()[:4],
                tome(1647, "The Tome of Divinity", races=DWARF_MASK | HUMAN_MASK),
                tome(
                    1648,
                    "The Tome of Divinity",
                    prev=1647,
                    reward=7328,
                    display=7329,
                    races=DWARF_MASK | HUMAN_MASK,
                ),
            ],
            giver_rows=givers(),
            spawn_rows=[],
            loot_rows=[],
        )
        move, _blocked = classquest.next_move(b, human)
        self.assertIsNone(move)

    def test_the_opener_is_owed_like_the_chain(self):
        owed = classquest.owed(book(), gakk())
        self.assertIsNotNone(owed)
        self.assertEqual(owed.quest, 2999)


if __name__ == "__main__":
    unittest.main()
