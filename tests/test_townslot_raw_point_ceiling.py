"""A raw point errand is not re-issued inside its arrival ceiling.

The module lets a character go at a ground point it reached and does not walk
that standing aim again for fifteen minutes, but the passes that write ground
points never clear them. A second pass then wrote another point a minute later:
the leader left its quest drive for each, ended it at the point, went back to
the quest drive and was taken off it again, seven times in forty minutes.
"""

import unittest

import townslot

A = "at:0:-6673.9,-2174.3,244.2"
B = "at:0:2289.6,-5318.4,88.6"
# Pinned from the ticket, not read from the module under test.
CEILING = 900.0
WAIT = "wait"


def economy(_aim):
    return True


class TheAlternationBetweenTwoRawPointErrands(unittest.TestCase):
    def _ask(self, slot, claimant, aim, column, now, urgent=False):
        decision = slot.want(
            claimant=claimant,
            character="Leader",
            aim=aim,
            leader="Leader",
            column=column,
            retaskable=("",),
            now=now,
            urgent=urgent,
        )
        if decision.granted:
            slot.settle(decision, True, now)
        return decision

    def test_a_second_raw_point_waits_out_the_ceiling(self):
        slot = townslot.Slot(releasable=economy)
        first = self._ask(slot, "forge", A, "", 0.0)
        self.assertTrue(first.granted)
        # The module let the leader go at A and the column was emptied.
        again = self._ask(slot, "mail", B, "", 90.0)
        self.assertEqual(WAIT, again.verdict)
        self.assertIn("ground point", again.reason)
        # The same point is not written again either.
        self.assertEqual(WAIT, self._ask(slot, "forge", A, "", 200.0).verdict)

    def test_it_is_asked_again_after_the_ceiling(self):
        slot = townslot.Slot(releasable=economy)
        self._ask(slot, "forge", A, "", 0.0)
        late = self._ask(slot, "mail", B, "", CEILING + 1)
        self.assertTrue(late.granted)

    def test_a_keyword_errand_and_an_urgent_ask_are_not_held(self):
        slot = townslot.Slot(releasable=economy)
        self._ask(slot, "forge", A, "", 0.0)
        self.assertTrue(self._ask(slot, "auction", "auctioneer", "", 60.0).granted)
        slot = townslot.Slot(releasable=economy)
        self._ask(slot, "forge", A, "", 0.0)
        self.assertTrue(self._ask(slot, "mail", B, "", 60.0, urgent=True).granted)

    def test_the_standing_errand_is_still_held_not_refused(self):
        slot = townslot.Slot(releasable=economy)
        self._ask(slot, "forge", A, "", 0.0)
        hold = self._ask(slot, "forge", A, A, 30.0)
        self.assertEqual(townslot.SLOT_HOLD, hold.verdict)


if __name__ == "__main__":
    unittest.main()
