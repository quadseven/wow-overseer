"""jobs.py: the RimWorld-style job-schedule vocabulary (infra#2834).

Pure module, no MySQL/Discord/LLM - same seam as travel.py's own tests.
"""
import unittest

import jobs


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


if __name__ == "__main__":
    unittest.main()
