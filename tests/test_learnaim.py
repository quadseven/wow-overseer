"""Finishing a learn errand that is over, and walking one nobody is on.

infra#3686. `overseer_roster.learn_skill` non-zero makes mod-overseer refuse
every travel aim for that character, and the only thing that clears it inside
the worldserver is arriving at a trainer - which needs a travel aim. One
character carried a settled skinning errand for ten days and the family simply
stood around.

THE MOST IMPORTANT CLASS HERE IS THE ONE THAT ASSERTS A RULE IS ABSENT.
`ThereIsNoHoldsRule` pins, against mod_overseer.cpp's own text, that holding a
skill is NOT evidence an errand is finished - mod-overseer#74 removed exactly
that predicate from `TrainOnArrival` because a character at its rank ceiling
holds the skill and is not done. A reconcile that reintroduced it would stop
every profession in the family at the tier it already has, and nothing would
fail: the roster would simply go quiet.

Nothing here has been run against a live worldserver, and nothing in this file
claims it has.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import goals  # noqa: E402
import learnaim  # noqa: E402
import professions  # noqa: E402
import trainjob  # noqa: E402
import travel  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

SKINNING = goals.SKILL_IDS["skinning"]
LEATHERWORKING = goals.SKILL_IDS["leatherworking"]
TAILORING = goals.SKILL_IDS["tailoring"]
ALCHEMY = goals.SKILL_IDS["alchemy"]
HERBALISM = goals.SKILL_IDS["herbalism"]
FIRST_AID = goals.SKILL_IDS["first aid"]


def row(character, **kw):
    return learnaim.Row(character=character, **kw)


class TheVocabularyAgrees(unittest.TestCase):
    def test_the_trainer_role_is_read_from_travel_not_spelled(self):
        self.assertIn(learnaim.TRAINER_ROLE, travel.ROLES)
        self.assertEqual(professions.TRAINER_ROLE, learnaim.TRAINER_ROLE)
        self.assertEqual(trainjob.TRAINER_ROLE, learnaim.TRAINER_ROLE)

    def test_the_secondary_ids_are_read_from_trainjob_not_restated(self):
        self.assertEqual(tuple(sorted(trainjob.SECONDARY.values())),
                         learnaim.SECONDARY_IDS)

    def test_the_two_clear_reasons_are_distinct_sentences(self):
        self.assertNotEqual(learnaim.SETTLED, learnaim.UNASSIGNED)
        self.assertTrue(learnaim.SETTLED.strip())
        self.assertTrue(learnaim.UNASSIGNED.strip())


class ThereIsNoHoldsRule(unittest.TestCase):
    """mod-overseer#74 REMOVED "holds the skill means done" from TrainOnArrival
    and the comment explaining why is still in the file. Holding a skill and
    holding it at its ceiling are different facts, and only a trainer selling
    the next tier tells them apart. This class is the guard against somebody
    re-deriving the obvious rule from first principles, because nothing would
    break loudly if they did - the family would just stop advancing.
    """

    @classmethod
    def setUpClass(cls):
        cls.cpp = MODULE.read_text(encoding="utf-8", errors="replace")
        cls.source = (pathlib.Path(learnaim.__file__)).read_text(encoding="utf-8")

    def test_the_cpp_still_refuses_to_treat_holding_as_finished(self):
        self.assertIn("NOT A SHORTCUT ANY MORE", self.cpp)
        self.assertIn("bool const alreadyHasSkill = bot->HasSkill(skill);", self.cpp)

    def test_this_module_never_reads_a_held_skill_set(self):
        for banned in ("holds", "HasSkill", "character_skills"):
            self.assertNotIn(
                "row.%s" % banned, self.source,
                "learnaim must not decide from what a character holds (#74)",
            )
        self.assertNotIn("holds", [f.name for f in learnaim.Row.__dataclass_fields__.values()])

    def test_a_character_at_its_ceiling_keeps_its_errand(self):
        """The live shape: herbalism held at 132 against a max of 225, with the
        errand standing to buy the next tier. A holds-based rule would delete
        it; this one leaves it alone and lets the trainer answer."""
        r = row("Ugga", learn_skill=HERBALISM, wanted=(ALCHEMY, HERBALISM),
                traded=(HERBALISM,), settled=(), travel_npc="", leads=True)
        self.assertEqual("", learnaim.finished(r))
        self.assertEqual(HERBALISM, learnaim.outstanding(r))

class FinishedAnswersFromWhatWasDecided(unittest.TestCase):
    def test_the_live_case_that_froze_the_family(self):
        """overseer_trade id 126: Bork, learn skinning, settled 2026-09-03. The
        roster still named skill 393 on 2026-09-13. The settled row is what
        says the errand was carried out - not the skill map, which describes
        the world's shape rather than this errand's outcome."""
        bork = row("Bork", learn_skill=SKINNING,
                   wanted=(LEATHERWORKING, SKINNING),
                   traded=(LEATHERWORKING, SKINNING),
                   settled=(LEATHERWORKING, SKINNING))
        self.assertEqual(learnaim.SETTLED, learnaim.finished(bork))

    def test_a_settled_row_for_a_different_skill_says_nothing(self):
        r = row("Bork", learn_skill=SKINNING, wanted=(LEATHERWORKING, SKINNING),
                traded=(LEATHERWORKING, SKINNING), settled=(LEATHERWORKING,))
        self.assertEqual("", learnaim.finished(r))

    def test_a_planned_row_is_an_errand_not_a_record_of_one(self):
        r = row("Og", learn_skill=TAILORING, wanted=(TAILORING,),
                traded=(TAILORING,), settled=())
        self.assertEqual("", learnaim.finished(r))

    def test_a_skill_the_roster_never_asked_for_is_TrainOnArrivals_refusal(self):
        r = row("Og", learn_skill=ALCHEMY, wanted=(TAILORING,))
        self.assertEqual(learnaim.UNASSIGNED, learnaim.finished(r))

    def test_no_errand_is_nothing_to_decide(self):
        self.assertEqual("", learnaim.finished(row("Grog", wanted=(TAILORING,))))

    def test_an_empty_permission_column_is_not_a_denial(self):
        """`professions` empty means _write_declared_professions has not
        written this row - a realm missing the column, a degraded cycle - and
        reading it as "the roster asks for nothing" would clear every
        outstanding errand in the family the first time that write failed."""
        r = row("Grug", learn_skill=TAILORING, wanted=())
        self.assertEqual("", learnaim.finished(r))


class ASecondaryErrandIsLiftedNotPreserved(unittest.TestCase):
    """infra#3701, and the reversal of this module's original exemption.

    A secondary learn errand used to be EXEMPT from the staleness test, on the
    reasoning that it asks for a rank rather than a start and trainers do sell
    ranks. Trainers do; mod-overseer cannot buy one. `SkillStartedBySpell`
    gates on `IsPrimaryProfessionSkill` (mod_overseer.cpp:10314), false for
    First Aid, Cooking and Fishing, so the trainer resolve matches no spawn
    (:10058) and `TrainerSpellForSkill` matches no spell (:10369).

    That makes the exemption an outage rather than a kindness: the world can
    only clear `learn_skill` from `TrainOnArrival`, which the character can
    never reach, and a non-zero `learn_skill` makes `TravelAimBook::Claim`
    refuse EVERY travel aim for that character. Exempting it meant nothing
    could lift the fence, ever.
    """

    def test_a_secondary_errand_is_over_the_moment_it_exists(self):
        r = row("Ugga", learn_skill=FIRST_AID, wanted=(ALCHEMY, HERBALISM))
        self.assertEqual(learnaim.SECONDARY, learnaim.finished(r))
        self.assertEqual(0, learnaim.outstanding(r))

    def test_all_three_secondaries_are_lifted(self):
        for skill in learnaim.SECONDARY_IDS:
            r = row("Ugga", learn_skill=skill, wanted=(ALCHEMY, HERBALISM))
            self.assertEqual(learnaim.SECONDARY, learnaim.finished(r), skill)

    def test_it_is_lifted_even_when_the_column_is_empty(self):
        """An empty `professions` column exempts a PRIMARY, because absence
        means the write failed rather than that nothing is wanted. A secondary
        is refused by the worldserver either way, so that exemption must not
        rescue it."""
        r = row("Ugga", learn_skill=FIRST_AID, wanted=())
        self.assertEqual(learnaim.SECONDARY, learnaim.finished(r))

    def test_it_is_lifted_even_if_the_column_somehow_carries_it(self):
        """Defence in depth. `wanted_ids` cannot emit a secondary and a test
        pins that, but this module reads a column the worldserver also writes,
        so it must not depend on the column being sane."""
        r = row("Ugga", learn_skill=FIRST_AID, wanted=(FIRST_AID, ALCHEMY))
        self.assertEqual(learnaim.SECONDARY, learnaim.finished(r))

    def test_the_clear_is_actually_written(self):
        r = row("Ugga", learn_skill=FIRST_AID, wanted=(ALCHEMY,), leads=True)
        plan = learnaim.plan([r])
        self.assertEqual(("Ugga",), tuple(s.character for s in plan.clear))
        self.assertEqual("", plan.aim, "a secondary must never be walked")
        sql = learnaim.statements(plan)
        self.assertEqual(1, len(sql))
        self.assertIn("learn_skill = 0", sql[0][0])
        self.assertEqual(("Ugga", FIRST_AID), sql[0][1])

    def test_a_primary_is_still_left_alone(self):
        """The reversal must not catch mod-overseer#74's case: a character
        holding a primary at its ceiling is not finished, it is stuck, and only
        a trainer selling the next tier tells those apart."""
        r = row("Ugga", learn_skill=HERBALISM, wanted=(ALCHEMY, HERBALISM))
        self.assertEqual("", learnaim.finished(r))
        self.assertEqual(HERBALISM, learnaim.outstanding(r))

    def test_the_permission_column_never_carries_one_anyway(self):
        ids = professions.wanted_ids("Ugga")
        self.assertNotIn(str(FIRST_AID), ids.split(","))

    def test_a_settled_secondary_trade_still_ends_it(self):
        r = row("Ugga", learn_skill=FIRST_AID, wanted=(ALCHEMY,),
                traded=(FIRST_AID,), settled=(FIRST_AID,))
        self.assertIn(learnaim.finished(r), (learnaim.SECONDARY, learnaim.SETTLED))

class TheBornFrozenErrandIsCarriedOutNotDiscarded(unittest.TestCase):
    """mod-overseer's AimLearnAt writes learn_skill with no trade row behind it
    and never writes travel_npc, so a derived errand is born with no journey
    attached - and the fence then refuses every other aim for that character.
    Clearing it would throw away a real instruction. Aiming it carries the
    instruction out and lets TrainOnArrival reach its own verdict.
    """

    def test_an_errand_with_no_trade_row_is_derived(self):
        r = row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), traded=())
        self.assertTrue(learnaim.derived(r))

    def test_an_errand_a_trade_plan_wrote_is_not(self):
        r = row("Grug", learn_skill=TAILORING, wanted=(TAILORING,),
                traded=(TAILORING,))
        self.assertFalse(learnaim.derived(r))

    def test_the_leader_with_an_unwalked_errand_is_aimed(self):
        p = learnaim.plan([
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=True),
            row("Grog", leads=False),
        ])
        self.assertEqual("Grug", p.aim)
        self.assertEqual(TAILORING, p.skill)
        self.assertEqual((), p.clear)

    def test_a_follower_is_never_aimed_and_is_named_as_waiting(self):
        """AimedMover answers RefuseInFormation for a follower and says the
        remedy itself: aim the leader. Writing the column anyway would be the
        written-and-unread failure this whole issue is about, self-inflicted."""
        p = learnaim.plan([
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=False),
            row("Grog", leads=True),
        ])
        self.assertEqual("", p.aim)
        self.assertEqual(("Grug",), p.waiting)

    def test_only_one_character_is_aimed_and_the_rest_wait(self):
        p = learnaim.plan([
            row("Bork", learn_skill=SKINNING, wanted=(SKINNING,), leads=True),
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=True),
        ])
        self.assertEqual("Bork", p.aim)
        self.assertEqual(("Grug",), p.waiting)

    def test_a_character_already_walking_somewhere_is_left_alone(self):
        """Aimed at a vendor by the economy, at a door by a run, or at a
        trainer by _write_trade_errand - all of them own the column, and
        writing over one is the second-writer collision this codebase has
        already paid for on exactly this column."""
        for aim in ("vendor", "at:1:-7219,-2948,6", learnaim.TRAINER_ROLE):
            p = learnaim.plan([
                row("Grug", learn_skill=TAILORING, wanted=(TAILORING,),
                    leads=True, travel_npc=aim),
            ])
            self.assertEqual("", p.aim, aim)
            self.assertEqual((), p.waiting, aim)

    def test_an_errand_that_is_over_is_cleared_and_never_also_aimed(self):
        p = learnaim.plan([
            row("Bork", learn_skill=SKINNING, wanted=(SKINNING,), leads=True,
                traded=(SKINNING,), settled=(SKINNING,)),
        ])
        self.assertEqual(("Bork",), tuple(s.character for s in p.clear))
        self.assertEqual("", p.aim)
        self.assertEqual((), p.waiting)


class TheLeadIsBorrowedOnlyForAnErrandNothingElseCanSee(unittest.TestCase):
    def test_a_derived_errand_makes_its_character_the_traveller(self):
        rows = [row("Grug", learn_skill=TAILORING, wanted=(TAILORING,)),
                row("Grog")]
        self.assertEqual("Grug", learnaim.traveller(rows))

    def test_the_borrow_survives_the_aim_it_asked_for(self):
        """The aim fills travel_npc, and if that ended the borrow the lead
        would snap back the same cycle and the character would never walk."""
        rows = [row("Grug", learn_skill=TAILORING, wanted=(TAILORING,),
                    travel_npc=learnaim.TRAINER_ROLE)]
        self.assertEqual("Grug", learnaim.traveller(rows))

    def test_a_trade_backed_errand_borrows_nothing_here(self):
        """_errand_traveller already borrows for those and bounds it with
        ERRAND_LEAD_HOURS. Taking the lead for one here would route around a
        bound somebody wrote for a reason."""
        rows = [row("Og", learn_skill=TAILORING, wanted=(TAILORING,),
                    traded=(TAILORING,))]
        self.assertEqual("", learnaim.traveller(rows))

    def test_a_finished_errand_borrows_nothing(self):
        rows = [row("Bork", learn_skill=SKINNING, wanted=(SKINNING,),
                    settled=(SKINNING,))]
        self.assertEqual("", learnaim.traveller(rows))

    def test_nobody_is_the_resting_answer(self):
        self.assertEqual("", learnaim.traveller([row("Grog"), row("Og")]))
        self.assertEqual("", learnaim.traveller([]))

class TheStatementsAreBoundAndAreCompareAndSwaps(unittest.TestCase):
    def test_the_clear_only_lands_on_the_value_it_read(self):
        """Without `AND learn_skill = %s` this would blank whatever AimLearnAt
        wrote between the read and the write - a clear that erases a brand new
        errand it never looked at."""
        p = learnaim.plan([
            row("Bork", learn_skill=SKINNING, wanted=(SKINNING,),
                traded=(SKINNING,), settled=(SKINNING,)),
        ])
        sql, params = learnaim.statements(p)[0]
        self.assertIn("SET learn_skill = 0", sql)
        self.assertIn("WHERE name = %s AND learn_skill = %s", sql)
        self.assertEqual(("Bork", SKINNING), params)

    def test_the_aim_only_lands_on_an_empty_column(self):
        """The same guard _write_trade_errand's ECONOMY_ERRANDS branch applies,
        written the same way: an economy pass or a dungeon Claim that took the
        column between the read and this write keeps it."""
        p = learnaim.plan([
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=True),
        ])
        sql, params = learnaim.statements(p)[0]
        self.assertIn("SET travel_npc = %s", sql)
        self.assertIn("AND travel_npc = ''", sql)
        self.assertIn("AND learn_skill = %s", sql)
        self.assertEqual((learnaim.TRAINER_ROLE, "Grug", TAILORING), params)

    def test_no_name_no_skill_and_no_keyword_is_interpolated(self):
        p = learnaim.plan([
            row("Bork", learn_skill=SKINNING, wanted=(SKINNING,),
                traded=(SKINNING,), settled=(SKINNING,)),
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=True),
        ])
        for sql, _ in learnaim.statements(p):
            for value in ("Bork", "Grug", str(SKINNING), str(TAILORING),
                          learnaim.TRAINER_ROLE):
                self.assertNotIn(value, sql)

    def test_the_clears_run_before_the_aim(self):
        p = learnaim.plan([
            row("Bork", learn_skill=SKINNING, wanted=(SKINNING,),
                traded=(SKINNING,), settled=(SKINNING,)),
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=True),
        ])
        written = learnaim.statements(p)
        self.assertEqual(2, len(written))
        self.assertIn("learn_skill = 0", written[0][0])
        self.assertIn("travel_npc", written[1][0])

    def test_nothing_to_do_is_no_statements_at_all(self):
        self.assertEqual([], learnaim.statements(learnaim.Plan()))


class TheReportSaysWhatHappenedAndWhy(unittest.TestCase):
    def test_a_clear_carries_its_consequence(self):
        p = learnaim.plan([
            row("Bork", learn_skill=SKINNING, wanted=(SKINNING,),
                traded=(SKINNING,), settled=(SKINNING,)),
        ])
        line = learnaim.report(p)
        self.assertIn("Bork", line)
        self.assertIn(str(SKINNING), line)
        self.assertIn("travel aim", line)

    def test_an_aim_never_claims_anybody_learned_anything(self):
        p = learnaim.plan([
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=True),
        ])
        line = learnaim.report(p)
        self.assertIn("Grug", line)
        self.assertIn("Arriving is not learning", line)
        for lie in ("has learned", "now knows", "trained "):
            self.assertNotIn(lie, line)

    def test_a_stranded_follower_is_named_even_though_nothing_was_written(self):
        p = learnaim.plan([
            row("Grug", learn_skill=TAILORING, wanted=(TAILORING,), leads=False),
            row("Grog", leads=True),
        ])
        self.assertEqual([], learnaim.statements(p))
        self.assertIn("Grug", learnaim.report(p))

    def test_silence_is_the_empty_answer(self):
        self.assertEqual("", learnaim.report(learnaim.Plan()))

class TheBridgeReallyRunsIt(unittest.TestCase):
    """A pure module with no caller is the failure this one exists to fix,
    arrived at from the other side: travel.aim_statements was written, correct
    and uncalled, for months (infra#3270), and learn_skill sat stale for ten
    days because the clear that should have existed did not. Pinned by source
    text, the same way test_trainjob pins the train drive.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8", errors="replace")

    def _protect_cycle(self):
        cycle = self.source[self.source.index("async def _protect_characters(self)"):]
        return cycle[:cycle.index("async def _share_quests_loop")]

    def test_the_bridge_imports_the_module(self):
        self.assertIn("import learnaim", self.source)

    def test_the_pass_exists_and_is_called(self):
        self.assertIn("async def _reconcile_learn_aims(self)", self.source)
        self.assertIn("await self._reconcile_learn_aims()", self.source)

    def test_it_runs_on_the_protect_cycle(self):
        """Every ten minutes, not once at startup. Both writers of the column
        keep writing, so a one-shot pass would fix the roster it found and
        miss every one after it."""
        self.assertIn("await self._reconcile_learn_aims()", self._protect_cycle())

    def test_it_runs_after_the_permission_and_after_the_lead(self):
        """learnaim measures one clear reason against the `professions` column
        and gates the aim on the `lead` column. Reading either before it is
        written would decide this cycle against last cycle's answer."""
        cycle = self._protect_cycle()
        at = cycle.index("await self._reconcile_learn_aims()")
        self.assertLess(cycle.index("_write_declared_professions"), at)
        self.assertLess(cycle.index("_mark_party_leader"), at)

    def test_the_writes_are_the_pure_modules_own(self):
        self.assertIn("learnaim.statements(learn_plan)", self.source)
        self.assertIn("_run_learn_aim_plan", self.source)

    def test_the_lead_is_borrowed_through_head_now(self):
        """The aim is gated on `lead`, so without this the pass would only ever
        act on a character that was already leading for some other reason - and
        the born-frozen errand it exists for is on whoever mod-overseer picked,
        not on whoever bonds did."""
        self.assertIn("def _derived_errand_traveller()", self.source)
        self.assertIn("learnaim.traveller(_learn_aim_rows())", self.source)
        self.assertIn(
            "return (_train_traveller() or _errand_traveller()\n"
            "            or _derived_errand_traveller()\n"
            "            or bonds.head_of_family())",
            self.source,
        )

    def test_the_borrow_is_the_weakest_claim_on_the_lead(self):
        """An order a person just gave and a trade the family decided both
        outrank an errand mod-overseer wrote for itself."""
        head = self.source[self.source.index("def _head_now()"):]
        head = head[:head.index("def _protected_guids")]
        self.assertLess(head.index("_train_traveller()"),
                        head.index("_derived_errand_traveller()"))
        self.assertLess(head.index("_errand_traveller()"),
                        head.index("_derived_errand_traveller()"))

    def test_the_reads_do_not_join_across_the_collation_split(self):
        """overseer_roster is utf8mb4_unicode_ci and overseer_trade is
        utf8mb4_0900_ai_ci. Two reads and a match in Python removes the
        question; a join here would need an explicit COLLATE or raise 1267
        every cycle."""
        reader = self.source[self.source.index("def _learn_aim_rows()"):]
        reader = reader[:reader.index("def _derived_errand_traveller()")]
        self.assertIn("FROM overseer_trade", reader)
        self.assertIn("FROM overseer_roster", reader)
        # The docstring and the comments say the word "join" while explaining
        # why there is not one, so the assertion is made against the CODE: the
        # body past the docstring, minus every comment line.
        body = reader[reader.index('"""', reader.index('"""') + 3) + 3:]
        code = "\n".join(
            line for line in body.split("\n") if not line.strip().startswith("#")
        )
        self.assertNotIn("JOIN", code.upper())
        self.assertNotIn("COLLATE", code.upper())

    def test_a_failed_reconcile_does_not_cost_the_rest_of_the_protect_cycle(self):
        """infra#3173's lesson again: this sits in the middle of a cycle that
        still has the spec tabs and the randomize guards to do."""
        block = self.source[self.source.index("async def _reconcile_learn_aims(self)"):]
        block = block[:block.index("async def _conjure")]
        self.assertIn("except Exception:", block)
        self.assertIn("log.exception", block)

    def test_the_reads_and_the_writes_are_guarded_for_a_realm_without_them(self):
        # END MARKERS ARE `def` LINES, NOT COMMENTS. This second one read
        # `# WHO THE PARTY FOLLOWS` until infra#3715 retired the HOMEWARD_LEAD
        # block that comment introduced, and the test then errored with
        # "substring not found" - which says nothing about the guard it exists
        # to check. A definition is the real end of the block above it.
        for signature, end in (
            ("def _learn_aim_rows()", "def _derived_errand_traveller()"),
            ("def _run_learn_aim_plan(statements)", "def _head_now()"),
        ):
            block = self.source[self.source.index(signature):]
            block = block[:block.index(end)]
            self.assertIn("(1054, 1146)", block, signature)


if __name__ == "__main__":
    unittest.main()