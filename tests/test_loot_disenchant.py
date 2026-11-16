"""Truly trash is disenchanted, not shelved: the guild loot policy's last rule.

Loot order: an upgrade for anyone goes to that guildmate; what nobody can use
goes to the guild bank or the auction house; what is truly trash is broken down
for enchanting materials. Trash is an UNBOUND uncommon-to-epic piece that
upgrades nobody, whose expected auction value is low, and that a guild
enchanter's Enchanting skill can break down. Never vendored.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
import itemplan  # noqa: E402
import lootpolicy  # noqa: E402
from lootpolicy import BANK_OR_AUCTION, DISENCHANT, UPGRADE, VENDOR  # noqa: E402

import test_epic_kept as base  # noqa: E402
from test_itemplan import member, stack  # noqa: E402
from test_loot_policy import piece, yes  # noqa: E402

EVERY_CLASS = base.EVERY_CLASS
ENCHANTING = 333


def cheap(row):
    return 800  # copper, well under TRASH_CEILING


def dear(row):
    return 250_000  # 25 gold


def unread(row):
    return None


def green(**kw):
    """An unbound uncommon piece nobody asked for; the core asks skill 25."""
    fields = dict(quality=2, disenchant_skill=25)
    fields.update(kw)
    return piece(**fields)


def enchanters(**skills):
    return lambda: dict(skills)


def decide(row, wanted=(), value=cheap, who=None):
    return lootpolicy.decide(
        row,
        EVERY_CLASS,
        yes(wanted),
        auction_value=value,
        enchanters=who if who is not None else enchanters(Og=60),
    )


class TheTrashRule(unittest.TestCase):
    def test_an_unbound_cheap_green_nobody_wants_is_disenchanted(self):
        v = decide(green())
        self.assertEqual(v.route, DISENCHANT)
        self.assertIn("Og", v.why)

    def test_a_cheap_green_nobody_can_wear_is_disenchanted_too(self):
        self.assertEqual(decide(green(required_level=80)).route, DISENCHANT)

    def test_a_valuable_one_keeps_the_bank_or_the_auction_house(self):
        self.assertEqual(decide(green(), value=dear).route, BANK_OR_AUCTION)

    def test_the_ceiling_is_exclusive(self):
        def at(row):
            return lootpolicy.TRASH_CEILING

        self.assertEqual(decide(green(), value=at).route, BANK_OR_AUCTION)

    def test_an_enchanter_with_too_little_skill_means_bank_or_auction(self):
        v = decide(green(), who=enchanters(Og=10))
        self.assertEqual(v.route, BANK_OR_AUCTION)

    def test_a_second_enchanter_with_enough_skill_is_enough(self):
        self.assertEqual(
            decide(green(), who=enchanters(Og=10, Oz=30)).route, DISENCHANT
        )

    def test_no_enchanter_means_bank_or_auction(self):
        self.assertEqual(decide(green(), who=enchanters()).route, BANK_OR_AUCTION)
        no_judge = lootpolicy.decide(green(), EVERY_CLASS, yes([]), auction_value=cheap)
        self.assertEqual(no_judge.route, BANK_OR_AUCTION)

    def test_an_unreadable_price_or_enchanter_list_is_not_trash(self):
        self.assertEqual(decide(green(), value=unread).route, BANK_OR_AUCTION)
        self.assertEqual(decide(green(), who=lambda: None).route, BANK_OR_AUCTION)

    def test_a_bug_in_the_enchanter_judge_is_not_swallowed(self):
        def broken():
            raise TypeError("a bug")

        with self.assertRaises(TypeError):
            decide(green(), who=broken)

    def test_a_piece_the_core_cannot_break_down_is_never_trash(self):
        for why, row in (
            ("no DisenchantID", green(disenchant_id=0)),
            ("never (-1)", green(disenchant_skill=-1)),
            ("unread skill", green(disenchant_skill=None)),
        ):
            with self.subTest(why=why):
                self.assertEqual(decide(row).route, BANK_OR_AUCTION)

    def test_nothing_here_is_ever_vendored(self):
        for row in (green(), green(required_level=80), green(quality=4)):
            for value in (cheap, dear, unread):
                for who in (enchanters(), enchanters(Og=1), enchanters(Og=300)):
                    got = decide(row, value=value, who=who)
                    self.assertNotEqual(got.route, VENDOR)

    def test_an_upgrade_stays_an_upgrade(self):
        v = decide(green(), wanted=["Zrog"])
        self.assertEqual(v.route, UPGRADE)
        self.assertEqual(v.wanted_by, ("Zrog",))

    def test_a_bound_piece_nobody_can_use_is_still_disenchanted_at_any_price(self):
        row = green(instance_flags=1, required_level=80)
        self.assertEqual(decide(row, value=dear).route, DISENCHANT)

    def test_a_bound_usable_piece_stays_with_its_holder(self):
        self.assertEqual(decide(green(instance_flags=1)).route, lootpolicy.HOLD)

    def test_a_non_gear_item_is_never_trash(self):
        gem = green(item_class=3, inventory_type=0)
        self.assertEqual(decide(gem).route, BANK_OR_AUCTION)


class TheExpectedAuctionValue(unittest.TestCase):
    def test_a_market_quote_is_net_of_the_house_cut(self):
        self.assertEqual(itemplan.expected_auction_copper((1000, 3), 50), 950)

    def test_no_quote_uses_the_least_the_plan_wants_before_it_lists(self):
        self.assertEqual(
            itemplan.expected_auction_copper(None, 100),
            100 * itemplan.AUCTION_BEATS_VENDOR_BY,
        )

    def test_the_ceiling_is_twice_the_least_listing_gain(self):
        self.assertEqual(lootpolicy.TRASH_CEILING, 2 * itemplan.AUCTION_MIN_GAIN)

    def test_the_two_modules_name_the_route_the_same(self):
        self.assertEqual(itemplan.DISENCHANT, lootpolicy.DISENCHANT)


class TheBridgeGate(unittest.TestCase):
    """_insert_sell for a green: the DISENCHANT verdict writes the give."""

    def setUp(self):
        self.inner = base.WriterGateTest("test_an_ordinary_sale_is_untouched")
        self.inner.setUp()
        self.addCleanup(self.inner.doCleanups)
        self.bridge = self.inner.bridge
        patches = (
            mock.patch.object(
                self.bridge, "_expected_auction_copper", return_value=800
            ),
            mock.patch.object(
                self.bridge, "_family_enchanters", return_value={"Og": 60}
            ),
            mock.patch.object(self.bridge, "DISENCHANT_ROUTE", True),
            mock.patch.object(
                self.bridge,
                "_disenchant_facts",
                return_value=bag_pressure.DisenchantFacts(4, 2, 60, 25, False),
            ),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_cheap_green_is_given_to_the_enchanter_never_vendored(self):
        self.inner.facts[7001] = green(item_guid=7001)
        self.inner.wanted[7001] = ()
        self.bridge._insert_sell(self.inner.candidate("Grug", 7001, 2))
        written = self.inner.inserts()
        self.assertEqual(len(written), 2)
        give, breakdown = written
        self.assertEqual(give[1][:3], ("Grug", "guid:7001", "give"))
        self.assertEqual(give[1][3], "Og")
        self.assertIn("'disenchant'", breakdown[0])
        self.assertEqual(breakdown[1][0], "Og")
        self.assertFalse(any("'sell'" in sql for sql, _p in written))

    def test_a_valuable_green_is_neither_given_nor_sold(self):
        self.inner.facts[7002] = green(item_guid=7002)
        self.inner.wanted[7002] = ()
        with mock.patch.object(
            self.bridge, "_expected_auction_copper", return_value=250_000
        ):
            self.bridge._insert_sell(self.inner.candidate("Grug", 7002, 2))
        self.assertEqual(self.inner.inserts(), [])

    def test_too_little_skill_is_neither_given_nor_sold(self):
        self.inner.facts[7003] = green(item_guid=7003)
        self.inner.wanted[7003] = ()
        with mock.patch.object(
            self.bridge, "_family_enchanters", return_value={"Og": 5}
        ):
            self.bridge._insert_sell(self.inner.candidate("Grug", 7003, 2))
        self.assertEqual(self.inner.inserts(), [])

    def test_an_upgrade_is_neither_given_nor_sold(self):
        self.inner.facts[7004] = green(item_guid=7004)
        self.inner.wanted[7004] = ("Zrog",)
        self.bridge._insert_sell(self.inner.candidate("Grug", 7004, 2))
        self.assertEqual(self.inner.inserts(), [])

    def test_an_unreadable_enchanter_list_is_neither_given_nor_sold(self):
        self.inner.facts[7006] = green(item_guid=7006)
        self.inner.wanted[7006] = ()
        with mock.patch.object(
            self.bridge, "_family_enchanters", side_effect=OSError("db down")
        ):
            self.bridge._insert_sell(self.inner.candidate("Grug", 7006, 2))
        self.assertEqual(self.inner.inserts(), [])

    def test_a_bug_reading_the_enchanters_is_not_swallowed(self):
        self.inner.facts[7007] = green(item_guid=7007)
        self.inner.wanted[7007] = ()
        with (
            mock.patch.object(
                self.bridge, "_family_enchanters", side_effect=TypeError("bug")
            ),
            self.assertRaises(TypeError),
        ):
            self.bridge._insert_sell(self.inner.candidate("Grug", 7007, 2))

    def test_the_disenchant_writer_is_allowed_for_trash_only(self):
        self.inner.facts[7005] = green(item_guid=7005)
        self.inner.wanted[7005] = ()
        self.assertFalse(self.bridge._epic_blocks("Og", "guid:7005", "disenchant"))
        self.inner.wanted[7005] = ("Zrog",)
        self.assertTrue(self.bridge._epic_blocks("Og", "guid:7005", "disenchant"))


class LedgerCursor:
    """A cursor over a shared list of written overseer_command rows."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.lastrowid = 0
        self._one = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if sql.startswith("INSERT INTO overseer_command"):
            if "'disenchant'" in sql:
                kind = "disenchant"
            elif "'give'" in sql:
                kind = "give"
            else:
                kind = params[2]
            self.ledger.append(
                {"kind": kind, "command": params[1], "status": "pending"}
            )
            self.lastrowid = len(self.ledger)
        elif "status IN ('pending', 'claimed')" in sql and "command LIKE" in sql:
            exact, like_a, like_b = params
            prefixes = (like_a[:-1], like_b[:-1])
            self._one = {
                "n": sum(
                    1
                    for row in self.ledger
                    if row["kind"] in ("give", "mail")
                    and row["status"] in ("pending", "claimed")
                    and (row["command"] == exact or row["command"].startswith(prefixes))
                )
            }
        else:
            self._one = None

    def fetchone(self):
        return self._one

    def fetchall(self):
        return []


class LedgerConnection:
    def __init__(self, ledger):
        self.ledger = ledger

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return LedgerCursor(self.ledger)


class OneGivePerCopy(unittest.TestCase):
    """The plan's gift and the sale path's give never both move one copy."""

    def setUp(self):
        self.inner = base.WriterGateTest("test_an_ordinary_sale_is_untouched")
        self.inner.setUp()
        self.addCleanup(self.inner.doCleanups)
        self.bridge = self.inner.bridge
        self.ledger: list = []
        patches = (
            mock.patch.object(
                self.bridge,
                "_connect",
                side_effect=lambda: LedgerConnection(self.ledger),
            ),
            mock.patch.object(self.bridge, "DISENCHANT_ROUTE", True),
            mock.patch.object(
                self.bridge, "_family_enchanters", return_value={"Og": 60}
            ),
            mock.patch.object(
                self.bridge,
                "_disenchant_facts",
                return_value=bag_pressure.DisenchantFacts(4, 2, 60, 25, False),
            ),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        import guildshare

        self.gift = guildshare.Gift(
            holder="Grug",
            taker="Oz",
            item="Test Pants",
            entry=500,
            count=1,
            guid=8001,
            need="trash",
            reason="trash",
        )

    def kinds(self):
        return [row["kind"] for row in self.ledger]

    def test_the_plan_gift_first_then_the_sale_path_writes_one_give(self):
        self.assertTrue(self.bridge._insert_guild_gift(self.gift))
        self.assertEqual(self.bridge._disenchant_instead("Grug", 8001), 0)
        self.assertEqual(self.kinds(), ["give"])

    def test_the_sale_path_first_then_the_plan_gift_writes_one_give(self):
        self.assertTrue(self.bridge._disenchant_instead("Grug", 8001))
        # The give and the enchanter's own disenchant, and no second give.
        self.assertEqual(self.kinds(), ["give", "disenchant"])
        self.assertEqual(self.bridge._insert_guild_gift(self.gift), 0)
        self.assertEqual(self.kinds(), ["give", "disenchant"])

    def test_a_delivered_give_does_not_block_a_later_one(self):
        self.assertTrue(self.bridge._insert_guild_gift(self.gift))
        self.ledger[0]["status"] = "delivered"
        self.assertTrue(self.bridge._insert_guild_gift(self.gift))
        self.assertEqual(len(self.ledger), 2)


class ThePlannerAsksThePolicy(unittest.TestCase):
    """The item plan's disenchant step and the policy cannot disagree."""

    def pants(self, **kw):
        fields = dict(
            entry=500,
            name="Test Pants",
            item_class=4,
            subclass=1,
            quality=2,
            sell=100,
            bind=2,
            soulbound=False,
            req_level=30,
            item_level=30,
            disenchant_id=7,
            disenchant_skill=25,
            guid=9001,
        )
        fields.update(kw)
        return stack(holder="Og", **fields)

    def decision(self, route_for, members):
        ctx = itemplan.Context(fire_gear=frozenset(), loot_route=route_for)
        return itemplan.plan([self.pants()], members, ctx).decisions[0]

    def route(self, route_for):
        who = member(name="Og", skills=[(ENCHANTING, 60, 75)])
        return self.decision(route_for, [who]).route

    def test_an_upgrade_the_policy_names_is_not_broken_down(self):
        verdict = decide(green(item_guid=9001), wanted=["Zrog"])
        self.assertEqual(verdict.route, UPGRADE)
        got = self.route(lambda holder, guid: verdict.route)
        self.assertNotEqual(got, itemplan.DISENCHANT)

    def test_trash_the_policy_names_is_broken_down(self):
        verdict = decide(green(item_guid=9001))
        self.assertEqual(verdict.route, DISENCHANT)
        self.assertEqual(
            self.route(lambda holder, guid: verdict.route), itemplan.DISENCHANT
        )

    def test_the_plan_is_asked_about_the_very_copy(self):
        asked = []

        def route_for(holder, guid):
            asked.append((holder, guid))
            return DISENCHANT

        self.route(route_for)
        self.assertEqual(asked, [("Og", 9001)])

    def test_an_unreadable_verdict_breaks_nothing_down(self):
        got = self.route(lambda holder, guid: None)
        self.assertNotEqual(got, itemplan.DISENCHANT)

    def test_they_agree_across_every_scenario(self):
        scenarios = (
            dict(),
            dict(wanted=["Zrog"]),
            dict(value=dear),
            dict(who=enchanters(Og=5)),
            dict(who=enchanters()),
        )
        for kw in scenarios:
            with self.subTest(scenario=sorted(kw)):
                verdict = decide(green(item_guid=9001), **kw)
                planned = self.route(lambda holder, guid, v=verdict: v.route)
                self.assertEqual(
                    planned == itemplan.DISENCHANT, verdict.route == DISENCHANT
                )

    def test_a_low_skill_holder_gives_to_the_qualified_enchanter(self):
        """The policy says DISENCHANT because another enchanter reaches the
        skill: the plan follows it with the give, not with silence."""
        holder = member(name="Og", skills=[(ENCHANTING, 5, 75)])
        other = member(name="Oz", skills=[(ENCHANTING, 60, 75)])
        verdict = decide(green(item_guid=9001), who=enchanters(Og=5, Oz=60))
        self.assertEqual(verdict.route, DISENCHANT)
        d = self.decision(lambda holder, guid: verdict.route, [holder, other])
        self.assertEqual((d.route, d.target), (itemplan.GIVE, "Oz"))

    def test_a_low_skill_holder_with_no_qualified_enchanter_gets_no_give(self):
        holder = member(name="Og", skills=[(ENCHANTING, 5, 75)])
        other = member(name="Oz", skills=[(ENCHANTING, 10, 75)])
        d = self.decision(lambda holder, guid: DISENCHANT, [holder, other])
        self.assertNotIn(d.route, (itemplan.GIVE, itemplan.DISENCHANT))

    def test_a_low_skill_holder_is_not_given_a_piece_the_policy_keeps(self):
        holder = member(name="Og", skills=[(ENCHANTING, 5, 75)])
        other = member(name="Oz", skills=[(ENCHANTING, 60, 75)])
        d = self.decision(lambda holder, guid: UPGRADE, [holder, other])
        self.assertNotEqual(d.target, "Oz")
        self.assertNotEqual(d.route, itemplan.DISENCHANT)

    def test_a_plan_with_no_policy_wired_in_judges_alone_as_before(self):
        self.assertEqual(self.route(None), itemplan.DISENCHANT)

    def test_the_shadow_hands_the_plan_the_policy_and_the_stack_its_guid(self):
        import itemplan_shadow as shadow

        row = {
            "holder": "Og",
            "item_guid": 9001,
            "entry": 500,
            "name": "Test Pants",
            "quality": 2,
            "count": 1,
            "sell_price": 100,
            "item_class": 4,
        }
        self.assertEqual(shadow.build_stacks([row])[0].guid, 9001)
        seen = shadow.Extras(loot_route=lambda holder, guid: DISENCHANT)
        ctx = shadow._context(seen, None)
        self.assertEqual(ctx.loot_route("Og", 9001), DISENCHANT)


if __name__ == "__main__":
    unittest.main()
