"""Route around a death avoid disc instead of only refusing (wow-overseer#2540).

Synthetic fixtures: the same lava deaths as test_deathcells.py make one disc,
and the candidate waypoints are points shaped like surveyed creature spawns.
These tests pin the three cases the ticket names: a line that clears a disc
by luck needs no detour, a line that crosses one with a clear detour is
routed by way of the waypoint, and a line with no detour stays refused.
"""

import ast
import asyncio
import logging
import pathlib
import types
import unittest

import deathcells as dc

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")


def row(x, y, z=128.0, liquid="magma", killer="self", fell=0.0, map_id=0):
    return {
        "map_id": map_id,
        "x": x,
        "y": y,
        "z": z,
        "killer_type": killer,
        "liquid_type": liquid,
        "yards_fallen": fell,
    }


# The lava deaths of test_deathcells.py: one disc, centre about (-7806, -924),
# radius 100.
LAVA = [row(-7812, -928), row(-7814, -928), row(-7816, -930), row(-7780, -910)]
STORMWIND = {"map_id": 0, "x": -8800.0, "y": 600.0}
PLAGUELANDS = {"map_id": 0, "x": -6800.0, "y": -2450.0}

# Surveyed points shaped like creature spawns, told apart by where they stand
# relative to the disc on the Stormwind -> Plaguelands line.
SIDE = {"map_id": 0, "x": -7500.0, "y": -500.0, "z": 40.0}  # both legs clear
FAR = {"map_id": 0, "x": -6000.0, "y": 500.0, "z": 40.0}  # clear, but longer
BEHIND = {"map_id": 0, "x": -8600.0, "y": 300.0, "z": 40.0}  # leg two crosses
INSIDE = {"map_id": 0, "x": -7805.0, "y": -924.0, "z": 0.0}  # in the disc


class ADetourAroundADisc(unittest.TestCase):
    def setUp(self):
        self.discs = dc.discs(LAVA)

    def test_a_line_that_clears_a_disc_by_luck_needs_no_detour(self):
        north = {"map_id": 0, "x": -8800.0, "y": 2000.0}
        east = {"map_id": 0, "x": -5000.0, "y": 3000.0}
        self.assertIsNone(dc.crossing(self.discs, north, east))
        self.assertIsNone(dc.detour(self.discs, north, east, [SIDE]))

    def test_a_crossing_line_with_a_clear_detour_gets_the_waypoint(self):
        waypoint = dc.detour(self.discs, STORMWIND, PLAGUELANDS, [SIDE])
        self.assertIsNotNone(waypoint)
        self.assertEqual(
            (waypoint["x"], waypoint["y"], waypoint["z"]),
            (SIDE["x"], SIDE["y"], SIDE["z"]),
        )
        self.assertIsNone(dc.crossing(self.discs, STORMWIND, waypoint))
        self.assertIsNone(dc.crossing(self.discs, waypoint, PLAGUELANDS))

    def test_the_shortest_clear_route_wins(self):
        waypoint = dc.detour(self.discs, STORMWIND, PLAGUELANDS, [FAR, SIDE])
        self.assertEqual((waypoint["x"], waypoint["y"]), (SIDE["x"], SIDE["y"]))

    def test_a_point_the_family_died_on_is_never_a_waypoint(self):
        self.assertIsNone(dc.detour(self.discs, STORMWIND, PLAGUELANDS, [INSIDE]))

    def test_a_waypoint_is_not_chosen_from_inside_a_disc_the_walker_stands_in(
        self,
    ):
        # A second disc sits on the road north; the walker already stands in
        # the lava disc, so `crossing` alone would let a waypoint inside that
        # same disc serve (it never judges ground the walker stands on). The
        # detour must still refuse to stand the walk on ground the family
        # died on.
        discs = dc.discs(LAVA + [row(-8125, 225), row(-8123, 223)])
        self.assertEqual(len(discs), 2)
        standing = {"map_id": 0, "x": -7890.0, "y": -970.0}  # inside the lava
        inside = {"map_id": 0, "x": -7890.0, "y": -950.0, "z": 40.0}  # also in
        north = {"map_id": 0, "x": -8100.0, "y": 900.0}
        self.assertIsNotNone(dc.crossing(discs, standing, north))
        self.assertIsNone(dc.detour(discs, standing, north, [inside]))

    def test_a_point_whose_second_leg_crosses_is_not_a_detour(self):
        self.assertIsNone(dc.detour(self.discs, STORMWIND, PLAGUELANDS, [BEHIND]))

    def test_no_candidates_means_no_detour(self):
        self.assertIsNone(dc.detour(self.discs, STORMWIND, PLAGUELANDS, []))
        self.assertIsNone(dc.detour(self.discs, STORMWIND, PLAGUELANDS, None))

    def test_a_goal_inside_the_disc_has_no_detour(self):
        goal = {"map_id": 0, "x": -7814.0, "y": -929.0}
        self.assertIsNone(dc.detour(self.discs, STORMWIND, goal, [SIDE]))

    def test_a_candidate_on_another_map_is_not_a_waypoint(self):
        elsewhere = dict(SIDE, map_id=1)
        self.assertIsNone(dc.detour(self.discs, STORMWIND, PLAGUELANDS, [elsewhere]))

    def test_a_point_that_cannot_be_read_is_not_a_waypoint(self):
        self.assertIsNone(
            dc.detour(self.discs, STORMWIND, PLAGUELANDS, [{"map_id": 0}, None])
        )


class CrossingsNamesEveryDiscInTheWay(unittest.TestCase):
    def test_the_one_disc_on_the_line_is_named(self):
        discs = dc.discs(LAVA)
        hits = dc.crossings(discs, STORMWIND, PLAGUELANDS)
        self.assertEqual(hits, discs)

    def test_two_discs_on_one_line_are_both_named(self):
        rows = [row(1000, 0), row(1002, 2), row(2000, 0), row(2002, -2)]
        discs = dc.discs(rows)
        self.assertEqual(len(discs), 2)
        hits = dc.crossings(
            discs,
            {"map_id": 0, "x": 0.0, "y": 0.0},
            {"map_id": 0, "x": 3000.0, "y": 0.0},
        )
        self.assertEqual(hits, discs)

    def test_a_clear_line_crosses_nothing(self):
        discs = dc.discs(LAVA)
        north = {"map_id": 0, "x": -8800.0, "y": 2000.0}
        east = {"map_id": 0, "x": -5000.0, "y": 3000.0}
        self.assertEqual(dc.crossings(discs, north, east), [])


class _Reached(Exception):
    """Raised by the stub the door calls once the death check has passed."""


def _door(refusal, detour=None, with_detour=True, crossed=()):
    """The real `_claim_town_slot`, run with stubs, returning (fn, calls).

    Mirrors the harness in test_deathcells.py: `_current_travel_npc` stands
    in for everything past the death check and raises once it is reached.
    `detour` is the waypoint aim the detour helper answers, or "" for none;
    `with_detour=False` leaves the helper out of the namespace entirely, as
    the adapter tests that load the door in isolation see it.
    """
    tree = ast.parse(BRIDGE)
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_claim_town_slot"
    )
    module = ast.Module(body=[node], type_ignores=[])
    calls = []

    async def to_thread(fn, *args):
        return fn(*args)

    def reached(_leader):
        raise _Reached

    ns = {
        "asyncio": types.SimpleNamespace(to_thread=to_thread),
        "log": logging.getLogger("test_deathcells_detour"),
        "_head_now": lambda: "Lead",
        "_cohort_leader": lambda key: "Lead",
        "_current_travel_npc": reached,
        "_write_trade_errand": lambda *_a: calls.append("write"),
    }
    if refusal is not None:
        ns["_death_disc_refusal"] = lambda leader, aim: refusal
    if with_detour:
        ns["_death_disc_detour"] = lambda leader, aim: (detour or "", crossed)
    me = types.SimpleNamespace(_cohort_town_slot=lambda cohort: None)
    exec(compile(ast.fix_missing_locations(module), "bridge", "exec"), ns)
    return ns["_claim_town_slot"], me, calls


class TheDoorDetoursAroundADisc(unittest.TestCase):
    def go(self, refusal, detour=None, with_detour=True, aim="at:0:1.0,2.0,3.0"):
        fn, me, calls = _door(refusal, detour=detour, with_detour=with_detour)
        try:
            return asyncio.run(fn(me, "gather", "Lead", aim)), calls
        except _Reached:
            return "reached", calls

    def test_a_refused_aim_with_a_waypoint_goes_on_to_the_slot(self):
        got, _calls = self.go("crosses lava", detour="at:0:-7500.0,-500.0,40.0")
        self.assertEqual(got, "reached")

    def test_a_refused_aim_with_no_waypoint_is_not_written(self):
        got, calls = self.go("crosses lava", detour="")
        self.assertIs(got, False)
        self.assertEqual(calls, [])

    def test_no_detour_helper_means_the_refusal_stands_as_today(self):
        got, calls = self.go("crosses lava", with_detour=False)
        self.assertIs(got, False)
        self.assertEqual(calls, [])

    def test_the_waypoint_is_named_in_the_log(self):
        fn, me, _calls = _door("crosses lava", detour="at:0:-7500.0,-500.0,40.0")
        with self.assertLogs("test_deathcells_detour", level="WARNING") as logs:
            with self.assertRaises(_Reached):
                asyncio.run(fn(me, "gather", "Lead", "at:0:1.0,2.0,3.0"))
        self.assertTrue(
            any("at:0:-7500.0,-500.0,40.0" in line for line in logs.output),
            logs.output,
        )

    def test_a_failed_detour_names_every_disc_in_the_way(self):
        discs = dc.discs(LAVA + [row(-8125, 225), row(-8123, 223)])
        self.assertEqual(len(discs), 2)
        fn, me, _calls = _door("crosses lava", detour="", crossed=tuple(discs))
        with self.assertLogs("test_deathcells_detour", level="WARNING") as logs:
            got = asyncio.run(fn(me, "gather", "Lead", "at:0:1.0,2.0,3.0"))
        self.assertIs(got, False)
        text = "\n".join(logs.output)
        self.assertIn("also crosses", text)
        self.assertIn(discs[1].said(), text)

    def test_the_helper_the_door_looks_up_is_a_module_level_function(self):
        top = {n.name for n in ast.parse(BRIDGE).body if isinstance(n, ast.FunctionDef)}
        self.assertIn("_death_disc_detour", top)


if __name__ == "__main__":
    unittest.main()
