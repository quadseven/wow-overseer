"""`python3 -m ephemeral <lint|acts|seed|judge|submit|dispatch|collect> ...`: the `eph` command line."""

import argparse
import json
import os
import pathlib
import signal
import sys

from . import acts, anchors as anchors_mod, dbschema, lint
from .miniyaml import YamlError, loads


def _lint(args):
    try:
        anchors_doc = loads(
            pathlib.Path(args.anchors or anchors_mod.DEFAULT_PATH).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, YamlError) as exc:
        print(f"error: anchors: {exc}")
        return 2
    bad = anchors_mod.validate(anchors_doc)
    for problem in bad:
        print(f"error: anchors: {problem}")
    anchors = anchors_mod.Anchors((anchors_doc or {}).get("anchors") or {})
    schema = dbschema.Schema.load(args.schema)
    failed = bool(bad)
    for path in args.decrees:
        if pathlib.Path(path).name == "anchors.yaml":
            continue  # checked above, not a decree
        findings = lint.lint_path(path, anchors, schema)
        for f in findings:
            print(f"{path}: {f}")
        if lint.has_errors(findings) or (args.strict and findings):
            failed = True
        elif not findings:
            print(f"{path}: ok")
    return 1 if failed else 0


def _acts(args):
    try:
        decree = loads(pathlib.Path(args.decree).read_text(encoding="utf-8"))
        rows = acts.act_commands(decree)
    except (OSError, YamlError, KeyError, TypeError) as exc:
        print(f"error: {args.decree}: {exc}")
        return 2
    print(json.dumps(rows, indent=2))
    return 0


def _seed(args):
    from . import podpaths, seedrun

    return seedrun.run(
        args.decree,
        podpaths.with_vars_file(os.environ),
        dry_run=args.dry_run,
        anchors_path=args.anchors,
    )


def _judge(args):
    from . import judge, podpaths

    return judge.run(
        args.decree,
        podpaths.with_vars_file(os.environ),
        log_path=podpaths.log_path(args.log, os.environ),
        anchors_path=args.anchors,
    )


def _runner(args):
    """(config, kubectl, gh) for the PC-side commands."""
    from . import ghx, kube, runcfg

    cfg = runcfg.load(args.config)
    k = kube.Kubectl(cfg.namespace, kubeconfig=cfg.kubeconfig or None)
    gh = ghx.Gh(
        env=os.environ,
        author=cfg.author_login,
        write=not getattr(args, "dry_run", False),
    )
    return cfg, k, gh


def _guarded(fn):
    from . import collect, dispatch, ghx, kube, report, runcfg, submit

    def run(args):
        try:
            return fn(args)
        except dispatch.LeaseHeld as exc:
            print(f"error: {exc}")
            return 3
        except (
            runcfg.ConfigError, submit.SubmitError, dispatch.DispatchError,
            collect.CollectError, kube.KubeError, ghx.GhError, report.ReportError, OSError,
        ) as exc:  # fmt: skip
            print(f"error: {exc}")
            return 2

    return run


def _submit(args):
    from . import submit

    cfg, k, gh = _runner(args)
    opts = {
        "arm": args.arm, "node": args.node, "anchors": args.anchors,
        "control_worldserver": args.control_worldserver, "control_dbimport": args.control_dbimport,
        "control_playerbots_prefix": args.control_playerbots_prefix,
        "control_drop_keys": args.control_drop_keys,
        "control_pin": args.control_pin, "treatment_pin": args.treatment_pin,
        "control_bridge": args.control_bridge, "treatment_bridge": args.treatment_bridge,
        "decree_pr": args.decree_pr, "dry_run": args.dry_run,
    }  # fmt: skip
    submit.submit(cfg, k, gh, args.decree, opts)
    return 0


def _stop_signal(signum, frame):
    raise KeyboardInterrupt


def _dispatch(args):
    from . import dispatch, dispatchlock

    owner = dispatchlock.owner_name(args.owner)
    path = dispatchlock.lock_path()
    if args.stop:
        return dispatchlock.stop(path, owner)
    cfg, k, _ = _runner(args)
    dispatchlock.acquire(path, owner, max_age=args.lock_max_hours * 3600)
    try:
        d = dispatch.Dispatcher(
            cfg, k, owner=owner, on_tick=lambda: dispatchlock.renew(path)
        )
        # A stop signal ends the loop cleanly so the lease is handed back at once.
        signal.signal(signal.SIGTERM, _stop_signal)
        return d.run(interval=args.interval, once=args.once, standby=args.standby)
    finally:
        dispatchlock.release(path)


def _collect(args):
    from . import collect

    cfg, k, gh = _runner(args)
    col = collect.Collector(cfg, k, gh, env=os.environ)
    col.run(post=not args.dry_run)
    return 0


def _report(args):
    from . import report

    cfg, k, gh = _runner(args)
    reporter = report.Reporter(cfg, k, gh, env=os.environ)
    reporter.run(args.batches, dry_run=args.dry_run)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="eph")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint", help="check decrees against schema v1 and its rules")
    p.add_argument("decrees", nargs="+")
    p.add_argument(
        "--anchors", help="anchors.yaml (default: data/decrees/anchors.yaml)"
    )
    p.add_argument("--schema", help="schema snapshot JSON (default: the bundled one)")
    p.add_argument("--strict", action="store_true", help="warnings fail too")
    p.set_defaults(func=_lint)
    a = sub.add_parser(
        "acts", help="print a decree's act timeline as the command rows it becomes"
    )
    a.add_argument("decree")
    a.set_defaults(func=_acts)
    q = sub.add_parser(
        "seed",
        help="in a world pod: guard, compile and apply a decree's cast and arrange",
    )
    q.add_argument("decree")
    q.add_argument(
        "--anchors", help="anchors.yaml (default: data/decrees/anchors.yaml)"
    )
    q.add_argument(
        "--dry-run", action="store_true", help="print the SQL, apply nothing"
    )
    q.set_defaults(func=_seed)
    j = sub.add_parser(
        "judge",
        help="in a world pod: run the act timeline, decide PASS/FAIL/INVALID, write the result",
    )
    j.add_argument("decree")
    j.add_argument("--anchors", help="anchors.yaml (default: decrees/anchors.yaml)")
    j.add_argument(
        "--log",
        help="the worldserver log file log assertions read (default: $EPH_LOG_FILE, else $EPH_LOGS_DIR/Module.log)",
    )
    j.set_defaults(func=_judge)
    cfg_help = "runner settings JSON (default: $EPH_CONFIG; see ephemeral/eph.config.example.json)"
    s = sub.add_parser(
        "submit", help="queue a decree as suspended Jobs; starts nothing"
    )
    s.add_argument("decree")
    s.add_argument("--config", help=cfg_help)
    s.add_argument(
        "--anchors", help="anchors.yaml (default: data/decrees/anchors.yaml)"
    )
    s.add_argument("--arm", choices=("control", "treatment", "both"), default="both")
    s.add_argument(
        "--node",
        help="a node from the config (default: the first that takes the class)",
    )
    s.add_argument(
        "--control-worldserver", help="control worldserver image, name@sha256:..."
    )
    s.add_argument(
        "--control-dbimport",
        help="refused: both arms run the live db-import (see docs/EPHEMERAL.md)",
    )
    s.add_argument(
        "--control-playerbots-prefix",
        help="key prefix of the control image's playerbots.conf.dist when it predates the "
        "rename to Playerbots.* (for example AiPlayerbot); the control arm's keys are written with it",
    )
    s.add_argument(
        "--control-drop-keys",
        help="comma-separated override keys the control image's dists predate (for example "
        "Overseer.Raid.QuorumSeats); they are removed from the control arm's override files",
    )
    s.add_argument(
        "--control-bridge",
        help="control bridge image, name@sha256:... (bridge: on decrees; the image before the fix)",
    )
    s.add_argument(
        "--treatment-bridge",
        help="treatment bridge image (default: the base realm's running bridge image)",
    )
    s.add_argument(
        "--control-pin", help="commit the control image was built from (fix presence)"
    )
    s.add_argument(
        "--treatment-pin",
        help="commit the treatment image was built from (default: the live pin)",
    )
    s.add_argument(
        "--decree-pr",
        type=int,
        help="the decree's own pull request, for results of an unmerged decree",
    )
    s.add_argument(
        "--dry-run",
        action="store_true",
        help="render and check everything, create nothing",
    )
    s.set_defaults(func=_guarded(_submit))
    dp = sub.add_parser(
        "dispatch", help="the one process that starts queued worlds, inside the budget"
    )
    dp.add_argument("--config", help=cfg_help)
    dp.add_argument("--once", action="store_true", help="one pass, then exit")
    dp.add_argument("--interval", type=int, default=15)
    dp.add_argument(
        "--standby",
        action="store_true",
        help="when another dispatcher holds the lease, wait and take over when it is "
        "released or expires instead of exiting 3 (ignored with --once)",
    )
    dp.add_argument(
        "--owner",
        help="who owns this dispatcher (default: $EPH_OWNER, else the parent pid)",
    )
    dp.add_argument(
        "--stop",
        action="store_true",
        help="stop the running dispatcher of --owner, by pid; refuses another owner's",
    )
    dp.add_argument(
        "--lock-max-hours",
        type=float,
        default=6,
        help="a lock not renewed for this long is stale and taken over",
    )
    dp.set_defaults(func=_guarded(_dispatch))
    cl = sub.add_parser(
        "collect", help="copy results, decide, post evidence, close only under the rule"
    )
    cl.add_argument("--config", help=cfg_help)
    cl.add_argument(
        "--dry-run", action="store_true", help="decide and print, post nothing"
    )
    cl.set_defaults(func=_guarded(_collect))
    rp = sub.add_parser(
        "report",
        help="post one batch's evidence to its named issue; tick one box, never close",
    )
    rp.add_argument(
        "batches",
        nargs="+",
        help="one or more six-character batch ids from eph submit",
    )
    rp.add_argument("--config", help=cfg_help)
    rp.add_argument(
        "--dry-run", action="store_true", help="print the comment and proposed box edit"
    )
    rp.set_defaults(func=_guarded(_report))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
