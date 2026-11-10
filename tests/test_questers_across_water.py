"""A quester on the island whose next quest giver is on the mainland takes the
boat (#2194).

Teldrassil is an island on map 1. The quester's move to the next zone is a walk
to a giver on the mainland of the same map, which the module refuses as across
the water (retryable: a ride row takes the boat). The class quest path plans
that ride and holds the walk with a named reason (guildjobs.island_boat_step,
#2182); these tests hold the quester to the same helpers, to the same refusal
wording and back-off, and to the same crossing clock and walls. Rows are built
as the bridge reads them.
"""

import json
import unittest

import classquest
import guildjobs
import questers
from test_questers import giver, mirra, quest, world

DARKSHORE = 148
WALL = "no transport the module knows sails from this map to that map for this faction"
# The giver stands on the mainland of map 1, the member on the island.
MAINLAND_GIVER = (6000.0, 600.0)
ISLAND_AT = dict(map_id=1, x=9800.0, y=950.0, zone_id=141)


def cat():
    return world(
        extra_quests=[quest(40, DARKSHORE, 4, title="Darkshore Fish")],
        extra_givers=[
            giver(40, "start", 1040, 140, *MAINLAND_GIVER, map_id=1),
            giver(40, "end", 1040, 140, *MAINLAND_GIVER, map_id=1),
        ],
    )


def isle(**over):
    base = dict(level=5, quests_done=frozenset({1, 2, 3, 6, 20, 30}), **ISLAND_AT)
    base.update(over)
    return mirra(**base)


def refused_row(command, source, reason, age, retry=True, status="error"):
    body = {"outcome": "refused", "reason": reason, "retryable": retry}
    return {
        "id": 900 + age,
        "target_name": "Mirra",
        "command": command,
        "source": source,
        "status": status,
        "age": age,
        "result": json.dumps(body, separators=(",", ":")),
    }


def walk_refused(age):
    return refused_row(
        "walk-to-spawn creature:1040 near:12 max:20000",
        guildjobs.source_for(questers.WALK_ACTION, "Mirra"),
        classquest.ACROSS_WATER_REASON,
        age,
    )


def boat_refused(age, reason=WALL):
    command = classquest.ride_command(1, *classquest.ISLAND_BOAT_STOP)
    return refused_row(
        command,
        guildjobs.source_for(questers.CROSS_ACTION, "Mirra"),
        reason,
        age,
        retry=False,
    )


def plan(member=None, walks=(), boats=()):
    return questers.plan(
        cat(),
        member or isle(),
        questers.Clock(),
        0.0,
        tried=questers.attempts(walks),
        crossings=guildjobs.recent_from_rows(boats),
    )


class TheBoatStep(unittest.TestCase):
    def test_an_island_quester_with_a_mainland_giver_is_planned_the_boat(self):
        p = plan()
        self.assertIsNotNone(p.boat)
        self.assertIsNone(p.boat.walk)
        (row,) = p.boat.rows
        self.assertEqual(
            row.command, classquest.ride_command(1, *classquest.ISLAND_BOAT_STOP)
        )
        self.assertEqual(
            row.source, guildjobs.source_for(questers.CROSS_ACTION, "Mirra")
        )

    def test_a_quester_on_the_mainland_is_walked_as_before(self):
        p = plan(isle(x=6100.0, y=600.0))
        self.assertIsNone(p.boat)
        self.assertEqual(p.move.kind, classquest.TAKE)


class TheRefusalBackoff(unittest.TestCase):
    # A quester the bridge reads as on the mainland is planned the plain walk;
    # if the module still refuses it as across the water, the refusal holds it.
    def member(self):
        return isle(x=6100.0, y=600.0)

    def test_a_recent_refusal_writes_no_identical_walk(self):
        wait = classquest.BACKOFF_MINUTES[classquest.ACROSS_WATER_REASON]
        for age in (1, 3, wait - 1):
            with self.subTest(age=age):
                p = plan(self.member(), walks=[walk_refused(age)])
                self.assertIsNone(p.move)
                self.assertIn(classquest.ACROSS_WATER_REASON, p.line)

    def test_the_walk_is_asked_again_once_the_backoff_has_run(self):
        wait = classquest.BACKOFF_MINUTES[classquest.ACROSS_WATER_REASON]
        p = plan(self.member(), walks=[walk_refused(wait)])
        self.assertIsNotNone(p.move)

    def test_the_boat_is_not_held_by_the_walk_refusal_it_replaces(self):
        self.assertIsNotNone(plan(walks=[walk_refused(2)]).boat)


class TheHold(unittest.TestCase):
    def test_a_boat_the_module_refused_for_good_holds_the_move_with_a_name(self):
        p = plan(boats=[boat_refused(30)])
        self.assertIsNone(p.move)
        self.assertIsNone(p.boat)
        self.assertIn("across the water", p.line)
        self.assertIn("no boat step available", p.line)
        self.assertIn(WALL, p.line)

    def test_the_hold_lasts_the_long_back_off(self):
        cooldown = guildjobs.COOLDOWN_MINUTES[classquest.ACTION]
        for age in (cooldown + 1, classquest.CROSS_WALL_MINUTES - 1):
            with self.subTest(age=age):
                p = plan(boats=[boat_refused(age)])
                self.assertIsNone(p.move)
                self.assertIsNone(p.boat)
        late = plan(boats=[boat_refused(classquest.CROSS_WALL_MINUTES + 1)])
        self.assertIsNotNone(late.boat)

    def test_a_boat_in_flight_holds_the_quester_with_no_second_row(self):
        young = boat_refused(2)
        young["status"] = "verifying"
        young["result"] = ""
        p = plan(boats=[young])
        self.assertIsNone(p.boat)
        self.assertIsNone(p.move)


if __name__ == "__main__":
    unittest.main()
