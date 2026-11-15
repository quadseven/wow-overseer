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
import time
import types
import unittest

import deathcells as dc
import places
import situation
import towntrip
import travel

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


class ADetourHasALengthCeiling(unittest.TestCase):
    """A route that wanders far past the direct walk is no detour (#2540):
    the picker takes the shortest clear route among the candidates it is
    given, so without a ceiling a candidate far off the line is accepted
    however long the walk by way of it becomes."""

    def setUp(self):
        # One disc on the straight line from (0, 0) to (1000, 0), centre
        # about (501, 1), radius 100; the direct walk is 1000 yards.
        self.discs = dc.discs([row(500, 0), row(502, 2)])
        self.assertEqual(len(self.discs), 1)
        self.start = {"map_id": 0, "x": 0.0, "y": 0.0}
        self.goal = {"map_id": 0, "x": 1000.0, "y": 0.0}
        # Both legs clear the disc; the total walk is about 1720 yards,
        # inside twice the direct walk.
        self.near = {"map_id": 0, "x": 500.0, "y": 700.0, "z": 40.0}
        # Both legs clear the disc too; the total walk is about 2150 yards,
        # past twice the direct walk.
        self.far = {"map_id": 0, "x": 500.0, "y": 950.0, "z": 40.0}

    def test_a_route_past_twice_the_direct_walk_is_no_detour(self):
        self.assertIsNone(dc.detour(self.discs, self.start, self.goal, [self.far]))

    def test_a_route_inside_twice_the_direct_walk_still_serves(self):
        waypoint = dc.detour(self.discs, self.start, self.goal, [self.near])
        self.assertIsNotNone(waypoint)
        self.assertEqual((waypoint["x"], waypoint["y"]), (500.0, 700.0))

    def test_the_ceiling_falls_back_to_the_shorter_clear_route(self):
        waypoint = dc.detour(self.discs, self.start, self.goal, [self.far, self.near])
        self.assertEqual((waypoint["x"], waypoint["y"]), (500.0, 700.0))


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


def _cap_constants():
    """The real `_DETOUR_CAP` / `_DETOUR_WINDOW_SECONDS` from bridge.py."""
    consts = {}
    for top in ast.parse(BRIDGE).body:
        if (
            isinstance(top, ast.Assign)
            and isinstance(top.targets[0], ast.Name)
            and top.targets[0].id in ("_DETOUR_CAP", "_DETOUR_WINDOW_SECONDS")
        ):
            exec(
                compile(ast.Module(body=[top], type_ignores=[]), "bridge", "exec"),
                consts,
            )
    return consts


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
        "time": time,
        "_head_now": lambda: "Lead",
        "_cohort_leader": lambda key: "Lead",
        "_current_travel_npc": reached,
        "_write_trade_errand": lambda *_a: calls.append("write"),
    }
    ns.update(_cap_constants())
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


class _MySQLError(Exception):
    """The fake cursor's MySQL error; the helper catches it as pymysql's."""


class _DetourCursor:
    """Answers the helper's two reads: the walker's race (a `characters`
    read) and the ring of spawns around the disc (anything else)."""

    def __init__(self, race_rows=(), spawn_rows=(), fail_spawn=False):
        self.race_rows = list(race_rows)
        self.spawn_rows = list(spawn_rows)
        self.fail_spawn = fail_spawn
        self.calls = []
        self.rows = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "FROM characters" in sql:
            self.rows = list(self.race_rows)
        elif self.fail_spawn:
            raise _MySQLError(1146, "table does not exist")
        else:
            self.rows = list(self.spawn_rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _DetourConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _detour_helper(cursor):
    """The real `_death_disc_detour` and its `_DETOUR_*` constants, run
    against the fake cursor, with the disc and position reads stubbed to
    the lava disc and the Stormwind end of the walk."""
    tree = ast.parse(BRIDGE)
    ns = {"towntrip": towntrip}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.startswith("_DETOUR_")
        ):
            exec(
                compile(ast.Module(body=[node], type_ignores=[]), "bridge", "exec"), ns
            )
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_death_disc_detour"
    )
    ns.update(
        places=places,
        deathcells=dc,
        travel=travel,
        situation=situation,
        log=logging.getLogger("test_deathcells_detour"),
        pymysql=types.SimpleNamespace(
            err=types.SimpleNamespace(MySQLError=_MySQLError)
        ),
        _connect=lambda: _DetourConn(cursor),
        _fetch_death_discs=lambda: dc.discs(LAVA),
        _fetch_positions=lambda names: {
            "Lead": {"map_id": 0, "pos_x": -8800.0, "pos_y": 600.0}
        },
    )
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "bridge", "exec"), ns)
    return ns["_death_disc_detour"], ns


class TheDetourHelperReadsSafeSurveyedGround(unittest.TestCase):
    """`_death_disc_detour` itself (#2540): the SQL, the ring, the faction
    and rank of the spawns it weighs, and the aim it builds from the winner.
    The walker is an Orc (race 2), so the family's side is the Horde mask."""

    AIM = "at:0:-6800.0,-2450.0,128.0"

    def go(self, race_rows=({"race": 2},), spawn_rows=(), fail_spawn=False):
        cursor = _DetourCursor(race_rows, spawn_rows, fail_spawn)
        fn, consts = _detour_helper(cursor)
        self.cursor = cursor
        self.consts = consts
        return fn("Lead", self.AIM)

    def test_the_spawn_sql_reads_only_normal_rank_spawns_and_their_faction(self):
        _fn, consts = _detour_helper(_DetourCursor())
        sql = consts["_DETOUR_SPAWN_SQL"]
        self.assertIn("ct.`rank` = 0", sql)
        self.assertIn(
            "LEFT JOIN acore_world.factiontemplate_dbc ft ON ft.ID = ct.faction",
            sql,
        )
        self.assertIn("ft.EnemyGroup AS enemy_group", sql)
        self.assertIn(towntrip.REAL_SPAWN_SQL, sql)
        # The faction filter runs in the query, before the nearest-500
        # limit: a Python-only filter would never see a safe spawn past
        # 500 hostile or unread ones.
        self.assertIn("ft.EnemyGroup IS NOT NULL", sql)
        self.assertEqual(sql.count("(ft.EnemyGroup & %s) = 0"), 2)

    def test_the_ring_is_the_first_discs_and_the_aim_is_the_spawns_own(self):
        waypoint, crossed = self.go(spawn_rows=[dict(SIDE, enemy_group=0)])
        self.assertEqual(
            waypoint, travel.ground_aim(0, SIDE["x"], SIDE["y"], SIDE["z"])
        )
        self.assertEqual(len(crossed), 1)
        sql, params = self.cursor.calls[-1]
        self.assertEqual(sql, self.consts["_DETOUR_SPAWN_SQL"])
        disc = crossed[0]
        self.assertEqual(params[0], disc.map_id)
        self.assertEqual(params[1], situation.PLAYER_MASK)
        self.assertEqual(params[2], situation.HORDE_MASK)
        self.assertEqual(params[5], disc.radius**2)
        self.assertEqual(
            params[8], (disc.radius + self.consts["_DETOUR_REACH_YARDS"]) ** 2
        )
        self.assertEqual(params[-1], self.consts["_DETOUR_CANDIDATE_LIMIT"])

    def test_a_spawn_that_attacks_the_walkers_side_is_not_a_waypoint(self):
        rows = [
            dict(SIDE, enemy_group=4),  # attacks the Horde: the short route
            dict(FAR, enemy_group=2),  # attacks only the Alliance: safe here
        ]
        waypoint, _crossed = self.go(spawn_rows=rows)
        self.assertEqual(waypoint, travel.ground_aim(0, FAR["x"], FAR["y"], FAR["z"]))

    def test_a_spawn_that_attacks_every_player_is_not_a_waypoint(self):
        rows = [dict(SIDE, enemy_group=1), dict(FAR, enemy_group=0)]
        waypoint, _crossed = self.go(spawn_rows=rows)
        self.assertEqual(waypoint, travel.ground_aim(0, FAR["x"], FAR["y"], FAR["z"]))

    def test_a_spawn_whose_faction_cannot_be_read_is_not_a_waypoint(self):
        waypoint, crossed = self.go(spawn_rows=[dict(SIDE, enemy_group=None)])
        self.assertEqual(waypoint, "")
        self.assertEqual(len(crossed), 1)

    def test_no_detour_when_the_walkers_side_cannot_be_read(self):
        waypoint, crossed = self.go(
            race_rows=(), spawn_rows=[dict(SIDE, enemy_group=0)]
        )
        self.assertEqual(waypoint, "")
        self.assertEqual(len(crossed), 1)
        # Only the race read ran: with no side proven, the ring is not read.
        self.assertEqual(len(self.cursor.calls), 1)

    def test_a_spawn_table_the_world_image_lacks_still_degrades(self):
        waypoint, crossed = self.go(
            spawn_rows=[dict(SIDE, enemy_group=0)], fail_spawn=True
        )
        self.assertEqual(waypoint, "")
        self.assertEqual(len(crossed), 1)


def _door_live(refuse, detour):
    """The real `_claim_town_slot` with a live refusal and detour, a fake
    clock, and the real `_DETOUR_CAP` / `_DETOUR_WINDOW_SECONDS` constants.
    Returns (fn, me, consts); the same `me` is reused across asks so the
    door's own per-errand state carries the way it does in the process."""
    tree = ast.parse(BRIDGE)
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_claim_town_slot"
    )
    module = ast.Module(body=[node], type_ignores=[])
    consts = _cap_constants()
    clock = [1000.0]

    async def to_thread(fn, *args):
        return fn(*args)

    def reached(_leader):
        raise _Reached

    ns = {
        "asyncio": types.SimpleNamespace(to_thread=to_thread),
        "log": logging.getLogger("test_deathcells_detour"),
        "time": types.SimpleNamespace(monotonic=lambda: clock[0]),
        "_head_now": lambda: "Lead",
        "_cohort_leader": lambda key: "Lead",
        "_current_travel_npc": reached,
        "_write_trade_errand": lambda *_a: None,
        "_death_disc_refusal": refuse,
        "_death_disc_detour": detour,
    }
    ns.update(consts)
    me = types.SimpleNamespace(_cohort_town_slot=lambda cohort: None)
    exec(compile(ast.fix_missing_locations(module), "bridge", "exec"), ns)
    return ns["_claim_town_slot"], me, consts, clock


class TheDoorCapsDetoursPerErrand(unittest.TestCase):
    """Leg two is judged from wherever the leader ends up, so without a cap
    one errand can be offered waypoint after waypoint and never arrive
    (#2540). The budget is the door's own count for the errand."""

    AIM = "at:0:1.0,2.0,3.0"

    def build(self, refusal="crosses lava"):
        state = {"refusal": refusal}
        detour_calls = []

        def detour(leader, aim):
            detour_calls.append(aim)
            return "at:0:-7500.0,-500.0,40.0", ()

        fn, me, consts, clock = _door_live(lambda leader, aim: state["refusal"], detour)
        self.assertIn("_DETOUR_CAP", consts)
        self.assertIn("_DETOUR_WINDOW_SECONDS", consts)
        return fn, me, consts, clock, state, detour_calls

    def ask(self, fn, me, aim=None):
        try:
            return asyncio.run(fn(me, "gather", "Lead", aim or self.AIM))
        except _Reached:
            return "reached"

    def test_an_errand_is_routed_around_only_so_many_times(self):
        fn, me, consts, _clock, _state, calls = self.build()
        cap = consts["_DETOUR_CAP"]
        for _ in range(cap):
            self.assertEqual(self.ask(fn, me), "reached")
        self.assertEqual(len(calls), cap)
        with self.assertLogs("test_deathcells_detour", level="WARNING") as logs:
            self.assertIs(self.ask(fn, me), False)
        # The door stops asking the helper once the budget is spent, and
        # the refusal it logs says why.
        self.assertEqual(len(calls), cap)
        self.assertTrue(
            any("already been routed around" in line for line in logs.output),
            logs.output,
        )

    def test_a_clean_ask_refills_the_budget(self):
        fn, me, consts, _clock, state, calls = self.build()
        cap = consts["_DETOUR_CAP"]
        for _ in range(cap):
            self.assertEqual(self.ask(fn, me), "reached")
        self.assertIs(self.ask(fn, me), False)
        state["refusal"] = ""
        self.assertEqual(self.ask(fn, me), "reached")
        state["refusal"] = "crosses lava"
        self.assertEqual(self.ask(fn, me), "reached")
        self.assertEqual(len(calls), cap + 1)

    def test_the_budget_is_per_leader_and_aim(self):
        fn, me, consts, _clock, _state, calls = self.build()
        cap = consts["_DETOUR_CAP"]
        for _ in range(cap):
            self.assertEqual(self.ask(fn, me), "reached")
        self.assertIs(self.ask(fn, me), False)
        self.assertEqual(self.ask(fn, me, aim="at:0:9.0,9.0,9.0"), "reached")
        self.assertEqual(len(calls), cap + 1)

    def test_the_budget_comes_back_after_the_window(self):
        fn, me, consts, clock, _state, calls = self.build()
        cap = consts["_DETOUR_CAP"]
        for _ in range(cap):
            self.assertEqual(self.ask(fn, me), "reached")
        self.assertIs(self.ask(fn, me), False)
        clock[0] += consts["_DETOUR_WINDOW_SECONDS"] + 1.0
        self.assertEqual(self.ask(fn, me), "reached")
        self.assertEqual(len(calls), cap + 1)


if __name__ == "__main__":
    unittest.main()
