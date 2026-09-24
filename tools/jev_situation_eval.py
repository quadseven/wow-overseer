"""Does the movement picture change what Jev chooses? A paired evaluation.

For each family, the activity_choice question is built exactly as the bridge
builds it and asked twice, once without `situation` and once with it, over
the same facts at the same moment. The difference between the two answers is
the effect of the feature and nothing else. `--counterfactual` also asks the
same facts under three made-up situations (calm, scattered and stuck, dying
to elites) to show which way the answer moves when the picture does.

The "before" column is what overseer_jev_judgment already holds for the kind
over the last day: the answers and confidence Jev gave with no situation.

Needs the bridge's environment: MYSQL_HOST, MYSQL_ROOT_PASSWORD and
TYPESAFE_API_KEY (read from the environment and never printed). It reads the
realm and asks Jev; it writes nothing, and it never records a judgment.

    python3 tools/jev_situation_eval.py --minutes 5 --rounds 3 --counterfactual
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bridge  # noqa: E402
import campaignqueue  # noqa: E402
import jev  # noqa: E402
import jev_activity  # noqa: E402
import situation  # noqa: E402
import vision  # noqa: E402

KIND = jev_activity.KIND


def logged(hours: int = 24) -> dict:
    """What the record already says for the kind: per family, the answers."""
    with bridge._connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT subject, heuristic, jev, confidence, agree FROM "
            "overseer_jev_judgment WHERE kind = %s AND jev IS NOT NULL "
            "AND created_at > NOW() - INTERVAL %s HOUR",
            (KIND, int(hours)),
        )
        rows = [dict(r) for r in cur.fetchall()]
    out: dict = {}
    for r in rows:
        f = out.setdefault(str(r["subject"]), {"answers": {}, "conf": [], "agree": 0})
        f["answers"][r["jev"]] = f["answers"].get(r["jev"], 0) + 1
        f["conf"].append(float(r["confidence"] or 0.0))
        f["agree"] += int(r["agree"] or 0)
    return {
        k: {
            "n": len(v["conf"]),
            "answers": v["answers"],
            "mean_confidence": round(statistics.fmean(v["conf"]), 3),
            "agree_with_heuristic": round(v["agree"] / len(v["conf"]), 3),
        }
        for k, v in out.items()
        if v["conf"]
    }


def activity_facts(key: str, fam: dict, rows: list) -> jev_activity.Facts:
    """The activity Facts the bridge builds, without the bridge's clock state:
    the reason is the cadence and nothing can gather or train (only the
    bridge's own family gets those, and they need its live loops)."""
    names = list(fam["names"])
    leader = fam["leader"]
    reads = bridge._activity_reads(names, str(leader.get("name") or ""))
    done = leader.get("dungeon_runs_done")
    runs = None if done is None else int(done)
    members = jev_activity.members_from_rows(
        names,
        reads["members"],
        reads["free"],
        reads["worn"],
        reads["goods"],
        reads["recipes"],
    )
    return jev_activity.Facts(
        family=key or str(leader.get("name") or ""),
        members=members,
        job=str(leader.get("job") or "").strip().lower(),
        queue=campaignqueue.progress_line(rows, runs),
        withheld=jev_activity.withheld(bool(rows), reads["free"]),
        reason=jev_activity.CADENCE,
    )


def picture(key, fam, tracker, seer, now) -> situation.Situation:
    names = list(fam["names"])
    leader = str(fam["leader"].get("name") or "")
    reads = bridge._situation_reads(names, leader)
    look = None
    if seer is not None and leader in vision.heads():
        look = asyncio.run(seer.look(leader))
    levels = [int(r.get("level") or 0) for r in reads["members"] or ()]
    return situation.build(
        names,
        leader,
        reads["snapshot"],
        tracker,
        now,
        leader_travel=reads["columns"].get(leader, ""),
        leader_job=reads["jobs"].get(leader, ""),
        spawn_rows=reads["spawns"],
        death_rows=reads["deaths"],
        leader_nodes=reads["leader_nodes"],
        goal_nodes=reads["goal_nodes"],
        races=[r.get("race") for r in reads["members"] or ()],
        weakest_level=min(levels) if levels else 0,
        columns=reads["columns"],
        vision=look.state(time.monotonic()) if look is not None else None,
    )


def made_up(real: situation.Situation, shape: str) -> situation.Situation:
    """The real picture with one thing changed, for the counterfactual."""
    import dataclasses

    names = [b.name for b in real.bodies]
    if shape == "calm":
        return dataclasses.replace(
            real,
            progress={n: situation.MOVING for n in names},
            cohesion={"spread_yards": 6},
            danger={"hostile_spawns": 0},
            deaths={"count": 0},
        )
    if shape == "scattered_and_stuck":
        far = [
            "%s %d yd, 190 below" % (n, 900 + 100 * i) for i, n in enumerate(names[1:3])
        ]
        return dataclasses.replace(
            real,
            progress={n: situation.STUCK for n in names},
            cohesion={"spread_yards": 1100, "far_from_leader": far},
        )
    if shape == "dying_to_elites":
        return dataclasses.replace(
            real,
            danger={
                "hostile_spawns": 9,
                "elites": 4,
                "highest_level": 62,
                "levels_above_weakest_member": 4,
                "worst": ["Elite Guardian (elite, 60-62)"],
            },
            deaths={
                "count": 5,
                "killers": ["Elite Guardian x4", "environment"],
                "minutes_since_last": 2,
                "who": names[:3],
            },
        )
    raise ValueError(shape)


async def ask(client, f, rule) -> dict:
    j = await jev_activity.ask(client, f, rule)
    if j is None:
        return {"asked": False}
    return {
        "asked": True,
        "status": j.status,
        "heuristic": j.heuristic,
        "jev": j.jev,
        "confidence": None if j.confidence is None else round(j.confidence, 3),
        "top": dict(sorted((j.probabilities or {}).items(), key=lambda kv: -kv[1])[:3]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=5.0, help="trail to build first")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--gap", type=float, default=60.0, help="seconds between rounds")
    ap.add_argument("--counterfactual", action="store_true")
    ap.add_argument("--vision", action="store_true", help="look at the heads' frames")
    args = ap.parse_args()

    client = jev.Client.from_env(cache_size=0)
    if not client.configured:
        print("no TYPESAFE_API_KEY in the environment", file=sys.stderr)
        return 2
    rule = jev.Policy(KIND, jev.SHADOW, 1.0)
    seer = (
        vision.Seer.from_env(dict(os.environ, LLM_URL=bridge.LLM_URL))
        if args.vision
        else None
    )
    tracker = situation.Tracker()

    def sample():
        rows = bridge._fetch_situation_sample()
        names = [str(r["name"]) for r in rows]
        tracker.record_bodies(situation.bodies_from_rows(names, rows), time.monotonic())

    print(json.dumps({"before": logged()}, default=str))
    deadline = time.monotonic() + 60.0 * args.minutes
    while time.monotonic() < deadline:
        sample()
        time.sleep(30.0)
    fams = campaignqueue.families(bridge._fetch_queue_roster())
    pending = campaignqueue.pending_by_family(bridge._fetch_queue_rows())
    for rnd in range(args.rounds):
        sample()
        now = time.monotonic()
        for key, fam in sorted(fams.items()):
            f = activity_facts(key, fam, pending.get(key, []))
            where = picture(key, fam, tracker, seer, now)
            out = {
                "round": rnd,
                "family": key,
                "situation_line": where.line(),
                "without": asyncio.run(ask(client, f, rule)),
                "with": asyncio.run(
                    ask(
                        client,
                        jev_activity.Facts(**{**f.__dict__, "situation": where}),
                        rule,
                    )
                ),
            }
            if args.counterfactual and rnd == 0:
                out["counterfactual"] = {
                    shape: asyncio.run(
                        ask(
                            client,
                            jev_activity.Facts(
                                **{**f.__dict__, "situation": made_up(where, shape)}
                            ),
                            rule,
                        )
                    )
                    for shape in ("calm", "scattered_and_stuck", "dying_to_elites")
                }
            print(json.dumps(out, default=str))
            sys.stdout.flush()
        if rnd + 1 < args.rounds:
            end = time.monotonic() + args.gap
            while time.monotonic() < end:
                time.sleep(min(30.0, max(0.0, end - time.monotonic())))
                sample()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
