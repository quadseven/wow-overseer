import unittest

from source_utils import function_source, source_path


class SourceUtilsTests(unittest.TestCase):
    def test_function_source_comes_from_the_imported_module(self):
        source = function_source("source_fixture", "known_function")

        self.assertIn('return "source lookup sentinel"', source)

    def test_function_source_resolves_an_imported_callable(self):
        from source_fixture import known_function

        source = function_source(known_function)

        self.assertIn('return "source lookup sentinel"', source)

    def test_source_path_resolves_an_import_name(self):
        path = source_path("source_fixture")

        self.assertTrue(path.is_file())
        self.assertIn("source lookup sentinel", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
