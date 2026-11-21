"""class_boat_step answers each of its gates once (#2192).

The planner tests in test_classquest_across_water.py drive the boat through
the whole plan. These call the step itself, one refusal per gate: a member not
across the water (another map, or already on the mainland), a dead member, a
module wall, a crossing still cooling, and the open case that plans the ride.
The online and out-of-combat gates sit in the planner above the step, so they
are pinned through the plan.
"""

import types
import unittest

import classquest
import guildjobs
from test_classquest import class_plan, class_steps
from test_classquest_across_water import (
    WALL,
    boat_command,
    boat_row,
    island,
    recent,
    row,
)

# A giver on the mainland of the island's map, as the class chain names one.
MAINLAND_SPOT = guildjobs.Spot("creature", 19732, 1, -282.0, -4164.0, "Giver")
MOVE = types.SimpleNamespace(quest=1505, said="takes the class quest")


def step_for(member, spot=MAINLAND_SPOT, rows=()):
    return guildjobs.class_boat_step(member, MOVE, spot, recent(*rows))


class EachGate(unittest.TestCase):
    def test_an_island_member_with_a_mainland_spot_is_planned_the_ride(self):
        step, said, note = step_for(island())
        self.assertEqual(step.rows[0].command, boat_command())
        self.assertEqual(said, MOVE.said)
        self.assertEqual(note, "")

    def test_a_member_on_another_map_gets_no_boat_step(self):
        self.assertIsNone(step_for(island(map_id=0)))

    def test_a_member_already_on_the_mainland_gets_no_boat_step(self):
        self.assertIsNone(step_for(island(x=-282.0, y=-4164.0)))

    def test_a_spot_on_another_map_gets_no_boat_step(self):
        far = guildjobs.Spot("creature", 1, 0, -282.0, -4164.0)
        self.assertIsNone(step_for(island(), far))

    def test_a_dead_member_is_held_with_a_name_and_no_step(self):
        step, _said, note = step_for(island(alive=False))
        self.assertIsNone(step)
        self.assertIn("is dead", note)

    def test_a_module_wall_holds_the_ride_with_the_refusal_named(self):
        walled = boat_row("Isle", 30, WALL, "error")
        step, said, note = step_for(island(), rows=(walled,))
        self.assertIsNone(step)
        self.assertEqual(said, "")
        self.assertIn("no boat step available", note)
        self.assertIn(WALL, note)

    def test_a_crossing_still_cooling_holds_the_ride_with_no_note(self):
        young = boat_row("Isle", 1)
        step, said, note = step_for(island(), rows=(young,))
        self.assertIsNone(step)
        self.assertEqual(said, MOVE.said)
        self.assertEqual(note, "")

    def test_a_far_walk_backoff_does_not_hold_the_ride(self):
        # DECIDED (#2192): the boat step stays ahead of _class_held. The walk
        # backoff answers a refused far walk, and a ride is not a far walk.
        held = row(
            "Isle",
            "walk-to-spawn creature:19732 max:30000",
            classquest.ACTION + "-walk",
            classquest.REALM_FULL_REASON,
            1,
        )
        rows = recent(held)
        self.assertGreater(guildjobs.class_walk_backoff("Isle", rows), 0)
        steps = class_steps(class_plan([island()], recent=rows))
        self.assertEqual([s.rows[0].command for s in steps], [boat_command()])


class GatesAbovetheStep(unittest.TestCase):
    def rides(self, member):
        return [
            s
            for s in class_steps(class_plan([member]))
            if s.rows and s.rows[0].command.startswith(classquest.RIDE_VERB)
        ]

    def test_an_offline_island_member_is_planned_no_ride(self):
        self.assertEqual(self.rides(island(online=False)), [])

    def test_a_member_in_combat_is_planned_no_ride(self):
        self.assertEqual(self.rides(island(in_combat=True)), [])

    def test_the_same_member_online_and_out_of_combat_is_planned_the_ride(self):
        self.assertEqual(len(self.rides(island())), 1)


if __name__ == "__main__":
    unittest.main()
