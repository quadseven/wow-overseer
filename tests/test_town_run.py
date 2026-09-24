"""A family whose campaign waits in town stays in town (mod-overseer#659).

Measured on wow-dev 2026-09-24, with both families' dungeon campaigns held
"town first" for bag room (#265) and the family on the default `quest` job for
the wait:

  * 04:53 the quest drive gave the Alliance leader the council's quest, and he
    flew from Tanaris to Winterspring and on to Un'Goro to hand it in. At 05:06
    his members were 13,000 yards behind, and at 05:50 the five stood in five
    zones.
  * 02:55 four Horde members cut off from a leader left inside Ragefire were
    granted `new rpg`, and within five minutes one was in Ashenvale and another
    in Mulgore. They stayed 5,000 to 6,600 yards apart for an hour.

The wait now runs on the `town run` job. Pinned here: the job is a real mode,
the life pass stops handing the wander strategy to anybody without an errand,
the far walks wait in the town slot, and the skill goal does not pull the
family out to a field. The hand-off, the re-assert and the release are pinned
in test_town_first.py, the activity in test_jev_activity.py.
"""

import ast
import pathlib
import unittest

import goals
import jobs
import townslot

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"


def _code(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == name
        ):
            return ast.get_source_segment(BRIDGE, node)
    raise AssertionError("%s not found in bridge.py" % name)


def _assign(name):
    for node in ast.parse(BRIDGE).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("%s not found in bridge.py" % name)


class TownRunIsAMode(unittest.TestCase):
    def test_it_is_implemented_and_says_what_drives_it(self):
        self.assertEqual("town run", jobs.TOWN_RUN)
        self.assertIn(jobs.TOWN_RUN, jobs.IMPLEMENTED)
        self.assertIn("LeaderCarriesNewRpg", jobs.DRIVES[jobs.TOWN_RUN])
        self.assertIn("CutOffFollowerRoams", jobs.DRIVES[jobs.TOWN_RUN])
        self.assertTrue(jobs.can_set(jobs.TOWN_RUN))
        self.assertNotIn("NOT BUILT", jobs.describe(jobs.TOWN_RUN))

    def test_the_module_accepts_the_name(self):
        """DoJob refuses a job it does not list, and the rows this bridge
        writes would come back 'unknown job mode'. The drive behind it is
        pinned in mod-overseer's own tests/test_town_hold.cpp, because the
        submodule here predates it."""
        if not MODULE.exists():
            self.skipTest("mod-overseer submodule not checked out")
        source = MODULE.read_text(encoding="utf-8", errors="replace")
        self.assertIn('"town run", "train", "raid prep"', source)


class NobodyWandersInTown(unittest.TestCase):
    def test_the_leader_without_an_errand_is_not_handed_new_rpg(self):
        got = goals.life_strategies(leads=True, in_town=True)
        self.assertNotIn(goals.LIFE_STRATEGY, got)
        self.assertIn("nc -new rpg", got)
        self.assertIn(goals.FLEE_STRATEGY, got)

    def test_an_aimed_follower_is_not_handed_it_either(self):
        """drive_quest stays on the rows through the wait and is inert under
        the town job; `aimed` must not turn it back into a traveller."""
        got = goals.life_strategies(leads=False, aimed=True, in_town=True)
        self.assertEqual(["nc -new rpg", "nc +follow", goals.FLEE_STRATEGY], got)

    def test_an_errand_still_walks_the_leader(self):
        self.assertEqual(
            goals.life_strategies(leads=True, travelling=True),
            goals.life_strategies(leads=True, travelling=True, in_town=True),
        )
        self.assertIn(
            goals.LIFE_STRATEGY,
            goals.life_strategies(leads=True, travelling=True, in_town=True),
        )

    def test_out_of_town_nothing_changes(self):
        for leads in (True, False):
            for aimed in (True, False):
                for travelling in (True, False):
                    for gathering in (True, False):
                        kw = dict(
                            leads=leads,
                            aimed=aimed,
                            travelling=travelling,
                            gathering=gathering,
                        )
                        self.assertEqual(
                            goals.life_strategies(**kw),
                            goals.life_strategies(in_town=False, **kw),
                        )

    def test_the_life_pass_passes_the_job_per_character(self):
        code = _code("_give_them_a_life")
        self.assertIn("mode == jobs.TOWN_RUN", code)
        self.assertIn("in_town=(name in in_town)", code)


class TheFarWalksWaitInTown(unittest.TestCase):
    def slot(self, why="bag room for Bork, Grog"):
        slot = townslot.Slot(releasable=lambda aim: True)
        if why:
            slot.hold_for_town(why)
        return slot

    def want(self, slot, claimant, aim="at:1:-4000,-3000,20"):
        return slot.want(
            claimant=claimant,
            character="Grug",
            aim=aim,
            leader="Grug",
            column="",
            retaskable=("", aim),
            now=10.0,
        )

    def test_the_names_are_the_bridges(self):
        self.assertEqual(
            {
                _assign("GATHER_CLAIMANT"),
                _assign("FLIGHT_CLAIMANT"),
                _assign("LEVEL_CLAIMANT"),
                _assign("ATTUNE_CLAIMANT"),
            },
            set(townslot.AWAY_CLAIMANTS),
        )

    def test_a_walk_out_of_town_waits(self):
        for claimant in townslot.AWAY_CLAIMANTS:
            d = self.want(self.slot(), claimant)
            self.assertEqual(townslot.SLOT_WAIT, d.verdict, claimant)
            self.assertIn("waits in town", d.reason)

    def test_a_town_errand_still_takes_the_column(self):
        for claimant, aim in (
            ("economy", "vendor"),
            ("bank", "banker"),
            ("mail", "mailbox"),
        ):
            d = self.want(self.slot(), claimant, aim)
            self.assertEqual(townslot.SLOT_TAKE, d.verdict, claimant)

    def test_without_the_hold_the_walks_go(self):
        for claimant in townslot.AWAY_CLAIMANTS:
            d = self.want(self.slot(why=""), claimant)
            self.assertEqual(townslot.SLOT_TAKE, d.verdict, claimant)


class TheSkillGoalWaits(unittest.TestCase):
    def test_it_stands_down_on_the_town_job_before_it_writes(self):
        code = _code("_drive_skill")
        self.assertIn("if standing == jobs.TOWN_RUN:", code)
        self.assertLess(
            code.index("if standing == jobs.TOWN_RUN:"),
            code.index("await self._set_job("),
        )
        self.assertLess(
            code.index("if standing == jobs.TOWN_RUN:"),
            code.index("await self._walk_to_gather_field("),
        )


if __name__ == "__main__":
    unittest.main()
