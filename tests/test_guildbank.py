"""Who has more gold than they need, and how much of it goes to the guild.

The pure half of the guild-bank deposit pass (mod-overseer#437, infra#2831).
Written the same day the family's mining errand got stolen by a dungeon
crossing (mod-overseer#435/#438) - `guildbank.plan_deposits` never itself
writes `travel_npc`, but the caller in bridge.py routes the resulting errand
through `ECONOMY_ERRANDS`, deliberately, so it inherits the exact same
idle-traveller guard rather than repeating that mistake one file over.
"""

import ast
import pathlib
import re
import unittest

import guildbank
import travel

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
TRAVEL = pathlib.Path(__file__).resolve().parents[1] / "travel.py"
MOD_OVERSEER = (
    pathlib.Path(__file__).resolve().parents[1] / "mod-overseer/src/mod_overseer.cpp"
)


class ReserveDocumentationMatchesPinnedCore(unittest.TestCase):
    """Keep the reserve explanation aligned with the pinned core behavior."""

    def test_distinguishes_immediate_handlers_from_periodic_saves(self):
        source = (
            pathlib.Path(__file__).resolve().parents[1] / "guildbank.py"
        ).read_text(encoding="utf-8")
        self.assertIn("only the guild-bank withdraw and mail-money handlers", source)
        self.assertIn("SaveGoldToDB", source)
        self.assertIn("Player::SaveToDB", source)
        self.assertNotIn("there is no immediate gold save", source)


def member(**kw):
    base = dict(name="Grug", money=0, in_guild=True)
    base.update(kw)
    return base


# What `plan_deposits` actually holds back by default, which is NOT just the
# float any more (infra#3713): until the guild owns a bank tab, the tab's
# purchase price stays in the members' own purses, because that is where the
# core takes it from. The tests below name this rather than re-deriving it, so
# a change to either constant moves every expectation together.
RESERVE_NO_TAB = guildbank.FLOAT_COPPER + guildbank.TAB0_COST_COPPER


class WhoIsCarryingMoreThanTheFloat(unittest.TestCase):
    def test_nothing_below_the_reserve_is_planned(self):
        self.assertEqual(guildbank.plan_deposits([member(money=RESERVE_NO_TAB)]), [])

    def test_exactly_the_reserve_is_not_a_surplus(self):
        deposits = guildbank.plan_deposits([member(money=RESERVE_NO_TAB)])
        self.assertEqual(deposits, [])

    def test_one_copper_over_the_reserve_is_the_whole_surplus(self):
        deposits = guildbank.plan_deposits([member(money=RESERVE_NO_TAB + 1)])
        self.assertEqual(deposits, [guildbank.Deposit(name="Grug", copper=1)])

    def test_a_large_purse_deposits_everything_above_the_reserve(self):
        purse = RESERVE_NO_TAB + 50_000
        deposits = guildbank.plan_deposits([member(money=purse)])
        self.assertEqual(deposits, [guildbank.Deposit(name="Grug", copper=50_000)])


class OnlyAGuildMemberIsPlanned(unittest.TestCase):
    def test_a_character_with_no_guild_is_skipped_outright(self):
        """Not an error - the errand is meaningless for them, so the caller
        should never have to filter first."""
        deposits = guildbank.plan_deposits([member(money=1_000_000, in_guild=False)])
        self.assertEqual(deposits, [])

    def test_a_missing_in_guild_key_reads_as_not_in_a_guild(self):
        self.assertEqual(
            guildbank.plan_deposits([{"name": "Grug", "money": 1_000_000}]), []
        )

    def test_a_guild_member_alongside_a_non_member_only_plans_the_member(self):
        deposits = guildbank.plan_deposits(
            [
                member(name="Grug", money=RESERVE_NO_TAB + 50_000, in_guild=True),
                member(name="Stranger", money=RESERVE_NO_TAB + 50_000, in_guild=False),
            ]
        )
        self.assertEqual([d.name for d in deposits], ["Grug"])


class AStaleOrAbsentReadNeverManufacturesADeposit(unittest.TestCase):
    def test_a_missing_money_key_is_nothing_to_deposit_not_an_error(self):
        self.assertEqual(
            guildbank.plan_deposits([{"name": "Grug", "in_guild": True}]), []
        )

    def test_a_zero_purse_deposits_nothing(self):
        self.assertEqual(guildbank.plan_deposits([member(money=0)]), [])

    def test_a_negative_purse_deposits_nothing_rather_than_raising(self):
        """`characters.money` cannot actually be negative, but a stale or
        corrupt read should never turn into a request the executor could act
        on strangely - suppression is always the safe failure here."""
        self.assertEqual(guildbank.plan_deposits([member(money=-500)]), [])

    def test_a_non_int_money_value_is_treated_as_nothing_to_deposit(self):
        self.assertEqual(guildbank.plan_deposits([member(money="lots")]), [])

    def test_a_member_with_no_name_is_skipped(self):
        self.assertEqual(
            guildbank.plan_deposits([{"money": 1_000_000, "in_guild": True}]), []
        )


class MultipleMembersEachGetTheirOwnDeposit(unittest.TestCase):
    def test_every_member_over_the_reserve_gets_a_deposit(self):
        deposits = guildbank.plan_deposits(
            [
                member(name="Grug", money=RESERVE_NO_TAB + 100),
                member(name="Grog", money=RESERVE_NO_TAB + 200),
            ]
        )
        self.assertEqual(
            {d.name: d.copper for d in deposits}, {"Grug": 100, "Grog": 200}
        )

    def test_members_come_back_in_the_order_they_were_given(self):
        """Ordering, like _fetch_guild_money's own read, is the caller's
        concern - this module does not re-sort."""
        deposits = guildbank.plan_deposits(
            [
                member(name="Ugga", money=RESERVE_NO_TAB + 1),
                member(name="Bork", money=RESERVE_NO_TAB + 1),
            ]
        )
        self.assertEqual([d.name for d in deposits], ["Ugga", "Bork"])

    def test_an_empty_roster_plans_nothing(self):
        self.assertEqual(guildbank.plan_deposits([]), [])


class FormatItemDepositIsAPureFormatterTests(unittest.TestCase):
    """Mechanism only (infra#3647) - this renders the command text
    `GuildVerb::BankDepositItem` parses, it does not decide anything."""

    def test_guid_form(self):
        self.assertEqual(
            guildbank.format_item_deposit(item_guid=494263),
            "bank deposit-item guid:494263",
        )

    def test_entry_form(self):
        self.assertEqual(
            guildbank.format_item_deposit(entry=4562), "bank deposit-item entry:4562"
        )

    def test_neither_is_rejected(self):
        with self.assertRaises(ValueError):
            guildbank.format_item_deposit()

    def test_both_is_rejected(self):
        with self.assertRaises(ValueError):
            guildbank.format_item_deposit(item_guid=1, entry=1)

    def test_a_zero_guid_is_rejected(self):
        with self.assertRaises(ValueError):
            guildbank.format_item_deposit(item_guid=0)

    def test_a_negative_entry_is_rejected(self):
        with self.assertRaises(ValueError):
            guildbank.format_item_deposit(entry=-4562)

    def test_a_non_int_guid_is_rejected(self):
        with self.assertRaises(ValueError):
            guildbank.format_item_deposit(item_guid="494263")


class FetchGuildMoneyReadsTheRealSchemaTests(unittest.TestCase):
    """`_fetch_guild_money` crashed every single cycle in production
    (verified live: `pymysql.err.OperationalError: (1054, "Unknown column
    'guildid' in 'field list'")`, silently, for hours - `characters` has no
    `guildid` column on this world; guild membership lives in `guild_member`
    keyed by `guid`, the same table `test_raid_tab.py`'s own
    `SELECT gm2.guildid FROM guild_member gm2` already proved correct
    elsewhere in this codebase before this function was ever written. This
    pins the fix as a source-text check so a future edit cannot reintroduce
    the same non-existent column - a live pymysql connection is not
    available to this test suite, so this is the assertion that can
    actually run."""

    def setUp(self):
        self.source = BRIDGE.read_text(encoding="utf-8")
        start = self.source.index("def _fetch_guild_money(")
        end = self.source.index("\ndef ", start + 1)
        self.body = self.source[start:end]

    def test_reads_guild_membership_from_guild_member_not_characters(self):
        self.assertIn("guild_member", self.body)
        self.assertNotIn("guildid <> 0", self.body)
        self.assertNotIn("FROM characters WHERE name IN", self.body)

    def test_joins_on_guid_not_name(self):
        # guild_member has no `name` column at all - joining on it would be
        # the same class of guessed-schema mistake this fix corrects.
        self.assertIn("gm.guid = c.guid", self.body)


class RecentGuildBankKeysEscapesItsLikePatternTests(unittest.TestCase):
    """`_recent_guild_bank_keys` crashed every cycle too, right behind
    `_fetch_guild_money` once that one was fixed - `pymysql.cursors.Cursor.
    mogrify` runs `query % self._escape_args(args, conn)`, so a literal `%`
    inside the query string (the `LIKE 'bank deposit %'` clause) collides
    with pymysql's own %-style substitution: `ValueError: unsupported format
    character '''`. The fix binds the LIKE pattern as a parameter instead of
    writing it inline, the same way `minutes` already was - no live pymysql
    connection is available to this suite, so this pins the query shape as a
    source-text check, same convention as FetchGuildMoneyReadsTheRealSchemaTests
    above."""

    def setUp(self):
        source = BRIDGE.read_text(encoding="utf-8")
        start = source.index("def _recent_guild_bank_keys(")
        end = source.index("\ndef ", start + 1)
        self.body = source[start:end]

    def test_like_pattern_is_bound_not_inlined(self):
        doc_start = self.body.index('"""')
        doc_end = self.body.index('"""', doc_start + 3) + 3
        code = self.body[doc_end:]
        self.assertNotIn("LIKE 'bank deposit %'", code)
        self.assertIn("LIKE %s", code)
        self.assertIn('"bank deposit %"', code)

    def test_the_query_string_itself_has_no_bare_percent(self):
        # Every '%' the query STRING contains must be one of pymysql's own
        # placeholders (%s) - a bare one is exactly what crashed live.
        start = self.body.index("cur.execute(")
        end = self.body.index(")", self.body.index('MINUTE"'))
        query_call = self.body[start:end]
        query_literal = "".join(
            line.strip().strip('"')
            for line in query_call.splitlines()
            if line.strip().startswith('"')
        )
        self.assertEqual(query_literal.count("%"), query_literal.count("%s"))


class GuildBankTravelAimUsesTheRealKeywordTests(unittest.TestCase):
    """Even with both prior bugs fixed, every queued deposit came back live
    tonight as `status='error'`, `detail='no guild bank in reach'` - because
    the leader was never actually walked anywhere. `travel_npc='guild bank'`
    does not match anything: mod-overseer's own `TravelAimBook::TravelRoles()`
    defines exactly one guild-vault keyword, `"guild banker"`, matched WHOLE
    (see `ResolveTravelTarget`'s own comment: "an aim is a whole keyword or it
    is not this"). A stale comment beside `DoGuild`'s bank verb even asserted
    `travel_npc='guild bank'` "already resolves" - the unverified assumption
    that shipped this bug. This test reads the real submodule source directly,
    the same cross-repo discipline test_bags.py already holds itself to,
    rather than trusting a comment in bridge.py to still be true."""

    def setUp(self):
        if not MOD_OVERSEER.exists():
            self.skipTest("mod-overseer submodule not checked out")
        self.cpp = MOD_OVERSEER.read_text(encoding="utf-8")

    def test_the_real_keyword_is_guild_banker_not_guild_bank(self):
        self.assertIn('{"guild banker",', self.cpp)
        self.assertNotIn('{"guild bank",', self.cpp)

    def test_no_keyword_is_written_because_neither_one_can_work(self):
        """AND THE KEYWORD ABOVE IS DEAD TOO (infra#3702). This class used to
        assert bridge.py wrote `travel_npc="guild banker"`, which was the
        right correction to the previous bug and still could not deposit a
        copper, because `ResolveTravelTarget`'s role branch searches CREATURE
        spawns and no creature in the world carries the flag that keyword
        names:

            SELECT COUNT(*) FROM acore_world.creature_template
             WHERE npcflag & 0x8000000;   -> 0

        counted against the live wow-dev world database. A guild bank is a
        gameobject, so the pass now aims at the vault's own spawn row. Both
        keywords are asserted absent: writing either one back is a return to a
        mechanism that has never once worked."""
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn('travel_npc="guild bank"', source)
        self.assertNotIn('travel_npc="guild banker"', source)

    def test_the_flag_that_keyword_names_is_still_carried_by_no_creature(self):
        """The C++ table keeps the entry, so travel.ROLES has to keep it too -
        test_travel_npc.py asserts the two are equal. What must NOT come back
        is a reader that believes it resolves; travel.py documents it dead at
        the definition, and this pins that the note stays with it."""
        self.assertIn("UNIT_NPC_FLAG_GUILD_BANKER", travel.ROLES["guild banker"])
        note = TRAVEL.read_text(encoding="utf-8")
        self.assertIn("npcflag & 0x8000000", note)

    def test_the_economy_guard_still_covers_the_ground_aim(self):
        """`guild banker` stays in ECONOMY_ERRANDS (nothing writes it now, but
        the set is also the guard against a future writer taking the
        unconditional branch), and the `at:` aim the pass DOES write has to
        reach that same branch - otherwise it blanks `learn_skill` on its way
        past, which is mod-overseer#438's bug re-created one file over.

        THE GUARD MOVED (infra#3692 landed `_retaskable_from` between this
        being written and merging). It is now a tuple of the values an aim may
        be written over rather than a condition at the call site, so a ground
        aim has to be answered THERE - an empty tuple means "not an economy
        errand" and sends it down the unconditional branch."""
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertIn(
            '"guild banker"',
            source[
                source.index("ECONOMY_ERRANDS = (") : source.index(
                    "\n", source.index("ECONOMY_ERRANDS = (")
                )
            ],
        )
        guard = source[source.index("def _retaskable_from(") :]
        guard = guard[: guard.index("\ndef ")]
        self.assertIn("travel.is_ground_aim(aim)", guard)

    def test_a_ground_aim_may_retask_only_an_idle_traveller(self):
        """Idle, or already holding this exact aim - and NOT a refinement of
        anything. The numeric vendor aim may overwrite a plain `vendor`
        because they are the same errand at two resolutions; a vault is a
        different errand 121 yards away, so overwriting `vendor` with it would
        be the theft this guard exists to prevent.

        READ AS SOURCE TEXT, NOT BY CALLING IT, the same as every other
        bridge assertion in this file: `bridge` imports `discord` and pymysql,
        which the test environment does not install, so importing it here is
        an ERROR on CI and passes only on a machine that happens to have them
        (found exactly that way - green locally, `ModuleNotFoundError: No
        module named 'discord'` on the runner)."""
        source = BRIDGE.read_text(encoding="utf-8")
        guard = source[source.index("def _retaskable_from(") :]
        guard = guard[: guard.index("\ndef ")]
        branch = guard[guard.index("if travel.is_ground_aim(aim):") :]
        branch = branch[: branch.index("if aim.isdigit():")]
        self.assertIn('return ("", aim)', branch)
        # Not a refinement of `vendor`, unlike the numeric aim below it.
        self.assertNotIn("VENDOR_ROLE", branch)


class GuildBankOnceLogsWhetherTheLeaderWasActuallyAimedTests(unittest.TestCase):
    """`_write_trade_errand` returns whether the aim was actually taken -
    every other economy pass (craft_supply, the vendor pass) logs that
    return, and `_guild_bank_once` discarded it, which is the exact
    "written and unread" failure `_write_trade_errand`'s own docstring
    already warns about for a different caller (infra#3464). Measured live:
    the leader sat on a standing vendor/repair errand of its own for 15+
    minutes while the guild bank pass ran every cycle and said nothing."""

    def setUp(self):
        source = BRIDGE.read_text(encoding="utf-8")
        self.source = source
        start = source.index("async def _guild_bank_once(")
        end = source.index("\n    async def ", start + 1)
        self.body = source[start:end]

    def test_the_aim_result_is_captured_not_discarded(self):
        self.assertIn("aimed = await self._claim_town_slot(", self.body)
        self.assertIn(
            'self._claim_town_slot("guild bank", leader, vault.aim,', self.body
        )

    def test_a_refused_aim_is_logged(self):
        """Still logged, but the condition gained a second arm (infra#3702):
        a family already STANDING at the vault is not refused just because
        some other pass claimed the column in the gap after mod-overseer
        released the arrived aim. `if not aimed:` alone would skip exactly
        the cycle that was going to work."""
        self.assertIn("if not aimed and not at_the_vault:", self.body)
        self.assertIn("log.info(", self.body)

    def test_the_refusal_says_what_holds_the_column(self):
        """ "already on another errand" cannot tell a pass starved by a LIVE
        errand from one starved by an errand left behind, and that difference
        is the whole diagnosis. The holder is read and logged.

        SAID BY THE TOWN SLOT NOW, AND SAID BETTER (infra#3703). This pass used
        to read `_current_travel_npc` itself just to name the holder; the slot
        reads it once for every pass, names the holder AND how long it has held
        the column, how much lease is left and who is queued behind it. What
        this pins is that the sentence did not go away with the local read: the
        pass still reports its own cost, and `_claim_town_slot` still reports
        the holder."""
        self.assertIn(
            "guild bank: leader=%s could not be aimed at the vault", self.body
        )
        door = self.source[self.source.index("    async def _claim_town_slot(") :]
        door = door[: door.index("    async def _aim_at_reagent_vendor(")]
        self.assertIn("_current_travel_npc", door)
        self.assertIn("townslot.report(decision)", door)

    def test_nothing_is_queued_when_no_vault_can_be_reached(self):
        """A deposit queued when nobody can stand at a vault has exactly one
        possible answer - `no guild bank in reach` - which is the error this
        pass manufactured every ten minutes for its whole life."""
        head = self.body[: self.body.index("_recent_guild_bank_keys")]
        self.assertIn("if not vault.aim:", head)
        self.assertIn("return", head)


class TheVaultAimComesFromTheSpawnTableTests(unittest.TestCase):
    """infra#3702. The aim is built from a row of `acore_world.gameobject`,
    which is a surveyed spawn point, and never from a coordinate this process
    chose - a guessed z has no navmesh and this project has already lost
    characters to one."""

    def test_the_reader_joins_gameobject_on_the_characters_own_map(self):
        source = BRIDGE.read_text(encoding="utf-8")
        sql = source[
            source.index("_VAULT_SQL = (") : source.index("def _nearest_vault")
        ]
        self.assertIn("acore_world.gameobject", sql)
        self.assertIn("overseer_snapshot", sql)
        # The same-map rule, enforced in the join rather than hoped for.
        self.assertIn("g.map = s.map_id", sql)
        # Live position, not the player-save timer.
        self.assertIn("updated_at >", sql)
        self.assertNotIn("FROM characters", sql)

    def test_the_gameobject_type_is_the_named_constant_not_a_bare_34(self):
        source = BRIDGE.read_text(encoding="utf-8")
        reader = source[source.index("def _nearest_vault") :]
        reader = reader[: reader.index("\ndef ")]
        self.assertIn("travel.GUILD_VAULT_GO_TYPE", reader)
        self.assertEqual(34, travel.GUILD_VAULT_GO_TYPE)


class GroundAimFitsTheColumnOrIsRefusedTests(unittest.TestCase):
    """`overseer_roster.travel_npc` is VARCHAR(32) and MySQL TRUNCATES rather
    than refuses outside strict mode, so an over-long aim is not a failed aim
    - it is a different, plausible-looking coordinate nobody surveyed.
    mod-overseer's own berth writer refuses on the same bound
    (TRAVEL_AIM_COLUMN_CHARS); this is that rule on the Python side."""

    def test_a_real_vault_spawn_fits(self):
        # The Gadgetzan vault, read out of the live spawn table.
        self.assertEqual(
            "at:1:-7203.1,-3821.1,8.6",
            travel.ground_aim(1, -7203.14, -3821.13, 8.56098),
        )

    def test_the_longest_live_vault_spawn_still_fits_at_this_precision(self):
        # At full float precision this one renders as 33 characters, one past
        # the column; at the precision mod-overseer itself writes, it fits.
        aim = travel.ground_aim(530, -3909.75, -11548.9, -149.957)
        self.assertIsNotNone(aim)
        self.assertLessEqual(len(aim), travel.COLUMN_WIDTH)

    def test_an_aim_too_long_for_the_column_is_refused_not_truncated(self):
        self.assertIsNone(travel.ground_aim(1000, -17066.66, -17066.66, -17066.66))

    def test_a_missing_coordinate_is_refused(self):
        self.assertIsNone(travel.ground_aim(1, -7203.14, None, 8.5))

    def test_a_non_numeric_coordinate_is_refused_rather_than_raising(self):
        self.assertIsNone(travel.ground_aim(1, "over there", -3821.13, 8.5))

    def test_is_ground_aim_tells_an_aim_from_a_keyword(self):
        self.assertTrue(travel.is_ground_aim("at:1:-7203.1,-3821.1,8.6"))
        self.assertFalse(travel.is_ground_aim("guild banker"))
        self.assertFalse(travel.is_ground_aim(""))
        self.assertFalse(travel.is_ground_aim(None))


class AVaultOnAnotherMapIsRefusedWithASentenceTests(unittest.TestCase):
    """MoveFarTo paths through PathGenerator and there is no navmesh across an
    ocean, so a cross-map vault is not a longer walk - it is not a walk."""

    def spawn(self, **kw):
        base = dict(map_id=1, x=-7203.14, y=-3821.13, z=8.56098)
        base.update(kw)
        return base

    def test_a_same_map_vault_is_aimed_at(self):
        got = travel.vault_aim(self.spawn(), 1)
        self.assertEqual("at:1:-7203.1,-3821.1,8.6", got.aim)
        self.assertEqual("", got.refused)

    def test_a_cross_map_vault_is_refused(self):
        got = travel.vault_aim(self.spawn(map_id=530), 1)
        self.assertEqual("", got.aim)
        self.assertIn("530", got.refused)
        self.assertIn("navmesh", got.refused)

    def test_no_spawn_at_all_says_so(self):
        got = travel.vault_aim(None, 1)
        self.assertEqual("", got.aim)
        self.assertIn("map 1", got.refused)

    def test_an_unknown_position_is_its_own_refusal(self):
        got = travel.vault_aim(self.spawn(), None)
        self.assertEqual("", got.aim)
        self.assertIn("overseer_snapshot", got.refused)

    def test_every_refusal_is_a_whole_sentence_and_not_a_code(self):
        for got in (
            travel.vault_aim(None, 1),
            travel.vault_aim(self.spawn(map_id=530), 1),
            travel.vault_aim(self.spawn(), None),
        ):
            self.assertGreater(len(got.refused.split()), 8, got.refused)


class TheFirstTabPriceIsTheRealisedConfigValueTests(unittest.TestCase):
    """The price is a CONFIG value, not a core constant, so the only honest
    source is the config the realm actually runs (infra#3713).
    `_GetGuildBankTabPrice` (Guild.cpp:94 at the pinned AC_CORE_SHA) returns
    `sWorld->getIntConfig(CONFIG_GUILD_BANK_TAB_COST_0)`. Read live on
    2026-09-13 from the deployed worldserver.conf inside the running wow-dev
    worldserver pod: `Guild.BankTabCost0 = 1000000`. Pinned here so a change
    to the module's copy has to be a deliberate edit against a re-read, which
    is the discipline #3713 asked for after a remembered figure was removed
    from the issue for being unverifiable."""

    def test_the_first_tab_costs_one_hundred_gold(self):
        self.assertEqual(guildbank.TAB0_COST_COPPER, 1_000_000)

    def test_the_price_is_expressed_in_copper_not_gold(self):
        """A tab priced at 100 rather than 1_000_000 would reserve a hundredth
        of what it should, and is exactly the "wrong low" failure the
        constant's own comment warns about."""
        self.assertEqual(guildbank.TAB0_COST_COPPER // 10_000, 100)


class TheFloatDoesNotDriftFromTheRestOfThePackageTests(unittest.TestCase):
    """`guildbank.FLOAT_COPPER` deliberately does not import `needs` (that
    would drag `wealth` -> `bonds`/`family`/`armory`/`panel` into a module the
    pass wants cheap), so the equality is pinned here instead. If either side
    is retuned without the other, this fails rather than the two silently
    parting company."""

    def test_the_float_is_the_same_floor_needs_py_already_measured(self):
        import needs

        self.assertEqual(guildbank.FLOAT_COPPER, needs.THIN_COPPER)

    def test_the_float_is_above_the_broke_line_digest_py_reports(self):
        """It used to BE that line. `digest.py:116` calls one gold the point
        "under this and a character cannot pay a trainer", and the float was
        one gold, so the pass deposited every character onto exactly the
        threshold another module exists to report as a problem (infra#3713)."""
        import digest

        self.assertGreater(guildbank.FLOAT_COPPER, digest.BROKE_COPPER)


class TheReserveKeepsTheFirstTabAffordableTests(unittest.TestCase):
    """The infra#3713 regression, and the reason the reserve changed at all.

    A tab is bought with `player->ModifyMoney(-int32(tabCost))`
    (`Guild::HandleBuyBankTab`, Guild.cpp:1442) - the BUYER'S purse, never
    `guild.BankMoney`. So a deposit rule that empties the purses does not fund
    the tab, it makes the tab unbuyable, and the gold is then somewhere the
    purchase cannot reach it.

    The purses below are the real ones, read from the live `characters` table
    on 2026-09-13 for the family's guild."""

    LIVE_PURSES = {
        "Grug": 1_663_413,  # Guild Master
        "Ugga": 1_718_394,
        "Grog": 1_782_663,
        "Bork": 1_557_501,
        "Og": 1_690_879,
    }

    def _live_members(self):
        return [
            member(name=name, money=money, in_guild=True)
            for name, money in self.LIVE_PURSES.items()
        ]

    def test_every_member_still_clears_the_tab_price_afterwards(self):
        deposits = {
            d.name: d.copper for d in guildbank.plan_deposits(self._live_members())
        }
        for name, purse in self.LIVE_PURSES.items():
            left = purse - deposits.get(name, 0)
            self.assertGreaterEqual(
                left,
                guildbank.TAB0_COST_COPPER,
                f"{name} is left with {left} copper, under the "
                f"{guildbank.TAB0_COST_COPPER} the first tab costs",
            )

    def test_the_old_float_only_rule_would_have_stranded_every_purse(self):
        """Not a hypothetical: this is what the rule did before #3713, and it
        is why the issue's own "deposit gold first, then buy a tab" ordering
        is backwards. With only the float held back, every character is left
        on the float alone and the tab can never be bought by anyone."""
        self.assertLess(guildbank.FLOAT_COPPER, guildbank.TAB0_COST_COPPER)
        for name, purse in self.LIVE_PURSES.items():
            self.assertGreater(
                purse,
                guildbank.TAB0_COST_COPPER,
                f"{name} could not have bought a tab anyway",
            )

    def test_a_purse_that_cannot_clear_the_reserve_deposits_nothing(self):
        """A character poorer than the reserve keeps all of it rather than
        being taken down to the float - suppression, not a partial raid."""
        deposits = guildbank.plan_deposits([member(money=guildbank.TAB0_COST_COPPER)])
        self.assertEqual(deposits, [])


class AGuildThatAlreadyOwnsATabStopsReservingThePriceTests(unittest.TestCase):
    """Once the tab exists there is nothing left to save up for, so the
    reserve drops back to the plain working float."""

    def test_guild_has_tab_releases_the_tab_price(self):
        purse = guildbank.FLOAT_COPPER + guildbank.TAB0_COST_COPPER + 7
        deposits = guildbank.plan_deposits([member(money=purse)], guild_has_tab=True)
        self.assertEqual(
            deposits,
            [guildbank.Deposit(name="Grug", copper=guildbank.TAB0_COST_COPPER + 7)],
        )

    def test_the_default_is_the_cautious_answer(self):
        """Defaulting to False matters because the caller has not been taught
        to read `guild_bank_tab` yet: an un-wired caller must get the reserve
        that keeps the tab affordable, so wiring it later can only release
        gold, never strand it."""
        purse = guildbank.FLOAT_COPPER + guildbank.TAB0_COST_COPPER + 7
        self.assertEqual(
            guildbank.plan_deposits([member(money=purse)]),
            guildbank.plan_deposits([member(money=purse)], guild_has_tab=False),
        )
        self.assertNotEqual(
            guildbank.plan_deposits([member(money=purse)]),
            guildbank.plan_deposits([member(money=purse)], guild_has_tab=True),
        )


class TabDepositBlockersNamesBothSilentRefusalsTests(unittest.TestCase):
    """Both ways an item deposit fails are silent no-ops in the core, and an
    operator cannot tell them apart from a walk that never arrived
    (infra#3713)."""

    def test_the_realm_as_it_stands_reports_the_missing_tab(self):
        blockers = guildbank.tab_deposit_blockers(
            purchased_tabs=0, ranks_with_deposit=0
        )
        self.assertEqual(len(blockers), 2)
        self.assertIn("no purchased bank tab", blockers[0])
        self.assertIn("100 gold", blockers[0])
        self.assertIn("own purse", blockers[0])

    def test_a_freshly_bought_tab_is_still_blocked_for_four_of_five(self):
        """`_CreateNewBankTab` -> `CreateMissingTabsIfNeeded` sets
        `GUILD_BANK_RIGHT_FULL` only `if (m_rankId == GR_GUILDMASTER)`; every
        other rank defaults to `rights(0), slots(0)` (Guild.h:267). The
        family's guild is one Guild Master and four Officers, so buying the
        tab alone leaves exactly one character able to deposit."""
        blockers = guildbank.tab_deposit_blockers(
            purchased_tabs=1, ranks_with_deposit=1
        )
        self.assertEqual(len(blockers), 1)
        self.assertIn("Guild Master", blockers[0])

    def test_a_tab_open_to_more_than_one_rank_reports_nothing(self):
        self.assertEqual(
            guildbank.tab_deposit_blockers(purchased_tabs=1, ranks_with_deposit=2), []
        )

    def test_a_tab_with_no_rank_rights_at_all_is_reported(self):
        blockers = guildbank.tab_deposit_blockers(
            purchased_tabs=1, ranks_with_deposit=0
        )
        self.assertEqual(len(blockers), 1)
        self.assertIn("GUILD_BANK_RIGHT_DEPOSIT_ITEM", blockers[0])


class TabPurchaseVerbIsAvailableInThePinnedModuleTests(unittest.TestCase):
    """The pinned module exposes the tab-purchase capability.

    The Python adapter must not claim that a guild-bank tab can be bought until
    the module parser and executor call the pinned core API.
    """

    def setUp(self):
        if not MOD_OVERSEER.exists():
            self.skipTest("mod-overseer submodule not checked out")
        self.cpp = MOD_OVERSEER.read_text(encoding="utf-8")

    def test_the_module_can_buy_a_tab(self):
        self.assertIn("HandleBuyBankTab", self.cpp)
        self.assertIn("BankBuyTab", self.cpp)

    def test_the_module_can_open_rank_deposit_rights(self):
        self.assertIn("HandleSetRankInfo", self.cpp)


# The Gadgetzan Guild Vault, read out of the live `acore_world.gameobject`
# spawn table rather than chosen here - the same row `_nearest_vault` returns
# and the one the failing aim in infra#3804 was built from. The family's own
# positions below are the live `overseer_snapshot` readings taken while that
# issue was open, so the distances these tests judge are the distances the
# realm actually had. Nothing walks to any of them: this is a measurement
# fixture, not an aim.
GADGETZAN_VAULT = {"map_id": 1, "x": -7203.14, "y": -3821.13, "z": 8.56098}


def standing(name="Grug", map_id=1, pos_x=-7234.6, pos_y=-3804.1):
    """An `overseer_snapshot` row in the shape `_fetch_positions` returns.

    The default is Grug as measured on wow-dev on 2026-09-14 - about 36 yards
    from the vault above, which is exactly the state in which the pass queued
    five deposits and had them all refused."""
    return {"name": name, "map_id": map_id, "pos_x": pos_x, "pos_y": pos_y}


class ADepositIsAnsweredWhereTheCharacterStandsTests(unittest.TestCase):
    """infra#3804, and the C++ fact the old docstring got backwards.

    `_guild_bank_once` claimed each row stayed "pending until its holder
    reaches the vault". DoGuild's `GuildVerb::Bank` branch checks
    `GuildBankInReach(who, ...)` on the poll that picks the row up and hands a
    failure to `refuse()`. This pins the two properties that make that
    terminal: the check exists on the money branch, and DoGuild's `refuse` is
    a one-argument lambda that writes `refused` and returns - no retry class
    like the one mod-overseer#230 gave `vendor not in range`, and nothing that
    puts the row back to `pending`."""

    def setUp(self):
        if not MOD_OVERSEER.exists():
            self.skipTest("mod-overseer submodule not checked out")
        cpp = MOD_OVERSEER.read_text(encoding="utf-8")
        start = cpp.index(
            "if (request.verb == GuildVerb::Bank || request.verb == GuildVerb::BankWithdraw)"
        )
        self.money = cpp[start : cpp.index("GuildVerb::BankDepositItem", start)]
        guild = cpp[cpp.index("static char const* DoGuild(") :]
        self.refuse = guild[guild.index("auto refuse = [&]") :][:400]

    def test_the_money_deposit_measures_range_at_the_moment_it_is_answered(self):
        self.assertIn("GuildBankInReach(who, anyVaultInRange)", self.money)
        self.assertIn("return refuse(anyVaultInRange", self.money)
        self.assertIn('"no guild bank in reach"', self.money)

    def test_the_executor_says_it_acts_where_the_character_already_stands(self):
        self.assertIn("where the character already stands", self.money)

    def test_a_refusal_is_terminal_and_carries_no_retry_class(self):
        """One argument, `describe("refused", ...)`, return. A second argument
        is what a retryable class looks like in this file (DoBank passes one);
        a deposit has none, so a row queued early is not late, it is dead."""
        self.assertIn("auto refuse = [&](char const* reason)", self.refuse)
        self.assertIn('describe("refused", reason)', self.refuse)
        self.assertNotIn("pending", self.refuse)


class TheVaultReachGateAnswersForTheRealFamilyTests(unittest.TestCase):
    """`travel.spawn_in_reach` judged against the vault and the standoff the
    realm actually had, which is what makes these a guild-bank regression
    rather than arithmetic.

    THE FUNCTION IS SHARED AND ITS NAME IS THE DECISION (infra#3830). This
    judgement was written here for a guild vault, and the mail pass is its
    second caller; `travel.py` carries ONE of it, named for neither counter,
    because the body has no refusal sentence for a noun to live in - the test
    that keeps `vault_aim` and `mailbox_aim` apart answers the other way for
    a bare bool. `tests/test_mailrun.py` owns the general contract (the map
    test, the squared threshold, both axes, fail-closed on a row nobody can
    read) and pins that there is only one body, under no counter's name.
    Re-asserting all of that here would be the copy that decision refuses.
    What is guild-bank-specific is below: the real spawn row, the real
    positions, and the threshold this pass chose."""

    def test_the_family_where_the_realm_measured_them_is_not_in_reach(self):
        """About 36 yards out. This is the exact state that produced five
        `no guild bank in reach` rows one second after the aim was taken, so
        a gate that passes here is a gate that would have written them."""
        self.assertFalse(travel.spawn_in_reach(GADGETZAN_VAULT, standing(), 8))

    def test_a_depositor_at_the_vault_is_in_reach(self):
        at_it = standing(pos_x=GADGETZAN_VAULT["x"] + 3.0, pos_y=GADGETZAN_VAULT["y"])
        self.assertTrue(travel.spawn_in_reach(GADGETZAN_VAULT, at_it, 8))

    def test_every_one_of_the_five_is_judged_on_its_own_standing(self):
        """The whole of infra#3804 in one assertion: an arrived leader and a
        follower still walking get different answers from the same spawn row,
        which is why the pass asks per depositor rather than once."""
        arrived = standing(
            name="Grug", pos_x=GADGETZAN_VAULT["x"] + 2.0, pos_y=GADGETZAN_VAULT["y"]
        )
        behind = standing(name="Ugga")
        self.assertTrue(travel.spawn_in_reach(GADGETZAN_VAULT, arrived, 8))
        self.assertFalse(travel.spawn_in_reach(GADGETZAN_VAULT, behind, 8))

    def test_the_pass_gates_at_town_counter_yards_and_not_the_cores_five(self):
        """8, not INTERACTION_DISTANCE's 5, and the looseness is deliberate:
        a walk only lands within `travel.ARRIVED_POSITION_YARDS` of its aim,
        so a five-yard gate would refuse a character that had arrived
        correctly and the deposit would never be attempted at all. Pinned
        against the constant the pass actually passes in."""
        source = BRIDGE.read_text(encoding="utf-8")
        start = source.index("async def _guild_bank_once(")
        body = source[start : source.index("\n    async def ", start + 1)]
        self.assertIn("TOWN_COUNTER_YARDS", body)
        self.assertEqual(
            8, int(re.search(r"^TOWN_COUNTER_YARDS = (\d+)", source, re.M).group(1))
        )
        self.assertGreater(8, travel.ARRIVED_POSITION_YARDS)
        landed = standing(pos_x=GADGETZAN_VAULT["x"] + 7.0, pos_y=GADGETZAN_VAULT["y"])
        self.assertTrue(travel.spawn_in_reach(GADGETZAN_VAULT, landed, 8))
        self.assertFalse(travel.spawn_in_reach(GADGETZAN_VAULT, landed, 5))


class TheDepositQueueWaitsForTheWalkTests(unittest.TestCase):
    """infra#3804. The pass wrote the aim and all five rows in one breath, and
    the worldserver answered every row about a second later from where the
    family was still standing - 73 `no guild bank in reach` in 24 hours and
    zero deliveries all-time, measured on wow-dev.

    READ AS SOURCE TEXT, for the reason the other bridge assertions in this
    file give: `bridge` imports discord and pymysql, which CI does not
    install, so importing it here is an ERROR on the runner and a pass only on
    a machine that happens to have them."""

    def setUp(self):
        source = BRIDGE.read_text(encoding="utf-8")
        start = source.index("async def _guild_bank_once(")
        end = source.index("\n    async def ", start + 1)
        self.body = source[start:end]
        self.doc = self.body[: self.body.index('"""', self.body.index('"""') + 3)]
        self.loop = self.body[self.body.index("for deposit in deposits:") :]

    def test_every_depositor_is_asked_for_not_just_the_leader(self):
        """The pass only ever read the leader's position, to name the map. A
        per-holder gate needs a row per holder, and `_fetch_positions` batches,
        so this stays one query."""
        self.assertIn("d.name for d in deposits", self.body)
        self.assertIn("_fetch_positions, sorted({leader}", self.body)
        self.assertNotIn("_fetch_positions, [leader]", self.body)

    def test_the_gate_sits_above_the_insert_in_the_deposit_loop(self):
        """Inside the loop and before the write, so a character who has not
        arrived is skipped rather than queued. Above `_insert_guild` is the
        whole assertion: below it, the row is already in the table."""
        self.assertIn("travel.spawn_in_reach(", self.loop)
        self.assertLess(
            self.loop.index("travel.spawn_in_reach("), self.loop.index("_insert_guild")
        )

    def test_the_gate_reads_the_depositors_own_position(self):
        """`positions.get(deposit.name)`, never the leader's row and never the
        spawn's `d2` - `d2` is measured from the leader, and a leader who has
        arrived says nothing about a follower who has not."""
        gate = self.loop[self.loop.index("travel.spawn_in_reach(") :]
        gate = gate[: gate.index("_insert_guild")]
        self.assertIn("positions.get(deposit.name)", gate)
        self.assertIn("TOWN_COUNTER_YARDS", gate)
        self.assertNotIn("at_the_vault", gate)
        self.assertNotIn('spawn.get("d2")', gate)

    def test_a_holder_held_back_is_logged_rather_than_silently_dropped(self):
        """A pass that writes nothing and a pass that is broken look identical
        otherwise - the complaint infra#3660 made about the discarded aim
        result, restated for the rows."""
        self.assertIn("walking.append(deposit.name)", self.loop)
        self.assertIn("if walking:", self.loop)
        self.assertIn("not within %d yards of the vault", self.loop)

    def test_the_docstring_no_longer_claims_the_rows_wait(self):
        """The one sentence that was factually wrong, and the reason nobody
        looked for four hundred dead rows. `refuse()` is terminal; a deposit
        row does not stay pending for anybody."""
        self.assertIn("WAS FACTUALLY WRONG", self.doc)
        self.assertIn("Nothing waits.", self.doc)
        self.assertIn("It is terminal.", self.doc)
        # The old sentence survives only as a QUOTATION of what this docstring
        # used to say - it is kept because the correction is unreadable
        # without it. Anywhere it is still ASSERTED, it is still wrong, so
        # there is exactly one of it and it sits under the correction.
        self.assertEqual(self.doc.count("staying pending"), 1)
        self.assertGreater(
            self.doc.index("staying pending"), self.doc.index("WAS FACTUALLY WRONG")
        )
        self.assertNotIn("deposit row is queued", self.doc)

    def test_the_leader_distance_is_only_a_short_circuit_now(self):
        """`at_the_vault` still decides whether the pass continues - a family
        already standing at the vault must not be skipped just because another
        economy pass took the released column - but it no longer decides which
        rows are written."""
        head = self.body[: self.body.index("for deposit in deposits:")]
        self.assertIn("if not aimed and not at_the_vault:", head)
        self.assertIn("IT IS THE LEADER'S DISTANCE", head)


class BankSetupPlannerTests(unittest.TestCase):
    def test_missing_tab_is_bought_by_the_leader(self):
        self.assertEqual(
            (guildbank.SetupAction("Grug", "bank buy-tab tab:0"),),
            guildbank.plan_setup(
                leader="Grug", purchased_tabs=0, rank_ids=(0, 1, 2), deposit_rank_ids=()
            ),
        )

    def test_existing_tab_opens_only_missing_non_master_ranks(self):
        self.assertEqual(
            (
                guildbank.SetupAction("Grug", "bank buy-tab tab:1"),
                guildbank.SetupAction("Grug", "bank grant-deposit rank:2"),
                guildbank.SetupAction("Grug", "bank grant-deposit rank:4"),
            ),
            guildbank.plan_setup(
                leader="Grug",
                purchased_tabs=1,
                rank_ids=(0, 1, 2, 4),
                deposit_rank_ids=(1,),
            ),
        )

    def test_invalid_leader_fails_closed(self):
        self.assertEqual((), guildbank.plan_setup(leader="", purchased_tabs=0))


class TheGuildBuysItsTabsInOrderAndNamesThem(unittest.TestCase):
    """#319: three tabs, bought in order by the master and named."""

    def test_the_tabs_fit_the_column_and_the_verb(self):
        self.assertEqual([0, 1, 2], [t.tab_id for t in guildbank.TABS])
        for tab in guildbank.TABS:
            self.assertLessEqual(len(tab.name), 16, tab.name)
            self.assertRegex(tab.icon, r"^[A-Za-z0-9_]+$")
        self.assertEqual("Materials", guildbank.TABS[0].name)

    def test_the_prices_are_the_realms(self):
        self.assertEqual(
            (1_000_000, 2_500_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000),
            guildbank.TAB_COSTS_COPPER,
        )
        self.assertEqual(guildbank.TAB0_COST_COPPER, guildbank.tab_cost(0))
        self.assertEqual(0, guildbank.tab_cost(6))
        self.assertEqual(0, guildbank.tab_cost("x"))

    def test_the_next_tab_is_bought_and_named(self):
        got = guildbank.plan_setup(
            leader="Grug",
            purchased_tabs=1,
            rank_ids=(0, 1),
            deposit_rank_ids=(1,),
            purse=2_600_000,
            tab_names={0: ""},
        )
        self.assertEqual(
            [
                "bank buy-tab tab:1",
                "bank name-tab tab:0 icon:INV_Fabric_Linen_01 Materials",
            ],
            [a.command for a in got],
        )

    def test_a_later_tab_leaves_the_master_its_float(self):
        self.assertFalse(guildbank.can_buy_tab(2_500_000, 1))
        self.assertFalse(guildbank.can_buy_tab(2_599_999, 1))
        self.assertTrue(guildbank.can_buy_tab(2_600_000, 1))
        # Tab 0 is the price alone, the rule #246 set.
        self.assertTrue(guildbank.can_buy_tab(1_000_000, 0))

    def test_three_tabs_is_every_tab_the_guild_keeps(self):
        got = guildbank.plan_setup(
            leader="Grug",
            purchased_tabs=3,
            rank_ids=(0, 1),
            deposit_rank_ids=(1,),
            purse=900_000_000,
            tab_names={t.tab_id: t.name for t in guildbank.TABS},
        )
        self.assertEqual((), got)
        self.assertIsNone(guildbank.next_tab(3))
        self.assertEqual(0, guildbank.buyer_reserve(3))
        self.assertEqual(5_000_000, guildbank.buyer_reserve(2))

    def test_a_named_tab_is_not_renamed_and_an_unread_name_is_left(self):
        named = guildbank.plan_setup(
            leader="Grug",
            purchased_tabs=2,
            rank_ids=(0,),
            deposit_rank_ids=(),
            purse=0,
            tab_names={0: "Materials", 1: "Gear for Later"},
        )
        self.assertEqual((), named)
        unread = guildbank.plan_setup(
            leader="Grug",
            purchased_tabs=2,
            rank_ids=(0,),
            deposit_rank_ids=(),
            purse=0,
        )
        self.assertEqual((), unread)


class DuesInTheMailboxFundTheNextTab(unittest.TestCase):
    """#319: measured 2026-09-24, the Horde master held 501 copper while about
    2,400 gold of dues waited in its mailbox."""

    def test_the_horde_master_s_dues_would_buy_tab_0(self):
        self.assertTrue(guildbank.dues_fund_tab(0, 501, 24_000_000))

    def test_a_purse_that_already_pays_needs_no_mail_run(self):
        self.assertFalse(guildbank.dues_fund_tab(0, 1_000_000, 24_000_000))

    def test_dues_short_of_the_price_do_not_make_it_urgent(self):
        self.assertFalse(guildbank.dues_fund_tab(0, 501, 500_000))

    def test_a_guild_with_every_tab_has_nothing_to_fund(self):
        self.assertFalse(guildbank.dues_fund_tab(3, 0, 900_000_000))

    def test_an_unreadable_read_is_not_urgent(self):
        self.assertFalse(guildbank.dues_fund_tab(0, "x", 24_000_000))

    def test_the_wait_line_names_the_dues(self):
        line = guildbank.tab_waits_line("Zug", 501, 0, 24_000_000)
        self.assertIn("tab 0 waits - Zug holds 0g of the 100g", line)
        self.assertIn("2400g of dues wait unopened in Zug's mailbox", line)
        self.assertNotIn("mailbox", guildbank.tab_waits_line("Zug", 501))


class TheBuyerKeepsTheNextTabsPrice(unittest.TestCase):
    def test_only_the_buyer_holds_the_price_back(self):
        members = [
            {"name": "Grug", "money": 5_000_000, "in_guild": True},
            {"name": "Bork", "money": 5_000_000, "in_guild": True},
        ]
        got = guildbank.plan_deposits(
            members, guild_has_tab=True, buyer="Grug", reserve_for_buyer=2_500_000
        )
        self.assertEqual(
            [
                guildbank.Deposit("Grug", 5_000_000 - 100_000 - 2_500_000),
                guildbank.Deposit("Bork", 5_000_000 - 100_000),
            ],
            got,
        )

    def test_without_a_tab_the_old_reserve_stands(self):
        members = [{"name": "Zug", "money": 2_000_000, "in_guild": True}]
        got = guildbank.plan_deposits(
            members, guild_has_tab=False, buyer="Zug", reserve_for_buyer=1_000_000
        )
        self.assertEqual([guildbank.Deposit("Zug", 900_000)], got)


class BankSetupBridgeTests(unittest.TestCase):
    def setUp(self):
        self.source = BRIDGE.read_text(encoding="utf-8")

    def test_setup_reads_every_tab_and_the_masters_dues(self):
        body = self.source[self.source.index("def _fetch_guild_bank_setup(") :]
        body = body[: body.index("\ndef _setup_buyer")]
        self.assertIn("HAVING COUNT(*) = %s", body)
        self.assertIn('"tab_names": tab_names', body)
        self.assertIn('"tab_items": tab_items', body)
        self.assertIn("SUM(m.money)", body)
        self.assertIn('"master_mailed_copper": mailed', body)

    def test_setup_reads_all_tables_and_handles_old_realms(self):
        body = self.source[self.source.index("def _fetch_guild_bank_setup(") :]
        body = body[: body.index("\ndef _recent_guild_setup_keys")]
        self.assertIn("information_schema.tables", body)
        self.assertIn("guild_bank_tab", body)
        self.assertIn("guild_bank_right", body)
        self.assertIn("guild_rank", body)
        self.assertIn("1146", body)

    def test_setup_pass_uses_new_module_verbs(self):
        body = self.source[self.source.index("async def _guild_bank_once(") :]
        self.assertIn("plan_setup", body)
        self.assertIn("_recent_guild_setup_keys", body)
        self.assertIn("guildbank-setup", body)
        self.assertIn("bank buy-tab", self.source)
        self.assertIn("bank grant-deposit", self.source)


class ParameterisedQueriesSurviveMogrify(unittest.TestCase):
    """Every `cur.execute(sql, args)` in bridge.py must render with its args.

    pymysql builds a parameterised query as `sql % escaped_args`, so a literal
    percent in the SQL - the wildcard in a LIKE pattern, almost always - has to
    be doubled. Get it wrong and `mogrify` raises `TypeError: not enough
    arguments for format string` BEFORE the query reaches MySQL, which also
    means an `except pymysql.err.MySQLError` handler does not catch it.

    infra#3713 is what that cost. `_recent_guild_setup_keys` had
    `LIKE 'bank grant-deposit %'` with a bare percent, so the guild-bank pass
    raised on every cycle and no guild on the realm ever bought a bank tab. The
    pass only runs once it wins the family's single travel column, which it
    waited roughly twenty minutes for, so the traceback was rare enough in the
    log to read as incidental - three investigations blamed a missing C++ verb,
    an offline client and an unmet prerequisite before anyone read it.

    The sibling `_recent_guild_bank_keys` two hundred lines away shows the
    other correct answer: pass the pattern as an argument
    (`command LIKE %s`, `("bank deposit %", ...)`) so the percent never sits in
    the format string at all.

    Parsed with `ast` rather than grepped, so a percent inside a docstring or a
    comment cannot raise a false alarm.
    """

    @staticmethod
    def _literal(node):
        """The SQL text if this argument is a plain (possibly joined) literal."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = ParameterisedQueriesSurviveMogrify._literal(node.left)
            right = ParameterisedQueriesSurviveMogrify._literal(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    def test_no_execute_call_raises_on_its_own_placeholders(self):
        tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
                continue
            if len(node.args) != 2:
                continue
            sql = self._literal(node.args[0])
            if sql is None:
                continue
            # How many arguments the call actually supplies.
            args = node.args[1]
            if isinstance(args, (ast.Tuple, ast.List)):
                supplied = len(args.elts)
            else:
                continue  # built at runtime; cannot count statically
            checked += 1
            try:
                sql % tuple("x" * supplied)
            except TypeError as exc:
                self.fail(
                    f"bridge.py line {node.lineno}: query supplies {supplied} "
                    f"argument(s) but does not render ({exc}). A literal % in "
                    f"the SQL must be doubled to %%, or passed as an argument. "
                    f"Query: {sql[:120]!r}"
                )
        self.assertGreater(checked, 5, "parsed too few execute() calls to trust")


def _gb_block() -> str:
    """`_guild_bank_once`'s body, to the next def at the same indent."""
    src = BRIDGE.read_text(encoding="utf-8")
    signature = "    async def _guild_bank_once(self, cohort=None) -> None:"
    start = src.index(signature)
    rest = src[start:]
    match = re.search(r"\n {0,4}(async def |def |class )", rest[1:])
    return rest[: match.start() + 1] if match else rest


def _gb_statements() -> str:
    """The same body with docstrings and `#` commentary stripped.

    Required here, not optional. The fix this guards quotes the exact buggy
    expressions (`aimed or at_the_vault`) in its own explanatory comments, so a
    test reading raw source would match the prose that documents the bug and
    pass while the bug was live. `test_town_bank_errands._statements` exists
    for the same reason and says it was caught by this twice.
    """
    body = _gb_block()
    marker = '"""'
    if body.count(marker) >= 2:
        body = body.split(marker, 2)[2]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


class TheGuildBankPassActsOnlyWhereItIsStanding(unittest.TestCase):
    """Winning the travel column is not the same as having walked it.

    infra#3713. Both gates in `_guild_bank_once` read the claim as though it
    were an arrival - the setup path as `if aimed or at_the_vault`, the deposit
    path as `if not aimed and not at_the_vault`. `_claim_town_slot` returns
    True the moment the pass wins the RIGHT TO WALK, which is the start of the
    journey; so on 2026-09-19 the column was claimed at 03:47:08 and
    `bank buy-tab` was queued at 03:47:09 with the leader 3311 yards from the
    vault. The core refused it, correctly, and `guild_bank_tab` stayed empty
    for the whole life of the pass.

    This is the same correction infra#3815 already made one pass over, where
    `TheBankStepNeedsNoArrivalTest` was renamed
    `TheBankStepAsksWhetherTheFamilyArrived` because, in its own words, "the
    name was the claim, and the claim was false".
    """

    def test_the_claim_is_never_a_substitute_for_the_arrival(self):
        """THE BUG, AS ONE ASSERTION. `aimed or at_the_vault` let a pass that
        had merely won the column queue a row for a leader still on the road."""
        self.assertNotIn("aimed or at_the_vault", _gb_statements())

    def test_starved_walking_and_arrived_are_three_separate_answers(self):
        """`not aimed and not at_the_vault` STAYS - it reports starvation, and
        infra#3464 exists because this pass used to discard that and say
        nothing while the leader sat on another errand for 15+ minutes. What
        was missing is the middle state: aimed, walking, not there yet. It used
        to fall through to queueing.

        THE COUNT IS ONE NOW, AND THAT IS THE POINT OF infra#4198. There were
        two of every gate because setup and deposit were two mutually
        exclusive branches, and the setup one returned on every path - so
        `plan_deposits` was never called while `plan_setup` still had a rank
        to ask about, which against the live guild was for ever. The three
        states are unchanged; there is one set of them, in front of one walk
        that serves both errands.
        """
        code = _gb_statements()
        self.assertIn("not aimed and not at_the_vault", code)
        self.assertEqual(code.count("if not at_the_vault:"), 1)

    def test_the_arrived_branch_is_what_queues(self):
        """Arrival is the fall-through past both negative gates (infra#4198).

        It used to be a positive `if at_the_vault:` inside the setup branch.
        The property is the same one and is now asserted where it lives: every
        row this pass writes is written BELOW the walking gate, so nothing is
        queued for a leader still on the road.
        """
        code = _gb_statements()
        arrived = code[code.index("if not at_the_vault:") :]
        arrived = arrived[arrived.index("return") + len("return") :]
        self.assertIn('"guildbank-setup")', arrived)
        self.assertIn('_insert_guild, deposit.name, command, "guildbank"', arrived)

    def test_the_column_is_still_claimed_so_the_walk_still_starts(self):
        """Dropping the RETURN VALUE must not drop the CALL.

        The claim is what writes the aim; without it the leader never sets off
        and an arrival-only gate would wait for ever. ONE claim now, not two:
        see the sibling test above and infra#4198.
        """
        self.assertEqual(
            _gb_statements().count("aimed = await self._claim_town_slot("), 1
        )


if __name__ == "__main__":
    unittest.main()
