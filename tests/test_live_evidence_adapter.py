"""The repo's Loom live-evidence adapter (#1463).

.loom/live-evidence.json declares two read-only commands Loom's station runs
to prove a shipped ticket's Live box: `.loom/live-evidence/log` (the realm
log archive report, through `realm-logs` on PATH) and `.loom/live-evidence/sql`
(one SELECT as the SELECT-only reader, through a short-lived port-forward).
These tests check the manifest against Loom's parse rules, run both scripts
against fake `realm-logs`, `kubectl` and `mysql` programs, and read the
scripts' text for anything that could write.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, ".loom", "live-evidence.json")
LOG = os.path.join(ROOT, ".loom", "live-evidence", "log")
SQL = os.path.join(ROOT, ".loom", "live-evidence", "sql")
SINCE = "2026-10-20T00:00:00Z"

# Loom's manifest rules (bus/live_adapter.py): the placeholders each kind may
# use and must name, the timeout ceiling, the source-name shape and the
# script-size cap.
PLACEHOLDERS = {
    "log": {"{source}", "{since}", "{since_epoch}", "{needle}"},
    "sql": {"{sql}"},
}
REQUIRED = {"log": {"{source}", "{needle}"}, "sql": {"{sql}"}}
MAX_TIMEOUT = 300
SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
MAX_SCRIPT_BYTES = 256 * 1024

REPORT = textwrap.dedent(
    """\
    coverage
      lines: 4200
      kubelet records read: 4200, unparsed: 0
      first archived line: 2026-10-18T00:00:00Z
      last archived line: 2026-10-21T12:30:00Z
      window: 2026-10-20T00:00:00Z to the end of the archive

    needle: boat leg taken
      regex: boat\\ leg\\ taken
      before window: 3
      inside window: 2
      first match: 2026-10-20T01:00:00Z
      last match: 2026-10-21T02:00:00Z
      per hour inside window (UTC):
        2026-10-20T00 0
        2026-10-20T01 1
      distinct inside window: 1
            2  overseer: boat leg taken by #
      samples: 2 of 2 matching lines inside the window (first, last and evenly spaced)
        > 2026-10-20T01:00:00Z overseer: boat leg taken by 4
        > 2026-10-21T02:00:00Z overseer: boat leg taken by 5
    """
)
EMPTY_REPORT = textwrap.dedent(
    """\
    coverage
      lines: 900
      kubelet records read: 900, unparsed: 0
      first archived line: 2026-10-20T06:00:00Z
      last archived line: 2026-10-21T06:00:00Z
      window: 2026-10-20T00:00:00Z to the end of the archive
    COVERAGE GAP: the archive starts at 2026-10-20T06:00:00Z, after the window start

    needle: drowned below the pier
      regex: drowned\\ below\\ the\\ pier
      before window: 0
      inside window: 0
      first match: none
      last match: none
      per hour inside window (UTC):
        2026-10-20T00 0
      distinct inside window: 0
      samples: 0 of 0 matching lines inside the window (first, last and evenly spaced)
    """
)

FAKE_REALM_LOGS = """\
import os, sys
with open(os.environ["FAKE_CALLS"], "a") as calls:
    calls.write("realm-logs\\t" + "\\t".join(sys.argv[1:]) + "\\n")
code = int(os.environ.get("FAKE_CODE", "0"))
if code:
    sys.stderr.write("kubectl: forbidden\\n")
    sys.exit(code)
with open(os.environ["FAKE_REPORT"]) as report:
    sys.stdout.write(report.read())
"""

FAKE_KUBECTL = """\
import os, sys, time
with open(os.environ["FAKE_CALLS"], "a") as calls:
    calls.write("kubectl\\t" + "\\t".join(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_FORWARD_FAIL"):
    sys.stderr.write("error: pods is forbidden\\n")
    sys.exit(1)
with open(os.environ["FAKE_PIDFILE"], "w") as pidfile:
    pidfile.write(str(os.getpid()))
print("Forwarding from 127.0.0.1:43123 -> 3306", flush=True)
while True:
    time.sleep(1)
"""

FAKE_MYSQL = """\
import os, sys, time
with open(os.environ["FAKE_CALLS"], "a") as calls:
    calls.write("mysql\\t" + "\\t".join(sys.argv[1:]) + "\\n")
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
code = int(os.environ.get("FAKE_CODE", "0"))
if code:
    sys.stderr.write("ERROR 1142 (42000): SELECT command denied\\n")
    sys.exit(code)
sys.stdout.write(os.environ.get("FAKE_ROWS", ""))
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Fakes:
    """A bin directory holding the fake programs and python3, and nothing
    else: it is the whole PATH, so a real kubectl, mysql or realm-logs on
    the machine running the tests is never found. Every call is recorded to
    one file."""

    def __init__(self, test: unittest.TestCase, programs: dict) -> None:
        self.dir = tempfile.mkdtemp(prefix="live-evidence-")
        test.addCleanup(self._clean)
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        for name, body in programs.items():
            path = os.path.join(self.bin, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("#!%s\n%s" % (sys.executable, body))
            os.chmod(path, 0o700)
        # For the scripts' `#!/usr/bin/env python3` line.
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))
        self.calls = os.path.join(self.dir, "calls")
        self.pidfile = os.path.join(self.dir, "pid")
        open(self.calls, "w").close()

    def _clean(self) -> None:
        if os.path.exists(self.pidfile):
            try:
                os.kill(self.forward_pid(), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
        shutil.rmtree(self.dir, ignore_errors=True)

    def env(self, **extra) -> dict:
        # The station's minimal environment: PATH, HOME, LANG, TMPDIR.
        env = {
            "PATH": self.bin,
            "HOME": self.dir,
            "LANG": "C.UTF-8",
            "TMPDIR": self.dir,
        }
        env.update({"FAKE_CALLS": self.calls, "FAKE_PIDFILE": self.pidfile}, **extra)
        return env

    def recorded(self) -> list:
        with open(self.calls, encoding="utf-8") as handle:
            return [line.rstrip("\n").split("\t") for line in handle if line.strip()]

    def report(self, text: str) -> str:
        path = os.path.join(self.dir, "report")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def forward_pid(self) -> int:
        with open(self.pidfile, encoding="utf-8") as handle:
            return int(handle.read())

    def wait_dead(self, pid: int) -> bool:
        for _ in range(100):
            if not _alive(pid):
                return True
            time.sleep(0.05)
        return False


def run(script: str, args: list, env: dict, timeout: int = 60):
    # Run directly, as the station does: the #! line picks the interpreter.
    return subprocess.run(
        [script, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=env["TMPDIR"],
    )


class ManifestTest(unittest.TestCase):
    """The manifest is one Loom's parser accepts (bus/live_adapter.parse)."""

    def setUp(self) -> None:
        with open(MANIFEST, encoding="utf-8") as handle:
            self.data = json.load(handle)

    def test_version_one_with_both_commands(self):
        self.assertEqual(self.data["version"], 1)
        self.assertEqual(set(self.data), {"version", "log", "sql"})

    def test_each_argv_follows_the_rules(self):
        for kind in ("log", "sql"):
            command = self.data[kind]
            argv = command["argv"]
            self.assertIsInstance(argv, list)
            self.assertTrue(0 < len(argv) <= 32)
            for item in argv:
                self.assertTrue(item.isascii() and 0 < len(item) <= 200, item)
            first = argv[0]
            parts = first.split("/")
            self.assertTrue(first.startswith(".loom/") and len(parts) >= 2, first)
            for part in parts[1:]:
                self.assertRegex(part, NAME_RE)
            for item in argv[1:]:
                self.assertNotEqual(item, "exec")
                if "{" in item or "}" in item:
                    self.assertIn(
                        item, PLACEHOLDERS[kind], "a placeholder is a whole argument"
                    )
            self.assertLessEqual(REQUIRED[kind], set(argv[1:]))
            timeout = command["timeout"]
            self.assertIsInstance(timeout, int)
            self.assertTrue(0 < timeout <= MAX_TIMEOUT)

    def test_scripts_are_executable_python_with_a_shebang(self):
        for kind in ("log", "sql"):
            path = os.path.join(ROOT, self.data[kind]["argv"][0])
            self.assertTrue(os.access(path, os.X_OK), path)
            with open(path, "rb") as handle:
                body = handle.read()
            self.assertTrue(body.startswith(b"#!/usr/bin/env python3\n"), path)
            self.assertLessEqual(len(body), MAX_SCRIPT_BYTES)
            self.assertTrue(body.isascii(), path)
            compile(body, path, "exec")

    def test_sources_match_the_script(self):
        sources = self.data["log"]["sources"]
        for source in sources:
            self.assertRegex(source, SOURCE_RE)
        with open(LOG, encoding="utf-8") as handle:
            declared = re.search(r"^SOURCES = \(([^)]*)\)", handle.read(), re.M).group(
                1
            )
        self.assertEqual(sources, re.findall(r'"([^"]+)"', declared))
        self.assertIn("worldserver", sources)
        self.assertIn("wow-overseer", sources)


class LogAdapterTest(unittest.TestCase):
    def fakes(self, report: str = REPORT, **extra):
        fakes = Fakes(self, {"realm-logs": FAKE_REALM_LOGS})
        return fakes, fakes.env(FAKE_REPORT=fakes.report(report), **extra)

    def test_prints_samples_window_and_count(self):
        fakes, env = self.fakes()
        done = run(LOG, ["worldserver", SINCE, "boat leg taken"], env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            done.stdout.splitlines(),
            [
                "2026-10-20T01:00:00Z overseer: boat leg taken by 4",
                "2026-10-21T02:00:00Z overseer: boat leg taken by 5",
                # From the window start (inside the archive) to its last line.
                "loom-evidence-window-hours: 36.5",
                "loom-evidence-count: 2",
            ],
        )
        self.assertEqual(
            fakes.recorded(),
            [["realm-logs", "report", "worldserver", SINCE, "boat leg taken"]],
        )

    def test_no_match_exits_one_and_still_says_the_window(self):
        _, env = self.fakes(EMPTY_REPORT)
        done = run(LOG, ["wow-overseer", SINCE, "drowned below the pier"], env)
        self.assertEqual(done.returncode, 1, done.stderr)
        # The archive starts after the window start: only what it holds counts.
        self.assertEqual(
            done.stdout.splitlines(),
            ["loom-evidence-window-hours: 24.0", "loom-evidence-count: 0"],
        )

    def test_a_failed_report_is_no_answer(self):
        _, env = self.fakes(FAKE_CODE="3")
        done = run(LOG, ["worldserver", SINCE, "boat leg taken"], env)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("exited 3", done.stderr)

    def test_a_report_without_the_needle_block_is_no_answer(self):
        _, env = self.fakes()
        done = run(LOG, ["worldserver", SINCE, "some other needle"], env)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")

    def test_an_unparseable_report_is_no_answer(self):
        _, env = self.fakes("kubectl: connection refused\n")
        done = run(LOG, ["worldserver", SINCE, "boat leg taken"], env)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")

    def test_without_realm_logs_on_path_it_says_so(self):
        fakes = Fakes(self, {})
        done = run(LOG, ["worldserver", SINCE, "boat leg taken"], fakes.env())
        self.assertEqual(done.returncode, 2)
        self.assertIn("realm-logs", done.stderr)

    def test_refused_arguments_run_nothing(self):
        cases = [
            ["mysql", SINCE, "boat leg taken"],
            ["worldserver", "yesterday", "boat leg taken"],
            ["worldserver", SINCE, "--until=2030-01-01T00:00:00Z"],
            ["worldserver", SINCE, ""],
            ["worldserver", SINCE],
        ]
        for args in cases:
            fakes, env = self.fakes()
            done = run(LOG, args, env)
            self.assertEqual(done.returncode, 2, args)
            self.assertEqual(done.stdout, "", args)
            self.assertEqual(fakes.recorded(), [], args)


class SqlAdapterTest(unittest.TestCase):
    STATEMENT = "SELECT name, level FROM characters WHERE level >= 60 LIMIT 2"
    ROWS = "name\tlevel\nZug\t60\nUzza\t61\n"

    def fakes(self, **extra):
        fakes = Fakes(self, {"kubectl": FAKE_KUBECTL, "mysql": FAKE_MYSQL})
        return fakes, fakes.env(**extra)

    def test_prints_one_line_per_row_and_closes_the_forward(self):
        fakes, env = self.fakes(FAKE_ROWS=self.ROWS)
        done = run(SQL, [self.STATEMENT], env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            done.stdout.splitlines(), ["name=Zug level=60", "name=Uzza level=61"]
        )
        self.assertTrue(
            fakes.wait_dead(fakes.forward_pid()), "the port-forward outlived the read"
        )
        (kubectl, mysql) = fakes.recorded()
        self.assertEqual(
            kubectl,
            [
                "kubectl",
                "-n",
                "wow-dev",
                "port-forward",
                "pod/mysql-0",
                ":3306",
                "--address",
                "127.0.0.1",
            ],
        )
        self.assertEqual(mysql[0:2], ["mysql", "--no-defaults"])
        self.assertIn("--port=43123", mysql)
        self.assertIn("--host=127.0.0.1", mysql)
        self.assertIn("--user=agent_reader", mysql)
        self.assertIn("--database=acore_characters", mysql)
        self.assertIn("--execute=" + self.STATEMENT, mysql)
        self.assertFalse([arg for arg in mysql if arg.startswith(("-p", "--password"))])

    def test_no_rows_exits_one(self):
        fakes, env = self.fakes(FAKE_ROWS="name\tlevel\n")
        done = run(SQL, [self.STATEMENT], env)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertTrue(fakes.wait_dead(fakes.forward_pid()))

    def test_a_client_error_is_no_answer_and_closes_the_forward(self):
        fakes, env = self.fakes(FAKE_CODE="1")
        done = run(SQL, [self.STATEMENT], env)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")
        self.assertIn("SELECT command denied", done.stderr)
        self.assertTrue(fakes.wait_dead(fakes.forward_pid()))

    def test_a_forward_that_never_opens_is_no_answer(self):
        fakes, env = self.fakes(FAKE_FORWARD_FAIL="1")
        done = run(SQL, [self.STATEMENT], env)
        self.assertEqual(done.returncode, 2)
        self.assertIn("did not open", done.stderr)
        self.assertEqual([call[0] for call in fakes.recorded()], ["kubectl"])

    def test_sigterm_mid_query_closes_the_forward(self):
        fakes, env = self.fakes(FAKE_ROWS=self.ROWS, FAKE_SLEEP="30")
        process = subprocess.Popen(
            [SQL, self.STATEMENT],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(process.kill)
        for _ in range(200):
            if [call[0] for call in fakes.recorded()] == ["kubectl", "mysql"]:
                break
            time.sleep(0.05)
        pid = fakes.forward_pid()
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=20), 2)
        process.stdout.close()
        process.stderr.close()
        self.assertTrue(fakes.wait_dead(pid), "the port-forward outlived a SIGTERM")

    def test_missing_mysql_client_says_so_and_runs_nothing(self):
        fakes = Fakes(self, {"kubectl": FAKE_KUBECTL})
        done = run(SQL, [self.STATEMENT], fakes.env())
        self.assertEqual(done.returncode, 2)
        self.assertIn("`mysql` is not on PATH", done.stderr)
        self.assertEqual(fakes.recorded(), [])

    def test_anything_but_one_select_or_show_is_refused_unrun(self):
        refused = [
            "DELETE FROM characters",
            "UPDATE characters SET level = 80",
            "INSERT INTO characters VALUES (1)",
            "DROP TABLE characters",
            "SELECT 1; DROP TABLE characters",
            "SELECT * FROM characters INTO OUTFILE '/tmp/x'",
            "SELECT name FROM characters FOR UPDATE",
            "SELECT SLEEP(100) FROM characters",
            "SELECT name FROM characters -- comment",
            "CALL reset_all()",
            "SET GLOBAL read_only = 0",
            "SELECT 1",
            "",
        ]
        for statement in refused:
            fakes, env = self.fakes(FAKE_ROWS=self.ROWS)
            done = run(SQL, [statement], env)
            self.assertEqual(done.returncode, 2, statement)
            self.assertIn("refused", done.stderr, statement)
            self.assertEqual(fakes.recorded(), [], statement)

    def test_show_and_with_select_run(self):
        for statement in (
            "SHOW TABLES",
            "WITH t AS (SELECT guid FROM characters) SELECT guid FROM t",
        ):
            _, env = self.fakes(FAKE_ROWS="guid\n7\n")
            done = run(SQL, [statement], env)
            self.assertEqual(done.returncode, 0, (statement, done.stderr))
            self.assertEqual(done.stdout, "guid=7\n")


class ReadOnlyTextTest(unittest.TestCase):
    """Neither script can exec into a pod, write through kubectl, or read the
    database as anyone but the SELECT-only reader."""

    def read(self, path: str) -> str:
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_no_exec_and_no_write_verb(self):
        writes = (
            r"\b(?:apply|create|delete|patch|edit|replace|scale|annotate|label|cordon|drain"
            r"|taint|cp|run|rollout|set|expose|attach|debug)\b"
        )
        for path in (LOG, SQL):
            text = self.read(path)
            self.assertNotRegex(text, r"kubectl\s+exec", path)
            self.assertNotRegex(text, r"[\"']exec[\"']", path)
            self.assertNotIn("os.system", text, path)
            self.assertNotIn("shell=True", text, path)
            # Every kubectl argv the script builds names one read-only verb.
            for verbs in re.findall(r'"-n",\s*NAMESPACE,\s*"([a-z-]+)"', text):
                self.assertNotRegex(verbs, writes, path)
        self.assertNotIn(
            '"kubectl"', self.read(LOG), "the log adapter reads only through realm-logs"
        )
        self.assertEqual(
            re.findall(r'"-n",\s*NAMESPACE,\s*"([a-z-]+)"', self.read(SQL)),
            ["port-forward"],
        )

    def test_only_the_select_only_reader_without_a_password(self):
        text = self.read(SQL)
        self.assertEqual(
            re.findall(r'^DB_USER = "([^"]*)"', text, re.M), ["agent_reader"]
        )
        self.assertEqual(text.count("--user="), 1)
        self.assertNotIn("--password", text)
        self.assertNotRegex(text, r'"-p|"-u')
        self.assertNotIn("mysql", self.read(LOG))


if __name__ == "__main__":
    unittest.main()
