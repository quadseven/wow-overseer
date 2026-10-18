"""A vendor in the same town is a short stop, so a campaign lets a sale through.

Health, 2026-10-15: the first family's leader read "Carrying things to sell,
waiting for a vendor within reach" for 3.3 hours from 20:30:17Z, with two of
the family on the same step from the same second. The family was on its
dungeon campaign, and while a campaign owns the traveller the town slot
answers every pass with a wait except a short stop at a counter in the same
town (#276). The mailbox, the banker and the vault were stops; the vendor was
not, because the vendor pass never said how far its counter was. So the trip
#1057 takes after a 30 minute wait was refused for the whole campaign, and the
sellers stayed held until it ended.

Pinned here: the vendor pass is a stop claimant, a campaign lets its near
vendor through once per window, a far vendor still waits, and the vendor pass
says how far its counter is only when that makes it a stop.
"""

import pathlib
import unittest

import townslot

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def economy(aim):
    return aim in ("vendor", "banker", "repair", "auctioneer") or aim.startswith("at:")


def campaign():
    s = townslot.Slot(releasable=economy)
    s.yield_to_campaign("dungeon:blackfathom on Grug")
    return s


def sell(s, now, *, distance, column=""):
    """The vendor pass's own claim: urgent, on the leader, for `vendor`."""
    return s.want(
        claimant="economy",
        character="Grug",
        aim="vendor",
        leader="Grug",
        column=column,
        retaskable=("", "vendor"),
        now=now,
        urgent=True,
        distance=distance,
    )


class TheVendorIsATownStop(unittest.TestCase):
    def test_a_vendor_in_the_same_town_is_a_stop(self):
        self.assertTrue(townslot.is_town_stop("economy", 60.0))

    def test_a_vendor_across_the_zone_is_an_ordinary_trip(self):
        self.assertFalse(townslot.is_town_stop("economy", townslot.TOWN_STOP_YARDS + 1))


class ACampaignLetsTheSaleThrough(unittest.TestCase):
    def test_a_near_vendor_takes_the_free_column(self):
        d = sell(campaign(), 0.0, distance=60.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)
        self.assertTrue(d.stop)

    def test_a_far_vendor_still_waits_for_the_campaign(self):
        d = sell(campaign(), 0.0, distance=None)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("campaign owns the traveller", d.reason)

    def test_the_sale_walk_holds_and_is_not_handed_back_while_it_walks(self):
        s = campaign()
        s.settle(sell(s, 0.0, distance=60.0), True, 0.0)
        self.assertEqual(
            townslot.SLOT_HOLD, sell(s, 30.0, distance=20.0, column="vendor").verdict
        )
        self.assertIsNone(
            s.campaign_release(
                leader="Grug", column="vendor", now=60.0, ground=lambda a: False
            )
        )

    def test_one_sale_stop_per_campaign_window(self):
        s = campaign()
        s.settle(sell(s, 0.0, distance=60.0), True, 0.0)
        s.holder = None  # the sale landed and the errand was released
        again = sell(s, 600.0, distance=60.0)
        self.assertEqual(townslot.SLOT_WAIT, again.verdict)
        self.assertIn("one stop per", again.reason)


class OnlyAStopSaysHowFar(unittest.TestCase):
    def test_a_near_counter_is_passed_on(self):
        self.assertEqual(60.0, townslot.stop_yards("economy", 60.0))

    def test_a_far_or_unread_counter_is_not(self):
        """A far trip keeps vendor_stall as its only give-up, as before."""
        far = townslot.TOWN_STOP_YARDS + 1
        self.assertIsNone(townslot.stop_yards("economy", far))
        self.assertIsNone(townslot.stop_yards("economy", None))
        self.assertIsNone(townslot.stop_yards("auction", 10.0))


class TheVendorPassSaysHowFar(unittest.TestCase):
    def test_the_vendor_claim_carries_the_nearest_vendor(self):
        start = BRIDGE.index("    async def _vendor_once(")
        body = BRIDGE[start : BRIDGE.index("\n    async def ", start + 1)]
        claim = body[body.index('"economy", leader, "vendor"') :]
        claim = claim[: claim.index(")\n")]
        self.assertIn("distance=", claim)
        self.assertIn("_nearest_vendor_yards", body)


if __name__ == "__main__":
    unittest.main()
