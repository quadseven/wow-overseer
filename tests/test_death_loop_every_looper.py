"""Every member listed in a death loop gets an escape or one logged reason (#2152).

WHY THIS EXISTS. The live read of 2026-11-17 listed nine members as
death-loop and the bridge log held no escape step and no reason for seven of
them. Three causes, all in the pass and none in the escape's own rungs:

  * the reason lines ride in `plan.notes`, which the bridge logs five lines a
    pass and then "and N more like it", so a reason was built and never read;
  * a member outside the lineup (role UNASSIGNED) is offered a class step
    only, so the escape never saw it, and no line said so;
  * a step the allowance or a walk already in flight refused was a note too.

The plan now carries `loop_lines`: one line per listed member that got no
escape step, whatever the reason, and an unassigned member is offered the
escape like any other.
"""

import ast
import logging
import pathlib
import unittest

import guildjobs
import guildroute
from test_guildjobs_death_loop import NAME, loop_of, plain_world
from test_guildlevel_open_quests import member


def plan(members=(), loops=None, **kw):
    return guildjobs.plan(
        list(members),
        masters={"Cave": "Grug", "Bonkers": "Zug"},
        leveling=kw.pop("leveling", plain_world()),
        cap=guildroute.FAR_WALK_YARDS,
        loops=loops if loops is not None else {NAME: loop_of()},
        **kw,
    )


class TheEscapeIssuedLeavesNoReasonLine(unittest.TestCase):
    def test_a_member_whose_escape_starts_has_no_loop_line(self):
        result = plan([member(NAME)])
        self.assertEqual([s.action for s in result.steps], ["hearth"])
        self.assertEqual(result.loop_lines, ())


class EveryOtherListedMemberHasOneLine(unittest.TestCase):
    def only_line(self, result):
        self.assertEqual(len(result.loop_lines), 1, result.loop_lines)
        line = result.loop_lines[0]
        self.assertTrue(line.startswith("%s gets no death-loop escape" % NAME), line)
        self.assertIn("Hillsbrad Foothills", line)
        return line

    def test_in_combat(self):
        result = plan([member(NAME, in_combat=True)])
        self.assertIn("in combat", self.only_line(result))

    def test_the_line_survives_a_pass_full_of_other_notes(self):
        # The bridge caps plan.notes; loop_lines is its own field.
        others = [member("Other%d" % i, in_combat=True, zone_id=1) for i in range(12)]
        result = plan([member(NAME, in_combat=True)] + others)
        self.assertIn("in combat", self.only_line(result))

    def test_a_step_the_pass_refused_names_the_refusal(self):
        result = plan([member(NAME)], busy={NAME})
        self.assertIn("already on another guild walk", self.only_line(result))

    def test_a_listed_member_the_pass_did_not_read_is_named(self):
        result = plan([])
        self.assertIn("not placed this pass", self.only_line(result))

    def test_a_roster_family_member_is_named_a_roster_member(self):
        fam = member(NAME, role=guildjobs.FAMILY)
        result = plan([], family_members=[fam])
        self.assertIn("roster member", self.only_line(result))

    def test_a_member_already_out_of_the_zone_is_named(self):
        result = plan([member(NAME, zone_id=1, in_combat=True)])
        self.assertIn("already out of", self.only_line(result))


class AMemberOutsideTheLineupIsOfferedTheEscape(unittest.TestCase):
    def test_an_unassigned_looper_in_its_zone_is_issued_the_hearth(self):
        m = member(NAME, role=guildjobs.UNASSIGNED)
        result = plan([], class_candidates=[m])
        self.assertEqual(
            [(s.holder, s.action) for s in result.steps], [(NAME, "hearth")]
        )
        self.assertEqual(result.loop_lines, ())

    def test_an_unassigned_looper_that_cannot_escape_gets_a_line(self):
        m = member(NAME, role=guildjobs.UNASSIGNED, in_combat=True)
        result = plan([], class_candidates=[m])
        self.assertEqual(result.steps, ())
        self.assertIn("in combat", result.loop_lines[0])


class TheBridgeLogsEveryLoopLine(unittest.TestCase):
    """The bridge imports discord, which CI does not install, so the helper is
    lifted out of the source and run against a plain logger."""

    def _helper(self):
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
            encoding="utf-8"
        )
        node = next(
            n
            for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name == "_log_loop_lines"
        )
        logger = logging.getLogger("test_death_loop_every_looper")
        space = {"log": logger}
        exec(compile(ast.Module([node], []), "bridge.py", "exec"), space)
        return space["_log_loop_lines"], logger

    def test_no_line_is_capped(self):
        helper, logger = self._helper()
        lines = tuple(
            "M%d gets no death-loop escape from X: in combat" % i for i in range(20)
        )
        with self.assertLogs(logger, level="INFO") as got:
            helper(lines)
        self.assertEqual(len(got.records), 20)
        self.assertNotIn("more like it", "\n".join(got.output))

    def test_the_pass_calls_it(self):
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_log_loop_lines(plan.loop_lines)", src)


if __name__ == "__main__":
    unittest.main()
