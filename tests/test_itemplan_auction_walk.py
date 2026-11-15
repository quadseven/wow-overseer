"""A planned AUCTION stack gets a walk to an auctioneer (#2605 follow-up).

Measured on the dev realm on 2026-11-15: the item plan logged many AUCTION
decisions in one afternoon and wrote no `kind='auction'` row, because the
executor lists only while the holder already stands at a counter and nothing
sent a holder to one. The walk is the existing `_auction_list_walk`; this pins
that the executor asks for it, at the plan's own price and nothing else.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan_shadow as shadow  # noqa: E402
from test_itemplan_recipe_exit import row  # noqa: E402
from test_itemplan_shadow import import_bridge  # noqa: E402

TEMPLATE = {
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
}


def extras():
    return shadow.Extras(
        open_quest_items={"Ana": frozenset()},
        market={},
        templates=TEMPLATE,
        instance_soulbound={101: False},
        fire_gear=frozenset(),
        guild_free={},
        guild_crafters=(),
    )


class TheExecutorSendsAHolderToTheCounter(unittest.IsolatedAsyncioTestCase):
    async def run_pass(self, houses):
        executor = SimpleNamespace(
            _auction_holder_houses=mock.AsyncMock(return_value=houses),
            _auction_list_walk=mock.AsyncMock(),
            _keep_at_auctioneer=mock.AsyncMock(),
        )
        queued = []
        bridge = import_bridge()
        shadow.reset()

        def insert(holder, command):
            queued.append((holder, command))
            return 1

        with (
            mock.patch.object(
                bridge.itemplan_shadow, "auction_enabled", return_value=True
            ),
            mock.patch.object(bridge, "_itemplan_reads", return_value=extras()),
            mock.patch.object(bridge, "_recent_auction_keys", return_value=set()),
            mock.patch.object(bridge, "_insert_auction", side_effect=insert),
        ):
            await bridge.Bridge._itemplan_auction(
                executor, ["Ana"], "Fam", [row(101, 2001, "Design: Ring")], {"Ana": 10}
            )
        return executor, queued

    async def test_a_holder_away_from_a_counter_is_walked_there(self):
        executor, queued = await self.run_pass({})
        self.assertEqual(queued, [])
        executor._auction_list_walk.assert_awaited_once()
        args, kwargs = executor._auction_list_walk.await_args
        self.assertEqual(args[2], "Fam")
        sales = kwargs["sales"]
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0].candidate.item_guid, 101)

    async def test_the_walk_carries_the_plans_price_not_a_made_up_one(self):
        executor, _ = await self.run_pass({})
        sale = executor._auction_list_walk.await_args.kwargs["sales"][0]
        self.assertEqual(sale.buyout, 8000)

    async def test_a_holder_already_at_a_counter_lists_and_does_not_walk(self):
        executor, queued = await self.run_pass({"Ana": 2})
        self.assertEqual(len(queued), 1)
        executor._auction_list_walk.assert_not_awaited()
        executor._keep_at_auctioneer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
