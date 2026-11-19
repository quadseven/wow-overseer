"""Bloodscalp Ears (quest 189, Stranglethorn Vale, 35, min 30): a quester can
finish it from the ticket's world rows, and an old stall recorded in the
ledger is not held as a world fact.

The rows are shaped as questers.QUESTS_SQL, questers/classquest loot and spawn
reads consume them: quest 189 requires item 1519 (Bloodscalp Ear) x15, dropped
by creature entries 587, 588, 595, 597, 660, 671, 694, 697, 699, 701 and 702.
The giver, ender, zone id and coordinates are illustrative, not read from a
world database: the test proves the rule from those rows, not the world's
placement.
"""

import unittest

import classquest
import questers
from test_questers import HUMAN, PRIEST, giver, quest, spawn, world

STRANGLETHORN = 33
EARS = 189
BLOODSCALP_EAR = 1519
DROPPERS = (587, 588, 595, 597, 660, 671, 694, 697, 699, 701, 702)
WANTED = 15


def ears_world():
    ears = quest(EARS, STRANGLETHORN, 35, min_level=30, title="Bloodscalp Ears")
    ears.update({"item1": BLOODSCALP_EAR, "item_count1": WANTED})
    return world(
        extra_quests=[ears],
        extra_givers=[
            giver(EARS, "start", 3189, 737, 0, 0),
            giver(EARS, "end", 3189, 737, 0, 0),
        ],
        extra_spawns=[
            spawn(8000 + i, entry, 100.0 * i, 0, level=33)
            for i, entry in enumerate(DROPPERS, start=1)
        ],
        extra_loot=[
            {"item": BLOODSCALP_EAR, "entry": entry} for entry in DROPPERS
        ],
    )


def log_row(count, status=questers.STATUS_INCOMPLETE):
    row = {
        "guid": 8,
        "quest": EARS,
        "status": status,
        "progress": count,
        "item1": BLOODSCALP_EAR,
        "itemcount1": count,
    }
    for i in range(2, 7):
        row["item%d" % i] = 0
        row["itemcount%d" % i] = 0
    for i in range(1, 5):
        row["npc%d" % i] = 0
        row["mobcount%d" % i] = 0
    return row


def holder(count, status=questers.STATUS_INCOMPLETE):
    member_row = {
        "guid": 8,
        "name": "Mirra",
        "level": 35,
        "race": HUMAN,
        "class_id": PRIEST,
        "online": 1,
        "map_id": 0,
        "pos_x": 0.0,
        "pos_y": 0.0,
        "zone_id": STRANGLETHORN,
    }
    (member,) = questers.members_from_rows(
        [member_row],
        [log_row(count, status)],
        [{"guid": 8, "quest": q} for q in (20, 21)],
    )
    return member


class AQuesterCanFinishBloodscalpEars(unittest.TestCase):
    def test_each_hunt_is_for_a_creature_that_drops_a_bloodscalp_ear(self):
        cat = ears_world()
        count = 0
        hunted = []
        for _ in range(WANTED):
            move = questers.plan(cat, holder(count), questers.Clock(), 0.0).move
            self.assertEqual((move.kind, move.quest), (classquest.HUNT, EARS))
            self.assertIn(move.spot.entry, DROPPERS)
            hunted.append(move.spot.entry)
            count += 1
        self.assertTrue(hunted)

    def test_the_full_quest_is_handed_in(self):
        member = holder(WANTED, status=questers.STATUS_COMPLETE)
        move = questers.plan(ears_world(), member, questers.Clock(), 0.0).move
        self.assertEqual((move.kind, move.quest), (classquest.TURN_IN, EARS))


class AnOldStallIsNotHeldAsAWorldFact(unittest.TestCase):
    def test_a_stall_recorded_only_in_the_ledger_is_retryable(self):
        ledger = {("Mirra", EARS): questers.ledger_state("broken", questers.STALLED)}
        self.assertEqual(
            questers.LEDGER_STALLED,
            ledger[("Mirra", EARS)],
        )
        self.assertEqual(frozenset(), questers.known_broken("Mirra", {}, ledger))

    def test_a_stall_nobody_judged_is_retried_when_objectives_are_actionable(self):
        member = holder(0)
        retry = questers.stalled_holds_with_actionable_objectives(
            ears_world(), member, {EARS: questers.STALLED}
        )
        self.assertEqual(retry, frozenset({EARS}))


if __name__ == "__main__":
    unittest.main()
