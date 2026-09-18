"""A vendor errand that ended up on a follower is released by somebody.

WHAT WAS MEASURED, ON wow-dev, 2026-09-13, WITH infra#3717 DEPLOYED. The
leader's vendor errand now has a terminal path and uses it. A follower's does
not:

    name  lead  job    travel_npc          (20:20)
    Grug  1     craft  repair
    Bork  0     craft  vendor
    Grog  0     craft
    Og    0     craft
    Ugga  0     craft

Re-read at 20:45 the same row was still `Bork | lead=0 | travel_npc=vendor`,
by then with `job=quest`, and Bork's own sell queue held 0 `pending` and 0
`claimed` rows against 358 `delivered`. `_settle_vendor_errand` reads
`leader = await asyncio.to_thread(_head_now)` and hands that one name to
`_release_trade_errand`, whose UPDATE is
`WHERE name = %s AND travel_npc = %s`. Nothing in the process ever names Bork,
so his column cannot empty - not this cycle, not any cycle.

IT IS NOT INERT. `_aimed_names` is `drive_quest <> 0 OR travel_npc <> ''`,
`_give_them_a_life` hands every aimed character `nc +new rpg`, and
mod-overseer's `CanBeSentToNpc(botAI)` is exactly
`botAI->HasStrategy("new rpg", ...)`, so `TravelHoldsTheWheel` -
`!travelTarget.empty() && (CanBeSentToNpc(botAI) || MaySteerItself(name))` -
makes itself true off the stale column and stands that follower's quest drive
down for ever. mod-overseer will not clear it: `vendor` is one of the four aims
`IsMaintenanceErrand` covers, so `TravelAimBook::Release` reaches "errand done,
releasing" and skips the column write (the infra#3655 fence). The bridge is the
only side that can.

AND THE RELEASE HAS TO BE REACHED, NOT MERELY WRITTEN. A stranded aim's
completion signal is its own sell queue going quiet, and a quiet queue is
exactly the state in which this pass has nothing to sell and returns early:
measured, the last `kind='sell'` row on wow-dev was written at 18:02:30 and the
column still stood at 20:45, which is roughly 108 consecutive 90-second cycles
in which a release below `family_town_run_needed` would never have run. The
sequence model at the bottom of this file runs the sweep in both positions and
shows the low one is worth precisely as much as no sweep at all.
"""
import pathlib
import re
import unittest

import bag_pressure

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PACKAGE / "bridge.py"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = _source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


def _code(signature: str) -> str:
    """The same block with its docstring removed.

    The prose above a function is allowed to describe the states it does not
    reach; the CODE is what has to be checked for an order or a guard.
    """
    body = _block(signature)
    marker = '"""'
    if body.count(marker) >= 2:
        return body.split(marker, 2)[2]
    return body


def _statements(signature: str) -> str:
    """The same block again with the `#` commentary stripped out too.

    This codebase argues at length in comments on purpose, and those comments
    name the very functions these tests order - the sweep's own comment block
    names `family_town_run_needed` while explaining why it must run above it,
    which puts that string hundreds of characters BEFORE the call it describes.
    Any test that orders or counts a call has to read the statements.
    """
    return "\n".join(line for line in _code(signature).splitlines()
                     if not line.lstrip().startswith("#"))


class AStrandedErrandEndsOnlyWhenItsOwnQueueIsQuiet(unittest.TestCase):
    """The pure rule, and the argument for each answer."""

    def test_a_drained_queue_is_the_one_thing_that_releases(self):
        """The live realm's own state: Bork holds `vendor`, and holds 0
        `pending` and 0 `claimed` sell rows of his own."""
        self.assertEqual(
            bag_pressure.stranded_errand_step(0),
            bag_pressure.VENDOR_ERRAND_RELEASE,
        )

    def test_rows_still_unanswered_hold(self):
        """The working half, and it must survive the fix. A follower's own
        rows execute when that follower is standing at the counter, so an
        errand with rows outstanding still has work in front of it."""
        self.assertEqual(
            bag_pressure.stranded_errand_step(4),
            bag_pressure.VENDOR_ERRAND_HOLD,
        )

    def test_an_unreadable_queue_holds_rather_than_releases(self):
        """NOT KNOWING IS A REASON TO HOLD. -1 is what `_outstanding_sales`
        reports when the command table cannot be read at all, and reading that
        as "finished" is the fail-open direction."""
        self.assertEqual(
            bag_pressure.stranded_errand_step(-1),
            bag_pressure.VENDOR_ERRAND_HOLD,
        )

    def test_nothing_but_a_drained_queue_ever_releases(self):
        """Swept rather than sampled, so a later edit cannot add a releasing
        case by accident - and so no timeout, age or idleness can creep in as
        a second way to end an errand."""
        for outstanding in (-99, -2, -1, 1, 2, 17, 358, 12881):
            with self.subTest(outstanding=outstanding):
                self.assertEqual(
                    bag_pressure.stranded_errand_step(outstanding),
                    bag_pressure.VENDOR_ERRAND_HOLD,
                )

    def test_it_never_answers_aim(self):
        """There is no third answer here and that is deliberate. A follower's
        aim walks nobody - `AimedMover::RefuseInFormation` says so in the
        worldserver log every time - so "aim it" is not a thing this rule may
        ever decide."""
        for outstanding in (-1, 0, 1, 9):
            with self.subTest(outstanding=outstanding):
                self.assertNotEqual(
                    bag_pressure.stranded_errand_step(outstanding),
                    bag_pressure.VENDOR_ERRAND_AIM,
                )

    def test_the_completion_rule_is_written_once(self):
        """The leader's half and the stranded half differ in everything EXCEPT
        what ends an errand. `vendor_errand_step` answers its at-counter branch
        by asking this function, so there is exactly one place that can ever be
        loosened into releasing on something softer than a quiet queue."""
        for outstanding in (-99, -1, 0, 1, 17, 1000):
            with self.subTest(outstanding=outstanding):
                self.assertEqual(
                    bag_pressure.vendor_errand_step(True, outstanding),
                    bag_pressure.stranded_errand_step(outstanding),
                )

    def test_the_leader_half_is_unchanged_away_from_the_counter(self):
        """Sharing the completion rule must not have shared the arrival rule.
        A leader that has not arrived is still aimed, whatever its queue says,
        because releasing it would cancel the journey."""
        for outstanding in (-1, 0, 4):
            with self.subTest(outstanding=outstanding):
                self.assertEqual(
                    bag_pressure.vendor_errand_step(False, outstanding),
                    bag_pressure.VENDOR_ERRAND_AIM,
                )


class TheBridgeCanFindAnErrandItIsNotCarryingItself(unittest.TestCase):
    """bridge.py imports discord and cannot be imported here, so the seam is
    read as text the way test_vendor_errand.py and test_bank_pass.py do."""

    def test_the_reader_exists_at_all(self):
        """The defect was that no code path ever NAMED the stranded row."""
        self.assertIn("def _errand_holders(", _source())

    def test_it_asks_the_roster_which_rows_carry_the_keyword(self):
        src = _source()
        start = src.index("_ERRAND_HOLDERS_SQL = (")
        sql = src[start:src.index("\n)", start)]
        self.assertIn("SELECT name FROM overseer_roster", sql)
        self.assertIn("enabled = 1", sql)
        self.assertIn("travel_npc = %%s", sql)
        self.assertIn("name IN (%s)", sql)

    def test_every_value_still_reaches_mysql_as_a_bound_parameter(self):
        """THE S608 SUPPRESSION IS ONLY HONEST WHILE THIS IS TRUE. What is
        interpolated is a run of `%s` placeholders whose count comes from
        `len(names)`; the keyword is spelled `%%s` so it survives the `%` as a
        placeholder, and both it and the names are passed to `cur.execute`. If
        a future edit formats a VALUE into this string the noqa becomes a lie,
        and this is the test that says so."""
        code = _code("def _errand_holders(")
        self.assertIn('placeholders = ",".join(["%s"] * len(names))', code)
        self.assertIn("_ERRAND_HOLDERS_SQL % placeholders", code)
        self.assertIn("cur.execute(sql, (travel_npc, *names))", code)

    def test_it_refuses_to_hunt_for_anything_but_an_economy_errand(self):
        """The fence one step earlier: a caller that cannot assemble the list
        of rows carrying a profession keyword cannot go on to blank one
        (mod-overseer#438)."""
        code = _code("def _errand_holders(")
        self.assertIn("if not _is_economy_aim(travel_npc):", code)
        self.assertLess(code.index("_is_economy_aim"), code.index("_connect()"))

    def test_a_world_without_the_column_yields_nobody(self):
        """"Nobody is carrying this" is the direction that releases nothing,
        which is the safe way to not know."""
        code = _code("def _errand_holders(")
        self.assertIn("in (1054, 1146)", code)
        self.assertIn("return []", code)


class TheKeywordGuardOnTheReleaseIsUntouched(unittest.TestCase):
    """Re-pinned here rather than assumed. This change gives
    `_release_trade_errand` a second caller and a second kind of caller, which
    is exactly when a guard gets quietly relaxed to suit one of them."""

    def test_the_keyword_is_still_in_the_where_clause(self):
        code = _code("def _release_trade_errand(")
        self.assertIn("WHERE name = %s AND travel_npc = %s", code)

    def test_it_still_refuses_anything_outside_the_economy(self):
        """infra#3703 renamed the question to `_is_economy_aim` and widened it
        to the aims the WRITE already treated as economy - a ground aim, a bare
        creature entry - because the two guards disagreeing is what left a
        vault aim with no way back out of the column. The refusal itself is
        unchanged and is exercised against a real trainer keyword in
        tests/test_town_slot.py."""
        code = _code("def _release_trade_errand(")
        self.assertIn("if not _is_economy_aim(travel_npc):", code)
        self.assertLess(code.index("_is_economy_aim"), code.index("_connect()"))

    def test_it_still_writes_the_column_back_to_empty_and_nothing_else(self):
        code = _code("def _release_trade_errand(")
        self.assertIn("SET travel_npc = ''", code)
        for column in ("learn_skill", "unlearn_skill", "craft_spell"):
            self.assertNotIn(column, code)


class TheSweepReleasesOnlyWhatItMayRelease(unittest.TestCase):

    def _sweep(self) -> str:
        return _statements(
            "    async def _release_stranded_vendor_errands(")

    def test_the_sweep_exists_at_all(self):
        self.assertIn("async def _release_stranded_vendor_errands(", _source())

    def test_it_releases_this_pass_s_own_keyword_and_no_other(self):
        """`travel_npc` is one slot four passes write, and each must hand back
        what it wrote. Releasing the town trip's `repair` or the bank pass's
        `banker` from the sell pass would be the cross-pass theft
        `_write_trade_errand`'s guard exists to prevent (mod-overseer#438)."""
        sweep = self._sweep()
        self.assertIn('_release_trade_errand, name, "vendor"', sweep)
        self.assertEqual(sweep.count("_release_trade_errand"), 1)
        for other in ('"repair"', '"banker"', '"guild banker"'):
            self.assertNotIn(other, sweep)

    def test_it_only_looks_for_vendor_rows_in_the_first_place(self):
        self.assertIn('_errand_holders, "vendor", names', self._sweep())

    def test_it_never_writes_an_aim(self):
        """A follower carrying a vendor aim is a row to hand back, never a
        character to send somewhere: aiming one is an UPDATE that moves nobody
        and costs it fifteen seconds of errand budget on every travel poll."""
        sweep = self._sweep()
        self.assertNotIn("_write_trade_errand", sweep)
        self.assertNotIn("_insert_sell", sweep)

    def test_it_asks_each_character_about_its_own_queue(self):
        """PER CHARACTER, NOT PER FAMILY. The leader's half reads the whole
        family's queue because the family walks as one; a stranded aim is on
        one row and moves one character nowhere, so holding it open because a
        SIBLING has rows outstanding would latch it on the exact realm state
        this defect was found in."""
        sweep = self._sweep()
        self.assertIn("_outstanding_sales, [name]", sweep)
        self.assertIn("bag_pressure.stranded_errand_step(outstanding)", sweep)

    def test_only_a_release_verdict_writes_anything(self):
        """Hold and release are opposite intentions, and the bug class this
        whole area keeps producing is the one where both read as "no write"."""
        sweep = self._sweep()
        self.assertIn("if step != bag_pressure.VENDOR_ERRAND_RELEASE:", sweep)
        self.assertLess(sweep.index("VENDOR_ERRAND_RELEASE"),
                        sweep.index("_release_trade_errand"))

    def test_the_leader_is_excluded_by_name(self):
        """LOAD-BEARING, NOT TIDY. A leader that has just been aimed is still
        walking and has no rows queued yet - rows are only written for a holder
        already in reach of a counter - so its own queue reads 0 and this rule
        would cancel the journey on the cycle it was ordered. The leader's
        errand ends on arrival plus a quiet queue, and `_settle_vendor_errand`
        is what settles it."""
        self.assertIn("if name != leader", self._sweep())

    def test_without_a_leader_it_sweeps_nobody(self):
        """"Stranded" is defined against `_head_now()`. With no answer there is
        no way to tell the one character that can walk from the four that
        cannot, and every standing aim would be swept including the live one."""
        sweep = self._sweep()
        self.assertIn("if not leader:", sweep)
        self.assertLess(sweep.index("if not leader:"),
                        sweep.index("_errand_holders"))

    def test_the_leader_half_still_settles_exactly_one_errand(self):
        """The sweep is a separate method rather than more lines inside
        `_settle_vendor_errand`, so that function still asks one question and
        still releases one errand - which is the shape infra#3708 lifted it out
        whole to get."""
        settle = _statements("    async def _settle_vendor_errand(")
        self.assertEqual(settle.count("_release_trade_errand"), 2)
        self.assertIn('_release_trade_errand, leader, "vendor"', settle)
        self.assertNotIn("_errand_holders", settle)


class TheSweepIsActuallyReached(unittest.TestCase):
    """A release below an early return passes every test above and does
    nothing. These are the tests that say the control flow gets there."""

    def _pass(self) -> str:
        return _statements("    async def _vendor_once(")

    def test_the_pass_calls_it(self):
        body = self._pass()
        self.assertIn(
            "await self._release_stranded_vendor_errands(names, leader)", body)
        self.assertEqual(body.count("_release_stranded_vendor_errands"), 1)

    def test_it_runs_above_every_early_return_in_the_pass(self):
        """THE MEASURED REASON. A stranded aim's completion signal is its own
        sell queue going quiet, and a quiet queue is the state in which this
        pass has nothing to sell and returns early. On wow-dev the last
        `kind='sell'` row was written at 18:02:30 and `Bork.travel_npc` still
        read `vendor` at 20:45 - roughly 108 consecutive 90-second cycles in
        which a sweep below these gates would never have run once."""
        body = self._pass()
        swept = body.index("_release_stranded_vendor_errands")
        for gate in ("family_town_run_needed", "self._mid_run(",
                     "if not candidates:", "_fetch_free_slots"):
            with self.subTest(gate=gate):
                self.assertLess(swept, body.index(gate))

    def test_it_runs_with_the_leader_the_pass_already_read(self):
        """One read of `_head_now()` for the whole pass. Settling an errand
        against one leader and deciding who is stranded against another would
        be two leaders, and the second one could sweep the first one's live
        aim."""
        body = self._pass()
        self.assertLess(body.index("leader = await asyncio.to_thread(_head_now)"),
                        body.index("_release_stranded_vendor_errands"))
        self.assertEqual(body.count("_head_now"), 1)

    def test_the_leader_is_settled_before_anybody_is_called_stranded(self):
        """Order within the pair: the leader's own errand is given its proper
        completion test first, so a leader that has finished is released as a
        leader rather than left to be looked at twice."""
        body = self._pass()
        self.assertLess(body.index("_settle_vendor_errand"),
                        body.index("_release_stranded_vendor_errands"))

    def test_the_sweep_cannot_fight_the_aim_the_same_pass_writes(self):
        """The aim is written below the gates and only ever on the leader
        (infra#3553); the sweep runs above them and never on the leader. They
        cannot touch the same row in the same cycle."""
        body = self._pass()
        self.assertLess(body.index("_release_stranded_vendor_errands"),
                        body.index("_claim_town_slot"))
        self.assertEqual(body.count("_claim_town_slot"), 1)
        self.assertIn('self._claim_town_slot(', body)
        self.assertIn('"economy", leader, "vendor", urgent=True', body)


class TheStrandingIsActuallyBroken(unittest.TestCase):
    """A SEQUENCE test, because the defect lives across cycles and not inside
    any one decision.

    Every individual thing the pass did was defensible. It settled the errand
    the leader carried, against the right completion signal, and left every
    other row alone - which is correct for a column only the leader ever
    carries and wrong for the realm as it actually is. No single-pass assertion
    can see that, because on any one cycle "nothing was released" is the right
    answer for a leader who has not finished.

    The model below is the smallest world that can: two characters, one
    `travel_npc` slot each, a queue each, and a leader that has to WALK before
    it arrives. The follower starts carrying `vendor` - which is how the realm
    was found, and is reachable two ways, from the per-holder aims infra#3553
    stopped writing and from `overseer_roster.lead` moving while an aim stands.

    It is a MODEL and it is trusted for one property only: whether a column can
    return to empty, and whose. The facts it encodes are measured - the leader
    really arrives, the queues really drain, and the pass really does return
    early on the cycles when there is nothing to sell.
    """

    LEADER = "Grug"
    FOLLOWER = "Bork"

    @classmethod
    def _cycles(cls, count, sweep=True, sweep_below_the_gate=False,
                sweep_includes_the_leader=False, follower_queue_drains=True,
                sell_on=(), rows_each_trip=3, walk_cycles=2):
        """Run the pass `count` times and report both columns after each one.

        `sweep=False` is the pass as infra#3717 left it: the leader's errand
        settles, and a row on anybody else is named by nothing.
        `sell_on` is the set of cycle indices on which bag pressure is over the
        trigger and the pass gets past its gates at all; the default, no cycle
        at all, is the realm between 18:02 and 20:45.
        """
        leader, follower = cls.LEADER, cls.FOLLOWER
        column = {leader: "", follower: "vendor"}
        queue = {leader: 0, follower: 0 if follower_queue_drains else 2}
        walked = 0
        seen = []

        def sweep_now():
            who = [follower, leader] if sweep_includes_the_leader else [follower]
            for name in who:
                if column[name] != "vendor":
                    continue
                if (bag_pressure.stranded_errand_step(queue[name])
                        == bag_pressure.VENDOR_ERRAND_RELEASE):
                    column[name] = ""

        for cycle in range(count):
            # THE WORLD, BETWEEN TWO PASSES. Only the leader's aim walks
            # anybody: a follower carrying one is refused in formation, so its
            # column moves it nowhere and cannot be its own way out. Arrival
            # takes more than one pass, which is the fact that makes releasing
            # a walking leader a cancelled journey rather than a no-op.
            walked = walked + 1 if column[leader] == "vendor" else 0
            at_counter = walked >= walk_cycles
            if at_counter:
                queue[leader] = 0
                if follower_queue_drains:
                    queue[follower] = 0

            # THE PASS. The leader's own errand is settled first, above every
            # gate, exactly as infra#3708 left it.
            step = bag_pressure.vendor_errand_step(
                at_counter, queue[leader] + queue[follower])
            if step == bag_pressure.VENDOR_ERRAND_RELEASE:
                column[leader] = ""
            if sweep and not sweep_below_the_gate:
                sweep_now()

            # ...THEN THE GATES. A family with nothing to sell has returned by
            # here, and that is most cycles.
            if cycle in sell_on:
                if sweep and sweep_below_the_gate:
                    sweep_now()
                if step == bag_pressure.VENDOR_ERRAND_AIM:
                    column[leader] = "vendor"
                # Rows are only queued for a holder ALREADY in reach of a
                # counter, which is why a walking leader's own queue reads 0.
                if at_counter:
                    queue[leader] += rows_each_trip
            seen.append({leader: column[leader], follower: column[follower],
                         "arrived": at_counter})
        return seen

    def _follower(self, seen) -> list:
        return [cycle[self.FOLLOWER] for cycle in seen]

    def _leader(self, seen) -> list:
        return [cycle[self.LEADER] for cycle in seen]

    def test_the_old_pass_never_gives_a_followers_column_back(self):
        """THE DEFECT, REPRODUCED. The release names `_head_now()`, the column
        is on somebody else, and the UPDATE matches no row - for ever, whatever
        the family does afterwards."""
        seen = self._cycles(12, sweep=False)
        self.assertEqual(set(self._follower(seen)), {"vendor"})

    def test_the_new_pass_gives_it_back_on_the_first_cycle(self):
        """Same world, same quiet queue. Bork's own sell queue was already at
        0 `pending` and 0 `claimed` when this was measured, so there is nothing
        to wait for."""
        seen = self._cycles(12)
        self.assertEqual(self._follower(seen)[0], "")
        self.assertEqual(set(self._follower(seen)), {""})

    def test_a_sweep_below_the_gate_is_worth_exactly_as_much_as_no_sweep(self):
        """THE REACHABILITY TRAP, AS A MEASUREMENT. A stranded errand is
        finished BECAUSE there is nothing left to sell, and nothing left to
        sell is the cycle the pass returns early. Placed below the gates the
        release is written, tested, shipped - and never executed."""
        low = self._cycles(12, sweep_below_the_gate=True)
        none_at_all = self._cycles(12, sweep=False)
        self.assertEqual(self._follower(low), self._follower(none_at_all))
        self.assertEqual(set(self._follower(low)), {"vendor"})

    def test_a_low_sweep_fires_only_on_the_cycles_the_family_goes_shopping(self):
        """The same trap from the other side, and why it would have looked
        fixed in a dry run: give the family something to sell on every cycle
        and the low sweep works. The realm went 163 minutes without queueing a
        single sell row."""
        low = self._cycles(12, sweep_below_the_gate=True, sell_on=range(12))
        self.assertIn("", self._follower(low))

    def test_a_follower_with_rows_of_its_own_keeps_its_errand(self):
        """THE HALF A CARELESS FIX BREAKS. A follower whose sell rows are still
        unanswered has work in front of it, and no number of cycles turns that
        into permission to release. Released on completion, never on age."""
        seen = self._cycles(20, follower_queue_drains=False)
        self.assertEqual(set(self._follower(seen)), {"vendor"})

    def test_an_unreadable_queue_never_decays_into_a_release(self):
        """A database that cannot be read must not look like a finished
        errand, however long the process runs."""
        seen = self._cycles(20, follower_queue_drains=False)
        self.assertNotIn("", self._follower(seen))
        for _ in range(20):
            self.assertEqual(
                bag_pressure.stranded_errand_step(-1),
                bag_pressure.VENDOR_ERRAND_HOLD,
            )

    def test_sweeping_the_leader_too_would_cancel_the_journey(self):
        """WHY THE EXCLUSION IS LOAD-BEARING AND NOT TIDINESS. A leader aimed
        on one cycle is still walking on the next, and has no rows of its own
        yet because rows are only queued for a holder already in reach. Its own
        queue therefore reads 0, the stranded rule says "release", and the
        errand is handed back before the family ever reaches the counter."""
        excluded = self._cycles(8, sell_on={0})
        included = self._cycles(8, sell_on={0}, sweep_includes_the_leader=True)
        self.assertTrue(any(cycle["arrived"] for cycle in excluded))
        self.assertFalse(any(cycle["arrived"] for cycle in included))
        self.assertIn("vendor", self._leader(excluded))

    def test_the_leaders_own_errand_still_ends_the_way_infra3717_ends_it(self):
        """The sweep must not have changed the half that already worked: the
        leader is aimed, walks, arrives, and gives the column back when its
        queue is quiet."""
        seen = self._cycles(8, sell_on={0})
        self.assertEqual(self._leader(seen)[0], "vendor")
        self.assertIn("", self._leader(seen))
        self.assertTrue(any(cycle["arrived"] for cycle in seen))

    def test_a_family_that_restocks_every_cycle_still_round_trips(self):
        """The live realm's own shape once it is selling again (infra#3709 -
        something sellable reappears because the economy is selling the
        family's own profession tools back). The leader's column comes and
        goes; the follower's stays given back."""
        seen = self._cycles(12, sell_on=range(12))
        self.assertIn("", self._leader(seen))
        self.assertIn("vendor", self._leader(seen))
        self.assertEqual(set(self._follower(seen)), {""})

    def test_a_leadership_move_is_the_cause_that_has_no_last_occurrence(self):
        """The stranded row does not need a pre-infra#3553 write to exist. The
        errand is written to whoever led at the time, and `lead` moving while
        it stands leaves the old leader holding a column the next pass asks a
        different name to hand back - which is this model's opening state, and
        why the answer is a sweep rather than a one-off migration."""
        seen = self._cycles(6, sweep=False)
        self.assertEqual(self._follower(seen)[-1], "vendor")
        self.assertEqual(self._cycles(6)[-1][self.FOLLOWER], "")


if __name__ == "__main__":
    unittest.main()
