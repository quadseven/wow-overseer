"""A lost mail aim with nobody at a mailbox ends the pass without the settle wait.

wow-overseer#1141, split from #802 item 7. Since #477 the mail pass falls
through when the leader could not be aimed at a mailbox, so a taker already
standing at one still gets its takes queued. It then always called
`_settled_positions`, which reads, sleeps SETTLE_SECONDS (6 s) and reads again,
even when the first read already put no taker within TOWN_COUNTER_YARDS of the
mailbox: a 6 s wait on most passes for no row.

Pinned here on the same fakes as test_family_economy_parity: not aimed and no
taker in reach skips the settle read and writes nothing; not aimed and a taker
in reach still settles and queues that taker's take, as before.
"""

import asyncio
import types
import unittest

from test_family_economy_parity import (  # noqa: F401 - also sets up the pymysql stub
    HORDE,
    TheSelf,
    _Log,
    _mail_ns,
)


class _LostSlot(TheSelf):
    """The bridge with the town slot held by somebody else, recording every
    settle read it is asked for."""

    def __init__(self, world):
        super().__init__(world)
        self.settle_reads = []

    async def _claim_town_slot(
        self, claimant, character, aim, urgent=False, cohort=None, distance=None
    ):
        self.claims.append((claimant, character, aim, cohort))
        return False

    async def _settled_positions(self, names):
        self.settle_reads.append(list(names))
        return {n: {"map_id": 1, "at": n in self.world["standing"]} for n in names}


def _in_reach(spawn, where, yards):
    return bool(where) and where.get("at", False)


def _run(standing):
    world, log = {"standing": set(standing)}, _Log()
    me = _LostSlot(world)
    ns = _mail_ns(world, log)
    ns["_fetch_positions"] = lambda names: {
        n: {"map_id": 1, "at": n in world["standing"]} for n in names
    }
    ns["travel"] = types.SimpleNamespace(
        mailbox_aim=lambda spawn, map_id: types.SimpleNamespace(
            aim="at:1:1,1,1", refused=""
        ),
        spawn_in_reach=_in_reach,
    )
    ns["_mail_takes_in_reach"] = lambda takes, spawn, positions, yards, aim: [
        t for t in takes if _in_reach(spawn, positions.get(t.character), yards)
    ]
    me._mail_urgent = lambda *a: ns["_mail_urgent"](me, *a)
    asyncio.run(ns["_mail_once"](me, HORDE))
    return world, me, log


class ALostAimWithNobodyAtTheBoxDoesNotWait(unittest.TestCase):
    def test_no_taker_in_reach_skips_the_settle_read_and_writes_nothing(self):
        world, me, log = _run(standing=())
        self.assertEqual([("mail", "Zug", "at:1:1,1,1", "Zug")], me.claims)
        self.assertEqual([], me.settle_reads)
        self.assertNotIn("taken", world)
        self.assertTrue(
            any("could not be aimed at a mailbox" in ln for ln in log.lines),
            log.lines,
        )
        self.assertFalse(any("queued" in ln for ln in log.lines), log.lines)

    def test_a_taker_in_reach_still_settles_and_is_queued(self):
        world, me, log = _run(standing=("Uzza",))
        self.assertEqual([sorted(HORDE.names)], me.settle_reads)
        self.assertEqual(["Uzza"], world["taken"])
        self.assertTrue(
            any("could not be aimed at a mailbox" in ln for ln in log.lines),
            log.lines,
        )
        self.assertTrue(
            any(ln.startswith("mail: queued 1/5 take(s)") for ln in log.lines),
            log.lines,
        )


if __name__ == "__main__":
    unittest.main()
