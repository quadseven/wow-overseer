"""No auctioneer in reach is not an auction errand.

A leader on a map whose auctioneers are all the other side's, or all a
continent away, was aimed at the `auctioneer` keyword anyway, because the
auction passes asked only whether the map has any auctioneer at all. The
module released the aim as soon as it read it and the pass wrote it again on
its next cycle, so the family's one travel column and the town slot's lease on
it were held for a walk that could never start, and the leader could not be
sent back for members left behind. The door now refuses the keyword when the
spawn table shows no counter of the family's side within a town walk, and
remembers the refusal for a bounded time.

bridge.py imports discord and cannot be imported here, so its helper is
loaded from source and its door is read as text.
"""

import ast
import pathlib
import types
import unittest

import auction
import bag_pressure

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
    encoding="utf-8"
)

MAP = 1


def _row(entry, faction, yards, map_id=MAP):
    return {
        "entry": entry,
        "name": "counter %d" % entry,
        "faction": faction,
        "map_id": map_id,
        "yards": yards,
    }


# Four counters on the map, every one the other side's or neutral but a
# continent away, as the module reported it for the stuck leader.
HORDE_ONLY_FAR = [_row(1, 29, 16000.0), _row(2, 68, 17000.0), _row(3, 104, 18000.0)]
ALLIANCE_NEAR = [_row(4, 12, 800.0)]
ALLIANCE_FAR = [_row(5, 12, 18000.0)]


class TheKeywordResolvesOnlyWithinATownWalk(unittest.TestCase):
    def test_counters_all_of_the_other_side_do_not_resolve(self):
        ok, why = auction.counter_in_reach("alliance", HORDE_ONLY_FAR, map_id=MAP)
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_a_usable_counter_far_beyond_a_town_walk_does_not_resolve(self):
        ok, why = auction.counter_in_reach("alliance", ALLIANCE_FAR, map_id=MAP)
        self.assertFalse(ok)
        self.assertIn("18000", why)

    def test_a_counter_within_a_town_walk_resolves(self):
        self.assertEqual(
            (True, ""), auction.counter_in_reach("alliance", ALLIANCE_NEAR, map_id=MAP)
        )

    def test_a_neutral_counter_within_a_town_walk_resolves(self):
        rows = [_row(6, 474, 300.0)]
        self.assertEqual(
            (True, ""), auction.counter_in_reach("horde", rows, map_id=MAP)
        )

    def test_a_leader_whose_side_is_unknown_is_not_refused_on_a_guess(self):
        self.assertEqual(
            (True, ""), auction.counter_in_reach("", HORDE_ONLY_FAR, map_id=MAP)
        )


class TheRefusalIsRemembered(unittest.TestCase):
    def test_it_stands_for_the_bound_and_then_lapses(self):
        memory = auction.CounterRefusals(seconds=600)
        self.assertTrue(memory.remember("L", MAP, "none in reach", now=0.0))
        self.assertEqual("none in reach", memory.standing("L", MAP, 599.0))
        self.assertEqual("", memory.standing("L", MAP, 600.0))

    def test_it_is_not_carried_to_another_map(self):
        memory = auction.CounterRefusals(seconds=600)
        memory.remember("L", MAP, "none in reach", now=0.0)
        self.assertEqual("", memory.standing("L", 0, 10.0))

    def test_it_is_said_once_while_it_stands(self):
        memory = auction.CounterRefusals(seconds=600)
        self.assertTrue(memory.remember("L", MAP, "x", now=0.0))
        self.assertFalse(memory.remember("L", MAP, "x", now=30.0))
        self.assertTrue(memory.remember("L", MAP, "x", now=700.0))

    def test_forgetting_clears_it(self):
        memory = auction.CounterRefusals(seconds=600)
        memory.remember("L", MAP, "x", now=0.0)
        memory.forget("L")
        self.assertEqual("", memory.standing("L", MAP, 1.0))


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a):
        self.lines.append(msg % a if a else msg)


def _load_helper(rows, team="alliance", clock=None):
    tree = ast.parse(BRIDGE)
    wanted = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_auctioneer_reach_refusal"
    ]
    assert len(wanted) == 1
    reads = {"spawns": 0}

    def spawns(here):
        reads["spawns"] += 1
        return rows

    log = _Log()
    ns = {
        "auction": auction,
        "bag_pressure": bag_pressure,
        "time": types.SimpleNamespace(monotonic=lambda: clock[0]),
        "log": log,
        "_AUCTION_COUNTER_REFUSALS": auction.CounterRefusals(),
        "_fetch_bag_trip_facts": lambda names: [
            {"name": "Leader", "map_id": MAP, "pos_x": 0.0, "pos_y": 0.0}
        ],
        "_fetch_auctioneer_spawns": spawns,
        "_fetch_teams": lambda names: {"Leader": team},
    }
    exec(  # noqa: S102 - bridge.py's own source
        compile(ast.Module(body=wanted, type_ignores=[]), "bridge.py", "exec"), ns
    )
    return ns["_auctioneer_reach_refusal"], reads, log


class TheDoorRefusesTheKeyword(unittest.TestCase):
    def test_a_leader_with_no_counter_in_reach_is_refused_and_it_is_said_once(self):
        clock = [0.0]
        refusal, reads, log = _load_helper(HORDE_ONLY_FAR, clock=clock)
        self.assertTrue(refusal("Leader", auction.AUCTIONEER_ROLE))
        clock[0] = 60.0
        self.assertTrue(refusal("Leader", auction.AUCTIONEER_ROLE))
        self.assertEqual(1, len(log.lines))

    def test_the_spawn_table_is_not_read_again_inside_the_bound(self):
        clock = [0.0]
        refusal, reads, _ = _load_helper(HORDE_ONLY_FAR, clock=clock)
        for second in (0.0, 5.0, 300.0, 599.0):
            clock[0] = second
            refusal("Leader", auction.AUCTIONEER_ROLE)
        self.assertEqual(1, reads["spawns"])
        clock[0] = 601.0
        refusal("Leader", auction.AUCTIONEER_ROLE)
        self.assertEqual(2, reads["spawns"])

    def test_a_leader_with_a_counter_in_reach_is_not_refused(self):
        refusal, _, log = _load_helper(ALLIANCE_NEAR, clock=[0.0])
        self.assertEqual("", refusal("Leader", auction.AUCTIONEER_ROLE))
        self.assertEqual([], log.lines)

    def test_only_the_bare_keyword_is_judged(self):
        refusal, reads, _ = _load_helper(HORDE_ONLY_FAR, clock=[0.0])
        for aim in ("vendor", "8723", "at:1:1.0,2.0,3.0"):
            self.assertEqual("", refusal("Leader", aim))
        self.assertEqual(0, reads["spawns"])

    def test_an_unreadable_spawn_table_is_not_a_refusal(self):
        refusal, _, _ = _load_helper(None, clock=[0.0])
        self.assertEqual("", refusal("Leader", auction.AUCTIONEER_ROLE))

    def test_the_town_slot_door_asks_before_it_claims(self):
        door = BRIDGE[BRIDGE.index("async def _claim_town_slot") :]
        door = door[: door.index("decision = self._claims.want_column(")]
        self.assertIn('globals().get("_auctioneer_reach_refusal")', door)
        self.assertIn("unreachable, leader, aim", door)


if __name__ == "__main__":
    unittest.main()
