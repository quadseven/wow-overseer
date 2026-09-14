"""A vendor errand ends, and it ends because its own queue went quiet.

WHAT WAS MEASURED, ON THE LIVE REALM, 2026-09-13. All five characters stood
inside one shop in Gadgetzan within 3.6 yards of each other for over half an
hour. `overseer_roster` held `Grog.travel_npc = 'vendor'` continuously, and the
worldserver said this every fifteen seconds, for hours:

    'Grog' reached 'vendor' (creature 5594) - errand done, releasing
    travel release for 'Grog' skipped the column write - a profession or
    economy errand is outstanding and this book never claimed the aim it
    would have erased

The module declares the errand finished and is not allowed to clear the column
(the fence infra#3655 added), and bridge.py held exactly one `SET travel_npc`
statement which only ever wrote a keyword. One writer that only ever sets is a
latch, and `TravelHoldsTheWheel` stands the quest drive down for as long as an
errand is outstanding.

THE ERRAND WAS NOT STALE, AND THE TESTS BELOW EXIST TO KEEP THE FIX FROM
PRETENDING IT WAS. The leader really had arrived - 4.4 yards from the merchant
against the core's 5.0 yard interact gate - and the sales really were landing,
seventeen `delivered` in the half hour it was watched. A rule that released an
errand for looking finished would have broken the half that works. So the only
thing allowed to end one is its queue emptying.

AND THE STATES THAT MATTER ARE NOT THE ONES THE REALM IS IN. The realm today is
permanently "at the counter with something to sell", so a test that only
described today would pass while proving nothing. Every branch below is
exercised deliberately, including the two the realm has never been in: a drained
queue at the counter, and a queue that cannot be read at all.
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

    This file's own first draft counted `_write_trade_errand` twice and called
    it two aims, because the comment above the call names the function it is
    explaining. This codebase argues at length in comments on purpose, so any
    test that COUNTS a call has to read the statements and not the prose.
    """
    return "\n".join(line for line in _code(signature).splitlines()
                     if not line.lstrip().startswith("#"))


class TheStepEndsAnErrandOnlyWhenItsQueueIsQuiet(unittest.TestCase):
    """The three answers, and the argument for each one."""

    def test_a_leader_away_from_a_counter_is_aimed(self):
        """The ordinary case, and the only one that existed before."""
        self.assertEqual(
            bag_pressure.vendor_errand_step(at_counter=False,
                                            sales_outstanding=4),
            bag_pressure.VENDOR_ERRAND_AIM,
        )

    def test_a_leader_away_from_a_counter_is_aimed_even_with_nothing_queued(self):
        """The walk comes FIRST. Rows are only queued for a holder already in
        reach, so an empty queue on the road is what a trip looks like before
        it has started, not after it has finished."""
        self.assertEqual(
            bag_pressure.vendor_errand_step(at_counter=False,
                                            sales_outstanding=0),
            bag_pressure.VENDOR_ERRAND_AIM,
        )

    def test_a_leader_at_the_counter_with_sales_pending_holds(self):
        """The live realm's own state on 2026-09-13. The errand is working;
        the answer is to leave it alone, NOT to re-assert it."""
        self.assertEqual(
            bag_pressure.vendor_errand_step(at_counter=True,
                                            sales_outstanding=4),
            bag_pressure.VENDOR_ERRAND_HOLD,
        )

    def test_a_leader_at_the_counter_with_a_drained_queue_releases(self):
        """The state the realm has never reached, and the whole point of the
        change: an errand that has done its work gives the column back."""
        self.assertEqual(
            bag_pressure.vendor_errand_step(at_counter=True,
                                            sales_outstanding=0),
            bag_pressure.VENDOR_ERRAND_RELEASE,
        )

    def test_an_unreadable_queue_holds_rather_than_releases(self):
        """NOT KNOWING IS A REASON TO HOLD. -1 is what the bridge reports when
        the command table is missing entirely. Reading that as "finished" is
        the fail-open direction, and it walks the leader away from rows already
        queued against the counter."""
        self.assertEqual(
            bag_pressure.vendor_errand_step(at_counter=True,
                                            sales_outstanding=-1),
            bag_pressure.VENDOR_ERRAND_HOLD,
        )

    def test_only_a_drained_queue_releases_and_nothing_else_does(self):
        """Swept rather than sampled, so a later edit cannot add a releasing
        case by accident."""
        for outstanding in (-99, -1, 1, 2, 17, 1000):
            with self.subTest(outstanding=outstanding):
                self.assertNotEqual(
                    bag_pressure.vendor_errand_step(True, outstanding),
                    bag_pressure.VENDOR_ERRAND_RELEASE,
                )

    def test_the_three_answers_are_distinct_words(self):
        """They are compared by value at the call site."""
        self.assertEqual(
            len({bag_pressure.VENDOR_ERRAND_AIM,
                 bag_pressure.VENDOR_ERRAND_HOLD,
                 bag_pressure.VENDOR_ERRAND_RELEASE}), 3)


class TheBridgeCanActuallyHandTheColumnBack(unittest.TestCase):
    """bridge.py imports discord and cannot be imported here, so the seam is
    read as text the way test_bank_pass.py already does."""

    def test_the_release_exists_at_all(self):
        """The defect was the absence of this function, not a bug inside one."""
        self.assertIn("def _release_trade_errand(", _source())

    def test_it_writes_the_column_back_to_empty(self):
        code = _code("def _release_trade_errand(")
        self.assertIn("SET travel_npc = ''", code)

    def test_it_can_only_release_the_errand_it_is_asked_about(self):
        """The keyword is in the WHERE clause, so a stale reading of who owns
        the column cannot turn into an erase of somebody else's errand."""
        code = _code("def _release_trade_errand(")
        self.assertIn("WHERE name = %s AND travel_npc = %s", code)

    def test_it_refuses_anything_that_is_not_an_economy_errand(self):
        """mod-overseer#438's bug, self-inflicted one file over: blanking a
        standing profession errand because an economy pass asked.

        THE GUARD MOVED TO `_is_economy_aim` IN infra#3703 AND THE FENCE DID
        NOT. It asks `_retaskable_from` - the same tuple the WRITE's WHERE
        clause is built from - so a ground aim is now releasable, because it
        was always writable down the same branch. What is still refused is the
        thing this test exists for, and tests/test_town_slot.py runs the real
        predicate against `profession trainer` rather than reading it."""
        code = _code("def _release_trade_errand(")
        self.assertIn("if not _is_economy_aim(travel_npc):", code)
        self.assertLess(code.index("_is_economy_aim"), code.index("_connect()"))

    def test_the_guard_covers_every_economy_errand_and_nothing_else(self):
        """The release is allowed exactly where the write is allowed."""
        src = _source()
        line = src[src.index("ECONOMY_ERRANDS = ("):]
        line = line[: line.index("\n")]
        self.assertIn('"vendor"', line)
        self.assertIn('"banker"', line)
        self.assertIn('"repair"', line)


class TheQueueReadIsTheOnlyCompletionSignal(unittest.TestCase):

    def _sql(self) -> str:
        """The hoisted query text.

        HOISTED RATHER THAN INLINE, AND NOT FOR TIDINESS. ruff anchors S608 at
        the START of the expression, so a `# noqa` on the line carrying the `%`
        does not silence a multi-line query - the file says so in four other
        places. The constant makes the interpolation one short line that can
        carry its own annotation, which is the form every other batched query
        here already uses.
        """
        src = _source()
        start = src.index("_OUTSTANDING_SALES_SQL = (")
        # To the closing paren at column 0, not the first `)` in the text -
        # `COUNT(*)` carries one three words in.
        return src[start:src.index("\n)", start)]

    def test_only_unanswered_rows_count_as_outstanding(self):
        """`delivered`, `error`, `applied`, `unchanged` and `verifying` are all
        ANSWERS. Counting the refusals would hold the errand open on 17,536
        all-time `vendor not in range` rows for ever."""
        self.assertIn("status IN ('pending', 'claimed')", self._sql())

    def test_it_only_counts_sell_rows(self):
        self.assertIn("kind = 'sell'", self._sql())

    def test_it_only_counts_the_family_it_was_asked_about(self):
        self.assertIn("target_name IN", self._sql())

    def test_every_value_still_reaches_mysql_as_a_bound_parameter(self):
        """THE S608 SUPPRESSION IS ONLY HONEST WHILE THIS IS TRUE. What is
        interpolated is a run of `%s` placeholders whose count comes from
        `len(names)`; the names themselves are passed to `cur.execute` as
        parameters. If a future edit ever formats a VALUE into this string the
        noqa becomes a lie, and this is the test that says so."""
        code = _code("def _outstanding_sales(")
        self.assertIn('placeholders = ",".join(["%s"] * len(names))', code)
        self.assertIn("_OUTSTANDING_SALES_SQL % placeholders", code)
        self.assertIn("cur.execute(sql, names)", code)

    def test_the_names_it_is_given_come_from_the_roster_and_not_a_caller(self):
        """The other half of the same argument: `names` in the pass is the
        `characters.name` column read back by `_protected_guids`, filtered by
        OVERSEER_NOTABLE_NAMES. No request, message or item name reaches it."""
        body = _code("    async def _vendor_once(")
        self.assertIn("_protected_guids", body)
        self.assertIn("_outstanding_sales", _code("    async def _settle_vendor_errand("))

    def test_an_unreadable_queue_reports_minus_one_and_not_zero(self):
        """Returning 0 would make a missing table look exactly like a finished
        errand, which is the one reading that must never happen by accident."""
        code = _code("def _outstanding_sales(")
        self.assertIn("return -1", code)
        self.assertNotIn("return 0\n            raise", code)

    def test_no_names_is_nothing_outstanding_rather_than_unknown(self):
        """An empty roster has no queue, which is a fact and not a failure."""
        code = _code("def _outstanding_sales(")
        self.assertIn("if not names:", code)


class ThePassAimsOnceAndReleasesLast(unittest.TestCase):

    def _pass(self) -> str:
        """Statements only. This pass argues its reasoning at length in
        comments that name the very functions these tests order, so reading the
        prose puts `family_town_run_needed` hundreds of characters before the
        call it is describing. Caught twice while writing this file."""
        return _statements("    async def _vendor_once(")

    def _settle(self) -> str:
        return _statements("    async def _settle_vendor_errand(")

    def test_the_step_decides_whether_an_aim_is_written(self):
        """The unconditional write on every cycle is what built the latch."""
        self.assertIn("bag_pressure.vendor_errand_step(", self._settle())
        self.assertIn("if step == bag_pressure.VENDOR_ERRAND_AIM:", self._pass())

    def test_the_settling_is_one_function_with_one_question(self):
        """LIFTED OUT WHOLE. The draft that kept it inline put the release
        below three early returns where it could never fire, which is a
        control-flow bug in a function that had grown past holding in a head.
        `_vendor_once` asks the question once and reads one answer."""
        body = self._pass()
        self.assertIn("step = await self._settle_vendor_errand(names, leader)",
                      body)
        self.assertEqual(body.count("_settle_vendor_errand"), 1)

    def test_the_settling_releases_nothing_but_this_pass_s_own_errand(self):
        """`travel_npc` is one slot four passes write. Releasing the town
        trip's `repair` from here would be the cross-pass theft
        `_write_trade_errand`'s guard exists to prevent (mod-overseer#438).
        Measured 2026-09-13: the leader re-armed as `repair` about five minutes
        after the column was cleared by hand, so the other three are latched
        exactly as this one was and are filed separately."""
        settle = self._settle()
        self.assertIn('_release_trade_errand, leader, "vendor"', settle)
        for other in ('"repair"', '"banker"', '"guild banker"'):
            self.assertNotIn(other, settle)

    def test_the_aim_is_still_written_before_any_row_that_needs_it(self):
        """Unchanged from before, and for the same reason the bank pass gives:
        a queue written before the walk is a queue of refusals."""
        body = self._pass()
        self.assertLess(body.index("_claim_town_slot"),
                        body.index("_insert_sell"))

    def test_the_errand_is_settled_above_every_early_return(self):
        """THE ORDERING BUG THIS FILE'S OWN SEQUENCE MODEL CAUGHT. The release
        reads naturally at the bottom of the pass and rebuilds the latch one
        step along: an errand is only finished BECAUSE the selling worked, and
        selling empties the bags, so the cycle that would hand the column back
        is the same cycle `family_town_run_needed` returns False. A family that
        sold everything would have been parked for having succeeded."""
        body = self._pass()
        self.assertLess(body.index("_settle_vendor_errand"),
                        body.index("family_town_run_needed"))
        self.assertLess(body.index("_settle_vendor_errand"),
                        body.index("self._mid_run("))
        self.assertLess(body.index("_settle_vendor_errand"),
                        body.index("if not candidates:"))

    def test_ending_an_old_errand_does_not_depend_on_starting_a_new_one(self):
        """Nothing about a quiet bag makes a standing errand less finished."""
        body = self._pass()
        self.assertLess(body.index("_settle_vendor_errand"),
                        body.index("family_town_run_needed"))

    def test_the_errand_goes_to_the_family_leader_and_still_only_one(self):
        """infra#3553. Aiming a follower is an update that moves nobody and
        costs it fifteen seconds of its errand budget every poll.

        SINCE infra#3703 THE AIM GOES THROUGH `_claim_town_slot`, which reads
        `_head_now` itself and refuses anybody who is not the leader, so the
        rule is enforced rather than remembered. Still exactly one aim, and
        still onto `leader`."""
        body = _statements("    async def _vendor_once(")
        self.assertEqual(body.count("_claim_town_slot"), 1)
        self.assertEqual(self._settle().count("_release_trade_errand"), 1)
        self.assertIn('self._claim_town_slot("economy", leader, "vendor")', body)

    def test_the_release_names_the_same_keyword_it_aimed_with(self):
        """Releasing `repair` because a vendor pass finished would take the
        town trip's errand off a leader still walking to a repairer."""
        self.assertIn('_release_trade_errand, leader, "vendor"', self._settle())

    def test_where_the_leader_stands_is_read_from_the_live_snapshot(self):
        """`_fetch_town` reads overseer_snapshot within TOWN_COUNTER_YARDS, not
        the save timer, which on this realm is minutes behind."""
        settle = self._settle()
        self.assertIn("_fetch_town, leader", settle)
        self.assertIn("bool(leader_town.vendor)", settle)

    def test_the_pressure_gate_still_decides_whether_a_new_trip_is_made(self):
        """Settling the old errand moved above it; deciding on a new one did
        not. `family_town_run_needed` must still stand between the gates and
        any aim, or the family is walked to town on no pressure at all."""
        body = self._pass()
        self.assertLess(body.index("family_town_run_needed"),
                        body.index("_claim_town_slot"))
        self.assertLess(body.index("family_town_run_needed"),
                        body.index("_insert_sell"))


class TheLatchIsActuallyBroken(unittest.TestCase):
    """A SEQUENCE test, because the defect was never in any one decision.

    Every individual thing the old pass did was defensible. It aimed a leader at
    a vendor because there was something to sell, the leader walked there, the
    rows landed, and it aimed again next cycle because there was something to
    sell again. The bug only exists across cycles: the column had an entry and
    no exit, so no single-pass assertion can see it. The model below is the
    smallest thing that can - one `travel_npc` slot, one queue, and a world that
    drains it - and it runs the old rule and the new rule over the same world.

    It is a MODEL and it is only trusted for the one property it is asked about:
    whether the column can ever return to empty. The measured facts it encodes
    are the two that matter and both came off the live realm - the leader really
    does arrive, and the queue really does drain (seventeen `delivered` in half
    an hour).
    """

    @staticmethod
    def _cycles(count, new_rows_each_cycle=0, queue_drains=True, settle=True):
        """Run the pass `count` times and report `travel_npc` after each one.

        The world starts where the realm was found: a trip has been issued and
        rows are outstanding. `settle=False` is the old pass, which aimed
        whenever it had work and never handed anything back.
        """
        column, queue, at_counter = "vendor", 2, False
        seen = []
        for _ in range(count):
            # THE WORLD, BETWEEN TWO PASSES. A leader carrying an aim reaches
            # the counter - measured at 4.4 yards against the core's 5.0 yard
            # interact gate - and a leader carrying none eventually wanders off
            # it, which is the entire point of handing the column back. What is
            # queued is answered while it stands there, in "tens of seconds" by
            # mod-overseer's own reckoning of the drain rate.
            if column == "vendor":
                at_counter = True
            elif at_counter:
                at_counter = False
            if at_counter and queue_drains:
                queue = 0

            # THE PASS. Settling the old errand first, above every gate.
            step = (bag_pressure.vendor_errand_step(at_counter, queue)
                    if settle else bag_pressure.VENDOR_ERRAND_AIM)
            if settle and step == bag_pressure.VENDOR_ERRAND_RELEASE:
                column = ""
            # ...then the gates, and only a family with something to sell
            # reaches the aim at all.
            if new_rows_each_cycle:
                if step == bag_pressure.VENDOR_ERRAND_AIM:
                    column = "vendor"
                queue += new_rows_each_cycle
            seen.append(column)
        return seen

    def test_the_old_rule_never_gives_the_column_back(self):
        """THE DEFECT, REPRODUCED. With no terminal path `travel_npc` is set
        once and is never empty again, whatever the family does afterwards, so
        TravelHoldsTheWheel stands the quest drive down for ever."""
        seen = self._cycles(12, settle=False)
        self.assertEqual(set(seen), {"vendor"})

    def test_the_new_rule_gives_it_back_once_the_queue_is_quiet(self):
        """Same world, same arrival, same drained queue."""
        seen = self._cycles(12)
        self.assertEqual(seen[0], "")
        self.assertEqual(set(seen), {""})

    def test_a_queue_that_never_drains_keeps_its_errand_for_ever(self):
        """THE HALF A CARELESS FIX BREAKS, and the coordinator's correction in
        one test: the errand that parked the family was real and working. A
        leader whose rows are still unanswered keeps the column, no matter how
        many cycles pass, because it has to be standing at the counter when its
        own rows execute."""
        seen = self._cycles(20, queue_drains=False)
        self.assertEqual(set(seen), {"vendor"})

    def test_a_family_that_restocks_every_cycle_is_no_longer_parked(self):
        """The live realm's own shape, and the honest result rather than a
        flattering one. Something sellable reappears on every single cycle
        (infra#3709 - the economy is selling the family's own profession tools
        and they are re-acquired), so the leader does go back. What changes is
        that it is a round trip rather than a parking space: the column empties
        on the cycles the trip is finished, which is time the quest drive can
        pick somebody up in. Ending the restock loop is infra#3709's job, not
        this one's."""
        seen = self._cycles(12, new_rows_each_cycle=3)
        self.assertIn("", seen)
        self.assertIn("vendor", seen)

    def test_an_unreadable_queue_never_releases_however_long_it_runs(self):
        """A database that cannot be read must not decay into a release."""
        seen = self._cycles(20, queue_drains=False)
        self.assertNotIn("", seen)
        for _ in range(20):
            self.assertEqual(
                bag_pressure.vendor_errand_step(True, -1),
                bag_pressure.VENDOR_ERRAND_HOLD,
            )


if __name__ == "__main__":
    unittest.main()
