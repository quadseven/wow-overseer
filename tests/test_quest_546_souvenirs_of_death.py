"""Quest 546 Souvenirs of Death: a quester can finish it given the world rows.

The ticket's world rows: QuestLevel 25, MinLevel 20, Hillsbrad Foothills;
required item 3692 (Hillsbrad Human Skull) x30, dropped by creature entries
232, 2244, 2260, 2261, 2264, 2265, 2266, 2267, 2268, 2269, 2270, 2305, 2335,
2360, 2387, 2403, 2404, 2427, 2428, 2448, 2449, 2450, 2451, 2503, 7068, 7069,
7071, 7072, 7074, 7075.

Those creature entries are the item's drop sources. With spawns for them, the
quest has a huntable objective, so a quester takes it, hunts the droppers of
the skull still short, and hands it in once it holds 30. The quest is not
unsourced: item 3692 has creatures that drop it, so no STALLED_UNSOURCED or
invented per-quest reason applies.

The levels and the giver/ender entry are fixture-only: the ticket lists no
giver, ender or spawn rows.
"""

import unittest

import classquest
import questers
from test_questers import HUMAN, PRIEST, giver, mirra, quest, spawn, world

SOUVENIRS_OF_DEATH = 546
SKULL = 3692
WANTED = 30
HILLSBRAD = 26
DROPPERS = (
    232,
    2244,
    2260,
    2261,
    2264,
    2265,
    2266,
    2267,
    2268,
    2269,
    2270,
    2305,
    2335,
    2360,
    2387,
    2403,
    2404,
    2427,
    2428,
    2448,
    2449,
    2450,
    2451,
    2503,
    7068,
    7069,
    7071,
    7072,
    7074,
    7075,
)


def souvenirs_world():
    row = quest(
        SOUVENIRS_OF_DEATH, HILLSBRAD, 25, min_level=20, title="Souvenirs of Death"
    )
    row.update(item1=SKULL, item_count1=WANTED)
    spawns = [
        spawn(6000 + i, entry, 100.0 * i, 0.0, level=24)
        for i, entry in enumerate(DROPPERS)
    ]
    loot = [{"item": SKULL, "entry": entry} for entry in DROPPERS]
    return world(
        extra_quests=[row],
        extra_givers=[
            giver(SOUVENIRS_OF_DEATH, "start", 9546, 235, 0, 0),
            giver(SOUVENIRS_OF_DEATH, "end", 9546, 235, 0, 0),
        ],
        extra_spawns=spawns,
        extra_loot=loot,
    )


def holder(skulls=0, status=questers.STATUS_INCOMPLETE, in_log=True):
    base = dict(
        name="Hulani",
        level=25,
        race=HUMAN,
        class_id=PRIEST,
        zone_id=HILLSBRAD,
        map_id=0,
        x=0.0,
        y=0.0,
        quest_progress={SOUVENIRS_OF_DEATH: skulls},
        quest_item_objectives={SOUVENIRS_OF_DEATH: {SKULL: skulls}},
    )
    if in_log:
        base["quest_log"] = {SOUVENIRS_OF_DEATH: status}
    return mirra(**base)


class CanFinishSouvenirsOfDeath(unittest.TestCase):
    def test_the_quest_is_open_to_a_fresh_quester(self):
        cat = souvenirs_world()
        fresh = questers.Member(**{**holder().__dict__, "quest_log": {}})
        self.assertTrue(questers.open_to(cat, fresh, SOUVENIRS_OF_DEATH))

    def test_it_hunts_a_skull_dropper_when_short(self):
        cat = souvenirs_world()
        move = questers.plan(cat, holder(), questers.Clock(), 0.0).move
        self.assertEqual((move.kind, move.quest), (classquest.HUNT, SOUVENIRS_OF_DEATH))
        self.assertIn(move.spot.entry, DROPPERS)

    def test_it_hands_in_when_full(self):
        cat = souvenirs_world()
        member = holder(skulls=WANTED, status=questers.STATUS_COMPLETE)
        move = questers.plan(cat, member, questers.Clock(), 0.0).move
        self.assertEqual(
            (move.kind, move.quest), (classquest.TURN_IN, SOUVENIRS_OF_DEATH)
        )

    def test_the_short_objective_is_the_skull_until_full(self):
        cat = souvenirs_world()
        quest_row = cat.quest(SOUVENIRS_OF_DEATH)
        self.assertEqual(
            questers._short_entries(holder(), SOUVENIRS_OF_DEATH, quest_row),
            set(DROPPERS),
        )
        self.assertEqual(
            questers._short_entries(
                holder(skulls=WANTED), SOUVENIRS_OF_DEATH, quest_row
            ),
            set(),
        )

    def test_a_hunt_counts_progress_until_the_quest_is_complete(self):
        # The hunt ends when the saved counters reach the required total, and
        # the quest is then complete and due a hand-in.
        cat = souvenirs_world()
        clocks = questers.Clock()
        member = holder(skulls=0)
        move = questers.plan(cat, member, clocks, 0.0).move
        self.assertEqual((move.kind, move.quest), (classquest.HUNT, SOUVENIRS_OF_DEATH))
        full = questers.Member(
            **{
                **member.__dict__,
                "quest_progress": {SOUVENIRS_OF_DEATH: WANTED},
                "quest_item_objectives": {SOUVENIRS_OF_DEATH: {SKULL: WANTED}},
            }
        )
        move = questers.plan(cat, full, clocks, 60.0).move
        self.assertEqual(
            (move.kind, move.quest), (classquest.TURN_IN, SOUVENIRS_OF_DEATH)
        )

    def test_two_idle_hours_give_the_sourced_stall_not_unsourced(self):
        # item 3692 has creature droppers spawned in the world, so two hours
        # of stillness is the plain STALLED reason, not STALLED_UNSOURCED.
        cat = souvenirs_world()
        reason = questers._broken_reason(
            cat.quest(SOUVENIRS_OF_DEATH),
            cat.facts[SOUVENIRS_OF_DEATH],
            questers.STATUS_INCOMPLETE,
            questers.STALL_SECONDS,
            frozenset(),
            {},
        )
        self.assertEqual(reason, questers.STALLED)
        self.assertNotEqual(reason, questers.STALLED_UNSOURCED)


if __name__ == "__main__":
    unittest.main()
