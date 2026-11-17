"""GET /api/v2/whats-live: follower bridge commit, worldserver roll, and recent PRs (#2700)."""

import json
import pathlib
import shutil
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

with stub_modules(pymysql=PYMYSQL):
    import apiv2
    import realmmaint
    from apiv2 import whats_live as wl


NOW = datetime(2026, 11, 15, 16, 0, 0, tzinfo=timezone.utc)
NOW_EPOCH = int(NOW.timestamp())
DIGEST_BRIDGE = "sha256:" + "b" * 64
DIGEST_REALM = "sha256:" + "a" * 64

BRIDGE_HEAD = "9950c6363959828ee6b72500c0294cd96fc121d8"
BRIDGE_OLD = "6e5616d2a1b2c3d4e5f60718293a4b5c6d7e8f90"
BRIDGE_NEW = "2f05f6978c92d19b1e8d7cf48d96f080b362f96a"
MOD_PIN = "12b0e8ab1bbce7ef1e63b7d1b50d5ba2cb38ce56"
MOD_NEW = "abcdef1234567890abcdef1234567890abcdef12"


class _Reader:
    def __init__(self, answers=None, error=None):
        self.answers = answers or {}
        self.error = error

    def rows(self, sql, params=(), *, what=""):
        if self.error:
            raise self.error
        return list(self.answers.get(sql, []))


def _ctx(build_rows=(), version_rows=(), error=None):
    answers = {}
    if build_rows:
        from apiv2 import roll as v2roll

        answers[v2roll.BUILD_SQL] = list(build_rows)
    if version_rows:
        from apiv2 import roll as v2roll

        answers[v2roll.VERSION_SQL] = list(version_rows)
    return types.SimpleNamespace(read=_Reader(answers, error=error), server=None)


def _bridge_cm(commit=BRIDGE_HEAD, digest=DIGEST_BRIDGE, deployed_at="1794756601"):
    return {
        "metadata": {"name": "wow-dev-bridge-follow"},
        "data": {
            "merge": commit,
            "digest": digest,
            "deployed_at": deployed_at,
            "previous": BRIDGE_OLD[:10],
            "ship_pr": "2698",
        },
    }


def _banner_rows(module_commit=MOD_PIN, pins="match"):
    return [
        {"name": "realm", "value": "wow-dev", "source": "declared", "reported_at": NOW},
        {
            "name": "realm_kind",
            "value": "non-production",
            "source": "declared",
            "reported_at": NOW,
        },
        {
            "name": "mod-overseer",
            "value": module_commit,
            "source": "declared",
            "reported_at": NOW,
        },
        {"name": "pins", "value": pins, "source": "declared", "reported_at": NOW},
    ]


def _realm_status(state="UP", digest=DIGEST_REALM, started="2026-11-15T15:35:20Z"):
    if state == "UNKNOWN":
        return {
            "checked_at": realmmaint.iso(NOW),
            "state": "UNKNOWN",
            "alert": False,
            "summary": "Realm status not measured.",
            "worldserver": None,
            "unmeasured": {"state": "The cluster API read failed: 403"},
        }
    return {
        "checked_at": realmmaint.iso(NOW),
        "state": state,
        "alert": False,
        "summary": "Realm is up.",
        "worldserver": {
            "up": True,
            "desired_replicas": 1,
            "ready_replicas": 1,
            "started_at": started,
            "image_digest": digest,
            "restart_count": 0,
            "down_since": None,
        },
        "unmeasured": {},
    }


class RouteAndClusterReads(unittest.TestCase):
    def test_route_is_registered(self):
        self.assertIn("/api/v2/whats-live", apiv2.ROUTES)

    def test_bridge_follower_fixture_and_missing_record(self):
        got = wl.read_bridge(fetch_cm=lambda: _bridge_cm())
        self.assertEqual(got["commit"], BRIDGE_HEAD)
        self.assertEqual(got["short"], BRIDGE_HEAD[:12])
        self.assertEqual(got["digest"], DIGEST_BRIDGE)
        self.assertEqual(got["deployed_seconds"], 1794756601)
        self.assertTrue(got["deployed_at"].endswith("Z"))
        self.assertEqual(got["ship_pr"], 2698)
        self.assertEqual(got["unmeasured"], {})

        def boom():
            raise PermissionError("403 forbidden")

        missing = wl.read_bridge(fetch_cm=boom)
        self.assertEqual(missing["commit"], wl.UNKNOWN)
        self.assertEqual(missing["digest"], wl.UNKNOWN)
        self.assertEqual(missing["deployed_at"], wl.UNKNOWN)
        self.assertIn("bridge", missing["unmeasured"])
        self.assertIn("403 forbidden", missing["unmeasured"]["bridge"])

    def test_realm_banner_and_status_fixture_and_absent_module_commit(self):
        ctx = _ctx(
            build_rows=_banner_rows(),
            version_rows=[{"core_version": "AzerothCore rev. 8a4e76eac8c4+"}],
        )
        got = wl.read_realm(ctx, read_status=lambda now=None: _realm_status(), now=NOW)
        self.assertEqual(got["module_commit"], MOD_PIN)
        self.assertEqual(got["image_digest"], DIGEST_REALM)
        self.assertEqual(got["started_at"], "2026-11-15T15:35:20Z")
        self.assertEqual(got["core_revision"], "8a4e76eac8c4")
        self.assertEqual(got["unmeasured"], {})

        absent = wl.read_realm(
            _ctx(), read_status=lambda now=None: _realm_status("UNKNOWN"), now=NOW
        )
        self.assertEqual(absent["module_commit"], wl.UNKNOWN)
        self.assertEqual(absent["image_digest"], wl.UNKNOWN)
        self.assertEqual(absent["started_at"], wl.UNKNOWN)
        self.assertIn("module_commit", absent["unmeasured"])
        self.assertIn("realm", absent["unmeasured"])

    def test_banner_with_naive_db_datetimes_and_aware_clock(self):
        naive = NOW.replace(tzinfo=None)
        rows = _banner_rows()
        for row in rows:
            row["reported_at"] = naive
        ctx = _ctx(build_rows=rows)
        got = wl.read_realm(ctx, read_status=lambda now=None: _realm_status(), now=NOW)
        self.assertEqual(got["module_commit"], MOD_PIN)
        self.assertNotIn("banner", got["unmeasured"])


class CommitGraphAndLiveProof(unittest.TestCase):
    def test_pr_states_from_fixture_commit_graph_and_proof_markers(self):
        # Commit graph: BRIDGE_NEW -> BRIDGE_HEAD -> c1 -> BRIDGE_OLD
        parents = {
            BRIDGE_NEW: (BRIDGE_HEAD,),
            BRIDGE_HEAD: ("c1" + "0" * 38,),
            "c1" + "0" * 38: (BRIDGE_OLD,),
            BRIDGE_OLD: (),
        }
        ancestors = wl.ancestors_of(BRIDGE_HEAD, parents)
        proven = {2640}

        # Merged into main only (newer than BRIDGE_HEAD) -> merged (even if #470 had proof).
        self.assertEqual(
            wl.classify_pr_state(BRIDGE_NEW, [2700], BRIDGE_HEAD, ancestors, proven),
            "merged",
        )
        # Deployed on BRIDGE_HEAD, ticket without Live proof: -> deployed.
        self.assertEqual(
            wl.classify_pr_state(
                "c1" + "0" * 38, [2608], BRIDGE_HEAD, ancestors, proven
            ),
            "deployed",
        )
        # Deployed on BRIDGE_HEAD, ref'd ticket has Live proof: -> live-proven.
        self.assertEqual(
            wl.classify_pr_state(BRIDGE_HEAD, [2640], BRIDGE_HEAD, ancestors, proven),
            "live-proven",
        )
        # Deployed ticket must never promote an un-deployed PR on the same ticket.
        self.assertEqual(
            wl.classify_pr_state(BRIDGE_NEW, [2640], BRIDGE_HEAD, ancestors, proven),
            "merged",
        )
        # Unknown running commit -> unknown, never guesses.
        self.assertEqual(
            wl.classify_pr_state(BRIDGE_HEAD, [2640], wl.UNKNOWN, None, proven),
            wl.UNKNOWN,
        )

    def test_extract_refs_excludes_epic_part_of_and_extracts_live_proof(self):
        refs = wl.extract_refs(
            "Plan boat crossing (#2640)",
            "## Why\nFix crossing.\nRefs #2640\nPart of #470\n",
            pr_number=2698,
        )
        self.assertEqual(refs, [2640])

    def test_live_proof_marker_only_accepted_from_trusted_fleet_or_owner(self):
        comments = [
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/470",
                "user": {"login": "owner-handle"},
                "author_association": "OWNER",
                "body": "Live proof: epic tracking",
            },
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2640",
                "user": {"login": "agent-google-gemini[bot]"},
                "author_association": "NONE",
                "body": "Live proof: Draenei shamans crossed and trained.",
            },
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2641",
                "user": {"login": "agent-anthropic-claude-code[bot]"},
                "author_association": "CONTRIBUTOR",
                "body": "Live proof: verified on wow-dev.",
            },
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2642",
                "user": {"login": "agent-meta-muse[bot]"},
                "author_association": "NONE",
                "body": "Live proof: checked.",
            },
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2643",
                "user": {"login": "org-member"},
                "author_association": "MEMBER",
                "body": "Live proof: member confirmed.",
            },
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2699",
                "user": {"login": "random-stranger"},
                "author_association": "NONE",
                "body": "Live proof: spoofed by passerby.",
            },
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2697",
                "user": {"login": "outside-contributor"},
                "author_association": "CONTRIBUTOR",
                "body": "Live proof: spoofed by contributor.",
            },
            {
                "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2608",
                "user": {"login": "agent-anthropic-claude-code[bot]"},
                "author_association": "NONE",
                "body": "Reviewed and approved.",
            },
        ]
        proven = wl.extract_proven_tickets(comments)
        self.assertEqual(proven, {470, 2640, 2641, 2642, 2643})
        self.assertNotIn(2699, proven)
        self.assertNotIn(2697, proven)
        # Since extract_refs omitted Part of #470, #470 proof never promotes PR #2608.
        self.assertEqual(
            wl.extract_refs("Buy bank slots (#2608)", "Refs #2608\nPart of #470", 2687),
            [2608],
        )


class BoundedBoardAndRateLimits(unittest.TestCase):
    def _recent_iso(self, hours_ago):
        dt = NOW - timedelta(hours=hours_ago)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_live_board_reads_bounded_pages_and_classifies_both_repos(self):
        calls = []

        def fake_github(path):
            calls.append(path)
            if path.startswith("quadseven/wow-overseer/pulls"):
                return (
                    200,
                    [
                        {
                            "number": 2701,
                            "title": "Newer bridge PR (#2700)",
                            "body": "Refs #2700\nPart of #470",
                            "merged_at": self._recent_iso(1),
                            "updated_at": self._recent_iso(1),
                            "merge_commit_sha": BRIDGE_NEW,
                            "base": {"ref": "main"},
                            "html_url": "https://github.com/quadseven/wow-overseer/pull/2701",
                        },
                        {
                            "number": 2698,
                            "title": "Plan boat crossing (#2640)",
                            "body": "Refs #2640\nPart of #470",
                            "merged_at": self._recent_iso(2),
                            "updated_at": self._recent_iso(2),
                            "merge_commit_sha": BRIDGE_HEAD,
                            "base": {"ref": "main"},
                            "html_url": "https://github.com/quadseven/wow-overseer/pull/2698",
                        },
                    ],
                    {},
                )
            if path.startswith("quadseven/wow-overseer/commits?sha=" + BRIDGE_HEAD):
                return (
                    200,
                    [{"sha": BRIDGE_HEAD, "parents": [{"sha": BRIDGE_OLD}]}],
                    {},
                )
            if path.startswith("quadseven/wow-overseer/issues/comments"):
                return (
                    200,
                    [
                        {
                            "issue_url": "https://api.github.com/repos/quadseven/wow-overseer/issues/2640",
                            "user": {"login": "agent-anthropic-claude-code[bot]"},
                            "author_association": "NONE",
                            "body": "Live proof: shamans trained on Eastern Kingdoms.",
                        }
                    ],
                    {},
                )
            if path.startswith("quadseven/mod-overseer/pulls"):
                return (
                    200,
                    [
                        {
                            "number": 1568,
                            "title": "Add guild Promote and Motd verbs (#2616)",
                            "body": "Refs #2616",
                            "merged_at": self._recent_iso(3),
                            "updated_at": self._recent_iso(3),
                            "merge_commit_sha": MOD_NEW,
                            "base": {"ref": "main"},
                            "html_url": "https://github.com/quadseven/mod-overseer/pull/1568",
                        }
                    ],
                    {},
                )
            if path.startswith("quadseven/mod-overseer/commits?sha=" + MOD_PIN):
                return 200, [{"sha": MOD_PIN, "parents": []}], {}
            if path.startswith("quadseven/mod-overseer/issues/comments"):
                return 200, [], {}
            raise AssertionError("Unexpected path: " + path)

        board = wl.LiveBoard(
            fetch=fake_github,
            clock=lambda: float(NOW_EPOCH),
            spawn=lambda fn: fn(),
        )
        snap = board.snapshot(BRIDGE_HEAD, MOD_PIN)
        self.assertEqual(snap["prs_state"], "ready")
        by_num = {p["number"]: p for p in snap["prs"]}
        self.assertEqual(by_num[2701]["state"], "merged")
        self.assertEqual(by_num[2698]["state"], "live-proven")
        self.assertEqual(by_num[1568]["state"], "merged")
        self.assertLessEqual(len(calls), 8)

    def test_rate_limit_degrades_to_unknown_and_halts_until_reset(self):
        calls = []

        def limited_github(path):
            calls.append(path)
            return (
                403,
                None,
                {
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(NOW_EPOCH + 600),
                },
            )

        now = [float(NOW_EPOCH)]
        board = wl.LiveBoard(
            fetch=limited_github,
            clock=lambda: now[0],
            spawn=lambda fn: fn(),
        )
        snap1 = board.snapshot(BRIDGE_HEAD, MOD_PIN)
        self.assertEqual(snap1["prs_state"], "limited")
        self.assertEqual(snap1["prs"], [])
        self.assertIn("prs", snap1["unmeasured"])
        count_first = len(calls)
        self.assertEqual(count_first, 1)

        # Within reset window, second call makes zero GitHub requests.
        now[0] += 60
        snap2 = board.snapshot(BRIDGE_HEAD, MOD_PIN)
        self.assertEqual(snap2["prs_state"], "limited")
        self.assertEqual(len(calls), count_first)


@unittest.skipUnless(shutil.which("node"), "node is needed to render views")
class WhatsLiveSitePanel(unittest.TestCase):
    def test_panel_renders_live_unknown_and_safe_links(self):
        from test_app_shell import node_module

        payload = {
            "checked_at": realmmaint.iso(NOW),
            "bridge": {
                "commit": BRIDGE_HEAD,
                "short": BRIDGE_HEAD[:12],
                "digest": DIGEST_BRIDGE,
                "deployed_at": realmmaint.iso(NOW),
                "deployed_seconds": NOW_EPOCH,
                "ship_pr": 2698,
            },
            "realm": {
                "state": "UP",
                "up": True,
                "roll": "core 8a4e76eac8c4, module 12b0e8ab1bbc",
                "image_digest": DIGEST_REALM,
                "started_at": realmmaint.iso(NOW),
                "reported_at": "2026-11-15 15:36:02",
                "module_commit": MOD_PIN,
                "core_revision": "8a4e76eac8c4",
            },
            "prs_state": "ready",
            "prs_checked_at": NOW_EPOCH,
            "window_hours": 48,
            "prs": [
                {
                    "repo": "quadseven/wow-overseer",
                    "component": "bridge",
                    "number": 2698,
                    "title": "Plan boat crossing (#2640)",
                    "merge_commit": BRIDGE_HEAD,
                    "merged_at": realmmaint.iso(NOW),
                    "refs": [2640],
                    "url": "https://github.com/quadseven/wow-overseer/pull/2698",
                    "state": "live-proven",
                },
                {
                    "repo": "quadseven/mod-overseer",
                    "component": "module",
                    "number": 1568,
                    "title": "Evil URL PR",
                    "merge_commit": MOD_NEW,
                    "merged_at": realmmaint.iso(NOW),
                    "refs": [2616],
                    "url": "javascript:alert(1)",
                    "state": "merged",
                },
            ],
            "unmeasured": {},
        }
        read = {"data": payload, "error": None, "loading": False, "at": 1}
        out = node_module(
            "views/whatslive.js",
            "console.log(JSON.stringify(M.whatsLiveSection(%s, %d).s));"
            % (json.dumps(read), NOW_EPOCH + 30),
        )
        self.assertIn("9950c6363959", out)
        self.assertIn("12b0e8ab1bbc", out)
        self.assertIn("Live proven", out)
        self.assertIn("https://github.com/quadseven/wow-overseer/pull/2698", out)
        self.assertNotIn("javascript:alert(1)", out)

    def test_panel_renders_unknown_bridge_realm_and_prs(self):
        from test_app_shell import node_module

        payload = {
            "checked_at": realmmaint.iso(NOW),
            "bridge": {
                "commit": "unknown",
                "short": "unknown",
                "digest": "unknown",
                "deployed_at": "unknown",
                "deployed_seconds": None,
                "ship_pr": None,
            },
            "realm": {
                "state": "unknown",
                "up": None,
                "roll": "unknown",
                "image_digest": "unknown",
                "started_at": "unknown",
                "reported_at": "unknown",
                "module_commit": "unknown",
                "core_revision": "unknown",
            },
            "prs_state": "unknown",
            "prs_checked_at": NOW_EPOCH,
            "window_hours": 48,
            "prs": [],
            "unmeasured": {
                "bridge": "ConfigMap missing",
                "realm": "realm-status unreadable",
                "prs": "GitHub rate limit until 17:00",
            },
        }
        read = {"data": payload, "error": None, "loading": False, "at": 1}
        out = node_module(
            "views/whatslive.js",
            "console.log(JSON.stringify(M.whatsLiveSection(%s, %d).s));"
            % (json.dumps(read), NOW_EPOCH + 30),
        )
        self.assertIn("ConfigMap missing", out)
        self.assertIn("realm-status unreadable", out)
        self.assertIn("GitHub rate limit until 17:00", out)

    def test_server_view_reads_and_renders_whats_live(self):
        from test_app_shell import node_module

        reads = node_module(
            "views/server.js",
            "console.log(JSON.stringify(M.default.reads()));",
        )
        self.assertIn("/api/v2/whats-live", reads)
        rendered = node_module(
            "views/server.js",
            "const ctx = { get: (k) => k === '/api/v2/whats-live' ? "
            "{ data: { checked_at: null, bridge: { commit: 'unknown' }, "
            "realm: { state: 'unknown' }, prs_state: 'checking', prs: [], "
            "unmeasured: {} }, error: null, loading: false, at: 1 } "
            ": { data: null, error: null, loading: true, at: 0 } };"
            "console.log(JSON.stringify(M.default.render(ctx).s));",
        )
        self.assertIn("What&#39;s live", rendered)
        self.assertIn("Checking recent merged PRs", rendered)

    def test_api_doc_documents_whats_live_endpoint(self):
        doc = (HERE / "docs" / "API.md").read_text(encoding="utf-8")
        self.assertIn("## `GET /api/v2/whats-live`", doc)


if __name__ == "__main__":
    unittest.main()
