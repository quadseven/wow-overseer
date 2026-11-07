"""One claims module: who holds the column and who holds a member.

Characterization tests for the centralized interface. These pass against
the old townslot and bag_pressure paths and against the new claims
interface, proving the move changed no decision.

Pass-against-pass cases pinned here:

* A released bag hold keeps the quest walk it handed over (#872): once
  the hold is released, bag pressure no longer releases the leader's
  ground aim; while it still stands, it does.
* A re-assertion does not renew a column lease.
* Urgency preempts only a releasable aim past its lease.
* A follower is never granted the column.
* A member hold judged on evidence releases only after the window with
  no gain, and a gain restarts the clock.

In-process rule: a fresh Claims store holds nothing. A bridge restart
forgets holds exactly as before, and each family's cohort keeps its own
column slot.
"""

import types
import unittest

import bag_pressure
import claims
import townslot


def economy(aim):
    return (
        aim in ("vendor", "banker", "repair", "guild banker", "auctioneer")
        or str(aim).startswith("at:")
        or str(aim).isdigit()
    )


def ground(aim):
    return str(aim).startswith("at:")


def decide(**kw):
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
    return claims.decide(**base)


def town_decide(**kw):
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


QUEST_WALK = "at:1:139.2,1325.8,193.5"
FAMILY = ("Bork", "Grog", "Grug", "Og", "Ugga")
MEASURED = {"Bork": 15, "Grog": 0, "Grug": 19, "Og": 10, "Ugga": 6}
WINDOW = bag_pressure.BAG_HOLD_STUCK_SECONDS


class TheTwoInterfacesAgree(unittest.TestCase):
    """Claims surfaces the townslot decisions without rewriting them."""

    def test_the_claims_slot_is_the_townslot_slot(self):
        self.assertIs(townslot.Slot, claims.Slot)

    def test_a_free_column_is_taken_the_same_way(self):
        self.assertEqual(town_decide().verdict, decide().verdict)
        self.assertEqual(town_decide().reason, decide().reason)

    def test_a_held_column_waits_the_same_way(self):
        holder = townslot.Holder("economy", "Grug", "vendor", since=0.0)
        old = town_decide(
            column="vendor",
            holder=holder,
            now=100.0,
        )
        new = decide(
            column="vendor",
            holder=holder,
            now=100.0,
        )
        self.assertEqual(old.verdict, new.verdict)
        self.assertEqual(townslot.SLOT_WAIT, new.verdict)

    def test_a_follower_is_refused_the_same_way(self):
        old = town_decide(character="Ugga")
        new = decide(character="Ugga")
        self.assertEqual(old.verdict, new.verdict)
        self.assertEqual(townslot.SLOT_NOT_THE_LEADER, new.verdict)

    def test_decide_is_the_same_function(self):
        self.assertIs(townslot.decide, claims.decide)

    def test_the_verdict_words_are_the_same(self):
        for name in (
            "SLOT_TAKE",
            "SLOT_HOLD",
            "SLOT_WAIT",
            "SLOT_PREEMPT",
            "SLOT_CLEAR",
            "SLOT_NOT_THE_LEADER",
            "SLOT_GIVE_UP",
        ):
            self.assertEqual(getattr(townslot, name), getattr(claims, name))


class ColumnLeaseRules(unittest.TestCase):
    def test_reassertion_does_not_renew_the_lease(self):
        holder = townslot.Holder("guild bank", "Grug", "at:1:1,2,3", since=0.0)
        first = decide(column="at:1:1,2,3", holder=holder, now=100.0)
        self.assertEqual(townslot.SLOT_HOLD, first.verdict)
        self.assertEqual(0.0, first.inherit_since)

    def test_an_expired_lease_is_preempted_by_the_next(self):
        holder = townslot.Holder("economy", "Grug", "vendor", since=0.0)
        d = decide(
            claimant="guild bank",
            aim="at:1:9,9,9",
            column="vendor",
            retaskable=("", "at:1:9,9,9"),
            holder=holder,
            now=claims.LEASE_SECONDS + 1.0,
        )
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)
        self.assertTrue(d.writes)
        self.assertIsNotNone(d.release)

    def test_release_is_legal_only_for_a_releasable_aim(self):
        holder = townslot.Holder("economy", "Grug", "vendor", since=0.0)
        trainer = townslot.Holder("economy", "Grug", "trainer:1", since=0.0)
        self.assertTrue(claims.release_legal(holder, economy))
        self.assertFalse(claims.release_legal(trainer, economy))

    def test_expiry_is_since_plus_the_lease(self):
        holder = townslot.Holder("economy", "Grug", "vendor", since=10.0)
        self.assertEqual(
            10.0 + claims.LEASE_SECONDS, claims.column_expiry(holder, 100.0)
        )

    def test_an_orphan_gets_the_longer_lease(self):
        orphan = townslot.Holder("", "Grug", "vendor", since=0.0)
        self.assertEqual(claims.ORPHAN_LEASE_SECONDS, claims.lease_for(orphan))


class AReleasedHoldKeepsTheQuestWalk(unittest.TestCase):
    """Pass against pass: the bag hold releases, the level pass walks,
    and the economy pass must not tear the walk down afterwards (#872)."""

    def test_the_pure_rule_released_means_no_release(self):
        self.assertFalse(
            claims.may_release_ground(
                aim=QUEST_WALK,
                pressure=True,
                in_run=False,
                hold_released=True,
                ground=ground,
            )
        )

    def test_the_pure_rule_standing_means_release(self):
        self.assertTrue(
            claims.may_release_ground(
                aim=QUEST_WALK,
                pressure=True,
                in_run=False,
                hold_released=False,
                ground=ground,
            )
        )

    def test_the_release_names_why_and_when(self):
        rel = claims.ground_release(
            aim=QUEST_WALK,
            pressure=True,
            in_run=False,
            hold_released=True,
            ground=ground,
        )
        self.assertFalse(rel.legal)
        self.assertIn("quest", rel.why.lower())

    def test_claims_and_townslot_agree_on_the_rule(self):
        for released in (True, False):
            self.assertEqual(
                townslot.urgent_ground_release(
                    aim=QUEST_WALK,
                    pressure=True,
                    in_run=False,
                    hold_released=released,
                    ground=ground,
                ),
                claims.may_release_ground(
                    aim=QUEST_WALK,
                    pressure=True,
                    in_run=False,
                    hold_released=released,
                    ground=ground,
                ),
            )


class MemberHoldsOverTime(unittest.TestCase):
    def test_nobody_at_the_floor_is_no_hold(self):
        self.assertIsNone(
            claims.member_hold_observe(FAMILY, {"Bork": 4, "Grog": 6}, 0.0)
        )

    def test_the_measured_family_is_held_on_grog(self):
        hold = claims.member_hold_observe(FAMILY, MEASURED, 0.0)
        self.assertEqual((), hold.stuck)
        self.assertIn("Grog", hold.why)
        self.assertEqual(hold.since + WINDOW, hold.expires_at)

    def test_no_gain_in_the_window_releases(self):
        hold = claims.member_hold_observe(FAMILY, MEASURED, 0.0)
        for minute in range(1, 46):
            hold = claims.member_hold_observe(
                FAMILY,
                MEASURED,
                60.0 * minute,
                previous=hold,
            )
        self.assertEqual(("Grog",), hold.stuck)
        self.assertTrue(hold.released)

    def test_a_gain_restarts_the_clock(self):
        hold = claims.member_hold_observe(FAMILY, MEASURED, 0.0)
        for minute in range(1, 41):
            hold = claims.member_hold_observe(
                FAMILY, MEASURED, 60.0 * minute, previous=hold
            )
        hold = claims.member_hold_observe(
            FAMILY, dict(MEASURED, Grog=2), 2460.0, previous=hold
        )
        self.assertEqual(2460.0, hold.since)
        self.assertEqual((), hold.stuck)

    def test_the_legal_release_is_the_stuck_members(self):
        hold = claims.member_hold_observe(FAMILY, MEASURED, 0.0)
        self.assertIsNone(hold.legal_release)
        for minute in range(1, 46):
            hold = claims.member_hold_observe(
                FAMILY, MEASURED, 60.0 * minute, previous=hold
            )
        self.assertEqual(("Grog",), hold.legal_release)

    def test_claims_and_bag_pressure_agree(self):
        progress = bag_pressure.bag_hold_progress(None, MEASURED, 0.0)
        hold = claims.member_hold_observe(FAMILY, MEASURED, 0.0)
        self.assertEqual(progress.best, hold.best)
        self.assertEqual(bag_pressure.bag_hold_stuck(progress), hold.stuck)

    def test_a_store_is_in_process_and_starts_empty(self):
        store = claims.MemberClaims()
        self.assertIsNone(store.current(FAMILY))
        self.assertFalse(store.released(FAMILY))
        hold = store.observe(FAMILY, MEASURED, 0.0)
        self.assertIsNotNone(hold)
        self.assertIsNotNone(store.current(FAMILY))
        store.reset(FAMILY)
        self.assertIsNone(store.current(FAMILY))


def knight(name="Brug", **kw):
    base = dict(
        name=name,
        online=True,
        class_id=6,
        map_id=609,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


class BusyAndStrandedKnights(unittest.TestCase):
    def test_busy_is_the_union_of_every_set(self):
        busy = claims.busy_members({"A"}, {"B", "C"}, (), ["D"], {"E"})
        self.assertEqual({"A", "B", "C", "D", "E"}, busy)

    def test_busy_includes_a_train_walk(self):
        busy = claims.busy_members({"A"}, {"T"})
        self.assertIn("T", busy)

    def test_a_knight_in_the_start_zone_is_freed(self):
        member = knight()
        held = {
            "guild run": {"Brug"},
            "crafter walk": {"Brug"},
        }
        freed = claims.stranded_knights([member], {"other": 0.0}, held)
        self.assertEqual({"Brug"}, freed)

    def test_a_knight_on_its_own_step_is_not_freed(self):
        member = knight()
        held = {"guild run": {"Brug"}}
        freed = claims.stranded_knights([member], {"Brug": 0.0}, held)
        self.assertEqual(set(), freed)

    def test_a_knight_outside_the_start_zone_is_not_freed(self):
        member = knight(map_id=1)
        held = {"guild run": {"Brug"}}
        freed = claims.stranded_knights([member], {}, held)
        self.assertEqual(set(), freed)

    def test_the_labels_name_what_held_it(self):
        member = knight()
        held = {"guild run": {"Brug"}, "crafter walk": {"Brug"}}
        labels = claims.stranded_held_labels([member], {}, held)
        self.assertEqual({"Brug": ("crafter walk", "guild run")}, labels)

    def test_the_death_knight_predicate_is_the_modules(self):
        import classquest

        member = knight(
            class_id=classquest.DEATH_KNIGHT, map_id=classquest.DEATH_KNIGHT_START_MAP
        )
        self.assertTrue(claims.is_stranded_knight(member))


class PerCohortSlots(unittest.TestCase):
    def test_each_cohort_gets_its_own_slot(self):
        store = claims.Claims(releasable=economy)
        own = store.slot_for(None)
        other = store.slot_for("Zug")
        self.assertIsNot(own, other)
        self.assertIs(own, store.slot_for(None))
        self.assertIs(other, store.slot_for("Zug"))

    def test_a_new_slot_is_in_memory_only(self):
        first = claims.new_column_slot(releasable=economy)
        second = claims.new_column_slot(releasable=economy)
        self.assertIsNot(first, second)
        self.assertIsNone(first.holder)


if __name__ == "__main__":
    unittest.main()
