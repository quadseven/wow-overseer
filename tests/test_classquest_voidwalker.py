"""A warlock stays with its Voidwalker quest instead of sailing off to the next.

Measured on the dev realm on 2026-11-07 (wow-overseer#2032): 26 of 52 guild
warlocks at level 10 or more did not know Summon Voidwalker (spell 697, the
reward of the level 10 class quest chain), and 21 of them held a quest of that
chain. An Alliance warlock's chain is in Elwynn and Stormwind (Surena Caledon,
1688, then The Binding, 1689); its next chain, the Succubus (Heartswood, 1738),
is in Ashenvale on Kalimdor. The bridge log of that day shows the same members
crossing back and forth: Nubb crossed to the Eastern Kingdoms for Surena
Caledon at 17:13 and, on the next pass there, crossed back to Kalimdor for
Heartswood at 17:54; Sogg and Lugg did the same three to four times in a day.
On the Eastern Kingdoms the Voidwalker hunt was held for a while (Surena's one
spawn refused or tried), and the planner took the first move of any later
reward, which was a boat back. The hold lapsed on the far continent, so the
next pass crossed again, and neither quest was ever finished.

A player finishes the quest it came for. A later reward's crossing does not
pass over an earlier reward whose quest is in the member's log, held for a
reason of its own (HOLDING), with its work on the member's own continent: the
member waits out the hold where it stands, as a CROSS already does within one
reward (classquest._live).
"""

import unittest

import classquest
from test_classquest import EASTERN, KALIMDOR, who

WARLOCK, HUMAN = 9, 1
ALLIANCE_MASK = 1101
WARLOCK_SORT = -61

SURENA_QUEST, BINDING_QUEST, HEARTSWOOD = 1688, 1689, 1738

GAKIN = {
    "guid": 79798,
    "entry": 6122,
    "map_id": EASTERN,
    "x": -8983.0,
    "y": 1041.5,
    "name": "Gakin the Darkbinder",
}
SURENA = {
    "guid": 80211,
    "entry": 881,
    "map_id": EASTERN,
    "x": -9530.0,
    "y": -1200.0,
    "name": "Surena Caledon",
    "rank": 0,
    "level": 11,
}
# The Succubus chain's giver and objective on Kalimdor (Ashenvale).
ASHENVALE_GIVER = {
    "guid": 33010,
    "entry": 6268,
    "map_id": KALIMDOR,
    "x": 2700.0,
    "y": -400.0,
    "name": "Ashenvale giver",
}
HEART = {
    "guid": 33500,
    "entry": 3809,
    "map_id": KALIMDOR,
    "x": 2900.0,
    "y": -300.0,
    "name": "Ashenvale Bear",
    "rank": 0,
    "level": 25,
}


def qrow(qid, title, **over):
    row = {
        "id": qid,
        "title": title,
        "sort": WARLOCK_SORT,
        "min_level": 10,
        "races": ALLIANCE_MASK,
        "classes": 256,
        "prev": 0,
        "reward": 0,
        "display": 0,
        "grp": 0,
    }
    for i in range(1, 5):
        row["npc%d" % i] = 0
        row["npc_count%d" % i] = 0
    for i in range(1, 7):
        row["item%d" % i] = 0
        row["item_count%d" % i] = 0
    row.update(over)
    return row


def warlock_book():
    rows = [
        qrow(SURENA_QUEST, "Surena Caledon", npc1=881, npc_count1=1),
        qrow(
            BINDING_QUEST,
            "The Binding",
            prev=SURENA_QUEST,
            reward=11520,
            display=697,
        ),
        qrow(
            HEARTSWOOD,
            "Heartswood",
            min_level=20,
            reward=11519,
            display=712,
            npc1=3809,
            npc_count1=1,
        ),
    ]
    givers = [
        dict(GAKIN, quest=SURENA_QUEST, role="start"),
        dict(GAKIN, quest=SURENA_QUEST, role="end"),
        dict(GAKIN, quest=BINDING_QUEST, role="start"),
        dict(GAKIN, quest=BINDING_QUEST, role="end"),
        dict(ASHENVALE_GIVER, quest=HEARTSWOOD, role="start"),
        dict(ASHENVALE_GIVER, quest=HEARTSWOOD, role="end"),
    ]
    return classquest.build(rows, givers, [SURENA, HEART], [])


def nubb(**over):
    """A level 43 human warlock in Elwynn holding Surena Caledon (status 3)."""
    base = dict(
        class_id=WARLOCK,
        race=HUMAN,
        level=43,
        map_id=EASTERN,
        x=-9400.0,
        y=-1100.0,
        quest_log={SURENA_QUEST: classquest.STATUS_INCOMPLETE},
        quests_done=frozenset(),
        known=frozenset(),
    )
    base.update(over)
    return who("Nubb", **base)


TRIED = {SURENA_QUEST: ((EASTERN, SURENA["x"], SURENA["y"]),)}


class TheVoidwalkerFirst(unittest.TestCase):
    def test_a_warlock_without_697_is_sent_to_the_voidwalker_chain(self):
        move, _blocked = classquest.next_move(warlock_book(), nubb())
        self.assertEqual(move.kind, classquest.HUNT)
        self.assertEqual(move.quest, SURENA_QUEST)
        self.assertIn("697", move.why)

    def test_one_that_never_took_it_walks_to_its_giver(self):
        move, _blocked = classquest.next_move(warlock_book(), nubb(quest_log={}))
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, SURENA_QUEST))

    def test_one_on_the_other_continent_crosses_for_the_voidwalker(self):
        m = nubb(map_id=KALIMDOR, x=2600.0, y=-350.0)
        move, _blocked = classquest.next_move(warlock_book(), m)
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, EASTERN))
        self.assertEqual(move.quest, SURENA_QUEST)


class NoBoatBackWhileItWaits(unittest.TestCase):
    def test_a_tried_hunt_here_does_not_send_it_across_for_the_succubus(self):
        move, blocked = classquest.next_move(warlock_book(), nubb(), TRIED)
        self.assertIsNone(move)
        self.assertTrue(any("Surena Caledon" in b for b in blocked))
        self.assertTrue(any("Heartswood" in b for b in blocked))

    def test_a_given_up_hunt_here_does_not_either(self):
        move, _blocked = classquest.next_move(
            warlock_book(), nubb(), held_off=frozenset({SURENA_QUEST})
        )
        self.assertIsNone(move)

    def test_the_wait_is_named(self):
        _move, blocked = classquest.next_move(warlock_book(), nubb(), TRIED)
        held = [b for b in blocked if "Heartswood" in b]
        self.assertEqual(len(held), 1)
        self.assertIn("Surena Caledon", held[0])
        self.assertIn("Kalimdor", held[0])

    def test_with_the_voidwalker_known_the_succubus_crossing_goes(self):
        m = nubb(known=frozenset({697}), quest_log={})
        move, _blocked = classquest.next_move(warlock_book(), m, TRIED)
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, KALIMDOR))
        self.assertEqual(move.quest, HEARTSWOOD)

    def test_a_held_quest_not_in_the_log_does_not_hold_the_crossing(self):
        # A voidwalker quest never taken (its giver too far, say) is no hold
        # on the member: nothing it came for is half done here.
        m = nubb(quest_log={})
        gakin_gone = classquest.build(
            [
                qrow(SURENA_QUEST, "Surena Caledon", npc1=881, npc_count1=1),
                qrow(
                    HEARTSWOOD,
                    "Heartswood",
                    min_level=20,
                    reward=11519,
                    display=712,
                    npc1=3809,
                    npc_count1=1,
                ),
                qrow(
                    BINDING_QUEST,
                    "The Binding",
                    prev=SURENA_QUEST,
                    reward=11520,
                    display=697,
                ),
            ],
            [
                dict(ASHENVALE_GIVER, quest=HEARTSWOOD, role="start"),
                dict(ASHENVALE_GIVER, quest=HEARTSWOOD, role="end"),
            ],
            [SURENA, HEART],
            [],
        )
        move, _blocked = classquest.next_move(gakin_gone, m)
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, KALIMDOR))

    def test_a_hold_on_the_other_continent_does_not_hold_this_one(self):
        # Held off while it stands on Kalimdor: the Voidwalker work is not
        # here, so the Succubus quest on Kalimdor is worked (no crossing).
        m = nubb(map_id=KALIMDOR, x=2600.0, y=-350.0)
        move, _blocked = classquest.next_move(
            warlock_book(), m, held_off=frozenset({SURENA_QUEST})
        )
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, HEARTSWOOD))


if __name__ == "__main__":
    unittest.main()
