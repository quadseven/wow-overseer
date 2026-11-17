"""A sale trip the ledger did not record keeps its place in the column (#1261).

THE RECORDED SHAPE, wow-dev 2026-11-16, Zug's family, after a bridge restart.
The leader carried `travel_npc = 'vendor'` and stood at the counter; the
ledger had no entry for it, so `_reconcile` read it as an orphan:

    18:56:11 mail takes the traveller Zug from an unknown writer: 'vendor' has
             held the family's one travel column for 0s, past its 0s lease
    18:58:01 town errand takes the traveller Zug from an unknown writer:
             'vendor' has held the family's one travel column for 0s, past
             its 0s lease

An orphan ranked behind every named pass (`walk_rank` 2), and the urgent ask
zeroes the orphan lease, so a mail pass or a town errand cut it down in the
same call that first saw it. The sale trip never ran its sales and the family
sat at the bag floor. These tests fail before the aim, not the claimant, ranks
an orphan.
"""

import unittest

import townslot

LEADER = "Zug"
ORPHAN_LEASE = townslot.ORPHAN_GROUND_GRACE_SECONDS


def economy(aim):
    text = str(aim or "")
    return text in ("vendor", "banker", "repair", "auctioneer") or text.startswith(
        "at:"
    )


def ask(slot, claimant, aim, column, now, urgent=False):
    return slot.want(
        claimant=claimant,
        character=LEADER,
        aim=aim,
        leader=LEADER,
        column=column,
        retaskable=("", aim),
        now=now,
        urgent=urgent,
    )


class AnOrphanSaleTripIsNotCutDownAtOnce(unittest.TestCase):
    def slot(self):
        return townslot.Slot(releasable=economy)

    def test_an_urgent_mail_pass_waits_behind_an_orphan_vendor_aim(self):
        slot = self.slot()
        d = ask(
            slot, "mail", "at:0:-6673.9,-2174.3,244.2", "vendor", 100.0, urgent=True
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict, d.reason)

    def test_an_urgent_town_errand_waits_behind_an_orphan_vendor_aim(self):
        slot = self.slot()
        d = ask(
            slot, "town errand", "at:0:1644.8,276.2,-62.3", "vendor", 100.0, urgent=True
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict, d.reason)

    def test_the_wait_holds_while_the_sale_trip_is_inside_its_bound(self):
        slot = self.slot()
        ask(slot, "mail", "at:0:1,2,3", "vendor", 100.0, urgent=True)
        d = ask(
            slot, "mail", "at:0:1,2,3", "vendor", 100.0 + ORPHAN_LEASE - 1, urgent=True
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict, d.reason)

    # Pins the orphan bound only: a trip that cannot finish is released by the lease.
    # How sellers held far away rejoin the leader is covered by the vendor wait tests.
    def test_a_trip_that_cannot_finish_is_released_within_the_orphan_bound(self):
        slot = self.slot()
        ask(slot, "mail", "at:0:1,2,3", "vendor", 100.0, urgent=True)
        d = ask(
            slot, "mail", "at:0:1,2,3", "vendor", 100.0 + ORPHAN_LEASE + 1, urgent=True
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict, d.reason)

    def test_an_orphan_of_no_bag_room_aim_is_still_cut_by_a_bag_room_pass(self):
        slot = self.slot()
        d = ask(slot, "economy", "vendor", "at:0:9,9,9", 100.0, urgent=True)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict, d.reason)

    def test_a_bag_room_pass_still_cuts_an_orphan_that_is_not_a_bag_room_aim(self):
        slot = self.slot()
        d = ask(slot, "bags", "vendor", "at:0:9,9,9", 100.0, urgent=True)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict, d.reason)

    def test_a_named_holder_rank_is_unchanged(self):
        self.assertTrue(townslot.urgency_cuts("economy", None, False))
        holder = townslot.Holder(claimant="", character=LEADER, aim="vendor", since=0.0)
        self.assertFalse(townslot.urgency_cuts("mail", holder, False))
        self.assertFalse(townslot.urgency_cuts("town errand", holder, False))
        ground = townslot.Holder(
            claimant="", character=LEADER, aim="at:0:1,2,3", since=0.0
        )
        self.assertTrue(townslot.urgency_cuts("mail", ground, False))


class AReservingErrandDoesNotCutAnOrphanSaleTripEither(unittest.TestCase):
    """wow-dev 2026-11-16 22:44: the errand had reserved the traveller, and a
    reservation made `urgency_cuts` return True before the orphan's rank was
    read, so the grace of #2771 never applied on that path."""

    def test_a_reserved_town_errand_waits_behind_an_orphan_vendor_aim(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("town errand", 99.0, "bag room")
        d = ask(
            slot, "town errand", "at:0:1644.8,276.2,-62.3", "vendor", 100.0, urgent=True
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict, d.reason)

    def test_a_reserved_errand_still_cuts_the_orphan_after_the_grace(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("town errand", 99.0, "bag room")
        ask(slot, "town errand", "at:0:1,2,3", "vendor", 100.0, urgent=True)
        d = ask(
            slot,
            "town errand",
            "at:0:1,2,3",
            "vendor",
            100.0 + ORPHAN_LEASE + 1,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict, d.reason)

    def test_a_reservation_still_cuts_any_other_holder(self):
        ground = townslot.Holder(
            claimant="", character=LEADER, aim="at:0:1,2,3", since=0.0
        )
        self.assertTrue(townslot.urgency_cuts("town errand", ground, True))


if __name__ == "__main__":
    unittest.main()
