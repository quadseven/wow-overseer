"""eph collect: evidence posts, closes only under the rule, identity is checked."""

import base64
import hashlib
import json
import pathlib
import tempfile
import unittest

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

    def test_unticked_other_boxes_block_the_close(self):
        self.issue(
            body="- [ ] something else entirely\n- [ ] Live: the family leaves without a patron dying\n"
        )
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        self.collect()
        self.assertEqual(self.closes(), [])
        self.assertIn("unticked", self.ledger()[0]["evidence"])

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

    def test_old_copied_results_are_pruned_and_uncopied_are_kept(self):
        self.results(["FAIL"] * 3, ["PASS"] * 3)
        for rid in ("abc123-c1", "abc123-t1"):
            self.c.objs[("configmaps", "wow-ephemeral", f"eph-result-{rid}")][
                "metadata"
            ]["creationTimestamp"] = "2026-10-01T00:00:00Z"
        self.collect()
        names = {
            o["metadata"]["name"] for o in self.c.of("configmaps", "wow-ephemeral")
        }
        self.assertNotIn("eph-result-abc123-c1", names)
        self.assertIn("eph-result-abc123-c2", names)


class ReviewFixesTest(Base):
    def test_a_strangers_marker_comment_does_not_suppress_the_apps_own(self):
        mark = "<!-- eph:demo-decree:" + SHA + " -->"
        self.fg.comments[f"repos/{REPO}/issues/12/comments"] = [
            {"user": {"login": "someone-else"}, "body": mark, "html_url": "u"}]  # fmt: skip
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


if __name__ == "__main__":
    unittest.main()
