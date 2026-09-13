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


if __name__ == "__main__":
    unittest.main()
