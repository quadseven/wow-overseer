"""The realm roller's act side against fakes of the deploy repo and the cluster (#590).

`FakeGitHub` is a small in-memory git host: trees, blobs, commits, branches,
pull requests with squash merges, check runs, workflow runs and their logs.
`FakeKube` holds Deployments, pods, pod logs and the status ConfigMap. Every
write either fake receives is recorded, so a test can say "nothing was
written" as well as "this exact commit was".
"""

import copy
import difflib
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import realmroller_act as act  # noqa: E402
import realmroller_plan as plan  # noqa: E402

EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "realm_roller_example"
T0 = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)
ROLLER = "roller"
CUR = "r2026.10.04-1"
NEXT = "r2026.10.04-2"
OLD_OV, NEW_OV = "7" * 40, "8" * 40
OLD_WS, NEW_WS = "sha256:" + "c" * 64, "sha256:" + "e" * 64
DI = "sha256:" + "d" * 64


def _h(*parts) -> str:
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:40]


# --- the fake deploy repo ---------------------------------------------------------


class FakeGitHub:
    def __init__(self, files: dict, gitlinks: dict):
        self.blobs: dict[str, bytes] = {}
        self.snapshots: dict[
            str, dict
        ] = {}  # root tree id -> {path: (mode, type, sha)}
        self.commits: dict[str, dict] = {}
        self.refs: dict[str, str] = {}
        self.prs: dict[int, dict] = {}
        self.checks: dict[str, list] = {}
        self.default_checks = [
            {"name": "ci", "status": "completed", "conclusion": "success"}
        ]
        self.threads: dict[int, int] = {}
        self.runs: dict[int, dict] = {}
        self.logs: dict[int, str] = {}
        self.dispatched: list = []
        self.writes: list = []
        self.comments: list = []
        # The seed (and its digest lines) is a day old: the hourly gate is open.
        self.clock = T0 - timedelta(days=1)
        flat = {p: ("100644", "blob", self._blob(t.encode())) for p, t in files.items()}
        flat.update({p: ("160000", "commit", sha) for p, sha in gitlinks.items()})
        root = self._root(flat)
        self.refs["main"] = self._commit("seed", root, [])
        self.clock = T0

    # storage
    def _blob(self, data: bytes) -> str:
        sha = hashlib.sha256(b"blob" + data).hexdigest()[:40]
        self.blobs[sha] = data
        return sha

    def _root(self, flat: dict) -> str:
        rid = _h(sorted(flat.items()))
        self.snapshots[rid] = dict(flat)
        return rid

    def _commit(self, message, root, parents) -> str:
        sha = _h(message, root, parents, len(self.commits))
        self.commits[sha] = {
            "sha": sha,
            "message": message,
            "tree": {"sha": root},
            "parents": [{"sha": p} for p in parents],
            "date": self.clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return sha

    def flat(self, ref) -> dict:
        if ref is None:
            return {}
        sha = self.refs.get(ref, ref)
        return self.snapshots[self.commits[sha]["tree"]["sha"]]

    def text(self, ref: str, path: str) -> str:
        return self.blobs[self.flat(ref)[path][2]].decode()

    # the GitHub surface the roller uses
    def branch_sha(self, branch):
        return self.refs.get(branch)

    def commit(self, sha):
        return self.commits[sha]

    def tree(self, tid):
        root, _, prefix = tid.partition(":")
        flat = self.snapshots[root]
        out, seen = [], set()
        for path, (mode, typ, sha) in sorted(flat.items()):
            if prefix and not path.startswith(prefix + "/"):
                continue
            rest = path[len(prefix) + 1 :] if prefix else path
            head, _, more = rest.partition("/")
            if more:
                if head not in seen:
                    seen.add(head)
                    sub = "%s/%s" % (prefix, head) if prefix else head
                    out.append(
                        {
                            "path": head,
                            "mode": "040000",
                            "type": "tree",
                            "sha": "%s:%s" % (root, sub),
                        }
                    )
            else:
                out.append({"path": head, "mode": mode, "type": typ, "sha": sha})
        return out

    def blob(self, sha):
        return self.blobs[sha]

    def make_tree(self, base, entries):
        self.writes.append(("tree", entries))
        flat = dict(self.snapshots[base])
        for e in entries:
            if "content" in e:
                flat[e["path"]] = (e["mode"], "blob", self._blob(e["content"].encode()))
            elif e["sha"] is None:
                flat.pop(e["path"], None)
            else:
                flat[e["path"]] = (e["mode"], e["type"], e["sha"])
        return self._root(flat)

    def make_commit(self, message, tree, parents):
        self.writes.append(("commit", message))
        return self._commit(message, tree, parents)

    def set_branch(self, branch, sha):
        self.writes.append(("branch", branch))
        self.refs[branch] = sha

    def delete_branch(self, branch):
        self.writes.append(("delete", branch))
        self.refs.pop(branch, None)

    def pulls(self, state="open"):
        return [p for p in self.prs.values() if state == "all" or p["state"] == state]

    def pull(self, n):
        return copy.deepcopy(self.prs[n])

    def create_pull(self, title, head, base, body):
        self.writes.append(("pr", title))
        n = 100 + len(self.prs) + 1
        self.prs[n] = {
            "number": n,
            "title": title,
            "body": body,
            "head": {"ref": head, "sha": self.refs[head]},
            "base": {"ref": base},
            "state": "open",
            "merged": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "merge_commit_sha": None,
        }
        return self.prs[n]

    def add_pr(self, n, head_ref, files: dict):
        """A person's open PR branched from main, changing `files`."""
        base = self.refs["main"]
        tree = self.make_tree(
            self.commits[base]["tree"]["sha"],
            [
                {"path": p, "mode": "100644", "type": "blob", "content": t}
                for p, t in files.items()
            ],
        )
        self.refs[head_ref] = self._commit("config", tree, [base])
        self.prs[n] = {
            "number": n,
            "title": "config",
            "head": {"ref": head_ref, "sha": self.refs[head_ref]},
            "base": {"ref": "main"},
            "state": "open",
            "merged": False,
            "mergeable": True,
            "mergeable_state": "clean",
        }
        self.writes.clear()

    def pull_files(self, n):
        head = self.prs[n]["head"]["sha"]
        parent = self.commits[head]["parents"][0]["sha"]
        return [{"filename": p} for p in self._diff(parent, head)]

    def merge_base(self, base, head):
        return self.commits[head]["parents"][0]["sha"]

    def check_runs(self, sha):
        return self.checks.get(sha, self.default_checks)

    def statuses(self, sha):
        return []

    def open_threads(self, n):
        return self.threads.get(n, 0)

    def merge_pull(self, n, sha, title):
        pr = self.prs[n]
        assert pr["head"]["sha"] == sha, "merged a head the roller did not check"
        head = pr["head"]["sha"]
        parent = self.commits[head]["parents"][0]["sha"]
        flat = dict(self.flat("main"))
        for path in self._diff(parent, head):
            new = self.flat(head).get(path)
            if new is None:
                flat.pop(path, None)
            else:
                flat[path] = new
        merged = self._commit(title, self._root(flat), [self.refs["main"]])
        self.refs["main"] = merged
        pr.update(state="closed", merged=True, merge_commit_sha=merged)
        self.writes.append(("merge", n))
        return {"sha": merged}

    def comment(self, n, text):
        self.comments.append((n, text))

    def close_pull(self, n, text):
        self.writes.append(("close", n))
        self.comments.append((n, text))
        self.prs[n]["state"] = "closed"

    def dispatch(self, workflow, ref, inputs):
        self.writes.append(("dispatch", workflow))
        run = 9000 + len(self.dispatched)
        self.dispatched.append((workflow, ref, inputs, run))
        self.runs[run] = {"status": "in_progress", "conclusion": None}
        return run

    def run(self, run_id):
        return self.runs[run_id]

    def run_log(self, run_id):
        return self.logs[run_id]

    def _diff(self, a, b):
        fa, fb = self.flat(a), self.flat(b)
        return sorted(p for p in set(fa) | set(fb) if fa.get(p) != fb.get(p))

    def path_commits(self, path, branch, limit=20):
        out, sha = [], self.refs[branch]
        while sha and len(out) < limit:
            c = self.commits[sha]
            parent = c["parents"][0]["sha"] if c["parents"] else None
            before = self.flat(parent).get(path) if parent else None
            if self.flat(sha).get(path) != before:
                out.append({"sha": sha, "commit": {"committer": {"date": c["date"]}}})
            sha = parent
        return out

    def commit_detail(self, sha):
        c = self.commits[sha]
        parent = c["parents"][0]["sha"] if c["parents"] else None
        files = []
        for p in self._diff(parent, sha):
            old, new = self.flat(parent).get(p), self.flat(sha).get(p)

            def lines(e):
                return (
                    self.blobs[e[2]].decode().splitlines()
                    if e and e[1] == "blob"
                    else []
                )

            patch = "\n".join(
                ln
                for ln in difflib.unified_diff(lines(old), lines(new), lineterm="")
                if not ln.startswith("@@")
            )
            files.append({"filename": p, "patch": patch})
        return {
            "sha": sha,
            "parents": c["parents"],
            "files": files,
            "commit": {"committer": {"date": c["date"]}},
        }


# --- the fake cluster ---------------------------------------------------------------


class FakeKube:
    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.logs: dict[str, str] = {}
        self.writes: list = []
        self.created_at = "2026-10-05T03:00:00Z"

    def get(self, path):
        base, _, query = path.partition("?")
        if query:
            sel = urllib.parse.parse_qs(query)["labelSelector"][0]
            key, _, value = sel.partition("=")
            items = [
                o
                for p, o in self.objects.items()
                if p.startswith(base + "/")
                and o["metadata"].get("labels", {}).get(key) == value
            ]
            return {"items": items}
        return copy.deepcopy(self.objects.get(path))

    def create(self, path, body):
        self.writes.append(("create", body["metadata"]["name"]))
        obj = copy.deepcopy(body)
        obj["metadata"]["creationTimestamp"] = self.created_at
        obj["status"] = {"phase": "Pending"}
        self.objects["%s/%s" % (path, body["metadata"]["name"])] = obj
        return obj

    def delete(self, path):
        self.writes.append(("delete", path))
        self.objects.pop(path, None)

    def merge_patch(self, path, body):
        self.writes.append(("patch", path))
        obj = self.objects.setdefault(path, {"metadata": {}, "data": {}})
        obj.setdefault("data", {}).update(body["data"])
        return obj

    def log(self, path):
        base = path.partition("?")[0]
        return self.logs.get(base, "")


STATUS = "/api/v1/namespaces/dev-realm/configmaps/realm-roller-status"
DEPLOY = "/apis/apps/v1/namespaces/dev-realm/deployments/worldserver"
PODS = "/api/v1/namespaces/dev-realm/pods"


def _site(grug=0, zug=0, active=()):
    def fam(name, inside):
        return {
            "family": name,
            "members": [{"name": "m%d" % i, "instance": i < inside} for i in range(5)],
        }

    answers = {
        "http://site.example/api/family?family=Grug": fam("Grug", grug),
        "http://site.example/api/family?family=Zug": fam("Zug", zug),
        "http://site.example/api/guildruns": {"active": list(active), "recent": []},
    }
    return answers.get


def _deploy_files(overseer=OLD_OV):
    return {
        "build/pins.env": "CORE_SHA=%s\nPLAYERBOTS_SHA=%s\nOVERSEER_SHA=%s\nDUNGEON_CLEAR_SHA=%s\n"
        "OLLAMA_CHAT_SHA=%s\n" % ("1" * 40, "2" * 40, overseer, "4" * 40, "5" * 40),
        "overlay/kustomization.yaml": "images:\n"
        "  - name: registry.example/worldserver\n"
        "    # Build 102: by hand\n"
        "    # second line\n"
        "    digest: %s\n"
        "  - name: registry.example/db-import\n"
        "    digest: %s\n" % (OLD_WS, DI),
        "overlay/banner.yaml": 'env:\n  - name: PIN_OVERSEER\n    value: "%s"\n'
        % OLD_OV,
        "checks/drift.py": 'AHEAD = {"OVERSEER": {"live": "%s", "dev": "%s", "deployed_dev": "%s"}}\n'
        % ("0" * 40, OLD_OV, OLD_OV),
        "overlay/tests/test_banner.py": 'WANT = "%s"\n' % OLD_OV,
        "cfg/population.conf": "Bots = 500\n",
    }


def _roller_files(paused=False, queue_extra=()):
    ch = json.loads((EXAMPLE / "channel.json").read_text())
    ch["paused"] = paused
    ch["paused_reason"] = "" if not paused else "example pause"
    files = {"%s/channel.json" % ROLLER: plan.dumps(ch)}
    for p in sorted((EXAMPLE / "releases").glob("*.json")):
        files["%s/releases/%s" % (ROLLER, p.name)] = p.read_text()
    for raw in queue_extra:
        files["%s/releases/%s.json" % (ROLLER, raw["release"])] = plan.dumps(raw)
        ch["queue"].append(raw["release"])
        files["%s/channel.json" % ROLLER] = plan.dumps(ch)
    return files


class Harness(unittest.TestCase):
    """A deploy repo, a cluster and a site, with the roller pointed at them."""

    def setUp(self):
        self.now = T0

    def make(self, paused=False, overseer=OLD_OV, queue_extra=(), site=None):
        files = dict(_deploy_files(overseer))
        files.update(_roller_files(paused, queue_extra))
        self.gh = FakeGitHub(files, {"modules/mod-overseer": OLD_OV})
        # Hand-made rolls are long past, so the hourly gate is open.
        self.kube = FakeKube()
        # Everyone has been out for ten minutes, as the last tick saw it.
        out = json.dumps({"out_since": (T0 - timedelta(minutes=10)).isoformat()})
        self.kube.objects[STATUS] = {
            "metadata": {"name": "realm-roller-status"},
            "data": {"status.json": out},
        }
        self.store = act.StatusStore(self.kube, "dev-realm", "realm-roller-status")
        self.site = site or _site()
        self.gh.add_pr(
            104, "people/population", {"cfg/population.conf": "Bots = 1000\n"}
        )
        self.kube.writes.clear()
        return self

    def roller(self):
        return act.Roller(
            self.gh,
            self.kube,
            self.store,
            ROLLER,
            "http://site.example",
            "wow-overseer#590",
            clock=lambda: self.now,
            fetch=self.site,
        )

    def step(self, minutes=0):
        self.now += timedelta(minutes=minutes)
        self.gh.clock = self.now
        return self.roller().step()

    def status(self):
        text = self.kube.objects[STATUS]["data"].get("status.json")
        return json.loads(text) if text else {}

    def held(self, name):
        return self.status().get("releases", {}).get(name, {})


def _next_release(overseer="9" * 40):
    """A proposed release after NEXT: mod-overseer moves, one prove grep, one verify."""
    d = json.loads((EXAMPLE / "releases" / ("%s.json" % NEXT)).read_text())
    d["release"] = "r2026.10.05-1"
    d["sources"]["mod-overseer"] = overseer
    d["changes"] = [
        {
            "pr": "#105",
            "what": "a new log line",
            "prove": {"image": "worldserver", "grep": "new log line"},
            "verify": {"log": "worldserver", "grep": "new log line", "within": "30m"},
        }
    ]
    d["build"] = {"run": 0, "images": {}}
    d["state"] = "proposed"
    d["history"] = []
    return d


def _build_log(sources, ws, di):
    lines = ["clone %s" % sha[:12] for sha in sources.values()]
    for repo, digest in (
        ("registry.example/worldserver", ws),
        ("registry.example/db-import", di),
    ):
        lines += [
            "The push refers to repository [%s]" % repo,
            "core-111111111111-mod-222222222222: digest: %s size: 9" % digest,
            "#9 exporting manifest sha256:%s done" % ("f" * 64),
            "The push refers to repository [%s]" % repo,
            "latest: digest: %s size: 9" % digest,
        ]
    return "\n".join("2026-10-05T03:10:00.0000000Z %s" % ln for ln in lines)


class Paused(Harness):
    def test_a_paused_channel_writes_nothing_anywhere(self):
        self.make(paused=True, queue_extra=[_next_release()])
        notes = self.step()
        self.assertEqual(notes, ["paused: example pause; nothing acted"])
        self.assertEqual(self.gh.writes, [])
        self.assertEqual(self.gh.dispatched, [])
        self.assertEqual(self.kube.writes, [])

    def test_a_channel_without_the_flag_is_paused(self):
        self.make(queue_extra=[_next_release()])
        ch = json.loads(self.gh.text("main", "roller/channel.json"))
        del ch["paused"]
        self.gh.refs["main"] = self.gh.make_commit(
            "unflag",
            self.gh.make_tree(
                self.gh.commit(self.gh.refs["main"])["tree"]["sha"],
                [
                    {
                        "path": "roller/channel.json",
                        "mode": "100644",
                        "type": "blob",
                        "content": plan.dumps(ch),
                    }
                ],
            ),
            [self.gh.refs["main"]],
        )
        self.gh.writes.clear()
        self.assertIn("nothing acted", self.step()[0])
        self.assertEqual(self.gh.writes, [])


class BuildAndProve(Harness):
    def test_build_then_digests_then_prove(self):
        rel = _next_release()
        self.make(queue_extra=[rel])
        # 1. Dispatch from the release's SHAs.
        self.step()
        (workflow, ref, inputs, run) = self.gh.dispatched[0]
        self.assertEqual(
            (workflow, ref, inputs["release"]), ("build.yml", "main", "r2026.10.05-1")
        )
        self.assertIn("OVERSEER_SHA=" + "9" * 40, inputs["pins"].split())
        held = self.held("r2026.10.05-1")
        self.assertEqual((held["state"], held["build"]["run"]), ("building", run))
        # 2. Still running: nothing moves.
        self.step(5)
        self.assertEqual(self.held("r2026.10.05-1")["state"], "building")
        # 3. Done: both digests, each by its repository.
        self.gh.runs[run] = {"status": "completed", "conclusion": "success"}
        self.gh.logs[run] = _build_log(rel["sources"], NEW_WS, DI)
        self.step(5)
        held = self.held("r2026.10.05-1")
        self.assertEqual(held["state"], "built")
        self.assertEqual(held["build"]["images"]["worldserver"], NEW_WS)
        self.assertEqual(held["build"]["images"]["db-import"], DI)
        self.assertEqual(
            held["build"]["images"]["site"], "sha256:" + "f" * 64
        )  # carried
        # 4. Prove: a throwaway pod greps the binary.
        self.step(1)
        pod_path = (
            "/api/v1/namespaces/roller-prove/pods/prove-r2026-10-05-1-worldserver"
        )
        pod = self.kube.objects[pod_path]
        self.assertEqual(
            pod["spec"]["containers"][0]["image"],
            "registry.example/worldserver@" + NEW_WS,
        )
        self.assertEqual(self.held("r2026.10.05-1")["state"], "built")
        pod["status"]["phase"] = "Succeeded"
        self.kube.logs[pod_path + "/log"] = "count=3\n"
        self.step(1)
        self.assertEqual(self.held("r2026.10.05-1")["state"], "proven")
        self.assertNotIn(pod_path, self.kube.objects)  # cleaned up

    def test_a_build_whose_log_lacks_a_pin_failed(self):
        rel = _next_release()
        self.make(queue_extra=[rel])
        self.step()
        run = self.gh.dispatched[0][3]
        self.gh.runs[run] = {"status": "completed", "conclusion": "success"}
        old = dict(
            rel["sources"], **{"mod-overseer": OLD_OV}
        )  # the override did not take
        self.gh.logs[run] = _build_log(old, NEW_WS, DI)
        self.step(5)
        held = self.held("r2026.10.05-1")
        self.assertEqual(held["state"], "build_failed")
        self.assertIn("mod-overseer", held["history"][-1]["note"])

    def test_a_failed_run_is_build_failed(self):
        self.make(queue_extra=[_next_release()])
        self.step()
        self.gh.runs[self.gh.dispatched[0][3]] = {
            "status": "completed",
            "conclusion": "failure",
        }
        self.step(5)
        self.assertEqual(self.held("r2026.10.05-1")["state"], "build_failed")

    def test_a_grep_not_found_is_prove_failed(self):
        rel = _next_release()
        self.make(queue_extra=[rel])
        self.step()
        run = self.gh.dispatched[0][3]
        self.gh.runs[run] = {"status": "completed", "conclusion": "success"}
        self.gh.logs[run] = _build_log(rel["sources"], NEW_WS, DI)
        self.step(5)
        self.step(1)
        pod_path = (
            "/api/v1/namespaces/roller-prove/pods/prove-r2026-10-05-1-worldserver"
        )
        self.kube.objects[pod_path]["status"]["phase"] = "Failed"
        self.kube.logs[pod_path + "/log"] = "count=0\n"
        self.step(1)
        self.assertEqual(self.held("r2026.10.05-1")["state"], "prove_failed")

    def test_an_unreadable_binary_is_retried_not_passed(self):
        rel = _next_release()
        self.make(queue_extra=[rel])
        self.step()
        run = self.gh.dispatched[0][3]
        self.gh.runs[run] = {"status": "completed", "conclusion": "success"}
        self.gh.logs[run] = _build_log(rel["sources"], NEW_WS, DI)
        self.step(5)
        self.step(1)
        pod_path = (
            "/api/v1/namespaces/roller-prove/pods/prove-r2026-10-05-1-worldserver"
        )
        self.kube.objects[pod_path]["status"]["phase"] = "Succeeded"
        self.kube.logs[pod_path + "/log"] = "count=\n"
        self.step(1)
        self.assertEqual(self.held("r2026.10.05-1")["state"], "built")


class Roll(Harness):
    """The example's proven release rolls in ONE commit, inside the gates."""

    def setUp(self):
        super().setUp()
        self.make()
        self.main_before = self.gh.refs["main"]

    def open_roll(self):
        notes = self.step()
        prs = [
            p
            for p in self.gh.prs.values()
            if p["head"]["ref"] == "realm-roller/roll-%s" % NEXT
        ]
        self.assertEqual(len(prs), 1, notes)
        return prs[0]

    def test_the_roll_is_one_commit_with_every_moving_line(self):
        pr = self.open_roll()
        head = pr["head"]["sha"]
        self.assertEqual(self.gh.commits[head]["parents"], [{"sha": self.main_before}])
        t = self.gh.text
        self.assertIn("OVERSEER_SHA=%s\n" % NEW_OV, t(head, "build/pins.env"))
        self.assertIn("CORE_SHA=%s\n" % ("1" * 40), t(head, "build/pins.env"))
        self.assertEqual(
            self.gh.flat(head)["modules/mod-overseer"], ("160000", "commit", NEW_OV)
        )
        kust = t(head, "overlay/kustomization.yaml")
        self.assertIn(
            "    # Build 103: release %s, written by the realm roller.\n    digest: %s\n"
            % (NEXT, NEW_WS),
            kust,
        )
        self.assertNotIn("by hand", kust)
        self.assertIn("db-import\n    digest: %s" % DI, kust)
        self.assertIn('value: "%s"' % NEW_OV, t(head, "overlay/banner.yaml"))
        drift = t(head, "checks/drift.py")
        self.assertIn('"dev": "%s", "deployed_dev": "%s"' % (NEW_OV, NEW_OV), drift)
        self.assertIn('"live": "%s"' % ("0" * 40), drift)
        self.assertEqual(
            t(head, "overlay/tests/test_banner.py"), 'WANT = "%s"\n' % NEW_OV
        )
        # The queued config PR rides the same restart.
        self.assertEqual(t(head, "cfg/population.conf"), "Bots = 1000\n")
        chan = json.loads(t(head, "roller/channel.json"))
        self.assertEqual(
            (chan["current"], chan["previous"], chan["queue"]), (NEXT, CUR, [])
        )
        self.assertEqual(
            json.loads(t(head, "roller/releases/%s.json" % NEXT))["state"], "rolling"
        )
        # Nothing on main moved yet; the PR body passes the readiness shape.
        self.assertEqual(self.gh.refs["main"], self.main_before)
        self.assertIn("## Acceptance", pr["body"])

    def test_merges_when_checks_pass_and_closes_the_folded_pr(self):
        pr = self.open_roll()
        self.step(5)
        self.assertTrue(self.gh.prs[pr["number"]]["merged"])
        main = self.gh.refs["main"]
        self.assertIn("OVERSEER_SHA=%s" % NEW_OV, self.gh.text(main, "build/pins.env"))
        self.assertEqual(self.gh.prs[104]["state"], "closed")
        self.assertIn("Folded into #%d" % pr["number"], dict(self.gh.comments)[104])
        self.assertNotIn("realm-roller/roll-%s" % NEXT, self.gh.refs)
        self.assertEqual(self.status()["rolls"][NEXT]["pr"], pr["number"])

    def test_pending_checks_do_not_merge(self):
        pr = self.open_roll()
        self.gh.checks[pr["head"]["sha"]] = [
            {"name": "ci", "status": "in_progress", "conclusion": None}
        ]
        self.step(5)
        self.assertFalse(self.gh.prs[pr["number"]]["merged"])

    def test_an_open_review_thread_does_not_merge(self):
        pr = self.open_roll()
        self.gh.threads[pr["number"]] = 1
        self.step(5)
        self.assertFalse(self.gh.prs[pr["number"]]["merged"])

    def test_a_closed_gate_holds_a_ready_pr(self):
        pr = self.open_roll()
        self.site = _site(grug=2)
        notes = self.step(5)
        self.assertFalse(self.gh.prs[pr["number"]]["merged"])
        self.assertIn("in an instance", " ".join(notes))

    def test_failed_checks_close_the_roll_and_pause(self):
        pr = self.open_roll()
        self.gh.checks[pr["head"]["sha"]] = [
            {"name": "ci", "status": "completed", "conclusion": "failure"}
        ]
        self.step(5)
        self.assertEqual(self.gh.prs[pr["number"]]["state"], "closed")
        pause = [
            p
            for p in self.gh.prs.values()
            if p["head"]["ref"].startswith("realm-roller/pause-")
        ]
        self.assertEqual(len(pause), 1)
        chan = json.loads(self.gh.text(pause[0]["head"]["sha"], "roller/channel.json"))
        self.assertTrue(chan["paused"])
        self.assertIn("failing: ci", chan["paused_reason"])
        # The pause PR is driven first next tick, and merges.
        self.step(5)
        self.assertTrue(self.gh.prs[pause[0]["number"]]["merged"])
        self.assertIn("nothing acted", self.step(5)[0])


class RefusedRoll(Harness):
    def test_a_deploy_repo_not_at_current_pauses_instead_of_rolling(self):
        # Someone moved the overseer pin by hand: the old value is not there.
        self.make(overseer="6" * 40)
        self.step()
        refs = [
            p["head"]["ref"]
            for p in self.gh.prs.values()
            if p["head"]["ref"].startswith("realm-roller/")
        ]
        self.assertEqual(len(refs), 1)
        self.assertTrue(refs[0].startswith("realm-roller/pause-"))
        pr = [p for p in self.gh.prs.values() if p["head"]["ref"] == refs[0]][0]
        self.assertIn("matched 0 time", pr["body"])


def _deployment(digest, ready=True):
    return {
        "metadata": {"name": "worldserver", "generation": 4},
        "spec": {
            "replicas": 1,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "worldserver",
                            "image": "registry.example/worldserver@" + digest,
                        }
                    ]
                }
            },
        },
        "status": {
            "observedGeneration": 4,
            "updatedReplicas": 1,
            "availableReplicas": 1 if ready else 0,
            "unavailableReplicas": 0 if ready else 1,
        },
    }


def _pod(name, digest, restarts=0):
    return {
        "metadata": {"name": name, "labels": {"app": "worldserver"}},
        "spec": {
            "containers": [
                {
                    "name": "worldserver",
                    "image": "registry.example/worldserver@" + digest,
                }
            ]
        },
        "status": {
            "containerStatuses": [{"name": "worldserver", "restartCount": restarts}]
        },
    }


class OnTheRealm(Harness):
    """After the roll: Ready, verify on live logs, or revert and pause."""

    def setUp(self):
        super().setUp()
        self.make()
        self.before = self.gh.refs["main"]
        self.step()  # open the roll PR
        self.step(5)  # merge it
        self.rolled = self.gh.refs["main"]
        self.assertNotEqual(self.before, self.rolled)
        self.kube.objects[DEPLOY] = _deployment(OLD_WS)

    def live(self, log=""):
        self.kube.objects[DEPLOY] = _deployment(NEW_WS)
        self.kube.objects[PODS + "/ws-new"] = _pod("ws-new", NEW_WS)
        self.kube.logs[PODS + "/ws-new/log"] = log
        self.step(2)
        self.assertEqual(self.held(NEXT)["state"], "live")

    def test_the_old_image_still_running_is_not_ready(self):
        notes = self.step(2)
        self.assertIn("restarting", " ".join(notes))
        self.assertEqual(self.held(NEXT), {})

    def test_verified_after_the_window_with_clean_logs(self):
        self.live("boot\nworld ready\n")
        self.step(10)
        self.assertEqual(
            self.held(NEXT)["state"], "live"
        )  # the absent check's window is open
        self.step(25)
        self.assertEqual(self.held(NEXT)["state"], "verified")

    def test_a_seen_absent_text_reverts_the_roll_and_pauses(self):
        self.live("boot\n")
        self.kube.logs[PODS + "/ws-new/log"] = "boot\ncasting worldbuff on 40 bots\n"
        self.step(3)
        pr = [
            p
            for p in self.gh.prs.values()
            if p["head"]["ref"] == "realm-roller/rollback-%s" % NEXT
        ]
        self.assertEqual(len(pr), 1)
        head = pr[0]["head"]["sha"]
        # Every deploy line the roll moved is back; the channel is paused.
        for path in (
            "build/pins.env",
            "overlay/kustomization.yaml",
            "overlay/banner.yaml",
            "checks/drift.py",
            "overlay/tests/test_banner.py",
            "cfg/population.conf",
        ):
            self.assertEqual(
                self.gh.text(head, path), self.gh.text(self.before, path), path
            )
        self.assertEqual(
            self.gh.flat(head)["modules/mod-overseer"], ("160000", "commit", OLD_OV)
        )
        chan = json.loads(self.gh.text(head, "roller/channel.json"))
        self.assertEqual((chan["current"], chan["paused"]), (CUR, True))
        self.assertIn('seen absent "casting worldbuff"', chan["paused_reason"])
        rel = json.loads(self.gh.text(head, "roller/releases/%s.json" % NEXT))
        self.assertEqual(
            [e["to"] for e in rel["history"]][-3:], ["rolling", "live", "rolled_back"]
        )
        plan.parse_set(
            chan,
            {
                n[len("roller/releases/") : -5]: json.loads(self.gh.text(head, n))
                for n in self.gh.flat(head)
                if n.startswith("roller/releases/")
            },
        )
        # Next tick drives the rollback PR to a merge, ignoring the gates.
        self.site = _site(grug=3)
        self.step(1)
        self.assertTrue(self.gh.prs[pr[0]["number"]]["merged"])
        self.assertEqual(
            self.gh.text("main", "build/pins.env"),
            self.gh.text(self.before, "build/pins.env"),
        )

    def test_a_crash_loop_rolls_back(self):
        self.live("boot\n")
        self.kube.objects[PODS + "/ws-new"] = _pod("ws-new", NEW_WS, restarts=5)
        self.step(1)
        self.assertTrue(
            any(
                p["head"]["ref"].startswith("realm-roller/rollback-")
                for p in self.gh.prs.values()
            )
        )

    def test_a_revert_over_a_later_change_needs_a_person(self):
        self.live("boot\n")
        # A person edits a line the roll moved, after the roll.
        main = self.gh.refs["main"]
        tree = self.gh.make_tree(
            self.gh.commit(main)["tree"]["sha"],
            [
                {
                    "path": "overlay/banner.yaml",
                    "mode": "100644",
                    "type": "blob",
                    "content": "changed\n",
                }
            ],
        )
        self.gh.refs["main"] = self.gh.make_commit("hand edit", tree, [main])
        self.kube.logs[PODS + "/ws-new/log"] = "casting worldbuff\n"
        self.step(1)
        refs = [p["head"]["ref"] for p in self.gh.prs.values() if p["state"] == "open"]
        self.assertTrue(any(r.startswith("realm-roller/pause-") for r in refs), refs)
        self.assertFalse(any(r.startswith("realm-roller/rollback-") for r in refs))


# --- the adapters ---------------------------------------------------------------------


class Recorder:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, body=None, context=None, follow=True):
        self.calls.append((method, url, dict(headers), body, follow))
        return self.answers.pop(0)


def _resp(status, data=None, headers=None, raw=None):
    body = (
        raw
        if raw is not None
        else json.dumps(data).encode()
        if data is not None
        else b""
    )
    return act.Response(status, headers or {}, body)


class Adapters(unittest.TestCase):
    def gh(self, answers):
        rec = Recorder(answers)
        return act.GitHub("owner/deploy", lambda: "tok", http=rec), rec

    def test_pages_follow_the_link_header(self):
        gh, rec = self.gh(
            [
                _resp(
                    200,
                    [1, 2],
                    {"Link": '<https://api.github.com/x?page=2>; rel="next"'},
                ),
                _resp(200, [3]),
            ]
        )
        self.assertEqual(gh.pages("/pulls?state=open"), [1, 2, 3])
        self.assertEqual(rec.calls[1][1], "https://api.github.com/x?page=2")

    def test_the_job_log_redirect_is_fetched_without_the_token(self):
        gh, rec = self.gh(
            [
                _resp(200, {"jobs": [{"id": 7}]}),
                _resp(302, headers={"Location": "https://storage.example/log?sig=1"}),
                _resp(200, raw=b"the log"),
            ]
        )
        self.assertEqual(gh.run_log(5), "the log")
        self.assertFalse(rec.calls[1][4])  # not followed automatically
        self.assertNotIn("Authorization", rec.calls[2][2])

    def test_a_dispatch_without_a_run_id_is_an_error(self):
        gh, _ = self.gh([_resp(204)])
        with self.assertRaises(act.ApiError):
            gh.dispatch("build.yml", "main", {})
        gh, rec = self.gh([_resp(200, {"workflow_run_id": 42})])
        self.assertEqual(gh.dispatch("build.yml", "main", {"release": "r"}), 42)
        self.assertTrue(json.loads(rec.calls[0][3])["return_run_details"])

    def test_an_error_status_raises_with_the_url(self):
        gh, _ = self.gh([_resp(403, {"message": "nope"})])
        with self.assertRaisesRegex(act.ApiError, "403"):
            gh.pull(3)

    def test_transport_refuses_plain_http(self):
        with self.assertRaises(ValueError):
            act.transport("GET", "http://example.com/", {})

    def test_marker_time_reads_added_and_removed_lines(self):
        class G:
            def path_commits(self, path, branch, limit=20):
                return [{"sha": "b"}, {"sha": "a"}]

            def commit_detail(self, sha):
                patch = {
                    "b": "+# a comment\n-# old comment",
                    "a": "-    digest: sha256:1\n+    digest: sha256:2",
                }[sha]
                return {
                    "files": [{"filename": "o/k.yaml", "patch": patch}],
                    "commit": {
                        "committer": {
                            "date": "2026-10-04T10:00:00Z"
                            if sha == "a"
                            else "2026-10-04T12:00:00Z"
                        }
                    },
                }

        when = act.marker_time(G(), "main", "o/k.yaml", "digest: sha256:")
        self.assertEqual(when, datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc))


@unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
class AppTokenSigning(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.key = pathlib.Path(self.dir) / "key.pem"
        subprocess.run(
            ["openssl", "genrsa", "-out", str(self.key), "2048"],
            check=True,
            capture_output=True,
        )

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_the_jwt_verifies_and_the_token_is_scoped_to_one_repo(self):
        rec = Recorder(
            [_resp(201, {"token": "ghs_x", "expires_at": "2026-10-05T04:00:00Z"})]
        )
        tok = act.AppToken(
            "123",
            "456",
            str(self.key),
            "owner/deploy",
            http=rec,
            clock=lambda: 1_790_000_000,
        )
        self.assertEqual(tok(), "ghs_x")
        method, url, headers, body, _ = rec.calls[0]
        self.assertEqual(
            url, "https://api.github.com/app/installations/456/access_tokens"
        )
        sent = json.loads(body)
        self.assertEqual(sent["repositories"], ["deploy"])
        self.assertEqual(sent["permissions"]["contents"], "write")
        jwt = headers["Authorization"].split(" ", 1)[1]
        head, payload, sig = jwt.split(".")
        claims = json.loads(act.base64.urlsafe_b64decode(payload + "=="))
        self.assertEqual((claims["iss"], claims["exp"] - claims["iat"]), ("123", 600))
        pub = pathlib.Path(self.dir) / "pub.pem"
        subprocess.run(
            ["openssl", "rsa", "-in", str(self.key), "-pubout", "-out", str(pub)],
            check=True,
            capture_output=True,
        )
        sigfile = pathlib.Path(self.dir) / "sig"
        sigfile.write_bytes(act.base64.urlsafe_b64decode(sig + "=="))
        ok = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(pub),
                "-signature",
                str(sigfile),
            ],
            input=("%s.%s" % (head, payload)).encode(),
            capture_output=True,
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
        # Cached: a second call mints nothing.
        self.assertEqual(tok(), "ghs_x")
        self.assertEqual(len(rec.calls), 1)


if __name__ == "__main__":
    unittest.main()
