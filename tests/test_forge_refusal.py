"""The forge pass does not walk the leader to a Forge it cannot survive (#2538).

On the dev realm the leader died three times to one Scarlet Enchanter walking
to the nearest Forge on the whole map. These tests pin the refusals (too far,
a split family, hostile ground, a death disc), that a near safe Forge is aimed
as before, that a refusal waits and says why in one line, and that the town
stop's own branch is untouched.
"""

import ast
import asyncio
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import levelroute  # noqa: E402
import travel  # noqa: E402

BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")


def cell(x, y, level, elite=False, n=1, map_id=0):
    return types.SimpleNamespace(
        map_id=map_id, x=float(x), y=float(y), level=level, elite=elite, n=n
    )


# A Forge spawn row as `_FORGE_SQL` returns it, 300 yards from the leader.
FORGE = {
    "map_id": 0,
    "x": 1548.7,
    "y": -5387.1,
    "z": 78.2,
    "radius": 10,
    "d2": 300.0**2,
}
LEADER = {"map_id": 0, "x": 1548.7, "y": -5087.1}
HOME = {
    "Grug": LEADER,
    "Ugga": {"map_id": 0, "x": 1560.0, "y": -5090.0},
    "Grog": {"map_id": 0, "x": 1540.0, "y": -5080.0},
}


def refusal(**over):
    args = dict(spawn=FORGE, leader="Grug", positions=HOME, hostile=(), level=60)
    args.update(over)
    return travel.forge_refusal(**args)


class DistanceAndTheFamily(unittest.TestCase):
    def test_a_near_forge_in_quiet_ground_is_not_refused(self):
        self.assertEqual(refusal(), "")

    def test_a_forge_past_the_walking_budget_is_refused_with_its_distance(self):
        far = dict(FORGE, d2=(travel.FORGE_WALK_YARDS + 500.0) ** 2)
        why = refusal(spawn=far)
        self.assertIn("Forge", why)
        self.assertIn("%d yards" % (travel.FORGE_WALK_YARDS + 500), why)

    def test_a_forge_exactly_at_the_budget_is_still_walked(self):
        edge = dict(FORGE, d2=travel.FORGE_WALK_YARDS**2)
        self.assertEqual(refusal(spawn=edge), "")

    def test_a_leader_far_from_its_members_is_not_walked_away(self):
        split = dict(HOME)
        split["Ugga"] = {"map_id": 0, "x": 1548.0, "y": -2000.0}
        split["Grog"] = {"map_id": 1, "x": 0.0, "y": 0.0}
        why = refusal(positions=split)
        self.assertIn("split", why)

    def test_one_straggler_does_not_stop_the_errand(self):
        one = dict(HOME)
        one["Grog"] = {"map_id": 0, "x": 1548.0, "y": -2000.0}
        self.assertEqual(refusal(positions=one), "")

    def test_a_leader_alone_in_the_snapshot_is_not_called_split(self):
        self.assertEqual(refusal(positions={"Grug": LEADER}), "")

    def test_no_leader_position_judges_nothing(self):
        self.assertEqual(refusal(positions={}), "")


class HostileGround(unittest.TestCase):
    def test_a_hostile_elite_at_the_leader_level_beside_the_forge_refuses(self):
        why = refusal(hostile=[cell(1500, -5400, 60, elite=True)])
        self.assertIn("elite", why)
        self.assertIn("level 60", why)

    def test_an_elite_well_below_the_leader_is_not_a_danger(self):
        self.assertEqual(refusal(hostile=[cell(1500, -5400, 40, elite=True)]), "")

    def test_mostly_red_ground_refuses_without_any_elite(self):
        why = refusal(hostile=[cell(1500, -5400, 66, n=6), cell(1500, -5300, 50)])
        self.assertIn("above", why)

    def test_a_few_red_spawns_among_many_green_ones_are_walked(self):
        self.assertEqual(
            refusal(hostile=[cell(1500, -5400, 66, n=1), cell(1500, -5300, 50, n=9)]),
            "",
        )

    def test_hostiles_far_from_the_forge_or_on_another_map_are_ignored(self):
        far = cell(1548.7 + 5000, -5387.1, 60, elite=True)
        other = cell(1548.7, -5387.1, 60, elite=True, map_id=1)
        self.assertEqual(refusal(hostile=[far, other]), "")

    def test_an_unknown_level_judges_no_danger(self):
        self.assertEqual(
            refusal(level=0, hostile=[cell(1500, -5400, 60, elite=True)]), ""
        )

    def test_the_constants_are_the_leveling_zone_rules(self):
        self.assertEqual(travel.FORGE_DANGER_GAP, levelroute.DANGER_GAP)
        self.assertEqual(travel.FORGE_DANGER_SHARE, levelroute.DANGER_SHARE)


def _forge_once(refusal_stub, spawn, smelters, claim_calls, logs, town_stop=False):
    tree = ast.parse(BRIDGE)
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_forge_once"
    )
    module = ast.Module(body=[node], type_ignores=[])

    async def to_thread(fn, *args):
        return fn(*args)

    async def mid_run(_names):
        return False

    async def claim(*a, **k):
        claim_calls.append(a)
        return True

    async def town_demand(_cohort=None):
        return smelters

    class Log:
        def info(self, msg, *a):
            logs.append(msg % a)

        warning = info

    ns = {
        "asyncio": types.SimpleNamespace(to_thread=to_thread),
        "log": Log(),
        "travel": travel,
        "_cohort_key": lambda c: None,
        "_forge_errands": lambda key: {} if town_stop else smelters,
        "_family_of": lambda c: (["Grug", "Ugga"], "Grug"),
        "_fetch_positions": lambda names: {"Grug": {"map_id": 0}},
        "_nearest_forge": lambda leader: spawn,
    }
    if refusal_stub is not None:
        ns["_forge_refusal"] = refusal_stub
    exec(compile(ast.fix_missing_locations(module), "bridge", "exec"), ns)
    me = types.SimpleNamespace(
        _mid_run=mid_run,
        _claim_town_slot=claim,
        _town_stop_demand=town_demand,
    )
    return ns["_forge_once"], me


class TheForgePassWaits(unittest.TestCase):
    def go(self, why, spawn=None, town_stop=False, smelters=None):
        claims, logs = [], []
        fn, me = _forge_once(
            (lambda *_a: why) if why is not None else None,
            spawn or dict(FORGE),
            {"Grog": 2657} if smelters is None else smelters,
            claims,
            logs,
            town_stop=town_stop,
        )
        asyncio.run(fn(me))
        return claims, logs

    def test_a_refused_forge_writes_no_aim_and_logs_one_line_with_the_reason(self):
        claims, logs = self.go("the Forge is 4000 yards away")
        self.assertEqual(claims, [])
        said = [x for x in logs if "4000 yards away" in x]
        self.assertEqual(len(said), 1)
        self.assertIn("Grog", said[0])
        self.assertFalse([x for x in logs if "unknown writer" in x])

    def test_a_clear_forge_is_aimed_exactly_as_before(self):
        claims, logs = self.go("")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0][0], "forge")
        self.assertEqual(claims[0][2], "at:0:1548.7,-5387.1,78.2")
        self.assertTrue([x for x in logs if "aimed at" in x])

    def test_the_town_stop_wait_for_a_far_forge_is_unchanged(self):
        far = dict(FORGE, d2=(travel.TOWN_STATION_YARDS + 100) ** 2)
        claims, logs = self.go("", spawn=far, town_stop=True, smelters={"Grog": 2657})
        self.assertEqual(claims, [])
        self.assertTrue([x for x in logs if "wait for a town stop" in x])

    def test_the_refusal_is_asked_after_the_walk_is_known_and_before_the_claim(self):
        body = BRIDGE.split("async def _forge_once", 1)[1].split(
            "async def _town_stop_demand", 1
        )[0]
        self.assertIn("_forge_refusal", body)
        self.assertLess(body.index("travel.forge_aim("), body.index("_forge_refusal"))
        self.assertLess(body.index("_forge_refusal"), body.index("_claim_town_slot"))

    def test_the_helper_is_module_level_and_judges_the_death_discs_too(self):
        top = {
            n.name: n for n in ast.parse(BRIDGE).body if isinstance(n, ast.FunctionDef)
        }
        self.assertIn("_forge_refusal", top)
        text = ast.get_source_segment(BRIDGE, top["_forge_refusal"])
        self.assertIn("_fetch_death_discs", text)
        self.assertIn("travel.forge_refusal", text)


if __name__ == "__main__":
    unittest.main()
