"""GET /api/v2/whats-live - follower bridge commit, worldserver roll, and recent PRs.

Answers in one read-only JSON document what a watcher needs instead of chasing
tickets and pods by hand:

- bridge: the running bridge commit, image digest, and roll timestamp from the
  `wow-dev-bridge-follow` ConfigMap (`merge`, `digest`, `deployed_at`).
- realm:  the running worldserver roll (via `realm_status` and the realm's
  `overseer_build` banner) and the `mod-overseer` commit it carries.
- prs:    recent merged PRs (last 48 hours, bounded) on `wow-overseer` and
  `mod-overseer`, classified as `merged`, `deployed`, `live-proven`, or
  `unknown` when the running commit or GitHub history could not be read.

Cluster reads reuse `apiv2/realm_status.py` and its service account. Every
unreadable source answers `unknown` with its reason in `unmeasured`, never a guess.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import realm
import realmmaint
from apiv2 import realm_status, roll, upstream

log = logging.getLogger(__name__)

UNKNOWN = "unknown"
DEFAULT_BRIDGE_CM = "wow-dev-bridge-follow"
WINDOW_HOURS = 48
COMMENT_WINDOW_HOURS = 72
TTL = 900
RETRY = 300
PR_PER_PAGE = 50
MAX_PR_PAGES = 2
MAX_PRS_PER_REPO = 40
COMMIT_PER_PAGE = 100
MAX_COMMIT_PAGES = 3
COMMENT_PER_PAGE = 100
MAX_COMMENT_PAGES = 3

REPOS = (
    {"repo": "quadseven/wow-overseer", "component": "bridge", "branch": "main"},
    {"repo": "quadseven/mod-overseer", "component": "module", "branch": "main"},
)

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.I)
REF_RE = re.compile(r"\b(?:refs?|fixes|closes|resolves)\s+#(\d+)\b", re.I)
TITLE_REF_RE = re.compile(r"\(#(\d+)\)")
LIVE_PROOF_RE = re.compile(r"(?:^|\n)\s*(?:[-*]\s*)?live\s+proof\s*:", re.I)


def _bridge_cm_name() -> str:
    return os.environ.get("WHATS_LIVE_BRIDGE_CONFIGMAP") or DEFAULT_BRIDGE_CM


def _default_fetch_cm() -> dict:
    ns = realm_status._namespace()
    return realm_status._get(
        "/api/v1/namespaces/%s/configmaps/%s" % (ns, _bridge_cm_name())
    )


def _parse_deployed_at(raw) -> tuple[str, int | None]:
    text = str(raw or "").strip()
    if not text:
        return UNKNOWN, None
    if text.isdigit():
        epoch = int(text)
        return realmmaint.iso(datetime.fromtimestamp(epoch, timezone.utc)), epoch
    dt = realmmaint.parse_time(text)
    if dt is not None:
        return realmmaint.iso(dt), int(dt.timestamp())
    return UNKNOWN, None


def _short(sha: str) -> str:
    return sha[:12] if sha != UNKNOWN else UNKNOWN


def read_bridge(fetch_cm: Callable[[], dict] | None = None) -> dict:
    """Read bridge follower state (`merge`, `digest`, `deployed_at`) or unknown."""
    reader = fetch_cm or _default_fetch_cm
    try:
        cm = reader()
    except Exception as err:  # noqa: BLE001 - unreadable ConfigMap returns unknown
        log.warning("bridge follower ConfigMap unreadable: %s", err)
        return {
            "commit": UNKNOWN,
            "short": UNKNOWN,
            "digest": UNKNOWN,
            "deployed_at": UNKNOWN,
            "deployed_seconds": None,
            "previous": UNKNOWN,
            "ship_pr": None,
            "unmeasured": {"bridge": "The follower ConfigMap read failed: %s" % err},
        }
    data = (cm or {}).get("data") if isinstance(cm, dict) else None
    if not isinstance(data, dict):
        data = {}
    unmeasured = {}
    commit = str(data.get("merge") or "").strip().lower() or UNKNOWN
    digest = str(data.get("digest") or "").strip() or UNKNOWN
    deployed_at, deployed_seconds = _parse_deployed_at(data.get("deployed_at"))
    for key, val in (
        ("merge", commit),
        ("digest", digest),
        ("deployed_at", deployed_at),
    ):
        if val == UNKNOWN:
            unmeasured[key] = "The follower ConfigMap omitted `%s`." % key
    previous = str(data.get("previous") or "").strip().lower() or UNKNOWN
    raw_pr = str(data.get("ship_pr") or "").strip().lstrip("#")
    ship_pr = int(raw_pr) if raw_pr.isdigit() else None
    return {
        "commit": commit,
        "short": _short(commit),
        "digest": digest,
        "deployed_at": deployed_at,
        "deployed_seconds": deployed_seconds,
        "previous": previous,
        "ship_pr": ship_pr,
        "unmeasured": unmeasured,
    }


def _read_banner(ctx, now: datetime) -> tuple[dict | None, str]:
    if ctx is None or not hasattr(ctx, "read"):
        return None, "The realm database reader is not available."
    try:
        build_rows = ctx.read.rows(roll.BUILD_SQL, what="overseer_build")
        version_rows = ctx.read.rows(roll.VERSION_SQL, what="acore_world.version")
    except Exception as err:  # noqa: BLE001 - banner read fails soft
        return None, "The realm database read failed: %s" % err
    return realm.build_realm(build_rows, version_rows, [], now=now), ""


def _banner_fields(banner: dict | None, banner_err: str) -> tuple[dict, dict]:
    unmeasured = {"banner": banner_err} if banner_err else {}
    mod_commit = roll._module_commit(banner) if banner else None
    if not mod_commit:
        mod_commit = UNKNOWN
        stale = bool(banner and banner.get("pins") == realm.PINS_STALE)
        unmeasured["module_commit"] = (
            "The worldserver's reported pins are stale."
            if stale
            else "The realm banner did not report its mod-overseer commit."
        )
    fields = {
        "build": (roll._build(banner) if banner else None) or UNKNOWN,
        "core_revision": (banner.get("core_revision") if banner else None) or UNKNOWN,
        "reported_at": (banner.get("reported_at") if banner else None) or UNKNOWN,
        "module_commit": mod_commit,
        "pins": (banner.get("pins") if banner else None) or UNKNOWN,
    }
    return fields, unmeasured


def _status_fields(rs: dict | None) -> tuple[dict, dict]:
    ws = rs.get("worldserver") if isinstance(rs, dict) else None
    if not rs or rs.get("state") == "UNKNOWN" or not isinstance(ws, dict):
        why = ((rs or {}).get("unmeasured") or {}).get("state")
        return {
            "state": "UNKNOWN",
            "up": None,
            "image_digest": UNKNOWN,
            "started_at": UNKNOWN,
        }, {"realm": why or "Worldserver status is unknown."}
    digest = str(ws.get("image_digest") or "").strip() or UNKNOWN
    started = str(ws.get("started_at") or "").strip() or UNKNOWN
    unmeasured = (
        {"image_digest": "Worldserver image digest is absent."}
        if digest == UNKNOWN
        else {}
    )
    return {
        "state": str(rs.get("state") or "UNKNOWN"),
        "up": ws.get("up"),
        "image_digest": digest,
        "started_at": started,
    }, unmeasured


def read_realm(
    ctx,
    read_status: Callable[..., dict] | None = None,
    now: datetime | None = None,
) -> dict:
    """Read worldserver roll and mod-overseer commit from banner + realm-status."""
    now = now or datetime.now(timezone.utc)
    banner, banner_err = _read_banner(ctx, now)
    b_fields, b_unmeasured = _banner_fields(banner, banner_err)
    rs = (read_status or realm_status.read_state)(now=now)
    s_fields, s_unmeasured = _status_fields(rs)
    unmeasured = {**b_unmeasured, **s_unmeasured}
    build_label = b_fields["build"]
    roll_label = build_label if build_label != UNKNOWN else s_fields["image_digest"]
    return {
        "state": s_fields["state"],
        "up": s_fields["up"],
        "roll": roll_label,
        "build": build_label,
        "image_digest": s_fields["image_digest"],
        "started_at": s_fields["started_at"],
        "reported_at": b_fields["reported_at"],
        "module_commit": b_fields["module_commit"],
        "module_short": _short(b_fields["module_commit"]),
        "core_revision": b_fields["core_revision"],
        "pins": b_fields["pins"],
        "unmeasured": unmeasured,
    }


def ancestors_of(head_sha: str | None, parents_by_sha: dict) -> frozenset[str]:
    """All commit SHAs reachable from `head_sha` in `parents_by_sha`."""
    if not head_sha or str(head_sha).lower() == UNKNOWN:
        return frozenset()
    norm_graph = {
        str(k).lower(): tuple(str(p).lower() for p in (v or ()))
        for k, v in (parents_by_sha or {}).items()
    }
    seen: set[str] = set()
    stack = [str(head_sha).lower()]
    while stack:
        cur = stack.pop()
        if not cur or cur in seen:
            continue
        seen.add(cur)
        stack.extend(p for p in norm_graph.get(cur, ()) if p not in seen)
    return frozenset(seen)


def _contains_commit(
    running_sha: str, running_ancestors: frozenset[str], target_sha: str
) -> bool:
    target = target_sha.lower()
    running = running_sha.lower()
    if target == running or target in running_ancestors:
        return True
    if len(target) >= 7:
        for anc in running_ancestors:
            if anc.startswith(target) or (len(anc) >= 7 and target.startswith(anc)):
                return True
    return False


def classify_pr_state(
    merge_commit_sha: str | None,
    refs: list[int],
    running_sha: str | None,
    running_ancestors: frozenset[str] | None,
    proven_tickets: set[int],
) -> str:
    """Classify one merged PR as merged, deployed, live-proven, or unknown."""
    run = (running_sha or "").strip().lower()
    merge = (merge_commit_sha or "").strip().lower()
    if not run or run == UNKNOWN or running_ancestors is None or not merge:
        return UNKNOWN
    if not _contains_commit(run, running_ancestors, merge):
        return "merged"
    if any(t in proven_tickets for t in refs):
        return "live-proven"
    return "deployed"


def extract_refs(title: str, body: str, pr_number: int) -> list[int]:
    """Ticket numbers ref'd by a PR, omitting `Part of #<epic>`."""
    found = {int(m.group(1)) for m in TITLE_REF_RE.finditer(title or "")}
    for source in (title or "", body or ""):
        for match in REF_RE.finditer(source):
            found.add(int(match.group(1)))
    found.discard(int(pr_number))
    return sorted(found)


def extract_proven_tickets(comments: list) -> set[int]:
    """Issue numbers whose comments carry a `Live proof:` marker."""
    proven: set[int] = set()
    for item in comments or ():
        if not isinstance(item, dict):
            continue
        body = str(item.get("body") or "")
        if not LIVE_PROOF_RE.search(body):
            continue
        issue_url = str(item.get("issue_url") or "")
        tail = issue_url.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            proven.add(int(tail))
    return proven


def _gh_get(fetch: Callable, now: float, path: str):
    status, body, headers = fetch(path)
    until = upstream._limited(status, headers, now)
    if until is not None:
        raise upstream.Limited(until)
    if status != 200:
        raise RuntimeError("GitHub returned HTTP %d" % status)
    return body


def _fetch_recent_pulls(fetch: Callable, now: float, spec: dict) -> list[dict]:
    cutoff = datetime.fromtimestamp(now, timezone.utc) - timedelta(hours=WINDOW_HOURS)
    repo = spec["repo"]
    branch = spec["branch"]
    out: list[dict] = []
    for page in range(1, MAX_PR_PAGES + 1):
        path = (
            "%s/pulls?state=closed&sort=updated&direction=desc&per_page=%d&page=%d"
            % (repo, PR_PER_PAGE, page)
        )
        items = _gh_get(fetch, now, path)
        if not isinstance(items, list) or not items:
            break
        stop = False
        for pr in items:
            base_ref = ((pr.get("base") or {}).get("ref")) or ""
            merged_raw = pr.get("merged_at")
            updated_dt = realmmaint.parse_time(pr.get("updated_at") or "")
            if updated_dt and updated_dt < cutoff:
                stop = True
            if base_ref != branch or not merged_raw:
                continue
            merged_dt = realmmaint.parse_time(merged_raw)
            if merged_dt and merged_dt >= cutoff:
                out.append(pr)
                if len(out) >= MAX_PRS_PER_REPO:
                    return out
        if stop or len(items) < PR_PER_PAGE:
            break
    return out


def _fetch_ancestors(
    fetch: Callable, now: float, repo: str, running_sha: str
) -> frozenset[str] | None:
    if not SHA_RE.match(running_sha or ""):
        return None
    parents: dict[str, tuple[str, ...]] = {}
    for page in range(1, MAX_COMMIT_PAGES + 1):
        path = "%s/commits?sha=%s&per_page=%d&page=%d" % (
            repo,
            running_sha,
            COMMIT_PER_PAGE,
            page,
        )
        items = _gh_get(fetch, now, path)
        if not isinstance(items, list) or not items:
            break
        for commit in items:
            sha = str(commit.get("sha") or "").lower()
            if sha:
                parents[sha] = tuple(
                    str(p.get("sha") or "").lower()
                    for p in commit.get("parents") or ()
                    if p.get("sha")
                )
        if len(items) < COMMIT_PER_PAGE:
            break
    return ancestors_of(running_sha, parents)


def _fetch_proven(fetch: Callable, now: float, repo: str) -> set[int]:
    since = (
        datetime.fromtimestamp(now, timezone.utc)
        - timedelta(hours=COMMENT_WINDOW_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    proven: set[int] = set()
    for page in range(1, MAX_COMMENT_PAGES + 1):
        path = (
            "%s/issues/comments?sort=updated&direction=desc&since=%s&per_page=%d&page=%d"
            % (
                repo,
                since,
                COMMENT_PER_PAGE,
                page,
            )
        )
        items = _gh_get(fetch, now, path)
        if not isinstance(items, list) or not items:
            break
        proven.update(extract_proven_tickets(items))
        if len(items) < COMMENT_PER_PAGE:
            break
    return proven


def _build_pr_row(
    spec: dict,
    pr: dict,
    running_sha: str,
    ancestors: frozenset[str] | None,
    proven: set[int],
) -> dict:
    num = int(pr["number"])
    title = upstream.ascii_line(str(pr.get("title") or ""))
    refs = extract_refs(str(pr.get("title") or ""), str(pr.get("body") or ""), num)
    merge_commit = str(pr.get("merge_commit_sha") or "").strip().lower() or UNKNOWN
    state = classify_pr_state(
        None if merge_commit == UNKNOWN else merge_commit,
        refs,
        running_sha,
        ancestors,
        proven,
    )
    return {
        "repo": spec["repo"],
        "component": spec["component"],
        "number": num,
        "title": title,
        "merge_commit": merge_commit,
        "merge_short": _short(merge_commit),
        "merged_at": str(pr.get("merged_at") or ""),
        "refs": refs,
        "url": str(pr.get("html_url") or ""),
        "state": state,
    }


class LiveBoard:
    """Cached recent merged PRs from GitHub, refreshed in the background."""

    def __init__(self, fetch=upstream.github, clock=time.time, spawn=None):
        self.fetch = fetch
        self.clock = clock
        self.spawn = spawn or self._thread
        self.lock = threading.Lock()
        self.prs: list[dict] = []
        self.key: tuple[str, str] | None = None
        self.at = 0.0
        self.next_at = 0.0
        self.limited_until = 0
        self.settled = False
        self.running = False
        self.error = ""

    @staticmethod
    def _thread(work: Callable) -> None:
        threading.Thread(target=work, daemon=True, name="whats-live-refresh").start()

    def _payload(self, now: float) -> dict:
        limited = self.limited_until if self.limited_until > now else None
        if limited:
            state = "limited"
        elif self.error and not self.prs:
            state = UNKNOWN
        elif self.settled:
            state = "ready"
        else:
            state = "checking"
        unmeasured = {}
        if limited:
            unmeasured["prs"] = upstream.LIMITED_WHY
        elif self.error:
            unmeasured["prs"] = self.error
        elif state == "checking":
            unmeasured["prs"] = "Checking GitHub for recent merged PRs."
        return {
            "prs_state": state,
            "prs_checked_at": int(self.at) if self.at else None,
            "limited_until": limited,
            "ttl": TTL,
            "window_hours": WINDOW_HOURS,
            "prs": list(self.prs),
            "unmeasured": unmeasured,
        }

    def snapshot(self, bridge_commit: str, module_commit: str) -> dict:
        """Return cached PR state immediately, starting a background refresh if due."""
        key = (_short(bridge_commit), _short(module_commit))
        now = self.clock()
        start = False
        with self.lock:
            due = (self.key != key or now >= self.next_at) and now >= self.limited_until
            if due and not self.running:
                self.running = start = True
        if start:
            self.spawn(lambda: self.refresh(bridge_commit, module_commit, key))
        with self.lock:
            return self._payload(self.clock())

    def refresh(self, bridge_commit: str, module_commit: str, key) -> None:
        """Fetch recent PRs, ancestor commits, and live-proof markers cleanly."""
        now = self.clock()
        running_by_component = {"bridge": bridge_commit, "module": module_commit}
        rows: list[dict] = []
        limit = 0
        err_msg = ""
        try:
            for spec in REPOS:
                repo = spec["repo"]
                running_sha = running_by_component[spec["component"]]
                pulls = _fetch_recent_pulls(self.fetch, now, spec)
                ancestors = _fetch_ancestors(self.fetch, now, repo, running_sha)
                need_proofs = bool(ancestors) and any(
                    extract_refs(
                        pr.get("title") or "", pr.get("body") or "", pr["number"]
                    )
                    for pr in pulls
                )
                proven = _fetch_proven(self.fetch, now, repo) if need_proofs else set()
                for pr in pulls:
                    rows.append(_build_pr_row(spec, pr, running_sha, ancestors, proven))
            rows.sort(key=lambda r: (r["merged_at"], r["number"]), reverse=True)
        except upstream.Limited as err:
            limit = err.until
            err_msg = upstream.LIMITED_WHY
        except Exception as err:  # noqa: BLE001 - degrade GitHub errors to unknown
            log.warning("whats-live GitHub read failed: %s", err)
            err_msg = "GitHub read failed: %s" % err
        finally:
            with self.lock:
                self._settle(rows, key, now, limit, err_msg)

    def _settle(
        self, rows: list[dict], key, now: float, limit: int, err_msg: str
    ) -> None:
        self.settled = True
        self.key = key
        self.limited_until = limit
        self.error = err_msg
        if not err_msg:
            self.prs = rows
            self.at = now
            self.next_at = now + TTL
        else:
            self.next_at = now + RETRY
        self.running = False


BOARD = LiveBoard()


def build_whats_live(
    ctx,
    *,
    fetch_cm: Callable[[], dict] | None = None,
    read_status: Callable[..., dict] | None = None,
    board: LiveBoard | None = None,
    now: datetime | None = None,
) -> dict:
    """Assemble the complete /api/v2/whats-live JSON document."""
    now = now or datetime.now(timezone.utc)
    bridge = read_bridge(fetch_cm=fetch_cm)
    realm_info = read_realm(ctx, read_status=read_status, now=now)
    pr_snap = (board or BOARD).snapshot(bridge["commit"], realm_info["module_commit"])
    unmeasured = {}
    unmeasured.update(bridge.get("unmeasured") or {})
    unmeasured.update(realm_info.get("unmeasured") or {})
    unmeasured.update(pr_snap.get("unmeasured") or {})
    return {
        "checked_at": realmmaint.iso(now),
        "bridge": {k: v for k, v in bridge.items() if k != "unmeasured"},
        "realm": {k: v for k, v in realm_info.items() if k != "unmeasured"},
        "prs_state": pr_snap["prs_state"],
        "prs_checked_at": pr_snap["prs_checked_at"],
        "window_hours": pr_snap["window_hours"],
        "prs": pr_snap["prs"],
        "unmeasured": unmeasured,
    }


def whats_live(_query: dict, ctx) -> tuple[int, dict]:
    return 200, build_whats_live(ctx)


ROUTES = {"/api/v2/whats-live": whats_live}
