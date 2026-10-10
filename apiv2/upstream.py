"""GET /api/v2/upstream: how far behind each pinned dependency is.

The realm is built from pinned commits of a few public projects. This asks
GitHub's public API how many commits each project has gained since the pin,
and lists the notable ones, so an operator can see drift without opening a
terminal.

WHERE THE PINS COME FROM. The site cannot read the private infra repo that
holds the pin file, and a copy committed here would only be a second pin
that drifts. Instead the pins are what the realm itself reports it is
running (the same overseer_build rows /api/realm names in its banner: the
core revision, mod-playerbots, mod-ollama-chat, mod-dungeon-clear,
mod-ah-bot-plus). A project the realm does not report (mod-junk-to-gold,
mod-overseer) takes its pin from the OVERSEER_UPSTREAM_PINS environment
variable, a JSON object of name -> commit. A project with no pin from either
is "not measured", never guessed.

NEVER BLOCKS A PAGE. The handler answers from a cache at once. When the cache
is older than an hour (or the pins changed) it starts one background refresh
and answers with what it has. A cold cache answers "checking" with the pins
and no counts. GitHub is asked without a token, so the budget is 60 requests
an hour; one refresh is at most about 16, once an hour. When GitHub says the
limit is reached, nothing more is asked until its reset time, and the rows
keep their last good reading marked stale, or read "not measured".

Read-only: the realm is only read, and nothing here writes anywhere.
"""

from __future__ import annotations

import calendar
import json
import math
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Callable

TTL = 3600  # seconds a reading is good for
RETRY = 300  # seconds before asking again after a failed refresh
PER_PAGE = 250  # the most commits a compare lists per page
LISTED = 6  # notable commits shown per project
API = "https://api.github.com/repos/"
ENV_PINS = "OVERSEER_UPSTREAM_PINS"

# name: the pin's key; repo/branch: where its upstream lives. `pin` is the key
# the pin is read under, so two rows can measure one pin against two places.
COMPONENTS = (
    {
        "name": "core",
        "label": "AzerothCore, playerbots fork",
        "role": "core",
        "repo": "mod-playerbots/azerothcore-wotlk",
        "branch": "Playerbot",
        "pin": "core",
    },
    {
        "name": "azerothcore",
        "label": "AzerothCore, the fork's own upstream",
        "role": "core",
        "repo": "azerothcore/azerothcore-wotlk",
        "branch": "master",
        "pin": "core",
    },
    {
        "name": "mod-playerbots",
        "label": "mod-playerbots",
        "role": "module",
        "repo": "mod-playerbots/mod-playerbots",
        "branch": "master",
        "pin": "mod-playerbots",
    },
    {
        "name": "mod-ollama-chat",
        "label": "mod-ollama-chat",
        "role": "module",
        "repo": "DustinHendrickson/mod-ollama-chat",
        "branch": "main",
        "pin": "mod-ollama-chat",
    },
    {
        "name": "mod-ah-bot-plus",
        "label": "mod-ah-bot-plus",
        "role": "module",
        "repo": "NathanHandley/mod-ah-bot-plus",
        "branch": "master",
        "pin": "mod-ah-bot-plus",
    },
    {
        "name": "mod-junk-to-gold",
        "label": "mod-junk-to-gold",
        "role": "module",
        "repo": "noisiver/mod-junk-to-gold",
        "branch": "master",
        "pin": "mod-junk-to-gold",
    },
    {
        "name": "mod-dungeon-clear",
        "label": "mod-dungeon-clear (ours)",
        "role": "ours",
        "repo": "quadseven/mod-dungeon-clear",
        "branch": "master",
        "pin": "mod-dungeon-clear",
    },
    {
        "name": "mod-overseer",
        "label": "mod-overseer (ours)",
        "role": "ours",
        "repo": "quadseven/mod-overseer",
        "branch": "main",
        "pin": "mod-overseer",
    },
)

LIMITED_WHY = "GitHub's rate limit is spent; the next check is after its reset."
SHA = re.compile(r"^[0-9a-f]{7,40}$")

# Commit titles that are bookkeeping, not change.
_SKIP = re.compile(
    r"^(merge |chore|style|ci\b|\(ci\)|docs?\b|test|refactor)|import pending|autolabel|"
    r"coderabbit|agent guidelines|whitespace|typo",
    re.I,
)
_CRASH = re.compile(
    r"crash|use-after-free|after a call that can free|freed|null.?check|nullptr|deadlock|"
    r"race\b|segfault|overflow|out of range|never read|dangling",
    re.I,
)
_SECURITY = re.compile(
    r"security|exploit|cheat|inject|sanitiz|stop addon messages|spoof", re.I
)
_BOTS = re.compile(
    r"\bbots?\b|playerbot|selfbot|\(Bot|Ai/|\bAi\b|loot|rpg|battleground|bg\b", re.I
)
_RUNS = re.compile(
    r"dungeon|raid|heroic|instance|encounter|boss|Scripts/|Ulduar|Onyxia|ICC\b|BWL|Kara\b",
    re.I,
)
# Tags in the order they rank.
TAGS = (("security", _SECURITY), ("crash", _CRASH), ("bots", _BOTS), ("runs", _RUNS))


def ascii_line(text: str, limit: int = 110) -> str:
    """One line of ASCII: the page's copy rule applies to titles it quotes."""
    text = (text or "").splitlines()[0] if text else ""
    text = text.replace(chr(0x2014), "-").replace(chr(0x2013), "-")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def tags_of(title: str) -> list[str]:
    return [name for name, pattern in TAGS if pattern.search(title)]


def notable(commits: list) -> tuple[list, dict]:
    """(the commits worth a line, counts of kinds), newest first.

    The kinds are read from commit titles by keyword, so the counts say "titles
    that mention", not "verified". Bookkeeping commits are dropped; the rest
    rank by their strongest tag, then by recency.
    """
    found = []
    counts = {name: 0 for name, _ in TAGS}
    for rank, commit in enumerate(reversed(commits or [])):
        body = commit.get("commit") or {}
        title = ascii_line(body.get("message") or "")
        if not title or _SKIP.search(title):
            continue
        tags = tags_of(title)
        for tag in tags:
            counts[tag] += 1
        weight = min(
            (i for i, (name, _) in enumerate(TAGS) if name in tags), default=len(TAGS)
        )
        date = ((body.get("committer") or {}).get("date")) or ""
        found.append(
            (
                weight,
                rank,
                {
                    "sha": (commit.get("sha") or "")[:8],
                    "title": title,
                    "tags": tags,
                    "date": date[:10],
                },
            )
        )
    found.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in found[:LISTED]], counts


def seconds_of(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def github(path: str) -> tuple[int, object, dict]:
    """(status, JSON body, headers). Status 0 is a network failure. No token."""
    # API is a fixed https URL and `path` is built from the COMPONENTS table and
    # validated hex pins, so no file: or custom scheme can reach urlopen.
    request = urllib.request.Request(  # noqa: S310
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "wow-overseer-upstream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as resp:  # noqa: S310 - fixed https host
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as err:
        return err.code, None, dict(err.headers or {})
    except (OSError, ValueError):
        return 0, None, {}


class Limited(Exception):
    """GitHub's rate limit is spent; `until` is its reset time (unix seconds)."""

    def __init__(self, until: int):
        super().__init__("rate limited")
        self.until = until


def _limited(status: int, headers: dict, now: float) -> int | None:
    lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
    if status == 429 or (status == 403 and lowered.get("x-ratelimit-remaining") == "0"):
        try:
            return int(lowered.get("x-ratelimit-reset", ""))
        except ValueError:
            return int(now) + RETRY
    return None


def compare(
    fetch: Callable, now: float, repo: str, pin: str, branch: str
) -> dict | None:
    """The compare of a pin against its branch: pages joined, or None if the
    pin is unknown to GitHub. Raises Limited when the rate limit is spent."""
    base = "%s/compare/%s...%s?per_page=%d" % (repo, pin, branch, PER_PAGE)
    pages = [1]
    out = None
    while pages:
        page = pages.pop()
        status, body, headers = fetch(base + "&page=%d" % page)
        until = _limited(status, headers, now)
        if until is not None:
            raise Limited(until)
        if status != 200 or not isinstance(body, dict):
            if out is None:
                return None
            break
        if out is None:
            out = body
            last = math.ceil((body.get("ahead_by") or 0) / PER_PAGE)
            if last > 1:
                pages.append(last)
        else:
            out["commits"] = (out.get("commits") or []) + (body.get("commits") or [])
    return out


def row_of(
    spec: dict,
    pin: str | None,
    how: str | None,
    reading: dict | None,
    at: float,
    why: str = "GitHub did not answer for this commit.",
) -> dict:
    """One project's row from its compare (None: could not be measured, for `why`)."""
    row = {
        "name": spec["name"],
        "label": spec["label"],
        "role": spec["role"],
        "repo": spec["repo"],
        "branch": spec["branch"],
        "pinned": pin[:12] if pin else None,
        "pin_source": how,
        "pinned_at": None,
        "head": None,
        "head_at": None,
        "behind": None,
        "carried": None,
        "status": "not measured",
        "reason": None,
        "checked_at": None,
        "stale": False,
        "notable": [],
        "counts": None,
        "url": None,
    }
    if not pin:
        row["reason"] = "The realm does not report this pin."
        return row
    if reading is None:
        row["reason"] = why
        return row
    commits = reading.get("commits") or []
    base = (reading.get("base_commit") or {}).get("commit", {})
    head = commits[-1] if commits else (reading.get("base_commit") or {})
    behind = reading.get("ahead_by")
    row.update(
        {
            "pinned_at": seconds_of((base.get("committer") or {}).get("date")),
            "head": (head.get("sha") or "")[:12] or None,
            "head_at": seconds_of(
                ((head.get("commit") or {}).get("committer") or {}).get("date")
            ),
            "behind": behind,
            "carried": reading.get("behind_by"),
            "status": "current" if behind == 0 else "behind",
            "checked_at": int(at),
            "url": "https://github.com/%s/compare/%s...%s"
            % (spec["repo"], pin[:12], spec["branch"]),
        }
    )
    row["notable"], row["counts"] = notable(commits)
    return row


class Board:
    """The cached readings, refreshed at most hourly in the background."""

    def __init__(self, fetch=github, clock=time.time, spawn=None):
        self.fetch = fetch
        self.clock = clock
        self.spawn = spawn or self._thread
        self.lock = threading.Lock()
        self.rows: dict = {}  # name -> last row
        self.key = None  # the pins the rows were read for
        self.at = 0.0  # when the last refresh finished
        self.next_at = 0.0  # when the next refresh is due
        self.limited_until = 0
        self.settled = False  # a refresh has finished at least once
        self.running = False

    @staticmethod
    def _thread(work: Callable) -> None:
        threading.Thread(target=work, daemon=True, name="upstream-refresh").start()

    def snapshot(self, pins: dict) -> dict:
        """The payload now, starting a refresh if one is due. Never waits."""
        key = tuple(sorted((k, v[0]) for k, v in pins.items()))
        now = self.clock()
        start = False
        with self.lock:
            due = (self.key != key or now >= self.next_at) and now >= self.limited_until
            if due and not self.running:
                self.running = start = True
            rows = [self._row(spec, pins) for spec in COMPONENTS]
            limited = self.limited_until if self.limited_until > now else None
            checked = self.at or None
            state = "limited" if limited else ("ready" if self.settled else "checking")
        if start:
            self.spawn(lambda: self.refresh(pins, key))
        return {
            "state": state,
            "checked_at": int(checked) if checked else None,
            "limited_until": limited,
            "ttl": TTL,
            "rows": rows,
        }

    def _row(self, spec: dict, pins: dict) -> dict:
        pin, how = pins.get(spec["pin"], (None, None))
        old = self.rows.get(spec["name"])
        if pin and old and old["pinned"] == pin[:12]:
            return dict(old, pin_source=how)
        why = "Not checked yet."
        if self.limited_until > self.clock():
            why = LIMITED_WHY
        return row_of(spec, pin, how, None, 0, why)

    def refresh(self, pins: dict, key) -> None:
        """Measure every project. Runs on a worker thread, or inline in tests."""
        now = self.clock()
        rows: dict = {}
        limit = 0
        try:
            for spec in COMPONENTS:
                pin, how = pins.get(spec["pin"], (None, None))
                reading = None
                if pin and not limit:
                    try:
                        reading = compare(
                            self.fetch, now, spec["repo"], pin, spec["branch"]
                        )
                    except Limited as err:
                        limit = err.until
                why = LIMITED_WHY if limit else "GitHub did not answer for this commit."
                rows[spec["name"]] = row_of(spec, pin, how, reading, now, why)
        finally:
            with self.lock:
                self._settle(rows, key, now, limit)

    def _settle(self, rows: dict, key, now: float, limit: int) -> None:
        for name, row in list(rows.items()):
            old = self.rows.get(name)
            if (
                row["pinned"]
                and row["status"] == "not measured"
                and old
                and old["status"] != "not measured"
                and old["pinned"] == row["pinned"]
            ):
                rows[name] = dict(old, stale=True)
        measured = any(r["status"] != "not measured" for r in rows.values())
        self.rows = rows
        self.key = key
        self.settled = True
        if measured:
            self.at = now
        self.limited_until = limit
        self.next_at = now + (TTL if measured else RETRY)
        self.running = False


BOARD = Board()


def env_pins(environ=None) -> dict:
    """OVERSEER_UPSTREAM_PINS: a JSON object of name -> commit, or nothing."""
    raw = (environ if environ is not None else os.environ).get(ENV_PINS, "")
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v).lower() for k, v in data.items() if SHA.match(str(v).lower())
    }


def declared_pins(payload: dict, environ=None) -> dict:
    """name -> (commit, where it came from): the realm's report first, the
    environment only for what the realm does not report."""
    pins = {}
    core = (payload or {}).get("core_revision") or ""
    if SHA.match(core):
        pins["core"] = (core, "realm")
    for item in (payload or {}).get("upstreams") or ():
        value = str(item.get("value") or "").lower()
        if SHA.match(value):
            pins[str(item.get("name"))] = (value, "realm")
    for name, value in env_pins(environ).items():
        pins.setdefault(name, (value, "environment"))
    return pins


def realm_payload(ctx) -> dict:
    """The /api/realm banner's JSON, read through this request's reader."""
    server = ctx.server
    return server.realm.build_realm(
        build_rows=ctx.read.rows(server._BUILD_SQL, what="overseer_build"),
        version_rows=ctx.read.rows(
            server._WORLD_VERSION_SQL, what="acore_world.version"
        ),
        realmlist_rows=ctx.read.rows(
            server._REALMLIST_SQL, what="acore_auth.realmlist"
        ),
    )


def upstream(_query: dict, ctx) -> tuple[int, dict]:
    return 200, BOARD.snapshot(declared_pins(realm_payload(ctx)))


ROUTES = {"/api/v2/upstream": upstream}
