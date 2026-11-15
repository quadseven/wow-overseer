"""A recipe nobody can learn has an exit: a seat, the vault, or the auction (#2605).

Measured on the dev realm on 2026-11-15 over 687 recipe, pattern and book
stacks held by the two guilds: 172 could be learned by a raid seat today and
only sat unrouted, 502 were for a profession a seat is assigned but whose
skill is still short, and 13 were for a profession nobody works. Rule R9 said
"never vendor" and nothing else took them, so they filled bags, banks and both
vaults. The rule now: a recipe a guildmate can learn now goes to that guildmate;
one a seat could learn within its assigned profession is kept for it in the
vault, to a ceiling; every other tradable recipe is listed on the real auction
house by the character holding it; an unsold listing that came back twice may
be vendored. Nothing is created: only what a character already holds.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import guildtrades  # noqa: E402
import itemplan  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
from itemplan import (  # noqa: E402
    AUCTION,
    GIVE,
    GUILD_BANK,
    SELL_VENDOR,
    Context,
)
from test_itemplan import decide, member, one, stack  # noqa: E402

ALCHEMY, ENCHANTING, JEWELCRAFTING = 171, 333, 755
VAULT = {
    ("Fam", itemplan.GUILD_TAB_MATERIALS): 40,
    ("Fam", itemplan.GUILD_TAB_RAID): 10,
}


def recipe(entry=9001, rank=200, subclass=6, skill=ALCHEMY, quality=2, **kw):
    base = dict(
        holder="Uzza",
        entry=entry,
        name="Recipe %d" % entry,
        item_class=itemplan.C_RECIPE,
        subclass=subclass,
        quality=quality,
        sell=2000,
        required_skill_rank=rank,
        required_skill=skill,
    )
    base.update(kw)
    return stack(**base)


UZZA = member("Uzza", skills=[(197, 150, 225)])


def ctx(**kw):
    base = dict(fire_gear=frozenset(), guild_free=dict(VAULT))
    base.update(kw)
    return Context(**base)


class WhoCanLearnItNow(unittest.TestCase):
    def test_a_guildmate_with_the_skill_gets_it(self):
        r = recipe(rank=150)
        d = one([r], [UZZA], r, ctx(guild_crafters=(("Seatsmith", "alchemy", 200),)))
        self.assertEqual((d.route, d.target), (GIVE, "Seatsmith"))
        self.assertIn("learn it now", d.reason)

    def test_a_guildmate_short_of_the_skill_does_not_take_a_bag_slot(self):
        r = recipe(rank=250)
        d = one([r], [UZZA], r, ctx(guild_crafters=(("Seatsmith", "alchemy", 100),)))
        self.assertNotEqual(d.route, GIVE)


class KeptForTheAssignedSeat(unittest.TestCase):
    def test_a_trade_a_seat_is_assigned_is_kept_in_the_vault(self):
        r = recipe(rank=250)
        d = one([r], [UZZA], r, ctx())
        self.assertEqual((d.route, d.tab), (GUILD_BANK, itemplan.GUILD_TAB_MATERIALS))
        self.assertIn("assigned", d.reason)

    def test_the_vault_ceiling_keeps_it_from_filling(self):
        recipes = [
            recipe(entry=9100 + i, rank=100 + i)
            for i in range(itemplan.SEAT_RECIPE_CEILING + 5)
        ]
        by_key, _ = decide(recipes, [UZZA], ctx())
        routes = [by_key[r.key].route for r in recipes]
        self.assertEqual(routes.count(GUILD_BANK), itemplan.SEAT_RECIPE_CEILING)
        self.assertEqual(routes.count(AUCTION), 5)

    def test_the_nearest_to_learnable_is_kept_first(self):
        near = recipe(entry=9201, rank=60)
        far = recipe(entry=9202, rank=290)
        filler = [
            recipe(entry=9300 + i, rank=61 + i)
            for i in range(itemplan.SEAT_RECIPE_CEILING - 1)
        ]
        by_key, _ = decide(
            [far, near, *filler],
            [UZZA],
            ctx(guild_crafters=(("Seatsmith", "alchemy", 55),)),
        )
        self.assertEqual(by_key[near.key].route, GUILD_BANK)
        self.assertEqual(by_key[far.key].route, AUCTION)

    def test_a_full_vault_lists_it_instead(self):
        r = recipe(rank=250)
        d = one([r], [UZZA], r, ctx(guild_free={}))
        self.assertEqual(d.route, AUCTION)

    def test_the_assigned_trades_are_the_profession_plans(self):
        plan = {
            itemplan.TRADE_OF_SKILL[s]
            for s in guildtrades.PRIMARIES
            if itemplan.TRADE_OF_SKILL[s] in itemplan.RECIPE_TRADE.values()
        }
        self.assertEqual(itemplan.SEAT_TRADES, frozenset(plan))


class EverythingElseIsListed(unittest.TestCase):
    def test_a_trade_no_seat_is_assigned_is_listed_at_the_vendor_quote(self):
        r = recipe(subclass=10, skill=JEWELCRAFTING, rank=200)
        d = one([r], [UZZA], r, ctx())
        self.assertEqual(d.route, AUCTION)
        self.assertEqual(d.target, itemplan.LIST_AT_VENDOR_QUOTE)

    def test_a_market_quote_lists_at_the_market_not_the_vendor_quote(self):
        r = recipe(subclass=10, skill=JEWELCRAFTING, rank=200, entry=9500)
        d = one([r], [UZZA], r, ctx(market={9500: (40_000, 1)}))
        self.assertEqual(d.route, AUCTION)
        self.assertNotEqual(d.target, itemplan.LIST_AT_VENDOR_QUOTE)

    def test_a_bound_recipe_is_never_listed(self):
        r = recipe(subclass=10, skill=JEWELCRAFTING, bind=1, soulbound=True)
        d = one([r], [UZZA], r, ctx())
        self.assertNotEqual(d.route, AUCTION)
        self.assertNotEqual(d.route, SELL_VENDOR)

    def test_a_rare_recipe_stays_out_of_the_house_and_the_vendor(self):
        r = recipe(subclass=10, skill=JEWELCRAFTING, quality=3, sell=9000)
        d = one([r], [UZZA], r, ctx())
        self.assertNotIn(d.route, (AUCTION, SELL_VENDOR))

    def test_a_recipe_is_never_vendored_before_it_has_failed_to_sell(self):
        r = recipe(subclass=10, skill=JEWELCRAFTING)
        d = one([r], [UZZA], r, ctx())
        self.assertNotEqual(d.route, SELL_VENDOR)
        once = ctx(failed_listings={("Uzza", r.entry): 1})
        self.assertEqual(one([r], [UZZA], r, once).route, AUCTION)

    def test_two_failed_listings_let_the_vendor_have_it(self):
        r = recipe(subclass=10, skill=JEWELCRAFTING, sell=300)
        twice = ctx(
            failed_listings={("Uzza", r.entry): itemplan.FAILED_LISTINGS_BEFORE_VENDOR}
        )
        d = one([r], [UZZA], r, twice)
        self.assertEqual(d.route, SELL_VENDOR)

    def test_two_failed_listings_of_a_dear_recipe_still_wait_for_a_release(self):
        r = recipe(subclass=10, skill=JEWELCRAFTING, sell=40_000)
        twice = ctx(
            failed_listings={("Uzza", r.entry): itemplan.FAILED_LISTINGS_BEFORE_VENDOR}
        )
        d = one([r], [UZZA], r, twice)
        self.assertEqual(d.route, SELL_VENDOR)
        self.assertTrue(d.confirm)


def row(guid, entry, name, sell=2000, quality=2):
    return {
        "holder": "Ana",
        "item_guid": guid,
        "entry": entry,
        "name": name,
        "quality": quality,
        "count": 1,
        "sell_price": sell,
        "item_class": 9,
        "bag_family": 0,
        "quest_item": False,
        "reagent": False,
        "profession_needed": False,
    }


class TheExecutorListsThem(unittest.IsolatedAsyncioTestCase):
    async def test_a_recipe_with_no_market_is_listed_at_four_times_the_vendor(self):
        from test_itemplan_shadow import import_bridge

        rows = [row(101, 2001, "Design: Ring")]
        extras = shadow.Extras(
            open_quest_items={"Ana": frozenset()},
            market={},
            templates={
                2001: {
                    "item_class": 9,
                    "subclass": 10,
                    "bonding": 0,
                    "inventory_type": 0,
                    "item_level": 1,
                    "req_level": 0,
                    "required_skill_rank": 200,
                    "required_skill": 755,
                    "container_slots": 0,
                    "fire_res": 0,
                    "stats": {},
                }
            },
            instance_soulbound={101: False},
            fire_gear=frozenset(),
            guild_free={},
            guild_crafters=(),
        )
        queued = []
        executor = SimpleNamespace(
            _auction_holder_houses=mock.AsyncMock(return_value={"Ana": 2}),
            _keep_at_auctioneer=mock.AsyncMock(),
        )
        bridge = import_bridge()
        shadow.reset()

        def insert(holder, command):
            queued.append((holder, command))
            return 1

        with (
            mock.patch.object(
                bridge.itemplan_shadow, "auction_enabled", return_value=True
            ),
            mock.patch.object(bridge, "_itemplan_reads", return_value=extras),
            mock.patch.object(bridge, "_recent_auction_keys", return_value=set()),
            mock.patch.object(bridge, "_insert_auction", side_effect=insert),
        ):
            await bridge.Bridge._itemplan_auction(
                executor, ["Ana"], "Fam", rows, {"Ana": 10}
            )
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][1], "list guid:101 bid:6400 buyout:8000 hours:12")


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


class TheListingHistory(unittest.TestCase):
    def carried(self):
        return [row(101, 2001, "Design: Ring"), row(102, 2002, "Plans: Belt")]

    def test_a_stack_listed_twice_and_still_carried_counts_two(self):
        import itemplan_data

        history = [
            {"item_guid": "101", "listings": 2},
            {"item_guid": "999", "listings": 3},
        ]
        got = itemplan_data.failed_listings(history, self.carried())
        self.assertEqual(got, {("Ana", 2001): 2})

    def test_the_read_asks_for_applied_list_rows_only(self):
        import itemplan_data
        import itemplan_reads

        cur = FakeCursor([{"item_guid": "102", "listings": 2}])
        got = itemplan_reads._failed_listings(cur, self.carried())
        self.assertEqual(got, {("Ana", 2002): 2})
        self.assertIn("kind = 'auction'", cur.sql)
        self.assertIn("applied", cur.sql)
        self.assertEqual(cur.sql, itemplan_data.LISTING_HISTORY_SQL)

    def test_the_plan_reads_the_history_from_the_extras(self):
        rows = [row(101, 2001, "Design: Ring", sell=300)]
        extras = shadow.Extras(
            open_quest_items={"Ana": frozenset()},
            failed_listings={("Ana", 2001): 2},
            templates={
                2001: {
                    "item_class": 9,
                    "subclass": 10,
                    "bonding": 0,
                    "inventory_type": 0,
                    "item_level": 1,
                    "req_level": 0,
                    "required_skill_rank": 200,
                    "required_skill": 755,
                    "container_slots": 0,
                    "fire_res": 0,
                    "stats": {},
                }
            },
            instance_soulbound={101: False},
            fire_gear=frozenset(),
        )
        report = shadow.shadow(["Ana"], "Fam", rows, {"Ana": 10}, extras=extras)
        self.assertEqual(report.plan.decisions[0].route, SELL_VENDOR)


if __name__ == "__main__":
    unittest.main()
