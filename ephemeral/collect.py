"""`eph collect`: copy results off the cluster, decide, post, and close only under the rule.

Order of work for each submitted batch with no finished decision:

1. copy every `eph-result-*` ConfigMap to `<results_dir>/<decree>/<run>.json`;
2. decide with `decide.decide` (control and treatment, validity, fix presence);
3. post, never from a pod: the issue comment is idempotent (hidden marker),
   boxes are ticked BEFORE a close, an epic is never closed, and a close needs
   all of: outcome `proven`, the decree on the default branch byte for byte,
   an approval of that decree's pull request by someone other than its author
   or this App, and no unticked box left in the issue body.

An unmerged decree posts to its own pull request when one is known, never to
the issue. A comment's author is read back and must be the configured App.
"""

import base64
import hashlib
import json
import pathlib
import time

from . import decide
from .ghx import require_identity
from .kube import KubeError

LABEL_WAITING = "awaiting-live-check"
LABEL_READY = "ready-for-agent"
APPROVE_MARK = "<!-- fleet:review v1 verdict="


class CollectError(Exception):
    """Collect cannot continue."""


def decree_status(gh, cfg, rec):
    """('merged-independent' | 'merged' | 'not-on-main', pr number or None, commit or '')."""
    repo, did = cfg.decree_repo, rec["decree_id"]
    path = f"decrees/{did}.yaml"
    doc = gh.api(f"repos/{repo}/contents/{path}?ref=main", missing_ok=True)
    if not doc or doc.get("encoding") != "base64":
        return "not-on-main", None, ""
    main_sha = hashlib.sha256(base64.b64decode(doc["content"])).hexdigest()
    if main_sha != rec["decree_sha256"]:
        return "not-on-main", None, ""
    commits = gh.api(f"repos/{repo}/commits?path={path}&sha=main&per_page=1") or []
    commit = commits[0]["sha"] if commits else ""
    prs = gh.api(f"repos/{repo}/commits/{commit}/pulls", missing_ok=True) or []
    pr = next((p for p in prs if p.get("merged_at")), None)
    if not pr:
        return "merged", None, commit
    return (
        ("merged-independent" if _independent(gh, cfg, repo, pr) else "merged"),
        pr["number"],
        commit,
    )


def _independent(gh, cfg, repo, pr):
    author, head = pr["user"]["login"], pr["head"]["sha"]
    n = pr["number"]
    other = lambda login: login not in (author, cfg.author_login)  # noqa: E731
    for r in gh.api(f"repos/{repo}/pulls/{n}/reviews?per_page=100") or []:
        if (
            r.get("state") == "APPROVED"
            and r.get("commit_id") == head
            and other(r["user"]["login"])
        ):
            return True
    verdict = None
    for c in gh.comments(repo, n):
        if not other(c["user"]["login"]):
            continue
        for line in (c.get("body") or "").splitlines():
            if line.startswith(APPROVE_MARK) and f"head={head}" in line:
                verdict = "verdict=APPROVE" in line
    return bool(verdict)


class Collector:
    def __init__(self, cfg, kube, gh, env=None, out=print, clock=time.time):
        self.cfg, self.kube, self.gh, self.out, self.clock = cfg, kube, gh, out, clock
        self.env = env if env is not None else {}

    # -- step 1: copy
    def fetch(self):
        got = {}
        for cm in self.kube.list("configmaps", selector="eph/verdict"):
            name = cm["metadata"]["name"]
            if not name.startswith("eph-result-"):
                continue
            rid = name[len("eph-result-") :]
            data = cm.get("data") or {}
            try:
                result = json.loads(data.get("result.json", ""))
            except ValueError:
                result = {"verdict": "INVALID", "reasons": ["result.json is not JSON"]}
            result.setdefault("verdict", data.get("verdict", "INVALID"))
            decree = cm["metadata"]["labels"].get("eph/decree", "") or "unknown"
            p = pathlib.Path(self.cfg.results_dir) / decree / f"{rid}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {"configmap": name, "created": cm["metadata"].get("creationTimestamp"), "result": result},
                    indent=2, sort_keys=True,
                ),
                encoding="utf-8",
            )  # fmt: skip
            got[rid] = result
        return got

    def prune(self):
        """Delete result ConfigMaps older than the keep window that are already copied."""
        limit = self.cfg.result_keep_days * 86400
        for cm in self.kube.list("configmaps", selector="eph/verdict"):
            name = cm["metadata"]["name"]
            rid = name[len("eph-result-") :]
            decree = cm["metadata"]["labels"].get("eph/decree", "") or "unknown"
            copy = pathlib.Path(self.cfg.results_dir) / decree / f"{rid}.json"
            created = cm["metadata"].get("creationTimestamp", "")
            try:
                age = self.clock() - _epoch(created)
            except ValueError:
                continue
            if name.startswith("eph-result-") and age > limit and copy.exists():
                self.kube.delete("configmaps", name)
                self.out(f"pruned {name}")

    # -- step 2 and 3
    def records(self):
        base = pathlib.Path(self.cfg.results_dir)
        return sorted(base.glob("*/batch-*.json")) if base.is_dir() else []

    def run(self, post=True):
        try:
            self.fetch()
        except KubeError as exc:
            raise CollectError(f"cannot read results: {exc}") from exc
        if post:
            require_identity(self.env)
        outcomes = {}
        for path in self.records():
            rec = json.loads(path.read_text(encoding="utf-8"))
            done = path.with_name(f"decision-{rec['batch']}.json")
            if done.exists():
                continue
            res = self._results(rec)
            d = decide.decide(rec, res)
            outcomes[rec["batch"]] = d["outcome"]
            self.out(
                f"{rec['decree_id']} batch {rec['batch']}: {d['outcome']} ({d['reason']})"
            )
            if d["outcome"] == "pending" or not post:
                continue
            notes = self._act(rec, d, res)
            done.write_text(
                json.dumps({"outcome": d["outcome"], "notes": notes}, indent=2),
                encoding="utf-8",
            )
        if post:
            try:
                self.prune()
            except KubeError as exc:
                self.out(f"prune skipped: {exc}")
        return outcomes

    def _results(self, rec):
        base = pathlib.Path(self.cfg.results_dir) / rec["decree_id"]
        out = {}
        for r in rec["runs"]:
            p = base / f"{r['run_id']}.json"
            if p.exists():
                out[r["run_id"]] = json.loads(p.read_text(encoding="utf-8"))["result"]
        return out

    def _act(self, rec, d, res):
        status, pr, commit = decree_status(self.gh, self.cfg, rec)
        notes = []
        outcome = d["outcome"]
        for entry in rec["proves"]:
            repo, issue = entry.get("repo"), entry.get("issue")
            body = decide.render_comment(
                rec, d, res, self.cfg.decree_repo, commit, entry
            )
            if status == "not-on-main":
                target = rec.get("decree_pr")
                if target and outcome != "pending":
                    self._comment_once(self.cfg.decree_repo, target, body, rec)
                notes.append(
                    f"{repo}#{issue}: decree not on the default branch; nothing posted to the issue"
                )
                self._ledger(
                    repo, issue, "unclear", f"{outcome}: decree not merged yet", ""
                )
                continue
            if not isinstance(issue, int):
                notes.append(f"{repo}: no issue number in the decree")
                continue
            notes.append(self._issue(rec, d, entry, body, status, outcome))
        return notes

    def _issue(self, rec, d, entry, body, status, outcome):
        repo, n = entry["repo"], entry["issue"]
        evidence = f"{outcome}: {d['reason']}"
        if outcome in ("non-discriminating", "unclear"):
            self._ledger(repo, n, "unclear", evidence, "")
            return f"{repo}#{n}: {outcome}, nothing posted"
        url = self._comment_once(repo, n, body, rec)
        if outcome == "pass-uncontrolled":
            self._ledger(
                repo, n, "unclear", "pass-uncontrolled: " + d["statistics"], url
            )
            return f"{repo}#{n}: pass-uncontrolled, evidence posted, left open"
        if outcome == "disproven":
            self.gh.remove_label(repo, n, LABEL_WAITING)
            if self.gh.label_exists(repo, LABEL_READY):
                self.gh.add_label(repo, n, LABEL_READY)
            self._ledger(repo, n, "disproven", evidence, url)
            return f"{repo}#{n}: disproven, left open"
        # proven
        closed, why = self._close(repo, n, entry, status)
        self._ledger(
            repo,
            n,
            "proven",
            evidence + ("" if closed else f" (not closed: {why})"),
            url,
        )
        return f"{repo}#{n}: proven, " + ("closed" if closed else f"left open ({why})")

    def _close(self, repo, n, entry, status):
        if status != "merged-independent":
            return False, "the decree was not merged through an independent approval"
        issue = self.gh.issue(repo, n)
        if issue.get("state") == "closed":
            return False, "already closed"
        if any(
            "epic" in (lb.get("name", "")).lower() for lb in issue.get("labels", [])
        ):
            return False, "an epic is never closed"
        body, _ = decide.tick_boxes(issue.get("body") or "", entry.get("criterion", ""))
        if decide.unticked(body):
            return False, "unticked boxes remain that this run does not prove"
        if body != (issue.get("body") or ""):
            self.gh.edit_body(repo, n, body)
        self.gh.remove_label(repo, n, LABEL_WAITING)
        self.gh.close_completed(repo, n)
        return True, ""

    def _comment_once(self, repo, n, body, rec):
        mark = decide.marker(rec["decree_id"], rec["decree_sha256"])
        for c in self.gh.comments(repo, n):
            if mark in (c.get("body") or ""):
                return c.get("html_url", "")
        return self.gh.comment(repo, n, body).get("html_url", "")

    def _ledger(self, repo, n, verdict, evidence, url):
        if not self.cfg.ledger_path:
            return
        line = {
            "repo": repo, "issue": n, "verdict": verdict,
            "evidence": evidence.replace("\n", " ")[:300], "scenario": "", "comment_url": url,
        }  # fmt: skip
        with open(self.cfg.ledger_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(line) + "\n")


def _epoch(text):
    from datetime import datetime, timezone

    return (
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
