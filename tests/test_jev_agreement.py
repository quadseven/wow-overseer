"""#356: an answer that agrees with the heuristic below the floor is Jev's.

Measured over 24 hours on the dev realm: 81 activity_choice calls, 18 movement
and 5 run_recovery had Jev name exactly the choice carried out, and each was
recorded `acted=heuristic` because its confidence sat under the floor. The goal
counts Jev's answer as acted on when it is what was done.
"""

import unittest

import jev
import jev_activity
import jev_movement
import jev_recovery


class AgreementIsJevs(unittest.TestCase):
    def policies(self):
        return (
            jev_movement.policy({}),
            jev_activity.policy({}),
            jev_recovery.policy(jev_recovery.KIND_RECOVERY, {}),
            jev_recovery.policy(jev_recovery.KIND_STALL, {}),
        )

    def test_an_agreement_below_the_floor_is_recorded_both(self):
        for rule in self.policies():
            with self.subTest(kind=rule.kind):
                self.assertEqual(rule.acted("a", "a", 0.05), jev.BOTH)

    def test_a_disagreement_below_the_floor_still_leaves_the_heuristic(self):
        for rule in self.policies():
            with self.subTest(kind=rule.kind):
                self.assertEqual(rule.acted("a", "b", 0.05), jev.HEURISTIC)


if __name__ == "__main__":
    unittest.main()
