"""The realm roller's act side: the adapters and the one step a tick takes.

#590 phase 2. `Roller.step` reads the deploy repo's channel and release files
through the GitHub API, moves them on with the roller's status, reads the
gates and the realm, asks `realmroller.tick` for the one next step, and takes
it: dispatch a build, read its digests, prove the binary in a throwaway pod,
write and merge the ONE roll commit, watch the restart and the live logs,
and on a failure revert the roll commit and pause the channel.

EVERY STEP IS BEHIND THE CHANNEL'S PAUSE FLAG. A paused channel (the
default: a channel file that does not say `"paused": false`) makes `step`
report and return before any write: no dispatch, no pod, no branch, no PR,
no status write. Turning the roller on is a reviewed commit to that file.

STDLIB ONLY, so it runs in the overseer image: the GitHub and Kubernetes
APIs are plain HTTPS, and the app token is signed by the `openssl` binary
(the image's ca-certificates package depends on it). Nothing here shells out
to git or kubectl.

The adapters (`GitHub`, `Kube`, `StatusStore`) are thin; every decision is
in `realmroller` (the tick) and `realmroller_plan` (the commits, the
digests, the verdicts), which the tests drive with fakes of these adapters.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import realmroller as rr
import realmroller_plan as plan
import realmroller_world as world

log = logging.getLogger("realmroller")

_TIMEOUT = 30
_UA = "realm-roller"
# What the roller's installation token may do, asked for at mint time even
# though the app grants no more: contents and pull requests to write the roll
# commit and its PR, actions to dispatch the build and read its log, checks
# and statuses to read a PR's checks.
TOKEN_PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "actions": "write",
    "checks": "read",
    "statuses": "read",
}


class ApiError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, text: str):
        self.status = status
        super().__init__("%s %s answered %d: %s" % (method, url, status, text[:300]))


# --- HTTP ----------------------------------------------------------------------


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes

    def json(self):
        return json.loads(self.body.decode() or "null")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def transport(
    method: str,
    url: str,
    headers: dict,
    body: bytes | None = None,
    context: ssl.SSLContext | None = None,
    follow: bool = True,
) -> Response:
    """One HTTPS request. Any status comes back as a Response; only I/O raises."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("refusing a non-https URL: %s" % url)
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.HTTPSHandler(context=context)
    ]
    if not follow:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=_TIMEOUT) as resp:
            return Response(resp.status, dict(resp.headers), resp.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, dict(exc.headers or {}), exc.read() or b"")


# --- the GitHub App token ---------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class AppToken:
    """An installation token for one repository, minted from the app's private key.

    The key never leaves its file: `openssl dgst -sign` reads it there. The
    token is asked for ONE repository and `TOKEN_PERMISSIONS`, whatever the
    installation could grant, and is cached until five minutes before expiry.
    """

    def __init__(
        self,
        app_id: str,
        installation_id: str,
        key_path: str,
        repo: str,
        http=transport,
        run=subprocess.run,
        clock=time.time,
        api: str = "https://api.github.com",
    ):
        self.app_id = app_id.strip()
        self.installation_id = installation_id.strip()
        self.key_path = key_path
        self.repo_name = repo.split("/", 1)[1]
        self.http, self.run, self.clock, self.api = http, run, clock, api
        self._token, self._expires = None, 0.0

    def jwt(self) -> str:
        now = int(self.clock())
        head = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        body = _b64url(
            json.dumps({"iat": now - 60, "exp": now + 540, "iss": self.app_id}).encode()
        )
        signing_input = ("%s.%s" % (head, body)).encode()
        out = self.run(
            ["openssl", "dgst", "-sha256", "-sign", self.key_path],
            input=signing_input,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if out.returncode != 0 or not out.stdout:
            # stderr names the file and the failure, never key bytes.
            raise RuntimeError("openssl could not sign: %s" % out.stderr.decode()[:200])
        return "%s.%s" % (signing_input.decode(), _b64url(out.stdout))

    def __call__(self) -> str:
        if self._token and self.clock() < self._expires - 300:
            return self._token
        url = "%s/app/installations/%s/access_tokens" % (self.api, self.installation_id)
        body = json.dumps(
            {"repositories": [self.repo_name], "permissions": TOKEN_PERMISSIONS}
        ).encode()
        resp = self.http(
            "POST",
            url,
            {
                "Authorization": "Bearer %s" % self.jwt(),
                "Accept": "application/vnd.github+json",
                "User-Agent": _UA,
            },
            body,
        )
        if resp.status != 201:
            raise ApiError("POST", url, resp.status, resp.body.decode(errors="replace"))
        data = resp.json()
        self._token = data["token"]
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        self._expires = expires.timestamp()
        return self._token


# --- GitHub ------------------------------------------------------------------------


_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHub:
    """The deploy repo through the REST and GraphQL APIs. One repository only."""

    def __init__(self, repo: str, token, http=transport, api="https://api.github.com"):
        self.repo, self.token, self.http, self.api = repo, token, http, api
        self._trees: dict[str, list] = {}

    def _headers(self) -> dict:
        return {
            "Authorization": "Bearer %s" % self.token(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": _UA,
        }

    def call(
        self, method: str, path: str, body=None, ok=(200,), url: str | None = None
    ):
        url = url or "%s/repos/%s%s" % (self.api, self.repo, path)
        data = json.dumps(body).encode() if body is not None else None
        resp = self.http(method, url, self._headers(), data)
        if resp.status not in ok:
            raise ApiError(method, url, resp.status, resp.body.decode(errors="replace"))
        return resp

    def get(self, path: str):
        return self.call("GET", path).json()

    def pages(self, path: str, key: str | None = None) -> list:
        """Every item of a paginated list, following the Link header."""
        sep = "&" if "?" in path else "?"
        url = "%s/repos/%s%s%sper_page=100" % (self.api, self.repo, path, sep)
        items = []
        while url:
            resp = self.call("GET", "", url=url)
            data = resp.json()
            items.extend(data[key] if key else data)
            m = _NEXT_LINK.search(resp.headers.get("Link", "") or "")
            url = m.group(1) if m else None
        return items

    # git data
    def branch_sha(self, branch: str) -> str | None:
        resp = self.call("GET", "/git/ref/heads/%s" % branch, ok=(200, 404))
        return resp.json()["object"]["sha"] if resp.status == 200 else None

    def commit(self, sha: str) -> dict:
        return self.get("/git/commits/%s" % sha)

    def tree(self, sha: str) -> list:
        if sha not in self._trees:
            self._trees[sha] = self.get("/git/trees/%s" % sha)["tree"]
        return self._trees[sha]

    def blob(self, sha: str) -> bytes:
        data = self.get("/git/blobs/%s" % sha)
        return base64.b64decode(data["content"])

    def make_tree(self, base_tree: str, entries: list) -> str:
        return self.call(
            "POST", "/git/trees", {"base_tree": base_tree, "tree": entries}, ok=(201,)
        ).json()["sha"]

    def make_commit(self, message: str, tree: str, parents: list) -> str:
        return self.call(
            "POST",
            "/git/commits",
            {"message": message, "tree": tree, "parents": parents},
            ok=(201,),
        ).json()["sha"]

    def set_branch(self, branch: str, sha: str) -> None:
        if self.branch_sha(branch) is None:
            self.call(
                "POST",
                "/git/refs",
                {"ref": "refs/heads/%s" % branch, "sha": sha},
                ok=(201,),
            )
        else:
            self.call(
                "PATCH", "/git/refs/heads/%s" % branch, {"sha": sha, "force": True}
            )

    def delete_branch(self, branch: str) -> None:
        self.call("DELETE", "/git/refs/heads/%s" % branch, ok=(204, 404, 422))

    # pull requests
    def pulls(self, state: str = "open") -> list:
        return self.pages("/pulls?state=%s" % state)

    def pull(self, number: int) -> dict:
        return self.get("/pulls/%d" % number)

    def pull_files(self, number: int) -> list:
        return self.pages("/pulls/%d/files" % number)

    def merge_base(self, base: str, head: str) -> str:
        return self.get("/compare/%s...%s" % (base, head))["merge_base_commit"]["sha"]

    def check_runs(self, sha: str) -> list:
        return self.pages("/commits/%s/check-runs" % sha, key="check_runs")

    def statuses(self, sha: str) -> list:
        return self.get("/commits/%s/status" % sha).get("statuses", [])

    def open_threads(self, number: int) -> int:
        owner, name = self.repo.split("/", 1)
        query = (
            "query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){"
            "pullRequest(number:$p){reviewThreads(first:100){nodes{isResolved}}}}}"
        )
        resp = self.call(
            "POST",
            "",
            {"query": query, "variables": {"o": owner, "n": name, "p": number}},
            url="%s/graphql" % self.api,
        ).json()
        if resp.get("errors"):
            raise ApiError("POST", "graphql", 200, json.dumps(resp["errors"]))
        nodes = resp["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        return sum(1 for n in nodes if not n["isResolved"])

    def create_pull(self, title: str, head: str, base: str, body: str) -> dict:
        return self.call(
            "POST",
            "/pulls",
            {"title": title, "head": head, "base": base, "body": body},
            ok=(201,),
        ).json()

    def merge_pull(self, number: int, sha: str, title: str) -> dict:
        return self.call(
            "PUT",
            "/pulls/%d/merge" % number,
            {"merge_method": "squash", "sha": sha, "commit_title": title},
        ).json()

    def comment(self, number: int, text: str) -> None:
        self.call("POST", "/issues/%d/comments" % number, {"body": text}, ok=(201,))

    def close_pull(self, number: int, text: str) -> None:
        self.comment(number, text)
        self.call("PATCH", "/pulls/%d" % number, {"state": "closed"})

    # actions
    def dispatch(self, workflow: str, ref: str, inputs: dict) -> int:
        resp = self.call(
            "POST",
            "/actions/workflows/%s/dispatches" % workflow,
            {"ref": ref, "inputs": inputs, "return_run_details": True},
            ok=(200, 204),
        )
        data = resp.json() if resp.body else {}
        run_id = (data or {}).get("workflow_run_id")
        if not isinstance(run_id, int):
            # Without the run id there is no knowing which run is ours.
            raise ApiError(
                "POST", "dispatches", resp.status, "no workflow_run_id returned"
            )
        return run_id

    def run(self, run_id: int) -> dict:
        return self.get("/actions/runs/%d" % run_id)

    def run_log(self, run_id: int) -> str:
        """Every job's log text. The log URL redirects to storage, fetched without the token."""
        texts = []
        for job in self.pages("/actions/runs/%d/jobs" % run_id, key="jobs"):
            url = "%s/repos/%s/actions/jobs/%d/logs" % (self.api, self.repo, job["id"])
            resp = self.http("GET", url, self._headers(), None, follow=False)
            if resp.status in (301, 302, 303, 307, 308):
                where = resp.headers.get("Location") or resp.headers.get("location")
                resp = self.http("GET", where, {"User-Agent": _UA}, None)
            if resp.status != 200:
                raise ApiError(
                    "GET", url, resp.status, resp.body.decode(errors="replace")
                )
            texts.append(resp.body.decode(errors="replace"))
        return "\n".join(texts)

    # history
    def path_commits(self, path: str, branch: str, limit: int = 20) -> list:
        q = urllib.parse.urlencode({"sha": branch, "path": path, "per_page": limit})
        return self.get("/commits?%s" % q)

    def commit_detail(self, sha: str) -> dict:
        return self.get("/commits/%s" % sha)


def entry_at(gh: GitHub, commit_sha: str, path: str) -> dict | None:
    """The tree entry ({mode, type, sha}) at `path` in a commit, or None when absent."""
    tree = gh.commit(commit_sha)["tree"]["sha"]
    parts = path.strip("/").split("/")
    for i, part in enumerate(parts):
        found = next((e for e in gh.tree(tree) if e["path"] == part), None)
        if found is None:
            return None
        if i == len(parts) - 1:
            return found
        if found["type"] != "tree":
            return None
        tree = found["sha"]
    return None


def text_at(gh: GitHub, commit_sha: str, path: str) -> str | None:
    e = entry_at(gh, commit_sha, path)
    if e is None or e["type"] != "blob":
        return None
    return gh.blob(e["sha"]).decode()


def read_roller(gh: GitHub, sha: str, roller_path: str) -> tuple[dict, dict[str, dict]]:
    """channel.json and releases/*.json under `roller_path` at commit `sha`."""
    channel_text = text_at(gh, sha, "%s/channel.json" % roller_path)
    if channel_text is None:
        raise rr.Invalid(roller_path, ["no channel.json"])
    rel_dir = entry_at(gh, sha, "%s/releases" % roller_path)
    raws = {}
    for e in gh.tree(rel_dir["sha"]) if rel_dir else []:
        if e["type"] == "blob" and e["path"].endswith(".json"):
            raws[e["path"][: -len(".json")]] = json.loads(gh.blob(e["sha"]).decode())
    return json.loads(channel_text), raws


def marker_time(gh: GitHub, branch: str, path: str, pattern: str) -> datetime | None:
    """`git log -1 -G pattern -- path`, through the API: the last commit whose diff
    adds or removes a line of `path` matching `pattern`."""
    rx = re.compile(pattern)
    for c in gh.path_commits(path, branch):
        detail = gh.commit_detail(c["sha"])
        for f in detail.get("files", []):
            if f.get("filename") != path:
                continue
            for line in (f.get("patch") or "").splitlines():
                if line[:1] in "+-" and not line.startswith(("+++", "---")):
                    if rx.search(line[1:]):
                        return rr.instant(
                            detail["commit"]["committer"]["date"].replace("Z", "+00:00")
                        )
    return None


# --- Kubernetes --------------------------------------------------------------------


class Kube:
    """The cluster API from inside a pod, with the pod's service account."""

    SA = "/var/run/secrets/kubernetes.io/serviceaccount"

    def __init__(
        self, server: str, token_path: str, ca_path: str | None, http=transport
    ):
        self.server, self.token_path, self.http = server.rstrip("/"), token_path, http
        self.context = ssl.create_default_context(cafile=ca_path) if ca_path else None

    @classmethod
    def in_cluster(cls) -> Kube:
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        return cls(
            "https://%s:%s" % (host, port), cls.SA + "/token", cls.SA + "/ca.crt"
        )

    def _call(self, method, path, body=None, ok=(200,), ctype="application/json"):
        with open(self.token_path) as fh:
            token = fh.read().strip()
        headers = {"Authorization": "Bearer %s" % token, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = ctype
            data = json.dumps(body).encode()
        url = self.server + path
        resp = self.http(method, url, headers, data, context=self.context)
        if resp.status not in ok:
            raise ApiError(
                method, path, resp.status, resp.body.decode(errors="replace")
            )
        return resp

    def get(self, path: str) -> dict | None:
        resp = self._call("GET", path, ok=(200, 404))
        return resp.json() if resp.status == 200 else None

    def create(self, path: str, body: dict) -> dict:
        return self._call("POST", path, body, ok=(201, 200)).json()

    def delete(self, path: str) -> None:
        self._call("DELETE", path, ok=(200, 202, 404))

    def merge_patch(self, path: str, body: dict) -> dict:
        return self._call(
            "PATCH", path, body, ctype="application/merge-patch+json"
        ).json()

    def log(self, path: str) -> str:
        return self._call("GET", path).body.decode(errors="replace")


class StatusStore:
    """The roller's status between ticks, in one ConfigMap key. A missing key is empty."""

    KEY = "status.json"

    def __init__(self, kube: Kube, namespace: str, name: str):
        self.kube = kube
        self.path = "/api/v1/namespaces/%s/configmaps/%s" % (namespace, name)

    def load(self) -> dict:
        cm = self.kube.get(self.path)
        if cm is None:
            raise RuntimeError("status ConfigMap %s is missing" % self.path)
        text = (cm.get("data") or {}).get(self.KEY)
        return json.loads(text) if text else {}

    def save(self, status: dict) -> None:
        self.kube.merge_patch(
            self.path,
            {"data": {self.KEY: json.dumps(status, indent=1, sort_keys=True)}},
        )


# --- the step ---------------------------------------------------------------------


@dataclass
class Context:
    channel_raw: dict
    raws: dict[str, dict]
    channel: rr.Channel
    releases: dict[str, rr.Release]
    act: plan.Act
    base_sha: str
    status: dict
    notes: list[str] = field(default_factory=list)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


class Roller:
    """One tick of the roller against the deploy repo, the cluster and the site."""

    def __init__(
        self,
        gh: GitHub,
        kube: Kube,
        store: StatusStore,
        roller_path: str,
        site_url: str,
        tracker: str,
        base: str = "main",
        clock=lambda: datetime.now(timezone.utc),
        fetch=world.fetch_json,
    ):
        self.gh, self.kube, self.store, self.base = gh, kube, store, base
        self.roller_path = roller_path.strip("/")
        self.site_url, self.tracker = site_url, tracker
        self.clock, self.fetch = clock, fetch

    # The branch names the roller writes, one per purpose.
    def _branch(self, ctx: Context, kind: str, name: str) -> str:
        return "%s%s-%s" % (ctx.act.branch_prefix, kind, name)

    def step(self) -> list[str]:
        """Take the one next step. Returns what it did, a line per fact."""
        now = self.clock()
        channel_raw, main_raws, base_sha, act_base = self._read_main()
        channel = rr.parse_channel(channel_raw)
        if channel.paused:
            return [
                "paused: %s; nothing acted"
                % (channel.paused_reason or "no reason given")
            ]
        act = plan.parse_act(channel_raw.get("act"), channel)
        if act.base != act_base:
            raise rr.Invalid("act", ["base %s was not the branch read" % act.base])
        status = self.store.load()
        raws, dropped = plan.overlay(main_raws, status.get("releases", {}))
        held = {k: v for k, v in status.get("releases", {}).items() if k not in dropped}
        status["releases"] = held
        channel, releases = plan.parse_set(channel_raw, raws)
        plan.check_logs(act, releases)
        ctx = Context(channel_raw, raws, channel, releases, act, base_sha, status)
        if dropped:
            ctx.notes.append(
                "deploy repo moved on; dropped status for %s" % ", ".join(dropped)
            )

        if self._finish_inflight(ctx):
            self.store.save(status)
            return ctx.notes
        w = self._observe(ctx, now)
        action = rr.tick(channel, releases, w)
        ctx.notes.append(
            "tick: %s%s: %s"
            % (
                action.kind,
                " %s" % action.release if action.release else "",
                action.why,
            )
        )
        handler = getattr(self, "_do_%s" % action.kind)
        handler(ctx, action, now)
        self.store.save(status)
        return ctx.notes

    def _read_main(self):
        # The base branch name lives in the channel file, so the first read
        # takes the branch the CLI names and the step checks they agree.
        sha = self.gh.branch_sha(self.base)
        if sha is None:
            raise RuntimeError("deploy repo has no branch %s" % self.base)
        channel_raw, raws = read_roller(self.gh, sha, self.roller_path)
        return channel_raw, raws, sha, self.base

    # -- in-flight rollback and pause PRs come first ---------------------------

    def _finish_inflight(self, ctx: Context) -> bool:
        """Drive an open rollback or pause PR. True when one exists (nothing else runs)."""
        prefix = ctx.act.branch_prefix
        mine = [
            p
            for p in self.gh.pulls("open")
            if p["head"]["ref"].startswith((prefix + "rollback-", prefix + "pause-"))
        ]
        if not mine:
            return False
        for pr in mine:
            self._drive(ctx, pr, threads_block=False)
        return True

    def _drive(self, ctx: Context, pr_stub: dict, threads_block: bool) -> plan.Verdict:
        """Merge a roller PR once its checks pass; report otherwise."""
        pr = self.gh.pull(pr_stub["number"])
        sha = pr["head"]["sha"]
        threads = self.gh.open_threads(pr["number"]) if threads_block else 0
        v = plan.pr_verdict(
            pr,
            self.gh.check_runs(sha),
            self.gh.statuses(sha),
            threads,
            ctx.act.required_checks,
            threads_block=threads_block,
        )
        ctx.notes.append("PR #%d: %s (%s)" % (pr["number"], v.kind, v.why))
        if v.kind == "ready":
            self.gh.merge_pull(pr["number"], sha, pr["title"])
            merged = self.gh.pull(pr["number"])
            if not merged.get("merged"):
                ctx.notes.append("PR #%d did not merge" % pr["number"])
                return plan.Verdict("pending", "merge did not land")
            self.gh.delete_branch(pr["head"]["ref"])
            ctx.notes.append(
                "merged PR #%d as %s" % (pr["number"], merged["merge_commit_sha"])
            )
            return plan.Verdict("merged", merged["merge_commit_sha"])
        if v.kind == "failed" and not threads_block:
            ctx.notes.append("PR #%d needs a person: %s" % (pr["number"], v.why))
        return v

    # -- what the tick reads -------------------------------------------------------

    def _observe(self, ctx: Context, now: datetime) -> rr.World:
        p = ctx.channel.policy
        family = world.family_in_instance(self.site_url, p.families, self.fetch)
        guild = world.guild_groups_inside(self.site_url, p.guild_run_states, self.fetch)
        inside = None if family is None or guild is None else family + guild
        prev = ctx.status.get("out_since")
        out_since = world.carry_out_since(
            rr.instant(prev) if prev else None, inside, now
        )
        ctx.status["out_since"] = _iso(out_since) if out_since else None
        marker = marker_time(
            self.gh, ctx.act.base, p.roll_marker_path, p.roll_marker_pattern
        )
        w = rr.World(
            now=now,
            family_in_instance=family,
            guild_groups_inside=guild,
            out_since=out_since,
            last_roll_started=rr.last_roll_start(ctx.releases, marker),
        )
        cur = ctx.releases[ctx.channel.current]
        if cur.state in rr.ON_REALM:
            w = self._observe_realm(ctx, cur, w)
        return w

    def _parts(self, ctx: Context, rel: rr.Release) -> tuple[rr.Component, ...]:
        """The components a release on the realm restarted, against the rollback target."""
        prev = ctx.releases[ctx.channel.previous]
        return rr.touched(ctx.channel, rel, prev) or ctx.channel.components

    def _observe_realm(self, ctx: Context, rel: rr.Release, w: rr.World) -> rr.World:
        ready, restarts = True, 0
        for comp in self._parts(ctx, rel):
            spec = ctx.act.watch[comp.name]
            r, n = self._readiness(spec, rel.images.get(spec.image, "?"))
            ready, restarts = ready and r, restarts + n
        seen, bad = self._scan_logs(ctx, rel)
        rolls = ctx.status.setdefault("rolls", {}).get(rel.name, {})
        rolled_at = rolls.get("merged_at")
        return rr.World(
            now=w.now,
            family_in_instance=w.family_in_instance,
            guild_groups_inside=w.guild_groups_inside,
            out_since=w.out_since,
            last_roll_started=w.last_roll_started,
            ready=ready,
            restarts=restarts,
            bad_signature=bad,
            seen={label: True for label in seen},
            rolled_at=rr.instant(rolled_at) if rolled_at else self._rolled_at(ctx, rel),
        )

    def _rolled_at(self, ctx: Context, rel: rr.Release) -> datetime | None:
        """When the commit that put `rel` on the realm landed: the last commit to its file."""
        path = "%s/releases/%s.json" % (self.roller_path, rel.name)
        commits = self.gh.path_commits(path, ctx.act.base, limit=1)
        if not commits:
            return None
        return rr.instant(
            commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00")
        )

    def _pods(self, namespace: str, selector: str) -> list:
        q = urllib.parse.urlencode({"labelSelector": selector})
        data = self.kube.get("/api/v1/namespaces/%s/pods?%s" % (namespace, q))
        return (data or {}).get("items", [])

    @staticmethod
    def _runs(pod: dict, container: str, digest: str) -> bool:
        """Whether `container` in `pod` runs the image with `digest`."""
        for c in pod.get("spec", {}).get("containers", []) + pod.get("spec", {}).get(
            "initContainers", []
        ):
            if c.get("name") == container and digest in c.get("image", ""):
                return True
        return False

    def _readiness(self, spec: plan.Watch, digest: str) -> tuple[bool, int]:
        """(the Deployment runs `digest` and finished rolling out, its pods' restarts)."""
        dep = self.kube.get(
            "/apis/apps/v1/namespaces/%s/deployments/%s"
            % (spec.namespace, spec.deployment)
        )
        if dep is None:
            return False, 0
        containers = dep["spec"]["template"]["spec"].get("containers", [])
        image = next(
            (c["image"] for c in containers if c["name"] == spec.container), ""
        )
        st, want = dep.get("status", {}), dep["spec"].get("replicas", 1)
        ready = (
            digest in image
            and st.get("observedGeneration", 0) >= dep["metadata"].get("generation", 0)
            and st.get("updatedReplicas", 0) == want
            and st.get("availableReplicas", 0) == want
            and not st.get("unavailableReplicas")
        )
        restarts = 0
        for pod in self._pods(spec.namespace, spec.selector):
            if not self._runs(pod, spec.container, digest):
                continue
            for cs in pod.get("status", {}).get("containerStatuses", []):
                if cs.get("name") == spec.container:
                    restarts += cs.get("restartCount", 0)
        return ready, restarts

    def _scan_logs(self, ctx: Context, rel: rr.Release) -> tuple[set[str], str | None]:
        """Every verify text seen and the first fatal signature, from the new pods' logs.

        Read incrementally: each pod's log from where the last tick stopped
        (with a few seconds' overlap), and what was seen is kept in the status,
        so an hour-long window does not mean rereading an hour of log.
        """
        scan = ctx.status.setdefault("scan", {}).setdefault(
            rel.name, {"pods": {}, "seen": [], "bad": None}
        )
        checks = [c.verify for c in rel.changes if c.verify]
        names = {c.verify.log for c in rel.changes if c.verify}
        for comp in self._parts(ctx, rel):
            names.add(comp.name)
            names.update(comp.images)
        seen = set(scan["seen"])
        bad = scan.get("bad")
        for name in sorted(n for n in names if n in ctx.act.logs):
            src = ctx.act.logs[name]
            mine = [c for c in checks if c.log == name]
            digests = [
                rel.images[i]
                for comp in self._parts(ctx, rel)
                for i in comp.images
                if i in rel.images
            ]
            for pod in self._pods(src.namespace, src.selector):
                if not any(self._runs(pod, src.container, d) for d in digests):
                    continue
                pname = pod["metadata"]["name"]
                key = "%s/%s/%s" % (src.namespace, pname, src.container)
                q = {"container": src.container, "timestamps": "false"}
                since = scan["pods"].get(key)
                if since:
                    q["sinceTime"] = since
                started = self.clock()
                text = self.kube.log(
                    "/api/v1/namespaces/%s/pods/%s/log?%s"
                    % (src.namespace, pname, urllib.parse.urlencode(q))
                )
                found, sig = plan.scan(
                    text.splitlines(), mine, ctx.channel.policy.rollback.log_signatures
                )
                seen |= found
                bad = bad or sig
                scan["pods"][key] = (started - timedelta(seconds=5)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
        scan["seen"], scan["bad"] = sorted(seen), bad
        return seen, bad

    # -- the actions -----------------------------------------------------------------

    def _hold(self, ctx: Context, name: str, raw: dict) -> None:
        ctx.status.setdefault("releases", {})[name] = raw
        ctx.raws[name] = raw

    def _do_wait(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        return None

    def _build_for(
        self, ctx: Context, rel: rr.Release
    ) -> tuple[str, plan.Build] | None:
        cur = ctx.releases[ctx.channel.current]
        parts = rr.touched(ctx.channel, rel, cur)
        recipes = [(c.name, ctx.act.builds.get(c.name)) for c in parts]
        missing = [n for n, b in recipes if b is None]
        if not parts or missing or len(recipes) != 1:
            ctx.notes.append(
                "cannot build %s: touches %s; one built component per release, "
                "and act.builds must name it"
                % (rel.name, ", ".join(c.name for c in parts) or "nothing")
            )
            return None
        name, build = recipes[0]
        assert build is not None  # `missing` is empty
        return name, build

    def _do_build(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        rel = ctx.releases[_named(action)]
        found = self._build_for(ctx, rel)
        if found is None:
            return
        comp, build = found
        run_id = self.gh.dispatch(
            build.workflow, build.ref, plan.build_inputs(build, rel)
        )
        raw = plan.advance(
            ctx.raws[rel.name],
            "building",
            now,
            "build run %d dispatched" % run_id,
            run=run_id,
        )
        self._hold(ctx, rel.name, raw)
        ctx.notes.append(
            "dispatched %s for %s: run %d" % (build.workflow, rel.name, run_id)
        )

    def _do_watch_build(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        rel = ctx.releases[_named(action)]
        found = self._build_for(ctx, rel)
        if found is None:
            return
        comp, build = found
        run = self.gh.run(rel.run)
        if run.get("status") != "completed":
            ctx.notes.append("build run %d: %s" % (rel.run, run.get("status")))
            return
        raw = ctx.raws[rel.name]
        if run.get("conclusion") != "success":
            why = "build run %d concluded %s" % (rel.run, run.get("conclusion"))
            self._hold(ctx, rel.name, plan.advance(raw, "build_failed", now, why))
            ctx.notes.append(why)
            return
        text = self.gh.run_log(rel.run)
        lacks = plan.build_log_lacks(text, build, rel)
        try:
            if lacks:
                raise plan.PairingError(
                    "the log never names %s at its SHA" % ", ".join(lacks)
                )
            digests = plan.read_digests(text, build)
        except plan.PairingError as exc:
            why = "build run %d unusable: %s" % (rel.run, exc)
            self._hold(ctx, rel.name, plan.advance(raw, "build_failed", now, why))
            ctx.notes.append(why)
            return
        # Images of components this release does not touch carry over from the
        # current release, so the next roll's edits have every old value.
        cur = ctx.releases[ctx.channel.current]
        images = {k: v for k, v in cur.images.items() if k not in digests}
        images.update(digests)
        note = "digests read from run %d: %s" % (
            rel.run,
            ", ".join("%s %s" % (k, v[7:19]) for k, v in sorted(digests.items())),
        )
        self._hold(ctx, rel.name, plan.advance(raw, "built", now, note, images=images))
        ctx.notes.append(note)

    def _do_prove(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        rel = ctx.releases[_named(action)]
        greps = plan.prove_greps(rel)
        raw = ctx.raws[rel.name]
        if not greps:
            self._hold(
                ctx, rel.name, plan.advance(raw, "proven", now, "no prove greps")
            )
            return
        found = self._build_for(ctx, rel)
        if found is None:
            return
        comp, build = found
        results = ctx.status.setdefault("prove", {}).setdefault(rel.name, {})
        ns = ctx.act.prove_namespace
        for image in sorted(greps):
            if image in results:
                continue
            if image not in ctx.act.binaries or image not in build.image_repos:
                ctx.notes.append("cannot prove %s: act names no binary or repo" % image)
                return
            pod = plan.prove_pod(ctx.act, rel, image, build.image_repos[image])
            name = pod["metadata"]["name"]
            path = "/api/v1/namespaces/%s/pods/%s" % (ns, name)
            live = self.kube.get(path)
            if live is None:
                self.kube.create("/api/v1/namespaces/%s/pods" % ns, pod)
                ctx.notes.append("prove pod %s started" % name)
                continue
            phase = live.get("status", {}).get("phase")
            if phase in ("Succeeded", "Failed"):
                counts = plan.prove_counts(
                    self.kube.log(path + "/log"), len(greps[image])
                )
                self.kube.delete(path)
                if counts is None:
                    ctx.notes.append("prove pod %s inconclusive; retrying" % name)
                    continue
                results[image] = counts
                continue
            created = rr.instant(
                live["metadata"]["creationTimestamp"].replace("Z", "+00:00")
            )
            if now - created > ctx.act.prove_within:
                self.kube.delete(path)
                ctx.notes.append(
                    "prove pod %s took too long (%s); retrying" % (name, phase)
                )
            else:
                ctx.notes.append("prove pod %s: %s" % (name, phase))
        if not all(i in results for i in greps):
            return
        missing = [
            '"%s" in %s' % (g, i)
            for i in sorted(greps)
            for g, n in zip(greps[i], results[i])
            if n < 1
        ]
        total = sum(len(g) for g in greps.values())
        if missing:
            why = "prove grep not found: %s" % ", ".join(missing)
            self._hold(ctx, rel.name, plan.advance(raw, "prove_failed", now, why))
        else:
            why = "%d of %d prove grep(s) found" % (total, total)
            self._hold(ctx, rel.name, plan.advance(raw, "proven", now, why))
        ctx.status["prove"].pop(rel.name, None)
        ctx.notes.append("%s: %s" % (rel.name, why))

    def _do_mark_live(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        raw = plan.advance(ctx.raws[_named(action)], "live", now, action.why)
        self._hold(ctx, _named(action), raw)

    def _do_mark_verified(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        raw = plan.advance(ctx.raws[_named(action)], "verified", now, action.why)
        self._hold(ctx, _named(action), raw)

    # -- the roll ------------------------------------------------------------------

    def _do_roll(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        head = _named(action)
        branch = self._branch(ctx, "roll", head)
        rolls = ctx.status.setdefault("rolls", {})
        open_rolls = [
            p
            for p in self.gh.pulls("open")
            if p["head"]["ref"].startswith(ctx.act.branch_prefix + "roll-")
        ]
        for pr in open_rolls:
            if pr["head"]["ref"] != branch:
                self.gh.close_pull(
                    pr["number"], "Superseded: the roller now rolls %s." % head
                )
                self.gh.delete_branch(pr["head"]["ref"])
                ctx.notes.append("closed stale roll PR #%d" % pr["number"])
        mine = [p for p in open_rolls if p["head"]["ref"] == branch]
        if not mine:
            self._open_roll(ctx, action, branch, now)
            return
        pr = mine[0]
        v = self._drive(ctx, pr, threads_block=True)
        if v.kind == "merged":
            rolls[head] = {
                "pr": pr["number"],
                "commit": v.why,
                "merged_at": _iso(self.clock()),
            }
            ctx.status.get("releases", {}).pop(head, None)
            for name in action.supersedes:
                ctx.status.get("releases", {}).pop(name, None)
            ctx.status.get("releases", {}).pop(ctx.channel.current, None)
            for c in ctx.releases[head].changes:
                if c.fold:
                    n = rr.fold_number(c.pr)
                    self.gh.close_pull(
                        n,
                        "Folded into #%d (realm roller release %s)."
                        % (pr["number"], head),
                    )
                    ctx.notes.append("closed folded PR #%d" % n)
        elif v.kind == "conflict":
            self.gh.close_pull(
                pr["number"], "Conflicts with the base branch; the roller rewrites it."
            )
            self.gh.delete_branch(branch)
        elif v.kind == "failed":
            self.gh.close_pull(
                pr["number"],
                "Checks failed (%s); the roller pauses the channel." % v.why,
            )
            self.gh.delete_branch(branch)
            self._open_pause(
                ctx, "roll PR #%d for %s failed: %s" % (pr["number"], head, v.why), now
            )

    def _roll_files(
        self, ctx: Context, action: rr.Action, now: datetime
    ) -> tuple[list[dict], list[str], list[str]]:
        """The tree entries of the ONE roll commit."""
        head = ctx.releases[_named(action)]
        cur = ctx.releases[ctx.channel.current]
        changed = {s for s in head.sources if head.sources[s] != cur.sources.get(s)}
        touched = {c.name for c in rr.touched(ctx.channel, head, cur)}
        entries: dict[str, dict] = {}
        texts: dict[str, str] = {}
        modes: dict[str, str] = {}
        forbidden = (self.roller_path,) + tuple(g.path for g in ctx.act.gitlinks)
        # Folded config PRs first: the edits below apply on top of them.
        folds = []
        for c in head.changes:
            if not c.fold:
                continue
            n = rr.fold_number(c.pr)
            folds.append(c.pr)
            pr = self.gh.pull(n)
            if pr["state"] != "open":
                raise plan.PlanError("folded %s is %s" % (c.pr, pr["state"]))
            mbase = self.gh.merge_base(ctx.base_sha, pr["head"]["sha"])
            files = []
            for f in self.gh.pull_files(n):
                for path in {
                    f["filename"],
                    f.get("previous_filename") or f["filename"],
                }:
                    at_head = entry_at(self.gh, pr["head"]["sha"], path)
                    if at_head:
                        modes[path] = at_head["mode"]
                    files.append(
                        plan.FoldFile(
                            path=path,
                            at_merge_base=_sha(entry_at(self.gh, mbase, path)),
                            on_base=_sha(entry_at(self.gh, ctx.base_sha, path)),
                            at_head=_sha(at_head),
                            gitlink=bool(at_head and at_head["mode"] == "160000"),
                        )
                    )
            for path, blob in plan.fold_entries(c.pr, files, forbidden).items():
                if blob is None:
                    entries[path] = {
                        "path": path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": None,
                    }
                else:
                    texts[path] = self.gh.blob(blob).decode()
        for e in ctx.act.edits:
            if plan.applies(e, changed, touched) and e.path not in texts:
                text = text_at(self.gh, ctx.base_sha, e.path)
                if text is None:
                    raise plan.PlanError("%s: not in the deploy repo" % e.path)
                texts[e.path] = text
        edited = plan.apply_edits(
            texts, ctx.act.edits, plan.values(cur), plan.values(head), changed, touched
        )
        for path, text in edited.items():
            entry = entry_at(self.gh, ctx.base_sha, path)
            mode = modes.get(path) or (entry["mode"] if entry else "100644")
            entries[path] = {
                "path": path,
                "mode": mode,
                "type": "blob",
                "content": text,
            }
        for g in ctx.act.gitlinks:
            if g.source not in changed:
                continue
            entry = entry_at(self.gh, ctx.base_sha, g.path)
            if (
                not entry
                or entry["mode"] != "160000"
                or entry["sha"] != cur.sources[g.source]
            ):
                raise plan.PlanError(
                    "%s does not point at the current %s" % (g.path, g.source)
                )
            entries[g.path] = {
                "path": g.path,
                "mode": "160000",
                "type": "commit",
                "sha": head.sources[g.source],
            }
        roller = plan.roll_roller_files(
            self.roller_path,
            ctx.channel_raw,
            ctx.raws,
            head.name,
            action.supersedes,
            now,
        )
        for path, text in roller.items():
            entries[path] = {
                "path": path,
                "mode": "100644",
                "type": "blob",
                "content": text,
            }
        return list(entries.values()), sorted(touched), folds

    def _open_roll(
        self, ctx: Context, action: rr.Action, branch: str, now: datetime
    ) -> None:
        head = ctx.releases[_named(action)]
        cur = ctx.releases[ctx.channel.current]
        try:
            entries, touched, folds = self._roll_files(ctx, action, now)
        except plan.PlanError as exc:
            self._open_pause(ctx, "roll of %s refused: %s" % (head.name, exc), now)
            return
        title = "wow-dev: roll %s (%s)" % (head.name, head.summary)
        sha = self._commit(ctx, entries, title)
        self.gh.set_branch(branch, sha)
        body = plan.roll_body(
            head, cur, touched, action.supersedes, folds, self.tracker
        )
        pr = self.gh.create_pull(title, branch, ctx.act.base, body)
        ctx.status.setdefault("rolls", {})[head.name] = {"pr": pr["number"]}
        ctx.notes.append("opened roll PR #%d for %s" % (pr["number"], head.name))

    def _commit(self, ctx: Context, entries: list, title: str) -> str:
        tree = self.gh.make_tree(self.gh.commit(ctx.base_sha)["tree"]["sha"], entries)
        return self.gh.make_commit(
            "%s\n\nWritten by the realm roller (%s)." % (title, self.tracker),
            tree,
            [ctx.base_sha],
        )

    def _open_pause(self, ctx: Context, why: str, now: datetime) -> None:
        files = plan.pause_files(self.roller_path, ctx.channel_raw, why, now)
        entries = [
            {"path": p, "mode": "100644", "type": "blob", "content": t}
            for p, t in files.items()
        ]
        stamp = now.strftime("%Y%m%d%H%M")
        branch = self._branch(ctx, "pause", stamp)
        title = "wow-dev: pause the realm roller"
        self.gh.set_branch(branch, self._commit(ctx, entries, title))
        pr = self.gh.create_pull(
            title, branch, ctx.act.base, plan.pause_body(why, self.tracker)
        )
        ctx.notes.append("opened pause PR #%d: %s" % (pr["number"], why))

    # -- the rollback ------------------------------------------------------------------

    def _roll_commit(self, ctx: Context, name: str) -> str | None:
        known = ctx.status.get("rolls", {}).get(name, {}).get("commit")
        if known:
            return known
        path = "%s/releases/%s.json" % (self.roller_path, name)
        commits = self.gh.path_commits(path, ctx.act.base, limit=1)
        return commits[0]["sha"] if commits else None

    def _do_rollback(self, ctx: Context, action: rr.Action, now: datetime) -> None:
        name, target = _named(action), _named(action, "target")
        roll = self._roll_commit(ctx, name)
        try:
            if roll is None:
                raise plan.PlanError("no roll commit found for %s" % name)
            detail = self.gh.commit_detail(roll)
            parent = detail["parents"][0]["sha"]
            sides = []
            for f in detail.get("files", []):
                path = f["filename"]
                sides.append(
                    plan.Side(
                        path=path,
                        before=_ms(entry_at(self.gh, parent, path)),
                        rolled=_ms(entry_at(self.gh, roll, path)),
                        now=_ms(entry_at(self.gh, ctx.base_sha, path)),
                    )
                )
            reverts = plan.revert_entries(sides, self.roller_path)
        except plan.PlanError as exc:
            self._open_pause(
                ctx,
                "rollback of %s needs a person (%s): %s" % (name, exc, action.why),
                now,
            )
            return
        entries = []
        for path, ms in reverts.items():
            if ms is None:
                entries.append(
                    {"path": path, "mode": "100644", "type": "blob", "sha": None}
                )
            else:
                kind = "commit" if ms[0] == "160000" else "blob"
                entries.append(
                    {"path": path, "mode": ms[0], "type": kind, "sha": ms[1]}
                )
        files = plan.rollback_roller_files(
            self.roller_path, ctx.channel_raw, ctx.raws, name, target, action.why, now
        )
        for path, text in files.items():
            entries.append(
                {"path": path, "mode": "100644", "type": "blob", "content": text}
            )
        title = "wow-dev: roll back %s to %s" % (name, target)
        branch = self._branch(ctx, "rollback", name)
        self.gh.set_branch(branch, self._commit(ctx, entries, title))
        roll_pr = ctx.status.get("rolls", {}).get(name, {}).get("pr")
        body = plan.rollback_body(
            name,
            target,
            action.why,
            "#%s" % roll_pr if roll_pr else roll[:12],
            self.tracker,
        )
        pr = self.gh.create_pull(title, branch, ctx.act.base, body)
        ctx.status.get("releases", {}).pop(name, None)
        ctx.notes.append("opened rollback PR #%d: %s" % (pr["number"], action.why))


def _named(action: rr.Action, attr: str = "release") -> str:
    """The release (or rollback target) an action names; every act but wait has one."""
    value = getattr(action, attr)
    if not value:
        raise rr.Invalid("tick", ["%s names no %s" % (action.kind, attr)])
    return value


def _sha(entry: dict | None) -> str | None:
    return entry["sha"] if entry else None


def _ms(entry: dict | None) -> tuple[str, str] | None:
    return (entry["mode"], entry["sha"]) if entry else None


# --- the scheduled job's entry point -------------------------------------------------


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read().strip()


def main(argv=None) -> int:
    """One tick in act mode, as the scheduled job runs it.

        python3 realmroller_act.py --repo OWNER/NAME --roller-path PATH \\
            --site-url URL --status NAMESPACE/CONFIGMAP --app-dir DIR

    `--app-dir` is the mounted app Secret: files `app_id`, `installation_id`
    and `private_key`. The key is read only by openssl, from that file.
    """
    import argparse
    import sys

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--repo", required=True, help="the deploy repo, OWNER/NAME")
    ap.add_argument("--base", default="main", help="the deploy repo's base branch")
    ap.add_argument(
        "--roller-path", required=True, help="channel.json's directory in the repo"
    )
    ap.add_argument("--site-url", required=True, help="the overseer site's base URL")
    ap.add_argument(
        "--status", required=True, help="NAMESPACE/CONFIGMAP holding the status"
    )
    ap.add_argument("--app-dir", required=True, help="the mounted GitHub App Secret")
    ap.add_argument("--tracker", default="wow-overseer#590", help="cited in PR bodies")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token = AppToken(
        _read(os.path.join(args.app_dir, "app_id")),
        _read(os.path.join(args.app_dir, "installation_id")),
        os.path.join(args.app_dir, "private_key"),
        args.repo,
    )
    kube = Kube.in_cluster()
    namespace, name = args.status.split("/", 1)
    roller = Roller(
        GitHub(args.repo, token),
        kube,
        StatusStore(kube, namespace, name),
        args.roller_path,
        args.site_url,
        args.tracker,
        base=args.base,
    )
    try:
        notes = roller.step()
    except (rr.Invalid, plan.PlanError, plan.PairingError, ApiError, OSError) as exc:
        print("realm roller: stopped: %s" % exc, file=sys.stderr)
        return 1
    for line in notes:
        print("realm roller: %s" % line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
