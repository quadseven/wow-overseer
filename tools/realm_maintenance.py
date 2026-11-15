#!/usr/bin/env python3
"""realm-maintenance: take the worldserver down on purpose, with a notice.

    realm-maintenance down --reason "why" --eta 20m [--who label] [--force]
    realm-maintenance up

`down` writes the maintenance notice (reason, who, started_at, expected_back)
as an annotation on the Deployment, then scales it to 0. `up` scales to 1,
waits for the rollout to be Ready, then moves the notice to the last-notice
annotation. If the wait fails the notice stays, so the realm status reads
OVERRUN once the ETA passes instead of looking like an unexplained outage.

Settings: NAMESPACE (or --namespace) names the realm's namespace;
REALM_MAINTENANCE_WHO (or --who) is an agent or role label, never a person's
name; --deployment defaults to worldserver; KUBECONFIG and --context pass to
kubectl. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import realmmaint  # noqa: E402

ROLLOUT_TIMEOUT = "600s"
DRAIN_TIMEOUT = "330s"


def _kubectl(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="realm-maintenance", description=__doc__)
    p.add_argument("-n", "--namespace")
    p.add_argument("--deployment", default="worldserver")
    p.add_argument("--context")
    sub = p.add_subparsers(dest="command", required=True)
    down = sub.add_parser("down", help="write the notice, then scale to 0")
    down.add_argument("--reason", required=True)
    down.add_argument("--eta", required=True, help="90s, 20m or 2h")
    down.add_argument("--who")
    down.add_argument("--force", action="store_true", help="replace an open notice")
    sub.add_parser("up", help="scale to 1, wait for Ready, clear the notice")
    return p


def _dump(value: dict) -> str:
    return json.dumps(value, separators=(",", ":"))


class Realm:
    """One worldserver Deployment, driven through kubectl."""

    def __init__(self, base: list[str], deployment: str, run, now, out):
        self.base, self.deployment, self.run = base, deployment, run
        self.now, self.out = now, out
        self.target = "deploy/" + deployment

    def kube(self, *rest: str) -> subprocess.CompletedProcess:
        return self.run(self.base + list(rest))

    def open_notice(self) -> dict | None:
        res = self.kube("get", self.target, "-o", "json")
        if res.returncode != 0:
            raise SystemExit("cannot read %s: %s" % (self.target, res.stderr.strip()))
        meta = json.loads(res.stdout).get("metadata") or {}
        raw = (meta.get("annotations") or {}).get(realmmaint.NOTICE_KEY)
        return realmmaint.parse_notice(raw)

    def down(self, reason: str, who: str, eta, force: bool) -> int:
        held = self.open_notice()
        if held and not force:
            self.out(
                "refusing: a maintenance notice is already open (%s, by %s, back by %s). "
                "Use --force to replace it."
                % (held["reason"], held["who"], held["expected_back"])
            )
            return 1
        notice = realmmaint.new_notice(reason, who, self.now(), eta)
        res = self.kube(
            "annotate",
            self.target,
            "--overwrite",
            "%s=%s" % (realmmaint.NOTICE_KEY, _dump(notice)),
        )
        if res.returncode != 0:
            self.out("could not write the notice, not scaling: " + res.stderr.strip())
            return 1
        res = self.kube("scale", self.target, "--replicas=0")
        if res.returncode != 0:
            self.kube("annotate", self.target, realmmaint.NOTICE_KEY + "-")
            self.out("scale failed, notice cleared: " + res.stderr.strip())
            return 1
        self.out(
            "notice written; %s scaled to 0; back by %s"
            % (self.target, notice["expected_back"])
        )
        res = self.kube(
            "wait",
            "--for=delete",
            "pod",
            "-l",
            "app=" + self.deployment,
            "--timeout=" + DRAIN_TIMEOUT,
        )
        if res.returncode != 0:
            self.out("warning: pods did not finish draining: " + res.stderr.strip())
        return 0

    def up(self) -> int:
        held = self.open_notice()
        res = self.kube("scale", self.target, "--replicas=1")
        if res.returncode != 0:
            self.out("scale failed: " + res.stderr.strip())
            return 1
        res = self.kube(
            "rollout", "status", self.target, "--timeout=" + ROLLOUT_TIMEOUT
        )
        if res.returncode != 0:
            self.out(
                "not Ready within %s; notice left in place: %s"
                % (ROLLOUT_TIMEOUT, res.stderr.strip())
            )
            return 1
        if held:
            last = realmmaint.retire(held, self.now())
            res = self.kube(
                "annotate",
                self.target,
                "--overwrite",
                "%s=%s" % (realmmaint.LAST_KEY, _dump(last)),
                realmmaint.NOTICE_KEY + "-",
            )
            if res.returncode != 0:
                self.out(
                    "Ready, but the notice could not be cleared: " + res.stderr.strip()
                )
                return 1
        self.out("%s is Ready; notice cleared" % self.target)
        return 0


def _down_args(p, args, env):
    """(reason, who, eta) from the arguments, or a usage error."""
    try:
        eta = realmmaint.parse_eta(args.eta)
    except ValueError as err:
        p.error(str(err))
    who = (args.who or env.get("REALM_MAINTENANCE_WHO") or "").strip()
    if not who:
        p.error("set REALM_MAINTENANCE_WHO or pass --who (an agent or role label)")
    reason = args.reason.strip()
    if not reason:
        p.error("--reason may not be empty")
    return reason, who, eta


def main(argv=None, run=_kubectl, now=None, env=None, out=print) -> int:
    env = os.environ if env is None else env
    now = now or (lambda: datetime.now(timezone.utc))
    p = _parser()
    args = p.parse_args(argv)
    namespace = args.namespace or env.get("NAMESPACE")
    if not namespace:
        p.error("set NAMESPACE or pass --namespace")
    base = [env.get("REALM_MAINTENANCE_KUBECTL", "kubectl")]
    if args.context:
        base += ["--context", args.context]
    base += ["-n", namespace]
    realm = Realm(base, args.deployment, run, now, out)
    if args.command == "down":
        reason, who, eta = _down_args(p, args, env)
        return realm.down(reason, who, eta, args.force)
    return realm.up()


if __name__ == "__main__":
    sys.exit(main())
