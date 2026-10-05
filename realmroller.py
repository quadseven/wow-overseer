"""The realm roller: release and channel files, and one pure decision tick.

#590, from the prototype approved in #522. A RELEASE is a named, complete set
of source SHAs plus the images one build made from them. A CHANNEL names the
release a realm runs (`current`), the verified release it falls back to
(`previous`), a `queue` of releases waiting to roll, a `paused` flag and the
policy. Both are JSON files in the deploy repo, beside the overlay they change,
so a roll and its state change are one commit there.

This module is pure: it parses and validates those files and decides, from
them and from a `World` the caller observed, the ONE thing the roller should
do next. It reads no network, cluster or git. `realmroller_world.py` observes;
`tools/realm_roller.py` wires the two together (dry run only in phase 1).

THE ANSWERS #522 APPROVED, and where each lives here:

- Site-only releases skip the worldserver gates (`Component.gated`).
- A roll waits for the families AND any guild group in an instance.
- The hourly limit is per roll start; a rollback is exempt.
- A failed roll rolls back automatically and pauses the channel.
- A missing verify grep rolls back unless the change marks it `soft`.
- Queued proven releases coalesce: only the newest rolls.
- A channel file that does not say `paused` IS paused. Turning the roller on
  is an explicit `"paused": false` in a reviewed commit.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# proposed -> building -> built -> proven -> rolling -> live -> verified
# Exits: build_failed, prove_failed, rolled_back; superseded when a newer
# proven release rolls in its place (coalescing).
NEXT = {
    "proposed": ("building",),
    "building": ("built", "build_failed"),
    "built": ("proven", "prove_failed"),
    "proven": ("rolling", "superseded"),
    "rolling": ("live", "rolled_back"),
    "live": ("verified", "rolled_back"),
}
STATES = frozenset(NEXT) | {
    "verified",
    "build_failed",
    "prove_failed",
    "rolled_back",
    "superseded",
}
# A release in one of these is on the realm and watched before anything else.
ON_REALM = ("rolling", "live")
# The states a queued release may be in. Failed releases stay queued (and
# visible) until a person removes them; the tick skips them.
QUEUED = ("proposed", "building", "built", "proven", "build_failed", "prove_failed")
# A release in one of these has both digests of every component it touches.
HAS_IMAGES = ("built", "proven", "rolling", "live", "verified", "rolled_back")

_NAME = re.compile(r"^r\d{4}\.\d{2}\.\d{2}-\d+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DURATION = re.compile(r"^(\d+)([smh])$")
_FOLD_PR = re.compile(r"^[A-Za-z0-9_.-]*#(\d+)$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours"}


class Invalid(ValueError):
    """A release or channel file that the roller must not act on.

    Carries every problem found, not just the first, so one read of the
    error is enough to fix the file.
    """

    def __init__(self, where: str, problems: list[str]):
        self.where = where
        self.problems = problems
        super().__init__("%s: %s" % (where, "; ".join(problems)))


def duration(text: object) -> timedelta:
    """`"60m"` -> 60 minutes. Seconds, minutes or hours; nothing else."""
    m = _DURATION.match(str(text))
    if not m or int(m.group(1)) <= 0:
        raise ValueError("not a duration like 5m, 1h or 30s: %r" % (text,))
    return timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})


def instant(text: object) -> datetime:
    """An ISO 8601 time WITH an offset. A naive time is refused, not guessed."""
    when = datetime.fromisoformat(str(text))
    if when.tzinfo is None:
        raise ValueError("time has no UTC offset: %r" % (text,))
    return when


# --- the channel ----------------------------------------------------------


@dataclass(frozen=True)
class Component:
    """One restartable part of the realm and the sources and images it is built from.

    `gated` components (the worldserver) take the hourly and the instance
    gates; an ungated one (the site) restarts only its own pods.
    """

    name: str
    sources: tuple[str, ...]
    images: tuple[str, ...]
    gated: bool


@dataclass(frozen=True)
class Rollback:
    restarts_over: int
    restarts_window: timedelta
    log_signatures: tuple[str, ...]
    bots_below_pct: int
    bots_below_for: timedelta


@dataclass(frozen=True)
class Policy:
    min_interval: timedelta
    settle: timedelta
    ready_within: timedelta
    families: tuple[str, ...]
    guild_run_states: tuple[str, ...]
    rollback: Rollback
    # Where a roll that predates the roller left its mark: the deploy-repo
    # file whose digest lines a roll changes, and the regex `git log -G` uses.
    roll_marker_path: str
    roll_marker_pattern: str


@dataclass(frozen=True)
class Channel:
    channel: str
    realm: str
    current: str
    previous: str
    queue: tuple[str, ...]
    paused: bool
    paused_reason: str
    components: tuple[Component, ...]
    policy: Policy

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(s for c in self.components for s in c.sources)


def _need(d: dict, key: str, kind, problems: list[str], where: str = ""):
    value = d.get(key)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        problems.append("%s%s must be %s" % (where, key, _kind_name(kind)))
        return None
    return value


def _kind_name(kind) -> str:
    names = {str: "a string", int: "an integer", bool: "true or false", list: "a list"}
    return names.get(kind, "an object")


def _strings(d: dict, key: str, problems: list[str], where: str = "") -> tuple:
    value = _need(d, key, list, problems, where)
    if value is None:
        return ()
    if not value or not all(isinstance(v, str) and v for v in value):
        problems.append("%s%s must be a non-empty list of strings" % (where, key))
        return ()
    return tuple(value)


def _duration_of(d: dict, key: str, problems: list[str], where: str = ""):
    try:
        return duration(d.get(key))
    except ValueError as exc:
        problems.append("%s%s: %s" % (where, key, exc))
        return timedelta(0)


def parse_channel(data: object) -> Channel:
    """A channel file's JSON, checked. Raises Invalid listing every problem."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise Invalid("channel", ["must be a JSON object"])
    name = _need(data, "channel", str, problems) or ""
    realm = _need(data, "realm", str, problems) or ""
    current = _release_name(data, "current", problems)
    previous = _release_name(data, "previous", problems)
    queue = _parse_queue(data.get("queue", []), current, problems)
    paused, reason = _parse_paused(data, problems)
    components = _parse_components(data.get("components"), problems)
    policy = _parse_policy(data.get("policy"), problems)
    if problems:
        raise Invalid("channel %s" % (name or "?"), problems)
    return Channel(
        name, realm, current, previous, tuple(queue), paused, reason, components, policy
    )


def _release_name(data: dict, key: str, problems: list[str]) -> str:
    value = _need(data, key, str, problems) or ""
    if value and not _NAME.match(value):
        problems.append("%s %r is not a release name like r2026.10.04-1" % (key, value))
    return value


def _parse_queue(queue: object, current: str, problems: list[str]) -> list[str]:
    if not isinstance(queue, list) or not all(isinstance(q, str) for q in queue):
        problems.append("queue must be a list of release names")
        return []
    problems.extend(
        "queue entry %r is not a release name" % q for q in queue if not _NAME.match(q)
    )
    if len(set(queue)) != len(queue):
        problems.append("queue names a release twice")
    if current and current in queue:
        problems.append("current %s is also queued" % current)
    return queue


def _parse_paused(data: dict, problems: list[str]) -> tuple[bool, str]:
    """PAUSED UNLESS SAID OTHERWISE. A missing or non-boolean flag is paused.

    The roller is turned on by a reviewed `"paused": false`, never by an
    omission or a typo.
    """
    raw = data.get("paused", True)
    if not isinstance(raw, bool):
        problems.append("paused must be true or false")
    reason = data.get("paused_reason", "")
    if not isinstance(reason, str):
        problems.append("paused_reason must be a string")
        reason = ""
    return raw is not False, reason


def _parse_components(raw: object, problems: list[str]) -> tuple[Component, ...]:
    if not isinstance(raw, dict) or not raw:
        problems.append("components must be an object naming at least one component")
        return ()
    out = []
    seen_sources: set[str] = set()
    seen_images: set[str] = set()
    for name, spec in raw.items():
        where = "components.%s." % name
        if not isinstance(spec, dict):
            problems.append("%s must be an object" % where[:-1])
            continue
        sources = _strings(spec, "sources", problems, where)
        images = _strings(spec, "images", problems, where)
        gated = _need(spec, "gated", bool, problems, where)
        for s in sources:
            if s in seen_sources:
                problems.append("source %s belongs to two components" % s)
            seen_sources.add(s)
        for i in images:
            if i in seen_images:
                problems.append("image %s belongs to two components" % i)
            seen_images.add(i)
        out.append(Component(name, sources, images, bool(gated)))
    return tuple(out)


def _parse_policy(raw: object, problems: list[str]) -> Policy:
    if not isinstance(raw, dict):
        problems.append("policy must be an object")
        raw = {}
    rb = raw.get("rollback")
    if not isinstance(rb, dict):
        problems.append("policy.rollback must be an object")
        rb = {}
    restarts = _need(rb, "restarts_over", int, problems, "policy.rollback.")
    pct = _need(rb, "bots_below_pct", int, problems, "policy.rollback.")
    if isinstance(pct, int) and not 0 < pct < 100:
        problems.append("policy.rollback.bots_below_pct must be between 1 and 99")
    marker = raw.get("roll_marker")
    if not isinstance(marker, dict):
        problems.append("policy.roll_marker must be an object with path and pattern")
        marker = {}
    path = _need(marker, "path", str, problems, "policy.roll_marker.") or ""
    pattern = _need(marker, "pattern", str, problems, "policy.roll_marker.") or ""
    if pattern:
        try:
            re.compile(pattern)
        except re.error as exc:
            problems.append("policy.roll_marker.pattern: %s" % exc)
    return Policy(
        min_interval=_duration_of(raw, "min_interval", problems, "policy."),
        settle=_duration_of(raw, "settle", problems, "policy."),
        ready_within=_duration_of(raw, "ready_within", problems, "policy."),
        families=_strings(raw, "families", problems, "policy."),
        guild_run_states=_strings(raw, "guild_run_states", problems, "policy."),
        rollback=Rollback(
            restarts_over=restarts or 0,
            restarts_window=_duration_of(
                rb, "restarts_window", problems, "policy.rollback."
            ),
            log_signatures=_strings(rb, "log_signatures", problems, "policy.rollback."),
            bots_below_pct=pct or 0,
            bots_below_for=_duration_of(
                rb, "bots_below_for", problems, "policy.rollback."
            ),
        ),
        roll_marker_path=path,
        roll_marker_pattern=pattern,
    )


# --- the release ----------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """A change's live-log check: `grep` must appear, or `absent` must not, within `within`."""

    log: str
    text: str
    absent: bool
    within: timedelta
    soft: bool

    @property
    def label(self) -> str:
        return ('absent "%s"' if self.absent else '"%s"') % self.text


@dataclass(frozen=True)
class Change:
    pr: str
    what: str
    prove: tuple[str, str] | None  # (image, grep) run against the built binary
    verify: Check | None
    # A queued config-only PR in the deploy repo whose diff rides the roll
    # commit, so it lands in the same restart. `pr` names it as `#N` or
    # `repo#N`.
    fold: bool = False


@dataclass(frozen=True)
class Event:
    at: datetime
    to: str
    by: str
    note: str


@dataclass(frozen=True)
class Release:
    name: str
    summary: str
    proposed_by: str
    sources: dict[str, str]
    changes: tuple[Change, ...]
    run: int
    images: dict[str, str]
    state: str
    history: tuple[Event, ...] = field(default=())

    def entered(self, state: str) -> datetime | None:
        """When this release last moved to `state`, from its own history."""
        times = [e.at for e in self.history if e.to == state]
        return max(times) if times else None


def parse_release(data: object, channel: Channel) -> Release:
    """A release file's JSON, checked against the channel's sources and images."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise Invalid("release", ["must be a JSON object"])
    name = _need(data, "release", str, problems) or ""
    if name and not _NAME.match(name):
        problems.append("release %r is not a name like r2026.10.04-1" % name)
    summary = _need(data, "summary", str, problems) or ""
    proposed_by = _need(data, "proposed_by", str, problems) or ""
    sources = _parse_sources(data.get("sources"), channel, problems)
    images_all = {i for c in channel.components for i in c.images}
    logs = images_all | {c.name for c in channel.components}
    changes = _parse_changes(data.get("changes"), images_all, logs, problems)
    run, images = _parse_build(data.get("build", {}), images_all, problems)
    state = data.get("state")
    if state not in STATES:
        problems.append(
            "state %r is not one of %s" % (state, ", ".join(sorted(STATES)))
        )
    history = _parse_history(data.get("history", []), state, problems)
    if problems:
        raise Invalid("release %s" % (name or "?"), problems)
    return Release(
        name, summary, proposed_by, sources, changes, run, images, state, history
    )


def _parse_sources(raw: object, channel: Channel, problems: list[str]) -> dict:
    """EVERY SOURCE, EVERY TIME. A release is complete on its own.

    Nothing is inherited from a branch or from the release before it.
    """
    if not isinstance(raw, dict):
        problems.append("sources must be an object")
        return {}
    missing = [s for s in channel.sources if s not in raw]
    if missing:
        problems.append("sources lacks %s" % ", ".join(missing))
    extra = [s for s in raw if s not in channel.sources]
    if extra:
        problems.append(
            "sources names %s, which no component builds" % ", ".join(extra)
        )
    problems.extend(
        "sources.%s must be a full 40-character SHA" % key
        for key, sha in raw.items()
        if not isinstance(sha, str) or not _SHA.match(sha)
    )
    return dict(raw)


def _parse_build(build: object, images_all: set, problems: list[str]):
    """(run id, {image: digest}) from the release's `build` block."""
    if not isinstance(build, dict):
        problems.append("build must be an object")
        return 0, {}
    run = build.get("run", 0)
    if not isinstance(run, int) or isinstance(run, bool) or run < 0:
        problems.append("build.run must be a non-negative integer")
        run = 0
    images = build.get("images", {})
    if not isinstance(images, dict):
        problems.append("build.images must be an object")
        return run, {}
    for key, digest in images.items():
        if key not in images_all:
            problems.append("build.images.%s is not an image of any component" % key)
        if not isinstance(digest, str) or not _DIGEST.match(digest):
            problems.append("build.images.%s must be sha256:<64 hex>" % key)
    return run, dict(images)


def _parse_changes(raw, images, logs, problems) -> tuple[Change, ...]:
    if not isinstance(raw, list):
        problems.append("changes must be a list")
        return ()
    out = []
    for n, c in enumerate(raw):
        where = "changes[%d]." % n
        if not isinstance(c, dict):
            problems.append("%s must be an object" % where[:-1])
            continue
        pr = _need(c, "pr", str, problems, where) or ""
        what = _need(c, "what", str, problems, where) or ""
        prove = None
        if "prove" in c:
            p = c["prove"]
            if (
                not isinstance(p, dict)
                or p.get("image") not in images
                or not isinstance(p.get("grep"), str)
                or not p.get("grep")
            ):
                problems.append(
                    "%sprove needs an image of a component and a non-empty grep" % where
                )
            else:
                prove = (p["image"], p["grep"])
        verify = None
        if "verify" in c:
            verify = _parse_check(c["verify"], logs, where + "verify.", problems)
        fold = c.get("fold", False)
        if not isinstance(fold, bool):
            problems.append("%sfold must be true or false" % where)
            fold = False
        elif fold and not _FOLD_PR.match(pr):
            problems.append("%sfold needs pr like #123 or repo#123" % where)
        out.append(Change(pr, what, prove, verify, fold))
    return tuple(out)


def _parse_check(v, logs, where, problems) -> Check | None:
    if not isinstance(v, dict):
        problems.append("%s must be an object" % where[:-1])
        return None
    log = v.get("log")
    if log not in logs:
        problems.append("%slog must name a component or image log" % where)
    has_grep, has_absent = "grep" in v, "absent" in v
    if has_grep == has_absent:
        problems.append("%s needs exactly one of grep or absent" % where[:-1])
        return None
    text = v["grep"] if has_grep else v["absent"]
    if not isinstance(text, str) or not text:
        problems.append(
            "%s%s must be a non-empty string"
            % (where, "grep" if has_grep else "absent")
        )
        return None
    within = _duration_of(v, "within", problems, where)
    soft = v.get("soft", False)
    if not isinstance(soft, bool):
        problems.append("%ssoft must be true or false" % where)
        soft = False
    return Check(str(log), text, has_absent, within, soft)


def _parse_history(raw, state, problems) -> tuple[Event, ...]:
    if not isinstance(raw, list):
        problems.append("history must be a list")
        return ()
    events = []
    for n, e in enumerate(raw):
        if not isinstance(e, dict):
            problems.append("history[%d] must be an object" % n)
            continue
        try:
            at = instant(e.get("at"))
        except (TypeError, ValueError) as exc:
            problems.append("history[%d].at: %s" % (n, exc))
            continue
        events.append(
            Event(at, str(e.get("to")), str(e.get("by", "")), str(e.get("note", "")))
        )
    # The history is the release's own path through the states: it starts at
    # proposed, every step is a legal move, and it ends where `state` says.
    here = "proposed"
    for e in events:
        if e.to not in NEXT.get(here, ()):
            problems.append(
                "history moves %s -> %s, which is not a legal move" % (here, e.to)
            )
            return tuple(events)
        here = e.to
    if state in STATES and here != state:
        problems.append("history ends at %s but state is %s" % (here, state))
    for a, b in itertools.pairwise(events):
        if b.at < a.at:
            problems.append("history goes back in time at %s" % b.to)
    return tuple(events)


def fold_number(pr: str) -> int:
    """The deploy-repo PR number a folded change names (`#5` or `repo#5` -> 5)."""
    m = _FOLD_PR.match(pr)
    if not m:
        raise ValueError("not a PR reference like #123 or repo#123: %r" % pr)
    return int(m.group(1))


def touched(channel: Channel, release: Release, base: Release) -> tuple[Component, ...]:
    """The components whose sources differ between `base` and `release`."""
    return tuple(
        c
        for c in channel.components
        if any(release.sources.get(s) != base.sources.get(s) for s in c.sources)
    )


def check_set(channel: Channel, releases: dict[str, Release]) -> None:
    """The channel and its releases, checked as one: what one file cannot see alone."""
    problems = _check_refs(channel, releases)
    if not problems:
        problems = _check_images(channel, releases)
    if problems:
        raise Invalid("channel %s" % channel.channel, problems)


def _check_refs(channel: Channel, releases: dict[str, Release]) -> list[str]:
    problems = [
        "%s %s has no release file" % (key, getattr(channel, key))
        for key in ("current", "previous")
        if getattr(channel, key) not in releases
    ]
    for q in channel.queue:
        if q not in releases:
            problems.append("queued %s has no release file" % q)
        elif releases[q].state not in QUEUED:
            problems.append(
                "queued %s is %s, which cannot wait in a queue" % (q, releases[q].state)
            )
    prev = releases.get(channel.previous)
    if prev is not None and prev.state != "verified":
        # The rollback target must be known good, or a rollback is a gamble.
        problems.append(
            "previous %s is %s; a rollback target must be verified"
            % (prev.name, prev.state)
        )
    cur = releases.get(channel.current)
    if cur is not None and cur.state not in ON_REALM + ("verified",):
        problems.append(
            "current %s is %s; it must be rolling, live or verified"
            % (cur.name, cur.state)
        )
    return problems


def _check_images(channel: Channel, releases: dict[str, Release]) -> list[str]:
    """A COUPLED PAIR LEAVES BUILT TOGETHER OR NOT AT ALL.

    Every image of every component a release touches must be present once it
    is built. Called only after _check_refs found `current`.
    """
    cur = releases[channel.current]
    problems = []
    for name, rel in releases.items():
        if rel.state not in HAS_IMAGES or name == channel.current:
            continue
        want = [i for c in touched(channel, rel, cur) for i in c.images]
        lacking = [i for i in want if i not in rel.images]
        if lacking:
            problems.append(
                "%s is %s without the %s digest(s)"
                % (name, rel.state, ", ".join(lacking))
            )
    return problems


# --- the tick -------------------------------------------------------------


@dataclass(frozen=True)
class World:
    """What the roller observed this tick. Every field is read, never assumed.

    None means "could not read", and each gate treats that as the unsafe
    answer: an unreachable family API counts as a family inside.
    """

    now: datetime
    family_in_instance: int | None
    guild_groups_inside: int | None
    # When the families and guild groups were last seen to leave. The tick
    # only reads this; the CALLER carries it from one tick to the next
    # (realmroller_world.carry_out_since).
    out_since: datetime | None
    last_roll_started: datetime | None
    ready: bool | None = None  # the restarted component reports Ready
    restarts: int = 0  # restarts within policy.rollback.restarts_window
    bad_signature: str | None = None  # a fatal log line seen since the roll
    # Every check's label -> whether its text has been seen in its log since
    # the release went live.
    seen: dict[str, bool] = field(default_factory=dict)
    bots_low_since: datetime | None = None  # bots online under the threshold
    # When the roll commit landed on the deploy repo's base branch. The release
    # history's `rolling` time is when the roll PR was opened, and checks and
    # review can hold that PR for longer than ready_within; the Ready window
    # counts from the merge when it is known.
    rolled_at: datetime | None = None


@dataclass(frozen=True)
class Action:
    """The one thing to do this tick.

    kind: wait | build | watch_build | prove | roll | mark_live | mark_verified
    | rollback. `target` is the release a rollback restores; `supersedes` the
    older proven releases a coalescing roll retires; `pause` is set on a
    rollback, which pauses the channel until a person looks.
    """

    kind: str
    release: str | None
    why: str
    target: str | None = None
    supersedes: tuple[str, ...] = ()
    pause: bool = False
    gated: bool = True


def last_roll_start(
    releases: dict[str, Release], marker: datetime | None
) -> datetime | None:
    """The latest roll start: any release entering `rolling`, or the deploy-repo mark.

    A rollback is not a roll start (#522 answer 5), so it is never counted.
    `marker` covers rolls made by hand before the roller existed.
    """
    times = [t for t in (r.entered("rolling") for r in releases.values()) if t]
    if marker is not None:
        times.append(marker)
    return max(times) if times else None


def tick(channel: Channel, releases: dict[str, Release], w: World) -> Action:
    """Decide the one next step. Pure: reads its arguments, changes nothing."""
    cur = releases[channel.current]
    if cur.state in ON_REALM:
        return _watch(channel, cur, w)
    step = _pipeline_step(channel, releases)
    if step is not None:
        return step

    proven = [n for n in channel.queue if releases[n].state == "proven"]
    if not proven:
        return Action("wait", None, "nothing proven")
    head = proven[-1]  # coalesce: the newest proven release rolls
    older = tuple(proven[:-1])
    parts = touched(channel, releases[head], cur)
    gated = any(c.gated for c in parts)
    held = _held(channel, w, gated)
    if held:
        return Action("wait", head, held, supersedes=older, gated=gated)
    names = ", ".join(c.name for c in parts) or "nothing"
    why = "one commit: %s digests + banner + deployed_dev" % names
    if not gated:
        why += " (ungated: restarts %s only)" % names
    return Action("roll", head, why, supersedes=older, gated=gated)


def _pipeline_step(channel: Channel, releases: dict[str, Release]) -> Action | None:
    """Build and prove, oldest queued first. These run even while paused or gated."""
    for name in channel.queue:
        rel = releases[name]
        if rel.state == "proposed":
            return Action("build", name, "dispatch one build from the release's SHAs")
        if rel.state == "building":
            return Action("watch_build", name, "build run %d in progress" % rel.run)
        if rel.state == "built":
            greps = sum(1 for c in rel.changes if c.prove)
            return Action(
                "prove", name, "throwaway pod greps the binary (%d grep(s))" % greps
            )
    return None


def _held(channel: Channel, w: World, gated: bool) -> str:
    """Why the roll waits, or "" when every gate is open. Pause holds every roll."""
    if channel.paused:
        reason = channel.paused_reason
        return "channel paused" + (": %s" % reason if reason else "")
    if not gated:
        return ""
    p = channel.policy
    if w.last_roll_started and w.now - w.last_roll_started < p.min_interval:
        nxt = (w.last_roll_started + p.min_interval).astimezone(timezone.utc)
        return "one roll start per %s; next at %s" % (
            _span(p.min_interval),
            nxt.strftime("%H:%MZ"),
        )
    for count, unreadable, what in (
        (w.family_in_instance, "family API unreachable", "family member(s)"),
        (w.guild_groups_inside, "guild runs unreadable", "guild group(s)"),
    ):
        if count is None:
            return "%s: treat as inside" % unreadable
        if count > 0:
            return "%d %s in an instance" % (count, what)
    if w.out_since is None or w.now - w.out_since < p.settle:
        return "everyone out, settling for %s" % _span(p.settle)
    return ""


def _watch(channel: Channel, rel: Release, w: World) -> Action:
    """A release on the realm: roll back on any failure, else move it forward.

    A rollback skips the hourly and the instance gates (the realm is already
    broken) and pauses the channel so the next release does not roll over an
    unexplained failure.
    """
    pending: list[str] = []
    flagged: list[str] = []
    failed = _realm_failure(channel, rel, w)
    if failed is None and rel.state == "live":
        failed, pending, flagged = _verify(rel, w)
    if failed:
        return Action("rollback", rel.name, failed, target=channel.previous, pause=True)
    if rel.state == "rolling":
        return (
            Action("mark_live", rel.name, "Ready")
            if w.ready
            else Action("wait", rel.name, "restarting")
        )
    if pending:
        return Action("wait", rel.name, "verifying: %d check(s) open" % len(pending))
    why = "every check passed"
    if flagged:
        why += "; soft check(s) flagged: %s" % ", ".join(flagged)
    return Action("mark_verified", rel.name, why)


def _realm_failure(channel: Channel, rel: Release, w: World) -> str | None:
    """A failure that rolls back in any on-realm state, or None."""
    rb = channel.policy.rollback
    if w.bad_signature:
        return "log signature: %s" % w.bad_signature
    if w.restarts > rb.restarts_over:
        return "%d restarts in %s" % (w.restarts, _span(rb.restarts_window))
    if rel.state == "rolling" and not w.ready:
        started = w.rolled_at or rel.entered("rolling") or w.now
        if w.now - started > channel.policy.ready_within:
            return "not Ready within %s" % _span(channel.policy.ready_within)
    if rel.state == "live" and w.bots_low_since is not None:
        if w.now - w.bots_low_since >= rb.bots_below_for:
            return "bots online under %d%% for %s" % (
                rb.bots_below_pct,
                _span(rb.bots_below_for),
            )
    return None


def _verify(rel: Release, w: World) -> tuple[str | None, list[str], list[str]]:
    """(failure, open checks, flagged soft checks) for a live release."""
    live_at = rel.entered("live") or w.now
    pending, flagged = [], []
    for check in (c.verify for c in rel.changes if c.verify):
        hit = bool(w.seen.get(check.label))
        over = w.now - live_at >= check.within
        # An absent text seen fails at once; a grep fails only once its window
        # has passed unseen.
        failed = hit if check.absent else (over and not hit)
        if failed:
            if not check.soft:
                verb = "seen" if check.absent else "never seen"
                return "%s %s" % (verb, check.label), pending, flagged
            flagged.append(check.label)
        elif not over and (check.absent or not hit):
            pending.append(check.label)
    return None, pending, flagged


def _span(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    if minutes and minutes % 60 == 0:
        return "%dh" % (minutes // 60)
    return "%dm" % minutes if minutes else "%ds" % int(td.total_seconds())
