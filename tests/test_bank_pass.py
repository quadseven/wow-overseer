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

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = PACKAGE / "bridge.py"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[3] / "docker/wow-overseer/Dockerfile"


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
        the walk is a queue of refusals."""
        body = _block("    async def _bank_once(")
        self.assertIn("travel_npc=\"banker\"", body)
        self.assertLess(body.index("_write_trade_errand"), body.index("_insert_bank"))

    def test_the_errand_goes_to_the_family_leader(self):
        """Only the leader takes `new rpg`; followers arrive by following.
        Sending a follower straight to an NPC leaves that character behind."""
        body = _block("    async def _bank_once(")
        self.assertIn("leader = await asyncio.to_thread(_head_now)", body)
        self.assertIn("professions.Errand(character=leader", body)

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


class TheModuleShips(unittest.TestCase):

    def test_bank_is_in_the_image(self):
        self.assertIn("_shared/bank.py", DOCKERFILE.read_text(encoding="utf-8"))

    def test_the_bridge_imports_it(self):
        self.assertIn("\nimport bank\n", _source())


if __name__ == "__main__":
    unittest.main()
