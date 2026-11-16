"""The guild loot policy: every seller obeys one function (lootpolicy.decide).

Priority order: an upgrade goes to the guildmate it upgrades; what somebody
could use, or nobody could, goes to the guild bank or the auction house; a
bound piece nobody can use is disenchanted; only gray and junk is vendored.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import lootpolicy  # noqa: E402
from lootpolicy import (  # noqa: E402
    BANK_OR_AUCTION,
    DISENCHANT,
    HOLD,
    UPGRADE,
    VENDOR,
)

import test_epic_kept as base  # noqa: E402

EVERY_CLASS = base.EVERY_CLASS


def piece(**kw):
    """A carried, unbound, mail chest a warrior could wear at the cap."""
    row = {
        "item_guid": 5001,
        "entry": 9000,
        "name": "Test Hauberk",
        "quality": 3,
        "required_level": 40,
        "item_class": 4,
        "subclass": 3,
        "inventory_type": 5,
        "allowable_class": -1,
        "instance_flags": 0,
        "bonding": 2,
        "holder_class": 1,
        "disenchant_id": 60,
    }
    row.update(kw)
    return row


def yes(names):
    return lambda row: tuple(names)


def nobody(row):
    return ()


def unread(row):
    return None


# Required level above the cap: no class can ever wear it.
UNWEARABLE = dict(required_level=80)


class RuleOneUpgrade(unittest.TestCase):
    def test_a_piece_that_upgrades_a_guildmate_goes_to_that_guildmate(self):
        v = lootpolicy.decide(piece(), EVERY_CLASS, yes(["Zrog", "Bluk"]))
        self.assertEqual(v.route, UPGRADE)
        self.assertEqual(v.wanted_by, ("Zrog", "Bluk"))

    def test_an_epic_upgrade_is_an_upgrade_too(self):
        v = lootpolicy.decide(piece(quality=4), EVERY_CLASS, yes(["Zrog"]))
        self.assertEqual(v.route, UPGRADE)

    def test_a_soulbound_copy_cannot_be_passed_to_a_guildmate(self):
        row = piece(instance_flags=1, holder="Bork")
        v = lootpolicy.decide(row, EVERY_CLASS, yes(["Zrog"]))
        self.assertNotEqual(v.route, UPGRADE)
        self.assertEqual(v.wanted_by, ())

    def test_a_bind_on_pickup_copy_cannot_be_passed_either(self):
        row = piece(bonding=1, holder="Bork")
        v = lootpolicy.decide(row, EVERY_CLASS, yes(["Zrog", "Oz"]))
        self.assertNotEqual(v.route, UPGRADE)

    def test_a_soulbound_copy_can_upgrade_its_own_holder(self):
        row = piece(instance_flags=1, holder="Bork")
        v = lootpolicy.decide(row, EVERY_CLASS, yes(["Zrog", "Bork"]))
        self.assertEqual((v.route, v.wanted_by), (UPGRADE, ("Bork",)))

    def test_a_soulbound_copy_with_no_known_holder_names_nobody(self):
        v = lootpolicy.decide(piece(instance_flags=1), EVERY_CLASS, yes(["Zrog"]))
        self.assertNotEqual(v.route, UPGRADE)

    def test_an_unread_judge_holds_it(self):
        self.assertEqual(lootpolicy.decide(piece(), EVERY_CLASS, unread).route, HOLD)

    def test_no_judge_holds_it(self):
        self.assertEqual(lootpolicy.decide(piece(), EVERY_CLASS).route, HOLD)


class RuleTwoUsableOrNobody(unittest.TestCase):
    def test_usable_but_nobody_upgrades_goes_to_bank_or_auction(self):
        v = lootpolicy.decide(piece(), EVERY_CLASS, nobody)
        self.assertEqual(v.route, BANK_OR_AUCTION)

    def test_an_epic_nobody_can_wear_goes_to_bank_or_auction(self):
        row = piece(quality=4, **UNWEARABLE)
        self.assertEqual(
            lootpolicy.decide(row, EVERY_CLASS, nobody).route, BANK_OR_AUCTION
        )

    def test_a_recipe_reagent_or_consumable_is_used_by_the_guild(self):
        for klass in (0, 5, 9):
            with self.subTest(item_class=klass):
                row = piece(item_class=klass, inventory_type=0, quality=2, subclass=0)
                v = lootpolicy.decide(row, EVERY_CLASS, nobody)
                self.assertEqual(v.route, BANK_OR_AUCTION)

    def test_a_bound_piece_nobody_can_use_is_disenchanted(self):
        row = piece(instance_flags=1, **UNWEARABLE)
        v = lootpolicy.decide(row, EVERY_CLASS, nobody)
        self.assertEqual(v.route, DISENCHANT)

    def test_a_bound_epic_nobody_can_use_is_disenchanted(self):
        row = piece(quality=4, bonding=1, **UNWEARABLE)
        v = lootpolicy.decide(row, EVERY_CLASS, nobody)
        self.assertEqual(v.route, DISENCHANT)

    def test_a_bound_piece_that_cannot_be_disenchanted_is_held(self):
        row = piece(instance_flags=1, disenchant_id=0, **UNWEARABLE)
        v = lootpolicy.decide(row, EVERY_CLASS, nobody)
        self.assertEqual(v.route, HOLD)

    def test_a_bound_piece_somebody_could_use_stays_with_its_holder(self):
        v = lootpolicy.decide(piece(instance_flags=1), EVERY_CLASS, nobody)
        self.assertEqual(v.route, HOLD)

    def test_a_soulbound_piece_is_only_ever_its_holders(self):
        """Soulbound to a mage, a plate piece cannot go to a warrior."""
        row = piece(instance_flags=1, holder_class=8, subclass=4)
        v = lootpolicy.decide(row, EVERY_CLASS, yes(["Zrog"]))
        self.assertNotIn(v.route, (UPGRADE, VENDOR))


class RuleThreeVendorOnlyGrayAndJunk(unittest.TestCase):
    def test_gray_is_vendored(self):
        row = piece(quality=0, bonding=0)
        self.assertEqual(lootpolicy.decide(row, EVERY_CLASS, nobody).route, VENDOR)

    def test_a_junk_item_is_vendored(self):
        row = piece(quality=1, item_class=15, subclass=0, inventory_type=0)
        self.assertEqual(lootpolicy.decide(row, EVERY_CLASS, nobody).route, VENDOR)

    def test_an_epic_is_never_vendored(self):
        for flags in (0, 1):
            for level in (40, 80):
                for judge in (yes(["Zrog"]), nobody, unread, None):
                    with self.subTest(flags=flags, level=level):
                        row = piece(
                            quality=4, instance_flags=flags, required_level=level
                        )
                        v = lootpolicy.decide(row, EVERY_CLASS, judge)
                        self.assertNotEqual(v.route, VENDOR)

    def test_a_usable_blue_is_never_vendored(self):
        for judge in (yes(["Zrog"]), nobody, unread):
            v = lootpolicy.decide(piece(quality=3), EVERY_CLASS, judge)
            self.assertNotEqual(v.route, VENDOR)

    def test_a_usable_green_is_never_vendored(self):
        for judge in (yes(["Zrog"]), nobody, unread):
            v = lootpolicy.decide(piece(quality=2), EVERY_CLASS, judge)
            self.assertNotEqual(v.route, VENDOR)

    def test_no_green_or_better_is_ever_vendored(self):
        for quality in (2, 3, 4, 5):
            for bonding in (0, 1, 2):
                for flags in (0, 1):
                    for klass, inv in ((4, 5), (2, 13), (0, 0), (15, 0), (7, 0)):
                        row = piece(
                            quality=quality,
                            bonding=bonding,
                            instance_flags=flags,
                            item_class=klass,
                            inventory_type=inv,
                        )
                        for judge in (yes(["A"]), nobody, unread, None):
                            v = lootpolicy.decide(row, EVERY_CLASS, judge)
                            self.assertNotEqual(v.route, VENDOR, row)

    def test_unread_quality_is_held(self):
        row = piece(quality=None)
        self.assertEqual(lootpolicy.decide(row, EVERY_CLASS, nobody).route, HOLD)


class FailClosed(unittest.TestCase):
    """An unknown is never read as a fact that allows a sale or a shelving."""

    def test_an_empty_class_set_is_unknown_not_nobody(self):
        """`bridge._guild_classes()` is empty when its read failed."""
        for quality in (2, 3, 4):
            with self.subTest(quality=quality):
                row = piece(quality=quality)
                for judge in (yes(["Zrog"]), nobody):
                    v = lootpolicy.decide(row, frozenset(), judge)
                    self.assertEqual(v.route, HOLD)

    def test_an_empty_class_set_never_disenchants_or_banks_a_wearable_epic(self):
        v = lootpolicy.decide(piece(quality=4), frozenset(), nobody)
        self.assertEqual(v.route, HOLD)

    def test_missing_binding_facts_hold_even_gray_and_junk(self):
        for gone in (("instance_flags",), ("bonding",), ("instance_flags", "bonding")):
            for row in (
                piece(quality=0),
                piece(quality=1, item_class=15, subclass=0, inventory_type=0),
                piece(quality=4),
            ):
                for key in gone:
                    row.pop(key)
                with self.subTest(gone=gone, quality=row["quality"]):
                    v = lootpolicy.decide(row, EVERY_CLASS, nobody)
                    self.assertEqual(v.route, HOLD)

    def test_a_none_binding_holds_too(self):
        for key in ("instance_flags", "bonding"):
            row = piece(quality=0, **{key: None})
            self.assertEqual(lootpolicy.decide(row, EVERY_CLASS).route, HOLD)

    def test_an_unread_binding_counts_as_bound(self):
        self.assertTrue(lootpolicy.is_bound({}))


class TheGate(unittest.TestCase):
    """The bridge's writers run for real against a fake world."""

    def setUp(self):
        self.inner = base.WriterGateTest("test_an_ordinary_sale_is_untouched")
        self.inner.setUp()
        self.addCleanup(self.inner.doCleanups)
        self.bridge = self.inner.bridge

    def facts(self, guid, **kw):
        self.inner.facts[guid] = piece(item_guid=guid, **kw)

    def test_a_usable_blue_is_never_vendored_by_the_sale_pass(self):
        self.facts(5001)
        self.inner.wanted[5001] = ()
        self.assertFalse(
            self.bridge._insert_sell(self.inner.candidate("Zrog", 5001, 3))
        )
        self.assertEqual(self.inner.inserts(), [])

    def test_an_epic_is_never_vendored_by_the_sale_pass(self):
        self.facts(5002, quality=4, **UNWEARABLE)
        self.assertFalse(
            self.bridge._insert_sell(self.inner.candidate("Zrog", 5002, 4))
        )
        self.assertEqual(self.inner.inserts(), [])

    def test_a_guild_job_sale_of_a_green_is_refused(self):
        self.facts(5003, quality=2)
        self.inner.wanted[5003] = ()
        row = base.guildcorps.Row("sell", "guid:5003", "", "guildjobs:supply:Zrog")
        self.assertFalse(self.bridge._insert_corps_row("Zrog", row))
        self.assertEqual(self.inner.inserts(), [])

    def test_gray_still_sells(self):
        self.facts(5004, quality=0, bonding=0)
        self.assertTrue(self.bridge._insert_sell(self.inner.candidate("Zrog", 5004, 0)))
        self.assertEqual(len(self.inner.inserts()), 1)

    def test_a_bound_piece_nobody_can_use_is_routed_to_disenchant(self):
        self.facts(5005, instance_flags=1, **UNWEARABLE)
        self.inner.wanted[5005] = ()
        with mock.patch.object(
            self.bridge, "_disenchant_instead", return_value=77
        ) as route:
            wrote = self.bridge._insert_sell(self.inner.candidate("Zrog", 5005, 3))
        self.assertEqual(wrote, 77)
        route.assert_called_once_with("Zrog", 5005)
        self.assertEqual(self.inner.inserts(), [])

    def test_a_failed_class_read_holds_a_wearable_epic(self):
        self.facts(5010, quality=4)
        self.inner.wanted[5010] = ()
        with (
            mock.patch.object(self.bridge, "_guild_classes", return_value=frozenset()),
            mock.patch.object(self.bridge, "_disenchant_instead") as route,
        ):
            wrote = self.bridge._insert_sell(self.inner.candidate("Zrog", 5010, 4))
            blocked = self.bridge._epic_blocks("Zrog", "guid:5010", "disenchant")
        self.assertFalse(wrote)
        route.assert_not_called()
        self.assertTrue(blocked)
        self.assertEqual(self.inner.inserts(), [])

    def test_a_gray_with_no_binding_facts_is_not_sold(self):
        self.facts(5011, quality=0)
        del self.inner.facts[5011]["bonding"]
        self.assertFalse(
            self.bridge._insert_sell(self.inner.candidate("Zrog", 5011, 0))
        )
        self.assertEqual(self.inner.inserts(), [])

    def test_a_sale_naming_an_item_with_no_facts_is_held(self):
        self.assertFalse(
            self.bridge._insert_sell(self.inner.candidate("Zrog", 6000, 0))
        )
        self.assertEqual(self.inner.inserts(), [])

    def test_a_quality_one_recipe_is_never_vendored_by_the_writers(self):
        recipe = dict(item_class=9, inventory_type=0, subclass=0, quality=1)
        self.facts(5020, **recipe)
        self.assertFalse(
            self.bridge._insert_sell(self.inner.candidate("Zrog", 5020, 1))
        )
        row = base.guildcorps.Row("sell", "guid:5020", "", "guildjobs:sell:Zrog")
        self.assertFalse(self.bridge._insert_corps_row("Zrog", row))
        self.assertEqual(self.inner.inserts(), [])

    def test_a_soulbound_upgrade_for_a_guildmate_is_not_called_an_upgrade(self):
        self.facts(5021, instance_flags=1)
        self.inner.wanted[5021] = ("Bluk",)
        self.assertTrue(self.bridge._epic_blocks("Zrog", "guid:5021", "disenchant"))
        self.assertFalse(
            self.bridge._insert_sell(self.inner.candidate("Zrog", 5021, 3))
        )

    def test_a_disenchant_of_an_upgrade_is_refused(self):
        self.facts(5006)
        self.inner.wanted[5006] = ("Bluk",)
        self.assertTrue(self.bridge._epic_blocks("Zrog", "guid:5006", "disenchant"))

    def test_a_disenchant_of_a_bound_unusable_piece_is_allowed(self):
        self.facts(5007, instance_flags=1, **UNWEARABLE)
        self.inner.wanted[5007] = ()
        self.assertFalse(self.bridge._epic_blocks("Zrog", "guid:5007", "disenchant"))


def trade_good(**kw):
    """A common trade good, the shape of an engineering bomb a quest names."""
    row = piece(
        entry=10562,
        name="Hi-Explosive Bomb",
        quality=1,
        item_class=7,
        subclass=0,
        inventory_type=0,
        required_level=0,
        bonding=0,
        disenchant_id=0,
    )
    row.update(kw)
    return row


class AQuestInTheLogNamesIt(unittest.TestCase):
    """A holder's open quest names the item: it never leaves the bags.

    The case: a quest-log entry whose usable item the client shows as a button
    lost the item to a vendor sale, because a common trade good with no wearer
    was filed as "a common item no guild rule claims" and the quest test only
    ever covered class 12.
    """

    def test_a_common_item_no_quest_names_is_still_vendored(self):
        v = lootpolicy.decide(trade_good(quest_needed=False), EVERY_CLASS)
        self.assertEqual(v.route, VENDOR)

    def test_a_common_item_a_logged_quest_names_is_held(self):
        v = lootpolicy.decide(trade_good(quest_needed=True), EVERY_CLASS)
        self.assertEqual(v.route, HOLD)
        self.assertIn("quest", v.why)

    def test_a_gray_item_a_logged_quest_names_is_held(self):
        v = lootpolicy.decide(trade_good(quest_needed=True, quality=0), EVERY_CLASS)
        self.assertEqual(v.route, HOLD)

    def test_an_unread_quest_log_holds_the_item(self):
        v = lootpolicy.decide(trade_good(quest_needed=None), EVERY_CLASS)
        self.assertEqual(v.route, HOLD)

    def test_a_held_quest_item_allows_no_sell_destroy_or_disenchant(self):
        v = lootpolicy.decide(trade_good(quest_needed=True), EVERY_CLASS)
        self.assertFalse(lootpolicy.allowed(v, "sell"))
        self.assertFalse(lootpolicy.allowed(v, "disenchant"))

    def test_a_quest_named_bound_piece_is_not_disenchanted(self):
        row = piece(quest_needed=True, instance_flags=1, **UNWEARABLE)
        v = lootpolicy.decide(row, EVERY_CLASS, nobody)
        self.assertEqual(v.route, HOLD)

    def test_the_fact_query_reads_the_holders_open_quests(self):
        import bag_pressure

        sql = bag_pressure.LOG_QUEST_NEEDED_SQL
        self.assertIn("character_queststatus", sql)
        self.assertIn("qs.guid = ii.owner_guid", sql)
        self.assertIn("qs.status <> 0", sql)
        for column in ("RequiredItemId1", "RequiredItemId6", "ItemDrop4", "StartItem"):
            self.assertIn(column, sql)


class TheGateHoldsAQuestItem(unittest.TestCase):
    def setUp(self):
        self.inner = base.WriterGateTest("test_an_ordinary_sale_is_untouched")
        self.inner.setUp()
        self.addCleanup(self.inner.doCleanups)
        self.bridge = self.inner.bridge

    def test_the_facts_query_carries_the_quest_flag(self):
        self.assertIn("quest_needed", self.bridge._EPIC_FACTS_SQL)

    def test_a_sale_of_a_quest_named_common_item_is_refused(self):
        self.inner.facts[5030] = trade_good(item_guid=5030, quest_needed=True)
        self.assertFalse(
            self.bridge._insert_sell(self.inner.candidate("Grug", 5030, 1))
        )
        self.assertEqual(self.inner.inserts(), [])
        self.assertTrue(self.bridge._epic_blocks("Grug", "guid:5030", "sell"))

    def test_a_sale_of_the_same_item_with_no_quest_is_not_blocked(self):
        self.inner.facts[5031] = trade_good(item_guid=5031, quest_needed=False)
        self.assertFalse(self.bridge._epic_blocks("Grug", "guid:5031", "sell"))


class TheMoversHoldAQuestItem(unittest.TestCase):
    """The guild gift (give and mail), the personal bank and the guild bank
    deposit never move an item a quest in the holder's log names."""

    def setUp(self):
        self.inner = base.WriterGateTest("test_an_ordinary_sale_is_untouched")
        self.inner.setUp()
        self.addCleanup(self.inner.doCleanups)
        self.bridge = self.inner.bridge

    def named(self, guid, needed):
        self.inner.facts[guid] = trade_good(item_guid=guid, quest_needed=needed)

    def gift(self, guid):
        import guildshare

        return guildshare.Gift(
            holder="Grug",
            taker="Fizzog",
            item="Runecloth",
            entry=14047,
            count=19,
            guid=guid,
            need="a quest",
            reason="surplus",
        )

    def move(self, guid, verb="deposit"):
        import bank

        return bank.Move(
            character="Grug",
            verb=verb,
            guid=guid,
            item="Runecloth",
            count=19,
            why="room",
        )

    def test_a_guild_gift_by_mail_of_a_quest_item_is_not_written(self):
        self.named(5040, True)
        wrote = self.bridge._insert_guild_gift(self.gift(5040), "mail")
        self.assertEqual(wrote, 0)
        self.assertEqual(self.inner.inserts(), [])

    def test_a_guild_gift_by_give_of_a_quest_item_is_not_written(self):
        self.named(5041, True)
        self.assertEqual(self.bridge._insert_guild_gift(self.gift(5041)), 0)
        self.assertEqual(self.inner.inserts(), [])

    def test_a_guild_gift_of_a_free_item_is_written(self):
        self.named(5042, False)
        self.assertTrue(self.bridge._insert_guild_gift(self.gift(5042), "mail"))

    def test_an_unreadable_gift_fact_is_not_written(self):
        self.assertEqual(self.bridge._insert_guild_gift(self.gift(5043)), 0)
        self.assertEqual(self.inner.inserts(), [])

    def test_a_personal_bank_deposit_of_a_quest_item_is_not_written(self):
        self.named(5044, True)
        move = self.move(5044)
        self.assertEqual(self.bridge._insert_bank(move, "deposit guid:5044"), 0)
        self.assertEqual(self.inner.inserts(), [])

    def test_a_personal_bank_deposit_of_a_free_item_is_written(self):
        self.named(5045, False)
        move = self.move(5045)
        self.assertTrue(self.bridge._insert_bank(move, "deposit guid:5045"))

    def test_a_withdraw_of_a_quest_item_is_never_held(self):
        self.named(5046, True)
        move = self.move(5046, "withdraw")
        self.assertTrue(self.bridge._insert_bank(move, "withdraw guid:5046"))

    def test_a_guild_bank_deposit_of_a_quest_item_is_not_written(self):
        self.named(5047, True)
        wrote = self.bridge._insert_guild(
            "Grug", "bank deposit-item guid:5047", "guildbank"
        )
        self.assertEqual(wrote, 0)
        self.assertEqual(self.inner.inserts(), [])


if __name__ == "__main__":
    unittest.main()
