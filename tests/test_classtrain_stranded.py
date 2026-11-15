"""A member with no class trainer on its map is refused once, not every three hours
(ticket 2624).

Read on the dev realm on 2026-11-15: 8 Draenei shamans on Kalimdor were walked
to a class trainer 66 times in a day and refused 66 times with the module's
non-retryable "no trainer of this character's class on this map". The walk's
only cooldown is three hours, so the same refusal came back at every one of
them. The refusal names the map (`"map":1` in its result), so it holds for as
long as the member stands on that map.
"""

import json
import unittest

import classtrain
import guildroute

REASON = (
    "no trainer of this character's class on this map has a class spell to teach it now"
)


def refusal(name, map_id=1, age=180, reason=REASON, retryable=False, status="error"):
    return {
        "target_name": name,
        "source": "guildtrain:%s" % name,
        "status": status,
        "age": age,
        "result": json.dumps(
            {
                "outcome": "refused",
                "reason": reason,
                "retryable": retryable,
                "map": map_id,
            }
        ),
    }


def taught(name, age=10):
    return {
        "target_name": name,
        "source": "guildtrain:%s" % name,
        "status": "applied",
        "age": age,
        "result": json.dumps({"outcome": "arrived", "taught": [123]}),
    }


def walker(name, map_id=1):
    return guildroute.Walker(
        name=name,
        map_id=map_id,
        in_combat=False,
        unwalkable="",
        cohort="",
        yards=300.0,
        aim="at:0:1,2,3",
        by_row=True,
    )


class WhoIsStranded(unittest.TestCase):
    def test_a_refusal_for_no_trainer_on_the_map_strands_the_member_there(self):
        self.assertEqual(classtrain.stranded([refusal("Brakk")]), {"Brakk": 1})

    def test_an_older_refusal_is_read_as_far_back_as_the_rows_go(self):
        self.assertEqual(
            classtrain.stranded([refusal("Brakk", age=20 * 24 * 60)]), {"Brakk": 1}
        )

    def test_a_later_walk_that_taught_something_frees_the_member(self):
        rows = [refusal("Brakk", age=600), taught("Brakk", age=10)]
        self.assertEqual(classtrain.stranded(rows), {})

    def test_another_refusal_is_not_a_strand(self):
        rows = [
            refusal("A", reason="character is moving", retryable=True),
            refusal("B", reason="a walk is already under way", retryable=True),
        ]
        self.assertEqual(classtrain.stranded(rows), {})

    def test_the_newest_row_decides(self):
        rows = [refusal("Brakk", map_id=1, age=900), refusal("Brakk", map_id=0, age=5)]
        self.assertEqual(classtrain.stranded(rows), {"Brakk": 0})

    def test_unreadable_rows_strand_nobody(self):
        rows = [{"target_name": "X", "source": "guildtrain:X", "result": "not json"}]
        self.assertEqual(classtrain.stranded(rows), {})


class InThePlan(unittest.TestCase):
    def trainee(self, name):
        due = classtrain.due(
            [
                {
                    "spell": 331,
                    "level": 4,
                    "cost": 100,
                    "req1": 0,
                    "req2": 0,
                    "req3": 0,
                }
            ],
            set(),
            20,
        )
        return classtrain.Trainee(name, "Cave", 20, 5000, due, True)

    def plan(self, stranded):
        return classtrain.plan(
            [self.trainee("Brakk")],
            {"Brakk": walker("Brakk", map_id=1)},
            set(),
            set(),
            stranded=stranded,
        )

    def test_a_stranded_member_on_the_same_map_is_not_walked_and_is_named_once(self):
        walks, notes = self.plan({"Brakk": 1})
        self.assertEqual(walks, [])
        self.assertTrue(any("no class trainer" in n and "map 1" in n for n in notes))

    def test_a_member_that_changed_map_is_walked_again(self):
        walks, _notes = self.plan({"Brakk": 0})
        self.assertEqual([w.name for w in walks], ["Brakk"])

    def test_an_unstranded_member_is_walked_as_before(self):
        walks, _notes = self.plan({})
        self.assertEqual([w.name for w in walks], ["Brakk"])


class TheSummaryCountsTheLastDayOnly(unittest.TestCase):
    def test_a_strand_read_from_weeks_back_is_not_a_walk_of_the_day(self):
        rows = [refusal("Brakk", age=20 * 24 * 60)]
        self.assertIn("0 class trainer walk(s)", classtrain.summary(rows))


if __name__ == "__main__":
    unittest.main()
