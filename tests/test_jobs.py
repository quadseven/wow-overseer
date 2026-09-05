"""jobs.py: the RimWorld-style job-schedule vocabulary (infra#2834).

Pure module, no MySQL/Discord/LLM - same seam as travel.py's own tests.

One class here is NOT pure and says so: IMPLEMENTED is a claim about C++ in
another repo, and a claim nobody checks is exactly how it came to say `quest`
alone for a week after `dungeon` was fully wired. So it is asserted against
mod_overseer.cpp as source text, the way test_bags.py and test_quest_aim.py
already do (infra#3205).
"""
import pathlib
import unittest
from unittest import mock

import jobs

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp"


class ResolveTest(unittest.TestCase):
    def test_every_canonical_mode_resolves_to_itself(self):
        for mode in jobs.MODES:
            self.assertEqual(jobs.resolve(mode), mode)

    def test_an_alias_resolves_to_its_canonical_mode(self):
        self.assertEqual(jobs.resolve("farming"), "farm")
        self.assertEqual(jobs.resolve("levelling"), "grind")
        self.assertEqual(jobs.resolve("charter"), "guild business")

    def test_case_and_whitespace_are_folded(self):
        self.assertEqual(jobs.resolve("  Farming  Time "), "farm")
        self.assertEqual(jobs.resolve("QUEST"), "quest")

    def test_unknown_text_resolves_to_none(self):
        self.assertIsNone(jobs.resolve("elephants"))

    def test_none_resolves_to_none(self):
        self.assertIsNone(jobs.resolve(None))

    def test_empty_string_resolves_to_none(self):
        self.assertIsNone(jobs.resolve(""))
        self.assertIsNone(jobs.resolve("   "))

    def test_every_alias_target_is_a_real_mode(self):
        for target in jobs.ALIASES.values():
            self.assertIn(target, jobs.MODES)


class ParseOrderTest(unittest.TestCase):
    def test_the_explicit_form(self):
        self.assertEqual(jobs.parse_order("job quest"), "quest")
        self.assertEqual(jobs.parse_order("job: farm"), "farm")
        self.assertEqual(jobs.parse_order("JOB grind"), "grind")

    def test_evans_own_sentence_from_the_issue(self):
        self.assertEqual(jobs.parse_order("its farming time"), "farm")
        self.assertEqual(jobs.parse_order("it's farming time"), "farm")

    def test_a_natural_phrase_elsewhere_in_a_sentence(self):
        self.assertEqual(jobs.parse_order("okay everyone, grinding time"), "grind")

    def test_an_ordinary_sentence_mentioning_a_mode_word_is_not_an_order(self):
        # "quest" alone must not fire on every sentence about quests - only a
        # phrase this module actually declares does.
        self.assertIsNone(jobs.parse_order("Grug finished a quest just now"))

    def test_unrecognised_text_is_none(self):
        self.assertIsNone(jobs.parse_order("hello there"))

    def test_empty_text_is_none(self):
        self.assertIsNone(jobs.parse_order(""))

    def test_job_with_no_mode_is_none(self):
        self.assertIsNone(jobs.parse_order("job"))
        self.assertIsNone(jobs.parse_order("job   "))

    def test_job_with_an_unknown_mode_is_none(self):
        self.assertIsNone(jobs.parse_order("job elephants"))


class DefaultAndWidthTest(unittest.TestCase):
    def test_default_is_quest(self):
        self.assertEqual(jobs.DEFAULT, "quest")
        self.assertIn(jobs.DEFAULT, jobs.MODES)

    def test_every_mode_fits_the_column(self):
        for mode in jobs.MODES:
            self.assertLessEqual(len(mode), jobs.COLUMN_WIDTH)

    def test_quest_is_implemented(self):
        self.assertIn("quest", jobs.IMPLEMENTED)

    def test_implemented_is_a_subset_of_modes(self):
        self.assertTrue(jobs.IMPLEMENTED <= set(jobs.MODES))


class DescribeTest(unittest.TestCase):
    def test_the_implemented_mode_makes_no_not_built_claim(self):
        self.assertNotIn("NOT BUILT", jobs.describe("quest"))

    def test_every_unimplemented_mode_says_so(self):
        for mode in jobs.MODES:
            if mode in jobs.IMPLEMENTED:
                continue
            self.assertIn("NOT BUILT YET", jobs.describe(mode))

    def test_describe_names_the_mode(self):
        self.assertIn("farm", jobs.describe("farm"))


class TheWriteGuard(unittest.TestCase):
    """infra#3338. `jobs.py` has always known which modes are real; nothing
    consulted it at the point an order was written, so `job craft` was
    accepted, stood the quest drive down, and idled five characters with
    nothing said anywhere about why."""

    def test_every_implemented_mode_may_be_set(self):
        for mode in jobs.IMPLEMENTED:
            self.assertTrue(jobs.can_set(mode), mode)
            self.assertEqual("", jobs.why_not(mode), mode)

    def test_no_unimplemented_mode_may_be_set(self):
        for mode in jobs.MODES:
            if mode in jobs.IMPLEMENTED:
                continue
            self.assertFalse(jobs.can_set(mode), mode)

    def test_every_refusal_says_why_and_what_works_instead(self):
        """A bare "no" is the same silence with a different shape."""
        for mode in jobs.MODES:
            if mode in jobs.IMPLEMENTED:
                continue
            why = jobs.why_not(mode)
            self.assertIn(mode, why)
            self.assertIn("3338", why)
            for wired in jobs.IMPLEMENTED:
                self.assertIn(wired, why, mode)

    def test_craft_names_the_verb_that_does_not_exist(self):
        """The mode the operator actually reaches for gets the specific
        answer: mod-overseer has no command kind that casts a tradeskill."""
        why = jobs.why_not("craft")
        self.assertIn("tradeskill", why)

    def test_a_mode_that_is_not_a_mode_is_refused_with_the_vocabulary(self):
        why = jobs.why_not("interpretive dance")
        self.assertIn("not a job mode", why)
        for mode in jobs.MODES:
            self.assertIn(mode, why)

    def test_every_blocked_reason_is_for_a_real_unimplemented_mode(self):
        for mode in jobs.BLOCKED:
            self.assertIn(mode, jobs.MODES)
            self.assertNotIn(mode, jobs.IMPLEMENTED)


class DrivesMatchesImplemented(unittest.TestCase):
    """A mode claimed as wired must name what it drives. The two sets falling
    apart is the same drift IMPLEMENTED itself exists to stop, one rung in:
    `describe` is what Discord hears, so a mode with no named drive is an
    order acknowledged with nothing behind the acknowledgement."""

    def test_every_implemented_mode_names_its_drive(self):
        self.assertEqual(set(jobs.DRIVES), set(jobs.IMPLEMENTED))

    def test_describe_says_what_an_implemented_mode_drives(self):
        for mode in jobs.IMPLEMENTED:
            self.assertIn(jobs.DRIVES[mode], jobs.describe(mode))

    def test_describe_survives_an_implemented_mode_with_no_drive_named(self):
        """The failure above must be a named test failure, never a KeyError
        raised through the function the console renders every chip with."""
        widened = frozenset(jobs.IMPLEMENTED | {"farm"})
        with mock.patch.object(jobs, "IMPLEMENTED", widened):
            said = jobs.describe("farm")
        self.assertIn("farm", said)
        self.assertNotIn("NOT BUILT YET", said)


class TrainIsWiredInPython(unittest.TestCase):
    """`train` is the one mode in IMPLEMENTED whose drive is NOT in
    mod_overseer.cpp, so ImplementedMatchesTheModule cannot pin it and
    tests/test_trainjob.py does instead. Asserted here too, by name, so the
    exception to that class's rule is written down where the rule is."""

    def test_train_is_implemented(self):
        self.assertIn("train", jobs.IMPLEMENTED)

    def test_its_drive_is_named_and_is_the_python_one(self):
        self.assertIn("trainjob", jobs.DRIVES["train"])


class ImplementedMatchesTheModule(unittest.TestCase):
    """IMPLEMENTED is what `describe` tells Discord, so a stale entry makes
    the overseer answer "NOT BUILT YET" to an order it is about to carry out.
    That is not a hypothetical - it is what this constant did between
    quadseven/mod-overseer#88 wiring the dungeon job and infra#3205 noticing.

    Contract over source TEXT, in the pattern test_bags.py and
    test_quest_aim.py established: the C++ is compiled only on a push to main,
    never on a PR, so reading it is the only gate a PR can have.
    """

    @classmethod
    def setUpClass(cls):
        if not MODULE.exists():
            raise unittest.SkipTest(
                "mod-overseer submodule not checked out; "
                "check.python-units.yml passes submodules: true for this dir")
        cls.source = MODULE.read_text(encoding="utf-8", errors="replace")

    def test_the_dungeon_job_really_does_drive_the_run_coordinator(self):
        """The leader's job being `dungeon` is the sole trigger for reset,
        stage, gather, cross, clear, exit and the campaign loop."""
        self.assertIn('leaderJob != "dungeon"', self.source)
        self.assertIn('leaderJob == "dungeon"', self.source)
        self.assertIn("dungeon", jobs.IMPLEMENTED)

    def test_the_quest_job_really_does_gate_the_quest_drive(self):
        """LoadJobs selects everything that is neither blank nor `quest`, so
        absence from that map IS the quest job."""
        self.assertIn("job <> 'quest'", self.source)
        self.assertIn("quest", jobs.IMPLEMENTED)

    def test_no_other_mode_claims_to_be_wired(self):
        """DoJob validates the rest against a list and writes the column,
        and nothing else reads them. Widening IMPLEMENTED without a branch in
        the module to point at is the drift this class exists to stop."""
        for mode in jobs.MODES:
            if mode in jobs.IMPLEMENTED:
                continue
            self.assertNotIn('leaderJob == "%s"' % mode, self.source, mode)
            self.assertNotIn('Job == "%s"' % mode, self.source, mode)


if __name__ == "__main__":
    unittest.main()
