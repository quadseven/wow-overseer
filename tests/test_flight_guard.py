"""A leader holding a column errand must not fly away from its goal (#2541).

On 2026-11-14 a leader 35 yards from a mailbox errand goal left by air and
ended up about 12,000 yards away on another part of the continent, and no
log line named who started that flight. These tests pin the pure decision
this repo can own: given the standing errand, who started a flight, the
node, and where the flight would land, say whether it may go and write the
one log line that names the starter, the node and the yards from the goal.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import flightguard  # noqa: E402

ERRAND = "at:0:-8877.0,652.0,96.0"
GOAL = {"map_id": 0, "x": -8877.0, "y": 652.0}
NEAR_GOAL = {"map_id": 0, "x": -8842.0, "y": 652.0}  # 35 yards from the goal
FAR_AWAY = {"map_id": 0, "x": 2035.0, "y": -3855.8}  # the Plaguelands landing
NEARER = {"map_id": 0, "x": -8870.0, "y": 652.0}  # 7 yards from the goal


class TheLogLine(unittest.TestCase):
    def test_a_flight_by_an_errand_holder_writes_one_line_naming_the_starter(self):
        check = flightguard.assess(
            leader="Leader",
            errand=ERRAND,
            starter="rpg",
            node=123,
            takeoff=NEAR_GOAL,
            destination=FAR_AWAY,
        )
        self.assertIsNotNone(check)
        self.assertEqual(1, len(check.log_line.splitlines()))
        self.assertIn("upstream rpg state", check.log_line)
        self.assertIn("node 123", check.log_line)
        self.assertIn("35 yards from the errand goal", check.log_line)

    def test_each_starter_is_named_in_its_own_words(self):
        for starter, words in (
            ("module", "module leg"),
            ("rpg", "upstream rpg state"),
            ("quest", "quest drive"),
        ):
            with self.subTest(starter=starter):
                check = flightguard.assess(
                    leader="Leader",
                    errand=ERRAND,
                    starter=starter,
                    node=1,
                    takeoff=NEAR_GOAL,
                    destination=NEARER,
                )
                self.assertIn(words, check.log_line)

    def test_no_errand_means_no_line_and_no_verdict(self):
        self.assertIsNone(
            flightguard.assess(
                leader="Leader",
                errand="",
                starter="rpg",
                node=1,
                takeoff=NEAR_GOAL,
                destination=FAR_AWAY,
            )
        )

    def test_an_errand_without_a_ground_goal_cannot_be_judged(self):
        """A role keyword names no coordinate, so yards from the goal is a
        number nobody holds; inventing one would be a fabricated reading."""
        self.assertIsNone(
            flightguard.assess(
                leader="Leader",
                errand="vendor",
                starter="rpg",
                node=1,
                takeoff=NEAR_GOAL,
                destination=FAR_AWAY,
            )
        )


class TheRefusal(unittest.TestCase):
    def test_a_leader_35_yards_from_the_goal_does_not_leave_by_flight(self):
        """The 2026-11-14 case, replayed: takeoff 35 yards from the goal,
        destination about 12,000 yards from it."""
        check = flightguard.assess(
            leader="Leader",
            errand=ERRAND,
            starter="rpg",
            node=123,
            takeoff=NEAR_GOAL,
            destination=FAR_AWAY,
        )
        self.assertTrue(check.refused)
        self.assertIn("farther from the errand goal", check.reason)

    def test_a_flight_toward_the_goal_is_allowed(self):
        check = flightguard.assess(
            leader="Leader",
            errand=ERRAND,
            starter="module",
            node=7,
            takeoff={"map_id": 0, "x": -8000.0, "y": 652.0},
            destination=NEARER,
        )
        self.assertFalse(check.refused)

    def test_a_flight_to_another_map_is_refused(self):
        check = flightguard.assess(
            leader="Leader",
            errand=ERRAND,
            starter="quest",
            node=9,
            takeoff=NEAR_GOAL,
            destination={"map_id": 1, "x": -8842.0, "y": 652.0},
        )
        self.assertTrue(check.refused)

    def test_the_rpg_state_is_gated_while_an_errand_stands(self):
        """`new rpg` may not start TravelFlight on its own while the column
        holds an errand; with no errand it is nobody's business here."""
        self.assertTrue(flightguard.rpg_flight_gated(ERRAND))
        self.assertTrue(flightguard.rpg_flight_gated("vendor"))
        self.assertFalse(flightguard.rpg_flight_gated(""))
        self.assertFalse(flightguard.rpg_flight_gated(None))

    def test_an_unknown_starter_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            flightguard.assess(
                leader="Leader",
                errand=ERRAND,
                starter="somebody",
                node=1,
                takeoff=NEAR_GOAL,
                destination=NEARER,
            )


if __name__ == "__main__":
    unittest.main()
