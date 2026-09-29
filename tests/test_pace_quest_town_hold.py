"""A family the pace holds on the questing fallback is not waiting in town for bag room.

Measured on wow-dev 2026-09-29. The Horde family's queue head was Ragefire Chasm
0 of 50. The pace had put the family on the questing fallback two days earlier
(dungeonpace.QUEST), so nobody carried a dungeon job. `_town_first_hold` reads
"a campaign waits and no member carries its job" as "handed to town for bag
room", so the town slot held the family in town for a campaign that was not
coming, the learn trips and the level route waited behind that hold, and the
economy passes ran errand after errand for a run that was never going to start.
The hold's own ceiling clock (`_TOWN_FIRST_SINCE`) is only started by the queue
step, which the pace never lets run, so the hold had no end.
"""

import ast
import pathlib
import unittest

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
NAMES = ["Oz", "Uzza", "Zork", "Zrog", "Zug"]


def _source(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _hold(jobs_now, questers=()):
    ns = {
        "_campaign_waiting": lambda names: True,
        "_jobs_of": lambda names: {n: jobs_now for n in names},
        "_PACE_QUESTERS": set(questers),
    }
    module = ast.Module(body=[_source("_town_first_hold")], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "bridge", "exec"), ns)
    return ns["_town_first_hold"]


class TheTownHoldAndThePace(unittest.TestCase):
    def test_a_campaign_handed_to_town_is_still_a_town_hold(self):
        self.assertTrue(_hold("town run")(NAMES))

    def test_a_family_on_the_questing_fallback_is_not_a_town_hold(self):
        self.assertFalse(_hold("quest", questers=NAMES)(NAMES))

    def test_one_questing_member_is_enough_to_stand_the_hold_down(self):
        self.assertFalse(_hold("town run", questers=["Zug"])(NAMES))

    def test_the_pace_keeps_the_set_it_is_asked_against(self):
        body = ast.get_source_segment(BRIDGE, _source("_pace_quest"))
        self.assertIn("_PACE_QUESTERS", body)
        self.assertIn("update(names)", body)
        self.assertIn("difference_update(names)", body)


if __name__ == "__main__":
    unittest.main()
