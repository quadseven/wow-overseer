#!/usr/bin/env python3
"""Run the tests/test_*.py modules in parallel subprocesses, across the
runner's cores, and fail if any module fails (#1290).

`python3 -m unittest discover -s tests` runs the ~12,600-test suite on one
core: about nine minutes of a 4-core CI runner. The time is spread evenly
over ~450 modules and no module leans on another's state, so the modules
split across processes. Each runs exactly as discover would import it: cwd
at the repo root, the tests dir first on the path.

Modules go out in batches, largest file first, so a heavy module does not
begin last and hold the run open alone. A batch is one module or a run of
small ones adding up to about the same size: one process per small module
pays interpreter start-up and imports ~450 times, which costs the CI runner
more than a tenth of its cores. Each batch's output prints under a
`===== <modules> =====` header as it finishes, then one total line:
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

# unittest's exit code when the modules loaded but held no tests (3.12+).
NO_TESTS_RAN = 5

# Batches per worker: enough that the last ones to finish are small.
BATCHES_PER_WORKER = 8

RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)


def discovered_modules(tests_dir: Path) -> list[tuple[str, int]]:
    """The modules `unittest discover -s tests -p 'test_*.py'` would load,
    with their file sizes, largest first. tests/ is not a package, so
    discover does not recurse and neither does this."""
    paths = [p for p in tests_dir.glob("test_*.py") if p.stem.isidentifier()]
    sized = [(p.stem, p.stat().st_size) for p in paths]
    sized.sort(key=lambda m: (-m[1], m[0]))
    return sized


def batched(modules: list[tuple[str, int]], workers: int) -> list[list[str]]:
    """Cut the size-ordered modules into runs of about equal total size."""
    target = sum(size for _, size in modules) / (workers * BATCHES_PER_WORKER)
    batches: list[list[str]] = []
    current: list[str] = []
    filled = 0
    for name, size in modules:
        current.append(name)
        filled += size
        if filled >= target:
            batches.append(current)
            current, filled = [], 0
    if current:
        batches.append(current)
    return batches


def run_batch(batch: list[str], tests_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(tests_dir), env.get("PYTHONPATH")])
    )
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "-v", *batch],
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
    workers = max(1, min(len(modules), os.cpu_count() or 1))
    batches = batched(modules, workers)
    print(
        f"Parallel unittest: {len(modules)} modules in {len(batches)} batches"
        f" on {workers} workers",
        flush=True,
    )
    total = 0
    failed: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_batch, b, tests_dir): b for b in batches}
        for future in concurrent.futures.as_completed(futures):
            batch = futures[future]
            result = future.result()
            output = result.stdout + result.stderr
            print(f"===== {' '.join(batch)} =====")
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
            ran = tests_ran(output)
            total += ran
            if result.returncode and not (
                result.returncode == NO_TESTS_RAN and ran == 0
            ):
                failed.append(" ".join(batch))

    for batch in sorted(failed):
        print(f"FAILED in: {batch}")
    print(
        f"Parallel unittest total: Ran {total} tests across {len(modules)} modules",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
