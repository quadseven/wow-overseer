"""eph collect: evidence posts, closes only under the rule, identity is checked."""

import base64
import hashlib
import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

from eph_fakes import FakeCluster, FakeGh, make_cfg
from ephemeral import collect, ghx, kube

DECREE_TEXT = "decree: v1\nid: demo-decree\n"
SHA = hashlib.sha256(DECREE_TEXT.encode()).hexdigest()
REPO = "quadseven/mod-dungeon-clear"
MAIN = "quadseven/wow-overseer"
HEAD = "h" * 40
COMMIT = "m" * 40
ENV = {"GH_TOKEN": "t", "GH_CONFIG_DIR": "/some/dir"}
ISSUE_BODY = "## Acceptance\n- [x] unit tests\n- [ ] Live: the family leaves without a patron dying\n"


def record(treatment_state="present"):
    runs = []
    for n in (1, 2, 3):
        for arm, ch in (("control", "c"), ("treatment", "t")):
            runs.append({"run_id": f"abc123-{ch}{n}", "arm": arm, "n": n,
                         "images": {"worldserver": f"r.example/ws@sha256:{'1' * 64}", "dbimport": "x"}})  # fmt: skip
    return {
        "batch": "abc123", "decree_id": "demo-decree", "decree_sha256": SHA,
        "decree_pr": 9, "class": "lean",
        "proves": [{"repo": REPO, "issue": 12, "criterion": "the family leaves without a patron dying"}],
        "runs": runs, "runs_wanted": {"control": 3, "treatment": 3},
        "presence": {"control": {"state": "absent", "pin": "p" * 40},
                     "treatment": {"state": treatment_state, "pin": "q" * 40}},
        "fidelity_deltas": ["Playerbots.MaxRandomBots: 2600 -> 0"],
    }  # fmt: skip


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_cfg(self.tmp.name)
        self.cfg.ledger_path = str(pathlib.Path(self.tmp.name) / "ledger.jsonl")
        self.c = FakeCluster()
        self.k = kube.Kubectl("wow-ephemeral", runner=self.c)
        self.fg = FakeGh()
        self.gh = ghx.Gh(self.fg, env=ENV, author="agent-anthropic-claude-code[bot]")
        self.logs = []
        self.rec = record()
        self.save(self.rec)
        self.main()
        self.issue()

    def save(self, rec):
        p = (
            pathlib.Path(self.cfg.results_dir)
            / rec["decree_id"]
            / f"batch-{rec['batch']}.json"
        )
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec), encoding="utf-8")

    def main(
        self,
        text=DECREE_TEXT,
        approver="luna[bot]",
        pr_author="agent-anthropic-claude-code[bot]",
    ):
        a = self.fg.answers
        a[("GET", f"repos/{MAIN}/contents/data/decrees/demo-decree.yaml?ref=main")] = {
            "encoding": "base64", "content": base64.b64encode(text.encode()).decode()}  # fmt: skip
        a[
            (
                "GET",
                f"repos/{MAIN}/commits?path=data/decrees/demo-decree.yaml&sha=main&per_page=1",
            )
        ] = [{"sha": COMMIT}]
        a[("GET", f"repos/{MAIN}/commits/{COMMIT}/pulls")] = [
            {"number": 7, "merged_at": "2026-11-15T00:00:00Z", "user": {"login": pr_author}, "head": {"sha": HEAD}}]  # fmt: skip
        a[("GET", f"repos/{MAIN}/pulls/7/reviews?per_page=100")] = (
            [{"state": "APPROVED", "user": {"login": approver}, "commit_id": HEAD}]
            if approver
            else []
        )

    def issue(self, body=ISSUE_BODY, labels=("awaiting-live-check",), state="open"):
        self.fg.answers[("GET", f"repos/{REPO}/issues/12")] = {
            "state": state, "body": body, "labels": [{"name": n} for n in labels]}  # fmt: skip
        self.fg.answers[("GET", f"repos/{REPO}/labels/ready-for-agent")] = {
            "name": "ready-for-agent"
        }

    def results(self, control, treatment, sha=SHA):
        for r in self.rec["runs"]:
            v = (control if r["arm"] == "control" else treatment)[r["n"] - 1]
            if v is None:
                continue
            body = {"verdict": v, "decree_sha256": sha, "run_id": r["run_id"], "arm": r["arm"],
                    "assertions": [{"name": "zero-patron-deaths", "role": "check", "status": "held",
                                    "expect": {"rows": 0}, "sql": "SELECT 1 FROM x", "observed": "rows=0",
                                    "sample": [["Grim Patron", 5]]}]}  # fmt: skip
            self.c.put("configmaps", "wow-ephemeral", f"eph-result-{r['run_id']}", {
                "metadata": {"labels": {"eph/verdict": v, "eph/decree": "demo-decree", "eph/arm": r["arm"]}},
                "data": {"verdict": v, "result.json": json.dumps(body)}})  # fmt: skip

    def collect(self, post=True, env=None):
        col = collect.Collector(
            self.cfg,
            self.k,
            self.gh,
            env=ENV if env is None else env,
            out=self.logs.append,
            clock=lambda: 1794787200.0,
        )
        return col.run(post=post)

    def writes(self):
        return [
            (c[0][4] if "-X" in c[0] else "GET", c[0][2])
            for c in self.fg.calls
            if "-X" in c[0]
        ]

    def ledger(self):
        p = pathlib.Path(self.cfg.ledger_path)
        return (
            [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            if p.exists()
            else []
        )

    def closes(self):
        return [c for c in self.fg.calls if c[1] and '"state": "closed"' in c[1]]


class ProvenTest(Base):
    def test_proven_comments_ticks_unlabels_and_closes_in_order(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.assertEqual(self.collect(), {"abc123": "proven"})
        comments = self.fg.comments[f"repos/{REPO}/issues/12/comments"]
        self.assertEqual(len(comments), 1)
        self.assertIn("<!-- eph:demo-decree:" + SHA + " -->", comments[0]["body"])
        self.assertIn("p = 1/20", comments[0]["body"])
        self.assertIn(
            "-- claude-code (Overseer, PC session, ephemeral worlds)",
            comments[0]["body"],
        )
        self.assertNotIn("r.example", comments[0]["body"])
        self.assertIn("sha256:" + "1" * 64, comments[0]["body"])
        calls = [
            (c[0][2], c[0][c[0].index("-X") + 1] if "-X" in c[0] else "GET", c[1])
            for c in self.fg.calls
        ]
        order = [i for i, (p, m, body) in enumerate(calls) if m in ("PATCH", "DELETE")]
        self.assertEqual(calls[order[0]][1], "PATCH")  # the body edit comes first
        self.assertIn("[x] Live: the family", calls[order[0]][2])
        self.assertIn('"state": "closed"', calls[order[-1]][2] or "")
        self.assertIn('"state_reason": "completed"', calls[order[-1]][2])
        self.assertTrue(
            any(
                m == "DELETE" and "labels/awaiting-live-check" in p for p, m, _ in calls
            )
        )
        self.assertEqual(self.ledger()[0]["verdict"], "proven")

    def test_a_second_run_posts_and_closes_nothing_more(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        n = len(self.fg.calls)
        self.collect()
        self.assertEqual(len(self.fg.calls), n)

    def test_a_proven_rerun_posts_its_own_evidence_before_updating_the_issue(self):
        target = f"repos/{REPO}/issues/12/comments"
        prior_rows = "\n".join(
            f"| `{run['run_id'].replace('abc123', 'def456')}` | {run['arm']} | PASS |"
            for run in self.rec["runs"]
        )
        self.fg.comments[target] = [
            {
                "user": {"login": self.cfg.author_login},
                "body": f"<!-- eph:demo-decree:{SHA} -->\n**underpowered**\n{prior_rows}",
                "html_url": "https://example.com/old",
            }
        ]
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(len(self.fg.comments[target]), 2)
        evidence = self.fg.comments[target][-1]
        self.assertIn("**proven**", evidence["body"])
        self.assertIn("`abc123-t3`", evidence["body"])
        self.assertEqual(self.ledger()[0]["comment_url"], evidence["html_url"])
        self.assertEqual(
            self.writes()[:2],
            [("POST", target), ("PATCH", f"repos/{REPO}/issues/12")],
        )
        self.assertEqual(len(self.closes()), 1)

    def test_self_approval_never_closes(self):
        self.main(approver="agent-anthropic-claude-code[bot]")
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])
        self.assertEqual(len(self.fg.comments[f"repos/{REPO}/issues/12/comments"]), 1)
        self.assertIn("not closed", self.ledger()[0]["evidence"])

    def test_no_approval_never_closes(self):
        self.main(approver=None)
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])

    def test_marker_approval_from_another_app_counts(self):
        self.main(approver=None)
        mark = f"<!-- fleet:review v1 verdict=APPROVE head={HEAD} -->"
        self.fg.comments[f"repos/{MAIN}/issues/7/comments"] = [
            {"user": {"login": "luna[bot]"}, "body": mark}
        ]
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(len(self.closes()), 1)

    def test_marker_approval_from_the_author_does_not_count(self):
        self.main(approver=None)
        mark = f"<!-- fleet:review v1 verdict=APPROVE head={HEAD} -->"
        self.fg.comments[f"repos/{MAIN}/issues/7/comments"] = [
            {"user": {"login": "agent-anthropic-claude-code[bot]"}, "body": mark}]  # fmt: skip
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])

    def test_proof_records_its_box_before_unrelated_live_boxes_block_close(self):
        body = (
            "## Departure\n"
            "- [ ] Live: the family leaves without a patron dying\n"
            "- [ ] Live: a witness follows the family\n"
            "## Return\n"
            "- [ ] Live: the family returns before nightfall\n"
        )
        self.issue(body=body)
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.assertEqual(self.collect(), {"abc123": "proven"})
        issue_path = f"repos/{REPO}/issues/12"
        writes = self.writes()
        self.assertEqual(
            writes, [("POST", f"{issue_path}/comments"), ("PATCH", issue_path)]
        )
        issue_edits = [
            json.loads(payload)
            for argv, payload in self.fg.calls
            if argv[2] == issue_path and "PATCH" in argv
        ]
        self.assertEqual(issue_edits, [{"body": body.replace("[ ]", "[x]", 1)}])
        self.assertIn("unticked", self.ledger()[0]["evidence"])
        self.collect()
        self.assertEqual(self.writes(), writes)

    def assert_evidence_only(self, body):
        self.issue(body=body)
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.assertEqual(self.collect(), {"abc123": "proven"})
        self.assertEqual(self.writes(), [("POST", f"repos/{REPO}/issues/12/comments")])

    def test_proof_cannot_tick_a_longer_live_criterion(self):
        self.assert_evidence_only(
            "- [ ] Live: the family leaves without a patron dying and returns in 10 minutes\n"
        )

    def test_proof_without_a_matching_box_keeps_a_checked_issue_open(self):
        self.assert_evidence_only("- [x] the family returns before nightfall\n")

    def test_proof_without_a_matching_box_keeps_an_issue_with_no_boxes_open(self):
        self.assert_evidence_only(
            "## Acceptance\nThe family returns before nightfall.\n"
        )

    def test_proof_with_duplicate_matching_boxes_is_evidence_only(self):
        self.assert_evidence_only(
            "- [x] the family leaves without a patron dying\n"
            "- [ ] Live: the family leaves without a patron dying\n"
        )

    def test_an_epic_is_never_closed(self):
        self.issue(labels=("awaiting-live-check", "epic"))
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])

    def test_unchecked_fix_presence_closes_nothing(self):
        self.rec = record("unchecked")
        self.save(self.rec)
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])
        self.assertEqual(self.fg.comments, {})

    def test_decree_changed_since_the_run_is_not_on_main(self):
        self.main(text=DECREE_TEXT + "# edited\n")
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])
        self.assertNotIn(f"repos/{REPO}/issues/12/comments", self.fg.comments)
        self.assertEqual(
            len(self.fg.comments[f"repos/{MAIN}/issues/9/comments"]), 1
        )  # the decree's own PR

    def test_an_already_closed_issue_gets_the_comment_only(self):
        self.issue(state="closed")
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])
        self.assertEqual(len(self.fg.comments[f"repos/{REPO}/issues/12/comments"]), 1)


class NotProvenTest(Base):
    def test_disproven_posts_unlabels_and_leaves_open(self):
        self.results(["FAIL"] * 3, ["PASS", "FAIL", "PASS"])
        self.assertEqual(self.collect(), {"abc123": "disproven"})
        self.assertEqual(self.closes(), [])
        self.assertEqual(len(self.fg.comments[f"repos/{REPO}/issues/12/comments"]), 1)
        sent = [c for c in self.fg.calls if "labels" in c[0][2] and "-X" in c[0]]
        self.assertTrue(any("ready-for-agent" in (c[1] or "") for c in sent))
        self.assertEqual(self.ledger()[0]["verdict"], "disproven")

    def test_control_pass_posts_nothing_to_the_issue(self):
        self.results(["PASS", None, None], ["PASS", None, None])
        self.assertEqual(self.collect(), {"abc123": "non-discriminating"})
        self.assertEqual(self.fg.comments, {})
        self.assertEqual(self.closes(), [])
        self.assertEqual(self.ledger()[0]["verdict"], "unclear")

    def test_invalid_posts_nothing_and_closes_nothing(self):
        self.results(["INVALID", None, None], ["PASS", None, None])
        self.collect()
        self.assertEqual(self.fg.comments, {})
        self.assertEqual(self.closes(), [])

    def test_pass_uncontrolled_posts_evidence_and_leaves_it_open(self):
        self.results(["INVALID"] * 3, ["PASS"] * 3)
        self.assertEqual(self.collect(), {"abc123": "pass-uncontrolled"})
        self.assertEqual(len(self.fg.comments[f"repos/{REPO}/issues/12/comments"]), 1)
        self.assertEqual(self.closes(), [])

    def test_pending_does_nothing_and_stays_open_for_a_later_run(self):
        self.results(["FAIL", None, None], ["PASS", None, None])
        self.assertEqual(self.collect(), {"abc123": "pending"})
        self.assertEqual(self.fg.comments, {})
        self.assertFalse(
            (
                pathlib.Path(self.cfg.results_dir)
                / "demo-decree"
                / "decision-abc123.json"
            ).exists()
        )

    def test_dry_run_writes_nothing_anywhere(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.assertEqual(self.collect(post=False, env={}), {"abc123": "proven"})
        self.assertEqual(self.writes(), [])


class IdentityTest(Base):
    def test_empty_token_refuses_before_any_write(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        with self.assertRaises(ghx.GhError):
            self.collect(env={"GH_TOKEN": "", "GH_CONFIG_DIR": "/d"})
        self.assertEqual(self.writes(), [])

    def test_missing_config_dir_refuses(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        with self.assertRaises(ghx.GhError):
            self.collect(env={"GH_TOKEN": "t"})

    def test_comment_by_the_wrong_author_stops_before_the_close(self):
        FakeGh.author = "someone-personal"
        self.addCleanup(setattr, FakeGh, "author", "agent-anthropic-claude-code[bot]")
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        with self.assertRaisesRegex(ghx.GhError, "someone-personal"):
            self.collect()
        self.assertEqual(self.closes(), [])


class FetchTest(Base):
    def test_results_are_copied_to_the_results_dir(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect(post=False, env={})
        p = pathlib.Path(self.cfg.results_dir) / "demo-decree" / "abc123-c1.json"
        self.assertEqual(
            json.loads(p.read_text(encoding="utf-8"))["result"]["verdict"], "FAIL"
        )

    def test_posted_results_are_archived_before_deletion_and_orphans_expire(
        self,
    ):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        undecided = record()
        undecided["batch"] = "undecided"
        for run in undecided["runs"]:
            run["run_id"] = run["run_id"].replace("abc123", "undecided")
        self.save(undecided)
        old_orphan = "eph-result-orphan-c1"
        recent_orphan = "eph-result-orphan-c2"
        old_undecided = "eph-result-undecided-c1"
        recent_undecided = "eph-result-undecided-c2"
        for name, created in (
            (old_orphan, "2026-10-01T00:00:00Z"),
            (recent_orphan, "2026-11-15T00:00:00Z"),
            (old_undecided, "2026-10-01T00:00:00Z"),
            (recent_undecided, "2026-11-15T00:00:00Z"),
        ):
            self.c.put(
                "configmaps",
                "wow-ephemeral",
                name,
                {
                    "metadata": {
                        "creationTimestamp": created,
                        "labels": {"eph/verdict": "FAIL", "eph/decree": "demo-decree"},
                    },
                    "data": {
                        "result.json": json.dumps(
                            {"verdict": "FAIL", "decree_sha256": SHA}
                        )
                    },
                },
            )
        deleted = []

        def runner(argv, text=None):
            if "delete" in argv:
                name = argv[argv.index("delete") + 2]
                cm = self.c.objs[("configmaps", "wow-ephemeral", name)]
                rid = name.removeprefix("eph-result-")
                archive = (
                    pathlib.Path(self.cfg.results_dir) / "demo-decree" / f"{rid}.json"
                )
                self.assertEqual(
                    json.loads(archive.read_text(encoding="utf-8")),
                    {
                        "configmap": name,
                        "created": cm["metadata"]["creationTimestamp"],
                        "result": json.loads(cm["data"]["result.json"]),
                    },
                )
                deleted.append(name)
            return self.c(argv, text)

        self.k.runner = runner
        self.assertEqual(self.collect()["undecided"], "pending")
        self.assertCountEqual(
            deleted,
            [f"eph-result-{r['run_id']}" for r in self.rec["runs"]] + [old_orphan],
        )
        names = {
            o["metadata"]["name"]
            for o in self.c.of("configmaps", "wow-ephemeral")
            if o["metadata"]["name"].startswith("eph-result-")
        }
        self.assertEqual(names, {recent_orphan, old_undecided, recent_undecided})

    def test_unposted_results_expire_strictly_after_fourteen_days_only_if_decided(self):
        for decided in (False, True):
            with self.subTest(decided=decided):
                self.results(["PASS" if decided else "FAIL"] * 3, [None] * 3)
                for n, age in enumerate(
                    (14 * 86400 + 1, 14 * 86400, 14 * 86400 - 1), 1
                ):
                    cm = self.c.objs[
                        ("configmaps", "wow-ephemeral", f"eph-result-abc123-c{n}")
                    ]
                    cm["metadata"]["creationTimestamp"] = datetime.fromtimestamp(
                        1794787200.0 - age, timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                self.assertEqual(
                    self.collect(),
                    {"abc123": "non-discriminating" if decided else "pending"},
                )
                self.assertEqual(self.writes(), [])
                remaining = {
                    o["metadata"]["name"]
                    for o in self.c.of("configmaps", "wow-ephemeral")
                    if o["metadata"]["name"].startswith("eph-result-")
                }
                expected = {"eph-result-abc123-c2", "eph-result-abc123-c3"}
                if not decided:
                    expected.add("eph-result-abc123-c1")
                self.assertEqual(remaining, expected)

    def test_posted_batch_pruning_retries_on_next_collect_without_reposting(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.c.fail["delete"] = 1
        self.collect()
        self.assertTrue(any("prune skipped" in line for line in self.logs))
        calls = len(self.fg.calls)
        del self.c.fail["delete"]
        self.collect()
        self.assertEqual(len(self.fg.calls), calls)
        self.assertFalse(
            any(
                o["metadata"]["name"].startswith("eph-result-")
                for o in self.c.of("configmaps", "wow-ephemeral")
            )
        )

    def test_dry_run_keeps_old_results(self):
        self.c.now = "2026-10-01T00:00:00Z"
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect(post=False)
        self.assertFalse(any("delete" in argv for argv, _ in self.c.calls))

    def test_legacy_posted_decision_is_pruned_without_posting_again(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.c.fail["delete"] = 1
        self.collect()
        done = (
            pathlib.Path(self.cfg.results_dir) / "demo-decree" / "decision-abc123.json"
        )
        decision = json.loads(done.read_text(encoding="utf-8"))
        del decision["posted"]
        done.write_text(json.dumps(decision), encoding="utf-8")
        del self.c.fail["delete"]
        writes = self.writes()
        self.collect()
        self.assertEqual(self.writes(), writes)
        self.assertFalse(
            any(
                o["metadata"]["name"].startswith("eph-result-")
                for o in self.c.of("configmaps", "wow-ephemeral")
            )
        )

    def test_archive_failure_prevents_deletion(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        archive = pathlib.Path(self.cfg.results_dir) / "demo-decree" / "abc123-c1.json"
        archive.mkdir()
        with self.assertRaises(OSError):
            self.collect()
        self.assertFalse(any("delete" in argv for argv, _ in self.c.calls))


class ReviewFixesTest(Base):
    def test_a_strangers_marker_comment_does_not_suppress_the_apps_own(self):
        body = "\n".join(
            [f"<!-- eph:demo-decree:{SHA} -->"]
            + [f"| `{run['run_id']}` |" for run in self.rec["runs"]]
        )
        self.fg.comments[f"repos/{REPO}/issues/12/comments"] = [
            {"user": {"login": "someone-else"}, "body": body, "html_url": "u"}
        ]
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        mine = [
            c
            for c in self.fg.comments[f"repos/{REPO}/issues/12/comments"]
            if c["user"]["login"].endswith("[bot]")
        ]
        self.assertEqual(len(mine), 1)

    def test_a_later_reject_marker_beats_an_earlier_approve_whatever_the_order(self):
        self.main(approver=None)
        ok = f"<!-- fleet:review v1 verdict=APPROVE head={HEAD} -->"
        no = f"<!-- fleet:review v1 verdict=REQUEST_CHANGES head={HEAD} -->"
        self.fg.comments[f"repos/{MAIN}/issues/7/comments"] = [
            {"user": {"login": "luna[bot]"}, "body": no, "created_at": "2026-11-15T12:00:00Z", "id": 2},
            {"user": {"login": "luna[bot]"}, "body": ok, "created_at": "2026-11-15T11:00:00Z", "id": 1},
        ]  # fmt: skip
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])

    def test_comments_are_read_across_pages(self):
        pages = [[{"user": {"login": "a"}, "body": "x", "html_url": "p1"}],
                 [{"user": {"login": "agent-anthropic-claude-code[bot]"}, "html_url": "p2",
                   "body": "<!-- eph:demo-decree:" + SHA + " -->"}]]  # fmt: skip
        calls = []

        def runner(argv, text=None):
            calls.append(argv)
            return 0, json.dumps(pages), ""

        got = ghx.Gh(runner).comments(REPO, 12)
        self.assertEqual([c["html_url"] for c in got], ["p1", "p2"])
        self.assertIn("--paginate", calls[0])
        self.assertIn("--slurp", calls[0])


class LatestReviewDecidesTest(Base):
    def reviews(self, *rows):
        out = []
        for n, (who, state, at) in enumerate(rows):
            out.append({"id": n + 1, "state": state, "user": {"login": who},
                        "commit_id": HEAD, "submitted_at": at})  # fmt: skip
        self.fg.answers[("GET", f"repos/{MAIN}/pulls/7/reviews?per_page=100")] = out
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()

    def test_approve_then_request_changes_refuses(self):
        self.reviews(("luna[bot]", "APPROVED", "2026-11-15T10:00:00Z"),
                     ("luna[bot]", "CHANGES_REQUESTED", "2026-11-15T11:00:00Z"))  # fmt: skip
        self.assertEqual(self.closes(), [])

    def test_approve_then_dismissed_refuses(self):
        self.reviews(("luna[bot]", "APPROVED", "2026-11-15T10:00:00Z"),
                     ("luna[bot]", "DISMISSED", "2026-11-15T11:00:00Z"))  # fmt: skip
        self.assertEqual(self.closes(), [])

    def test_request_changes_then_approve_passes(self):
        self.reviews(("luna[bot]", "CHANGES_REQUESTED", "2026-11-15T10:00:00Z"),
                     ("luna[bot]", "APPROVED", "2026-11-15T11:00:00Z"))  # fmt: skip
        self.assertEqual(len(self.closes()), 1)

    def test_approve_then_comment_still_passes(self):
        self.reviews(("luna[bot]", "APPROVED", "2026-11-15T10:00:00Z"),
                     ("luna[bot]", "COMMENTED", "2026-11-15T11:00:00Z"))  # fmt: skip
        self.assertEqual(len(self.closes()), 1)

    def test_order_is_by_timestamp_not_list_position(self):
        self.reviews(("luna[bot]", "CHANGES_REQUESTED", "2026-11-15T11:00:00Z"),
                     ("luna[bot]", "APPROVED", "2026-11-15T10:00:00Z"))  # fmt: skip
        self.assertEqual(self.closes(), [])

    def test_another_reviewers_outstanding_request_blocks(self):
        self.reviews(("luna[bot]", "APPROVED", "2026-11-15T10:00:00Z"),
                     ("gemini[bot]", "CHANGES_REQUESTED", "2026-11-15T11:00:00Z"))  # fmt: skip
        self.assertEqual(self.closes(), [])

    def test_a_marker_after_a_formal_approval_decides_for_that_reviewer(self):
        self.main(approver=None)
        self.fg.answers[("GET", f"repos/{MAIN}/pulls/7/reviews?per_page=100")] = [
            {"id": 1, "state": "APPROVED", "user": {"login": "luna[bot]"},
             "commit_id": HEAD, "submitted_at": "2026-11-15T10:00:00Z"}]  # fmt: skip
        no = f"<!-- fleet:review v1 verdict=REQUEST_CHANGES head={HEAD} -->"
        self.fg.comments[f"repos/{MAIN}/issues/7/comments"] = [
            {"id": 5, "user": {"login": "luna[bot]"}, "body": no, "created_at": "2026-11-15T12:00:00Z"}]  # fmt: skip
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])

    def test_an_approval_of_an_older_commit_after_a_newer_one_does_not_count(self):
        self.main(approver=None)
        self.fg.answers[("GET", f"repos/{MAIN}/pulls/7/reviews?per_page=100")] = [
            {"id": 1, "state": "APPROVED", "user": {"login": "luna[bot]"},
             "commit_id": "z" * 40, "submitted_at": "2026-11-15T10:00:00Z"}]  # fmt: skip
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])


class SmallDecreeTest(Base):
    def test_a_one_run_decree_posts_evidence_and_never_closes(self):
        self.rec = record()
        self.rec["runs"] = [r for r in self.rec["runs"] if r["n"] == 1]
        self.rec["runs_wanted"] = {"control": 1, "treatment": 1}
        self.save(self.rec)
        self.results(["FAIL"], ["PASS"])
        self.assertEqual(self.collect(), {"abc123": "underpowered"})
        self.assertEqual(self.closes(), [])
        self.assertEqual(len(self.fg.comments[f"repos/{REPO}/issues/12/comments"]), 1)
        self.assertEqual(self.ledger()[0]["verdict"], "unclear")


if __name__ == "__main__":
    unittest.main()
