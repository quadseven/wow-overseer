"""A backpack read error is a read error, not the end of the bag pass (#1062).

The pre-ship review of the bridge (infra#5384) found that `_hand_bags_once`
read the backpack inline: a MySQL error on that one read raised out of the
bag pass, and with it out of the materials pass that calls it, so no bag and
no reagent moved. Unread, `bag_upgrade.members_from_rows` already counts
every backpack as full; the pass says the read failed and goes on with that.

The bridge's own `_hand_bags_once` source is run against fakes, as
test_campaign_queue does for the queue pass.
"""

import asyncio
import types
import unittest

from test_campaign_queue import _load, _Log  # sets up the pymysql stub

import bag_upgrade  # noqa: E402
import pymysql  # noqa: E402  (the stub test_decree_order installs)

GIVE = "give"


def _row(holder, guid, slot, slots=8):
    """One container on `holder`, at backpack-level `slot` (bag 0)."""
    return dict(holder=holder, guid=guid, name="Bag %d" % guid, slots=slots,
                bag=0, slot=slot, used=0, entry=4496, subclass=0)


# Grog wears four bags and carries a fifth in his backpack; Ugga wears none.
ROWS = [_row("Grog", g, s) for g, s in ((1, 19), (2, 20), (3, 21), (4, 22))]
ROWS.append(_row("Grog", 5, bag_upgrade.BACKPACK_POSITIONS[0]))


def _bag_pass(backpack):
    """Run the bridge's bag pass once; (log lines, members seen, gives)."""
    log = _Log()
    seen, gives = [], []

    def insert_give(move, command):
        gives.append((move.giver, move.receiver, command))
        return 1

    ns = _load(
        ["_hand_bags_once"],
        {
            "asyncio": asyncio,
            "bag_upgrade": bag_upgrade,
            "pymysql": pymysql,
            "log": log,
            "handover": types.SimpleNamespace(
                GIVE=GIVE,
                spots=lambda rows: {},
                verdict=lambda g, r, where: types.SimpleNamespace(verb=GIVE, why=""),
                waiting=lambda *a: "waits",
            ),
            "_fetch_bag_state": lambda names: [dict(r) for r in ROWS],
            "_fetch_backpack_used": backpack,
            "_fetch_positions": lambda names: [],
            "_recent_give_keys": lambda minutes: set(),
            "_insert_bag_give": insert_give,
            "_log_capped": lambda tag, lines: None,
            "GIVE_RETRY_MINUTES": 30,
        },
    )

    async def equip_own(members):
        seen.extend(members)
        return set()

    me = types.SimpleNamespace(_equip_own_bags=equip_own)
    asyncio.run(ns["_hand_bags_once"](me, ["Grog", "Ugga"]))
    return log.lines, seen, gives


class ABackpackReadErrorIsSaid(unittest.TestCase):
    def test_the_read_error_is_logged_and_the_pass_goes_on(self):
        def refused(names):
            raise pymysql.err.MySQLError(2013, "Lost connection to MySQL server")

        lines, seen, gives = _bag_pass(refused)
        said = [ln for ln in lines if "backpack read failed" in ln]
        self.assertEqual(1, len(said), lines)
        self.assertIn("Lost connection", said[0])
        # Unread, every backpack counts as full, and the hand-over still runs.
        self.assertEqual({"Grog", "Ugga"}, {m.name for m in seen})
        self.assertEqual({0}, {m.backpack_free for m in seen})
        self.assertEqual([("Grog", "Ugga")], [g[:2] for g in gives])

    def test_a_read_backpack_is_used_as_before(self):
        lines, seen, gives = _bag_pass(lambda names: {"Grog": 1})
        self.assertFalse([ln for ln in lines if "backpack read failed" in ln])
        free = {m.name: m.backpack_free for m in seen}
        self.assertEqual(len(bag_upgrade.BACKPACK_POSITIONS) - 1, free["Grog"])
        self.assertEqual([("Grog", "Ugga")], [g[:2] for g in gives])


if __name__ == "__main__":
    unittest.main()
