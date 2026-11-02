"""Test modules that share a process pass in either order (#1648).

The parallel runner (#1290) puts several modules in one process, so a stub
one module leaves in sys.modules, or a module it drops after importing it,
reaches whichever modules share its batch. A module then passed or failed by
how the batches fell: a bare `pymysql` stub left behind turned an except
clause into `AttributeError: module 'pymysql' has no attribute 'err'`, and a
`mock.patch.dict(sys.modules)` around an import dropped the modules that
import pulled in, so the next module imported a second copy whose classes
compared unequal to the first.

Each check runs in a fresh interpreter, so what this process already holds
cannot hide or cause a finding.
"""

import json
import os
import pathlib
import subprocess
import sys
import textwrap
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent


def _run(script, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(TESTS), env.get("PYTHONPATH")])
    )
    done = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(script), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=600,
    )
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        raise AssertionError(
            f"exit {done.returncode}\n{done.stdout[-3000:]}\n{done.stderr[-3000:]}"
        )
    return json.loads(lines[-1])


# Loads and runs the named modules in order, in one process, as one batch of
# the parallel runner would, and records each module's result.
PAIR = """
    import io, json, sys, unittest
    sys.path.insert(0, "")
    out = []
    for name in sys.argv[1:]:
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        problems = [str(t) + "\\n" + tb for t, tb in result.errors + result.failures]
        out.append({
            "module": name,
            "ok": result.wasSuccessful(),
            "problems": problems,
        })
    print(json.dumps(out))
"""


class TwoModulesInOneProcess(unittest.TestCase):
    """Two modules that share a batch pass in either order."""

    PAIRS = [
        ("test_low_bag_sales", "test_standin"),
    ]

    def test_each_pair_passes_in_both_orders(self):
        for pair in self.PAIRS:
            for order in (pair, pair[::-1]):
                with self.subTest(order=order):
                    for got in _run(PAIR, *order):
                        self.assertTrue(got["ok"], "\n".join(got["problems"]))


if __name__ == "__main__":
    unittest.main()
