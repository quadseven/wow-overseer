"""Every EPH_* setting the package reads appears in data/ephemeral/config.example.env, with a fake value."""

import pathlib
import re
import unittest

PKG = pathlib.Path(__file__).resolve().parent.parent / "ephemeral"
EXAMPLE = PKG.parent / "data" / "ephemeral" / "config.example.env"


def read_in_code():
    found = set()
    for path in PKG.glob("*.py"):
        found |= set(
            re.findall(
                r"""["'](EPH_[A-Z0-9_]+)["']""", path.read_text(encoding="utf-8")
            )
        )
    return found


def in_example():
    names = {}
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(EPH_[A-Z0-9_]+)=(.*)$", line)
        if m:
            names[m.group(1)] = m.group(2)
    return names


class ConfigExampleTest(unittest.TestCase):
    def test_every_variable_the_code_reads_is_in_the_example(self):
        self.assertTrue(read_in_code(), "the scan found no EPH_ variable at all")
        self.assertEqual(sorted(read_in_code() - set(in_example())), [])

    def test_the_example_lists_nothing_the_code_does_not_read(self):
        self.assertEqual(sorted(set(in_example()) - read_in_code()), [])

    def test_credentials_are_obvious_placeholders(self):
        names = in_example()
        self.assertEqual(names["EPH_MYSQL_PASSWORD"], "YOUR_DB_PASSWORD_HERE")
        self.assertEqual(names["EPH_MYSQL_USER"], "YOUR_DB_USER_HERE")

    def test_the_guarded_values_match_what_the_guard_requires(self):
        from ephemeral import guard

        names = in_example()
        self.assertEqual(names["EPH_MYSQL_HOST"], guard.LOOPBACK)
        self.assertEqual(int(names["EPH_MYSQL_PORT"]), guard.WORLD_PORT)
        self.assertEqual(names["EPH_WORLD_LABEL"], guard.WORLD_LABEL_VALUE)
        self.assertEqual(names["EPH_HARNESS_GRANTS"], guard.GRANTS_ENABLED)


if __name__ == "__main__":
    unittest.main()
