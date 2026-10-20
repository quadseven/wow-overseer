"""The parallel unittest runner CI uses in place of `unittest discover` (#1290).

check.yml runs every tests/test_*.py module in its own subprocess across the
runner's cores. These tests build small throwaway suites and run the script
the way CI does, so the runner cannot quietly turn a failure green, drop a
module, or miscount what ran:

- one failing test, in any one module, fails the whole run;
- a module that holds no tests (unittest's exit code 5) is not a failure;
- the reported total equals what `unittest discover` counts for the same dir;
- check.yml really calls the runner, not discover.
"""

import pathlib
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = HERE / ".github" / "scripts" / "unittest_parallel.py"
CHECK_YML = HERE / ".github" / "workflows" / "check.yml"

PASSING = """
    import unittest

    class T(unittest.TestCase):
        def test_a(self):
            pass

        def test_b(self):
            pass
"""

# Imports a helper that sits next to the tests, the way most of this suite
# imports its fixtures: the runner must put the tests dir on the path.
USES_HELPER = """
    import unittest

    import helper

    class T(unittest.TestCase):
        def test_helper(self):
            self.assertEqual(helper.VALUE, 3)
"""

FAILING = """
    import unittest

    class T(unittest.TestCase):
        def test_ok(self):
            pass

        def test_broken(self):
            self.assertEqual(1, 2)
"""

EMPTY = """
    VALUE = "a test module with no TestCase in it"
"""


def build_suite(root, modules):
    tests = pathlib.Path(root) / "tests"
    tests.mkdir()
    (tests / "helper.py").write_text("VALUE = 3\n", encoding="utf-8")
    for name, body in modules.items():
        (tests / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return tests


def run_parallel(tests):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--tests-dir", str(tests)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def parallel_total(output):
    found = re.findall(
        r"^Parallel unittest total: Ran (\d+) tests? across (\d+) modules?$",
        output,
        re.M,
    )
    if not found:
        raise AssertionError(f"no total line in output:\n{output}")
    return int(found[-1][0]), int(found[-1][1])


class ParallelRunnerTest(unittest.TestCase):
    def test_script_exists(self):
        self.assertTrue(SCRIPT.is_file(), f"{SCRIPT} is missing")

    def test_a_failing_test_in_one_module_fails_the_run(self):
        with tempfile.TemporaryDirectory() as root:
            tests = build_suite(
                root,
                {"test_one": PASSING, "test_two": FAILING, "test_three": USES_HELPER},
            )
            result = run_parallel(tests)
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertRegex(output, r"(?m)^FAILED in: .*\btest_two\b")
        self.assertIn("FAIL: test_broken (test_two.", output)
        self.assertEqual(parallel_total(output), (5, 3))

    def test_a_module_with_no_tests_passes(self):
        with tempfile.TemporaryDirectory() as root:
            tests = build_suite(root, {"test_one": PASSING, "test_empty": EMPTY})
            result = run_parallel(tests)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(parallel_total(output), (2, 2))

    def test_the_total_matches_unittest_discover(self):
        modules = {
            "test_one": PASSING,
            "test_two": PASSING,
            "test_three": USES_HELPER,
            "test_empty": EMPTY,
        }
        with tempfile.TemporaryDirectory() as root:
            tests = build_suite(root, modules)
            # Not a test module by discover's pattern: the runner must skip it too.
            (tests / "helper_test.py").write_text(
                textwrap.dedent(FAILING), encoding="utf-8"
            )
            serial = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(tests),
                    "-p",
                    "test_*.py",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            result = run_parallel(tests)
        serial_out = serial.stdout + serial.stderr
        self.assertEqual(serial.returncode, 0, serial_out)
        counted = int(re.findall(r"^Ran (\d+) tests? in ", serial_out, re.M)[-1])
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(parallel_total(output), (counted, len(modules)))


class CheckWorkflowTest(unittest.TestCase):
    def test_check_runs_the_parallel_runner(self):
        text = CHECK_YML.read_text(encoding="utf-8")
        cmd = re.search(r"^\s*test-cmd:\s*\"(.*)\"\s*$", text, re.M)
        self.assertIsNotNone(cmd, "check.yml has no quoted unittest test-cmd")
        cmd = cmd.group(1)
        self.assertIn(
            "python3 .github/scripts/compile_check.py --min-python 3.12 &&", cmd
        )
        self.assertIn(
            "--with-requirements tests/requirements.txt python3 .github/scripts/unittest_parallel.py",
            cmd,
        )
        self.assertNotIn("unittest discover", cmd)


if __name__ == "__main__":
    unittest.main()
