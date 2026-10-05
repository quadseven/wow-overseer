"""The town errand loop says it ran (wow-dev 2026-10-05).

An errand is due only now and then; the loop wrote nothing for two hours while
idle and the "town errand loop has gone quiet" monitor paged. One line per
heartbeat after a full pass is the liveness the monitor reads.
"""

import ast
import pathlib
import unittest

import townerrand

SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()


class Log:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *args):
        self.lines.append(fmt % args)


def _heartbeat(errands):
    tree = ast.parse(SOURCE)
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_town_errand_heartbeat"
    )
    log = Log()
    ns = {"log": log, "_TOWN_ERRANDS": errands, "TOWN_ERRAND_HEARTBEAT_SECONDS": 900.0}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102
    return ns["_town_errand_heartbeat"], log


class TheLoopSaysItRan(unittest.TestCase):
    def test_the_first_pass_says_so_and_counts_errands_under_way(self):
        beat, log = _heartbeat(
            {
                ("Grug",): townerrand.State(phase=townerrand.STEPS),
                ("Zug",): townerrand.State(),
            }
        )
        self.assertEqual(beat(None, 100.0), 100.0)
        self.assertEqual(
            log.lines, ["town errand: pass ran for every family; 1 errand(s) under way"]
        )

    def test_once_a_heartbeat_and_no_more(self):
        beat, log = _heartbeat({})
        said = beat(None, 0.0)
        self.assertEqual(beat(said, 899.0), 0.0)
        self.assertEqual(beat(said, 900.0), 900.0)
        self.assertEqual(len(log.lines), 2)

    def test_the_loop_beats_after_every_full_pass(self):
        loop = SOURCE[SOURCE.index("    async def _town_errand_loop(") :]
        loop = loop[: loop.index("\n    async def ")]
        self.assertIn("said = _town_errand_heartbeat(said, time.monotonic())", loop)


if __name__ == "__main__":
    unittest.main()
