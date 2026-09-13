"""Who has more gold than they need, and how much of it goes to the guild.

The pure half of the guild-bank deposit pass (mod-overseer#437, infra#2831).
Written the same day the family's mining errand got stolen by a dungeon
crossing (mod-overseer#435/#438) - `guildbank.plan_deposits` never itself
writes `travel_npc`, but the caller in bridge.py routes the resulting errand
through `ECONOMY_ERRANDS`, deliberately, so it inherits the exact same
idle-traveller guard rather than repeating that mistake one file over.
"""
import pathlib
import unittest

import guildbank

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
MOD_OVERSEER = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"
)


def member(**kw):
    base = dict(name="Grug", money=0, in_guild=True)
    base.update(kw)
    return base


class WhoIsCarryingMoreThanTheFloat(unittest.TestCase):

    def test_nothing_below_the_float_is_planned(self):
        self.assertEqual(
            guildbank.plan_deposits([member(money=guildbank.FLOAT_COPPER)]), [])

    def test_exactly_the_float_is_not_a_surplus(self):
        deposits = guildbank.plan_deposits(
            [member(money=guildbank.FLOAT_COPPER)])
        self.assertEqual(deposits, [])

    def test_one_copper_over_the_float_is_the_whole_surplus(self):
        deposits = guildbank.plan_deposits(
            [member(money=guildbank.FLOAT_COPPER + 1)])
        self.assertEqual(deposits, [guildbank.Deposit(name="Grug", copper=1)])

    def test_a_large_purse_deposits_everything_above_the_float(self):
        deposits = guildbank.plan_deposits([member(money=50_000)])
        self.assertEqual(deposits,
                         [guildbank.Deposit(name="Grug",
                                            copper=50_000 - guildbank.FLOAT_COPPER)])


class OnlyAGuildMemberIsPlanned(unittest.TestCase):

    def test_a_character_with_no_guild_is_skipped_outright(self):
        """Not an error - the errand is meaningless for them, so the caller
        should never have to filter first."""
        deposits = guildbank.plan_deposits(
            [member(money=1_000_000, in_guild=False)])
        self.assertEqual(deposits, [])

    def test_a_missing_in_guild_key_reads_as_not_in_a_guild(self):
        self.assertEqual(
            guildbank.plan_deposits([{"name": "Grug", "money": 1_000_000}]), [])

    def test_a_guild_member_alongside_a_non_member_only_plans_the_member(self):
        deposits = guildbank.plan_deposits([
            member(name="Grug", money=50_000, in_guild=True),
            member(name="Stranger", money=50_000, in_guild=False),
        ])
        self.assertEqual([d.name for d in deposits], ["Grug"])


class AStaleOrAbsentReadNeverManufacturesADeposit(unittest.TestCase):

    def test_a_missing_money_key_is_nothing_to_deposit_not_an_error(self):
        self.assertEqual(guildbank.plan_deposits([{"name": "Grug",
                                                    "in_guild": True}]), [])

    def test_a_zero_purse_deposits_nothing(self):
        self.assertEqual(guildbank.plan_deposits([member(money=0)]), [])

    def test_a_negative_purse_deposits_nothing_rather_than_raising(self):
        """`characters.money` cannot actually be negative, but a stale or
        corrupt read should never turn into a request the executor could act
        on strangely - suppression is always the safe failure here."""
        self.assertEqual(guildbank.plan_deposits([member(money=-500)]), [])

    def test_a_non_int_money_value_is_treated_as_nothing_to_deposit(self):
        self.assertEqual(
            guildbank.plan_deposits([member(money="lots")]), [])

    def test_a_member_with_no_name_is_skipped(self):
        self.assertEqual(
            guildbank.plan_deposits([{"money": 1_000_000, "in_guild": True}]),
            [])


class MultipleMembersEachGetTheirOwnDeposit(unittest.TestCase):

    def test_every_member_over_the_float_gets_a_deposit(self):
        deposits = guildbank.plan_deposits([
            member(name="Grug", money=guildbank.FLOAT_COPPER + 100),
            member(name="Grog", money=guildbank.FLOAT_COPPER + 200),
        ])
        self.assertEqual({d.name: d.copper for d in deposits},
                         {"Grug": 100, "Grog": 200})

    def test_members_come_back_in_the_order_they_were_given(self):
        """Ordering, like _fetch_guild_money's own read, is the caller's
        concern - this module does not re-sort."""
        deposits = guildbank.plan_deposits([
            member(name="Ugga", money=guildbank.FLOAT_COPPER + 1),
            member(name="Bork", money=guildbank.FLOAT_COPPER + 1),
        ])
        self.assertEqual([d.name for d in deposits], ["Ugga", "Bork"])

    def test_an_empty_roster_plans_nothing(self):
        self.assertEqual(guildbank.plan_deposits([]), [])


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
        start = self.body.index('cur.execute(')
        end = self.body.index(')', self.body.index("MINUTE\""))
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

    def test_bridge_writes_the_real_keyword(self):
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertIn('travel_npc="guild banker"', source)
        self.assertNotIn('travel_npc="guild bank"', source)
        self.assertIn('"guild banker"', source[
            source.index("ECONOMY_ERRANDS = ("):
            source.index("\n", source.index("ECONOMY_ERRANDS = ("))
        ])


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
        start = source.index("async def _guild_bank_once(")
        end = source.index("\n    async def ", start + 1)
        self.body = source[start:end]

    def test_the_aim_result_is_captured_not_discarded(self):
        self.assertIn("aimed = await asyncio.to_thread(", self.body)
        self.assertIn("_write_trade_errand", self.body)

    def test_a_refused_aim_is_logged(self):
        self.assertIn("if not aimed:", self.body)
        self.assertIn("log.info(", self.body)


if __name__ == "__main__":
    unittest.main()
