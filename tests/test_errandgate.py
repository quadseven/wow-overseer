"""May the economy send this member off on an errand of its own (#2323).

The pure rule: a verdict as data from the clock, the member's last recall
and where it stands, and the stand-down clock a recall keeps. The bridge's
side of it (every aim writer asking the one helper) is in
tests/test_errand_recall_loop.py.
"""

import unittest

import dungeonstall
import errandgate as gate

COOLDOWN = dungeonstall.RECALL_COOLDOWN_SECONDS
HOLD = dungeonstall.HOLD_SECONDS


class TheVerdict(unittest.TestCase):
    def test_a_member_never_recalled_and_outside_is_allowed(self):
        got = gate.decide(500.0, None, "bank")
        self.assertTrue(got.allow)
        self.assertEqual("", got.reason)
        self.assertEqual(0.0, got.left_seconds)

    def test_a_member_recalled_lately_is_held_for_the_rest_of_the_cooldown(self):
        got = gate.decide(1000.0 + 600, 1000.0, "bank")
        self.assertFalse(got.allow)
        self.assertEqual(gate.RECALL_COOLDOWN, got.reason)
        self.assertEqual(COOLDOWN - 600, got.left_seconds)

    def test_the_cooldown_holds_at_the_moment_of_the_recall(self):
        got = gate.decide(1000.0, 1000.0, "guild bank")
        self.assertFalse(got.allow)
        self.assertEqual(COOLDOWN, got.left_seconds)

    def test_the_cooldown_ends_exactly_at_its_bound(self):
        self.assertFalse(gate.decide(1000.0 + COOLDOWN - 1, 1000.0, "forge").allow)
        self.assertTrue(gate.decide(1000.0 + COOLDOWN, 1000.0, "forge").allow)

    def test_every_economy_claimant_is_held_alike(self):
        for claimant in sorted(gate.ECONOMY_CLAIMANTS):
            got = gate.decide(1060.0, 1000.0, claimant)
            self.assertFalse(got.allow, claimant)
            self.assertEqual(gate.RECALL_COOLDOWN, got.reason, claimant)

    def test_the_five_passes_the_ticket_names_are_economy(self):
        for claimant in ("bank", "guild bank", "towntrip", "craft_supply", "forge"):
            self.assertTrue(gate.is_economy(claimant), claimant)
        self.assertTrue(gate.is_economy("economy"))
        self.assertTrue(gate.is_economy("bag pressure"))

    def test_an_aim_that_is_not_the_economys_is_never_held(self):
        for claimant in sorted(gate.OTHER_CLAIMANTS):
            got = gate.decide(1060.0, 1000.0, claimant, inside_instance=True)
            self.assertTrue(got.allow, claimant)

    def test_a_claimant_nobody_classified_is_not_held(self):
        """An unknown name is allowed here; the source scan is what refuses a
        writer nobody classified (tests/test_errand_recall_loop.py)."""
        self.assertFalse(gate.is_economy("somebody new"))
        self.assertTrue(gate.decide(1060.0, 1000.0, "somebody new").allow)

    def test_no_claimant_is_classified_twice(self):
        self.assertEqual(set(), set(gate.ECONOMY_CLAIMANTS) & set(gate.OTHER_CLAIMANTS))
        for claimant, why in gate.OTHER_CLAIMANTS.items():
            self.assertTrue(why.strip(), claimant)

    def test_a_member_inside_an_instance_is_held_whatever_its_recall(self):
        got = gate.decide(500.0, None, "bank", inside_instance=True)
        self.assertFalse(got.allow)
        self.assertEqual(gate.INSIDE_INSTANCE, got.reason)
        self.assertEqual(0.0, got.left_seconds)

    def test_inside_outranks_the_cooldown_as_the_reason(self):
        got = gate.decide(1060.0, 1000.0, "bank", inside_instance=True)
        self.assertEqual(gate.INSIDE_INSTANCE, got.reason)

    def test_a_recall_stamped_after_now_holds_nothing(self):
        """A clock that reads earlier than the stamp is no evidence of a
        recent recall, the way dungeonstall.recall_cooling reads it."""
        self.assertTrue(gate.decide(900.0, 1000.0, "bank").allow)

    def test_the_verdict_is_the_cooling_read_for_every_age(self):
        for age in (0, 1, COOLDOWN - 1, COOLDOWN, COOLDOWN + 1):
            self.assertEqual(
                dungeonstall.recall_cooling(1000.0, 1000.0 + age),
                not gate.decide(1000.0 + age, 1000.0, "economy").allow,
                age,
            )


class TheSentence(unittest.TestCase):
    def test_an_allowed_aim_says_nothing(self):
        self.assertEqual("", gate.decide(1.0, None, "bank").said("Oz", "bank"))

    def test_a_cooldown_names_the_member_the_pass_and_the_minutes_left(self):
        said = gate.decide(1000.0 + 600, 1000.0, "bank").said("Oz", "bank")
        self.assertIn("Oz", said)
        self.assertIn("bank", said)
        self.assertIn("20 more minute", said)

    def test_the_last_seconds_of_a_cooldown_read_as_one_minute(self):
        said = gate.decide(1000.0 + COOLDOWN - 5, 1000.0, "forge").said("Oz", "forge")
        self.assertIn("1 more minute", said)

    def test_inside_an_instance_says_so(self):
        said = gate.decide(1.0, None, "forge", inside_instance=True).said("Oz", "forge")
        self.assertIn("Oz", said)
        self.assertIn("inside an instance", said)


class TheStandDownClockAcrossARecall(unittest.TestCase):
    def test_a_member_never_recalled_starts_its_clock_now(self):
        self.assertEqual(500.0, gate.resume_since(500.0, None, 7))

    def test_a_recalled_member_goes_on_from_when_its_errand_began(self):
        served = gate.Served(head_id=7, seconds=600.0, at=1000.0)
        self.assertEqual(400.0, gate.resume_since(1100.0, served, 7))
        self.assertEqual(400.0, gate.resume_since(1000.0, served, 7))

    def test_another_queue_entry_starts_over(self):
        served = gate.Served(head_id=7, seconds=600.0, at=1000.0)
        self.assertEqual(1100.0, gate.resume_since(1100.0, served, 8))

    def test_a_recall_older_than_the_cooldown_is_forgotten(self):
        served = gate.Served(head_id=7, seconds=600.0, at=1000.0)
        self.assertEqual(400.0, gate.resume_since(1000.0 + COOLDOWN - 1, served, 7))
        self.assertEqual(
            1000.0 + COOLDOWN, gate.resume_since(1000.0 + COOLDOWN, served, 7)
        )

    def test_a_clock_before_the_recall_starts_over(self):
        served = gate.Served(head_id=7, seconds=600.0, at=1000.0)
        self.assertEqual(900.0, gate.resume_since(900.0, served, 7))

    def test_time_served_is_never_negative(self):
        served = gate.Served(head_id=7, seconds=-5.0, at=1000.0)
        self.assertEqual(1000.0, gate.resume_since(1100.0, served, 7))

    def test_a_member_short_of_the_stand_down_bound_is_still_recalled(self):
        self.assertTrue(gate.recall_due(dungeonstall.RECALL_SECONDS))
        self.assertTrue(gate.recall_due(HOLD - 1))

    def test_a_member_at_the_stand_down_bound_is_left_to_the_stand_down(self):
        self.assertFalse(gate.recall_due(HOLD))
        self.assertFalse(gate.recall_due(HOLD + 600))

    def test_repeated_recalls_reach_the_bound(self):
        """Ten minute errands with a recall after each and a minute with the
        party between: the third is past the stand-down bound, not at ten
        minutes for the third time."""
        now, served, seen = 1000.0, None, []
        for _ in range(3):
            since = gate.resume_since(now, served, 7)
            now += 600.0
            served = gate.Served(7, now - since, now)
            seen.append(served.seconds)
            now += 60.0
        self.assertEqual([600.0, 1260.0, 1920.0], seen)
        self.assertFalse(gate.recall_due(served.seconds))


if __name__ == "__main__":
    unittest.main()
