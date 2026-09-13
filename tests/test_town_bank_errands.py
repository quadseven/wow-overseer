"""The repair and banker errands end, and they end on their own evidence.

WHAT WAS MEASURED, ON THE LIVE REALM, 2026-09-13. infra#3708/#3717 gave the
SELL pass's errand a terminal path. The other maintenance errands were latched
in the identical way, in the identical column, and one of them re-pinned the
family about five minutes after the vendor one let go:

    18:47  travel_npc cleared by hand for all five, job set to quest
    18:48  the family WALKS for the first time in ninety minutes
    ~18:52 SELECT name, travel_npc FROM overseer_roster;  ->  Grog | repair

Re-armed from `_towntrip_once`, which wrote
`professions.Errand(character=leader, travel_npc="repair")` unconditionally,
before anything was planned, and never wrote the column back. Read again at
20:20 the same evening, with this change unshipped:

    Grug  lead=1  job=craft  travel_npc=repair
    Bork  lead=0  job=craft  travel_npc=vendor

The world will not clear either of them and refuses on purpose.
`OverseerDecisions::IsMaintenanceErrand` is `CounterRoleForAim(aim) != None`,
which is true for exactly `vendor`, `banker`, `repair` and `auctioneer`, so
`TravelAimBook::Release` reaches "errand done, releasing" on arrival and then
skips its `UPDATE overseer_roster SET travel_npc = ''`. Its sibling comment on
PruneVanished names the half that is missing - "the bridge owns the column too
and clears it when it re-aims the family" - and the bridge never did.

AND `TravelHoldsTheWheel` STANDS THE QUEST DRIVE DOWN for as long as the column
is non-empty on a character that can be steered, so a latched errand is a family
that cannot quest, cannot gather and cannot reach an auction house.

THE STATES THAT MATTER ARE NOT THE ONES THE REALM IS IN. A dry run against the
realm as it stands proves very little: it is permanently "damaged, at no
counter, with an empty queue". Every branch below is exercised deliberately,
including the ones the realm has never reached - a trip that has asked for
everything it can ask for, a queue that cannot be read at all, and the arrival
cycle where the rows are about to be written.
"""
import pathlib
import re
import unittest

import bank
import towntrip

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

    This codebase argues at length in comments that name the very functions
    these tests order, so any test that ORDERS or COUNTS a call has to read the
    statements and not the prose. test_vendor_errand.py was caught by this
    twice while it was being written.
    """
    return "\n".join(line for line in _code(signature).splitlines()
                     if not line.lstrip().startswith("#"))


def _worn(fraction: float) -> towntrip.Equipped:
    return towntrip.Equipped(entry=1, name="Axe",
                             durability=int(100 * fraction), max_durability=100)


def _member(name: str, fraction: float = 1.0, **kw) -> towntrip.Member:
    return towntrip.Member(
        name=name, klass=kw.pop("klass", "warrior"), level=kw.pop("level", 30),
        money=kw.pop("money", 10_000), free_slots=kw.pop("free_slots", 10),
        equipped=(_worn(fraction),), **kw,
    )


class TheTownStepEndsAnErrandOnlyOnItsOwnEvidence(unittest.TestCase):
    """The four answers, and the argument for each one."""

    def test_a_leader_away_from_a_counter_with_work_to_do_is_aimed(self):
        """The ordinary case, and the only one that existed before."""
        self.assertEqual(
            towntrip.errand_step(at_counter=False, rows_outstanding=0,
                                 work_unasked=True),
            towntrip.TOWN_ERRAND_AIM,
        )

    def test_the_arrival_cycle_holds_rather_than_releasing(self):
        """THE ONE A NAIVE `queue is quiet` RULE BREAKS. Counter rows can only
        be written from a counter, so the cycle the family arrives is the cycle
        the queue is still empty AND the rows are about to be queued. Handing
        the column back first lets the quest drive pick them up and walk them
        off their own rows before the world executes them."""
        self.assertEqual(
            towntrip.errand_step(at_counter=True, rows_outstanding=0,
                                 work_unasked=True),
            towntrip.TOWN_ERRAND_HOLD,
        )

    def test_a_counter_with_rows_still_unanswered_holds(self):
        """The errand is working. The answer is to leave it alone, NOT to
        re-assert it: a fresh write makes the aim book erase its own state and
        read a standing errand as a new one, which releases and re-takes the
        300 second counter hold."""
        self.assertEqual(
            towntrip.errand_step(at_counter=True, rows_outstanding=3,
                                 work_unasked=False),
            towntrip.TOWN_ERRAND_HOLD,
        )

    def test_nothing_left_to_ask_for_releases(self):
        """The terminal path, and the whole point of the change."""
        self.assertEqual(
            towntrip.errand_step(at_counter=True, rows_outstanding=0,
                                 work_unasked=False),
            towntrip.TOWN_ERRAND_RELEASE,
        )

    def test_it_releases_away_from_the_counter_too_and_that_is_deliberate(self):
        """NOT AN ARRIVAL TEST WITH A HOLE IN IT. A counter row cannot be
        WRITTEN anywhere but at a counter, so "everything this trip wanted has
        already been asked for" cannot be true of a trip that never arrived.
        Requiring `at_counter` here would instead rebuild the latch on the exact
        case the issue flagged as awkward: mod-overseer repairs from its own leg
        via RepairAtTheCounter and RepairMemberHere without queueing a row at
        all, and when it does, the damage is simply gone and this trip has
        nothing left to do - with the column still set and nobody left to clear
        it."""
        self.assertEqual(
            towntrip.errand_step(at_counter=False, rows_outstanding=0,
                                 work_unasked=False),
            towntrip.TOWN_ERRAND_RELEASE,
        )

    def test_an_unreadable_queue_holds_rather_than_releasing(self):
        """NOT KNOWING IS A REASON TO HOLD. -1 is what the bridge reports when
        the command table cannot be read. Reading that as "finished" is the
        fail-open direction, and it walks the family away from rows already
        queued against the counter."""
        for unasked in (True, False):
            with self.subTest(work_unasked=unasked):
                self.assertEqual(
                    towntrip.errand_step(at_counter=True, rows_outstanding=-1,
                                         work_unasked=unasked),
                    towntrip.TOWN_ERRAND_HOLD,
                )

    def test_nothing_but_a_quiet_queue_ever_releases(self):
        """Swept rather than sampled, so a later edit cannot add a releasing
        case by accident."""
        for outstanding in (-99, -1, 1, 2, 17, 1000):
            for at_counter in (True, False):
                for unasked in (True, False):
                    with self.subTest(outstanding=outstanding,
                                      at_counter=at_counter, unasked=unasked):
                        self.assertNotEqual(
                            towntrip.errand_step(at_counter, outstanding,
                                                 unasked),
                            towntrip.TOWN_ERRAND_RELEASE,
                        )

    def test_an_aim_is_never_written_at_the_counter(self):
        """The measured churn of infra#3717, kept out of this pass too: sixteen
        fresh 300 second holds in four minutes, the ceiling never once
        reached."""
        for outstanding in (-1, 0, 5):
            for unasked in (True, False):
                with self.subTest(outstanding=outstanding, unasked=unasked):
                    self.assertNotEqual(
                        towntrip.errand_step(True, outstanding, unasked),
                        towntrip.TOWN_ERRAND_AIM,
                    )

    def test_the_three_answers_are_distinct_words(self):
        """They are compared by value at the call site."""
        self.assertEqual(
            len({towntrip.TOWN_ERRAND_AIM, towntrip.TOWN_ERRAND_HOLD,
                 towntrip.TOWN_ERRAND_RELEASE}), 3)


class TheCounterWorkIsWhatACounterHasToServe(unittest.TestCase):
    """`counter_keys` is the third input, and it is the one that decides
    whether the family is walked anywhere at all."""

    def test_damaged_gear_is_counter_work_even_with_no_repairer_in_reach(self):
        """THE WHOLE REASON THIS IS NOT READ OFF `plan`. With an empty Town,
        `plan` turns the same damage into a `blocked` sentence and emits no
        errand - and "no repairer is in reach" is precisely the state the travel
        aim exists to END. Reading the errands alone would answer "no counter
        work" for every character still walking towards the counter."""
        members = (_member("Grug", 0.94),)
        trip = towntrip.plan(members, towntrip.Town())
        self.assertEqual(trip.errands, ())
        self.assertEqual(towntrip.counter_keys(members, trip),
                         (("Grug", towntrip.REPAIR_COMMAND),))

    def test_undamaged_gear_is_not_counter_work(self):
        """The family that needs nothing is not walked to a repairer, which is
        what the unconditional write at the top of the pass used to do every
        five minutes whatever the family needed."""
        members = (_member("Grug", 1.0),)
        trip = towntrip.plan(members, towntrip.Town(repairs=True))
        self.assertEqual(towntrip.counter_keys(members, trip), ())

    def test_the_key_is_the_retry_windows_own_shape(self):
        """`_recent_town_keys` reads back (target_name, command) for everything
        this pass queued. A second shape here would be a join nobody tests."""
        members = (_member("Grug", 0.5),)
        trip = towntrip.plan(members, towntrip.Town(repairs=True))
        queued = {(e.member, e.command) for e in trip.errands
                  if e.kind == towntrip.REPAIR_KIND}
        self.assertEqual(set(towntrip.counter_keys(members, trip)), queued)

    def test_a_purchase_only_counts_once_a_vendor_can_actually_serve_it(self):
        """The mirror-image argument. What a vendor stocks and what a character
        can afford are only knowable once one is in reach, so a purchase nobody
        can serve is not a reason to walk anybody anywhere - `_buy` says so
        itself by returning a note rather than an errand."""
        hungry = _member("Og", 1.0, klass="mage", level=30, money=10_000_000)
        entry = towntrip._tier(towntrip.FOOD, hungry.level)[1]
        self.assertEqual(towntrip.counter_keys(
            (hungry,), towntrip.plan((hungry,), towntrip.Town())), ())
        stocked = towntrip.Town(vendor=True, stocks=frozenset({entry}))
        keys = towntrip.counter_keys((hungry,), towntrip.plan((hungry,), stocked))
        self.assertEqual([name for name, _ in keys], ["Og"])

    def test_conjuring_and_handing_on_are_never_counter_work(self):
        """Both are free, both work anywhere on any map. Holding a travel
        column open for them would hold it for work the column does not serve -
        a slow conjure would keep `travel_npc = 'repair'` standing, and
        TravelHoldsTheWheel stands the quest drive down for exactly as long."""
        self.assertNotIn(towntrip.CONJURE_KIND, towntrip.COUNTER_KINDS)
        self.assertNotIn(towntrip.GIVE_KIND, towntrip.COUNTER_KINDS)
        mage = _member("Og", 1.0, klass="mage", level=30,
                       spells=frozenset(towntrip.CONJURE_FOOD))
        trip = towntrip.plan((mage,), towntrip.Town())
        self.assertTrue([e for e in trip.errands
                         if e.kind == towntrip.CONJURE_KIND])
        self.assertEqual(towntrip.counter_keys((mage,), trip), ())

    def test_the_damage_rule_is_written_once(self):
        """Two copies would be two answers, and the one in the bridge would be
        the untested one."""
        source = (PACKAGE / "towntrip.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("e.fraction < ANY_DAMAGE"), 1)
        self.assertIn("damaged = _damaged(member)", source)
        self.assertNotIn("ANY_DAMAGE", _code("    async def _towntrip_once(self)"))
        self.assertNotIn("ANY_DAMAGE",
                         _code("    async def _settle_town_errand("))


class TheBankStepNeedsNoArrivalTest(unittest.TestCase):

    def test_moves_this_pass_has_not_asked_for_are_aimed(self):
        self.assertEqual(bank.errand_step(rows_outstanding=0,
                                          moves_unasked=True),
                         bank.BANK_ERRAND_AIM)

    def test_rows_still_unanswered_hold(self):
        self.assertEqual(bank.errand_step(rows_outstanding=2,
                                          moves_unasked=True),
                         bank.BANK_ERRAND_HOLD)

    def test_a_fully_answered_queue_with_nothing_left_to_ask_releases(self):
        self.assertEqual(bank.errand_step(rows_outstanding=0,
                                          moves_unasked=False),
                         bank.BANK_ERRAND_RELEASE)

    def test_an_unreadable_queue_holds(self):
        """Same fail-closed direction as every other reader of this queue."""
        for unasked in (True, False):
            with self.subTest(moves_unasked=unasked):
                self.assertEqual(bank.errand_step(-1, unasked),
                                 bank.BANK_ERRAND_HOLD)

    def test_only_a_quiet_queue_ever_releases(self):
        for outstanding in (-7, -1, 1, 9, 400):
            for unasked in (True, False):
                with self.subTest(outstanding=outstanding, unasked=unasked):
                    self.assertNotEqual(bank.errand_step(outstanding, unasked),
                                        bank.BANK_ERRAND_RELEASE)

    def test_the_three_answers_are_distinct_words(self):
        self.assertEqual(
            len({bank.BANK_ERRAND_AIM, bank.BANK_ERRAND_HOLD,
                 bank.BANK_ERRAND_RELEASE}), 3)


class TheBridgeCanActuallyHandBothColumnsBack(unittest.TestCase):
    """bridge.py imports discord and cannot be imported here, so the seams are
    read as text the way test_bank_pass.py and test_vendor_errand.py do."""

    def test_both_settlings_exist_at_all(self):
        """The defect was the absence of these, not a bug inside one."""
        src = _source()
        self.assertIn("async def _settle_town_errand(", src)
        self.assertIn("async def _settle_bank_errand(", src)

    def test_the_town_settling_releases_only_its_own_keyword(self):
        """`travel_npc` is one slot several passes write and each must hand back
        what it wrote. Releasing the sell pass's `vendor` from here would be the
        cross-pass theft `_write_trade_errand`'s guard exists to prevent
        (mod-overseer#438), and test_vendor_errand.py pins the mirror."""
        settle = _statements("    async def _settle_town_errand(")
        self.assertIn('_release_trade_errand, leader, "repair"', settle)
        self.assertEqual(settle.count("_release_trade_errand"), 1)
        for other in ('"vendor"', '"banker"', '"guild banker"'):
            self.assertNotIn(other, settle)

    def test_the_bank_settling_releases_only_its_own_keyword(self):
        settle = _statements("    async def _settle_bank_errand(")
        self.assertIn('_release_trade_errand, leader, "banker"', settle)
        self.assertEqual(settle.count("_release_trade_errand"), 1)
        for other in ('"vendor"', '"repair"', '"guild banker"'):
            self.assertNotIn(other, settle)

    def test_each_settling_aims_with_the_keyword_it_releases(self):
        """Aiming with one word and releasing with another is a latch with two
        names, which is worse than the latch it replaces because it looks
        fixed."""
        town = _statements("    async def _settle_town_errand(")
        self.assertIn('travel_npc="repair"', town)
        self.assertEqual(town.count("_write_trade_errand"), 1)
        bank_settle = _statements("    async def _settle_bank_errand(")
        self.assertIn('travel_npc="banker"', bank_settle)
        self.assertEqual(bank_settle.count("_write_trade_errand"), 1)

    def test_both_keywords_are_economy_errands(self):
        """`_release_trade_errand` refuses anything outside ECONOMY_ERRANDS
        outright, so a keyword missing from that tuple would make the release a
        warning and nothing else."""
        src = _source()
        line = src[src.index("ECONOMY_ERRANDS = ("):]
        line = line[: line.index("\n")]
        self.assertIn('"repair"', line)
        self.assertIn('"banker"', line)

    def test_the_aim_result_is_read_rather_than_discarded(self):
        """An economy errand may only retask an IDLE traveller, so an aim
        refused because another town pass owns the column is a real, expected
        outcome (infra#3703) - and it was invisible until somebody logged it
        (infra#3464, infra#3660)."""
        for settle in ("    async def _settle_town_errand(",
                       "    async def _settle_bank_errand("):
            with self.subTest(settle=settle):
                code = _statements(settle)
                self.assertIn("aimed = await asyncio.to_thread(", code)
                self.assertIn("if not aimed:", code)


class TheQueueReadIsTheOnlyCompletionSignal(unittest.TestCase):

    def _sql(self, name: str) -> str:
        src = _source()
        start = src.index("%s = (" % name)
        # To the closing paren at column 0, not the first `)` in the text -
        # `COUNT(*)` carries one three words in.
        return src[start:src.index("\n)", start)]

    def test_only_unanswered_rows_count_as_outstanding(self):
        """`delivered`, `error`, `applied`, `unchanged` and `verifying` are all
        ANSWERS. Counting the refusals would hold the errand open for ever on
        rows nothing can change - the same trap `_outstanding_sales` describes
        against 17,536 all-time `vendor not in range` rows, and the bank queue
        is already 141 error against 1 delivered all time."""
        for name in ("_OUTSTANDING_TOWN_SQL", "_OUTSTANDING_BANK_SQL"):
            with self.subTest(sql=name):
                self.assertIn("status IN ('pending', 'claimed')",
                              self._sql(name))

    def test_the_town_count_is_scoped_to_this_passs_own_rows(self):
        """The materials and bag passes write kind='give' rows of their own.
        A count that could not tell them apart would hold the repair errand open
        on somebody else's hand-off - the same scope `_recent_town_keys`
        already carries and for the same reason."""
        self.assertIn("source = 'towntrip'", self._sql("_OUTSTANDING_TOWN_SQL"))

    def test_the_town_count_names_no_kind_of_its_own(self):
        """The vocabulary is towntrip.COUNTER_KINDS, which is where it is
        tested. A fifth spelling of 'repair' in a WHERE clause is the one place
        a typo reads as "this trip has no counter work" - a silent release of a
        live errand rather than a loud failure."""
        sql = self._sql("_OUTSTANDING_TOWN_SQL")
        self.assertIn("kind IN (%s)", sql)
        self.assertNotIn("'repair'", sql)
        self.assertNotIn("'buy'", sql)
        self.assertIn("towntrip.COUNTER_KINDS",
                      _code("def _outstanding_town_work("))

    def test_both_counts_are_scoped_to_the_family_they_were_asked_about(self):
        for name in ("_OUTSTANDING_TOWN_SQL", "_OUTSTANDING_BANK_SQL"):
            with self.subTest(sql=name):
                self.assertIn("target_name IN", self._sql(name))

    def test_every_value_still_reaches_mysql_as_a_bound_parameter(self):
        """THE S608 SUPPRESSION IS ONLY HONEST WHILE THIS IS TRUE. What is
        interpolated is a run of `%s` placeholders whose count comes from
        `len(kinds)` and `len(names)`; both are passed to `cur.execute` as
        parameters. If a future edit ever formats a VALUE into this string the
        noqa becomes a lie, and this is the test that says so."""
        code = _code("def _outstanding_counts(")
        self.assertIn('",".join(["%s"] * len(kinds))', code)
        self.assertIn('",".join(["%s"] * len(names))', code)
        self.assertIn("cur.execute(statement, (*kinds, *names))", code)

    def test_an_unreadable_queue_reports_minus_one_and_not_zero(self):
        """Returning 0 would make a missing table look exactly like a finished
        errand, which is the one reading that must never happen by accident."""
        code = _code("def _outstanding_counts(")
        self.assertIn("return -1", code)
        self.assertIn("1054", code)
        self.assertIn("1146", code)
        self.assertIn("1265", code)

    def test_no_names_is_nothing_outstanding_rather_than_unknown(self):
        """An empty roster has no queue, which is a fact and not a failure."""
        self.assertIn("if not names:", _code("def _outstanding_counts("))

    def test_the_names_come_from_the_roster_and_not_from_a_caller(self):
        """`names` in both passes is the `characters.name` column read back by
        `_protected_guids`, filtered by OVERSEER_NOTABLE_NAMES. No request,
        message or item name reaches it."""
        for body in ("    async def _towntrip_once(self)",
                     "    async def _bank_once("):
            with self.subTest(body=body):
                self.assertIn("_protected_guids", _code(body))


class TheSettlingIsReachedOnTheCyclesThatMatter(unittest.TestCase):
    """PROVING THE CONTROL FLOW, WHICH IS THE HALF THAT HAS BEEN GOT WRONG.
    A release that sits below an early return can never fire on a finished
    trip, and its unit tests all pass while it does nothing. infra#3717 caught
    exactly that in the sell pass with a sequence model; these are the same
    assertions for the two passes here."""

    def _town(self) -> str:
        return _statements("    async def _towntrip_once(self)")

    def _bank(self) -> str:
        return _statements("    async def _bank_once(")

    def test_the_town_errand_is_settled_above_the_nothing_to_do_return(self):
        """THE ORDERING BUG, NAMED. `if not trip.errands: return` is the single
        most likely state for a FINISHED trip to be in - nothing left to repair
        and nothing left to buy is precisely what done looks like - so a release
        below it could never fire on the cycles that matter."""
        body = self._town()
        self.assertLess(body.index("_settle_town_errand"),
                        body.index("if not trip.errands:"))

    def test_the_bank_errand_is_settled_above_the_no_moves_return(self):
        """Same argument one pass over: an errand is finished BECAUSE the moves
        landed, and moves that landed are moves bank.plan no longer proposes."""
        body = self._bank()
        self.assertLess(body.index("_settle_bank_errand"),
                        body.index("if not bank_plan.moves:"))

    def test_exactly_one_gate_stands_above_each_settling(self):
        """COUNTED, NOT EYEBALLED. The failure mode this exists for is a
        release that sits below three early returns and can never fire - it
        passes every unit test it has and does nothing at all on the realm.
        The one gate allowed above each settling is the roster/mid-run guard
        at the top, which is the same one `_settle_vendor_errand` sits below
        for `not names` and above for `_mid_run`: a town errand issued while
        the family is inside an instance pulls the leader out and the party
        spreads, so the pass genuinely must not run at all there."""
        for body, settle in ((self._town(), "_settle_town_errand"),
                             (self._bank(), "_settle_bank_errand")):
            with self.subTest(settle=settle):
                above = body[: body.index(settle)]
                self.assertEqual(above.count("return"), 1)
                self.assertIn("if not names or await self._mid_run(names):",
                              above)

    def test_each_pass_asks_the_question_once_and_reads_one_answer(self):
        """LIFTED OUT WHOLE. One question with one answer belongs in one
        place."""
        self.assertEqual(self._town().count("_settle_town_errand"), 1)
        self.assertEqual(self._bank().count("_settle_bank_errand"), 1)

    def test_neither_pass_writes_the_column_outside_its_settling(self):
        """The unconditional write at the top of the pass IS the defect. A
        second one left behind would rebuild the latch beside the fix."""
        self.assertNotIn("_write_trade_errand", self._town())
        self.assertNotIn("_write_trade_errand", self._bank())

    def test_the_aim_still_precedes_every_row_that_needs_one(self):
        """Unchanged, and still true: a row queued for a counter nobody is
        walking to is a refusal waiting to be logged."""
        town = self._town()
        self.assertLess(town.index("_settle_town_errand"),
                        town.index("_insert_town_errand"))
        bank_body = self._bank()
        self.assertLess(bank_body.index("_settle_bank_errand"),
                        bank_body.index("_insert_bank"))

    def test_the_leader_is_read_once_and_used_for_both_halves(self):
        """Releasing an errand from one leader and aiming another would be two
        leaders, which is infra#3553 restated."""
        for body, settle in ((self._town(), "_settle_town_errand"),
                             (self._bank(), "_settle_bank_errand")):
            with self.subTest(settle=settle):
                self.assertIn("leader = await asyncio.to_thread(_head_now)",
                              body)
                self.assertIn("self.%s(names, leader" % settle, body)

    def test_the_retry_window_is_read_before_the_errand_is_settled(self):
        """It is half of "has this trip anything left to ask for". Reading it
        twice would be two answers to one question."""
        town = self._town()
        self.assertLess(town.index("_recent_town_keys"),
                        town.index("_settle_town_errand"))
        self.assertIn("towntrip.counter_keys(members, trip)", town)
        bank_body = self._bank()
        self.assertLess(bank_body.index("_recent_bank_keys"),
                        bank_body.index("_settle_bank_errand"))


class TheGuildBankErrandIsNotOneOfThese(unittest.TestCase):
    """THE THIRD ERRAND infra#3728 NAMES, AND THE ISSUE IS OUT OF DATE ON IT.

    #3728's table says `_guild_bank_once` writes `travel_npc='guild banker'`
    and is latched like the other two. It has not written that keyword since
    infra#3702: no creature template in the world carries
    UNIT_NPC_FLAG_GUILD_BANKER, so the keyword could never resolve to a spawn,
    and the pass now aims at the vault's own gameobject spawn as an
    `at:<map>:<x>,<y>,<z>` ground aim instead.

    THAT CHANGES THE ANSWER RATHER THAN THE WORK. `IsMaintenanceErrand` is
    `CounterRoleForAim(aim) != None`, and `CounterRoleForAim` matches whole
    keywords only - vendor, banker, repair, auctioneer. A ground aim is none of
    them (mod-overseer's own tests pin
    `IsMaintenanceErrand("at:1:-705,-2045,66") == false`), so
    `TravelAimBook::Release` takes its `else` branch and the module clears the
    column itself the moment the walk arrives. The guild bank errand has a
    terminal path already, owned by the world, and there is nothing here to
    fix. Read live 2026-09-13 20:20, no character held a guild-bank aim of
    either shape.

    AND `_release_trade_errand` COULD NOT RELEASE ONE ANYWAY: it refuses any
    keyword outside ECONOMY_ERRANDS, and a ground aim is not in it - correctly,
    because that tuple is whole keywords too.
    """

    def test_the_pass_writes_a_ground_aim_and_not_the_keyword(self):
        code = _statements("    async def _guild_bank_once(")
        self.assertIn("travel_npc=vault.aim", code)
        self.assertNotIn('"guild banker"', code)

    def test_no_settling_was_added_for_it(self):
        """A release keyed on something the world already clears would be a
        second writer racing the first."""
        self.assertNotIn("_settle_guild_bank_errand", _source())

    def test_the_release_guard_still_refuses_a_ground_aim(self):
        """Widening ECONOMY_ERRANDS to cover one would let an economy pass
        blank a `learn_skill` errand on its way past - mod-overseer#438's bug
        re-created one file over."""
        import travel
        self.assertTrue(travel.is_ground_aim("at:1:-705.0,-2045.0,66.0"))
        line = _source()[_source().index("ECONOMY_ERRANDS = ("):]
        self.assertNotIn("at:", line[: line.index("\n")])


class TheLatchIsActuallyBroken(unittest.TestCase):
    """A SEQUENCE test, because the defect was never in any one decision.

    Every individual thing the old pass did was defensible. It aimed the leader
    at a repairer because somebody was damaged, the leader walked there, the
    rows landed, and it aimed again next cycle because somebody was still
    damaged. The bug only exists across cycles: the column had an entry and no
    exit, so no single-pass assertion can see it. The model below is the
    smallest thing that can - one `travel_npc` slot, one queue, one retry
    window - and it runs the old rule and the new rule over the same world.

    It is a MODEL and it is trusted only for the one property it is asked
    about: whether the column can ever return to empty. The facts it encodes are
    the measured ones - the leader does arrive, the queue does drain, and the
    family is damaged essentially all the time (durability was read at 99.1% to
    100% across the five on the day the town trip was written, and ANY_DAMAGE
    means any damage at all counts).
    """

    WINDOW = 12  # GIVE_RETRY_MINUTES=60 against a 300 second cycle.

    @classmethod
    def _town_cycles(cls, count, settle=True, gate=True, queue_drains=True,
                     damage_returns=True, readable=True):
        """Run the town pass `count` times and report `travel_npc` after each.

        The world starts where the realm was found at 20:20: the leader carries
        `repair`, is not yet at the counter, and somebody is damaged.
        `settle=False` is the OLD pass, which wrote the aim unconditionally at
        the top and handed nothing back. `gate=False` keeps the release but
        drops the third input, which is what a smaller fix would have looked
        like.
        """
        column, queue, at_counter, damaged, window = "repair", 0, False, True, 0
        seen = []
        for _ in range(count):
            # THE WORLD, BETWEEN TWO PASSES. A leader carrying an aim reaches
            # its counter; one carrying none eventually wanders off it, which is
            # the entire point of handing the column back. What is queued is
            # answered while it stands there.
            if column == "repair":
                at_counter = True
            elif at_counter:
                at_counter = False
            if at_counter and queue and queue_drains:
                queue = 0
                damaged = damage_returns
            window = max(0, window - 1)

            # THE PASS. Settling first, above every gate below it.
            unasked = damaged and not window
            if settle:
                step = towntrip.errand_step(at_counter, queue if readable
                                            else -1, unasked or not gate)
            else:
                step = towntrip.TOWN_ERRAND_AIM
            if step == towntrip.TOWN_ERRAND_AIM:
                column = "repair"
            elif step == towntrip.TOWN_ERRAND_RELEASE:
                column = ""
            # ...and then the rows, which can only be written at a counter and
            # never twice inside the retry window.
            if at_counter and unasked:
                queue += 1
                window = cls.WINDOW
            seen.append(column)
        return seen

    def test_the_old_rule_never_gives_the_column_back(self):
        """THE DEFECT, REPRODUCED. With no terminal path `travel_npc` is set and
        is never empty again, whatever the family does afterwards, so
        TravelHoldsTheWheel stands the quest drive down for ever."""
        self.assertEqual(set(self._town_cycles(24, settle=False)), {"repair"})

    def test_the_new_rule_gives_it_back_once_the_trip_is_finished(self):
        """Same world, same arrival, same drained queue."""
        seen = self._town_cycles(24)
        self.assertIn("", seen)
        self.assertEqual(seen[1], "")

    def test_the_family_spends_most_of_its_time_free(self):
        """THE HONEST RESULT RATHER THAN A FLATTERING ONE. The family is damaged
        again almost immediately, so the leader does go back to a repairer. What
        changes is that it is a round trip bounded by the retry window rather
        than a parking space: the column is empty on the great majority of
        cycles, which is time the quest drive can pick somebody up in."""
        seen = self._town_cycles(3 * self.WINDOW)
        self.assertGreater(seen.count(""), seen.count("repair") * 3)

    def test_without_the_unasked_gate_the_column_never_comes_back(self):
        """THE THIRD INPUT IS LOAD-BEARING, NOT DECORATION, and this is the test
        that says so. Release the column on a quiet queue alone and the pass
        re-aims the moment the family steps away - so the leader arrives, holds
        because there is always "work", and the column never empties at all.
        A fix that only added the release would have measured as no fix."""
        self.assertEqual(set(self._town_cycles(24, gate=False)), {"repair"})

    def test_a_queue_that_never_drains_keeps_its_errand_for_ever(self):
        """THE HALF A CARELESS FIX BREAKS. A leader whose rows are still
        unanswered keeps the column however many cycles pass, because it has to
        be standing at the counter when its own rows execute."""
        self.assertEqual(set(self._town_cycles(24, queue_drains=False)),
                         {"repair"})

    def test_an_unreadable_queue_never_decays_into_a_release(self):
        """A database that cannot be read must not look like a finished
        errand."""
        self.assertNotIn("", self._town_cycles(24, readable=False))

    def test_a_family_that_stops_taking_damage_is_left_alone(self):
        """The steady state a maintained family should reach, and the one the
        unconditional write could never reach: nothing to repair, so nobody is
        walked anywhere and the column stays empty."""
        seen = self._town_cycles(24, damage_returns=False)
        self.assertEqual(seen[-1], "")
        self.assertNotIn("repair", seen[2:])

    @classmethod
    def _bank_cycles(cls, count, settle=True, queue_answers=True,
                     moves_return=True, readable=True):
        """The same model for the bank pass, whose rows are queued from wherever
        the family is standing rather than only at a counter."""
        column, queue, moves, window = "banker", 0, True, 0
        seen = []
        for _ in range(count):
            if queue and queue_answers:
                queue = 0
                moves = moves_return
            window = max(0, window - 1)
            unasked = moves and not window
            if settle:
                step = bank.errand_step(queue if readable else -1, unasked)
            else:
                step = bank.BANK_ERRAND_AIM
            if step == bank.BANK_ERRAND_AIM:
                column = "banker"
            elif step == bank.BANK_ERRAND_RELEASE:
                column = ""
            if unasked:
                queue += 1
                window = cls.WINDOW
            seen.append(column)
        return seen

    def test_the_old_bank_rule_never_gives_the_column_back(self):
        self.assertEqual(set(self._bank_cycles(24, settle=False)), {"banker"})

    def test_the_new_bank_rule_gives_it_back_between_trips(self):
        seen = self._bank_cycles(24)
        self.assertIn("", seen)
        self.assertGreater(seen.count(""), seen.count("banker"))

    def test_a_bank_queue_that_is_never_answered_keeps_its_errand(self):
        self.assertEqual(set(self._bank_cycles(24, queue_answers=False)),
                         {"banker"})

    def test_an_unreadable_bank_queue_never_decays_into_a_release(self):
        self.assertNotIn("", self._bank_cycles(24, readable=False))

    def test_a_family_with_nothing_left_to_bank_is_left_alone(self):
        seen = self._bank_cycles(24, moves_return=False)
        self.assertEqual(seen[-1], "")


if __name__ == "__main__":
    unittest.main()
