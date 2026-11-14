"""A class quest on the mainland of the island's own map takes the boat (#2182).

Teldrassil is an island on map 1. A spawn walk from the island to a spawn on
the mainland of the same map is refused by the module as "across the water"
(retryable: a cross row takes the boat), and a bridge that plans it as a plain
walk asks the same walk again every class cool-down, so the member never starts
its class quest. These tests hold the planner to the same-map ride the module
itself makes the first leg of an island crossing, to a named hold when no boat
step can be planned, and to a back-off much longer than the class cool-down
for the refusal itself. Rows are built as the bridge reads them.
"""

import json
import unittest

import classquest
import guildjobs
import modsource
from test_classquest import class_plan, class_steps, who

# A point on the island (the Teldrassil box); the quest's giver stands on the
# mainland of the same map.
ISLAND = dict(map_id=1, x=9800.0, y=950.0, quests_done=frozenset({1505}))
WALL = "no transport the module knows sails from this map to that map for this faction"


def island(name="Isle", **over):
    return who(name, **dict(ISLAND, **over))


def row(name, command, action, reason, age, retry=True, status="error"):
    body = {"outcome": "refused", "reason": reason, "retryable": retry}
    return {
        "id": 910 + age,
        "target_name": name,
        "command": command,
        "source": guildjobs.source_for(action, name),
        "status": status,
        "age": age,
        "result": json.dumps(body, separators=(",", ":")) if reason else "",
    }


def recent(*rows):
    return guildjobs.recent_from_rows(rows)


def boat_command():
    return classquest.ride_command(1, *classquest.ISLAND_BOAT_STOP)


def walk_refused(name, age):
    return row(
        name,
        "walk-to-spawn creature:19732 max:30000",
        classquest.ACTION + "-walk",
        classquest.ACROSS_WATER_REASON,
        age,
    )


def boat_row(name, age, reason="", status="applied"):
    return row(
        name,
        boat_command(),
        classquest.CROSS_ACTION,
        reason,
        age,
        retry=False,
        status=status,
    )


def walks(result):
    return [s for s in class_steps(result) if s.walk is not None]


def rides(result):
    return [
        s
        for s in class_steps(result)
        if s.rows and s.rows[0].command.startswith(classquest.RIDE_VERB)
    ]


class TheBoatStep(unittest.TestCase):
    def test_an_island_member_with_a_mainland_spawn_is_planned_the_boat(self):
        result = class_plan([island()])
        self.assertEqual(walks(result), [])
        steps = rides(result)
        self.assertEqual(len(steps), 1)
        self.assertNotIn("Isle", result.class_holds)
        step = steps[0]
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].kind, "job")
        self.assertEqual(step.rows[0].command, boat_command())
        self.assertEqual(
            step.rows[0].source,
            guildjobs.source_for(classquest.CROSS_ACTION, "Isle"),
        )

    def test_the_ride_names_a_stop_on_the_island_map(self):
        self.assertTrue(boat_command().startswith("ride-to-stop map:1 x:6341.4 "))

    def test_a_member_on_the_mainland_is_walked_as_before(self):
        result = class_plan([who(quests_done=frozenset({1505}))])
        self.assertEqual(rides(result), [])
        self.assertEqual(len(walks(result)), 1)

    def test_a_boat_in_flight_holds_the_member_with_no_second_row(self):
        young = boat_row("Isle", 5, status="verifying")
        self.assertEqual(class_steps(class_plan([island()], recent=recent(young))), [])

    def test_the_boat_is_not_held_by_the_walk_refusal_it_replaces(self):
        result = class_plan([island()], recent=recent(walk_refused("Isle", 2)))
        self.assertEqual(len(rides(result)), 1)

    def test_a_walk_refusal_older_than_the_boat_does_not_hold_the_walk(self):
        landed = who("Landed", quests_done=frozenset({1505}))
        rows = (walk_refused("Landed", 50), boat_row("Landed", 40))
        result = class_plan([landed], recent=recent(*rows))
        self.assertEqual(len(walks(result)), 1)


class TheHold(unittest.TestCase):
    def test_a_boat_the_module_refused_for_good_holds_the_walk_with_a_name(self):
        result = class_plan(
            [island()], recent=recent(boat_row("Isle", 30, WALL, "error"))
        )
        self.assertEqual(class_steps(result), [])
        notes = " ".join(result.notes) + " " + result.lines.get("Isle", "")
        self.assertIn("across the water", notes)
        self.assertIn("no boat step available", notes)

    def test_the_hold_outlasts_the_class_cooldown_many_times_over(self):
        cooldown = guildjobs.COOLDOWN_MINUTES[classquest.ACTION]
        self.assertGreaterEqual(classquest.CROSS_WALL_MINUTES, 6 * cooldown)
        for age in (cooldown + 1, 3 * cooldown, classquest.CROSS_WALL_MINUTES - 1):
            with self.subTest(age=age):
                refused = boat_row("Isle", age, WALL, "error")
                held = class_plan([island()], recent=recent(refused))
                self.assertEqual(class_steps(held), [])
        late = boat_row("Isle", classquest.CROSS_WALL_MINUTES + 1, WALL, "error")
        self.assertEqual(len(rides(class_plan([island()], recent=recent(late)))), 1)


class TheRefusalBackoff(unittest.TestCase):
    # A member the bridge reads as on the mainland is planned the plain walk;
    # if the module still refuses it as across the water (its zone test is the
    # module's own), the refusal is what holds the walk back.
    def member(self):
        return who("Blind", quests_done=frozenset({1505}))

    def test_the_backoff_is_much_longer_than_the_class_cooldown(self):
        cooldown = guildjobs.COOLDOWN_MINUTES[classquest.ACTION]
        wait = classquest.BACKOFF_MINUTES[classquest.ACROSS_WATER_REASON]
        self.assertGreaterEqual(wait, 6 * cooldown)

    def test_a_recent_refusal_writes_no_identical_walk(self):
        wait = classquest.BACKOFF_MINUTES[classquest.ACROSS_WATER_REASON]
        for age in (1, guildjobs.COOLDOWN_MINUTES[classquest.ACTION] + 1, wait - 1):
            with self.subTest(age=age):
                refused = recent(walk_refused("Blind", age))
                result = class_plan([self.member()], recent=refused)
                self.assertEqual(walks(result), [])

    def test_the_walk_is_asked_again_once_the_backoff_has_run(self):
        wait = classquest.BACKOFF_MINUTES[classquest.ACROSS_WATER_REASON]
        result = class_plan([self.member()], recent=recent(walk_refused("Blind", wait)))
        self.assertEqual(len(walks(result)), 1)


class TheModuleWording(unittest.TestCase):
    def test_the_refusal_is_the_modules_own_literal(self):
        src = modsource.read(modsource.DECISIONS_H, encoding="utf-8")
        self.assertIn('"%s"' % classquest.ACROSS_WATER_REASON, src)

    def test_the_boat_stop_is_the_one_the_module_rides_first(self):
        src = modsource.read(modsource.DECISIONS_H, encoding="utf-8")
        for axis, value in zip("XY", classquest.ISLAND_BOAT_STOP, strict=True):
            self.assertIn("AUBERDINE_STOP_%s = %.2ff" % (axis, value), src)


if __name__ == "__main__":
    unittest.main()
