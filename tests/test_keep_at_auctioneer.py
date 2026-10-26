"""`_keep_at_auctioneer` re-asserts only an aim the auction pass holds (#864).

A follower's queued auction rows must not take the leader's mail, bank or
vendor errand: the pass asks the town slot instead. Runs on fakes.
"""

import ast
import asyncio
import pathlib
import types
import unittest

import auction

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
    encoding="utf-8"
)


def _load(names, namespace):
    wanted = [
        n
        for n in ast.walk(ast.parse(BRIDGE))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
    ]
    exec(  # noqa: S102 - bridge.py's own source
        compile(ast.Module(body=wanted, type_ignores=[]), "bridge.py", "exec"),
        namespace,
    )
    return namespace


async def _to_thread(fn, *a, **k):
    return fn(*a, **k)


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(msg % a if a else msg)


class _Slot:
    def __init__(self):
        self.adopted = []

    def adopt(self, **kw):
        self.adopted.append(kw)


_Sale = object


class _Self:
    def __init__(self, taken=True):
        self.slot = _Slot()
        self.claims = []
        self.taken = taken

    def _cohort_town_slot(self, cohort):
        return self.slot

    async def _claim_town_slot(self, claimant, character, aim, **kw):
        self.claims.append((claimant, character, aim, kw))
        return self.taken


class KeepAtAuctioneerTest(unittest.TestCase):
    def run_keep(self, column, taken=True):
        writes, log = [], _Log()
        ns = _load(
            ["_keep_at_auctioneer"],
            {
                "asyncio": types.SimpleNamespace(to_thread=_to_thread),
                "auction": auction,
                "professions": types.SimpleNamespace(
                    Errand=lambda **kw: types.SimpleNamespace(**kw)
                ),
                "_current_travel_npc": lambda name: column,
                "_write_trade_errand": lambda errand: writes.append(errand) or True,
                "_cohort_key": lambda cohort=None: "Grug",
                "_family_label": lambda cohort=None: "",
                "time": types.SimpleNamespace(monotonic=lambda: 1.0),
                "log": log,
            },
        )
        me = _Self(taken)
        asyncio.run(ns["_keep_at_auctioneer"](me, "Grug"))
        return me, writes, log

    def test_another_errand_is_kept_and_the_town_slot_asked(self):
        for column in ("mail", "vendor", "bank"):
            with self.subTest(column=column):
                me, writes, log = self.run_keep(column)
                self.assertEqual([], writes)
                self.assertEqual([], me.slot.adopted)
                self.assertEqual(
                    [("auction", "Grug", auction.AUCTIONEER_ROLE, {"cohort": "Grug"})],
                    me.claims,
                )
                self.assertEqual(1, len(log.lines))
                self.assertIn(column, log.lines[0])
                self.assertIn("Grug", log.lines[0])

    def test_the_log_says_whether_the_aim_was_taken(self):
        _, _, log = self.run_keep("mail", taken=False)
        self.assertIn("not taken", log.lines[0])

    def test_a_leader_at_the_auctioneer_aim_is_reasserted_and_adopted(self):
        me, writes, _ = self.run_keep(auction.AUCTIONEER_ROLE)
        self.assertEqual(1, len(writes))
        self.assertEqual(auction.AUCTIONEER_ROLE, writes[0].travel_npc)
        self.assertEqual([], me.claims)
        self.assertEqual(1, len(me.slot.adopted))
        self.assertEqual("auction", me.slot.adopted[0]["claimant"])


class ListWalkQueuesRows(unittest.TestCase):
    """`_auction_list_walk` queues listing rows, it does not only aim.

    A surplus material past the guild's target is carried by a member who is
    not at a counter, so `sales_by_house` drops it. The walk must queue its
    listing row at the leader's house (priced against the leader's house
    market, fair price included) rather than only aiming the leader.
    """

    def run_walk(self, sales=(), slot_taken=True, house_closed=False):
        queued = []
        log = _Log()
        ns = _load(
            ["_auction_list_walk"],
            {
                "asyncio": types.SimpleNamespace(to_thread=_to_thread),
                "auction": auction,
                "bag_pressure": types.SimpleNamespace(
                    family_town_run_needed=lambda names: 1
                ),
                "_log_changed": lambda claimant, lines, key=None, capped=False: None,
                "_fetch_free_slots": lambda names: {n: 8 for n in names},
                "_fetch_teams": lambda names: {name: "alliance" for name in names},
                "_recent_auction_keys": lambda minutes: set(),
                "_cohort_key": lambda cohort=None: "Grug",
                "_insert_auction": lambda holder, command, source="auction": (
                    queued.append((holder, command)) or 1
                ),
                "_family_label": lambda cohort=None: "",
                "GIVE_RETRY_MINUTES": 60,
                "log": log,
                "time": types.SimpleNamespace(monotonic=lambda: 1.0),
            },
        )
        me = _Self(slot_taken)

        async def listable(candidates, leader):
            return sales

        async def claim(claimant, character, aim, **kw):
            return slot_taken

        async def closed(house):
            return house_closed

        async def sell_house(house, candidates, seen, cohort):
            queued.append(("sell_house", house))
            return 0

        me._auction_listable_at_home = listable
        me._claim_town_slot = claim
        me._cohort_key = lambda cohort=None: "Grug"
        me._fetch_teams = lambda names: {name: "alliance" for name in names}
        me._house_is_closed = closed
        me._auction_sell_house = sell_house
        me._auction_urgency_spent = lambda cohort, kind, pressure: None

        candidate = {
            "holder": "Grog",
            "item_guid": 7,
            "entry": 2589,
            "label": "Linen Cloth",
            "quality": 1,
            "binding": "none",
            "quest_item": False,
            "recipient": "",
            "sell_price": 13,
            "count": 20,
            "fair_price": 546,
        }
        asyncio.run(
            ns["_auction_list_walk"](me, [candidate], ["Grug"], "Grug", cohort="Grug")
        )
        return queued, log

    def test_the_walk_queues_rows_instead_of_only_aiming(self):
        queued, _ = self.run_walk(sales=(_Sale(),))
        self.assertTrue(any("sell_house" in str(q) for q in queued))

    def test_no_sales_means_no_queue(self):
        queued, _ = self.run_walk(sales=())
        self.assertEqual([], queued)

    def test_slot_not_taken_means_no_queue(self):
        queued, _ = self.run_walk(sales=(_Sale(),), slot_taken=False)
        self.assertEqual([], queued)

    def test_closed_house_means_no_queue(self):
        queued, _ = self.run_walk(sales=(_Sale(),), house_closed=True)
        self.assertEqual([], queued)


if __name__ == "__main__":
    unittest.main()
