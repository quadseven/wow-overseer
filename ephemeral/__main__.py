"""`python3 -m ephemeral <lint|acts|seed> ...`: the `eph` command line."""

import argparse
import json
import os
import pathlib
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
    from . import seedrun

    return seedrun.run(
        args.decree, os.environ, dry_run=args.dry_run, anchors_path=args.anchors
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="eph")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lint", help="check decrees against schema v1 and its rules")
    p.add_argument("decrees", nargs="+")
    p.add_argument("--anchors", help="anchors.yaml (default: decrees/anchors.yaml)")
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
    q.add_argument("--anchors", help="anchors.yaml (default: decrees/anchors.yaml)")
    q.add_argument(
        "--dry-run", action="store_true", help="print the SQL, apply nothing"
    )
    q.set_defaults(func=_seed)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
