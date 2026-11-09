import unittest

import source_fixture
import source_utils


class FunctionSourceTests(unittest.TestCase):
    def test_finds_a_function_by_its_import_path(self):
        source = source_utils.function_source(source_fixture.sample_function)

        self.assertIn("def sample_function", source)
        self.assertIn('return "fixture source"', source)

    def test_finds_a_nested_method_by_its_import_path(self):
        source = source_utils.function_source(source_fixture.Fixture.method)

        self.assertIn("def method", source)
        self.assertIn('return "fixture method source"', source)


if __name__ == "__main__":
    unittest.main()
