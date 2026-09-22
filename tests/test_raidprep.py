"""The `raid prep` job mode: what it drives, and what it refuses to drive.

Two halves, and the second is the one that matters. The pure decisions are
ordinary unit tests. The last class is a CONTRACT TEST OVER bridge.py's SOURCE
TEXT, in the pattern test_jobs.py established for the C++ side: `jobs.IMPLEMENTED`
is a claim that setting a mode changes behaviour, and a claim whose branch has
been deleted is exactly the drift that had the overseer answering "NOT BUILT
YET" to an order it was about to carry out. `raid prep`'s branch lives in Python
rather than in mod_overseer.cpp, mirroring `train`, so it is pinned here rather
than there - but it is pinned the same way and for the same reason.

Nothing here has been run against a live worldserver, and nothing in this file
claims it has.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import goals  # noqa: E402
import jobs  # noqa: E402
import raidprep  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

ALCHEMY = goals.SKILL_IDS["alchemy"]
TAILORING = goals.SKILL_IDS["tailoring"]
FISHING = goals.SKILL_IDS["fishing"]


def member(name, **kw):
    kw.setdefault("job", raidprep.MODE)
    return raidprep.Member(name=name, **kw)


class TheVocabularyAgrees(unittest.TestCase):
    def test_the_mode_is_a_real_job_mode(self):
        self.assertIn(raidprep.MODE, jobs.MODES)

    def test_jobs_claims_it_is_implemented(self):
        self.assertIn(raidprep.MODE, jobs.IMPLEMENTED)

    def test_an_alias_names_raid_prep(self):
        self.assertEqual(jobs.resolve("raid prep"), "raid prep")

    def test_every_secondary_id_comes_from_goals(self):
        for name, skill in raidprep.SECONDARY.items():
            self.assertEqual(goals.SKILL_IDS[name], skill)


class FamilyModeAgrees(unittest.TestCase):
    def test_a_unanimous_family_is_the_mode(self):
        fam = [member("Grog"), member("Grug")]
        self.assertEqual(raidprep.family_mode(fam), raidprep.MODE)

    def test_a_questing_family_is_not_raid_prep(self):
        fam = [member("Grog", job="quest"), member("Grug", job="quest")]
        self.assertEqual(raidprep.family_mode(fam), "quest")

    def test_a_split_family_does_not_agree(self):
        fam = [member("Grog", job="quest"), member("Grug", job="craft")]
        self.assertEqual(raidprep.family_mode(fam), "")


class ReadinessRefusesOnlyWhenThereIsNothing(unittest.TestCase):
    def test_no_roster_refuses(self):
        self.assertTrue(raidprep.readiness([]))

    def test_an_umbrella_mode_with_mail_passes(self):
        fam = [member("Grog")]
        self.assertEqual(raidprep.readiness(fam, mail_items=1), "")

    def test_a_declared_held_profession_passes(self):
        fam = [member("Grog", wanted=(ALCHEMY,), holds=(ALCHEMY,))]
        self.assertEqual(raidprep.readiness(fam), "")

    def test_an_empty_family_with_nothing_refuses(self):
        fam = [member("Grog", wanted=(), holds=())]
        self.assertTrue(raidprep.readiness(fam))

    def test_secondary_professions_never_drive_raid_prep(self):
        fam = [member("Grog", wanted=(FISHING,), holds=(FISHING,))]
        # A lone secondary is not something a trainer can raise; it must not
        # be what lets the mode through alone.
        self.assertTrue(raidprep.readiness(fam))


class PlanAgreesWithReadiness(unittest.TestCase):
    def test_a_family_on_another_mode_refuses(self):
        fam = [member("Grog", job="quest")]
        plan = raidprep.plan(fam)
        self.assertTrue(plan.why_not)

    def test_a_family_with_mail_plans_mail(self):
        fam = [member("Grog")]
        plan = raidprep.plan(fam, mail_items=3)
        self.assertEqual(plan.mail_items, 3)
        self.assertFalse(plan.why_not)

    def test_a_family_with_a_gap_names_the_profession(self):
        fam = [member("Grog", wanted=(ALCHEMY,), holds=(ALCHEMY,))]
        plan = raidprep.plan(fam)
        self.assertFalse(plan.why_not)
        names = [p for _, p, _, _ in plan.profession_gaps]
        self.assertIn("alchemy", names)


class ReportAgrees(unittest.TestCase):
    def test_why_not_is_reported(self):
        plan = raidprep.plan([])
        self.assertIn("raid prep not possible", raidprep.report(plan))

    def test_mail_is_reported(self):
        plan = raidprep.plan([member("Grog")], mail_items=2)
        self.assertIn("2 mail item(s)", raidprep.report(plan))

    def test_nothing_is_reported(self):
        fam = [member("Grog", wanted=(), holds=())]
        plan = raidprep.plan(fam)
        # A family with nothing to prepare is refused at the order; the report
        # is the refusal sentence, never an empty "nothing to do".
        self.assertIn("raid prep not possible", raidprep.report(plan))


class ThePythonDriveIsWired(unittest.TestCase):
    """Contract over bridge.py's source text, in the pattern test_trainjob.py
    uses: `raid prep` lives in Python, so its positive drive is pinned here."""

    def test_bridge_imports_raidprep(self):
        self.assertIn("import raidprep", BRIDGE.read_text(encoding="utf-8"))

    def test_set_job_calls_the_raid_prep_drive(self):
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("_drive_raid_prep", source)
        self.assertIn("d.mode == raidprep.MODE", source)

    def test_the_drive_composes_the_shipped_sub_passes(self):
        source = BRIDGE.read_text(encoding="utf-8")
        for pass_name in ("_mail_once", "_craft_once", "_guild_bank_once"):
            self.assertIn(pass_name, source)


if __name__ == "__main__":
    unittest.main()
