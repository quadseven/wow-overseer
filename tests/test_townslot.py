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
import unittest

import townslot


def want(name, waiting_since, last_asked=None):
    return townslot.Want(claimant=name, waiting_since=waiting_since,
                         last_asked=waiting_since if last_asked is None
                         else last_asked)


def holder(name, aim, since, character="Grug"):
    return townslot.Holder(claimant=name, character=character, aim=aim,
                           since=since)


def economy(aim):
    """The releasable predicate, as `bridge._is_economy_aim` answers it.

    Keywords the economy writes, a surveyed ground aim, a bare creature entry.
    A trainer errand is none of those and is the one this must refuse.
    """
    return (aim in ("vendor", "banker", "repair", "guild banker", "auctioneer")
            or aim.startswith("at:") or aim.isdigit())


def decide(**kw):
    """`townslot.decide` with the arguments a live caller always supplies."""
    base = dict(claimant="guild bank", character="Grug", aim="at:1:1,2,3",
                leader="Grug", column="", retaskable=("", "at:1:1,2,3"),
                holder=None, wants=(), last_served={}, now=0.0,
                releasable=economy)
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
        d = decide(character="Ugga", leader="Grug", column="vendor",
                   holder=holder("economy", "vendor", since=0.0), now=99999.0)
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
        d = slot.want(claimant="economy", character="Grug", aim="vendor",
                      leader="Grug", column="", retaskable=("", "vendor"),
                      now=10.0)
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
        d = slot.want(claimant="economy", character="Grug", aim="vendor",
                      leader="Grug", column="", retaskable=("", "vendor"),
                      now=10.0)
        slot.settle(d, False, 10.0)
        self.assertIsNone(slot.holder)
        self.assertEqual(["economy"], [w.claimant for w in slot.wants])

    def test_a_refused_write_keeps_the_pass_in_the_queue(self):
        """It waited, so it is a waiter. Starting it again from the back on
        every lost race is how a pass with a slow cycle never gets a turn."""
        slot = townslot.Slot(releasable=economy)
        d = slot.want(claimant="bank", character="Grug", aim="banker",
                      leader="Grug", column="vendor", retaskable=("", "banker"),
                      now=5.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        granted = slot.want(claimant="bank", character="Grug", aim="banker",
                            leader="Grug", column="",
                            retaskable=("", "banker"), now=600.0)
        slot.settle(granted, False, 600.0)
        self.assertEqual([5.0], [w.waiting_since for w in slot.wants])


class TheLeaseRunsFromWhenItWasTaken(unittest.TestCase):
    """THE RULE THE WHOLE FIX RESTS ON. Every one of these passes re-asserts
    its aim on its own cycle, so a lease renewed by re-assertion is a lease that
    never expires - which is the bug this module exists to end, rebuilt with an
    extra mechanism in front of it."""

    def test_the_same_pass_asking_again_holds_rather_than_rewrites(self):
        d = decide(claimant="economy", aim="vendor", column="vendor",
                   retaskable=("", "vendor"),
                   holder=holder("economy", "vendor", since=0.0), now=100.0)
        self.assertEqual(townslot.SLOT_HOLD, d.verdict)
        self.assertTrue(d.granted)
        self.assertFalse(d.writes)

    def test_a_hold_carries_the_original_start_time_forward(self):
        d = decide(claimant="economy", aim="vendor", column="vendor",
                   retaskable=("", "vendor"),
                   holder=holder("economy", "vendor", since=0.0), now=100.0)
        self.assertEqual(0.0, d.inherit_since)

    def test_re_asserting_for_an_hour_does_not_push_the_lease_out(self):
        slot = townslot.Slot(releasable=economy)
        d = slot.want(claimant="economy", character="Grug", aim="vendor",
                      leader="Grug", column="", retaskable=("", "vendor"),
                      now=0.0)
        slot.settle(d, True, 0.0)
        for minute in range(1, 60):
            again = slot.want(claimant="economy", character="Grug",
                              aim="vendor", leader="Grug", column="vendor",
                              retaskable=("", "vendor"), now=minute * 60.0)
            slot.settle(again, True, minute * 60.0)
        self.assertEqual(0.0, slot.holder.since)
        starved = slot.want(claimant="guild bank", character="Grug",
                            aim="at:1:1,2,3", leader="Grug", column="vendor",
                            retaskable=("", "at:1:1,2,3"), now=3600.0)
        self.assertEqual(townslot.SLOT_PREEMPT, starved.verdict)

    def test_a_hold_is_logged_and_writes_nothing(self):
        """Re-writing the same word makes mod-overseer's aim book erase its own
        state and read a standing errand as a brand new one, releasing and
        re-taking the counter hold every time (infra#3708)."""
        d = decide(claimant="economy", aim="vendor", column="vendor",
                   retaskable=("", "vendor"),
                   holder=holder("economy", "vendor", since=0.0), now=30.0)
        self.assertIn("already holds", d.reason)
        self.assertFalse(d.writes)


class AHeldErrandIsWaitedFor(unittest.TestCase):

    def test_a_live_errand_inside_its_lease_is_left_alone(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=120.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertFalse(d.granted)
        self.assertIsNone(d.release)

    def test_the_wait_says_how_much_lease_is_left(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=120.0)
        self.assertIn("held 120s of a 300s lease", d.reason)
        self.assertIn("180s left", d.reason)

    def test_the_wait_names_the_pass_that_holds_it(self):
        """"Already on another errand" cannot tell a pass starved by a live
        errand from one starved by an errand left behind."""
        d = decide(column="repair", holder=holder("towntrip", "repair", 0.0),
                   now=10.0)
        self.assertIn("towntrip", d.reason)
        self.assertIn("'repair'", d.reason)


class AStuckErrandLosesTheSlot(unittest.TestCase):
    """The actual defect. An errand that never completes held the family's one
    traveller for as long as it liked, and every other town errand starved
    behind it."""

    def test_the_lease_expiring_hands_the_slot_over(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=301.0)
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
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=612.0)
        self.assertIn("612s", d.reason)
        self.assertIn("past its 300s lease", d.reason)
        self.assertIn("infra#3703", d.reason)

    def test_one_second_before_the_lease_is_still_a_wait(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=299.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_the_lease_boundary_itself_hands_over(self):
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=300.0)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_a_longer_lease_can_be_configured_without_changing_the_rule(self):
        """The realm's walks are what the number is about, so it is a knob."""
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=301.0, lease=900.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_asking_is_waiting_so_the_first_ask_may_preempt(self):
        """A pass does not have to spend one whole cycle being refused before
        it is allowed to take a lapsed lease. Its cycle is ten minutes; making
        it wait two would be the starvation with a politer name."""
        slot = townslot.Slot(releasable=economy)
        d = slot.want(claimant="guild bank", character="Grug",
                      aim="at:1:1,2,3", leader="Grug", column="vendor",
                      retaskable=("", "at:1:1,2,3"), now=400.0)
        # The ledger has never seen this column, so it adopts it as an orphan
        # on the long lease - the honest answer for an errand it cannot name.
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        later = slot.want(claimant="guild bank", character="Grug",
                          aim="at:1:1,2,3", leader="Grug", column="vendor",
                          retaskable=("", "at:1:1,2,3"), now=1700.0)
        self.assertEqual(townslot.SLOT_PREEMPT, later.verdict)


class AnErrandTheEconomyMayNotTouchIsNeverTaken(unittest.TestCase):
    """mod-overseer#438. A profession trainer errand is a standing plan that
    outlives a town run and carries `learn_skill` with it; blanking one is the
    bug the whole guarded branch exists to prevent."""

    def test_a_trainer_errand_is_waited_for_however_long_it_runs(self):
        d = decide(column="profession trainer",
                   holder=holder("", "profession trainer", 0.0), now=99999.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIsNone(d.release)

    def test_the_reason_says_it_is_not_the_economy_s_to_hand_back(self):
        d = decide(column="profession trainer",
                   holder=holder("", "profession trainer", 0.0), now=99999.0)
        self.assertIn("not an errand the economy may hand back", d.reason)

    def test_with_no_predicate_supplied_nothing_is_ever_preempted(self):
        """Fail closed. A caller that forgets to wire the guard gets a module
        that arbitrates turn order and never takes anything from anybody."""
        d = decide(column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=99999.0, releasable=None)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_the_default_slot_is_fail_closed_too(self):
        slot = townslot.Slot()
        d = slot.want(claimant="bank", character="Grug", aim="banker",
                      leader="Grug", column="vendor", retaskable=("", "banker"),
                      now=99999.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)


class AnErrandWithNoOwnerGetsTheWorldsOwnClock(unittest.TestCase):
    """A restart forgets who holds what and finds the column still set. The
    honest thing to say about that aim is "somebody wrote this and it was not
    anybody I remember", and the honest thing to do with it is to leave it
    alone until mod-overseer's own backstop would have given up on it:
    TRAVEL_BACKSTOP_SECONDS is 20 minutes."""

    def test_an_unrecorded_column_becomes_a_holder_rather_than_nothing(self):
        slot = townslot.Slot(releasable=economy)
        d = slot.want(claimant="bank", character="Grug", aim="banker",
                      leader="Grug", column="repair", retaskable=("", "banker"),
                      now=50.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertEqual("repair", slot.holder.aim)
        self.assertEqual("", slot.holder.claimant)

    def test_an_orphan_is_not_preempted_on_the_short_lease(self):
        d = decide(column="repair", holder=holder("", "repair", 0.0), now=600.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("1200s lease", d.reason)

    def test_an_orphan_is_preempted_once_the_world_has_given_up_too(self):
        d = decide(column="repair", holder=holder("", "repair", 0.0),
                   now=1201.0)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_an_orphan_is_named_as_one(self):
        d = decide(column="repair", holder=holder("", "repair", 0.0),
                   now=1201.0)
        self.assertIn("an unknown writer", d.reason)

    def test_lease_for_answers_zero_for_nobody(self):
        self.assertEqual(0.0, townslot.lease_for(None))

    def test_lease_for_separates_the_two_cases(self):
        self.assertEqual(townslot.LEASE_SECONDS,
                         townslot.lease_for(holder("economy", "vendor", 0.0)))
        self.assertEqual(townslot.ORPHAN_LEASE_SECONDS,
                         townslot.lease_for(holder("", "vendor", 0.0)))

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
            claimant="craft_rhythm", character="Grug", leader="Grug",
            column="vendor", now=0.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, waiting.verdict)

        clear = slot.want_idle(
            claimant="craft_rhythm", character="Grug", leader="Grug",
            column="vendor", now=townslot.ORPHAN_LEASE_SECONDS,
        )
        self.assertEqual(townslot.SLOT_CLEAR, clear.verdict)
        self.assertEqual(holder("", "vendor", 0.0), clear.release)
        self.assertFalse(clear.writes)
        self.assertIn("infra#3728", clear.reason)

    def test_a_live_vendor_inside_its_lease_is_preserved(self):
        slot = townslot.Slot(releasable=economy)
        taken = slot.want(
            claimant="economy", character="Grug", aim="vendor",
            leader="Grug", column="", retaskable=("", "vendor"), now=0.0,
        )
        slot.settle(taken, True, 0.0)

        idle = slot.want_idle(
            claimant="craft_rhythm", character="Grug", leader="Grug",
            column="vendor", now=townslot.LEASE_SECONDS - 1,
        )
        self.assertEqual(townslot.SLOT_WAIT, idle.verdict)
        self.assertIsNone(idle.release)

    def test_a_profession_errand_is_never_cleared(self):
        slot = townslot.Slot(releasable=economy)
        idle = slot.want_idle(
            claimant="craft_rhythm", character="Grug", leader="Grug",
            column="profession trainer", now=99999.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, idle.verdict)
        self.assertIsNone(idle.release)

    def test_settling_a_clear_records_an_empty_slot(self):
        slot = townslot.Slot(releasable=economy)
        slot.want_idle(
            claimant="craft_rhythm", character="Grug", leader="Grug",
            column="vendor", now=0.0,
        )
        clear = slot.want_idle(
            claimant="craft_rhythm", character="Grug", leader="Grug",
            column="vendor", now=townslot.ORPHAN_LEASE_SECONDS,
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
        d = decide(claimant="craft_supply", aim="5594",
                   retaskable=("", "5594", "vendor"), column="vendor",
                   holder=holder("economy", "vendor", 0.0), now=60.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_the_refinement_says_what_it_is(self):
        d = decide(claimant="craft_supply", aim="5594",
                   retaskable=("", "5594", "vendor"), column="vendor",
                   holder=holder("economy", "vendor", 0.0), now=60.0)
        self.assertIn("refines", d.reason)
        self.assertIn("sharper resolution", d.reason)

    def test_a_different_errand_is_not_a_refinement(self):
        d = decide(claimant="bank", aim="banker", retaskable=("", "banker"),
                   column="vendor", holder=holder("economy", "vendor", 0.0),
                   now=60.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_a_refinement_inherits_the_lease_it_refines(self):
        """Two passes refining each other's aims must not be able to launder a
        lease between them and keep the column for ever."""
        d = decide(claimant="craft_supply", aim="5594",
                   retaskable=("", "5594", "vendor"), column="vendor",
                   holder=holder("economy", "vendor", 0.0), now=200.0)
        self.assertEqual(0.0, d.inherit_since)

    def test_the_inherited_lease_really_does_expire_on_the_old_clock(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(claimant="economy", character="Grug", aim="vendor",
                          leader="Grug", column="", retaskable=("", "vendor"),
                          now=0.0)
        slot.settle(first, True, 0.0)
        refined = slot.want(claimant="craft_supply", character="Grug",
                            aim="5594", leader="Grug", column="vendor",
                            retaskable=("", "5594", "vendor"), now=200.0)
        slot.settle(refined, True, 200.0)
        self.assertEqual(0.0, slot.holder.since)
        third = slot.want(claimant="guild bank", character="Grug",
                          aim="at:1:1,2,3", leader="Grug", column="5594",
                          retaskable=("", "at:1:1,2,3"), now=310.0)
        self.assertEqual(townslot.SLOT_PREEMPT, third.verdict)


class TheTurnGoesToWhoeverHasWaitedLongest(unittest.TestCase):

    def test_a_lapsed_lease_goes_to_the_longest_waiter_and_not_to_the_asker(self):
        d = decide(claimant="auction", aim="auctioneer",
                   retaskable=("", "auctioneer"), column="vendor",
                   holder=holder("economy", "vendor", 0.0),
                   wants=(want("guild bank", 10.0), want("auction", 200.0)),
                   now=400.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("guild bank", d.reason)

    def test_and_the_longest_waiter_itself_is_granted(self):
        d = decide(claimant="guild bank", aim="at:1:1,2,3",
                   retaskable=("", "at:1:1,2,3"), column="vendor",
                   holder=holder("economy", "vendor", 0.0),
                   wants=(want("guild bank", 10.0), want("auction", 200.0)),
                   now=400.0)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_the_refusal_says_how_much_longer_the_other_has_waited(self):
        d = decide(claimant="auction", aim="auctioneer",
                   retaskable=("", "auctioneer"), column="vendor",
                   holder=holder("economy", "vendor", 0.0),
                   wants=(want("guild bank", 10.0), want("auction", 200.0)),
                   now=400.0)
        self.assertIn("190s longer", d.reason)

    def test_the_order_is_the_wait_and_not_the_alphabet(self):
        ordered = townslot.fresh_wants(
            [want("auction", 5.0), want("bank", 1.0), want("towntrip", 3.0)],
            now=10.0)
        self.assertEqual(["bank", "towntrip", "auction"],
                         [w.claimant for w in ordered])

    def test_a_tie_is_broken_the_same_way_every_run(self):
        ordered = townslot.fresh_wants(
            [want("towntrip", 1.0), want("auction", 1.0)], now=10.0)
        self.assertEqual(["auction", "towntrip"],
                         [w.claimant for w in ordered])


class TheFreeColumnIsYieldedToWhoeverIsOwedIt(unittest.TestCase):
    """FAIRNESS THAT DOES NOT STARVE THE OTHER WAY. Without this a 300-second
    pass simply wins every race against a 600-second one for ever, which is how
    the guild bank pass spent its whole life: the column empties, the frequent
    pass takes it again, and the rare one samples a held column every time."""

    def test_a_pass_that_was_just_served_stands_aside(self):
        d = decide(claimant="economy", aim="vendor", retaskable=("", "vendor"),
                   column="", wants=(want("guild bank", 10.0),),
                   last_served={"economy": 300.0}, now=400.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("stands aside", d.reason)
        self.assertIn("guild bank", d.reason)

    def test_a_pass_that_has_never_been_served_takes_the_free_column(self):
        """It cannot owe anybody a turn it has never had."""
        d = decide(claimant="economy", aim="vendor", retaskable=("", "vendor"),
                   column="", wants=(want("guild bank", 10.0),),
                   last_served={}, now=400.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_it_does_not_stand_aside_for_a_pass_it_has_not_outrun(self):
        """The waiter was served more recently than this pass, so this pass is
        the one that is owed the turn."""
        d = decide(claimant="economy", aim="vendor", retaskable=("", "vendor"),
                   column="", wants=(want("guild bank", 10.0),),
                   last_served={"economy": 100.0, "guild bank": 200.0},
                   now=400.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_it_does_not_stand_aside_for_a_shorter_wait(self):
        d = decide(claimant="economy", aim="vendor", retaskable=("", "vendor"),
                   column="", wants=(want("economy", 10.0),
                                     want("guild bank", 300.0)),
                   last_served={"economy": 305.0}, now=400.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_the_pass_that_was_yielded_to_then_takes_it(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(claimant="economy", character="Grug", aim="vendor",
                          leader="Grug", column="", retaskable=("", "vendor"),
                          now=0.0)
        slot.settle(first, True, 0.0)
        starved = slot.want(claimant="guild bank", character="Grug",
                            aim="at:1:1,2,3", leader="Grug", column="vendor",
                            retaskable=("", "at:1:1,2,3"), now=60.0)
        self.assertEqual(townslot.SLOT_WAIT, starved.verdict)
        # The world clears the column when the sell queue drains.
        again = slot.want(claimant="economy", character="Grug", aim="vendor",
                          leader="Grug", column="", retaskable=("", "vendor"),
                          now=300.0)
        self.assertEqual(townslot.SLOT_WAIT, again.verdict)
        theirs = slot.want(claimant="guild bank", character="Grug",
                           aim="at:1:1,2,3", leader="Grug", column="",
                           retaskable=("", "at:1:1,2,3"), now=360.0)
        self.assertEqual(townslot.SLOT_TAKE, theirs.verdict)


class TheYieldIsBounded(unittest.TestCase):
    """THE OTHER DIRECTION, WHICH IS THE FAILURE A FAIRNESS FIX INVENTS. A want
    registered once and never renewed would otherwise hold the whole family's
    town work still for ever, on behalf of a loop that has stopped asking."""

    def test_a_want_nobody_renews_goes_stale(self):
        live = townslot.fresh_wants([want("guild bank", 0.0, last_asked=0.0)],
                                    now=901.0)
        self.assertEqual([], live)

    def test_a_stale_want_is_not_yielded_to(self):
        d = decide(claimant="economy", aim="vendor", retaskable=("", "vendor"),
                   column="", wants=(want("guild bank", 0.0, last_asked=0.0),),
                   last_served={"economy": 300.0}, now=1000.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)

    def test_a_want_renewed_by_a_living_loop_stays_live(self):
        d = decide(claimant="economy", aim="vendor", retaskable=("", "vendor"),
                   column="", wants=(want("guild bank", 0.0, last_asked=900.0),),
                   last_served={"economy": 300.0}, now=1000.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_a_stale_want_does_not_hold_up_a_lapsed_lease_either(self):
        d = decide(claimant="auction", aim="auctioneer",
                   retaskable=("", "auctioneer"), column="vendor",
                   holder=holder("economy", "vendor", 0.0),
                   wants=(want("guild bank", 0.0, last_asked=0.0),
                          want("auction", 500.0, last_asked=1000.0)),
                   now=1000.0)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_the_freshness_window_outlasts_the_longest_pass_cycle(self):
        """The slowest of these loops runs every 600 seconds, so a want must
        survive one missed cycle without being called abandoned."""
        self.assertGreater(townslot.WANT_FRESH_SECONDS, 600.0)

    def test_a_pass_can_give_up_its_turn_without_waiting_for_the_clock(self):
        slot = townslot.Slot(releasable=economy)
        d = slot.want(claimant="bank", character="Grug", aim="banker",
                      leader="Grug", column="vendor", retaskable=("", "banker"),
                      now=0.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        slot.forget("bank")
        self.assertEqual([], slot.wants)

    def test_an_aimless_ask_registers_no_want(self):
        """A pass with nothing to ask for is not a waiter, and must not be able
        to hold the column still for a journey nobody wants taken."""
        slot = townslot.Slot(releasable=economy)
        d = slot.want(claimant="forge", character="Grug", aim="",
                      leader="Grug", column="vendor", retaskable=(), now=0.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertFalse(d.granted)
        self.assertEqual([], slot.wants)


class TheLedgerLearnsFromTheColumn(unittest.TestCase):
    """THE WORLD IS THE AUTHORITY AND THIS MEMORY IS NOT. mod-overseer clears
    `travel_npc` itself on arrival, on its own unreachable backstop, and when an
    errand has killed a character often enough to be called off. None of that
    comes back to this process except as an emptied column."""

    def test_an_emptied_column_ends_the_errand_whoever_ended_it(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(claimant="economy", character="Grug", aim="vendor",
                          leader="Grug", column="", retaskable=("", "vendor"),
                          now=0.0)
        slot.settle(first, True, 0.0)
        theirs = slot.want(claimant="bank", character="Grug", aim="banker",
                           leader="Grug", column="", retaskable=("", "banker"),
                           now=60.0)
        self.assertEqual(townslot.SLOT_TAKE, theirs.verdict)

    def test_a_column_somebody_else_wrote_replaces_the_remembered_holder(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(claimant="economy", character="Grug", aim="vendor",
                          leader="Grug", column="", retaskable=("", "vendor"),
                          now=0.0)
        slot.settle(first, True, 0.0)
        slot.want(claimant="bank", character="Grug", aim="banker",
                  leader="Grug", column="profession trainer",
                  retaskable=("", "banker"), now=60.0)
        self.assertEqual("profession trainer", slot.holder.aim)
        self.assertEqual("", slot.holder.claimant)
        self.assertEqual(60.0, slot.holder.since)

    def test_a_new_leader_forgets_the_old_leaders_errand(self):
        """The aim on that row moves nobody now, and it is not this slot's to
        arbitrate: only the leader travels."""
        slot = townslot.Slot(releasable=economy)
        first = slot.want(claimant="economy", character="Grug", aim="vendor",
                          leader="Grug", column="", retaskable=("", "vendor"),
                          now=0.0)
        slot.settle(first, True, 0.0)
        d = slot.want(claimant="bank", character="Bork", aim="banker",
                      leader="Bork", column="", retaskable=("", "banker"),
                      now=60.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)
        self.assertIsNone(slot.holder)

    def test_an_unchanged_column_keeps_the_clock_running(self):
        slot = townslot.Slot(releasable=economy)
        first = slot.want(claimant="economy", character="Grug", aim="vendor",
                          leader="Grug", column="", retaskable=("", "vendor"),
                          now=0.0)
        slot.settle(first, True, 0.0)
        slot.want(claimant="bank", character="Grug", aim="banker",
                  leader="Grug", column="vendor", retaskable=("", "banker"),
                  now=120.0)
        self.assertEqual(0.0, slot.holder.since)


class TheDecisionSaysWhatToDoWithIt(unittest.TestCase):

    def test_granted_covers_every_way_to_end_up_with_or_clear_it(self):
        self.assertEqual(
            (townslot.SLOT_TAKE, townslot.SLOT_HOLD, townslot.SLOT_PREEMPT,
             townslot.SLOT_CLEAR),
            townslot.GRANTED)

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
        for kw in ({}, {"character": "Ugga"},
                   {"column": "vendor", "holder": holder("economy", "vendor", 0.0)},
                   {"column": "vendor", "holder": holder("economy", "vendor", 0.0),
                    "now": 9000.0},
                   {"aim": ""}):
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
        tree = ast.parse(
            pathlib.Path(townslot.__file__).read_text(encoding="utf-8"))
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
