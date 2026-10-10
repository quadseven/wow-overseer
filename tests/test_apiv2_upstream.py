"""GET /api/v2/upstream: how far behind each pinned dependency is (apiv2/upstream.py).

GitHub is a fake `fetch` returning (status, body, headers) and the clock is a
list the tests move, so nothing here touches the network or sleeps. They hold
the contract the Server view reads: pins from the realm's own report, an
answer that never waits for GitHub, an hourly cache, and "not measured" (never
a guess) when GitHub is rate limited or fails.
"""

import json
import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
from apiv2 import upstream  # noqa: E402

PIN = "a" * 40
HEAD = "b" * 40


def commit(title, sha=HEAD, date="2026-10-01T12:00:00Z"):
    return {"sha": sha, "commit": {"message": title, "committer": {"date": date}}}


def compare_body(
    ahead=2, behind=0, titles=("fix(Bot): a crash in loot", "Merge pull request #1")
):
    commits = [commit(t, sha=("%02d" % i) * 20) for i, t in enumerate(titles)]
    return {
        "ahead_by": ahead,
        "behind_by": behind,
        "commits": commits,
        "base_commit": {
            "sha": PIN,
            "commit": {"committer": {"date": "2026-09-01T00:00:00Z"}},
        },
    }


class Wire:
    """A fake GitHub: `answers` maps a repo to (status, body, headers)."""

    def __init__(self, default=None, **by_repo):
        self.default = default or (200, compare_body(), {})
        self.by_repo = by_repo
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        repo = "/".join(path.split("/")[:2])
        return self.by_repo.get(repo, self.default)


PINS = {
    "core": ("7f12e89ee5f4", "realm"),
    "mod-playerbots": (PIN, "realm"),
    "mod-ollama-chat": (PIN, "realm"),
}


def board(wire, clock):
    """A Board whose refresh runs where it is asked, so a test can hold it back."""
    queued = []
    b = upstream.Board(fetch=wire, clock=lambda: clock[0], spawn=queued.append)
    b.queued = queued
    return b


def settle(b, pins=PINS):
    """Ask once and run the refresh it started."""
    b.snapshot(pins)
    while b.queued:
        b.queued.pop(0)()
    return b.snapshot(pins)


def by_name(payload):
    return {r["name"]: r for r in payload["rows"]}


class Notable(unittest.TestCase):
    def test_bookkeeping_is_dropped_and_kinds_are_read_from_titles(self):
        commits = [
            commit("Merge pull request #5 from x/test-staging"),
            commit("chore(DB): import pending files"),
            commit("fix(Bot/Chat): Stop addon messages from commanding bots (#2872)"),
            commit(
                "fix(Bot): never read an Item after a call that can free it (#2811)"
            ),
            commit("feat(Bot): a new thing"),
        ]
        top, counts = upstream.notable(commits)
        self.assertEqual(len(top), 3)
        self.assertEqual(top[0]["tags"][0], "security")
        self.assertIn("crash", top[1]["tags"])
        self.assertEqual(counts["security"], 1)
        self.assertEqual(counts["crash"], 1)

    def test_the_list_is_capped_and_newest_first_within_a_kind(self):
        commits = [
            commit("fix(Bot): change %d" % i, sha="%040x" % i) for i in range(20)
        ]
        top, _ = upstream.notable(commits)
        self.assertEqual(len(top), upstream.LISTED)
        self.assertEqual(top[0]["title"], "fix(Bot): change 19")

    def test_titles_are_one_line_of_ascii(self):
        line = upstream.ascii_line(
            "fix \u2014 caf\u00e9 \u201cx\u201d\nsecond line " + "y" * 200
        )
        self.assertTrue(line.isascii())
        self.assertNotIn("\n", line)
        self.assertLessEqual(len(line), 110)
        self.assertNotIn("\u2014", line)


class Compare(unittest.TestCase):
    def test_a_long_gap_reads_its_newest_page_too(self):
        pages = {
            1: compare_body(ahead=300, titles=("old",)),
            2: compare_body(ahead=300, titles=("new",)),
        }

        def fetch(path):
            return 200, pages[int(path.rsplit("page=", 1)[1])], {}

        got = upstream.compare(fetch, 0, "o/r", PIN, "main")
        self.assertEqual(
            [c["commit"]["message"] for c in got["commits"]], ["old", "new"]
        )

    def test_an_unknown_pin_is_none(self):
        self.assertIsNone(
            upstream.compare(lambda p: (404, None, {}), 0, "o/r", PIN, "main")
        )

    def test_a_spent_rate_limit_raises_with_its_reset(self):
        def spent(path):
            return (
                403,
                None,
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "5000"},
            )

        with self.assertRaises(upstream.Limited) as caught:
            upstream.compare(spent, 0, "o/r", PIN, "main")
        self.assertEqual(caught.exception.until, 5000)

    def test_a_forbidden_with_budget_left_is_not_a_rate_limit(self):
        denied = lambda p: (403, None, {"X-RateLimit-Remaining": "12"})  # noqa: E731
        self.assertIsNone(upstream.compare(denied, 0, "o/r", PIN, "main"))


class Reading(unittest.TestCase):
    def test_a_measured_row_says_pinned_head_behind_and_when(self):
        clock = [10000.0]
        b = board(Wire(), clock)
        payload = settle(b)
        row = by_name(payload)["mod-playerbots"]
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(row["status"], "behind")
        self.assertEqual(row["behind"], 2)
        self.assertEqual(row["pinned"], PIN[:12])
        self.assertEqual(row["pin_source"], "realm")
        self.assertEqual(row["checked_at"], 10000)
        self.assertEqual(row["pinned_at"], 1788220800)
        self.assertEqual(row["notable"][0]["title"], "fix(Bot): a crash in loot")
        self.assertTrue(
            row["url"].startswith(
                "https://github.com/mod-playerbots/mod-playerbots/compare/"
            )
        )

    def test_zero_commits_ahead_is_current(self):
        clock = [1.0]
        row = by_name(
            settle(
                board(Wire(default=(200, compare_body(ahead=0, titles=()), {})), clock)
            )
        )
        self.assertEqual(row["mod-ollama-chat"]["status"], "current")
        self.assertEqual(row["mod-ollama-chat"]["behind"], 0)

    def test_a_project_without_a_pin_is_not_measured_not_zero(self):
        row = by_name(settle(board(Wire(), [1.0])))["mod-junk-to-gold"]
        self.assertEqual(row["status"], "not measured")
        self.assertIsNone(row["behind"])
        self.assertIsNone(row["pinned"])

    def test_the_payload_is_json_and_ascii(self):
        text = json.dumps(settle(board(Wire(), [1.0])))
        self.assertTrue(text.isascii())


class NeverBlocks(unittest.TestCase):
    def test_a_cold_ask_answers_checking_without_calling_github(self):
        wire = Wire()
        b = board(wire, [1.0])
        payload = b.snapshot(PINS)
        self.assertEqual(wire.calls, [])
        self.assertEqual(payload["state"], "checking")
        self.assertEqual(len(b.queued), 1)
        rows = by_name(payload)
        self.assertEqual(rows["mod-playerbots"]["status"], "not measured")
        self.assertEqual(rows["mod-playerbots"]["pinned"], PIN[:12])

    def test_asks_while_a_refresh_runs_start_no_second_one(self):
        b = board(Wire(), [1.0])
        b.snapshot(PINS)
        b.snapshot(PINS)
        self.assertEqual(len(b.queued), 1)

    def test_a_refresh_that_raises_unlocks_the_next_ask(self):
        def boom(path):
            raise RuntimeError("down")

        b = board(boom, [1.0])
        b.snapshot(PINS)
        with self.assertRaises(RuntimeError):
            b.queued.pop(0)()
        self.assertFalse(b.running)


class Cache(unittest.TestCase):
    def test_an_hour_of_asks_cost_one_refresh_then_one_more(self):
        clock = [0.0]
        wire = Wire()
        b = board(wire, clock)
        settle(b)
        first = len(wire.calls)
        clock[0] = upstream.TTL - 1
        b.snapshot(PINS)
        self.assertEqual(b.queued, [])
        self.assertEqual(len(wire.calls), first)
        clock[0] = upstream.TTL + 1
        settle(b)
        self.assertGreater(len(wire.calls), first)

    def test_a_changed_pin_is_read_again_at_once(self):
        clock = [0.0]
        wire = Wire()
        b = board(wire, clock)
        settle(b)
        moved = dict(PINS, **{"mod-playerbots": ("c" * 40, "realm")})
        b.snapshot(moved)
        self.assertEqual(len(b.queued), 1)


class Failures(unittest.TestCase):
    def test_a_rate_limit_reads_not_measured_and_waits_for_the_reset(self):
        clock = [1000.0]
        spent = (403, None, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4600"})
        wire = Wire(default=spent)
        b = board(wire, clock)
        payload = settle(b)
        self.assertEqual(payload["state"], "limited")
        self.assertEqual(payload["limited_until"], 4600)
        self.assertEqual(by_name(payload)["mod-playerbots"]["status"], "not measured")
        self.assertIn("rate limit", by_name(payload)["mod-playerbots"]["reason"])
        asked = len(wire.calls)
        self.assertEqual(asked, 1)  # the first refusal stops the round
        clock[0] = 4000.0
        b.snapshot(PINS)
        self.assertEqual(b.queued, [])
        clock[0] = 4700.0
        payload = b.snapshot(PINS)
        self.assertEqual(len(b.queued), 1)
        self.assertNotEqual(payload["state"], "limited")

    def test_a_network_failure_is_not_measured_and_retried_later_not_at_once(self):
        clock = [0.0]
        wire = Wire(default=(0, None, {}))
        b = board(wire, clock)
        payload = settle(b)
        self.assertEqual(by_name(payload)["mod-playerbots"]["status"], "not measured")
        self.assertIsNone(payload["checked_at"])
        calls = len(wire.calls)
        clock[0] = upstream.RETRY - 1
        b.snapshot(PINS)
        self.assertEqual(len(wire.calls), calls)
        self.assertEqual(b.queued, [])
        clock[0] = upstream.RETRY + 1
        b.snapshot(PINS)
        self.assertEqual(len(b.queued), 1)

    def test_a_failure_after_a_good_reading_keeps_it_marked_stale(self):
        clock = [0.0]
        wire = Wire()
        b = board(wire, clock)
        settle(b)
        wire.default = (500, None, {})
        clock[0] = upstream.TTL + 1
        row = by_name(settle(b))["mod-playerbots"]
        self.assertEqual(row["status"], "behind")
        self.assertTrue(row["stale"])
        self.assertEqual(row["checked_at"], 0)

    def test_an_unknown_commit_for_one_project_leaves_the_others(self):
        wire = Wire(**{"mod-playerbots/mod-playerbots": (404, None, {})})
        rows = by_name(settle(board(wire, [1.0])))
        self.assertEqual(rows["mod-playerbots"]["status"], "not measured")
        self.assertEqual(rows["mod-ollama-chat"]["status"], "behind")
        self.assertEqual(rows["core"]["status"], "behind")


class Pins(unittest.TestCase):
    PAYLOAD = {
        "core_revision": "7f12e89ee5f4",
        "upstreams": [
            {"name": "mod-playerbots", "value": PIN},
            {"name": "crossing", "value": "boards"},
            {"name": "mod-ollama-chat", "value": "not a sha"},
        ],
    }

    def test_the_realms_report_is_the_pin(self):
        pins = upstream.declared_pins(self.PAYLOAD, {})
        self.assertEqual(pins["core"], ("7f12e89ee5f4", "realm"))
        self.assertEqual(pins["mod-playerbots"], (PIN, "realm"))
        self.assertNotIn("crossing", pins)
        self.assertNotIn("mod-ollama-chat", pins)

    def test_the_environment_fills_only_what_the_realm_does_not_report(self):
        env = {
            upstream.ENV_PINS: json.dumps(
                {"mod-junk-to-gold": "D" * 40, "mod-playerbots": "e" * 40}
            )
        }
        pins = upstream.declared_pins(self.PAYLOAD, env)
        self.assertEqual(pins["mod-junk-to-gold"], ("d" * 40, "environment"))
        self.assertEqual(pins["mod-playerbots"][1], "realm")

    def test_a_malformed_environment_is_ignored(self):
        for raw in ("{", "[1]", '{"x": "zz"}', ""):
            self.assertEqual(upstream.env_pins({upstream.ENV_PINS: raw}), {})

    def test_a_realm_that_reported_nothing_has_no_pins(self):
        self.assertEqual(upstream.declared_pins({}, {}), {})


class Handler(unittest.TestCase):
    def ctx(self, payload):
        server = types.SimpleNamespace(
            realm=types.SimpleNamespace(build_realm=lambda **rows: payload),
            _BUILD_SQL="b",
            _WORLD_VERSION_SQL="w",
            _REALMLIST_SQL="r",
        )
        read = types.SimpleNamespace(rows=lambda *a, **k: [])
        return types.SimpleNamespace(server=server, read=read)

    def test_the_route_is_registered_and_answers_from_the_realms_pins(self):
        fresh = board(Wire(), [1.0])
        original = upstream.BOARD
        upstream.BOARD = fresh
        try:
            status, payload = apiv2.handle(
                "/api/v2/upstream", {}, self.ctx(Pins.PAYLOAD)
            )
        finally:
            upstream.BOARD = original
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "checking")
        self.assertEqual(by_name(payload)["mod-playerbots"]["pinned"], PIN[:12])
        self.assertEqual(len(payload["rows"]), len(upstream.COMPONENTS))

    def test_no_token_is_read_or_sent(self):
        source = (HERE / "apiv2" / "upstream.py").read_text()
        self.assertNotIn("Authorization", source)
        self.assertNotIn("GITHUB_TOKEN", source)


if __name__ == "__main__":
    unittest.main()
