"""One column, seven passes, and the rules that decide between them.

WHAT WAS MEASURED, ON THE LIVE REALM, 2026-09-14. Two minutes apart, with
nothing broken in either pass:

    01:36:36 guild bank: queued 0/5 deposit(s), leader=Grug aimed at
             at:1:-7203.1,-3821.1,8.6
    01:38:37 auction: leader=Grug could not be aimed at an auctioneer - the
             column already holds 'at:1:-7203.1,-3821.1,8.6' and an economy
             errand may only retask an idle traveller, so this pass is starved
             until that one clears (infra#3703)

`overseer_roster.travel_npc` is one string, only the leader travels, and seven
passes want it. Nothing arbitrated, so the winner was whoever ran first and the
loser was starved for a whole cycle - and over a day that is not a fair coin:
the guild bank pass produced 68 `no guild bank in reach` rows in 24 hours.

THE STATES THAT MATTER ARE NOT THE ONES THE REALM IS IN, which is the trap this
file is written against. The realm today is permanently "the leader holds
somebody's errand", so a suite that described today would pass while proving
nothing about the rule. Every branch below is exercised deliberately, including
the ones the realm has never been in: a lease that expires while two passes
wait, a holder this process cannot name, a want nobody renews, and an errand
that is not the economy's to hand back at all.

AND THE TWO WAYS THIS FIX COULD ITSELF BE THE BUG ARE PINNED HARDEST:

  * A LEASE RENEWED BY RE-ASSERTION never expires, and every one of these
    passes re-asserts its aim on its own cycle. `TheLeaseRunsFromWhenItWasTaken`
    is that.
  * FAIRNESS THAT STARVES THE OTHER WAY - a rare pass holding the column still
    for a frequent one that has stopped asking - is `TheYieldIsBounded`.
"""

import ast
import pathlib
import re
import unittest

import townslot


def want(name, waiting_since, last_asked=None):
    return townslot.Want(
        claimant=name,
        waiting_since=waiting_since,
        last_asked=waiting_since if last_asked is None else last_asked,
    )


def holder(name, aim, since, character="Grug"):
    return townslot.Holder(claimant=name, character=character, aim=aim, since=since)


def economy(aim):
    """The releasable predicate, as `bridge._is_economy_aim` answers it.

    Keywords the economy writes, a surveyed ground aim, a bare creature entry.
    A trainer errand is none of those and is the one this must refuse.
    """
    return (
        aim in ("vendor", "banker", "repair", "guild banker", "auctioneer")
        or aim.startswith("at:")
        or aim.isdigit()
    )


def decide(**kw):
    """`townslot.decide` with the arguments a live caller always supplies."""
    base = dict(
        claimant="guild bank",
        character="Grug",
        aim="at:1:1,2,3",
        leader="Grug",
        column="",
        retaskable=("", "at:1:1,2,3"),
        holder=None,
        wants=(),
        last_served={},
        now=0.0,
        releasable=economy,
    )
    base.update(kw)
    return townslot.decide(**base)


class OnlyTheLeaderTravels(unittest.TestCase):
    """mod-overseer refuses to walk anybody not carrying `new rpg`, and
    goals.py keeps that on the leader alone. An aim on a follower is not merely
    inert: it is never released, and it bills that character fifteen seconds of
    economy errand budget on every travel poll until the whole family's errand
    is refused for fifteen minutes."""

    def test_a_follower_is_refused_rather_than_aimed(self):
        d = decide(character="Ugga", leader="Grug")
        self.assertEqual(townslot.SLOT_NOT_THE_LEADER, d.verdict)
        self.assertFalse(d.granted)
        self.assertFalse(d.writes)

    def test_the_refusal_names_the_strategy_that_makes_it_true(self):
        d = decide(character="Ugga", leader="Grug")
        self.assertIn("new rpg", d.reason)
        self.assertIn("Ugga", d.reason)
        self.assertIn("Grug", d.reason)

    def test_an_unreadable_leader_refuses_everybody(self):
        """`_head_now` answering nothing is a world this process cannot aim
        into. Writing anyway would be an UPDATE onto whoever asked."""
        d = decide(character="Grug", leader="")
        self.assertEqual(townslot.SLOT_NOT_THE_LEADER, d.verdict)
        self.assertIn("nobody", d.reason)

    def test_a_follower_request_never_preempts_the_leader_s_errand(self):
        d = decide(
            character="Ugga",
            leader="Grug",
            column="vendor",
            holder=holder("economy", "vendor", since=0.0),
            now=99999.0,
        )
        self.assertIsNone(d.release)

    def test_the_leader_himself_is_granted(self):
        d = decide(character="Grug", leader="Grug")
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)


class AFreeColumnIsTakenAndRecorded(unittest.TestCase):
    def test_an_empty_column_is_taken(self):
        d = decide()
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)
        self.assertTrue(d.granted)
        self.assertTrue(d.writes)
        self.assertIsNone(d.release)

    def test_the_reason_says_the_column_was_free(self):
        self.assertIn("the column was free", decide().reason)

    def test_a_taken_slot_is_recorded_against_the_pass_that_took_it(self):
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=10.0,
        )
        slot.settle(d, True, 10.0)
        self.assertEqual("economy", slot.holder.claimant)
        self.assertEqual("vendor", slot.holder.aim)
        self.assertEqual(10.0, slot.holder.since)

    def test_a_write_that_lost_a_race_records_no_holder(self):
        """The slot said yes and the guarded UPDATE matched nothing, which is a
        race rather than a contradiction. A ledger that recorded the INTENTION
        would hand this pass a lease it is not using and tell every other pass
        to wait for an errand nobody is on."""
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=10.0,
        )
        slot.settle(d, False, 10.0)
        self.assertIsNone(slot.holder)
        self.assertEqual(["economy"], [w.claimant for w in slot.wants])

    def test_a_refused_write_keeps_the_pass_in_the_queue(self):
        """It waited, so it is a waiter. Starting it again from the back on
        every lost race is how a pass with a slow cycle never gets a turn."""
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="vendor",
            retaskable=("", "banker"),
            now=5.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        granted = slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="",
            retaskable=("", "banker"),
            now=600.0,
        )
        slot.settle(granted, False, 600.0)
        self.assertEqual([5.0], [w.waiting_since for w in slot.wants])


class TheLeaseRunsFromWhenItWasTaken(unittest.TestCase):
    """THE RULE THE WHOLE FIX RESTS ON. Every one of these passes re-asserts
    its aim on its own cycle, so a lease renewed by re-assertion is a lease that
    never expires - which is the bug this module exists to end, rebuilt with an
    extra mechanism in front of it."""

    def test_the_same_pass_asking_again_holds_rather_than_rewrites(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            column="vendor",
            retaskable=("", "vendor"),
            holder=holder("economy", "vendor", since=0.0),
            now=100.0,
        )
        self.assertEqual(townslot.SLOT_HOLD, d.verdict)
        self.assertTrue(d.granted)
        self.assertFalse(d.writes)

    def test_a_hold_carries_the_original_start_time_forward(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            column="vendor",
            retaskable=("", "vendor"),
            holder=holder("economy", "vendor", since=0.0),
            now=100.0,
        )
        self.assertEqual(0.0, d.inherit_since)

    def test_re_asserting_for_an_hour_does_not_push_the_lease_out(self):
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(d, True, 0.0)
        for minute in range(1, 60):
            again = slot.want(
                claimant="economy",
                character="Grug",
                aim="vendor",
                leader="Grug",
                column="vendor",
                retaskable=("", "vendor"),
                now=minute * 60.0,
            )
            slot.settle(again, True, minute * 60.0)
        self.assertEqual(0.0, slot.holder.since)
        starved = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="at:1:1,2,3",
            leader="Grug",
            column="vendor",
            retaskable=("", "at:1:1,2,3"),
            now=3600.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, starved.verdict)

    def test_a_hold_is_logged_and_writes_nothing(self):
        """Re-writing the same word makes mod-overseer's aim book erase its own
        state and read a standing errand as a brand new one, releasing and
        re-taking the counter hold every time (infra#3708)."""
        d = decide(
            claimant="economy",
            aim="vendor",
            column="vendor",
            retaskable=("", "vendor"),
            holder=holder("economy", "vendor", since=0.0),
            now=30.0,
        )
        self.assertIn("already holds", d.reason)
        self.assertFalse(d.writes)


class AHeldErrandIsWaitedFor(unittest.TestCase):
    def test_a_live_errand_inside_its_lease_is_left_alone(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0), now=120.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertFalse(d.granted)
        self.assertIsNone(d.release)

    def test_the_wait_says_how_much_lease_is_left(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0), now=120.0)
        self.assertIn("held 120s of a 300s lease", d.reason)
        self.assertIn("180s left", d.reason)

    def test_the_wait_names_the_pass_that_holds_it(self):
        """ "Already on another errand" cannot tell a pass starved by a live
        errand from one starved by an errand left behind."""
        d = decide(column="repair", holder=holder("towntrip", "repair", 0.0), now=10.0)
        self.assertIn("towntrip", d.reason)
        self.assertIn("'repair'", d.reason)


class AStuckErrandLosesTheSlot(unittest.TestCase):
    """The actual defect. An errand that never completes held the family's one
    traveller for as long as it liked, and every other town errand starved
    behind it."""

    def test_the_lease_expiring_hands_the_slot_over(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0), now=301.0)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)
        self.assertTrue(d.granted)
        self.assertTrue(d.writes)

    def test_the_preemption_names_the_errand_to_hand_back_first(self):
        """The release is a compare-and-swap on the exact aim that was read, so
        a column that changed hands in between matches nothing."""
        held = holder("economy", "vendor", 0.0)
        d = decide(column="vendor", holder=held, now=301.0)
        self.assertEqual(held, d.release)
        self.assertEqual("Grug", d.release.character)
        self.assertEqual("vendor", d.release.aim)

    def test_the_preemption_says_how_long_and_cites_the_issue(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0), now=612.0)
        self.assertIn("612s", d.reason)
        self.assertIn("past its 300s lease", d.reason)
        self.assertIn("infra#3703", d.reason)

    def test_one_second_before_the_lease_is_still_a_wait(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0), now=299.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_the_lease_boundary_itself_hands_over(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0), now=300.0)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_a_longer_lease_can_be_configured_without_changing_the_rule(self):
        """The realm's walks are what the number is about, so it is a knob."""
        d = decide(
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            now=301.0,
            lease=900.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_asking_is_waiting_so_the_first_ask_may_preempt(self):
        """A pass does not have to spend one whole cycle being refused before
        it is allowed to take a lapsed lease. Its cycle is ten minutes; making
        it wait two would be the starvation with a politer name."""
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="at:1:1,2,3",
            leader="Grug",
            column="vendor",
            retaskable=("", "at:1:1,2,3"),
            now=400.0,
        )
        # The ledger has never seen this column, so it adopts it as an orphan
        # on the long lease - the honest answer for an errand it cannot name.
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        later = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="at:1:1,2,3",
            leader="Grug",
            column="vendor",
            retaskable=("", "at:1:1,2,3"),
            now=1700.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, later.verdict)


class AnErrandTheEconomyMayNotTouchIsNeverTaken(unittest.TestCase):
    """mod-overseer#438. A profession trainer errand is a standing plan that
    outlives a town run and carries `learn_skill` with it; blanking one is the
    bug the whole guarded branch exists to prevent."""

    def test_a_trainer_errand_is_waited_for_however_long_it_runs(self):
        d = decide(
            column="profession trainer",
            holder=holder("", "profession trainer", 0.0),
            now=99999.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIsNone(d.release)

    def test_the_reason_says_it_is_not_the_economy_s_to_hand_back(self):
        d = decide(
            column="profession trainer",
            holder=holder("", "profession trainer", 0.0),
            now=99999.0,
        )
        self.assertIn("not an errand the economy may hand back", d.reason)

    def test_with_no_predicate_supplied_nothing_is_ever_preempted(self):
        """Fail closed. A caller that forgets to wire the guard gets a module
        that arbitrates turn order and never takes anything from anybody."""
        d = decide(
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            now=99999.0,
            releasable=None,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_the_default_slot_is_fail_closed_too(self):
        slot = townslot.Slot()
        d = slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="vendor",
            retaskable=("", "banker"),
            now=99999.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)


class AnErrandWithNoOwnerGetsTheWorldsOwnClock(unittest.TestCase):
    """A restart forgets who holds what and finds the column still set. The
    honest thing to say about that aim is "somebody wrote this and it was not
    anybody I remember", and the honest thing to do with it is to leave it
    alone until mod-overseer's own backstop would have given up on it:
    TRAVEL_BACKSTOP_SECONDS is 20 minutes."""

    def test_an_unrecorded_column_becomes_a_holder_rather_than_nothing(self):
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="repair",
            retaskable=("", "banker"),
            now=50.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertEqual("repair", slot.holder.aim)
        self.assertEqual("", slot.holder.claimant)

    def test_an_orphan_is_not_preempted_on_the_short_lease(self):
        d = decide(column="repair", holder=holder("", "repair", 0.0), now=600.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("1200s lease", d.reason)

    def test_an_orphan_is_preempted_once_the_world_has_given_up_too(self):
        d = decide(column="repair", holder=holder("", "repair", 0.0), now=1201.0)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_an_orphan_is_named_as_one(self):
        d = decide(column="repair", holder=holder("", "repair", 0.0), now=1201.0)
        self.assertIn("an unknown writer", d.reason)

    def test_lease_for_answers_zero_for_nobody(self):
        self.assertEqual(0.0, townslot.lease_for(None))

    def test_lease_for_separates_the_two_cases(self):
        self.assertEqual(
            townslot.LEASE_SECONDS, townslot.lease_for(holder("economy", "vendor", 0.0))
        )
        self.assertEqual(
            townslot.ORPHAN_LEASE_SECONDS, townslot.lease_for(holder("", "vendor", 0.0))
        )

    def test_the_orphan_lease_matches_the_worlds_own_backstop(self):
        """mod_overseer.cpp: TRAVEL_BACKSTOP_SECONDS = 20 * 60. Past it the
        world has stopped believing in the errand too, so taking the column is
        not a race with anything."""
        self.assertEqual(20 * 60, townslot.ORPHAN_LEASE_SECONDS)

    def test_the_short_lease_is_several_town_walks_and_not_a_fraction_of_one(self):
        """The vendor counter and the vault were measured 121 yards apart in
        one town, and mod-overseer measures a walking bot at 112 yards a
        minute: 65 seconds. A lease shorter than the walk would preempt every
        errand while it was still working, which is the harm this whole module
        is careful about; one anywhere near the world's own 20-minute backstop
        would leave a stuck errand holding the family for as long as before."""
        walk = (121.0 / 112.0) * 60
        self.assertGreaterEqual(townslot.LEASE_SECONDS, 4 * walk)
        self.assertLess(townslot.LEASE_SECONDS, townslot.ORPHAN_LEASE_SECONDS)

    def test_the_short_lease_is_at_least_one_full_cycle_of_the_fastest_pass(self):
        """VENDOR_CYCLE_SECONDS, TOWNTRIP_CYCLE_SECONDS and
        CRAFT_FORGE_CYCLE_SECONDS are 300, so a holder always gets one whole
        cycle of its own to finish and hand the column back before anything
        else may take it."""
        self.assertGreaterEqual(townslot.LEASE_SECONDS, 300.0)


class AStaleErrandCanYieldToAnIdleDrive(unittest.TestCase):
    def test_an_orphaned_vendor_is_cleared_after_the_worlds_backstop(self):
        slot = townslot.Slot(releasable=economy)
        waiting = slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="vendor",
            now=0.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, waiting.verdict)

        clear = slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="vendor",
            now=townslot.ORPHAN_LEASE_SECONDS,
        )
        self.assertEqual(townslot.SLOT_CLEAR, clear.verdict)
        self.assertEqual(holder("", "vendor", 0.0), clear.release)
        self.assertFalse(clear.writes)
        self.assertIn("infra#3728", clear.reason)

    def test_a_live_vendor_inside_its_lease_is_preserved(self):
        slot = townslot.Slot(releasable=economy)
        taken = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)

        idle = slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="vendor",
            now=townslot.LEASE_SECONDS - 1,
        )
        self.assertEqual(townslot.SLOT_WAIT, idle.verdict)
        self.assertIsNone(idle.release)

    def test_a_profession_errand_is_never_cleared(self):
        slot = townslot.Slot(releasable=economy)
        idle = slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="profession trainer",
            now=99999.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, idle.verdict)
        self.assertIsNone(idle.release)

    def test_settling_a_clear_records_an_empty_slot(self):
        slot = townslot.Slot(releasable=economy)
        slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="vendor",
            now=0.0,
        )
        clear = slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="vendor",
            now=townslot.ORPHAN_LEASE_SECONDS,
        )
        slot.settle(clear, True, townslot.ORPHAN_LEASE_SECONDS)
        self.assertIsNone(slot.holder)
        self.assertEqual([], slot.wants)


class TheRefinementTheColumnAlreadyAllows(unittest.TestCase):
    """`_retaskable_from` lets a named creature entry be written over a plain
    `vendor`, because they are the same errand at two resolutions (infra#3692).
    A scheduler stricter than the column it guards would have made that fix
    inert, which is exactly what it was measured doing before it landed."""

    def test_a_sharper_aim_may_take_the_errand_it_refines(self):
        d = decide(
            claimant="craft_supply",
            aim="5594",
            retaskable=("", "5594", "vendor"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            now=60.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_the_refinement_says_what_it_is(self):
        d = decide(
            claimant="craft_supply",
            aim="5594",
            retaskable=("", "5594", "vendor"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            now=60.0,
        )
        self.assertIn("refines", d.reason)
        self.assertIn("sharper resolution", d.reason)

    def test_a_different_errand_is_not_a_refinement(self):
        d = decide(
            claimant="bank",
            aim="banker",
            retaskable=("", "banker"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            now=60.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_a_refinement_inherits_the_lease_it_refines(self):
        """Two passes refining each other's aims must not be able to launder a
        lease between them and keep the column for ever."""
        d = decide(
            claimant="craft_supply",
            aim="5594",
            retaskable=("", "5594", "vendor"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            now=200.0,
        )
        self.assertEqual(0.0, d.inherit_since)

    def test_the_inherited_lease_really_does_expire_on_the_old_clock(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        refined = slot.want(
            claimant="craft_supply",
            character="Grug",
            aim="5594",
            leader="Grug",
            column="vendor",
            retaskable=("", "5594", "vendor"),
            now=200.0,
        )
        slot.settle(refined, True, 200.0)
        self.assertEqual(0.0, slot.holder.since)
        third = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="at:1:1,2,3",
            leader="Grug",
            column="5594",
            retaskable=("", "at:1:1,2,3"),
            now=310.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, third.verdict)


class TheTurnGoesToWhoeverHasWaitedLongest(unittest.TestCase):
    def test_a_lapsed_lease_goes_to_the_longest_waiter_and_not_to_the_asker(self):
        d = decide(
            claimant="auction",
            aim="auctioneer",
            retaskable=("", "auctioneer"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            wants=(want("guild bank", 10.0), want("auction", 200.0)),
            now=400.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("guild bank", d.reason)

    def test_and_the_longest_waiter_itself_is_granted(self):
        d = decide(
            claimant="guild bank",
            aim="at:1:1,2,3",
            retaskable=("", "at:1:1,2,3"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            wants=(want("guild bank", 10.0), want("auction", 200.0)),
            now=400.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_the_refusal_says_how_much_longer_the_other_has_waited(self):
        d = decide(
            claimant="auction",
            aim="auctioneer",
            retaskable=("", "auctioneer"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            wants=(want("guild bank", 10.0), want("auction", 200.0)),
            now=400.0,
        )
        self.assertIn("190s longer", d.reason)

    def test_the_order_is_the_wait_and_not_the_alphabet(self):
        ordered = townslot.fresh_wants(
            [want("auction", 5.0), want("bank", 1.0), want("towntrip", 3.0)], now=10.0
        )
        self.assertEqual(["bank", "towntrip", "auction"], [w.claimant for w in ordered])

    def test_a_tie_is_broken_the_same_way_every_run(self):
        ordered = townslot.fresh_wants(
            [want("towntrip", 1.0), want("auction", 1.0)], now=10.0
        )
        self.assertEqual(["auction", "towntrip"], [w.claimant for w in ordered])


class TheFreeColumnIsYieldedToWhoeverIsOwedIt(unittest.TestCase):
    """FAIRNESS THAT DOES NOT STARVE THE OTHER WAY. Without this a 300-second
    pass simply wins every race against a 600-second one for ever, which is how
    the guild bank pass spent its whole life: the column empties, the frequent
    pass takes it again, and the rare one samples a held column every time."""

    def test_a_pass_that_was_just_served_stands_aside(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="",
            wants=(want("guild bank", 10.0),),
            last_served={"economy": 300.0},
            now=400.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("stands aside", d.reason)
        self.assertIn("guild bank", d.reason)

    def test_a_pass_that_has_never_been_served_takes_the_free_column(self):
        """It cannot owe anybody a turn it has never had."""
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="",
            wants=(want("guild bank", 10.0),),
            last_served={},
            now=400.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_urgent_bag_pressure_takes_a_free_column(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="",
            wants=(want("auction", 10.0),),
            last_served={"economy": 300.0},
            now=400.0,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_urgent_bag_pressure_preempts_an_expired_economy_errand(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="auctioneer",
            holder=holder("auction", "auctioneer", 0.0),
            wants=(want("guild bank", 10.0),),
            now=400.0,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_it_does_not_stand_aside_for_a_pass_it_has_not_outrun(self):
        """The waiter was served more recently than this pass, so this pass is
        the one that is owed the turn."""
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="",
            wants=(want("guild bank", 10.0),),
            last_served={"economy": 100.0, "guild bank": 200.0},
            now=400.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_it_does_not_stand_aside_for_a_shorter_wait(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="",
            wants=(want("economy", 10.0), want("guild bank", 300.0)),
            last_served={"economy": 305.0},
            now=400.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_the_pass_that_was_yielded_to_then_takes_it(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        starved = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="at:1:1,2,3",
            leader="Grug",
            column="vendor",
            retaskable=("", "at:1:1,2,3"),
            now=60.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, starved.verdict)
        # The world clears the column when the sell queue drains.
        again = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=300.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, again.verdict)
        theirs = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="at:1:1,2,3",
            leader="Grug",
            column="",
            retaskable=("", "at:1:1,2,3"),
            now=360.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, theirs.verdict)


class TheYieldIsBounded(unittest.TestCase):
    """THE OTHER DIRECTION, WHICH IS THE FAILURE A FAIRNESS FIX INVENTS. A want
    registered once and never renewed would otherwise hold the whole family's
    town work still for ever, on behalf of a loop that has stopped asking."""

    def test_a_want_nobody_renews_goes_stale(self):
        live = townslot.fresh_wants(
            [want("guild bank", 0.0, last_asked=0.0)], now=901.0
        )
        self.assertEqual([], live)

    def test_a_stale_want_is_not_yielded_to(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="",
            wants=(want("guild bank", 0.0, last_asked=0.0),),
            last_served={"economy": 300.0},
            now=1000.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_a_want_renewed_by_a_living_loop_stays_live(self):
        d = decide(
            claimant="economy",
            aim="vendor",
            retaskable=("", "vendor"),
            column="",
            wants=(want("guild bank", 0.0, last_asked=900.0),),
            last_served={"economy": 300.0},
            now=1000.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_a_stale_want_does_not_hold_up_a_lapsed_lease_either(self):
        d = decide(
            claimant="auction",
            aim="auctioneer",
            retaskable=("", "auctioneer"),
            column="vendor",
            holder=holder("economy", "vendor", 0.0),
            wants=(
                want("guild bank", 0.0, last_asked=0.0),
                want("auction", 500.0, last_asked=1000.0),
            ),
            now=1000.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_the_freshness_window_outlasts_the_longest_pass_cycle(self):
        """The slowest of these loops runs every 600 seconds, so a want must
        survive one missed cycle without being called abandoned."""
        self.assertGreater(townslot.WANT_FRESH_SECONDS, 600.0)

    def test_a_pass_can_give_up_its_turn_without_waiting_for_the_clock(self):
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="vendor",
            retaskable=("", "banker"),
            now=0.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        slot.forget("bank")
        self.assertEqual([], slot.wants)

    def test_an_aimless_ask_registers_no_want(self):
        """A pass with nothing to ask for is not a waiter, and must not be able
        to hold the column still for a journey nobody wants taken."""
        slot = townslot.Slot(releasable=economy)
        d = slot.want(
            claimant="forge",
            character="Grug",
            aim="",
            leader="Grug",
            column="vendor",
            retaskable=(),
            now=0.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertFalse(d.granted)
        self.assertEqual([], slot.wants)


class ASlowPassIsRankedByItsWaitAndNotByItsLastAsk(unittest.TestCase):
    """infra#4208. `WANT_FRESH_SECONDS` answers "is this loop still asking?",
    and `_ahead_of` used it to answer a different question: "where does the
    pass that is asking RIGHT NOW stand in the queue?" A pass whose cycle is
    longer than the freshness window fell off the end of that loop and was
    ranked behind every other waiter however long it had actually been starved.

    MEASURED ON wow-dev 2026-09-19, three minutes apart, with a dead
    `auctioneer` aim on an expired 300s lease sitting between them:

        14:36:49 guild bank waits: ... but flight has been waiting 1020s
                 longer and takes the slot first
        14:39:48 flight waits: ... but guild bank has been waiting -1020s
                 longer and takes the slot first

    THE SAME MAGNITUDE WITH OPPOSITE SIGNS IS THE PROOF. `flight` began waiting
    at 13:39:48 and `guild bank` at 13:56:48, so 1020 seconds is the real gap
    and `flight` is the older of the two. The first line reads it correctly;
    the second has the roles the wrong way round, because `flight`'s own last
    ask had just gone stale and it was ranked behind every live want. Each is
    told in turn to stand aside for the other, neither takes the column, and
    the dead errand went on being held for another eight minutes.
    """

    def test_a_pass_whose_own_ask_went_stale_still_outranks_a_later_waiter(self):
        """THE FIX, STATED ONCE. `flight` asked at 0 and again at 1000, so its
        own want is stale by `WANT_FRESH_SECONDS`; `guild bank` began waiting
        at 600, six hundred seconds AFTER it. Ranking by the recorded wait
        puts `flight` first, which is what it is."""
        d = decide(
            claimant="flight",
            aim="at:1:9,9,9",
            retaskable=("", "at:1:9,9,9"),
            column="auctioneer",
            holder=holder("auction", "auctioneer", 0.0),
            wants=(
                want("flight", 0.0, last_asked=0.0),
                want("guild bank", 600.0, last_asked=990.0),
            ),
            now=1000.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_nothing_ahead_of_a_pass_started_waiting_after_it(self):
        """THE PROPERTY, RATHER THAN ONE CASE OF IT. Whatever the freshness of
        anybody's last ask, `ahead` may only ever contain passes that really
        did start waiting earlier. The old reading could not say that: a stale
        claimant was handed the whole live queue regardless of the clock."""
        wants = (
            want("flight", 0.0, last_asked=0.0),
            want("guild bank", 600.0, last_asked=990.0),
            want("gather", 800.0, last_asked=995.0),
        )
        for moment in range(900, 1400, 20):
            for claimant in ("flight", "guild bank", "gather"):
                mine = next(w for w in wants if w.claimant == claimant)
                ahead = townslot._ahead_of(
                    claimant, wants, float(moment), townslot.WANT_FRESH_SECONDS
                )
                later = [
                    w.claimant for w in ahead if w.waiting_since > mine.waiting_since
                ]
                self.assertEqual(
                    [],
                    later,
                    "at now=%d, %s was told to yield to %s, which started "
                    "waiting after it" % (moment, claimant, later),
                )

    def test_the_refusal_never_claims_a_negative_wait(self):
        """`-1020s longer` was in the live log. It cannot be produced by an
        ordering where everything `ahead` really is ahead."""
        wants = (
            want("flight", 0.0, last_asked=0.0),
            want("guild bank", 600.0, last_asked=990.0),
        )
        for claimant in ("flight", "guild bank"):
            d = decide(
                claimant=claimant,
                aim="at:1:9,9,9",
                retaskable=("", "at:1:9,9,9"),
                column="auctioneer",
                holder=holder("auction", "auctioneer", 0.0),
                wants=wants,
                now=1000.0,
            )
            for number in re.findall(r"waiting (-?\d+)s longer", d.reason):
                self.assertGreaterEqual(
                    int(number),
                    0,
                    "%s was told somebody had waited %ss longer" % (claimant, number),
                )

    def test_a_first_ask_still_queues_behind_everybody(self):
        """The claimant with NO want at all is the case this must not change:
        `_own_wait` answers `now` for it, every live want sorts before that,
        and it takes its turn at the back exactly as it did before."""
        ahead = townslot._ahead_of(
            "craft_supply",
            (
                want("guild bank", 10.0, last_asked=900.0),
                want("auction", 200.0, last_asked=900.0),
            ),
            now=1000.0,
            want_fresh=townslot.WANT_FRESH_SECONDS,
        )
        self.assertEqual(["guild bank", "auction"], [w.claimant for w in ahead])


class NoPassGoesUnservedOverAWholeShift(unittest.TestCase):
    """THE STARVATION TEST, AND IT IS WRITTEN TO FAIL ON THE OLD CODE.

    infra#4208's measured complaint is a rate: 15 grants per 6 hours on
    2026-09-19. Re-measured the same day over 2h43m after the arrival fixes
    landed, it was 9 grants - 19.9 per 6 hours - with a worst wait of 6906
    seconds, nearly three times the 2341s the issue recorded. A rate cannot be
    asserted from a single `decide` call, and a suite of single calls is
    exactly what let a pass that never wins look healthy branch by branch. So
    this drives a real `Slot` through the seven passes on their real cycles and
    asks the two questions the log asks: how many grants, and did anybody get
    nothing.

    WHAT THE OLD CODE DID ON THIS SIMULATION, with one pass on a cycle longer
    than `WANT_FRESH_SECONDS` - which `flight` really is, measured at 15 and 30
    minute gaps between asks:

        flight cycle  900s   25 grants / 3.3h   nobody starved
        flight cycle 1000s    3 grants / 3.3h   flight, guild bank, mail
                                                and towntrip never served
        flight cycle 1200s    2 grants / 3.3h   five of seven never served

    One slow consumer took the whole column down. That is not a fairness
    tuning question, it is the arbitration deadlocking, and the cliff sits
    exactly at the freshness window.
    """

    # The seven passes that write `travel_npc`, on the cycle each really runs.
    # 300s: VENDOR_CYCLE_SECONDS, TOWNTRIP_CYCLE_SECONDS,
    # CRAFT_FORGE_CYCLE_SECONDS. 600s: the bank, guild bank and auction passes.
    # `flight` is the slow one and is the pass the defect was measured on.
    CYCLES = {
        "towntrip": 300.0,
        "gather": 300.0,
        "craft_rhythm": 300.0,
        "guild bank": 600.0,
        "auction": 600.0,
        "mail": 600.0,
        "flight": 1200.0,
    }

    HOURS = 6.0
    STEP = 30.0

    def _run(self, cycles):
        """Six hours of seven passes asking, with nothing ever arriving.

        THE WORST CASE ON PURPOSE. No errand is handed back voluntarily, so
        every hold ends at its lease - which is what the live log showed for
        all five holders in the measured window. Arrival working would only
        make this kinder.
        """
        aims = {
            name: "at:1:%d,0,0" % index for index, name in enumerate(sorted(cycles))
        }
        slot = townslot.Slot(
            releasable=economy, long_leases={"gather": townslot.GATHER_LEASE_SECONDS}
        )
        column = ""
        grants = {name: 0 for name in cycles}
        next_ask = {name: 0.0 for name in cycles}
        waiting_from = {}
        worst_wait = 0.0
        now = 0.0
        for _ in range(int(self.HOURS * 3600.0 / self.STEP)):
            for name in sorted(cycles):
                if now < next_ask[name]:
                    continue
                next_ask[name] = now + cycles[name]
                decision = slot.want(
                    claimant=name,
                    character="Grug",
                    aim=aims[name],
                    leader="Grug",
                    column=column,
                    retaskable=("", aims[name]),
                    now=now,
                )
                if decision.writes:
                    column = aims[name]
                    slot.settle(decision, True, now)
                    grants[name] += 1
                    if name in waiting_from:
                        worst_wait = max(worst_wait, now - waiting_from.pop(name))
                elif decision.granted:
                    slot.settle(decision, True, now)
                else:
                    slot.settle(decision, False, now)
                    waiting_from.setdefault(name, now)
            now += self.STEP
        for started in waiting_from.values():
            worst_wait = max(worst_wait, now - started)
        return grants, worst_wait

    def test_every_pass_is_served_at_least_once(self):
        """THE ASSERTION THE ISSUE ASKED FOR. A consumer that never wins across
        the whole run is a FAILURE, not a slow start."""
        grants, _ = self._run(self.CYCLES)
        starved = sorted(name for name, count in grants.items() if count == 0)
        self.assertEqual(
            [],
            starved,
            "these passes asked for the traveller for %g hours and never got "
            "it: %s (grants: %s)" % (self.HOURS, starved, sorted(grants.items())),
        )

    def test_a_slow_pass_does_not_take_the_whole_column_down_with_it(self):
        """The cliff was at `WANT_FRESH_SECONDS`: a consumer whose cycle
        crossed it collapsed everybody's throughput, not only its own. Both
        sides of the old cliff must now behave the same."""
        inside, _ = self._run(dict(self.CYCLES, flight=900.0))
        outside, _ = self._run(dict(self.CYCLES, flight=1200.0))
        self.assertEqual([], [n for n, c in outside.items() if c == 0])
        self.assertGreater(
            sum(outside.values()),
            sum(inside.values()) * 0.75,
            "a pass slower than the freshness window still costs the column "
            "most of its throughput: %d grants against %d"
            % (sum(outside.values()), sum(inside.values())),
        )

    def test_the_grant_rate_clears_the_measured_baseline(self):
        """THE FLOOR IS CHOSEN TO CATCH A REGRESSION, NOT TO PIN THE NUMBER.
        This arbitration produces 42 on this run and the old one produced 2, so
        35 catches anything worse than a one-sixth slide while leaving room for
        a lease change that is a deliberate trade. It is also comfortably above
        the 19.9 per 6 hours measured live, which matters because this
        simulation is HARSHER than the realm - nothing ever arrives here, so
        every hold runs its whole lease."""
        grants, _ = self._run(self.CYCLES)
        self.assertGreater(
            sum(grants.values()),
            35,
            "grants per %g hours: %d, against 42 for this arbitration, 2 for "
            "the one it replaced and 19.9 measured live"
            % (self.HOURS, sum(grants.values())),
        )

    def test_the_worst_wait_is_bounded_and_the_bound_is_recorded(self):
        """infra#4208 asks for a stated bound rather than a hope. THE BOUND
        THIS ARBITRATION CLAIMS IS ONE HOUR for any one consumer. Simulated
        worst case here is 3300s; the old ordering's was 21600s, the whole run,
        because five of seven were never served at all. Live before the change,
        `towntrip` waited 6906 seconds for one turn."""
        _, worst = self._run(self.CYCLES)
        self.assertLess(
            worst,
            3600.0,
            "a pass waited %ds, past the hour this arbitration is willing to "
            "claim as its bound" % int(worst),
        )


class TheLedgerLearnsFromTheColumn(unittest.TestCase):
    """THE WORLD IS THE AUTHORITY AND THIS MEMORY IS NOT. mod-overseer clears
    `travel_npc` itself on arrival, on its own unreachable backstop, and when an
    errand has killed a character often enough to be called off. None of that
    comes back to this process except as an emptied column."""

    def test_an_emptied_column_ends_the_errand_whoever_ended_it(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        theirs = slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="",
            retaskable=("", "banker"),
            now=60.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, theirs.verdict)

    def test_a_column_somebody_else_wrote_replaces_the_remembered_holder(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="profession trainer",
            retaskable=("", "banker"),
            now=60.0,
        )
        self.assertEqual("profession trainer", slot.holder.aim)
        self.assertEqual("", slot.holder.claimant)
        self.assertEqual(60.0, slot.holder.since)

    def test_a_new_leader_forgets_the_old_leaders_errand(self):
        """The aim on that row moves nobody now, and it is not this slot's to
        arbitrate: only the leader travels."""
        slot = townslot.Slot(releasable=economy)
        first = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        d = slot.want(
            claimant="bank",
            character="Bork",
            aim="banker",
            leader="Bork",
            column="",
            retaskable=("", "banker"),
            now=60.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)
        self.assertIsNone(slot.holder)

    def test_an_unchanged_column_keeps_the_clock_running(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="vendor",
            retaskable=("", "banker"),
            now=120.0,
        )
        self.assertEqual(0.0, slot.holder.since)


class TheDecisionSaysWhatToDoWithIt(unittest.TestCase):
    def test_granted_covers_every_way_to_end_up_with_or_clear_it(self):
        self.assertEqual(
            (
                townslot.SLOT_TAKE,
                townslot.SLOT_HOLD,
                townslot.SLOT_PREEMPT,
                townslot.SLOT_CLEAR,
            ),
            townslot.GRANTED,
        )

    def test_a_hold_is_granted_but_writes_nothing(self):
        d = townslot.Decision(verdict=townslot.SLOT_HOLD, reason="x")
        self.assertTrue(d.granted)
        self.assertFalse(d.writes)

    def test_a_wait_is_neither(self):
        d = townslot.Decision(verdict=townslot.SLOT_WAIT, reason="x")
        self.assertFalse(d.granted)
        self.assertFalse(d.writes)

    def test_a_take_and_a_preempt_both_write(self):
        for verdict in (townslot.SLOT_TAKE, townslot.SLOT_PREEMPT):
            with self.subTest(verdict=verdict):
                d = townslot.Decision(verdict=verdict, reason="x")
                self.assertTrue(d.writes)

    def test_every_decision_names_the_pass_that_asked(self):
        """The ledger records the outcome against this name, so a decision that
        lost it would settle the holder as nobody."""
        for kw in (
            {},
            {"character": "Ugga"},
            {"column": "vendor", "holder": holder("economy", "vendor", 0.0)},
            {
                "column": "vendor",
                "holder": holder("economy", "vendor", 0.0),
                "now": 9000.0,
            },
            {"aim": ""},
        ):
            with self.subTest(kw=sorted(kw)):
                self.assertEqual("guild bank", decide(**kw).claimant)

    def test_the_report_is_one_prefixed_sentence(self):
        line = townslot.report(decide())
        self.assertTrue(line.startswith("town slot: "))
        self.assertNotIn("\n", line)


class ThePurityOfTheModule(unittest.TestCase):
    """Facts in, judgements out. Anything here that reached for a connection or
    a clock of its own would be untestable exactly where it matters: this
    module's whole job is arithmetic on times the caller supplies."""

    ALLOWED = {"__future__", "dataclasses"}

    def test_it_imports_nothing_but_the_standard_library(self):
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(townslot.__file__).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        self.assertEqual(set(), names - self.ALLOWED)

    def test_it_reads_no_clock_of_its_own(self):
        """Every duration here is `now` minus something the caller recorded. A
        module that asked the clock itself could not be tested at an hour's
        distance, which is most of this file."""
        import pathlib

        source = pathlib.Path(townslot.__file__).read_text(encoding="utf-8")
        for forbidden in ("time.monotonic", "time.time", "datetime.now"):
            self.assertNotIn(forbidden, source)

    def test_nonleader_ground_economy_aims_are_stranded(self):
        aims = {
            "Grug": "",
            "Og": "at:1:10,20,30",
            "Ugga": "vendor",
            "Bork": "profession trainer",
        }
        self.assertEqual(
            ("Og",),
            townslot.stranded_nonleader_aims(
                aims,
                "Grug",
                ground=lambda value: value.startswith("at:"),
                releasable=lambda value: value.startswith("at:"),
            ),
        )

    def test_no_leader_does_not_release_any_aim(self):
        self.assertEqual(
            (),
            townslot.stranded_nonleader_aims(
                {"Og": "at:1:10,20,30"},
                "",
                ground=lambda _: True,
                releasable=lambda _: True,
            ),
        )

    def test_bag_pressure_can_release_ground_aim_outside_a_run(self):
        self.assertTrue(
            townslot.urgent_ground_release(
                aim="at:1:10,20,30",
                pressure=True,
                in_run=False,
                ground=lambda value: value.startswith("at:"),
            )
        )

    def test_bag_pressure_never_interrupts_a_run(self):
        self.assertFalse(
            townslot.urgent_ground_release(
                aim="at:1:10,20,30",
                pressure=True,
                in_run=True,
                ground=lambda value: value.startswith("at:"),
            )
        )


class AWalkThatLeavesTownGetsALeaseDimensionedForIt(unittest.TestCase):
    """infra#4183. `LEASE_SECONDS` is derived for a town errand and says so -
    "121 yards apart in the same town ... 300 is four and a half of those
    walks". A gathering trip is not that walk. The family's crafters
    out-levelled their professions, so the nearest node the weakest gatherer
    can open is in another zone: measured twice against the leader's own live
    position, 2588 and 2344 yards, which at mod-overseer's own measured 416
    yards a minute is 373 and 338 seconds. Both overrun a 300 second lease, so
    a gathering walk preempted on it loses nearly the whole trip, every time.

    THE DANGER IN FIXING IT IS REBUILDING THE LATCH infra#3703 CLOSED, which is
    what the class below pins. A longer lease is still a lease."""

    def test_a_claimant_with_no_long_lease_is_unchanged(self):
        """The default carries the safety argument: naming one pass's longer
        walk must not quietly lengthen anybody else's."""
        self.assertEqual(
            townslot.LEASE_SECONDS,
            townslot.lease_for(
                holder("economy", "vendor", since=0.0), long_leases={"gather": 450.0}
            ),
        )

    def test_the_named_claimant_gets_its_own_value(self):
        self.assertEqual(
            450.0,
            townslot.lease_for(
                holder("gather", "at:1:1,2,3", since=0.0), long_leases={"gather": 450.0}
            ),
        )

    def test_an_orphan_is_still_an_orphan(self):
        """A holder this process cannot name has no claimant to look up, so the
        world's own backstop outranks the mapping rather than the reverse."""
        self.assertEqual(
            townslot.ORPHAN_LEASE_SECONDS,
            townslot.lease_for(
                holder("", "at:1:1,2,3", since=0.0),
                long_leases={"gather": 450.0, "": 10.0},
            ),
        )

    def test_a_garbage_value_falls_back_rather_than_raising(self):
        """The value arrives from an env knob, so it can be anything. Falling
        back to the town lease is wrong-but-safe; raising here would take the
        whole goal cycle down with it."""
        self.assertEqual(
            townslot.LEASE_SECONDS,
            townslot.lease_for(
                holder("gather", "at:1:1,2,3", since=0.0),
                long_leases={"gather": "soon"},
            ),
        )

    def test_the_constant_clears_the_longest_measured_trip(self):
        """373 seconds of walking, plus one 60 second goal cycle for the
        arrival to be SEEN. A lease that lapses while the walk is still landing
        is the treadmill this was chosen over."""
        self.assertGreaterEqual(townslot.GATHER_LEASE_SECONDS, 373.0 + 60.0)

    def test_it_is_not_so_long_that_it_outlasts_an_unknown_errand(self):
        """`ORPHAN_LEASE_SECONDS` is mod-overseer's own TRAVEL_BACKSTOP_SECONDS
        - the point where the world stops believing in the errand. A named pass
        allowed past it would be held longer than an errand nobody can name at
        all, inverting the whole argument for the orphan lease."""
        self.assertLess(townslot.GATHER_LEASE_SECONDS, townslot.ORPHAN_LEASE_SECONDS)

    def test_a_gathering_walk_survives_the_town_lease_while_a_pass_waits(self):
        """The behaviour the constant exists for, through the real decision."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        taken = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:100,200,30",
            leader="Grug",
            column="",
            retaskable=("", "at:1:100,200,30"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        # 360 seconds in: past a town errand's 300, inside the walk's 450.
        waiting = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="guild banker",
            leader="Grug",
            column="at:1:100,200,30",
            retaskable=("", "guild banker"),
            now=360.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, waiting.verdict)
        self.assertFalse(waiting.granted)

    def test_the_same_wait_would_have_preempted_a_town_errand(self):
        """The control. Identical timing and an identical ground aim, with a
        claimant that has no long lease - so the test above is proving the
        mapping rather than merely the clock."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        taken = slot.want(
            claimant="forge",
            character="Grug",
            aim="at:1:100,200,30",
            leader="Grug",
            column="",
            retaskable=("", "at:1:100,200,30"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        waiting = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="guild banker",
            leader="Grug",
            column="at:1:100,200,30",
            retaskable=("", "guild banker"),
            now=360.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, waiting.verdict)


class ALongerLeaseIsStillALease(unittest.TestCase):
    """infra#3703's rule, re-proved against the longest holder on the column.

    "An errand that cannot finish must not hold it for ever" is the defect that
    module exists to end, and the tempting shape for a long walk - exempting it
    the way a trainer errand is exempted - would rebuild exactly that latch.
    The trainer exemption works by being a KEYWORD aim `_is_economy_aim`
    refuses to release; a gathering aim is a ground aim, so it stays releasable
    and therefore stays preemptible. These fail if that stops being true."""

    def test_a_gathering_walk_is_preempted_once_its_own_lease_runs_out(self):
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        taken = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:100,200,30",
            leader="Grug",
            column="",
            retaskable=("", "at:1:100,200,30"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        waiting = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="guild banker",
            leader="Grug",
            column="at:1:100,200,30",
            retaskable=("", "guild banker"),
            now=500.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, waiting.verdict)
        self.assertTrue(waiting.granted)

    def test_it_cannot_hold_the_column_for_ever_by_re_asserting(self):
        """The lease runs from when the errand was taken, and the gathering
        pass re-asserts every 60 seconds like every other pass. An hour of
        re-assertion must not push it out - the rule
        `TheLeaseRunsFromWhenItWasTaken` pins for town errands, proved again
        for the one claimant allowed to outlast them."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        first = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:100,200,30",
            leader="Grug",
            column="",
            retaskable=("", "at:1:100,200,30"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        for minute in range(1, 60):
            again = slot.want(
                claimant="gather",
                character="Grug",
                aim="at:1:100,200,30",
                leader="Grug",
                column="at:1:100,200,30",
                retaskable=("", "at:1:100,200,30"),
                now=minute * 60.0,
            )
            slot.settle(again, True, minute * 60.0)
        self.assertEqual(0.0, slot.holder.since)
        waiting = slot.want(
            claimant="guild bank",
            character="Grug",
            aim="guild banker",
            leader="Grug",
            column="at:1:100,200,30",
            retaskable=("", "guild banker"),
            now=3600.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, waiting.verdict)

    def test_a_full_bag_still_cuts_through_it_immediately(self):
        """`Slot.want` zeroes every lease for an urgent caller, and this is the
        one that must not be forgotten when a new lease is added: a gathering
        walk is the longest hold on the column, so a full bag blocking loot has
        to take it at once rather than after 450 seconds."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        taken = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:100,200,30",
            leader="Grug",
            column="",
            retaskable=("", "at:1:100,200,30"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        urgent = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="at:1:100,200,30",
            retaskable=("", "vendor"),
            now=1.0,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, urgent.verdict)
        self.assertTrue(urgent.granted)

    def test_an_idle_drive_can_still_clear_it_once_the_lease_lapses(self):
        """`want_idle` reads the same mapping, so the gathering walk is not
        quietly exempt from the one path that empties the column for a drive
        that wants no errand at all (infra#3728)."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        taken = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:100,200,30",
            leader="Grug",
            column="",
            retaskable=("", "at:1:100,200,30"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        held = slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="at:1:100,200,30",
            now=400.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, held.verdict)
        cleared = slot.want_idle(
            claimant="craft_rhythm",
            character="Grug",
            leader="Grug",
            column="at:1:100,200,30",
            now=500.0,
        )
        self.assertEqual(townslot.SLOT_CLEAR, cleared.verdict)


class AnUrgentPassThatAchievesNothingStopsOutrankingEverything(unittest.TestCase):
    """infra#4191. `Slot.want` zeroes every lease for an urgent caller and lets
    it skip the queue, which is right - a full bag blocks loot. What was
    missing is infra#3703's other half: an errand that cannot finish must not
    hold the column for ever. #3703 bounds an ordinary holder with a lease;
    nothing bounded an urgent one.

    Measured live before the fix: the vendor pass took the column urgently on
    three consecutive cycles, found no vendor within reach each time, wrote no
    sale, and the family moved 21 yards in 12 minutes. `gather` won the column
    once in 20 minutes and lost it 28 seconds later.
    """

    def _urgent(self, slot, now):
        """Ask for the column under bag pressure, the way the vendor pass does."""
        return slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="at:1:100,200,30",
            retaskable=("", "vendor"),
            now=now,
            urgent=True,
        )

    def _gather_holds(self, slot):
        slot_taken = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:100,200,30",
            leader="Grug",
            column="",
            retaskable=("", "at:1:100,200,30"),
            now=0.0,
        )
        slot.settle(slot_taken, True, 0.0)

    def test_the_first_fruitless_grant_still_preempts(self):
        """One failure is not a pattern. The pass has to be allowed to try."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        self._gather_holds(slot)
        self.assertEqual(townslot.SLOT_PREEMPT, self._urgent(slot, 1.0).verdict)

    def test_a_fruitless_grant_suppresses_the_next_preemption(self):
        """THE LIVELOCK. Before this, every cycle looked like the first one."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        self._gather_holds(slot)
        self.assertEqual(townslot.SLOT_PREEMPT, self._urgent(slot, 1.0).verdict)
        slot.fruitless("economy", 1.0)
        # Same pressure, same claim, one second later - and now it waits its
        # turn behind the gathering walk instead of cutting in front of it.
        self.assertEqual(townslot.SLOT_WAIT, self._urgent(slot, 2.0).verdict)

    def test_urgency_returns_once_the_backoff_lapses(self):
        """A bound, not a ban. The pressure is real and may well be relievable
        by then, so the pass gets its preemption back."""
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        self._gather_holds(slot)
        until = slot.fruitless("economy", 0.0)
        self.assertEqual(townslot.URGENT_BACKOFF_SECONDS, until)
        self.assertEqual(townslot.SLOT_WAIT, self._urgent(slot, until - 1.0).verdict)
        self.assertEqual(townslot.SLOT_PREEMPT, self._urgent(slot, until + 1.0).verdict)

    def test_the_streak_doubles_and_is_capped(self):
        """The shape `SHARE_RETRY_MINUTES * 2**n` capped at
        `SHARE_BACKOFF_CAP_HOURS` already uses for a repeated action that keeps
        not working (infra#2892)."""
        slot = townslot.Slot(releasable=economy)
        base = townslot.URGENT_BACKOFF_SECONDS
        self.assertEqual(base, slot.fruitless("economy", 0.0))
        self.assertEqual(base * 2, slot.fruitless("economy", 0.0))
        self.assertEqual(base * 4, slot.fruitless("economy", 0.0))
        for _ in range(20):
            capped = slot.fruitless("economy", 0.0)
        self.assertEqual(townslot.URGENT_BACKOFF_CAP_SECONDS, capped)

    def test_a_productive_grant_clears_the_streak(self):
        """It has demonstrated it can finish, so the next bad run starts from
        one turn again rather than from wherever the last one ended."""
        slot = townslot.Slot(releasable=economy)
        slot.fruitless("economy", 0.0)
        slot.fruitless("economy", 0.0)
        slot.productive("economy")
        self.assertEqual(0.0, slot.urgency_suppressed_until("economy"))
        self.assertEqual(
            townslot.URGENT_BACKOFF_SECONDS, slot.fruitless("economy", 0.0)
        )

    def test_suppressed_urgency_is_not_a_refusal(self):
        """It loses the right to cut in front, not the right to the column. A
        free column is still taken the ordinary way."""
        slot = townslot.Slot(releasable=economy)
        slot.fruitless("economy", 0.0)
        taken = slot.want(
            claimant="economy",
            character="Grug",
            aim="vendor",
            leader="Grug",
            column="",
            retaskable=("", "vendor"),
            now=1.0,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_TAKE, taken.verdict)
        self.assertTrue(taken.granted)

    def test_a_pass_that_never_claims_urgency_is_untouched(self):
        """The ledger stays empty for the six passes that never preempt."""
        slot = townslot.Slot(releasable=economy)
        self.assertEqual(0.0, slot.urgency_suppressed_until("guild bank"))
        slot.fruitless("economy", 0.0)
        self.assertEqual(0.0, slot.urgency_suppressed_until("guild bank"))

    def test_one_claimants_backoff_does_not_silence_another(self):
        slot = townslot.Slot(releasable=economy, long_leases={"gather": 450.0})
        slot.fruitless("economy", 0.0)
        other = slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="at:1:100,200,30",
            retaskable=("", "banker"),
            now=1.0,
            urgent=True,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, other.verdict)


class AnUnledgeredWriteDoesNotOrphanTheColumn(unittest.TestCase):
    """`adopt` is what stops a pass evicting itself (infra#4194).

    `_reconcile` rebuilds the holder from the column on every `want()`, and any
    value it does not recognise becomes `Holder(claimant="", since=now)` - an
    orphan on the long lease, with the clock started AGAIN rather than
    continued. Two passes write `travel_npc` without going through
    `_claim_town_slot`: the auction pass re-asserting its own keyword while it
    still owns the column, and the trade pass writing a trainer aim. Left
    unrecorded, each of those evicts whoever legitimately held the traveller
    and hands a 1200s lease to nobody - and because the clock restarts on every
    unrecognised value, the stall has no upper bound at all.

    Measured on wow-dev before the fix: five passes queued behind an
    `unknown writer` whose lease read `held 0s of a 1200s lease` fourteen
    minutes into a pod that had never restarted.
    """

    def test_an_unledgered_write_orphans_the_column_without_adopt(self):
        slot = townslot.Slot()
        taken = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:-1175.1,-2532.8,123.9",
            leader="Grug",
            column="",
            retaskable=(),
            now=1000.0,
        )
        slot.settle(taken, True, 1000.0)
        self.assertEqual("gather", slot.holder.claimant)
        # Somebody writes the column without telling the ledger.
        slot.want(
            claimant="mail",
            character="Grug",
            aim="mailbox",
            leader="Grug",
            column="auctioneer",
            retaskable=(),
            now=1060.0,
        )
        self.assertEqual(
            "",
            slot.holder.claimant,
            "an unrecorded write should orphan - this is the bug",
        )

    def test_adopt_makes_the_write_recognised_instead(self):
        slot = townslot.Slot()
        taken = slot.want(
            claimant="gather",
            character="Grug",
            aim="at:1:-1175.1,-2532.8,123.9",
            leader="Grug",
            column="",
            retaskable=(),
            now=1000.0,
        )
        slot.settle(taken, True, 1000.0)
        slot.adopt(claimant="auction", character="Grug", aim="auctioneer", now=1060.0)
        slot.want(
            claimant="mail",
            character="Grug",
            aim="mailbox",
            leader="Grug",
            column="auctioneer",
            retaskable=(),
            now=1061.0,
        )
        self.assertEqual("auction", slot.holder.claimant)

    def test_an_adopted_holder_is_on_the_ordinary_lease_not_the_orphan_one(self):
        """The whole point: a known owner can be out-waited, a stranger cannot."""
        slot = townslot.Slot(lease=300.0, orphan_lease=1200.0)
        slot.adopt(claimant="auction", character="Grug", aim="auctioneer", now=1000.0)
        # Past the ordinary lease but far inside the orphan one.
        d = slot.want(
            claimant="mail",
            character="Grug",
            aim="mailbox",
            leader="Grug",
            column="auctioneer",
            retaskable=("auctioneer",),
            now=1000.0 + 400.0,
        )
        self.assertTrue(
            d.granted,
            "an adopted holder must expire on the ordinary lease; if this "
            "fails the adopted write is still unassailable for 1200s",
        )

    def test_the_clock_does_not_restart_once_the_write_is_adopted(self):
        slot = townslot.Slot()
        slot.adopt(claimant="auction", character="Grug", aim="auctioneer", now=1000.0)
        slot.want(
            claimant="mail",
            character="Grug",
            aim="mailbox",
            leader="Grug",
            column="auctioneer",
            retaskable=(),
            now=1300.0,
        )
        first = slot.holder.since
        slot.want(
            claimant="bank",
            character="Grug",
            aim="banker",
            leader="Grug",
            column="auctioneer",
            retaskable=(),
            now=1600.0,
        )
        self.assertEqual(
            first,
            slot.holder.since,
            "the lease must continue, not re-arm on every poll",
        )

    def test_adopt_refuses_an_incomplete_record(self):
        """A half-known holder is worse than an honest orphan."""
        slot = townslot.Slot()
        for kw in ({"claimant": ""}, {"character": ""}, {"aim": ""}):
            args = {
                "claimant": "auction",
                "character": "Grug",
                "aim": "auctioneer",
                "now": 1.0,
            }
            args.update(kw)
            slot.adopt(**args)
            self.assertIsNone(slot.holder, f"adopt should ignore {kw}")


class EveryUnledgeredTravelWriteTellsTheLedger(unittest.TestCase):
    """Pinned with `ast`, never a text search (infra#4194).

    `bridge.py`'s comments quote `_write_trade_errand` and `_claim_town_slot`
    verbatim while explaining this very bug, so a grep for those names matches
    the prose describing the problem and passes while the problem is live. This
    parses the module and asks the only question that matters: does every
    function that calls `_write_trade_errand` outside `_claim_town_slot` also
    tell the ledger about the write?
    """

    BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

    # `_claim_town_slot` IS the ledgered door - it calls `settle` itself, which
    # is the recording step. It is exempt by construction, not by exception.
    LEDGERED_DOOR = "_claim_town_slot"

    @staticmethod
    def _names(node) -> set:
        """Every name this function MENTIONS, not only the ones it calls.

        `_write_trade_errand` is never called directly - every site passes it
        to `asyncio.to_thread`, so it appears as an ARGUMENT and a collector
        that only reads `Call.func` finds nothing at all. A first draft of this
        test did exactly that, reported zero offenders, and stayed green when
        the fix was reverted. It measured nothing.
        """
        out = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                out.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                out.add(sub.attr)
        return out

    def test_no_function_writes_the_column_without_recording_it(self):
        tree = ast.parse(self.BRIDGE.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == self.LEDGERED_DOOR:
                continue
            calls = self._names(node)
            if "_write_trade_errand" not in calls:
                continue
            if "adopt" in calls or "settle" in calls:
                continue
            offenders.append(f"{node.name} (line {node.lineno})")
        self.assertEqual(
            [],
            offenders,
            "these write travel_npc without telling the ledger, so the next "
            f"want() orphans the column on the long lease: {offenders}",
        )
