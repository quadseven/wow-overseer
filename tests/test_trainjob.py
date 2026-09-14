"""The `train` job mode: what it drives, and what it refuses to drive.

Two halves, and the second is the one that matters. The pure decisions are
ordinary unit tests. The last class is a CONTRACT TEST OVER bridge.py's SOURCE
TEXT, in the pattern test_jobs.py established for the C++ side: `jobs.IMPLEMENTED`
is a claim that setting a mode changes behaviour, and a claim whose branch has
been deleted is exactly the drift that had the overseer answering "NOT BUILT
YET" to an order it was about to carry out. `train`'s branch lives in Python
rather than in mod_overseer.cpp, so it is pinned here rather than there - but it
is pinned the same way and for the same reason.

Nothing here has been run against a live worldserver, and nothing in this file
claims it has.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import goals  # noqa: E402
import jobs  # noqa: E402
import trainjob  # noqa: E402
import travel  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

TAILORING = goals.SKILL_IDS["tailoring"]
JEWELCRAFTING = goals.SKILL_IDS["jewelcrafting"]
INSCRIPTION = goals.SKILL_IDS["inscription"]
FISHING = goals.SKILL_IDS["fishing"]


def member(name, **kw):
    kw.setdefault("job", trainjob.MODE)
    return trainjob.Member(name=name, **kw)


class TheVocabularyAgrees(unittest.TestCase):
    def test_outstanding_training_promotes_unanimous_questers(self):
        self.assertTrue(trainjob.should_activate({"Grug": "quest", "Ugga": "quest"}, True))

    def test_training_never_preempts_an_explicit_dungeon(self):
        self.assertFalse(trainjob.should_activate({"Grug": "dungeon", "Ugga": "dungeon"}, True))

    def test_no_assignments_does_not_change_mode(self):
        self.assertFalse(trainjob.should_activate({"Grug": "quest"}, False))

    def test_the_mode_is_a_real_job_mode(self):
        self.assertIn(trainjob.MODE, jobs.MODES)

    def test_jobs_claims_it_is_implemented(self):
        self.assertIn(trainjob.MODE, jobs.IMPLEMENTED)

    def test_the_trainer_role_is_a_real_travel_role(self):
        self.assertIn(trainjob.TRAINER_ROLE, travel.ROLES)

    def test_every_secondary_id_comes_from_goals(self):
        for name, skill in trainjob.SECONDARY.items():
            self.assertEqual(goals.SKILL_IDS[name], skill)


class ParseWantedTest(unittest.TestCase):
    def test_the_column_becomes_sorted_unique_ids(self):
        self.assertEqual((197, 333), trainjob.parse_wanted("333,197,197"))

    def test_an_empty_column_is_no_permission_at_all(self):
        self.assertEqual((), trainjob.parse_wanted(""))
        self.assertEqual((), trainjob.parse_wanted(None))

    def test_rubbish_narrows_rather_than_widens(self):
        """A malformed column must drop the unparseable half, never keep it -
        the same direction mod-overseer's LoadProfessionPlans fails in, and the
        only direction a parse error may fail in when the value is a
        permission."""
        self.assertEqual((197,), trainjob.parse_wanted("197,,abc,-5,0"))


class OutstandingRefusesEveryErrandTheWorldWouldRefuse(unittest.TestCase):
    def test_a_wanted_unheld_primary_is_the_errand(self):
        m = member("Grog", wanted=(JEWELCRAFTING, INSCRIPTION),
                   learn_skill=JEWELCRAFTING, holds=(INSCRIPTION,))
        self.assertEqual(JEWELCRAFTING, trainjob.outstanding(m))

    def test_no_learn_column_is_no_errand(self):
        self.assertEqual(0, trainjob.outstanding(member("Og", wanted=(TAILORING,))))

    def test_a_secondary_is_never_an_errand(self):
        """mod-overseer resolves through SkillStartedBySpell, which gates on
        IsPrimaryProfessionSkill - so a fishing errand can only ever walk
        somebody to a trainer that cannot teach them."""
        m = member("Ugga", wanted=(FISHING,), learn_skill=FISHING, holds=())
        self.assertEqual(0, trainjob.outstanding(m))

    def test_a_skill_the_roster_never_asked_for_is_refused(self):
        """TrainOnArrival refuses a learn that is not in plan.wanted and drops
        the errand; refusing here means the journey is not taken to be turned
        away at the end of it."""
        m = member("Og", wanted=(TAILORING,), learn_skill=JEWELCRAFTING)
        self.assertEqual(0, trainjob.outstanding(m))

    def test_a_skill_already_held_is_a_cap_and_not_a_learn(self):
        """The trainer resolve narrows on TrainerStartedSkills - what a spawn
        can START somebody in - so a held skill resolves to a trainer that
        cannot help until quadseven/mod-overseer#196 lands."""
        m = member("Og", wanted=(TAILORING,), learn_skill=TAILORING,
                   holds=(TAILORING,))
        self.assertEqual(0, trainjob.outstanding(m))


class FamilyModeTest(unittest.TestCase):
    def test_one_shared_mode_is_the_answer(self):
        self.assertEqual(
            "train", trainjob.family_mode([member("Og"), member("Grog")])
        )

    def test_a_split_family_has_no_mode(self):
        self.assertEqual(
            "",
            trainjob.family_mode([member("Og"), member("Grog", job="quest")]),
        )


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.family = [
            member("Grog", wanted=(JEWELCRAFTING, INSCRIPTION),
                   learn_skill=JEWELCRAFTING, holds=(INSCRIPTION,)),
            member("Og", wanted=(TAILORING,), holds=(TAILORING,)),
        ]

    def test_the_character_with_the_errand_travels(self):
        p = trainjob.plan(self.family)
        self.assertEqual("Grog", p.traveller)
        self.assertEqual(JEWELCRAFTING, p.skill)

    def test_a_family_on_another_mode_is_left_alone(self):
        others = [trainjob.Member(m.name, "dungeon:deadmines", m.wanted,
                                  m.learn_skill, m.holds) for m in self.family]
        p = trainjob.plan(others)
        self.assertEqual("", p.traveller)
        self.assertIn("dungeon:deadmines", p.why_not)

    def test_exactly_one_traveller_and_the_rest_wait(self):
        """Two aims is the 937-yard scatter of infra#2812 with a fresh reason
        attached; the family has one character carrying `new rpg` by design."""
        crowd = self.family + [
            member("Bork", wanted=(TAILORING,), learn_skill=TAILORING)
        ]
        p = trainjob.plan(crowd)
        self.assertEqual("Bork", p.traveller)
        self.assertEqual(("Grog",), p.waiting)

    def test_an_empty_roster_declines_and_says_why(self):
        p = trainjob.plan([])
        self.assertEqual("", p.traveller)
        self.assertTrue(p.why_not)

    def test_a_plan_that_declines_always_says_why(self):
        for members in ([], self.family[1:], [member("Og", job="quest")]):
            p = trainjob.plan(members)
            if not p.traveller:
                self.assertTrue(p.why_not, members)


class ReadinessIsAskedBeforeTheOrderIsWritten(unittest.TestCase):
    def test_an_outstanding_errand_is_ready(self):
        self.assertEqual(
            "",
            trainjob.readiness([
                member("Grog", job="quest", wanted=(JEWELCRAFTING,),
                       learn_skill=JEWELCRAFTING)
            ]),
        )

    def test_readiness_does_not_require_the_family_to_already_be_training(self):
        """The order has not been written yet when this is asked, so a check
        that needed job=train would refuse every first order."""
        ready = member("Grog", job="dungeon:deadmines", wanted=(JEWELCRAFTING,),
                       learn_skill=JEWELCRAFTING)
        self.assertEqual("", trainjob.readiness([ready]))

    def test_nothing_outstanding_is_refused_with_a_reason(self):
        why = trainjob.readiness([member("Og", wanted=(TAILORING,),
                                         holds=(TAILORING,))])
        self.assertIn("stand the quest drive down", why)

    def test_the_refusal_names_the_secondary_professions(self):
        """The operator asked for First Aid, Cooking and Fishing by name. An
        empty answer to a named request is the silence this module exists to
        stop."""
        why = trainjob.readiness([member("Og", wanted=(TAILORING,),
                                         holds=(TAILORING,))])
        for word in ("First Aid", "Cooking", "Fishing"):
            self.assertIn(word, why)

    def test_a_capped_character_is_named_in_the_refusal(self):
        why = trainjob.readiness([
            member("Og", wanted=(TAILORING,), learn_skill=TAILORING,
                   holds=(TAILORING,))
        ])
        self.assertIn("Og", why)
        self.assertIn("196", why)

    def test_an_empty_roster_is_refused(self):
        self.assertTrue(trainjob.readiness([]))


class StatementsAreTheAimAndItsClearingHalf(unittest.TestCase):
    def setUp(self):
        self.plan = trainjob.plan([
            member("Grog", wanted=(JEWELCRAFTING,), learn_skill=JEWELCRAFTING)
        ])

    def test_nobody_travelling_writes_nothing(self):
        self.assertEqual([], trainjob.statements(trainjob.TrainPlan()))

    def test_the_aim_and_the_clear_are_both_produced(self):
        stmts = trainjob.statements(self.plan)
        self.assertEqual(2, len(stmts))
        self.assertIn(trainjob.TRAINER_ROLE, stmts[0][1])
        self.assertEqual(travel.NONE, stmts[1][1][0])

    def test_no_name_and_no_role_is_ever_interpolated_into_the_sql(self):
        """Same assertion travel.aim_statements already carries, restated over
        this caller so a future hand-rolled UPDATE here cannot skip it."""
        for sql, params in trainjob.statements(self.plan):
            self.assertNotIn("Grog", sql)
            self.assertNotIn(trainjob.TRAINER_ROLE, sql)
            self.assertIn("Grog", params)


class ReportSaysWhatWasDoneAndNeverOverclaims(unittest.TestCase):
    def test_it_names_the_traveller_and_the_role(self):
        p = trainjob.plan([
            member("Grog", wanted=(JEWELCRAFTING,), learn_skill=JEWELCRAFTING)
        ])
        line = trainjob.report(p)
        self.assertIn("Grog", line)
        self.assertIn(trainjob.TRAINER_ROLE, line)

    def test_it_never_claims_anybody_learned_anything(self):
        """Aiming is not arriving and arriving is not learning. Only
        character_skills settles a trade, and this module cannot read it."""
        line = trainjob.report(trainjob.plan([
            member("Grog", wanted=(JEWELCRAFTING,), learn_skill=JEWELCRAFTING)
        ]))
        self.assertIn("Arriving is not learning", line)
        for lie in ("has learned", "trained ", "now knows"):
            self.assertNotIn(lie, line)

    def test_a_declining_plan_reports_its_reason(self):
        p = trainjob.TrainPlan(why_not="because")
        self.assertEqual("because", trainjob.report(p))


class TheBridgeReallyDrivesIt(unittest.TestCase):
    """jobs.IMPLEMENTED naming `train` is a promise that setting it changes
    behaviour. The branch it points at is in this file's own repository rather
    than in mod_overseer.cpp, so it is pinned by source text exactly as
    test_jobs.ImplementedMatchesTheModule pins the two C++ ones - widening the
    set without a drive to point at is the drift both classes exist to stop.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8", errors="replace")

    def test_the_bridge_imports_the_drive(self):
        self.assertIn("import trainjob", self.source)

    def test_the_drive_exists_and_is_called(self):
        self.assertIn("async def _drive_train(self)", self.source)
        self.assertIn("await self._drive_train()", self.source)

    def test_the_drive_is_re_asserted_on_the_protect_cycle(self):
        """Called twice: once when the order lands, once every protect cycle.
        A drive that ran only on the order would be lost to a restart."""
        self.assertEqual(2, self.source.count("await self._drive_train()"))

    def test_the_drive_writes_the_column_that_makes_a_character_walk(self):
        self.assertIn("_aim_train_traveller", self.source)
        self.assertIn("trainjob.statements(plan)", self.source)

    def test_the_traveller_is_also_made_the_leader(self):
        """mod-overseer refuses to send anybody not carrying `new rpg`, and
        only the leader carries it - so aiming a follower is an UPDATE that
        moves nobody."""
        self.assertIn("_train_traveller() or _errand_traveller()", self.source)

    def test_a_failed_drive_does_not_cost_the_rest_of_the_protect_cycle(self):
        """infra#3173's lesson, restated: this runs a third of the way into a
        cycle that still has the declared professions, the spec tabs and the
        randomize guards to do. An exception escaping here would take all of
        them with it."""
        drive = self.source[self.source.index("async def _drive_train(self)"):]
        drive = drive[:drive.index("async def _conjure")]
        self.assertIn("except Exception:", drive)
        self.assertIn("log.exception", drive)

    def test_the_reads_are_guarded_for_a_realm_without_the_columns(self):
        reader = self.source[self.source.index("def _train_members()"):]
        reader = reader[:reader.index("def _train_traveller()")]
        self.assertIn("(1054, 1146)", reader)


class TheWritePathRefusesAnUnimplementedMode(unittest.TestCase):
    """infra#3338: nothing consulted jobs.py at the point an order was written,
    so an unimplemented mode was accepted and silently idled the family."""

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8", errors="replace")
        start = cls.source.index("async def _set_job(self")
        cls.body = cls.source[start:cls.source.index("async def _drive_train")]

    def test_set_job_asks_jobs_why_not_before_writing_anything(self):
        self.assertIn("jobs.why_not(d.mode)", self.body)
        self.assertLess(
            self.body.index("jobs.why_not(d.mode)"),
            self.body.index("to_thread(_fetch_enabled_names)"),
            "the refusal must cost no query and cannot half-write a family",
        )

    def test_the_refusal_is_spoken_and_not_only_logged(self):
        self.assertIn("await channel.send(refusal", self.body)

    def test_a_refusal_returns_before_any_row_is_inserted(self):
        self.assertLess(
            self.body.index("await channel.send(refusal"),
            self.body.index("_insert_job"),
        )

    def test_train_is_also_checked_for_having_anything_to_do(self):
        self.assertIn("trainjob.readiness(", self.body)


if __name__ == "__main__":
    unittest.main()
