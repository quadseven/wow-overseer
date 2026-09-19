"""The bank pass reaches the command queue, and only through the pure planner.

bridge.py imports discord and cannot be imported here, so this reads it as
text the way test_bag_handover does. What is pinned is the seam
(mod-overseer#207): the bridge fetches inventory rows and writes `bank` rows,
every decision about what crosses the counter is bank.py's, and the errand
that puts a banker within reach is written BEFORE any row that needs one.
"""
import pathlib
import re
import unittest

import towntrip

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PACKAGE / "bridge.py"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
MOD_OVERSEER = (
    pathlib.Path(__file__).resolve().parents[1]
    / "mod-overseer/src/mod_overseer.cpp"
)


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

    The prose is allowed to say `reagent` and `deposit`; the CODE is what
    must not, because a word in the code is a decision being made twice.
    """
    body = _block(signature)
    marker = '"""'
    if body.count(marker) >= 2:
        return body.split(marker, 2)[2]
    return body


def _sql() -> str:
    src = _source()
    return src[src.index("_BANK_ITEMS_SQL = ("):src.index("def _fetch_bank_items(")]


class ThePassRunsAndInTheRightOrder(unittest.TestCase):

    def test_the_loop_is_started_with_the_others(self):
        """A loop nobody creates is a feature that ships and never runs."""
        src = _source()
        block = src[src.index("self._loops = {"):src.index("async def on_ready(")]
        self.assertIn("self._bank_loop,", block)

    def test_the_loop_calls_the_pass_and_survives_a_failed_one(self):
        body = _block("    async def _bank_loop(")
        self.assertIn("await self._bank_once()", body)
        self.assertIn("log.exception(", body)
        self.assertIn("while not self.is_closed():", body)

    def test_not_in_the_middle_of_a_dungeon_run(self):
        """A bank trip is a town errand. Pulling the leader out of a run to
        make one is how the party spreads."""
        body = _block("    async def _bank_once(")
        self.assertIn("await self._mid_run(names)", body)
        self.assertLess(body.index("self._mid_run("), body.index("_fetch_bank_items"))

    def test_the_travel_errand_is_written_before_any_row_that_needs_it(self):
        """DoBank refuses with `banker not in range`. A queue written before
        the walk is a queue of refusals.

        THE AIM MOVED INTO `_settle_bank_errand` (infra#3728) and the invariant
        did not. Writing the errand and handing it back are one decision - the
        pass wrote `banker` and nothing anywhere ever wrote the column back to
        empty, which is a latch with an entry and no exit - so the two ends live
        together, and what this pins is that the settling still precedes the
        first insert."""
        body = _block("    async def _bank_once(")
        settle = _block("    async def _settle_bank_errand(")
        self.assertIn('self._claim_town_slot("bank", leader, "banker")', settle)
        self.assertLess(body.index("_settle_bank_errand"), body.index("_insert_bank"))

    def test_the_errand_goes_to_the_family_leader(self):
        """Only the leader takes `new rpg`; followers arrive by following.
        Sending a follower straight to an NPC leaves that character behind.

        The leader is still read once, here, and handed to the settling - a
        release from one leader and an aim on another would be two leaders.

        AND THE AIM IS NOW ASKED FOR THROUGH THE TOWN SLOT (infra#3703), which
        reads `_head_now` itself and refuses to write an aim onto anybody who
        is not the leader. The rule this test names is therefore enforced in
        one place rather than restated in seven passes, and the release below
        still names the same leader this pass read."""
        body = _block("    async def _bank_once(")
        self.assertIn("leader = await asyncio.to_thread(_head_now)", body)
        self.assertIn("self._settle_bank_errand(names, leader", body)
        settle = _block("    async def _settle_bank_errand(")
        self.assertIn('self._claim_town_slot("bank", leader, "banker")', settle)
        self.assertIn('_release_trade_errand, leader, "banker"', settle)

    def test_the_leader_is_head_now_not_the_static_seniority_answer(self):
        """infra#3553/#3554. `_head_now()`, NOT bonds.head_of_family() directly.

        The two differ exactly when it matters: `_head_now` is what
        `_mark_party_leader` writes into `overseer_roster.lead` and what
        `_give_them_a_life` reads to decide who carries `new rpg`, so it
        names a character that can actually walk. `bonds.head_of_family()`
        is a pure seniority table that always answers the father, whatever
        the live world is doing.

        Measured on the dev realm: `overseer_roster.lead` was 'Grog' for at
        least six hours (a trade errand had borrowed the lead) while this
        pass kept writing the banker aim to 'Grug', the static answer.
        mod-overseer refused to walk 'Grug' ("does not carry `new rpg`"),
        never released the aim, and burned the errand budget into a 900s
        lockout every cycle - every personal bank on the realm sat empty.

        A per-holder-write regression would still pass a test that merely
        asserted `_head_now` was called somewhere in the block, so this also
        pins that the STATIC answer is gone from the actual code - checked
        with comments stripped, since the prose above is allowed to name the
        function it is warning against.
        """
        body = _block("    async def _bank_once(")
        self.assertIn("_head_now", body)
        code_lines = [ln.split("#", 1)[0] for ln in body.splitlines()]
        self.assertNotIn("bonds.head_of_family()", "\n".join(code_lines))

    def test_an_economy_errand_never_erases_a_trainer_errand(self):
        """The guard moved into `_retaskable_from` (infra#3692) so a SECOND
        kind of economy aim - a bare creature entry, which no role keyword
        can express - could join it without a second copy of the WHERE
        clause. What must not change, and is what this pins: an economy aim
        is still written under a WHERE that matches only an allowed standing
        value, and an errand outside that set still goes down the
        unconditional branch that carries learn_skill/unlearn_skill with
        it."""
        body = _block("def _write_trade_errand(")
        self.assertIn("retaskable = _retaskable_from(errand.travel_npc)", body)
        self.assertIn("WHERE name = %%s AND travel_npc IN (", body)
        guard = _block("def _retaskable_from(")
        self.assertIn("if aim in ECONOMY_ERRANDS:", guard)
        self.assertIn('return ("", aim)', guard)
        # Neither a keyword nor an entry retasks anybody: that is a standing
        # profession errand and belongs on the other branch.
        self.assertIn("return ()", guard)
        self.assertIn("\"banker\"", _source()[:_source().index("def _write_trade_errand(")]
                      .rsplit("ECONOMY_ERRANDS = ", 1)[1])

    def test_a_zero_rowcount_is_not_automatically_a_refusal(self):
        """This connection carries no `CLIENT_FOUND_ROWS`, so MySQL's default
        UPDATE semantics count rows CHANGED, not rows matched - re-asserting
        the same keyword a traveller already carries (the idempotent
        re-write this function's own docstring says happens every cycle)
        changes nothing, so `rowcount` is 0 even though this errand still
        owns the column. Measured live (infra#3663 follow-up): a leader who
        held `travel_npc='vendor'` unchanged for 20+ minutes was reported as
        refused every single cycle, because `bool(cur.rowcount)` treated
        "unchanged" identically to "some other keyword owns this". The fix
        reads the column back and calls it taken when the stored value
        already matches what was being written, not only when a row
        actually changed."""
        body = _block("def _write_trade_errand(")
        self.assertIn("if cur.rowcount:", body)
        self.assertIn("return True", body)
        self.assertIn("SELECT travel_npc FROM overseer_roster", body)
        self.assertIn("current == errand.travel_npc", body)


class TheBridgeDecidesNothingAboutTheBank(unittest.TestCase):

    def test_the_plan_comes_from_the_pure_module(self):
        body = _block("    async def _bank_once(")
        self.assertIn("bank.members_from_rows(rows, names)", body)
        self.assertIn("bank.family_from_skills(held)", body)
        self.assertIn("bank.plan(", body)
        self.assertIn("bank.command(move)", body)

    def test_no_slot_arithmetic_in_the_bridge(self):
        """Slot ranges, free-room counting and the bank's own size live in
        bank.py. A literal 19, 39 or 67 here would be a second copy."""
        body = _code("    async def _bank_once(")
        self.assertNotRegex(body, r"\b(16|19|22|23|28|38|39|66|67|73)\b")
        self.assertNotRegex(body, r"\[\"(bag|slot|count|quality)\"\]")
        self.assertNotIn("ContainerSlots", body)

    def test_no_policy_in_the_bridge(self):
        """Which item, which verb and which reason are all decided in the pure
        module. The bridge must not name a route, a verb or an item class."""
        body = _code("    async def _bank_once(")
        for word in ("deposit", "withdraw", "buy slot", "reagent", "quest",
                     "soulbound", "disposition."):
            self.assertNotIn(word, body)

    def test_the_fetch_is_only_a_fetch(self):
        body = _block("def _fetch_bank_items(")
        self.assertIn("_BANK_ITEMS_SQL", body)
        self.assertIn("return [dict(row) for row in cur.fetchall()]", body)
        self.assertNotRegex(body, r"\b(19|22|23|38|39|66|67|73)\b")

    def test_the_log_reports_what_was_written_not_what_was_planned(self):
        """Half a plan can be dropped by the retry window."""
        body = _block("    async def _bank_once(")
        self.assertIn("bank.lines(fresh)", body)


class TheRowsCarryWhatThePlannerReads(unittest.TestCase):

    def test_the_sql_names_every_column_members_from_rows_uses(self):
        sql = _sql()
        for column in ("AS holder", "AS level", "AS item_guid", "AS count",
                       "AS name", "AS quality", "AS sell_price",
                       "AS required_level", "AS bonding", "AS item_class",
                       "AS container_slots", "AS bag", "AS slot"):
            self.assertIn(column, sql)

    def test_both_sides_of_the_counter_come_back(self):
        """The bank pass needs the bags to decide what goes down, the bank to
        decide what comes back, and both to count the room. A WHERE on the
        geography would put that arithmetic in SQL."""
        sql = _sql()
        self.assertNotIn("ci.bag", sql.split("WHERE")[1])
        self.assertNotIn("ci.slot", sql.split("WHERE")[1])

    def test_it_joins_the_item_template_the_names_come_from(self):
        sql = _sql()
        self.assertIn("acore_world.item_template", sql)
        self.assertIn("ii.guid = ci.item", sql)


class TheBankRowIsTheRowDoBankReads(unittest.TestCase):
    """mod-overseer#207's column meaning, which is NOT give's: the character
    goes in target_name and target_arg is unused. A row with a name in
    target_arg would still be delivered and would still be wrong."""

    def test_columns(self):
        body = _block("def _insert_bank(")
        self.assertIn("(target_name, command, kind, target_arg, source)", body)
        self.assertIn("'bank'", body)
        self.assertIn("(move.character, command, \"economy\")", body)

    def test_target_arg_is_written_empty_rather_than_defaulted(self):
        body = _block("def _insert_bank(")
        self.assertIn("VALUES (%s, %s, 'bank', '', %s)", body)

    def test_a_world_without_the_enum_warns_instead_of_raising(self):
        body = _block("def _insert_bank(")
        self.assertIn("1265", body)
        self.assertIn("1146", body)
        self.assertIn("return 0", body)

    def test_a_missing_table_is_an_empty_window_rather_than_a_dead_pass(self):
        body = _block("def _recent_bank_keys(")
        self.assertIn("1146", body)
        self.assertIn("return set()", body)

    def test_the_same_move_is_not_queued_twice_inside_the_window(self):
        body = _block("    async def _bank_once(")
        self.assertIn("_recent_bank_keys, GIVE_RETRY_MINUTES", body)
        self.assertIn("(move.character, command) in seen", body)


class ABankRowIsAnsweredWhereTheCharacterStandsTests(unittest.TestCase):
    """infra#3815, and the C++ fact two paragraphs of the old docstring
    disagreed about.

    `_bank_once` claimed each command "stays pending until its holder reaches
    the counter". `DoBank` measures the range on the poll that picks the row
    up - `BankerInReach` searches INTERACTION_DISTANCE from where the
    character is standing at that instant - and hands a failure to `refuse`.
    This pins the three properties that make that terminal: the check is there,
    `refuse` writes `refused` and returns its second argument, and that second
    argument is the DETAIL STRING rather than a retry class of the kind
    mod-overseer#230 gave the sell verb.
    """

    def setUp(self):
        if not MOD_OVERSEER.exists():
            self.skipTest("mod-overseer submodule not checked out")
        cpp = MOD_OVERSEER.read_text(encoding="utf-8")
        self.cpp = cpp
        start = cpp.index("static char const* DoBank(")
        self.bank = cpp[start:cpp.index("static char const*", start + 10)]

    def test_the_range_is_measured_at_the_moment_the_row_is_answered(self):
        self.assertIn("BankerInReach(who, anyBankerInRange)", self.bank)
        self.assertIn('"banker not in range"', self.bank)
        self.assertIn("INTERACTION_DISTANCE",
                      self.cpp[self.cpp.index("static Creature* BankerInReach("):]
                      [:1200])

    def test_the_second_argument_is_the_detail_column_and_not_a_retry_class(self):
        """`describe("refused", reason); return detail;`. The detail is the
        text that lands in `overseer_command.detail`, which is why the column
        reads `banker not in range` - it is not a word anything classifies."""
        refuse = self.bank[self.bank.index("auto refuse = [&]"):][:300]
        self.assertIn("auto refuse = [&](char const* reason, char const* detail)",
                      refuse)
        self.assertIn('describe("refused", reason)', refuse)
        self.assertIn("return detail;", refuse)
        self.assertNotIn("pending", refuse)

    def test_only_the_sell_family_of_verbs_classifies_a_refusal(self):
        """`SellRefusalRetry` and its siblings exist and no bank row ever
        reaches one, so nothing can decide a bank refusal is retryable."""
        self.assertIn("SellRefusalRetry", self.cpp)
        self.assertNotIn("BankRefusalRetry", self.cpp)
        self.assertNotIn("retry", self.bank)

    def test_no_verb_puts_a_row_back_on_the_queue_in_place(self):
        """mod-overseer#230's own diff removed the last of those four lines.
        A row that is answered is answered; there is no `pending` to wait in."""
        self.assertIn("NO ROW GOES BACK ON THE QUEUE IN PLACE", self.cpp)


class TheBankerBitIsTheWorldsOwnFlag(unittest.TestCase):
    """`towntrip.Town.banker` (infra#3815) - the same reader, one more bit.

    The value is checked against the live world DB rather than a wiki: every
    `creature_template` row subnamed 'Banker' on wow-dev carries 0x20000, 55
    rows carry it in all, and it is the bit `BankerInReach` hands
    `GetNPCIfCanInteractWith` as UNIT_NPC_FLAG_BANKER.
    """

    def test_the_bit_is_the_cores_own_value(self):
        self.assertEqual(towntrip.NPC_FLAG_BANKER, 0x20000)

    def test_a_banker_in_reach_is_read_from_its_own_npcflag(self):
        town = towntrip.town_from_rows(
            [{"npcflag": towntrip.NPC_FLAG_BANKER, "item": None}])
        self.assertTrue(town.banker)

    def test_a_vendor_or_a_repairer_alone_is_not_a_banker(self):
        """The whole point of the gate: a family standing in a market with no
        bank must not have bank rows written for it."""
        for flag in (towntrip.NPC_FLAG_VENDOR, towntrip.NPC_FLAG_REPAIR):
            with self.subTest(flag=flag):
                self.assertFalse(
                    towntrip.town_from_rows([{"npcflag": flag, "item": 787}]).banker)

    def test_one_spawn_can_carry_several_of_the_bits(self):
        town = towntrip.town_from_rows([{
            "npcflag": towntrip.NPC_FLAG_BANKER | towntrip.NPC_FLAG_VENDOR,
            "item": 787,
        }])
        self.assertTrue(town.banker)
        self.assertTrue(town.vendor)

    def test_a_banker_sells_nothing_by_being_a_banker(self):
        """`stocks` is still gated on the VENDOR bit. A banker with npc_vendor
        rows it cannot sell from would otherwise promise a purchase."""
        town = towntrip.town_from_rows(
            [{"npcflag": towntrip.NPC_FLAG_BANKER, "item": 787}])
        self.assertEqual(town.stocks, frozenset())
        self.assertFalse(town.vendor)

    def test_nothing_in_reach_is_no_banker_in_reach(self):
        """The state the family is in for most of a trip, and the direction
        that withholds rows rather than writing refusals."""
        self.assertFalse(towntrip.town_from_rows([]).banker)
        self.assertFalse(towntrip.Town().banker)


class TheBankQueueWaitsForTheWalkTests(unittest.TestCase):
    """infra#3815. The rows are written on a cycle where somebody is actually
    at a counter, which is the shape `_vendor_once` and `_auction_once`
    already have and infra#3804 gave the guild vault one function along."""

    def test_the_reach_read_asks_the_world_for_the_banker_bit_too(self):
        """One reader for three counters. Drop this bit and the SQL filters
        every banker spawn out before `town_from_rows` ever sees it, so the
        gate below would hold every mover back for ever and the pass would
        write nothing at all."""
        code = _code("def _fetch_town(leader: str)")
        self.assertIn("towntrip.NPC_FLAG_BANKER", code)

    def test_the_gate_sits_above_the_insert_in_the_move_loop(self):
        """THE DEFECT, AS ONE ORDERING. 115 rows were written from wherever
        the family stood and answered `banker not in range` 1.05 seconds
        later, 141 error against 1 delivered all time."""
        body = _block("    async def _bank_once(")
        self.assertIn("at_the_counter[move.character]", body)
        self.assertLess(body.index("if not at_the_counter[move.character]:"),
                        body.index("_insert_bank, move, command"))

    def test_the_gate_reads_the_movers_own_position_and_not_the_leaders(self):
        """`BankerInReach(who, ...)` measures the character whose row it is.
        An arrived leader never meant five arrived movers - the same reason
        `_vendor_once` calls this reader per seller."""
        code = _code("    async def _bank_once(")
        self.assertIn("_fetch_town, move.character", code)
        self.assertNotIn("_fetch_town, leader", code)

    def test_one_reach_read_per_character_and_not_one_per_row(self):
        """Several moves share a holder and the counter does not move between
        them."""
        code = _code("    async def _bank_once(")
        self.assertLess(code.index("if move.character not in at_the_counter:"),
                        code.index("_fetch_town, move.character"))

    def test_a_mover_held_back_is_logged_rather_than_silently_dropped(self):
        """A pass that writes nothing and a broken one look identical
        otherwise (infra#3660)."""
        code = _code("    async def _bank_once(")
        self.assertIn("walking.append(move.character)", code)
        self.assertIn("if walking:", code)
        self.assertIn("TOWN_COUNTER_YARDS", code)

    def test_a_holder_the_world_cannot_see_is_not_work_this_trip_can_do(self):
        """THE LATCH THE GATE COULD HAVE BUILT. A move whose holder never
        arrives is never written, never enters the retry window, and would
        hold `unasked` true for ever - so `bank.errand_step` would keep the
        column on a family that had finished. `_fetch_positions` returns only
        rows fresher than a minute, so a name missing from it is dropped."""
        code = _code("    async def _bank_once(")
        self.assertIn("_fetch_positions, names", code)
        self.assertIn("and move.character in watched", code)
        self.assertLess(code.index("_fetch_positions, names"),
                        code.index("self._settle_bank_errand("))

    def test_the_settling_asks_whether_the_leader_arrived(self):
        """The third input, and the town trip's own. Without it a queue that
        went quiet because every row was refused reads as a finished errand,
        and the aim is handed back before the family gets there."""
        settle = _code("    async def _settle_bank_errand(")
        self.assertIn("_fetch_town, leader", settle)
        self.assertIn("bool(leader_town.banker), outstanding, moves_unasked",
                      settle)

    def test_the_arrival_is_read_through_the_reader_the_sell_pass_uses(self):
        """`_settle_vendor_errand` asks the same reader the same question one
        counter over. A banker is a creature, so this is NOT infra#3804's
        `travel.vault_in_reach`, which judges a gameobject spawn row."""
        settle = _code("    async def _settle_bank_errand(")
        vendor = _code("    async def _settle_vendor_errand(")
        self.assertIn("_fetch_town, leader", vendor)
        self.assertNotIn("vault_in_reach", settle)
        self.assertNotIn("vault_in_reach", _code("    async def _bank_once("))

    def test_the_docstring_no_longer_claims_the_rows_wait(self):
        """QUOTED AND ANSWERED, NOT DELETED, the way infra#3804 handled the
        same sentence one pass over: the correction is unreadable without the
        claim it corrects, and the claim is why nobody looked for years."""
        doc = " ".join(_block("    async def _bank_once(").split('"""')[1].split())
        self.assertIn("stays pending until its holder reaches the counter", doc)
        self.assertIn("Nothing stays pending", doc)
        self.assertIn("SO IT AIMS ON ONE CYCLE AND QUEUES ON A LATER ONE", doc)
        self.assertIn("141 error rows against 1 delivered", doc)


class TheModuleShips(unittest.TestCase):

    def test_bank_is_in_the_image(self):
        self.assertIn("bank.py", DOCKERFILE.read_text(encoding="utf-8"))

    def test_the_bridge_imports_it(self):
        self.assertIn("\nimport bank\n", _source())


if __name__ == "__main__":
    unittest.main()
