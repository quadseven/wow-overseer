"""One owner of the leader's walk while the family is held for bag room (#1375).

THE RECORDED TIMELINE, wow-dev 2026-10-24, Zug's family, after the 02:59 ship:

    03:00:53 bags takes the traveller Zug from an unknown writer ... past its 0s lease
    03:06:09 town errand takes the traveller Zug from bags: '8364' ... past its 0s lease
    03:11:18 economy takes the traveller Zug from town errand ... past its 0s lease
    03:11:55 town errand takes the traveller Zug from economy: 'vendor' ... past its 0s lease
    03:16:33 economy takes the traveller Zug from town errand ... past its 0s lease
    03:16:58 town errand takes the traveller Zug from economy: 'vendor' ... past its 0s lease
    03:20    town errand released: the walk to the capital did not land in 1200s

Grug's family the same hour: "town errand waits: bags owns the traveller Grug"
from 03:06 to 03:13, then "vendor ran out of time"; at 03:16 bags took the
banker walk off the errand and "bank ran out of time".

The town errand and the bags pass each reserved the traveller, and a
reservation REPLACED the other's. Whoever held it last asked urgently, which
zeroes every lease, and the reservation's protection followed the last writer,
so the third pass (economy, urgent on bag pressure) could take the column off
the errand the moment the bags pass had stolen its reservation. These tests
replay that order through `townslot.Slot` and fail on the code before #1375.
"""

import unittest

import townslot

HUB = "at:1:1657.9,-4433.0,17.5"
BAG_VENDOR = "8364"


def economy(aim):
    text = str(aim or "")
    return (
        text in ("vendor", "banker", "repair")
        or text.startswith("at:")
        or text.isdigit()
    )


def ask(slot, claimant, aim, column, now, urgent=False):
    return slot.want(
        claimant=claimant,
        character="Zug",
        aim=aim,
        leader="Zug",
        column=column,
        retaskable=("", aim),
        now=now,
        urgent=urgent,
    )


class TheRecordedTimeline(unittest.TestCase):
    def errand_on_the_road(self):
        """03:00: the town errand starts, reserves, and takes the hub walk."""
        slot = townslot.Slot(releasable=economy)
        self.assertTrue(slot.reserve("town errand", 0.0, "the family's town errand"))
        took = ask(slot, "town errand", HUB, "", 0.0, urgent=True)
        self.assertTrue(took.granted)
        slot.settle(took, True, 0.0)
        return slot

    def test_the_bags_pass_cannot_take_the_errands_hold(self):
        slot = self.errand_on_the_road()
        # 03:06: the bags pass sees the campaign withheld and a bag vendor.
        self.assertFalse(
            slot.reserve(
                "bags", 306.0, "the family's campaign is withheld for bag space"
            )
        )
        self.assertEqual("town errand", slot.reservation.claimant)
        self.assertIn("town errand owns it", slot.refused)

    def test_the_bags_walk_waits_instead_of_preempting(self):
        slot = self.errand_on_the_road()
        slot.reserve("bags", 306.0, "the family's campaign is withheld for bag space")
        d = ask(
            slot,
            "bags",
            BAG_VENDOR,
            HUB,
            306.0,
            urgent=slot.reserved_by("bags", 306.0),
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("town errand owns the traveller Zug", d.reason)

    def test_the_urgent_vendor_aim_waits_too(self):
        slot = self.errand_on_the_road()
        slot.reserve("bags", 306.0, "the family's campaign is withheld for bag space")
        d = ask(slot, "economy", "vendor", HUB, 618.0, urgent=True)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_the_errand_keeps_its_walk_through_the_whole_window(self):
        slot = self.errand_on_the_road()
        for now in (306.0, 618.0, 655.0, 993.0, 1018.0):
            slot.reserve("bags", now, "the family's campaign is withheld for bag space")
            ask(
                slot, "bags", BAG_VENDOR, HUB, now, urgent=slot.reserved_by("bags", now)
            )
            ask(slot, "economy", "vendor", HUB, now, urgent=True)
            mine = ask(slot, "town errand", HUB, HUB, now, urgent=True)
            self.assertEqual(townslot.SLOT_HOLD, mine.verdict, now)


class TheOrder(unittest.TestCase):
    def test_the_errand_outranks_a_standing_bags_hold(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("bags", 0.0, "the family's campaign is withheld for bag space")
        self.assertTrue(slot.reserve("town errand", 10.0, "the family's town errand"))
        self.assertEqual("town errand", slot.reservation.claimant)

    def test_an_unranked_pass_never_takes_a_live_hold(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("bags", 0.0, "withheld")
        self.assertFalse(slot.reserve("clearance", 10.0, "letters"))
        self.assertEqual("bags", slot.reservation.claimant)

    def test_a_lapsed_hold_may_be_taken_by_anybody(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("town errand", 0.0, "the family's town errand")
        self.assertTrue(slot.reserve("bags", townslot.RESERVE_SECONDS + 1, "withheld"))

    def test_the_order_is_the_operators(self):
        self.assertLess(
            townslot.reserve_rank("town errand"), townslot.reserve_rank("bags")
        )
        self.assertEqual(
            len(townslot.RESERVE_ORDER), townslot.reserve_rank("dungeon quests")
        )


class AHeldPassTimesOutIntoARecordedReason(unittest.TestCase):
    def test_the_lapse_is_said_once(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("town errand", 0.0, "the family's town errand")
        self.assertEqual("", slot.take_lapse(600.0))
        line = slot.take_lapse(townslot.RESERVE_SECONDS + 5)
        self.assertIn("town errand's hold on the traveller lapsed after 1205s", line)
        self.assertIn("the family's town errand", line)
        self.assertEqual("", slot.take_lapse(townslot.RESERVE_SECONDS + 60))

    def test_the_waiting_pass_gets_the_column_after_the_lapse(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("town errand", 0.0, "the family's town errand")
        took = ask(slot, "town errand", HUB, "", 0.0, urgent=True)
        slot.settle(took, True, 0.0)
        later = townslot.RESERVE_SECONDS + 1
        d = ask(slot, "bags", BAG_VENDOR, HUB, later, urgent=True)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_the_bridge_logs_the_lapse_and_the_refusal(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("take_lapse", source)
        self.assertGreaterEqual(
            source.count('log.info("town slot: %s", slot.refused)'), 3
        )


if __name__ == "__main__":
    unittest.main()
