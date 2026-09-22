"""What a skill goal actually does, per profession shape (infra#3731).

No MySQL, no Discord, no worldserver: skillgoal.py is pure, so every branch
here is exercised by handing it the facts bridge.py would have read.

THE PROPERTY THAT MATTERS MOST is the last class in this file: a plan that
cannot progress must SAY so and must issue no order. This service's dominant
failure mode is a mechanism that reports health while doing nothing - that is
the whole of the defect this module was written to close - so "blocked implies
silent, and never the other way round" is checked over every shape rather than
per branch.
"""

import unittest

import craft
import craft_rhythm
import gatheraim
import goals
import professions
import skillgoal
from skillgoal import CRAFTED, FISHING, GATHERED


def plan(**over):
    """A crafting plan that works, so each test can break one thing.

    Og's Tailoring at 50 is a real, live state - he is the one character whose
    profession has actually moved (1 -> 50 under job='craft') - and
    craft.recipe_for(197, 50) is a real bracket (Linen Belt, spell 8776). A
    fixture built on a state the world has never been in would pass while
    proving nothing about the world.
    """
    kwargs = dict(
        skill_name="tailoring",
        skill_id=goals.SKILL_IDS["tailoring"],
        target=225,
        observed=50,
        cap=75,
        beneficiary="Og",
        standing="dungeon",
        stalls=0,
    )
    kwargs.update(over)
    return skillgoal.plan(**kwargs)


class ShapeTest(unittest.TestCase):
    """The three shapes must PARTITION every skill goals.py can parse.

    A skill that falls through would reach `plan` and raise, which is a crash
    in the goal supervisor's own loop. The partition is asserted against
    goals.SKILL_IDS rather than against a list here, so adding a profession to
    that table without deciding its shape fails this test.
    """

    def test_every_parseable_skill_has_a_shape(self):
        for name in goals.SKILL_IDS:
            with self.subTest(skill=name):
                self.assertIn(skillgoal.shape_for(name), (CRAFTED, GATHERED, FISHING))

    def test_the_shapes_agree_with_professions_own_sets(self):
        """The classification is professions.py's fact, not this module's. If
        these ever disagree, two files hold two answers to 'is mining a
        gathering trade' and the wrong one is whichever a reader finds first."""
        for name in professions.GATHERING:
            self.assertEqual(skillgoal.shape_for(name), GATHERED, name)
        for name in professions.CRAFTING:
            self.assertEqual(skillgoal.shape_for(name), CRAFTED, name)

    def test_fishing_is_not_filed_under_secondary(self):
        """First Aid and Cooking craft; Fishing does not. Filing all three
        together puts fishing's real blocker (no pole, no drive) behind the
        crafting path's reasoning, where nobody would find it."""
        self.assertEqual(skillgoal.shape_for("fishing"), FISHING)
        self.assertEqual(skillgoal.shape_for("first aid"), CRAFTED)
        self.assertEqual(skillgoal.shape_for("cooking"), CRAFTED)

    def test_a_skill_no_set_claims_raises(self):
        """Deliberately NOT the 'return nothing rather than invent a fallback'
        rule the rest of this codebase holds. A missing recipe bracket is a
        world fact; a skill name no profession set claims is goals.SKILL_IDS
        and professions.py having drifted, which is a code fault and must fail
        where it happens."""
        with self.assertRaises(KeyError):
            skillgoal.shape_for("basket weaving")


class CraftingPathTest(unittest.TestCase):
    """The one shape that works, and it is measured working: Og's Tailoring
    went 1 -> 50 and Ugga's Alchemy 1 -> 14 under job='craft', with
    mod-overseer logging each cast by name."""

    def test_outside_the_rhythm_it_asks_for_the_crafting_mode(self):
        got = plan(standing="dungeon")
        self.assertEqual(got.mode, craft_rhythm.MODE_CRAFT)
        self.assertEqual(got.blocked, "")

    def test_inside_the_rhythm_it_writes_nothing(self):
        """THE HANDOVER. craft_rhythm is the only pass that can see held
        reagent counts, so it must be the only writer for the alternation. A
        goal re-asserting job='craft' on its own 60-second clock against that
        pass's 300-second one is two opinions about one column, and they take
        turns undoing each other while the family stands at a counter."""
        for standing in (craft_rhythm.MODE_CRAFT, craft_rhythm.MODE_GATHER):
            with self.subTest(standing=standing):
                got = plan(standing=standing)
                self.assertEqual(got.mode, "")
                self.assertEqual(got.blocked, "")
                self.assertIn("craft_rhythm", got.why)

    def test_a_family_that_does_not_agree_is_left_alone(self):
        """'' from standing_mode means a fan-out is still settling. Writing
        into a half-landed order is how a family ends up split across two
        modes; asking again next cycle costs one minute."""
        got = plan(standing="")
        self.assertEqual(got.mode, "")
        self.assertEqual(got.blocked, "")

    def test_the_reason_names_the_recipe_it_expects_to_be_cast(self):
        """A plan that cannot name what it is about to do is indistinguishable
        from one that has lost track of the recipe."""
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 50)
        self.assertIn(str(recipe.spell_id), plan().why)
        self.assertIn(recipe.name, plan().why)

    def test_a_skill_this_character_is_not_assigned_is_refused(self):
        """craft.craft_errand walks professions.assigned and nothing else for
        a primary trade, so a goal for a trade the roster never gave this
        character can never produce an errand - it would sit on job='craft'
        casting somebody else's recipe."""
        got = plan(
            skill_name="blacksmithing",
            skill_id=goals.SKILL_IDS["blacksmithing"],
            observed=1,
            beneficiary="Og",
        )
        self.assertTrue(got.blocked)
        self.assertIn("professions.assigned", got.blocked)
        self.assertEqual(got.mode, "")

    def test_a_secondary_is_not_assignment_gated(self):
        """SECONDARY costs no primary slot and all five hold all three, so it
        is checked for EVERY name - that is craft.craft_errand's own rule and
        the reason this slice is worth more than any one primary."""
        got = plan(
            skill_name="first aid",
            skill_id=goals.SKILL_IDS["first aid"],
            observed=1,
            target=75,
            cap=75,
            beneficiary="Grug",
        )
        self.assertEqual(got.blocked, "")
        self.assertEqual(got.mode, craft_rhythm.MODE_CRAFT)

    def test_no_bracket_is_refused_rather_than_driven(self):
        """Enchanting has no craft.RECIPES entry at all. Driving it would put
        Og on job='craft' with craft_spell 0 - employed and casting nothing,
        which DriveCraft skips with a bare `continue` and no log line."""
        got = plan(
            skill_name="enchanting",
            skill_id=goals.SKILL_IDS["enchanting"],
            observed=1,
            target=75,
            cap=75,
        )
        self.assertTrue(got.blocked)
        self.assertIn("craft.RECIPES", got.blocked)
        self.assertEqual(got.mode, "")

    def test_a_blocked_secondary_names_its_own_wall(self):
        """All three secondaries are stuck behind DIFFERENT walls, and
        conflating them is how 'the secondaries are capped at Apprentice' came
        to be the accepted story when not one of them is capped. Cooking is
        blocked by RequiresSpellFocus 4, a Cooking Fire nothing lights."""
        got = plan(
            skill_name="cooking",
            skill_id=goals.SKILL_IDS["cooking"],
            observed=1,
            target=75,
            cap=75,
            beneficiary="Grug",
        )
        self.assertTrue(got.blocked)
        self.assertIn(professions.SECONDARY_BLOCKED["cooking"], got.blocked)

    def test_first_aid_past_its_bracket_is_refused(self):
        """Linen Bandage greys at 60 and every bandage above it is a trainer
        purchase no reachable trainer sells. 58 points of headroom is real;
        the 59th is not."""
        got = plan(
            skill_name="first aid",
            skill_id=goals.SKILL_IDS["first aid"],
            observed=70,
            target=75,
            cap=75,
            beneficiary="Grug",
        )
        self.assertTrue(got.blocked)
        self.assertEqual(got.mode, "")


class RankCapTest(unittest.TestCase):
    """A goal that parks at 75 for ever and reports healthy is the same defect
    in a new place, so the cap is refused out loud rather than driven."""

    def test_a_primary_at_its_cap_is_refused_and_names_the_blocker(self):
        got = plan(observed=75, cap=75, target=225)
        self.assertTrue(got.blocked)
        self.assertIn("mod-overseer#196", got.blocked)
        self.assertEqual(got.mode, "")

    def test_a_secondary_at_its_cap_cites_the_measured_refusal(self):
        """Worse than the primary case and refused by different C++ entirely:
        SkillStartedBySpell gates on IsPrimaryProfessionSkill, so no trainer in
        the world is ever an answer for skill 129, 185 or 356."""
        got = plan(
            skill_name="first aid",
            skill_id=goals.SKILL_IDS["first aid"],
            observed=75,
            cap=75,
            target=150,
            beneficiary="Grug",
        )
        self.assertIn(professions.SECONDARY_RANK_REFUSAL, got.blocked)

    def test_a_goal_inside_the_cap_is_not_a_cap_problem(self):
        self.assertEqual(plan(observed=50, cap=75, target=75).blocked, "")

    def test_a_goal_exactly_at_the_cap_is_completion_not_a_block(self):
        """target == cap is reachable, and reconcile completes it before this
        module is ever asked. Refusing it here would refuse the one skill goal
        that can actually finish."""
        self.assertEqual(plan(observed=74, cap=75, target=75).blocked, "")

    def test_an_unread_cap_makes_no_cap_argument(self):
        """0 is 'no character_skills row', which is a character who has never
        held the trade. Inferring a ceiling of zero from that would refuse
        every goal for a trade somebody is about to learn."""
        self.assertEqual(plan(observed=50, cap=0, target=225).blocked, "")


class GatheringPathTest(unittest.TestCase):
    """Inverted by infra#3789: a gathering goal now DRIVES when it has a field.

    This class used to assert the refusal and call it the deliverable, which was
    right while all three holes were open. They are closed: `nc +loot` is
    granted (infra#3769, measured at 2,356 issuances), the per-node band is
    projected from the worldserver's own Lock.dbc because `acore_world.lock_dbc`
    is empty (`gatherband`), and the zone is chosen by `gatheraim`.

    THE THREE STATES ARE KEPT APART ON PURPOSE. `destination=None` means nobody
    surveyed; a refused Choice means somebody surveyed and the world said no;
    a chosen Choice means go. Collapsing the first two is how the old refusal
    came to tell the operator something false for five days, in Discord.
    """

    @staticmethod
    def _field(zone=148, lock=38, nodes=3, level=12):
        rows = [
            gatheraim.Spawn(
                map_id=1, zone_id=zone, x=float(i), y=0.0, z=5.0, lock_id=lock
            )
            for i in range(nodes)
        ]
        return gatheraim.choose(
            skills={"Grog": {"mining": 1}},
            standing_on=1,
            spawns=rows,
            family_level=60,
            zone_levels={zone: level},
        )

    def test_a_surveyed_field_drives_instead_of_refusing(self):
        got = plan(
            skill_name="mining",
            skill_id=goals.SKILL_IDS["mining"],
            observed=8,
            target=75,
            cap=75,
            beneficiary="Grug",
            standing="quest",
            destination=self._field(),
        )
        self.assertFalse(got.blocked)
        self.assertEqual(got.mode, skillgoal.MODE_GATHER)
        self.assertIn("zone 148", got.why)

    def test_the_mode_is_craft_rhythms_own_gather_constant(self):
        """job='quest' IS MODE_GATHER.

        Writing anything else reads to mod_overseer.cpp as "the quest drive
        stands down, full stop" - so this asserts the constant rather than the
        string, and asserts the string too, because the two drifting apart is
        the failure that would stand the whole family down.
        """
        self.assertEqual(skillgoal.MODE_GATHER, "quest")
        got = plan(
            skill_name="mining",
            skill_id=goals.SKILL_IDS["mining"],
            observed=8,
            target=75,
            cap=75,
            beneficiary="Grug",
            standing="quest",
            destination=self._field(),
        )
        self.assertEqual(got.mode, "quest")

    def test_a_refused_destination_surfaces_the_worlds_reason(self):
        """Not the generic sentence - the specific one the survey produced."""
        nowhere = gatheraim.choose(
            skills={"Grog": {"mining": 1}},
            standing_on=1,
            spawns=[],
            family_level=60,
            zone_levels={},
        )
        got = plan(
            skill_name="mining",
            skill_id=goals.SKILL_IDS["mining"],
            observed=8,
            target=75,
            cap=75,
            beneficiary="Grug",
            standing="quest",
            destination=nowhere,
        )
        self.assertTrue(got.blocked)
        self.assertEqual(got.mode, "")
        self.assertIn("no zone on map 1", got.blocked)

    def test_no_survey_is_distinct_from_the_world_saying_no(self):
        got = plan(
            skill_name="mining",
            skill_id=goals.SKILL_IDS["mining"],
            observed=8,
            target=75,
            cap=75,
            beneficiary="Grug",
            standing="quest",
            destination=None,
        )
        self.assertTrue(got.blocked)
        self.assertIn("did not run the survey", got.blocked)

    def test_the_refusal_no_longer_claims_loot_was_never_granted(self):
        """The stale sentence that printed to Discord for five days.

        infra#3769 closed on measurement. A refusal that outlives its cause is
        worse than no refusal, because it sends the next reader at a fixed bug.
        """
        got = plan(
            skill_name="mining",
            skill_id=goals.SKILL_IDS["mining"],
            observed=8,
            target=75,
            cap=75,
            beneficiary="Grug",
            standing="quest",
            destination=None,
        )
        self.assertNotIn("never been issued", got.blocked)
        self.assertIn("infra#3789", got.blocked)

    def test_every_gathering_skill_still_answers_without_a_destination(self):
        """Including skinning, which no destination can ever serve."""
        for name in sorted(professions.GATHERING):
            with self.subTest(skill=name):
                got = plan(
                    skill_name=name,
                    skill_id=goals.SKILL_IDS[name],
                    observed=8,
                    target=75,
                    cap=75,
                    beneficiary="Grug",
                    standing="quest",
                )
                self.assertTrue(got.blocked)
                self.assertEqual(got.mode, "")

    def test_mining_says_out_loud_that_the_smelt_exists(self):
        """A refusal a reader can disprove in one grep is one nobody trusts the
        next time. Smelt Copper (2657) is real, the forge walk is real, and
        neither starts an ore supply - so the refusal says all three."""
        got = plan(
            skill_name="mining",
            skill_id=goals.SKILL_IDS["mining"],
            observed=8,
            target=75,
            cap=75,
            beneficiary="Grug",
        )
        self.assertIn(skillgoal.SMELT_CAVEAT, got.blocked)

    def test_a_gathering_skill_with_no_smelt_does_not_claim_one(self):
        """Herbalism and Skinning have no craft.RECIPES bracket at all, so the
        smelt paragraph must not be attached to them - a refusal that cites a
        mechanism the skill does not have sends the reader to the wrong file."""
        got = plan(
            skill_name="herbalism",
            skill_id=goals.SKILL_IDS["herbalism"],
            observed=133,
            target=225,
            cap=225,
            beneficiary="Ugga",
        )
        self.assertNotIn(skillgoal.SMELT_CAVEAT, got.blocked)


class FishingPathTest(unittest.TestCase):
    def test_fishing_is_refused_and_names_its_issue(self):
        got = plan(
            skill_name="fishing",
            skill_id=goals.SKILL_IDS["fishing"],
            observed=1,
            target=75,
            cap=75,
            beneficiary="Bork",
        )
        self.assertTrue(got.blocked)
        self.assertIn("infra#3733", got.blocked)
        self.assertEqual(got.mode, "")

    def test_it_is_refused_before_the_recipe_table_is_consulted(self):
        """Answering 'no bracket' would be true and useless - it would send a
        reader to craft.RECIPES to add one, which cannot help, because fishing
        consumes nothing and creates nothing."""
        got = plan(
            skill_name="fishing",
            skill_id=goals.SKILL_IDS["fishing"],
            observed=1,
            target=75,
            cap=75,
            beneficiary="Bork",
        )
        self.assertEqual(got.blocked, skillgoal.FISHING_REFUSAL)
        self.assertNotIn("has no bracket covering", got.blocked)


class StalledTest(unittest.TestCase):
    """The drive is right and the number is not moving - a different statement
    from 'blocked', and it wants a different response from a reader."""

    def test_a_fresh_goal_is_not_stalled(self):
        self.assertEqual(plan(stalls=0).stalled, "")

    def test_a_goal_short_of_the_threshold_is_not_stalled(self):
        self.assertEqual(plan(stalls=goals.SKILL_BARREN_CYCLES - 1).stalled, "")

    def test_a_barren_goal_says_so_without_claiming_to_be_blocked(self):
        got = plan(stalls=goals.SKILL_BARREN_CYCLES)
        self.assertTrue(got.stalled)
        self.assertEqual(got.blocked, "", "starvation is not a permanent refusal")

    def test_it_names_both_causes_and_how_to_tell_them_apart(self):
        """NAMING ONLY REAGENTS IS A MISDIAGNOSIS, and it is the live one.

        Og's Tailoring is deadlocked right now for the OTHER reason: craft.py
        names Linen Belt (8776), which acore_world.trainer_spell shows is a
        trainer purchase he has never made, DriveCraft logs 'does not know the
        recipe' and clears craft_spell, and the planner re-writes it five
        minutes later - for ever. A sentence that said 'almost always reagents'
        would have sent a reader to count his bags, and he is holding 151 Bolts
        of Linen Cloth. The two causes are separated by one grep, so the
        sentence says which grep."""
        said = plan(stalls=goals.SKILL_BARREN_CYCLES).stalled
        self.assertIn("does not know the recipe", said)
        self.assertIn("infra#3689", said)
        self.assertIn("craft_rhythm", said)
        self.assertIn("infra#3696", said)

    def test_it_does_not_decide_between_them_itself(self):
        """Only the worldserver's own recorded answer can say which - that is
        craft.py's infra#3695 rule, written after a guard built on
        character_spell refused four characters that were crafting fine."""
        said = plan(stalls=goals.SKILL_BARREN_CYCLES).stalled
        self.assertIn("infra#3695", said)

    def test_a_blocked_plan_does_not_also_nag_about_stalling(self):
        """Two sentences for one state is how a channel becomes unreadable.
        A blocked goal has no drive to be starved."""
        got = plan(
            skill_name="fishing",
            skill_id=goals.SKILL_IDS["fishing"],
            observed=1,
            target=75,
            cap=75,
            beneficiary="Bork",
            stalls=goals.SKILL_BARREN_CYCLES * 3,
        )
        self.assertEqual(got.stalled, "")


class EveryPlanIsHonestTest(unittest.TestCase):
    """The property the whole module exists for, checked across every shape.

    A half-built path that reports healthy is worse than an unbuilt one. So:
    blocked implies no order; every plan explains itself; and nothing anywhere
    can return a combat strategy.
    """

    CASES = (
        # (skill, observed, cap, target, who)
        ("tailoring", 50, 75, 225, "Og"),  # works
        ("tailoring", 75, 75, 225, "Og"),  # rank cap
        ("enchanting", 1, 75, 75, "Og"),  # no bracket
        ("blacksmithing", 1, 75, 75, "Og"),  # unassigned
        ("blacksmithing", 1, 75, 75, "Grug"),  # assigned, works
        ("first aid", 1, 75, 75, "Grug"),  # secondary, works
        ("first aid", 70, 75, 75, "Grug"),  # secondary, past bracket
        ("cooking", 1, 75, 75, "Grug"),  # secondary, focus wall
        ("mining", 8, 75, 75, "Grug"),  # gathering + smelt
        ("herbalism", 133, 225, 225, "Ugga"),  # gathering, no smelt
        ("skinning", 12, 75, 75, "Bork"),  # gathering, no smelt
        ("fishing", 1, 75, 75, "Bork"),  # fishing
    )

    def _plans(self):
        for skill, observed, cap, target, who in self.CASES:
            for standing in ("", "quest", "craft", "dungeon", "train"):
                yield (
                    skill,
                    standing,
                    skillgoal.plan(
                        skill_name=skill,
                        skill_id=goals.SKILL_IDS[skill],
                        target=target,
                        observed=observed,
                        cap=cap,
                        beneficiary=who,
                        standing=standing,
                    ),
                )

    def test_a_blocked_plan_never_issues_an_order(self):
        for skill, standing, got in self._plans():
            if got.blocked:
                with self.subTest(skill=skill, standing=standing):
                    self.assertEqual(
                        got.mode,
                        "",
                        "%s is blocked and still asked for job=%s, which is "
                        "theatre: the order cannot help" % (skill, got.mode),
                    )

    def test_every_plan_says_why(self):
        for skill, standing, got in self._plans():
            with self.subTest(skill=skill, standing=standing):
                self.assertTrue(
                    got.blocked or got.why,
                    "a verdict that cannot say why is a silent idle",
                )

    def test_no_plan_ever_names_a_combat_strategy(self):
        """The defect, stated as an invariant. `grind` is what sent the family
        to die to Wastewander Assassins in Tanaris while a mining goal reported
        itself healthy."""
        for skill, standing, got in self._plans():
            with self.subTest(skill=skill, standing=standing):
                blob = " ".join((got.mode, got.why, got.blocked, got.stalled))
                self.assertNotIn("+grind", blob)
                self.assertNotIn("nc +", got.mode)

    def test_the_only_modes_it_may_ask_for_are_the_rhythm_modes(self):
        """A mode outside jobs.IMPLEMENTED is refused by _set_job and stands
        the quest drive down on the way (infra#3338); a mode inside it but
        outside the rhythm would be a standing order this module knows nothing
        about."""
        for skill, standing, got in self._plans():
            with self.subTest(skill=skill, standing=standing):
                self.assertIn(got.mode, ("",) + skillgoal.RHYTHM_MODES)

    def test_the_report_line_carries_the_verdict(self):
        """Logged every pass, decided or not: a pass that speaks only when it
        acts is indistinguishable from a pass that has died."""
        for skill, standing, got in self._plans():
            with self.subTest(skill=skill, standing=standing):
                line = skillgoal.report(got)
                self.assertIn(skill, line)
                self.assertIn(got.shape, line)
                if got.blocked:
                    self.assertIn("BLOCKED", line)


if __name__ == "__main__":
    unittest.main()
