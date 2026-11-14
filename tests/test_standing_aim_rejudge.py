"""A standing travel aim is re-judged after a death on its walk (#2539).

The leader died three times to one Scarlet Enchanter walking to a standing
Forge aim, and the aim was released only when its lease ran out. The avoid
discs were judged once, at the door. These tests replay that sequence and pin
that two deaths on a walk release the aim, that quiet ground and an unreadable
death table release nothing, and that the sweep is wired into the economy pass.
"""

import ast
import asyncio
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import deathcells as dc  # noqa: E402

BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")

AIM = "at:0:1548.7,-5387.1,78.2"
# Where a released ghost stands: a long way from the Forge, on the same map.
GRAVEYARD = {"map_id": 0, "x": 2300.0, "y": -4000.0}


def death(
    x=1550.0,
    y=-5380.0,
    who="Grug",
    killer="Scarlet Enchanter",
    killer_type="creature",
    map_id=0,
):
    return {
        "name": who,
        "map_id": map_id,
        "x": x,
        "y": y,
        "killer_type": killer_type,
        "killer_name": killer,
    }


THREE = [death(), death(1549.0, -5384.0), death(1551.0, -5386.0)]


class TheEasternPlaguelandsSequence(unittest.TestCase):
    def judge(self, deaths, aim=AIM, here=GRAVEYARD, discs=()):
        return dc.standing_aim_refusal(list(discs), deaths, here, aim)

    def test_the_first_death_alone_leaves_the_aim_standing(self):
        self.assertEqual(self.judge(THREE[:1]), "")

    def test_the_second_death_to_one_hostile_releases_it_not_the_lease(self):
        why = self.judge(THREE[:2])
        self.assertIn("2 deaths", why)
        self.assertIn("Scarlet Enchanter", why)
        self.assertIn(AIM, why)

    def test_the_third_death_still_says_so(self):
        self.assertIn("3 deaths", self.judge(THREE))

    def test_deaths_on_the_line_of_the_walk_count_too(self):
        mid = [death(2000.0, -4600.0), death(2010.0, -4590.0)]
        self.assertIn("2 deaths", self.judge(mid))

    def test_deaths_far_from_the_walk_leave_it_alone(self):
        elsewhere = [death(-8000.0, 500.0), death(-8010.0, 510.0)]
        self.assertEqual(self.judge(elsewhere), "")

    def test_deaths_on_another_map_leave_it_alone(self):
        self.assertEqual(self.judge([death(map_id=1), death(map_id=1)]), "")

    def test_no_deaths_leave_it_alone(self):
        self.assertEqual(self.judge([]), "")

    def test_an_unreadable_death_table_releases_nothing(self):
        self.assertEqual(self.judge(None), "")


class TheDiscsAreJudgedAgain(unittest.TestCase):
    def test_an_aim_that_now_crosses_a_disc_is_released_with_no_repeat_death(self):
        lava = [
            {
                "map_id": 0,
                "x": 1825.0 + i,
                "y": -4875.0,
                "z": 1.0,
                "killer_type": "self",
                "liquid_type": "magma",
                "yards_fallen": 0,
            }
            for i in (0, 2, 4)
        ]
        discs = dc.discs(lava)
        why = dc.standing_aim_refusal(discs, [], GRAVEYARD, AIM)
        self.assertIn("lava", why)

    def test_a_role_keyword_is_judged_by_its_nearest_holder(self):
        why = dc.standing_aim_refusal(
            [],
            [death(), death()],
            GRAVEYARD,
            "vendor",
            spawn={"map_id": 0, "x": 1548.0, "y": -5387.0},
        )
        self.assertIn("2 deaths", why)
        self.assertIn("vendor", why)

    def test_a_keyword_with_no_known_holder_is_not_judged(self):
        self.assertEqual(
            dc.standing_aim_refusal([], [death(), death()], GRAVEYARD, "vendor"), ""
        )


def _sweep(aims, why_by_name, released, logs):
    tree = ast.parse(BRIDGE)
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "_release_deadly_standing_aims"
    )
    module = ast.Module(body=[node], type_ignores=[])

    async def to_thread(fn, *args):
        return fn(*args)

    class Log:
        def warning(self, msg, *a):
            logs.append(msg % a)

        info = warning

    def release(name, aim):
        released.append((name, aim))
        return True

    ns = {
        "asyncio": types.SimpleNamespace(to_thread=to_thread),
        "log": Log(),
        "_standing_travel_aims": lambda: aims,
        "_deadly_standing_aims": lambda names, standing: {
            n: w for n, w in why_by_name.items() if n in standing
        },
        "_release_trade_errand": release,
    }
    exec(compile(ast.fix_missing_locations(module), "bridge", "exec"), ns)
    return ns["_release_deadly_standing_aims"]


class TheSweepReleases(unittest.TestCase):
    def run_sweep(self, aims, why_by_name, names):
        released, logs = [], []
        fn = _sweep(aims, why_by_name, released, logs)
        count = asyncio.run(fn(types.SimpleNamespace(), names))
        return count, released, logs

    def test_a_refused_aim_is_released_and_the_reason_logged(self):
        count, released, logs = self.run_sweep(
            {"Grug": AIM}, {"Grug": "2 deaths on the walk"}, ["Grug", "Ugga"]
        )
        self.assertEqual(count, 1)
        self.assertEqual(released, [("Grug", AIM)])
        self.assertEqual(len([x for x in logs if "2 deaths on the walk" in x]), 1)

    def test_an_aim_nobody_refuses_is_left_standing(self):
        count, released, _logs = self.run_sweep({"Grug": AIM}, {}, ["Grug"])
        self.assertEqual((count, released), (0, []))

    def test_only_this_familys_names_are_judged(self):
        count, released, _logs = self.run_sweep(
            {"Zug": AIM}, {"Zug": "deaths"}, ["Grug"]
        )
        self.assertEqual((count, released), (0, []))


class TheSweepIsWired(unittest.TestCase):
    def test_the_economy_pass_runs_it_outside_a_dungeon_run(self):
        spot = BRIDGE.split(
            "await self._release_stranded_ground_errands(names, leader)", 1
        )[1]
        head = spot.split("else:", 1)[0]
        self.assertIn("_release_deadly_standing_aims", head)

    def test_the_helper_reads_discs_deaths_and_fails_open(self):
        top = {
            n.name: n for n in ast.parse(BRIDGE).body if isinstance(n, ast.FunctionDef)
        }
        self.assertIn("_deadly_standing_aims", top)
        text = ast.get_source_segment(BRIDGE, top["_deadly_standing_aims"])
        self.assertIn("_fetch_death_discs", text)
        self.assertIn("_fetch_recent_deaths", text)
        self.assertIn("standing_aim_refusal", text)
        reader = ast.get_source_segment(BRIDGE, top["_fetch_recent_deaths"])
        self.assertIn("MySQLError", reader)
        self.assertIn("None", reader)


if __name__ == "__main__":
    unittest.main()
