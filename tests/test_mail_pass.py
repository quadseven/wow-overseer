"""The mail pass reaches the command queue, and only through the pure planner.

bridge.py imports discord and cannot be imported here, so this reads it as text
the way test_bank_pass does. What is pinned is the seam (infra#3741): the bridge
fetches letters and free slots and writes `mail` rows, every decision about what
is worth collecting is mailrun.py's, and the ground aim that puts a mailbox
within reach is written BEFORE any row that needs one.
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

    The prose is allowed to say `take-item` and `mailbox`; the CODE is what must
    not, because a word in the code is a decision being made twice.
    """
    body = _block(signature)
    marker = '"""'
    if body.count(marker) >= 2:
        return body.split(marker, 2)[2]
    return body


def _sql(name: str) -> str:
    """One `NAME = (...)` SQL literal, to its closing paren at column zero.

    Not `src.index(")", ...)`: `UNIX_TIMESTAMP()` is inside the statement, so a
    slice to the first paren cuts the query in half and every assertion below it
    passes against a fragment. The one test that caught it was the one asserting
    a string that happens to live past the cut.
    """
    src = _source()
    start = src.index("%s = (" % name)
    return src[start:src.index("\n)\n", start)]


class ThePassRunsAndInTheRightOrder(unittest.TestCase):

    def test_the_loop_is_started_with_the_others(self):
        """A loop nobody creates is a feature that ships and never runs, which
        is the exact failure this pass exists to undo one table over."""
        src = _source()
        gateway = src[src.index("self._loops = {"):src.index("async def on_ready(")]
        self.assertIn("self._mail_loop,", gateway)
        headless = src[src.index("loops = ["):src.index("log.info(\"headless:")]
        self.assertIn("self._mail_loop,", headless)

    def test_the_loop_calls_the_pass_and_survives_a_failed_one(self):
        body = _block("    async def _mail_loop(")
        self.assertIn("await self._mail_once()", body)
        self.assertIn("log.exception(", body)
        self.assertIn("while not self.is_closed():", body)

    def test_not_in_the_middle_of_a_dungeon_run(self):
        """A mail run is a town errand. Pulling the leader out of a run to make
        one is how the party spreads."""
        body = _block("    async def _mail_once(")
        self.assertIn("await self._mid_run(names)", body)
        self.assertLess(body.index("self._mid_run("), body.index("_fetch_mail"))

    def test_the_aim_is_written_before_any_row_that_needs_it(self):
        """`DoMail` refuses every one of its five verbs with `mailbox not in
        range` when `FindMailboxInReach` comes back empty. A queue written
        before the walk is a queue of refusals."""
        body = _block("    async def _mail_once(")
        self.assertLess(body.index("_write_trade_errand"), body.index("_insert_mail"))

    def test_nothing_is_queued_when_nobody_can_reach_a_mailbox(self):
        """The guild bank pass manufactured 84 `no guild bank in reach` rows
        this way before infra#3702. A refused aim must return, not queue."""
        body = _block("    async def _mail_once(")
        refusal = body[body.index("if not post.aim:"):body.index("aimed = await")]
        self.assertIn("return", refusal)
        self.assertNotIn("_insert_mail", refusal)

    def test_the_errand_goes_to_the_family_leader(self):
        """Only the leader takes `new rpg`; followers arrive by following.
        Sending a follower straight at a coordinate leaves that character
        behind."""
        body = _block("    async def _mail_once(")
        self.assertIn("leader = await asyncio.to_thread(_head_now)", body)
        self.assertIn("professions.Errand(character=leader, travel_npc=post.aim)", body)

    def test_the_leader_is_head_now_not_the_static_seniority_answer(self):
        """infra#3553/#3554. `_head_now()`, NOT bonds.head_of_family(): the
        static table named a follower for six hours while the character
        actually carrying `new rpg` was somebody else, and mod-overseer refused
        to walk the one that was aimed."""
        body = _block("    async def _mail_once(")
        code_lines = [ln.split("#", 1)[0] for ln in body.splitlines()]
        self.assertNotIn("bonds.head_of_family()", "\n".join(code_lines))

    def test_already_standing_at_a_mailbox_counts_as_aimed(self):
        """mod-overseer RELEASES a travel aim the moment the walk arrives, so
        the cycle after the family gets there finds the column empty. Gating the
        queue on the aim alone would skip exactly the cycle that was going to
        work."""
        body = _block("    async def _mail_once(")
        self.assertIn("TOWN_COUNTER_YARDS ** 2", body)
        self.assertIn("if not aimed and not at_the_mailbox:", body)

    def test_the_retry_window_is_read_before_the_plan_not_after(self):
        """It is an INPUT to the plan, not only a filter on it: the takes
        already queued are spent bag budget."""
        body = _block("    async def _mail_once(")
        self.assertLess(body.index("_recent_mail_keys"), body.index("mailrun.plan("))
        self.assertIn("mailrun.attachments_asked(seen)", body)

    def test_the_same_take_is_not_queued_twice_inside_the_window(self):
        body = _block("    async def _mail_once(")
        self.assertIn("_recent_mail_keys, GIVE_RETRY_MINUTES", body)
        self.assertIn("(take.character, command) in seen", body)


class TheBridgeDecidesNothingAboutTheMail(unittest.TestCase):

    def test_the_plan_comes_from_the_pure_module(self):
        body = _block("    async def _mail_once(")
        self.assertIn("mailrun.letters_from_rows(", body)
        self.assertIn("mailrun.plan(", body)
        self.assertIn("mailrun.command(take)", body)
        self.assertIn("mailrun.lines(fresh)", body)

    def test_no_policy_in_the_bridge(self):
        """Which letter, which verb and which reason are all decided in the
        pure module. The bridge must not name a verb, a wall or a threshold."""
        body = _code("    async def _mail_once(")
        for word in ("take-item", "take-money", "delete", "return mail",
                     "cod", "deliver_time", "disposition."):
            self.assertNotIn(word, body)

    def test_no_slot_or_visit_arithmetic_in_the_bridge(self):
        """Bag room, the visit limit and the spent-budget subtraction all live
        in mailrun.py. A bare number here would be a second copy."""
        body = _code("    async def _mail_once(")
        self.assertNotRegex(body, r"\bmailrun\.VISIT_LIMIT\b")
        self.assertNotRegex(body, r"free_slots\s*[-+]")

    def test_the_log_reports_what_was_written_not_what_was_planned(self):
        """Half a plan can be dropped by the retry window."""
        body = _block("    async def _mail_once(")
        self.assertIn("mailrun.lines(fresh)", body)


class TheRowsCarryWhatThePlannerReads(unittest.TestCase):

    def test_the_sql_names_every_column_letters_from_rows_uses(self):
        sql = _sql("_MAIL_SQL")
        for column in ("AS holder", "AS mail_id", "AS money", "AS cod",
                       "AS expire_time", "AS delivered", "AS item_guid"):
            self.assertIn(column, sql)

    def test_the_attachment_join_is_a_left_join(self):
        """A letter carrying only money has no `mail_items` row at all, and on
        this realm that is the auction settlement holding 4,100 copper. An
        inner join would drop it and nothing would say so."""
        sql = _sql("_MAIL_SQL")
        self.assertIn("LEFT JOIN mail_items", sql)

    def test_the_clock_is_the_databases_and_the_answer_is_what_crosses(self):
        """A Python clock disagreeing with the worldserver's would be a second
        opinion on a question the executor already answers by refusing."""
        sql = _sql("_MAIL_SQL")
        self.assertIn("(m.deliver_time <= UNIX_TIMESTAMP()) AS delivered", sql)

    def test_nothing_is_filtered_out_in_sql(self):
        """A COD letter, an undelivered one and an empty one are all told apart
        by the planner, which says in a note why each was left. A WHERE clause
        would make all three indistinguishable from an empty mailbox."""
        sql = _sql("_MAIL_SQL")
        where = sql.split("WHERE")[1]
        for column in ("m.cod", "m.money", "deliver_time", "has_items"):
            self.assertNotIn(column, where)

    def test_the_fetch_is_only_a_fetch(self):
        body = _block("def _fetch_mail(")
        self.assertIn("_MAIL_SQL", body)
        self.assertIn("return [dict(row) for row in cur.fetchall()]", body)

    def test_a_world_with_no_mail_tables_is_an_empty_mailbox(self):
        body = _block("def _fetch_mail(")
        self.assertIn("1146", body)
        self.assertIn("return []", body)


class TheMailboxIsFoundInTheSpawnTable(unittest.TestCase):

    def test_the_query_is_the_vault_query_with_one_different_type(self):
        """infra#3741 recorded reaching a mailbox as the hard, open part. The
        query that already walks the family to a Guild Vault answers it."""
        sql = _sql("_MAILBOX_SQL")
        self.assertIn("JOIN acore_world.gameobject g ON g.map = s.map_id", sql)
        self.assertIn("gt.type = %s", sql)
        self.assertIn("ORDER BY d2 LIMIT 1", sql)

    def test_the_same_map_rule_is_enforced_in_the_join(self):
        """MoveFarTo paths through PathGenerator and there is no navmesh across
        an ocean, so a cross-map spawn is not a worse candidate, it is not a
        candidate."""
        sql = _sql("_MAILBOX_SQL")
        self.assertIn("g.map = s.map_id", sql)

    def test_the_position_comes_from_the_snapshot_and_is_filtered_for_freshness(self):
        """The `characters` row is written on the player-save timer and can be
        a quarter of an hour stale, which here would aim the family at a
        mailbox near where they USED to be."""
        sql = _sql("_MAILBOX_SQL")
        self.assertIn("FROM overseer_snapshot s", sql)
        self.assertIn("s.updated_at > NOW() - INTERVAL 120 SECOND", sql)

    def test_the_type_is_the_named_constant_not_a_bare_19(self):
        """A fact about the game belongs in the pure module where a test can
        reach it, which is where travel.GUILD_VAULT_GO_TYPE already lives."""
        body = _block("def _nearest_mailbox(")
        self.assertIn("travel.MAILBOX_GO_TYPE", body)
        self.assertNotRegex(_code("def _nearest_mailbox("), r"\b19\b")

    def test_an_unreadable_world_is_no_mailbox_rather_than_a_crash(self):
        body = _block("def _nearest_mailbox(")
        self.assertIn("1054", body)
        self.assertIn("1146", body)
        self.assertIn("return None", body)


class TheMailRowIsTheRowDoMailReads(unittest.TestCase):
    """The mail migration's column meaning, which is NOT give's: the character
    goes in target_name, and target_arg carries the RECIPIENT OF A `send` ONLY.
    A take row with a name in target_arg would still be delivered and would
    still be wrong."""

    def test_columns(self):
        body = _block("def _insert_mail(")
        self.assertIn("(target_name, command, kind, target_arg, source)", body)
        self.assertIn("'mail'", body)
        self.assertIn("(take.character, command, \"economy\")", body)

    def test_target_arg_is_written_empty_rather_than_defaulted(self):
        body = _block("def _insert_mail(")
        self.assertIn("VALUES (%s, %s, 'mail', '', %s)", body)

    def test_a_world_without_the_enum_warns_instead_of_raising(self):
        body = _block("def _insert_mail(")
        self.assertIn("1265", body)
        self.assertIn("1146", body)
        self.assertIn("return 0", body)

    def test_a_missing_table_is_an_empty_window_rather_than_a_dead_pass(self):
        body = _block("def _recent_mail_keys(")
        self.assertIn("1146", body)
        self.assertIn("return set()", body)

    def test_the_window_is_scoped_to_this_kind(self):
        body = _block("def _recent_mail_keys(")
        self.assertIn("WHERE kind = 'mail'", body)


class TheGroundAimIsGuardedLikeTheVaults(unittest.TestCase):

    def test_a_ground_aim_may_only_retask_an_idle_traveller(self):
        """Without this an `at:` aim falls through `_retaskable_from` to the
        unconditional branch and blanks `learn_skill` on its way past - the bug
        mod-overseer#438 closed on the C++ side, re-created one file over."""
        guard = _block("def _retaskable_from(")
        self.assertIn("if travel.is_ground_aim(aim):", guard)
        self.assertIn('return ("", aim)', guard)

    def test_this_pass_never_releases_the_column_itself(self):
        """A ground aim is not a maintenance errand - `IsMaintenanceErrand` is
        `CounterRoleForAim(aim) != CounterRole::None` and that matches four
        whole keywords - so `TravelAimBook::Release` blanks `travel_npc` itself
        on arrival. A second writer for a column the world already clears is how
        a latch gets built."""
        body = _block("    async def _mail_once(")
        self.assertNotIn("_release_trade_errand", body)


class TheModuleShips(unittest.TestCase):

    def test_mailrun_is_in_the_image(self):
        self.assertIn("_shared/mailrun.py", DOCKERFILE.read_text(encoding="utf-8"))

    def test_the_bridge_imports_it(self):
        self.assertIn("\nimport mailrun\n", _source())

    def test_it_is_not_named_after_the_standard_library_module(self):
        """`mailbox` is a Python stdlib module and this package is imported with
        its own directory first on sys.path, so a file with that name here would
        silently shadow it for this process and everything it imports."""
        self.assertFalse((PACKAGE / "mailbox.py").exists())


if __name__ == "__main__":
    unittest.main()
