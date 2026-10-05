"""PROTOTYPE. One roller tick as a pure function, to react to, not to run.

The real roller would be a CronJob in the wow-dev namespace that runs this
every 5 minutes: read the channel and release files from git, read the world
(family API, worldserver pod, logs), call tick(), then do the one Action it
returns and commit the state change. Nothing here touches a cluster or git.

Run `python3 -B prototype/realm-roller/roller.py` for a few sample decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

STATES = (
    "proposed",
    "building",
    "built",
    "proven",
    "rolling",
    "live",
    "verified",
    "build_failed",
    "prove_failed",
    "rolled_back",
)
NEXT = {
    "proposed": {"building"},
    "building": {"built", "build_failed"},
    "built": {"proven", "prove_failed"},
    "proven": {"rolling"},
    "rolling": {"live", "rolled_back"},
    "live": {"verified", "rolled_back"},
}


@dataclass
class World:
    """What the roller reads each tick. All of it is observed, never assumed."""

    now: datetime
    family_members_in_instance: int | None  # None = family API unreachable
    families_out_since: datetime | None
    last_roll_started: datetime | None
    worldserver_ready: bool
    pod_started: datetime | None
    restarts_30m: int
    log_hits: dict[str, bool] = field(default_factory=dict)  # verify grep -> seen
    bad_signature: str | None = None


@dataclass
class Release:
    name: str
    state: str
    verify: list[str]  # greps that must appear after the roll


@dataclass
class Channel:
    current: str
    previous: str
    queue: list[Release]
    rolling: Release | None
    paused: bool
    min_interval: timedelta = timedelta(minutes=60)
    settle: timedelta = timedelta(minutes=5)
    ready_within: timedelta = timedelta(minutes=15)
    grace: timedelta = timedelta(minutes=60)


@dataclass
class Action:
    kind: str  # wait | build | prove | roll | mark_live | mark_verified | rollback
    release: str | None
    why: str


def advance(rel: Release, to: str) -> None:
    if to not in NEXT.get(rel.state, set()):
        raise ValueError(f"{rel.name}: {rel.state} -> {to} is not a legal move")
    rel.state = to


def tick(ch: Channel, w: World) -> Action:
    # 1. A release on the realm is watched before anything else happens.
    r = ch.rolling
    if r is not None:
        if w.bad_signature:
            return Action("rollback", r.name, f"log signature: {w.bad_signature}")
        if w.restarts_30m > 2:
            return Action("rollback", r.name, f"{w.restarts_30m} restarts in 30m")
        started = w.pod_started or w.now
        if r.state == "rolling":
            if w.worldserver_ready:
                return Action("mark_live", r.name, "worldserver Ready")
            if w.now - started > ch.ready_within:
                return Action("rollback", r.name, "not Ready in time")
            return Action("wait", r.name, "worldserver starting")
        if r.state == "live":
            missing = [g for g in r.verify if not w.log_hits.get(g)]
            if not missing:
                return Action("mark_verified", r.name, "every verify grep seen")
            if w.now - started > ch.grace:
                return Action("rollback", r.name, f"never seen: {missing}")
            return Action("wait", r.name, f"waiting on {len(missing)} verify grep(s)")

    # 2. Build and prove run even while paused; only the roll is gated.
    for q in ch.queue:
        if q.state == "proposed":
            return Action("build", q.name, "dispatch one build for the pair")
        if q.state == "built":
            return Action("prove", q.name, "throwaway pod greps the binary")

    proven = [q for q in ch.queue if q.state == "proven"]
    if not proven:
        return Action("wait", None, "nothing proven")
    head = proven[-1]  # coalesce: newest proven release wins

    # 3. The gates, in the order a person would ask about them.
    if ch.paused:
        return Action("wait", head.name, "channel paused")
    if w.last_roll_started and w.now - w.last_roll_started < ch.min_interval:
        nxt = w.last_roll_started + ch.min_interval
        return Action("wait", head.name, f"one roll per hour; next at {nxt:%H:%M}")
    if w.family_members_in_instance is None:
        return Action("wait", head.name, "family API unreachable: treat as inside")
    if w.family_members_in_instance > 0:
        return Action(
            "wait",
            head.name,
            f"{w.family_members_in_instance} family member(s) in a dungeon",
        )
    if w.families_out_since is None or w.now - w.families_out_since < ch.settle:
        return Action("wait", head.name, "families just left; settling")
    return Action("roll", head.name, "one commit: digests + banner + deployed_dev")


if __name__ == "__main__":
    t0 = datetime(2026, 10, 4, 20, 0)
    rel = Release("r2026.10.04-2", "proven", ["answered the trade", "AUCTION_HISTORY"])
    ch = Channel("r2026.10.04-1", "r2026.10.03-3", [rel], None, paused=False)
    base = dict(worldserver_ready=True, pod_started=None, restarts_30m=0)
    cases = [
        (
            "recent roll",
            World(t0, 0, t0 - timedelta(hours=1), t0 - timedelta(minutes=20), **base),
        ),
        ("family inside", World(t0, 3, None, t0 - timedelta(hours=2), **base)),
        (
            "clear",
            World(t0, 0, t0 - timedelta(minutes=9), t0 - timedelta(hours=2), **base),
        ),
    ]
    for label, w in cases:
        a = tick(ch, w)
        print(f"{label:14} -> {a.kind:6} {a.why}")
    advance(rel, "rolling")
    ch.rolling = rel
    w = World(
        t0 + timedelta(minutes=70),
        0,
        None,
        t0,
        worldserver_ready=True,
        pod_started=t0 + timedelta(minutes=2),
        restarts_30m=0,
        log_hits={"answered the trade": True},
    )
    rel.state = "live"
    a = tick(ch, w)
    print(f"{'live, 1 miss':14} -> {a.kind:6} {a.why}")
