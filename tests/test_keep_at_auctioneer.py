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


if __name__ == "__main__":
    unittest.main()
