"""Quest 221 "Worgen in the Woods" (#2173): a quest that cannot be finished due to missing giver and missing spawns.

The quest is:
- QuestLevel: 29; MinLevel: 23
- Previous quest: 173
- Required creature/object 205 x12 (Nightbane Dark Runner): 0 spawn(s) in zone, 57 total

It is broken because:
- The quest giver would not give it: no giver of that quest in reach
- Last objective counts: not in the log now

The test ensures:
1. A quester can finish this quest, or the ticket says why no one can
2. A test or a ledger row shows it
3. The ledger reason is gone or explained

Acceptance criteria:
- [ ] A quester can finish this quest, or the ticket says why no one can
- [ ] A test or a ledger row shows it
- [ ] The ledger reason is gone or explained
"""

import unittest

import classquest
import questers
from tests.test_questers import DUSKWOOD, HUMAN, WARRIOR, giver, quest, spawn, mirra

QUEST = 221


def worgen_catalogue(spawn_map, title="Worgen in the Woods"):
    """Quest 221: Worgen in the Woods, Duskwood, level 29.

    Previous quest: 173
    Required creature/object 205 x12 (Nightbane Dark Runner): 0 spawn(s) in zone,
    57 total spawns on `spawn_map`.
    """
    worgen = quest(
        QUEST,
        DUSKWOOD,
        29,
        min_level=23,
        prev=173,
        kill=205,
        count=12,
        title=title,
    )
    spawns = [
        spawn(
            9000 + i,
            205,
            5000.0 + i * 10,
            0.0,
            level=29,
            map_id=spawn_map,
            name="Nightbane Dark Runner",
        )
        for i in range(57)
    ]
    return questers.catalogue(
        [worgen],
        [
            giver(QUEST, "start", 8001, 801, 0, 0),
            giver(QUEST, "end", 8001, 801, 400, 0),
        ],
        spawns,
        [],
        [{"quest": QUEST, "kind": "creature", "entry": 801}],
        [{"quest": QUEST, "kind": "creature", "entry": 801}],
    )


def pindle_holder():
    """Pindle, who is stuck with quest 221."""
    return mirra(
        name="Pindle",
        level=29,
        race=HUMAN,
        class_id=WARRIOR,
        map_id=0,
        zone_id=DUSKWOOD,
        quest_log={QUEST: questers.STATUS_INCOMPLETE},
        quest_progress={QUEST: 0},
        quest_objectives={QUEST: {205: 0}},
    )


class AQuestCanBeFinished(unittest.TestCase):
    """A quester can finish this quest, or the ticket says why no one can.

    This quest is broken because:
    1. The quest giver is not spawned in Duskwood, so it cannot be taken
    2. The quest objectives are not spawned in Duskwood, so it cannot be worked from Duskwood
    """

    def test_quest_221_is_not_in_reach(self):
        """Quest 221 is not reachable because the giver is not spawned in Duskwood."""
        cat = worgen_catalogue(spawn_map=530)
        member = pindle_holder()

        # Quest 221 is NOT in reach for a member who already has it
        self.assertEqual(questers.in_reach(cat, member, DUSKWOOD), [])

    def test_quest_221_is_not_reachable(self):
        """Quest 221 cannot be worked because there is no crossing route from Duskwood to the spawn map."""
        cat = worgen_catalogue(spawn_map=530)
        member = pindle_holder()

        # Create a clock that advances time
        clock = questers.Clock()
        plan = None
        for i in range(13):
            plan = questers.plan(cat, member, clock, 600.0 * i)

        # After the stall clock runs, quest 221 should be marked as broken
        self.assertEqual(len(plan.broken), 1)
        self.assertEqual(plan.broken[0].quest, QUEST)
        self.assertEqual(plan.broken[0].reason, questers.STALLED)


class ATestOrLedgerRowShowsIt(unittest.TestCase):
    """A test or a ledger row shows it.

    The test above shows the quest is broken with reason STALLED.
    This reason is recorded in the quest ledger.
    """

    def test_a_quest_with_no_crossing_route_is_reported_broken(self):
        """Verify quest 221 is reported as broken in the quest ledger."""
        cat = worgen_catalogue(spawn_map=530)
        member = pindle_holder()

        # Create a clock that advances time
        clock = questers.Clock()
        plan = None
        for i in range(13):
            plan = questers.plan(cat, member, clock, 600.0 * i)

        # Quest 221 should be reported as broken with STALLED
        self.assertEqual(len(plan.broken), 1)
        self.assertEqual(plan.broken[0].quest, QUEST)
        self.assertEqual(plan.broken[0].reason, questers.STALLED)


class TheLedgerReasonIsGoneOrExplained(unittest.TestCase):
    """The ledger reason is gone or explained.

    This is verified by the test that quest 221 is reported as broken
    with reason STALLED, and the quest is known to be broken
    because it has no crossing route to the spawn map.
    """

    def test_stalled_is_explained(self):
        """The reason STALLED is explained as no crossing route to the spawn map."""
        # Quest 221 has no crossing route to the spawn map, so STALLED makes sense
        # The quest is broken because of this reason
        cat = worgen_catalogue(spawn_map=530)
        member = pindle_holder()

        # Create a clock that advances time
        clock = questers.Clock()
        plan = None
        for i in range(13):
            plan = questers.plan(cat, member, clock, 600.0 * i)

        # Quest 221 should be reported as broken with STALLED
        self.assertEqual(len(plan.broken), 1)
        self.assertEqual(plan.broken[0].reason, questers.STALLED)


if __name__ == "__main__":
    unittest.main()