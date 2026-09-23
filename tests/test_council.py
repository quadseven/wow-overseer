"""The family works out what today is for.

The operator's brief: "I really want them to sort of be like a team that collectively
talks together, talking about what they need to focus on today... sometimes
they just log in and just fish."

Two things make it a council rather than an announcement, and both are tested
here: it can disagree, and the plan it produces is data the goal supervisor
can act on rather than prose.
"""

import unittest

import bonds
import council
import goals


def _m(name, level, **over):
    return council.Member(
        name=name,
        level=level,
        class_name=over.pop("class_name", "Warrior"),
        gold=over.pop("gold", 999999),
        trades=over.pop("trades", 5),
    )


FAMILY = [_m("Grug", 5), _m("Ugga", 5), _m("Grog", 5), _m("Bork", 5), _m("Og", 5)]


class AssessTest(unittest.TestCase):
    """One member, its own row, and the levels anyone could read off a
    portrait. Nothing else is in scope."""

    def test_a_member_left_far_behind_outranks_anything_personal(self):
        me = _m("Grug", 9, trades=0, gold=0)
        p = council.assess(me, public_levels={"Grug": 9, "Ugga": 9, "Bork": 2})
        self.assertEqual((p.kind, p.beneficiary), ("level", "Bork"))

    def test_a_normal_level_spread_is_not_someone_being_left_behind(self):
        """Two levels apart is people playing different amounts. Treating that
        as an emergency would mean the family never does anything else."""
        me = _m("Grug", 6, trades=0)
        p = council.assess(me, public_levels={"Grug": 6, "Ugga": 5, "Bork": 4})
        self.assertNotEqual(p.kind, "level" if p.beneficiary != "Grug" else None)
        self.assertEqual(p.beneficiary, "Grug")

    def test_a_member_with_no_trade_wants_one(self):
        p = council.assess(_m("Og", 7, trades=0), public_levels={"Og": 7, "Grug": 7})
        self.assertEqual((p.kind, p.beneficiary), ("trades", "Og"))

    def test_a_poor_member_old_enough_for_a_mount_wants_coin(self):
        me = _m("Ugga", council.SAVING_FROM_LEVEL, gold=0, trades=5)
        p = council.assess(me, public_levels={"Ugga": me.level, "Grug": me.level})
        self.assertEqual((p.kind, p.beneficiary), ("coin", "Ugga"))

    def test_a_poor_member_too_young_to_ride_does_not_ask_for_coin(self):
        me = _m("Bork", council.SAVING_FROM_LEVEL - 1, gold=0, trades=5)
        p = council.assess(me, public_levels={"Bork": me.level, "Grug": me.level})
        self.assertNotEqual(p.kind, "coin")

    def test_a_member_with_nothing_pressing_proposes_a_quiet_day(self):
        me = _m("Grog", council.IDLE_LEVEL_STEP)
        p = council.assess(me, public_levels={"Grog": me.level, "Grug": me.level})
        self.assertEqual(p.kind, "idle")
        self.assertEqual(p.beneficiary, council.FAMILY_AT_LARGE)

    def test_assess_is_given_no_way_to_read_another_members_purse(self):
        """The private-brain boundary, enforced by signature rather than by
        discipline: assess takes ONE member and a map of public levels. A
        future reader who wants somebody else's gold has to change the
        signature to get it, which is the point (infra#2725)."""
        import inspect

        params = inspect.signature(council.assess).parameters
        self.assertEqual(list(params), ["me", "public_levels"])
        # A string, not the class: council.py uses `from __future__ import
        # annotations`, so every annotation is deferred.
        self.assertEqual(params["me"].annotation, "Member")


class CouncilTest(unittest.TestCase):
    def test_a_council_of_one_decides_nothing(self):
        c = council.hold([_m("Grug", 5)], history=[])
        self.assertIsNone(c.plan)
        self.assertIn("nobody", c.reason)

    def test_outsiders_are_not_in_the_family_council(self):
        c = council.hold([_m("Grug", 5), _m("Thrall", 60)], history=[])
        self.assertIsNone(c.plan)

    def test_the_family_agrees_to_carry_the_one_left_behind(self):
        members = [_m(n, 6) for n in ("Grug", "Ugga", "Grog", "Bork")] + [_m("Og", 1)]
        c = council.hold(members, history=[])
        self.assertEqual((c.plan.kind, c.plan.beneficiary), ("level", "Og"))

    def test_the_same_state_always_produces_the_same_plan(self):
        """The supervisor acts on this. A plan that depends on dict order
        would be a different day every time nothing changed."""
        members = [_m(n, 6) for n in ("Grug", "Ugga", "Grog", "Bork")] + [_m("Og", 1)]
        first = council.hold(members, history=[]).plan
        for _ in range(5):
            self.assertEqual(
                council.hold(list(reversed(members)), history=[]).plan, first
            )

    def test_four_people_reaching_one_conclusion_say_it_once(self):
        """They are folded into one proposal with the elder speaking. Four
        identical sentences in a row is an echo, not a conversation."""
        members = [_m(n, 6) for n in ("Grug", "Ugga", "Grog", "Bork")] + [_m("Og", 1)]
        lines = council.hold(members, history=[]).lines
        left_behind = [line for line in lines if "behind" in line]
        # Once when raised, once when settled.
        self.assertEqual(len(left_behind), 2, lines)

    def test_everyone_who_agrees_is_heard(self):
        members = [_m(n, 6) for n in ("Grug", "Ugga", "Grog", "Bork")] + [_m("Og", 1)]
        lines = council.hold(members, history=[]).lines
        for who in ("Ugga", "Grog", "Bork"):
            self.assertTrue(
                any(line.startswith(who + ":") for line in lines),
                "%s said nothing at all: %s" % (who, lines),
            )


class DisagreementTest(unittest.TestCase):
    """A council where everyone always agrees is an announcement in costume."""

    def test_grug_will_not_propose_helping_ugga_while_he_is_sulking(self):
        """He would refuse the muster for the same reason, so proposing it
        would have the council saying one thing and bonds doing another."""
        members = [_m("Grug", 6), _m("Ugga", 1), _m("Grog", 6), _m("Og", 6)]
        history = [("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
        c = council.hold(members, history=history)
        raised = [
            line
            for line in c.lines
            if line.startswith("Grug:") and "left behind" in line
        ]
        self.assertEqual(raised, [], c.lines)

    def test_the_refusal_is_spoken_rather_than_swallowed(self):
        members = [_m("Grug", 6), _m("Ugga", 1), _m("Grog", 6), _m("Og", 6)]
        history = [("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
        c = council.hold(members, history=history)
        self.assertTrue(
            any(line.startswith("Grug:") and "Og" in line for line in c.lines), c.lines
        )

    def test_somebody_else_still_carries_the_plan(self):
        """The sulk costs Ugga her husband's help, not the family's."""
        members = [_m("Grug", 6), _m("Ugga", 1), _m("Grog", 6), _m("Og", 6)]
        history = [("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
        c = council.hold(members, history=history)
        self.assertEqual(c.plan.beneficiary, "Ugga")
        self.assertNotIn("Grug", c.reason)

    def test_a_member_says_a_refusal_once_not_twice(self):
        members = [_m("Grug", 6), _m("Ugga", 1), _m("Grog", 6), _m("Og", 6)]
        history = [("Og", "Ugga")] * bonds.JEALOUSY_THRESHOLD
        lines = council.hold(members, history=history).lines
        grug = [line for line in lines if line.startswith("Grug:")]
        self.assertEqual(len(grug), len(set(grug)), grug)


class PlanIsActionableTest(unittest.TestCase):
    """An LLM that writes a lovely paragraph and no plan has produced nothing."""

    def test_a_level_plan_is_a_goal_the_supervisor_accepts(self):
        members = [_m(n, 6) for n in ("Grug", "Ugga", "Grog", "Bork")] + [_m("Og", 1)]
        plan = council.hold(members, history=[]).plan
        row = {
            "id": 1,
            "character_name": plan.beneficiary,
            "kind": plan.kind,
            "skill_name": None,
            "target": plan.target,
            "status": "active",
            "channel_id": "",
            "last_report": None,
        }
        actions = goals.reconcile(row, 1)
        self.assertTrue(
            any(isinstance(a, goals.StrategyCommand) for a in actions), actions
        )

    def test_the_plan_target_is_reachable_rather_than_aspirational(self):
        """Targeting the family median would ask a level 1 to gain five levels
        before the goal ever reports progress."""
        members = [_m(n, 20) for n in ("Grug", "Ugga", "Grog", "Bork")] + [_m("Og", 1)]
        plan = council.hold(members, history=[]).plan
        self.assertLessEqual(plan.target, 1 + council.BEHIND_BY)
        self.assertGreater(plan.target, 1)


class WiringTest(unittest.TestCase):
    """A council nobody runs is a very well-tested monologue.

    bridge.py needs pymysql and discord, so this walks its AST. Not a grep:
    `council.hold` in a comment holds no council.
    """

    @classmethod
    def setUpClass(cls):
        import ast
        import pathlib

        cls.ast = ast
        cls.tree = ast.parse(
            (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        )

    def _names_in(self, fn_name):
        ast = self.ast
        fn = next(
            n
            for n in ast.walk(self.tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == fn_name
        )
        return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)
        }

    def test_the_council_loop_is_actually_started(self):
        self.assertIn(
            "_hold_council",
            self._names_in("setup_hook"),
            "the loop is defined but never scheduled",
        )

    def test_a_council_speaks_in_the_world_rather_than_posting_a_summary(self):
        """The lines must be SAID, so they reach Discord by the one path world
        speech already takes. A second path drifts from the first."""
        names = self._names_in("_council_once")
        self.assertIn("_insert_speak", names)
        # And that it is handed a real line to say. Checking only the call
        # let a mutant that passed None straight through.
        self.assertIn("SpeakCommand", names)

    def test_a_council_is_held_where_the_family_can_actually_hear_it(self):
        """/say carries about 25 yards and they grind in different zones. The
        first live council went out on say: every captured line came back with
        heard_by equal to sender_name - five characters talking to themselves
        while Discord showed a conversation that never happened."""
        import ast
        import pathlib

        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        fn = next(
            n
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_council_once"
        )
        channels = [
            n.value
            for n in ast.walk(fn)
            if isinstance(n, ast.Constant)
            and n.value in ("say", "yell", "party", "raid")
        ]
        self.assertIn("party", channels)
        self.assertNotIn(
            "say",
            channels,
            "a council on /say is only heard by whoever stands next to the speaker",
        )

    def test_the_family_head_is_marked_as_party_leader(self):
        """Without this the party leader is whoever sorts first by name -
        which put Bork, the youngest, in charge of his own father."""
        names = self._names_in("_protect_characters")
        self.assertIn("_mark_party_leader", names)
        # Through _head_now since infra#2757, which is bonds.head_of_family()
        # except while a trade errand is outstanding - the character going to
        # the trainer leads, so the family walks there together behind its one
        # traveller. Asked from the same helper as _give_them_a_life so the
        # flag and the strategies can never disagree about who leads; a family
        # following a character that is about to stop leading is a party split
        # in two for thirty seconds.
        self.assertIn("_head_now", names)

    def test_leadership_is_not_corrected_with_a_gm_command(self):
        """A playerbot session does not carry GM security. With account 318 at
        gmlevel 3, `.pinfo` and `.gps` issued as the bot are both refused, so
        `.group leader` produced an error every cycle and never worked. The
        whole kind='gm' path is only usable while a real client holds the
        character."""
        names = self._names_in("_protect_characters")
        self.assertNotIn(
            "_insert_gm",
            names,
            "a bot session cannot run GM commands; issuing one here "
            "can only error, once per cycle, forever",
        )
        self.assertNotIn("GmCommand", names)

    def test_a_settled_plan_is_not_re_staged_every_hour(self):
        """Nothing has changed, so re-speaking the whole scene is a stuck
        record, not deliberation. Checked BEFORE the council speaks - persisting
        already refused the duplicate, but only after the scene had played."""
        self.assertIn("_already_agreed", self._names_in("_council_once"))

    def test_a_council_remembers_what_it_argued(self):
        self.assertIn("_insert_thought", self._names_in("_council_once"))

    def test_an_agreed_plan_is_persisted(self):
        self.assertIn("_persist_council_plan", self._names_in("_council_once"))

    def test_the_council_judges_on_real_history_not_an_empty_list(self):
        """history=[] would keep every test green and make every bond rule
        inert, so the sulk could never appear."""
        self.assertIn("history_from_thoughts", self._names_in("_council_once"))


if __name__ == "__main__":
    unittest.main()


class PhrasingTest(unittest.TestCase):
    def test_one_level_is_not_one_more_levels(self):
        """It reads as a template, and a template breaks the spell."""
        me = council.Member(
            "Grog", council.IDLE_LEVEL_STEP - 1, "Paladin", gold=999999, trades=5
        )
        p = council.assess(me, public_levels={"Grog": me.level, "Grug": me.level})
        self.assertIn("one more level.", p.said)
        self.assertNotIn("levels", p.said)

    def test_several_levels_still_reads_naturally(self):
        me = council.Member("Grog", 1, "Paladin", gold=999999, trades=5)
        p = council.assess(me, public_levels={"Grog": 1, "Grug": 1})
        self.assertIn("more levels.", p.said)


class SharedWantTest(unittest.TestCase):
    """Five characters each saying "I want 3 more levels" is ONE idea.

    Keying the merge on the beneficiary made it five, so the scene read as five
    people talking past each other and then all volunteering to help whoever
    happened to speak first.
    """

    def test_everyone_wanting_the_same_thing_says_it_once(self):
        members = [_m(n, 7) for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]
        lines = council.hold(members, history=[]).lines
        wants = [line for line in lines if "more level" in line]
        self.assertEqual(len(wants), 2, lines)  # raised once, settled once

    def test_the_others_still_answer(self):
        members = [_m(n, 7) for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]
        lines = council.hold(members, history=[]).lines
        for who in ("Ugga", "Grog", "Bork", "Og"):
            self.assertTrue(any(line.startswith(who + ":") for line in lines), lines)

    def test_wanting_different_amounts_is_still_two_ideas(self):
        """A shared want is the same want. Different targets are not."""
        members = [_m("Grug", 7), _m("Ugga", 7), _m("Og", 3), _m("Grog", 7)]
        lines = council.hold(members, history=[]).lines
        self.assertTrue(any("Og" in line for line in lines), lines)
