"""A short town stop at a mailbox, a banker or a vault is ordered, not raced (#276).

Measured on the dev realm on 2026-09-24. The Alliance family's travel column
changed hands every three to four minutes for a whole day: the mail pass took
it 11 times and the bank pass 11 times, and an urgent listing walk took it off
them again after 81 to 219 seconds, so no walk to a mailbox or a banker ever
landed. Grug held 22 letters with 2,609 gold in them. On the Horde side the
family's campaign owned the traveller, and every town pass waited for it.

Pinned here, on the pure ledger: a counter in the same town is a stop; a stop
takes a free column ahead of the queue and never preempts; nobody preempts a
stop inside its window, urgent or not; a campaign lets one stop per claimant
per window through into a free column, and does not hand it back while it
walks.
"""

import unittest

import townslot


def economy(aim):
    return aim in ("vendor", "banker", "repair", "auctioneer") or aim.startswith("at:")


MAILBOX = "at:1:-7154.4,-3829.5,8.8"


def slot():
    return townslot.Slot(releasable=economy)


def ask(s, claimant, aim, now, *, column="", distance=None, urgent=False):
    return s.want(
        claimant=claimant,
        character="Grug",
        aim=aim,
        leader="Grug",
        column=column,
        retaskable=("", aim),
        now=now,
        urgent=urgent,
        distance=distance,
    )


class WhatCountsAsAStop(unittest.TestCase):
    def test_the_three_counters_in_the_same_town(self):
        for claimant in ("mail", "bank", "guild bank"):
            self.assertTrue(townslot.is_town_stop(claimant, 40.0), claimant)
            self.assertTrue(
                townslot.is_town_stop(claimant, townslot.TOWN_STOP_YARDS), claimant
            )

    def test_a_counter_across_the_zone_is_an_ordinary_trip(self):
        """The measured family stood 790 yards from Gadgetzan's mailbox."""
        self.assertFalse(townslot.is_town_stop("mail", 790.0))
        self.assertFalse(townslot.is_town_stop("mail", townslot.TOWN_STOP_YARDS + 1))

    def test_an_unmeasured_distance_is_not_a_stop(self):
        self.assertFalse(townslot.is_town_stop("mail", None))
        self.assertFalse(townslot.is_town_stop("mail", "far"))
        self.assertFalse(townslot.is_town_stop("mail", -1.0))

    def test_no_other_claimant_is_a_stop(self):
        for claimant in ("auction", "economy", "clearance", "towntrip", "gather"):
            self.assertFalse(townslot.is_town_stop(claimant, 10.0), claimant)


class AStopGoesAheadOfTheQueueIntoAFreeColumn(unittest.TestCase):
    def queue(self):
        """Clearance waited first and the mail pass was served since, so an
        ordinary mail ask stands aside for it."""
        s = slot()
        s.settle(ask(s, "mail", MAILBOX, 0.0), True, 0.0)
        s.holder = None
        ask(s, "clearance", "at:1:5,5,5", 10.0, column="vendor")
        s.holder = None
        return s

    def test_an_ordinary_trip_stands_aside_for_the_older_want(self):
        s = self.queue()
        d = ask(s, "mail", MAILBOX, 100.0, distance=790.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("stands aside", d.reason)

    def test_a_stop_in_the_same_town_takes_the_free_column(self):
        s = self.queue()
        d = ask(s, "mail", MAILBOX, 100.0, distance=40.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)
        self.assertTrue(d.stop)
        self.assertIn("short town stop", d.reason)

    def test_a_stop_never_preempts_a_holder(self):
        s = slot()
        s.settle(ask(s, "economy", "vendor", 0.0), True, 0.0)
        d = ask(s, "mail", MAILBOX, 10.0, column="vendor", distance=20.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIsNone(d.release)


class NobodyPreemptsAStopInsideItsWindow(unittest.TestCase):
    def taken(self):
        s = slot()
        d = ask(s, "mail", MAILBOX, 0.0, distance=40.0)
        s.settle(d, True, 0.0)
        return s

    def test_the_measured_case_an_urgent_listing_walk_waits(self):
        """The auction pass took the mail pass's column 81 seconds in."""
        s = self.taken()
        d = ask(s, "auction", "auctioneer", 81.0, column=MAILBOX, urgent=True)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("short town stop", d.reason)
        self.assertIsNone(d.release)

    def test_an_idle_request_waits_too(self):
        s = self.taken()
        d = s.want_idle(
            claimant="gather", character="Grug", leader="Grug", column=MAILBOX, now=30.0
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_past_the_window_urgency_preempts_again(self):
        s = self.taken()
        d = ask(
            s,
            "auction",
            "auctioneer",
            townslot.TOWN_STOP_SECONDS + 1,
            column=MAILBOX,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_the_stop_itself_holds(self):
        s = self.taken()
        d = ask(s, "mail", MAILBOX, 60.0, column=MAILBOX, distance=20.0)
        self.assertEqual(townslot.SLOT_HOLD, d.verdict)


class ACampaignLetsOneShortStopThrough(unittest.TestCase):
    def campaign(self):
        s = slot()
        s.yield_to_campaign("dungeon:ragefire on Grug")
        return s

    def test_a_far_trip_still_waits_for_the_campaign(self):
        s = self.campaign()
        d = ask(s, "mail", MAILBOX, 0.0, distance=790.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("campaign owns the traveller", d.reason)

    def test_an_ordinary_claimant_still_waits(self):
        s = self.campaign()
        d = ask(s, "auction", "auctioneer", 0.0, distance=20.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_a_near_stop_takes_a_free_column(self):
        s = self.campaign()
        d = ask(s, "mail", MAILBOX, 0.0, distance=40.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)
        self.assertTrue(d.stop)
        self.assertIn("the approach waits for the stop", d.reason)

    def test_never_over_the_campaigns_own_aim(self):
        s = self.campaign()
        d = ask(s, "mail", MAILBOX, 0.0, column="at:1:1811,-4410,-18", distance=40.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("the column holds", d.reason)

    def test_the_stop_holds_while_it_walks(self):
        s = self.campaign()
        s.settle(ask(s, "mail", MAILBOX, 0.0, distance=40.0), True, 0.0)
        d = ask(s, "mail", MAILBOX, 30.0, column=MAILBOX, distance=20.0)
        self.assertEqual(townslot.SLOT_HOLD, d.verdict)

    def test_one_stop_per_claimant_per_window(self):
        s = self.campaign()
        s.settle(ask(s, "mail", MAILBOX, 0.0, distance=40.0), True, 0.0)
        s.holder = None  # the walk landed and the module released it
        again = ask(s, "mail", MAILBOX, 600.0, distance=40.0)
        self.assertEqual(townslot.SLOT_WAIT, again.verdict)
        self.assertIn("one stop per", again.reason)
        other = ask(s, "bank", "banker", 600.0, distance=60.0)
        self.assertEqual(townslot.SLOT_TAKE, other.verdict)
        later = ask(
            s, "mail", MAILBOX, townslot.CAMPAIGN_STOP_EVERY_SECONDS + 1, distance=40.0
        )
        self.assertEqual(townslot.SLOT_TAKE, later.verdict)

    def test_the_stop_is_not_handed_back_while_it_walks(self):
        s = self.campaign()
        s.settle(ask(s, "mail", MAILBOX, 0.0, distance=40.0), True, 0.0)
        self.assertIsNotNone(s.stop_live(60.0))
        held = s.campaign_release(
            leader="Grug",
            column=MAILBOX,
            now=60.0,
            ground=lambda a: a.startswith("at:"),
        )
        self.assertIsNone(held)

    def test_past_its_window_the_campaign_takes_it_back(self):
        s = self.campaign()
        s.settle(ask(s, "mail", MAILBOX, 0.0, distance=40.0), True, 0.0)
        later = townslot.TOWN_STOP_SECONDS + 1
        self.assertIsNone(s.stop_live(later))
        held = s.campaign_release(
            leader="Grug",
            column=MAILBOX,
            now=later,
            ground=lambda a: a.startswith("at:"),
        )
        self.assertIsNotNone(held)
        self.assertEqual("mail", held.claimant)


if __name__ == "__main__":
    unittest.main()
