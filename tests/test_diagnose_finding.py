"""scripts/diagnose_finding.py: a family-run-loop finding read from its runs,
the archived worldserver log and the deploy (#1311).

Every source is a fake: the realm through realmread.Memory, the log archive
and GitHub as plain callables, so the command is pinned with no database, no
cluster and no network. The fixture is shaped like Blackfathom Deeps runs
711012 (the split party at 20:18Z) and 713407 (the stall at 22:21Z, waiting
on a member surfacing for breath).
"""

import calendar
import importlib.util
import io
import os
import pathlib
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

_stub = types.ModuleType("pymysql")
_stub.MySQLError = type("MySQLError", (Exception,), {})
sys.modules.setdefault("pymysql", _stub)

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import realmread  # noqa: E402


def load():
    path = HERE / "scripts" / "diagnose_finding.py"
    spec = importlib.util.spec_from_file_location("diagnose_finding", path)
    module = importlib.util.module_from_spec(spec)
    # Registered first: a dataclass looks its module up while it is defined.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


diag = load()

KEY = "family-run-loop:Zug:48"
FAMILY = ["Zug", "Uzza", "Grakka", "Morbo", "Thudd"]
REVISION = "aaaaaaaaaaaa1111111111111111111111111111"
MERGE_1087 = "bbbbbbbbbbbb2222222222222222222222222222"
MERGE_1050 = "cccccccccccc3333333333333333333333333333"


def at(stamp: str) -> int:
    return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))


NOW = at("2026-10-19T23:00:00Z")

RUNS = [
    {
        "id": 711012,
        "leader_name": "Zug",
        "map_id": 48,
        "state": "ended",
        "outcome": "left",
        "ended_reason": "the party split across the instance",
        "started_unix": at("2026-10-19T20:02:00Z"),
        "ended_unix": at("2026-10-19T20:18:00Z"),
    },
    {
        "id": 713407,
        "leader_name": "Zug",
        "map_id": 48,
        "state": "ended",
        "outcome": "stalled",
        "ended_reason": "the failed exit recovered by hearth; every member is outside",
        "started_unix": at("2026-10-19T21:50:00Z"),
        "ended_unix": at("2026-10-19T22:31:00Z"),
    },
]

EVENTS = [
    {
        "run_id": 711012,
        "kind": "phase",
        "phase": "STAGING",
        "detail": "IDLE -> STAGING",
    },
    {
        "run_id": 711012,
        "kind": "boss",
        "phase": "CLEARING",
        "detail": "Ghamoo-ra (mask 0 -> 1)",
    },
    {
        "run_id": 711012,
        "kind": "phase",
        "phase": "EXITING",
        "detail": "CLEARING -> EXITING",
    },
    {
        "run_id": 713407,
        "kind": "phase",
        "phase": "CLEARING",
        "detail": "ENTERING -> CLEARING",
    },
    {
        "run_id": 713407,
        "kind": "boss",
        "phase": "CLEARING",
        "detail": "Lady Sarevess (mask 7 -> 15)",
    },
    {
        "run_id": 713407,
        "kind": "stalled",
        "phase": "CLEARING",
        "detail": "the dungeon module refused 'dc skip' 1 inside map 48: it had "
        "switched itself off with nothing left it could reach",
    },
]

STOP = (
    "{t} stdout F [DC:{who}] between-pulls wait gave up after 360 ticks / "
    "180000ms: Dungeon clear stopped: the party never became ready after 180s "
    "({why}). (present 5 of 5 alive, healer here=1)"
)

LOG_LINES = [
    STOP.format(
        t="2026-10-19T22:21:04.512345678Z", who="Zug", why="Waiting on Uzza (low mana)"
    ),
    STOP.format(
        t="2026-10-19T22:21:04.900000000Z",
        who="Grakka",
        why="Waiting on Uzza (low mana)",
    ),
    # Another family's member, inside the same minutes: not this family's stop.
    STOP.format(
        t="2026-10-19T22:22:00.000000000Z",
        who="Stranger",
        why="Waiting on Nobody (low HP)",
    ),
    # Before any run in the window: belongs to no run.
    STOP.format(
        t="2026-10-19T19:00:00.000000000Z",
        who="Zug",
        why="Waiting on Morbo (out of range)",
    ),
]

PULLS = [
    {
        "number": 1087,
        "title": "Split parties regroup before the next pull",
        "body": "Refs quadseven/wow-overseer#1074",
        "mergedAt": "2026-10-19T18:46:00Z",
        "mergeCommit": {"oid": MERGE_1087},
    },
    {
        "number": 1050,
        "title": "Breath is watched in water",
        "body": "Part of the family-run-loop:Zug:48 finding",
        "mergedAt": "2026-10-17T10:00:00Z",
        "mergeCommit": {"oid": MERGE_1050},
    },
    {
        "number": 1099,
        "title": "Unrelated: names wow-overseer#10740, not the ticket",
        "body": "",
        "mergedAt": "2026-10-19T12:00:00Z",
        "mergeCommit": {"oid": "d" * 40},
    },
]


def realm(runs=RUNS, events=EVENTS, family=FAMILY):
    return realmread.Memory(
        {
            diag.NOW_SQL: [{"now_at": NOW}],
            diag.ROSTER_SQL: [{"name": n} for n in family],
            diag.RUNS_SQL: [dict(r) for r in runs],
            diag.EVENTS_SQL: [dict(e) for e in events],
        }
    )


def compare(base: str, head: str) -> str:
    """GitHub's compare status of base...head: `ahead` when head holds base."""
    return "ahead" if base == MERGE_1050 else "diverged"


def sources(**over):
    made = {
        "realm": lambda: realm(),
        "logs": lambda since: list(LOG_LINES),
        "revision": lambda: REVISION,
        "pulls": lambda terms: [dict(p) for p in PULLS],
        "compare": compare,
    }
    made.update(over)
    return diag.Sources(**made)


def run(argv, src=None):
    out, err = io.StringIO(), io.StringIO()
    code = diag.main(argv, src or sources(), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def boom(*_args):
    raise OSError("connect to db.example.com failed for user root")


class TheRunsAndLogsTest(unittest.TestCase):
    def test_the_stall_names_the_stop_reason_and_the_undeployed_fix(self):
        code, text, _ = run([KEY, "--ticket", "1074"])
        self.assertEqual(0, code)
        self.assertIn("Waiting on Uzza (low mana)", text)
        self.assertIn("713407", text)
        self.assertIn("711012", text)
        self.assertIn("#1087", text)

    def test_each_run_shows_its_mask_last_phase_and_stall(self):
        _, text, _ = run([KEY])
        self.assertIn("mask 15 (4 encounters)", text)
        self.assertIn("ENTERING -> CLEARING", text)
        self.assertIn("switched itself off", text)
        self.assertIn("mask 1 (1 encounter)", text)
        self.assertIn("CLEARING -> EXITING", text)

    def test_a_stop_names_its_members_once(self):
        _, text, _ = run([KEY])
        stops = [line for line in text.splitlines() if "Waiting on Uzza" in line]
        self.assertEqual(1, len(stops), text)
        self.assertIn("Grakka", stops[0])
        self.assertIn("Zug", stops[0])

    def test_only_the_familys_stops_inside_a_run_are_read(self):
        _, text, _ = run([KEY])
        self.assertNotIn("Stranger", text)
        self.assertNotIn("Waiting on Morbo", text)

    def test_the_summary_counts_the_stalls_by_stop_reason(self):
        _, text, _ = run([KEY])
        self.assertIn("1 of 1 stalls: party never ready, waiting on low mana", text)

    def test_a_stall_with_no_stop_line_is_counted_as_such(self):
        quiet = sources(logs=lambda since: [])
        _, text, _ = run([KEY], quiet)
        self.assertIn("1 of 1 stalls: no Dungeon clear stopped line", text)

    def test_the_logs_are_asked_from_the_window_start(self):
        asked = []
        src = sources(logs=lambda since: asked.append(since) or [])
        run([KEY, "--hours", "24"], src)
        self.assertEqual(["2026-10-18T23:00:00Z"], asked)


class TheDeployLineTest(unittest.TestCase):
    def test_it_names_the_revision_and_only_the_merged_fix_not_in_it(self):
        _, text, _ = run([KEY, "--ticket", "1074"])
        deploy = [line for line in text.splitlines() if line.startswith("Deploy:")]
        self.assertEqual(1, len(deploy), text)
        self.assertIn(REVISION[:12], deploy[0])
        self.assertIn("#1087", deploy[0])
        self.assertNotIn("#1050", deploy[0])
        self.assertNotIn("#1099", deploy[0])

    def test_without_a_ticket_only_the_key_names_a_pull(self):
        _, text, _ = run([KEY])
        deploy = next(line for line in text.splitlines() if line.startswith("Deploy:"))
        self.assertNotIn("#1087", deploy)
        self.assertIn("none", deploy)

    def test_the_search_asks_for_the_key_and_the_ticket(self):
        asked = []
        src = sources(pulls=lambda terms: asked.append(list(terms)) or [])
        run([KEY, "--ticket", "1074"], src)
        self.assertEqual(
            [[KEY, "wow-overseer#1074", "wow-overseer/issues/1074"]], asked
        )

    def test_a_pull_citing_the_ticket_by_its_url_counts(self):
        cited = dict(
            PULLS[0], body="https://github.com/quadseven/wow-overseer/issues/1074"
        )
        src = sources(pulls=lambda terms: [cited])
        _, text, _ = run([KEY, "--ticket", "1074"], src)
        self.assertIn("#1087", text)

    def test_an_unknown_revision_still_lists_the_merged_pulls(self):
        src = sources(revision=lambda: (_ for _ in ()).throw(diag.Unreadable("no pin")))
        _, text, _ = run([KEY, "--ticket", "1074"], src)
        deploy = next(line for line in text.splitlines() if line.startswith("Deploy:"))
        self.assertIn("revision not read", deploy)
        self.assertIn("#1087", deploy)
        self.assertIn("#1050", deploy)

    def test_a_revision_given_on_the_command_line_wins(self):
        src = sources(revision=boom)
        _, text, _ = run([KEY, "--revision", "e" * 40], src)
        self.assertIn("e" * 12, text)


class TheUnreadableSourceTest(unittest.TestCase):
    def test_unreadable_logs_are_named_and_the_rest_still_prints(self):
        code, text, err = run([KEY, "--ticket", "1074"], sources(logs=boom))
        self.assertEqual(0, code)
        self.assertIn("Not read: logs", text)
        self.assertIn("713407", text)
        self.assertIn("switched itself off", text)
        self.assertIn("#1087", text)
        self.assertIn("OSError", err)

    def test_an_unreadable_realm_is_named_and_the_deploy_still_prints(self):
        code, text, _ = run([KEY, "--ticket", "1074"], sources(realm=boom))
        self.assertEqual(0, code)
        self.assertIn("Not read: runs", text)
        self.assertIn("#1087", text)

    def test_unreadable_github_is_named(self):
        _, text, _ = run([KEY], sources(pulls=boom))
        self.assertIn("Not read: pull requests", text)
        self.assertIn("Waiting on Uzza (low mana)", text)

    def test_an_error_text_never_reaches_the_output(self):
        _, text, _ = run([KEY], sources(logs=boom, realm=boom, pulls=boom))
        self.assertNotIn("example.com", text)
        self.assertNotIn("root", text)

    def test_a_named_reason_is_printed(self):
        src = sources(
            logs=lambda since: (_ for _ in ()).throw(
                diag.Unreadable("OVERSEER_REALM_LOGS is not set")
            )
        )
        _, text, _ = run([KEY], src)
        self.assertIn("Not read: logs (OVERSEER_REALM_LOGS is not set)", text)


class TheArchiveHelperTest(unittest.TestCase):
    def helper(self, body: str) -> str:
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "helper.sh")
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o700)
        return path

    def run_helper(self, body: str, timeout: float = 20):
        env = {diag.ENV_LOGS: self.helper(body)}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(diag, "ARCHIVE_TIMEOUT", timeout),
        ):
            return diag.archived_logs("2026-10-19T00:00:00Z")

    def test_only_the_stop_lines_come_back(self):
        got = self.run_helper("echo noise; echo '%sx'; echo more" % diag.STOP_TEXT)
        self.assertEqual(["%sx" % diag.STOP_TEXT], got)

    def test_the_all_bosses_cleared_lines_come_back(self):
        got = self.run_helper("echo noise; echo '%s'" % RFK_LOGS[0])
        self.assertEqual([RFK_LOGS[0]], got)

    def test_a_failing_helper_is_unreadable(self):
        with self.assertRaises(diag.Unreadable):
            self.run_helper("exit 3")

    def test_a_wedged_helper_is_cut_off_and_reaped(self):
        started = time.monotonic()
        with self.assertRaises(diag.Unreadable) as ctx:
            self.run_helper("exec sleep 30", timeout=0.5)
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 15)

    def test_a_programming_fault_is_not_called_an_unread_source(self):
        src = sources(logs=lambda since: {}["missing"])
        with self.assertRaises(KeyError):
            run([KEY], src)


# The dungeon module logs a clear it finished on its own line, not as a
# "Dungeon clear stopped" line (#1570). Shaped like two Razorfen Kraul runs of
# the family-run-loop:Zug:47 finding whose stop reason was this line.
CLEARED = (
    "{t} stdout F {ansi}2026-10-27 00:00:00 INFO [playerbots.dungeonclear] "
    "[DC:{who}] dungeon clear disabled: All bosses cleared!"
)
RFK_RUNS = [
    dict(
        RUNS[1],
        id=740000 + i,
        map_id=47,
        started_unix=NOW - 3600 * (i + 2),
        ended_unix=NOW - 3600 * (i + 1),
    )
    for i in range(2)
]
RFK_LOGS = [
    CLEARED.format(
        t=time.strftime("%Y-%m-%dT%H:%M:%S.5Z", time.gmtime(r["ended_unix"] - 120)),
        ansi=ansi,
        who="Zug",
    )
    for r, ansi in zip(RFK_RUNS, ["", "\x1b[0m"])
]


class TheAllBossesClearedStopTest(unittest.TestCase):
    def rfk(self):
        src = sources(
            realm=lambda: realm(runs=RFK_RUNS, events=[]),
            logs=lambda since: list(RFK_LOGS),
        )
        return run(["family-run-loop:Zug:47"], src)[1]

    def test_each_run_gets_the_all_bosses_cleared_reason(self):
        text = self.rfk()
        self.assertIn("2 of 2 stalls: All bosses cleared!", text)
        self.assertEqual(2, text.count("Zug: All bosses cleared!"), text)
        self.assertNotIn("no Dungeon clear stopped line", text)

    def test_the_parser_reads_a_cleared_line(self):
        stop = diag.stop_of(RFK_LOGS[1])
        self.assertEqual("Zug", stop.member)
        self.assertEqual("All bosses cleared!", stop.reason)
        self.assertEqual(RFK_RUNS[1]["ended_unix"] - 120, stop.at)

    def test_another_disable_is_not_read_as_a_stop(self):
        line = RFK_LOGS[0].replace("All bosses cleared!", "Dungeon clear disabled.")
        self.assertIsNone(diag.stop_of(line))


class TheShapeTest(unittest.TestCase):
    def test_another_kind_of_finding_has_no_diagnosis(self):
        code, text, _ = run(["dungeon-clear-rate:bfd"])
        self.assertEqual(0, code)
        self.assertEqual("no diagnosis for this kind of finding\n", text)

    def test_the_output_is_ascii_and_under_forty_lines(self):
        many = [
            dict(
                RUNS[1],
                id=720000 + i,
                started_unix=NOW - 3600 * (i + 2),
                ended_unix=NOW - 3600 * (i + 1),
            )
            for i in range(30)
        ]
        logs = [
            STOP.format(
                t=time.strftime(
                    "%Y-%m-%dT%H:%M:%S.0Z", time.gmtime(r["started_unix"] + 60 + k)
                ),
                who=FAMILY[k],
                why="Waiting on %s (out of range)" % FAMILY[k],
            )
            for r in many
            for k in range(5)
        ]
        src = sources(
            realm=lambda: realm(runs=many, events=[]), logs=lambda since: logs
        )
        _, text, _ = run([KEY], src)
        lines = text.splitlines()
        self.assertLess(len(lines), 40, text)
        text.encode("ascii")
        self.assertIn("older runs not shown", text)
        self.assertIn("30 of 30 stalls", text)
        # Runs are read in id order and shown highest id first.
        self.assertIn("Run 720029 ", text)
        self.assertNotIn("Run 720000 ", text)

    def test_the_parser_reads_a_stop_line(self):
        stop = diag.stop_of(LOG_LINES[0])
        self.assertEqual("Zug", stop.member)
        self.assertEqual(at("2026-10-19T22:21:04Z"), stop.at)
        self.assertEqual(
            "the party never became ready after 180s (Waiting on Uzza (low mana))",
            stop.reason,
        )
        self.assertIsNone(diag.stop_of("2026-10-19T22:21:04Z stdout F unrelated"))


if __name__ == "__main__":
    unittest.main()
