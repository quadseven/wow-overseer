#!/usr/bin/env python3
"""Run every tests/test_*.py module in its own subprocess, across the
runner's cores, and fail if any module fails (#1290).

`python3 -m unittest discover -s tests` runs the ~12,600-test suite on one
core: about nine minutes of a 4-core CI runner. The time is spread evenly
over ~450 modules and no module leans on another's state, so one process per
module scales close to linearly. Each module runs exactly as discover would
import it: cwd at the repo root, the tests dir first on the path.

Modules start largest file first, so a heavy module does not begin last and
hold the run open alone. Each module's output prints under a
`===== <module> =====` header as it finishes, then one total line:
`Parallel unittest total: Ran N tests across M modules`. A module with no
tests in it (unittest's exit code 5, "NO TESTS RAN") passes, as it does
under discover. Local `python3 -m unittest discover -s tests` still works.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
from pathlib import Path

# unittest's exit code when a module loaded but held no tests (3.12+).
NO_TESTS_RAN = 5

RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)


def discovered_modules(tests_dir: Path) -> list[str]:
    """The modules `unittest discover -s tests -p 'test_*.py'` would load,
    largest file first. tests/ is not a package, so discover does not recurse
    and neither does this."""
    paths = [p for p in tests_dir.glob("test_*.py") if p.stem.isidentifier()]
    paths.sort(key=lambda p: (-p.stat().st_size, p.name))
    return [p.stem for p in paths]


def run_module(module: str, tests_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(tests_dir), env.get("PYTHONPATH")])
    )
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", module, "-v"],
        cwd=tests_dir.parent,
        env=env,
        text=True,
        capture_output=True,
    )


def tests_ran(output: str) -> int:
    counts = RAN.findall(output)
    return int(counts[-1]) if counts else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tests-dir", type=Path, default=Path("tests"))
    args = parser.parse_args()
    tests_dir = args.tests_dir.resolve()

    modules = discovered_modules(tests_dir)
    total = 0
    failed: list[str] = []
    workers = max(1, min(len(modules), os.cpu_count() or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_module, m, tests_dir): m for m in modules}
        for future in concurrent.futures.as_completed(futures):
            module = futures[future]
            result = future.result()
            output = result.stdout + result.stderr
            print(f"===== {module} =====")
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
            ran = tests_ran(output)
            total += ran
            if result.returncode and not (
                result.returncode == NO_TESTS_RAN and ran == 0
            ):
                failed.append(module)

    for module in sorted(failed):
        print(f"FAILED module: {module}")
    print(
        f"Parallel unittest total: Ran {total} tests across {len(modules)} modules",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
