"""Replay a scenario fixture offline (#2281).

The production read path runs unchanged over `ReplayReader`, which answers
only the statements the capture holds. A statement the capture lacks fails
the replay instead of reading as an empty result, and so does a recorded
read the path no longer makes: the fixture is a slice of what the realm said,
and the path is held to all of it.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import realmread
from fidelity import fixture, surfaces, verify


def key_of(sql: str, params) -> str:
    return json.dumps([sql, None if params is None else list(params)], default=str)


class ReplayReader(realmread.Reader):
    """A realm reader over recorded reads. Each recorded read answers once."""

    def __init__(self, reads) -> None:
        self._queues: dict = defaultdict(deque)
        for read in reads:
            self._queues[key_of(read.sql, read.params)].append(read)

    def _run(self, sql: str, params) -> list:
        queue = self._queues.get(key_of(sql, params))
        if not queue:
            raise realmread.UnknownQuery(
                "read not in the capture (or already answered): %s %r" % (sql, params)
            )
        read = queue.popleft()
        if read.gap:
            raise realmread.Gap(read.gap, sql)
        return [dict(r) for r in read.rows]

    def unanswered(self) -> int:
        return sum(len(q) for q in self._queues.values())


@dataclass
class Result:
    name: str
    problems: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def compare(
    expected: dict,
    observed: dict,
    words: tuple = ("the record says", "the overseer said"),
) -> list:
    """What differs between the claims the record holds and what was observed."""
    problems = []
    want = {r["run"]: r for r in expected.get("runs", [])}
    got = {r["run"]: r for r in observed.get("runs", [])}
    for run in sorted(set(want) | set(got)):
        if want.get(run) != got.get(run):
            problems.append(
                "run %s: %s %s, %s %s"
                % (run, words[0], want.get(run), words[1], got.get(run))
            )
    return problems


def run(fx: fixture.Fixture) -> Result:
    result = Result(fx.name)
    if fx.surface not in surfaces.SURFACES:
        result.problems.append("unknown surface %r" % fx.surface)
        return result
    build, project = surfaces.SURFACES[fx.surface]
    reader = ReplayReader(fx.reads)
    try:
        payload = build(fx.args, reader)
    except realmread.UnknownQuery as err:
        result.problems.append(str(err))
        return result
    result.problems.extend(compare(fx.expect, project(payload)))
    if reader.unanswered():
        result.problems.append(
            "%d recorded read(s) were never asked" % reader.unanswered()
        )
    return result


SCENARIOS = Path(__file__).resolve().parent / "scenarios"


def main(argv=None) -> int:
    """Verify and replay scenario files (all of fidelity/scenarios by default).

        python3 -m fidelity.replay [scenario.json ...]

    Exits 1 when a fixture is not accepted by the verifier or a replay differs
    from the record."""
    paths = [Path(a) for a in argv or ()] or sorted(SCENARIOS.glob("*.json"))
    failed = 0
    for path in paths:
        try:
            fx = fixture.load(path)
        except fixture.FixtureError as err:
            problems = [str(err)]
            name = path.stem
        else:
            name = fx.name
            problems = verify.problems(fx) or run(fx).problems
        print("%s %s" % ("FAIL" if problems else "ok  ", name))
        for problem in problems:
            print("     %s" % problem)
        failed += bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
