"""An aim that outlived its lease is not written again for the same writer.

The module lets go of a counter aim it cannot walk and leaves the column alone.
The aim then stood until another pass took the column, and the pass that wrote
it asked for the same aim again on its next cycle: the leader was sent, let go
of and sent again, and every other errand waited behind the loop.
"""

import unittest

import townslot

AIM = "auctioneer"


def economy(_aim):
    return True


class AnAimThatOutlivedItsLease(unittest.TestCase):
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

    def _preempted(self):
        slot = townslot.Slot(releasable=economy)
        self._ask(slot, "auction", AIM, "", 0.0)
        when = townslot.LEASE_SECONDS + 100.0
        taken = self._ask(slot, "vendor", "vendor", AIM, when)
        return slot, taken, when

    def test_the_writer_is_refused_the_same_aim_after_the_hand_back(self):
        slot, taken, when = self._preempted()
        self.assertEqual(townslot.SLOT_PREEMPT, taken.verdict)
        slot.let_go(taken.release, True, when)
        again = self._ask(slot, "auction", AIM, "", when + 300.0)
        self.assertEqual(townslot.SLOT_WAIT, again.verdict)
        self.assertIn("gave up", again.reason)

    def test_the_refusal_is_bounded(self):
        slot, taken, when = self._preempted()
        slot.let_go(taken.release, True, when)
        later = self._ask(
            slot, "auction", AIM, "", when + townslot.SPENT_SECONDS + 1.0
        )
        self.assertTrue(later.granted)

    def test_another_aim_of_the_same_writer_is_not_refused(self):
        slot, taken, when = self._preempted()
        slot.let_go(taken.release, True, when)
        other = self._ask(slot, "auction", "banker", "", when + 300.0)
        self.assertTrue(other.granted)

    def test_a_walk_taken_off_the_leader_young_is_not_spent(self):
        slot = townslot.Slot(releasable=economy)
        young = townslot.Holder("auction", "Leader", AIM, 100.0)
        slot.let_go(young, True, 150.0)
        again = self._ask(slot, "auction", AIM, "", 200.0)
        self.assertTrue(again.granted)

    def test_an_orphan_records_nothing(self):
        slot = townslot.Slot(releasable=economy)
        slot.let_go(townslot.Holder("", "Leader", AIM, 0.0), True, 9999.0)
        self.assertEqual({}, slot._spent)


if __name__ == "__main__":
    unittest.main()
