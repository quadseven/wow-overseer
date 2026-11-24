"""A main-hand cast refused for want of a Runeforge in reach walks again.

Worked example: the walk to the forge ends short (it was cut off, or the
member was still on its way), the cast row is refused "no Runeforge is within
spell range", and that sentence was not among the out-of-reach refusals. The
use was read as a plain wait: the member asked again where it stood, never
walked toward the forge, and the quest was given up after the same refusal
nine times. The refusal now asks for one more walk to the forge.
"""

import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import classuse

WHY = "no Runeforge is within spell range"


def refused(detail=WHY):
    body = {"outcome": "refused", "reason": detail, "retry": "later"}
    return classuse.judge("Alpha", "error", detail, body)


class MainhandRewalkTests(unittest.TestCase):
    def test_a_forge_out_of_reach_asks_for_a_walk_again(self):
        answer = refused()
        self.assertEqual(answer.state, classuse.RETRY)
        self.assertTrue(answer.rewalk)

    def test_the_other_main_hand_refusals_do_not_walk(self):
        for why in ("the main-hand spell is on cooldown",):
            self.assertFalse(refused(why).rewalk)

    def test_the_known_out_of_reach_refusals_still_walk(self):
        for why in classuse.OUT_OF_REACH:
            self.assertTrue(refused(why).rewalk)


if __name__ == "__main__":
    unittest.main()
