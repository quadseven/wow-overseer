"""A training stop nobody can finish is handed back after the orphan lease (#2087).

Measured on the dev realm 2026-11-08: the module claimed `trainer:1228` for a
family leader at 03:28Z, could not prove ground toward a trainer 829 yards
off, and the column stayed held for about 17 hours. The bridge logged "not a
bridge errand this pass may hand back yet" 46 times, and every town pass,
the guild bank included, waited behind it. A trainer aim was not releasable,
so no lease ever applied to it. The module's own stops end by themselves in
at most about 11 minutes (89 stops over two days, longest 674s).

Pinned here:

  * a stale orphan `trainer:<entry>` is handed back to a campaign after the
    orphan lease and not before, once per stand;
  * a pass waiting for the column preempts it past the same lease;
  * a named pass's aim, a keyword plan and a bare entry are never taken by
    this rule;
  * a ground aim re-armed after a hand-back is handed back again, but only
    after a full orphan lease, and an unchanged stand only once;
  * the bridge releases a stop through the compare-and-swap that refuses a
    pending learn, and every other aim through the economy fence.
"""

import pathlib
import unittest

import learnaim
import townslot
import travel

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

STOP = "trainer:1228"
GROUND = "at:1:-1191.42,2888.37,85.9296"
LEASE = townslot.ORPHAN_LEASE_SECONDS


def economy(aim):
    return aim in ("vendor", "repair", "auctioneer") or (
        aim.startswith("at:") or aim.isdigit()
    )


def release(slot, column, now):
    return slot.campaign_release(
        leader="Grug", column=column, now=now, ground=travel.is_ground_aim
    )


class TheStopPredicate(unittest.TestCase):
    def test_only_a_numeric_trainer_entry(self):
        self.assertTrue(townslot.is_training_stop_aim(STOP))
        for aim in (
            "",
            "vendor",
            "1228",
            learnaim.TRAINER_ROLE,
            "trainer:",
            "trainer:0",
            "trainer:12a",
            GROUND,
            None,
        ):
            self.assertFalse(townslot.is_training_stop_aim(aim), aim)

    def test_the_bound_is_past_the_longest_stop_the_module_walks(self):
        self.assertGreaterEqual(LEASE, 1200.0)
        self.assertGreater(LEASE, 674.0)


class HandedBackToACampaign(unittest.TestCase):
    def test_a_stop_younger_than_the_lease_is_left_alone(self):
        slot = townslot.Slot(releasable=economy)
        self.assertIsNone(release(slot, STOP, 0.0))
        self.assertIsNone(release(slot, STOP, LEASE - 1.0))

    def test_a_stop_unchanged_for_the_lease_is_handed_back_once(self):
        slot = townslot.Slot(releasable=economy)
        self.assertIsNone(release(slot, STOP, 0.0))
        got = release(slot, STOP, LEASE)
        self.assertIsNotNone(got)
        self.assertEqual(STOP, got.aim)
        self.assertEqual("", got.claimant)
        self.assertIsNone(release(slot, STOP, LEASE + 60.0))

    def test_a_stop_the_module_re_arms_is_a_new_stand_with_a_new_clock(self):
        slot = townslot.Slot(releasable=economy)
        release(slot, STOP, 0.0)
        got = release(slot, STOP, LEASE)
        slot.released_for_campaign(got, True)
        self.assertIsNone(release(slot, "", LEASE + 10.0))
        self.assertIsNone(release(slot, STOP, LEASE + 20.0))
        self.assertIsNone(release(slot, STOP, 2 * LEASE + 19.0))
        self.assertIsNotNone(release(slot, STOP, 2 * LEASE + 20.0))

    def test_a_stop_that_changes_is_a_moving_aim_and_restarts_the_clock(self):
        slot = townslot.Slot(releasable=economy)
        release(slot, STOP, 0.0)
        self.assertIsNone(release(slot, "trainer:3034", LEASE - 1.0))
        self.assertIsNone(release(slot, "trainer:3034", LEASE + 5.0))
        self.assertIsNotNone(release(slot, "trainer:3034", 2 * LEASE - 1.0))

    def test_a_named_passes_stop_is_not_taken_by_the_orphan_rule(self):
        slot = townslot.Slot(releasable=economy)
        taken = slot.want(
            claimant="weapon master",
            character="Grug",
            aim=STOP,
            leader="Grug",
            column="",
            retaskable=(),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        got = release(slot, STOP, 10.0)
        # Returned as the named pass's aim by the existing rule, at once; the
        # orphan clock plays no part.
        self.assertTrue(got is None or got.claimant == "weapon master")

    def test_a_keyword_plan_and_a_bare_entry_are_not_stops(self):
        slot = townslot.Slot(releasable=economy)
        self.assertIsNone(release(slot, learnaim.TRAINER_ROLE, 5 * LEASE))

    def test_the_campaigns_own_ground_aim_is_not_handed_back_early(self):
        slot = townslot.Slot(releasable=economy)
        self.assertIsNone(release(slot, GROUND, 0.0))
        self.assertIsNone(release(slot, GROUND, townslot.LEASE_SECONDS - 1.0))


class AGroundAimTheModuleRearms(unittest.TestCase):
    def test_an_unchanged_stand_is_handed_back_only_once(self):
        slot = townslot.Slot(releasable=economy)
        release(slot, GROUND, 0.0)
        got = release(slot, GROUND, townslot.LEASE_SECONDS)
        self.assertIsNotNone(got)
        slot.released_for_campaign(got, False)
        self.assertIsNone(release(slot, GROUND, 5 * LEASE))

    def test_a_rearmed_stand_waits_a_full_orphan_lease(self):
        slot = townslot.Slot(releasable=economy)
        release(slot, GROUND, 0.0)
        first = release(slot, GROUND, townslot.LEASE_SECONDS)
        slot.released_for_campaign(first, True)
        release(slot, "", 400.0)
        self.assertIsNone(release(slot, GROUND, 410.0))
        self.assertIsNone(release(slot, GROUND, 410.0 + townslot.LEASE_SECONDS))
        self.assertIsNone(release(slot, GROUND, 409.0 + LEASE))
        self.assertIsNotNone(release(slot, GROUND, 410.0 + LEASE))


class APassPreemptsAStaleStop(unittest.TestCase):
    def ask(self, slot, now, column=STOP):
        return slot.want(
            claimant="guild bank",
            character="Grug",
            aim="at:1:-917.3,-3727.3,9.6",
            leader="Grug",
            column=column,
            retaskable=("", "at:1:-917.3,-3727.3,9.6"),
            now=now,
        )

    def test_it_waits_inside_the_lease_and_takes_the_column_after(self):
        slot = townslot.Slot(releasable=economy)
        first = self.ask(slot, 0.0)
        self.assertEqual(townslot.SLOT_WAIT, first.verdict)
        self.assertEqual(townslot.SLOT_WAIT, self.ask(slot, LEASE - 1.0).verdict)
        late = self.ask(slot, LEASE)
        self.assertEqual(townslot.SLOT_PREEMPT, late.verdict)
        self.assertEqual(STOP, late.release.aim)

    def test_it_still_waits_behind_a_stop_that_is_not_an_orphan(self):
        slot = townslot.Slot(releasable=economy)
        taken = slot.want(
            claimant="weapon master",
            character="Grug",
            aim=STOP,
            leader="Grug",
            column="",
            retaskable=(),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        got = self.ask(slot, 10 * LEASE)
        self.assertEqual(townslot.SLOT_WAIT, got.verdict)
        self.assertIn("not an errand the economy may hand back", got.reason)

    def test_the_keyword_plan_is_never_preempted(self):
        slot = townslot.Slot(releasable=economy)
        got = self.ask(slot, 10 * LEASE, column=learnaim.TRAINER_ROLE)
        self.assertEqual(townslot.SLOT_WAIT, got.verdict)


class TheBridgeRelease(unittest.TestCase):
    def test_a_stop_goes_through_the_learn_safe_swap_at_every_hand_back_site(self):
        # The pass release, the idle release and the campaign hand-back each
        # pick the swap for a training stop and the economy fence otherwise.
        self.assertEqual(3, BRIDGE.count("townslot.is_training_stop_aim("))
        self.assertEqual(3, BRIDGE.count("else _release_trade_errand"))

    def test_the_campaign_hand_back_says_how_long_the_aim_stood(self):
        self.assertIn("after it stood %ds", BRIDGE)


if __name__ == "__main__":
    unittest.main()
