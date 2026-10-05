"""The realm roller's gate readers and its dry run (#590)."""

import contextlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import realm_roller  # noqa: E402
import realmroller_world as world  # noqa: E402

EXAMPLE = ROOT / "tools" / "realm_roller_example"
T0 = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)


def _family(name, inside=0, size=5):
    return {
        "family": name,
        "families": ["Grug", "Zug"],
        "members": [{"name": "m%d" % i, "instance": i < inside} for i in range(size)],
    }


class Fake:
    """A fetch that answers from a dict of url -> payload, None when absent."""

    def __init__(self, answers):
        self.answers = answers
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        return self.answers.get(url)


BASE = "http://site.example"


def _answers(grug=0, zug=0, active=()):
    return {
        BASE + "/api/family?family=Grug": _family("Grug", grug),
        BASE + "/api/family?family=Zug": _family("Zug", zug),
        BASE + "/api/guildruns": {"active": list(active), "recent": []},
    }


class FamilyReader(unittest.TestCase):
    def test_counts_members_inside_across_families(self):
        fetch = Fake(_answers(grug=2, zug=1))
        self.assertEqual(world.family_in_instance(BASE, ("Grug", "Zug"), fetch), 3)

    def test_all_out_is_zero(self):
        self.assertEqual(
            world.family_in_instance(BASE + "/", ("Grug", "Zug"), Fake(_answers())), 0
        )

    def test_the_default_family_answering_for_a_missing_one_is_unreadable(self):
        # The API falls back to its default family for a name it does not
        # know. Counting that answer would read Grug's members as Zug's.
        a = _answers()
        a[BASE + "/api/family?family=Zug"] = _family("Grug")
        self.assertIsNone(world.family_in_instance(BASE, ("Grug", "Zug"), Fake(a)))

    def test_unreachable_is_none(self):
        self.assertIsNone(world.family_in_instance(BASE, ("Grug",), Fake({})))

    def test_an_empty_family_is_unreadable_not_out(self):
        a = _answers()
        a[BASE + "/api/family?family=Grug"] = _family("Grug", size=0)
        self.assertIsNone(world.family_in_instance(BASE, ("Grug",), Fake(a)))


class FetchJson(unittest.TestCase):
    def test_only_http_and_https_are_read(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            f.write('{"family": "Grug"}')
            f.flush()
            with self.assertLogs("realmroller", "WARNING") as logs:
                self.assertIsNone(world.fetch_json("file://" + f.name))
        self.assertIn("only http and https are read", logs.output[0])


class GuildReader(unittest.TestCase):
    def test_counts_groups_in_the_named_states(self):
        active = [{"state": "inside"}, {"state": "queued"}, {"state": "inside"}]
        fetch = Fake(_answers(active=active))
        self.assertEqual(world.guild_groups_inside(BASE, ("inside",), fetch), 2)
        self.assertEqual(
            world.guild_groups_inside(BASE, ("inside", "queued"), fetch), 3
        )

    def test_unreadable_is_none(self):
        self.assertIsNone(world.guild_groups_inside(BASE, ("inside",), Fake({})))
        fetch = Fake({BASE + "/api/guildruns": {"error": "world unreachable"}})
        self.assertIsNone(world.guild_groups_inside(BASE, ("inside",), fetch))


class OutSince(unittest.TestCase):
    def test_carries_resets_and_starts(self):
        earlier = T0 - timedelta(minutes=7)
        self.assertEqual(world.carry_out_since(earlier, 0, T0), earlier)
        self.assertEqual(world.carry_out_since(None, 0, T0), T0)
        self.assertIsNone(world.carry_out_since(earlier, 1, T0))
        self.assertIsNone(world.carry_out_since(earlier, None, T0))


def _git(repo, *args, when=None):
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "HOME": str(repo),
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, env=env
    )


def _deploy_repo(tmp):
    """A deploy repo whose overlay digest moved at 01:00Z, then only a comment at 02:00Z."""
    repo = tmp / "deploy"
    (repo / "overlay").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    k = repo / "overlay" / "kustomization.yaml"
    k.write_text("images:\n  - name: worldserver\n    digest: sha256:%s\n" % ("a" * 64))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first", when="2026-10-05T00:00:00Z")
    k.write_text(k.read_text().replace("a" * 64, "b" * 64))
    _git(repo, "commit", "-qam", "roll", when="2026-10-05T01:00:00Z")
    k.write_text("# a comment\n" + k.read_text())
    _git(repo, "commit", "-qam", "comment", when="2026-10-05T02:00:00Z")
    return repo


class GitMarker(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_the_last_digest_change_not_the_last_commit(self):
        repo = _deploy_repo(self.tmp)
        when = world.git_marker_time(
            repo, "HEAD", "overlay/kustomization.yaml", "digest: sha256:"
        )
        self.assertEqual(when, datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc))

    def test_not_a_repo_is_none(self):
        self.assertIsNone(world.git_marker_time(self.tmp, "HEAD", "x", "y"))


class _Site(BaseHTTPRequestHandler):
    answers: dict = {}

    def do_GET(self):  # noqa: N802
        body = self.answers.get(self.path)
        if body is None:
            self.send_response(503)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class DryRun(unittest.TestCase):
    """The command line end to end: a real HTTP site, a real git repo, no writes."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = _deploy_repo(self.tmp)
        self.roller = self.tmp / "roller"
        shutil.copytree(EXAMPLE, self.roller)
        _Site.answers = {
            urllib.parse.urlsplit(u)._replace(scheme="", netloc="").geturl(): v
            for u, v in _answers(grug=2).items()
        }
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def run_cli(self, *extra):
        out = io.StringIO()
        before = {p: p.read_bytes() for p in self.roller.rglob("*.json")}
        with contextlib.redirect_stdout(out):
            code = realm_roller.main(
                [
                    "dry-run",
                    "--roller-dir",
                    str(self.roller),
                    "--deploy-repo",
                    str(self.repo),
                    "--site-url",
                    self.url,
                    *extra,
                ]
            )
        # A dry run writes nothing.
        self.assertEqual(
            before, {p: p.read_bytes() for p in self.roller.rglob("*.json")}
        )
        return code, out.getvalue().splitlines()

    def test_paused_example_reports_readings_and_waits(self):
        code, lines = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("PAUSED", lines[0])
        self.assertIn("family in instance: 2; guild groups inside: 0", lines[4])
        self.assertTrue(
            lines[-1].startswith("dry-run  would wait r2026.10.04-2: channel paused"),
            lines[-1],
        )

    def test_unpaused_with_a_family_inside_waits_on_the_family(self):
        ch = json.loads((self.roller / "channel.json").read_text())
        ch["paused"] = False
        (self.roller / "channel.json").write_text(json.dumps(ch))
        _, lines = self.run_cli()
        self.assertEqual(
            lines[-1],
            "dry-run  would wait r2026.10.04-2: 2 family member(s) in an instance",
        )

    def test_an_invalid_file_fails_before_any_read(self):
        (self.roller / "releases" / "r2026.10.04-2.json").write_text("{}")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = realm_roller.main(["validate", "--roller-dir", str(self.roller)])
        self.assertEqual(code, 1)
        self.assertIn("invalid:", err.getvalue())

    def test_validate_the_shipped_example(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                realm_roller.main(["validate", "--roller-dir", str(EXAMPLE)]), 0
            )
        self.assertEqual(out.getvalue().strip(), "ok: channel dev, 3 release(s)")


if __name__ == "__main__":
    unittest.main()
