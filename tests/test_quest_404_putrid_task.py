"""A Putrid Task (quest 404, #3168): a quester can finish it, or the ledger
explains why no one can.

The world rows are shaped as questers.QUESTS_SQL, classquest.LOOT_SQL and
classquest.SPAWNS_SQL read them; the quest log row as questers.LOG_SQL reads
character_queststatus (itemcount1..6 beside each RequiredItemId). The item and
creature ids are illustrative, not read from a world database: the test proves
the rule, not the world's rows.
"""

import unittest

import classquest
import questers
import questledger
from test_questers import (
    PRIEST,
    HORDE_MASK,
    giver,
    quest,
    spawn,
    world,
)

# Zone and race constants from test_questers_eligibility.py
TIRISFAL = 85
UNDEAD = 5
HORDE = HORDE_MASK

PUTRID = 404
# Seven Putrid Claws from two creature entries.
PUTRID_CLAW = 2855
ROTTING_ANCESTOR = 1525
LOST_SOUL = 1526
WANTED = 7


def putrid_world():
    putrid = quest(PUTRID, TIRISFAL, 6, min_level=4, races=HORDE, title="A Putrid Task")
    putrid.update({"item1": PUTRID_CLAW, "item_count1": WANTED})
    return world(
        extra_quests=[putrid],
        extra_givers=[
            giver(PUTRID, "start", 2150, 1568, 0, 0),
            giver(PUTRID, "end", 2150, 1568, 0, 0),
        ],
        extra_spawns=[
            spawn(6001, ROTTING_ANCESTOR, 100.0, 0, level=5),
            spawn(6002, LOST_SOUL, 200.0, 0, level=5),
        ],
        extra_loot=[
            {"item": PUTRID_CLAW, "entry": ROTTING_ANCESTOR},
            {"item": PUTRID_CLAW, "entry": LOST_SOUL},
        ],
    )


def log_row(counts, status=questers.STATUS_INCOMPLETE):
    """A questers.LOG_SQL row for quest 404 with these ingredient counts."""
    row = {"guid": 8, "quest": PUTRID, "status": status}
    row["progress"] = sum(counts.get(item, 0) for item in [PUTRID_CLAW])
    for i in range(1, 7):
        item = PUTRID_CLAW if i == 1 else 0
        row["item%d" % i] = item
        row["itemcount%d" % i] = counts.get(item, 0)
    for i in range(1, 5):
        row["npc%d" % i] = 0
        row["mobcount%d" % i] = 0
    return row


def holder(counts, status=questers.STATUS_INCOMPLETE):
    """Grakk in Tirisfal at level 6, holding quest 404, read off LOG_SQL."""
    member_row = {
        "guid": 8,
        "name": "Grakk",
        "level": 6,
        "race": UNDEAD,
        "class_id": PRIEST,
        "online": 1,
        "map_id": 0,
        "pos_x": 0.0,
        "pos_y": 0.0,
        "zone_id": TIRISFAL,
    }
    (member,) = questers.members_from_rows(
        [member_row],
        [log_row(counts, status)],
        [{"guid": 8, "quest": q} for q in (20, 21)],
    )
    return member


class AQuesterCanFinishPutridTask(unittest.TestCase):
    def test_hunts_until_putrid_claw_count_is_met(self):
        cat = putrid_world()
        counts = {}
        hunted = []
        # Hunt until we have 7 Putrid Claws (each hunt gives some amount)
        for _ in range(7):  # Max 7 hunts needed if each gives 1
            member = holder(counts)
            move = questers.plan(cat, member, questers.Clock(), 0.0).move
            if move is None or move.kind != classquest.HUNT:
                break
            self.assertEqual(move.quest, PUTRID)
            self.assertIn(move.spot.entry, (ROTTING_ANCESTOR, LOST_SOUL))
            item = PUTRID_CLAW
            self.assertLess(counts.get(item, 0), WANTED)
            hunted.append(move.spot.entry)
            # Simulate getting 1 claw per hunt
            counts[item] = counts.get(item, 0) + 1
        # After getting all 7, it should turn in
        member = holder(counts, status=questers.STATUS_COMPLETE)
        move = questers.plan(cat, member, questers.Clock(), 0.0).move
        self.assertEqual((move.kind, move.quest), (classquest.TURN_IN, PUTRID))
        # Should have hunted both creature types
        self.assertTrue(set(hunted) & {ROTTING_ANCESTOR, LOST_SOUL})

    def test_the_full_task_is_handed_in(self):
        full = {PUTRID_CLAW: WANTED}
        member = holder(full, status=questers.STATUS_COMPLETE)
        move = questers.plan(putrid_world(), member, questers.Clock(), 0.0).move
        self.assertEqual((move.kind, move.quest), (classquest.TURN_IN, PUTRID))


class PutridTaskStallExplainsMissingSource(unittest.TestCase):
    def test_a_putrid_task_with_no_loot_rows_stalls_with_specific_reason(self):
        """When Putrid Claw has no creature drops, the stall names it."""
        putrid = quest(
            PUTRID, TIRISFAL, 6, min_level=4, races=HORDE, title="A Putrid Task"
        )
        putrid.update({"item1": PUTRID_CLAW, "item_count1": WANTED})
        cat = world(
            extra_quests=[putrid],
            extra_givers=[
                giver(PUTRID, "start", 2150, 1568, 0, 0),
                giver(PUTRID, "end", 2150, 1568, 0, 0),
            ],
            extra_spawns=[
                spawn(6001, ROTTING_ANCESTOR, 100.0, 0, level=5),
                spawn(6002, LOST_SOUL, 200.0, 0, level=5),
            ],
            # No extra_loot - the item has no source
        )
        member = holder({PUTRID_CLAW: 0})
        clock = questers.Clock()
        p = questers.plan(cat, member, clock, 0.0)
        self.assertEqual(p.broken, ())
        # Play for 2 hours
        for i in range(1, 13):
            p = questers.plan(cat, member, clock, 600.0 * i)
        self.assertEqual(len(p.broken), 1)
        self.assertEqual(p.broken[0].quest, PUTRID)
        # The reason should explain the missing Putrid Claw source
        self.assertNotEqual(p.broken[0].reason, questers.STALLED_UNSOURCED)
        self.assertIn("Putrid Claw", p.broken[0].reason)
        self.assertIn("no spawned creature drops", p.broken[0].reason)

    def test_putrid_task_ledger_explains_missing_putrid_claw_source(self):
        """The _broken_reason for quest 404 names the missing Putrid Claw source."""
        putrid = classquest.Quest(
            PUTRID,
            "A Putrid Task",
            0,
            6,
            0,
            0,
            0,
            0,
            0,
            items=((PUTRID_CLAW, WANTED),),
            enders=(
                classquest.Spawn(2150, 1568, 0, 0.0, 0.0, name="Deathguard Dillinger"),
            ),
        )
        facts = questers.Facts(zone=TIRISFAL, level=6, ender_npcs=True)

        early = questers._broken_reason(
            putrid,
            facts,
            questers.STATUS_INCOMPLETE,
            0,
            frozenset(),
            {},
        )
        self.assertEqual(early, "")

        reason = questers._broken_reason(
            putrid,
            facts,
            questers.STATUS_INCOMPLETE,
            questers.STALL_SECONDS,
            frozenset(),
            {},
        )

        self.assertEqual(
            reason,
            "A Putrid Task (quest 404) requires Putrid Claw (item 2855), "
            "which no spawned creature drops",
        )


class AnAbandonSaysWhy(unittest.TestCase):
    def test_an_abandon_nobody_recorded_broken_is_explained(self):
        taken = {
            "quest": PUTRID,
            "guid": 8,
            "character_name": "Grakk",
            "state": questledger.TAKEN,
            "first_taken": None,
            "finished": None,
            "reason": "",
        }
        (entry,) = questledger.changes({8: "Grakk"}, [taken], [], [], "now")
        self.assertEqual(entry.state, questledger.ABANDONED)
        self.assertEqual(entry.reason, questledger.ABANDONED_REASON)
        self.assertTrue(entry.reason)


if __name__ == "__main__":
    unittest.main()
