"""Ground the family died on twice is not a walk (wow-overseer#2457).

Synthetic fixtures: rows shaped like the death table's lava and under-world
fall rows. These tests pin what becomes an avoid disc, what does not, and that
a line over a disc is refused with a reason.
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


# Coordinates shaped like recorded lava deaths, and a fall under the world.
LAVA = [row(-7812, -928), row(-7814, -928), row(-7816, -930), row(-7780, -910)]
FALLS = [
    row(-8216, -562, z=-511, liquid="none", fell=30),
    row(-8151, -625, z=-505, liquid="none", fell=60),
]
STORMWIND = {"map_id": 0, "x": -8800.0, "y": 600.0}
PLAGUELANDS = {"map_id": 0, "x": -6800.0, "y": -2450.0}


class WhatIsLethalGround(unittest.TestCase):
    def test_lava_and_slime_are_lethal_ground(self):
        self.assertEqual(dc.kind_of(row(1, 1, liquid="magma")), "lava")
        self.assertEqual(dc.kind_of(row(1, 1, liquid="slime")), "slime")

    def test_a_self_death_after_a_fall_is_lethal_ground(self):
        self.assertEqual(dc.kind_of(row(1, 1, z=-500, liquid="none", fell=30)), "fall")

    def test_drowning_is_not_lethal_ground(self):
        self.assertEqual(dc.kind_of(row(1, 1, liquid="water")), "")

    def test_a_creature_kill_is_not_lethal_ground(self):
        self.assertEqual(dc.kind_of(row(1, 1, liquid="none", killer="creature")), "")

    def test_an_unsampled_fall_is_not_a_fall(self):
        self.assertEqual(dc.kind_of(row(1, 1, liquid="none", fell=-1.0)), "")

    def test_a_row_with_no_position_is_nothing(self):
        self.assertEqual(dc.kind_of({"killer_type": "self"}), "")


class DiscsFromDeaths(unittest.TestCase):
    def test_four_lava_deaths_make_one_disc_over_them(self):
        discs = dc.discs(LAVA)
        self.assertEqual(len(discs), 1)
        disc = discs[0]
        self.assertEqual((disc.kind, disc.deaths, disc.map_id), ("lava", 4, 0))
        for r in LAVA:
            self.assertLessEqual(
                ((disc.x - r["x"]) ** 2 + (disc.y - r["y"]) ** 2) ** 0.5, disc.radius
            )

    def test_one_death_is_not_a_place(self):
        self.assertEqual(dc.discs([row(-7812, -928)]), [])

    def test_two_deaths_far_apart_are_not_a_place(self):
        self.assertEqual(dc.discs([row(-7812, -928), row(-6000, -2000)]), [])

    def test_deaths_on_two_maps_never_join(self):
        self.assertEqual(dc.discs([row(5, 5, map_id=0), row(5, 5, map_id=1)]), [])

    def test_two_separate_stretches_are_two_discs(self):
        far = [row(-7840, -1117), row(-7843, -1119)]
        self.assertEqual(len(dc.discs(LAVA + far)), 2)

    def test_the_disc_is_never_smaller_than_the_floor_or_larger_than_the_cap(self):
        tight = dc.discs([row(0, 0), row(0, 0)])[0]
        self.assertEqual(tight.radius, dc.MIN_RADIUS)
        chain = [row(i * 100.0, 0) for i in range(40)]
        self.assertEqual(dc.discs(chain)[0].radius, dc.MAX_RADIUS)

    def test_falls_make_a_disc_too(self):
        discs = dc.discs(FALLS)
        self.assertEqual([d.kind for d in discs], ["fall"])

    def test_nothing_in_nothing_out(self):
        self.assertEqual(dc.discs([]), [])
        self.assertEqual(dc.discs(None), [])


class AWalkOverADisc(unittest.TestCase):
    def setUp(self):
        self.discs = dc.discs(LAVA)

    def test_the_line_over_the_lava_is_caught(self):
        hit = dc.crossing(self.discs, STORMWIND, PLAGUELANDS)
        self.assertIsNotNone(hit)

    def test_a_line_that_misses_is_clear(self):
        north = {"map_id": 0, "x": -8800.0, "y": 2000.0}
        east = {"map_id": 0, "x": -5000.0, "y": 3000.0}
        self.assertIsNone(dc.crossing(self.discs, north, east))

    def test_another_map_is_never_crossed(self):
        there = {"map_id": 1, "x": -7812.0, "y": -928.0}
        self.assertIsNone(dc.crossing(self.discs, there, there))

    def test_a_walker_already_inside_is_not_pinned_there(self):
        inside = {"map_id": 0, "x": -7812.0, "y": -928.0}
        out = {"map_id": 0, "x": -7000.0, "y": 0.0}
        self.assertIsNone(dc.crossing(self.discs, inside, out))

    def test_a_goal_inside_is_caught(self):
        goal = {"map_id": 0, "x": -7814.0, "y": -929.0}
        self.assertIsNotNone(dc.crossing(self.discs, STORMWIND, goal))

    def test_a_point_that_cannot_be_read_is_not_a_refusal(self):
        self.assertIsNone(dc.crossing(self.discs, {}, PLAGUELANDS))
        self.assertIsNone(dc.crossing(self.discs, STORMWIND, None))


class RefusingAnAim(unittest.TestCase):
    def test_a_ground_aim_over_the_lava_says_why(self):
        discs = dc.discs(LAVA)
        why = dc.aim_refusal(discs, STORMWIND, "at:0:-6800.0,-2450.0,60.0")
        self.assertIn("4 lava deaths", why)

    def test_a_ground_aim_that_clears_is_not_refused(self):
        discs = dc.discs(LAVA)
        self.assertEqual(
            dc.aim_refusal(discs, STORMWIND, "at:0:-8700.0,700.0,96.0"), ""
        )

    def test_a_keyword_aim_is_not_judged_here(self):
        discs = dc.discs(LAVA)
        self.assertEqual(dc.aim_refusal(discs, STORMWIND, "vendor"), "")

    def test_no_discs_refuses_nothing(self):
        self.assertEqual(dc.aim_refusal([], STORMWIND, "at:0:-6800.0,-2450.0,60.0"), "")


class PickingAQuest(unittest.TestCase):
    def setUp(self):
        self.discs = dc.discs(LAVA)
        self.ends = {
            9128: [{"map_id": 0, "x": -6800.0, "y": -2450.0}],
            60: [{"map_id": 0, "x": -8700.0, "y": 700.0}],
        }

    def test_a_quest_ending_past_the_lava_gives_way_to_the_next(self):
        picked, notes = dc.pick_quest(self.discs, STORMWIND, [9128, 60], self.ends)
        self.assertEqual(picked, 60)
        self.assertEqual(len(notes), 1)
        self.assertIn("9128", notes[0])

    def test_with_no_alternative_the_answer_is_nothing_and_says_why(self):
        picked, notes = dc.pick_quest(self.discs, STORMWIND, [9128], self.ends)
        self.assertEqual(picked, 0)
        self.assertTrue(notes)

    def test_a_quest_with_no_known_end_is_kept(self):
        picked, notes = dc.pick_quest(self.discs, STORMWIND, [777], {})
        self.assertEqual((picked, notes), (777, []))

    def test_the_nearest_end_on_the_map_is_the_one_judged(self):
        ends = {
            5: [
                {"map_id": 0, "x": -6800.0, "y": -2450.0},
                {"map_id": 0, "x": -8700.0, "y": 700.0},
            ]
        }
        picked, notes = dc.pick_quest(self.discs, STORMWIND, [5], ends)
        self.assertEqual((picked, notes), (5, []))

    def test_no_discs_keeps_the_first(self):
        self.assertEqual(
            dc.pick_quest([], STORMWIND, [9128, 60], self.ends), (9128, [])
        )


class TheBridgeUsesIt(unittest.TestCase):
    def test_the_town_slot_door_asks_before_writing_a_ground_aim(self):
        door = BRIDGE.split("async def _claim_town_slot", 1)[1].split(
            "def _cohort_town_slot", 1
        )[0]
        self.assertIn("_death_disc_refusal", door)
        self.assertLess(door.index("_death_disc_refusal"), door.index("taken = await"))

    def test_the_quest_choice_passes_over_a_walk_across_a_death_disc(self):
        choice = BRIDGE.split("def _choose_drive_quest", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_pass_over_deadly_quests", choice)
        helper = BRIDGE.split("def _pass_over_deadly_quests", 1)[1].split("\ndef ", 1)[
            0
        ]
        self.assertIn("deathcells.pick_quest", helper)

    def test_a_broken_read_fails_open_and_says_so(self):
        reader = BRIDGE.split("def _fetch_death_discs", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("MySQLError", reader)
        self.assertIn("log.warning", reader)


class _Reached(Exception):
    """Raised by the stub the door calls once the death check has passed."""


def _door(refusal):
    """The real `_claim_town_slot`, run with stubs, returning (fn, calls)."""
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
        "log": logging.getLogger("test_deathcells"),
        "_head_now": lambda: "Lead",
        "_cohort_leader": lambda key: "Lead",
        "_current_travel_npc": reached,
        "_write_trade_errand": lambda *_a: calls.append("write"),
    }
    if refusal is not None:
        ns["_death_disc_refusal"] = lambda leader, aim: refusal
    me = types.SimpleNamespace(_cohort_town_slot=lambda cohort: None)
    exec(compile(ast.fix_missing_locations(module), "bridge", "exec"), ns)
    return ns["_claim_town_slot"], me, calls


class TheDoorRuns(unittest.TestCase):
    def test_the_helper_the_door_looks_up_is_a_module_level_function(self):
        top = {n.name for n in ast.parse(BRIDGE).body if isinstance(n, ast.FunctionDef)}
        self.assertIn("_death_disc_refusal", top)

    def go(self, refusal, aim):
        fn, me, calls = _door(refusal)
        try:
            return asyncio.run(fn(me, "gather", "Lead", aim)), calls
        except _Reached:
            return "reached", calls

    def test_a_refused_ground_aim_is_not_written(self):
        got, calls = self.go("crosses lava", "at:0:1.0,2.0,3.0")
        self.assertIs(got, False)
        self.assertEqual(calls, [])

    def test_a_clear_ground_aim_goes_on_to_the_slot(self):
        got, _calls = self.go("", "at:0:1.0,2.0,3.0")
        self.assertEqual(got, "reached")

    def test_a_keyword_aim_is_never_judged(self):
        got, _calls = self.go("crosses lava", "vendor")
        self.assertEqual(got, "reached")


if __name__ == "__main__":
    unittest.main()
