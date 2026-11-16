"""Command line: `python -m forge build` and `python -m forge check-classes`."""

from __future__ import annotations

import argparse
import os
import pathlib
import shlex
import sys

from forge import build, classes, scrub


def _check_classes(args: argparse.Namespace) -> int:
    found = classes.load_classes(pathlib.Path(args.classes))
    tables = [
        t.strip()
        for t in pathlib.Path(args.tables).read_text(encoding="utf-8").splitlines()
        if t.strip()
    ]
    missing = classes.unclassified(tables, found)
    gone = classes.stale(tables, found)
    for name in missing:
        print(f"unclassified table: {name}", file=sys.stderr)
    for name in gone:
        print(f"class for a table that no longer exists: {name}", file=sys.stderr)
    return 1 if missing or gone else 0


def _lean_conf(args: argparse.Namespace) -> int:
    del args
    for key, value in scrub.LEAN_PLAYERBOTS_CONF.items():
        print(f"{key} = {value}")
    return 0


def _build(args: argparse.Namespace) -> int:
    registry = os.environ.get("FORGE_REGISTRY", "")
    prefix = os.environ.get("FORGE_BACKUP_PREFIX", "")
    if not prefix:
        print(
            "FORGE_BACKUP_PREFIX is not set; see data/forge/config.example.env",
            file=sys.stderr,
        )
        return 2
    cfg = build.Config(
        template_class=args.template_class,
        backup_dir=pathlib.Path(args.backup_dir),
        workdir=pathlib.Path(args.workdir),
        registry=registry,
        backup_prefix=prefix,
        db_import_cmd=tuple(shlex.split(args.db_import_cmd)),
        auth_dump=pathlib.Path(args.auth_dump) if args.auth_dump else None,
    )
    steps = build.plan(cfg, classes.load_classes())
    if args.dry_run:
        for step in steps:
            print(step.name)
        return 0
    build.execute(steps, build.SubprocessRunner(cfg))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-classes", help="fail when a table has no class")
    check.add_argument(
        "--tables", required=True, help="file with one table name per line"
    )
    check.add_argument("--classes", default=str(classes.DEFAULT_PATH))
    check.set_defaults(func=_check_classes)

    conf = sub.add_parser(
        "lean-conf", help="print the playerbots config a lean world must carry"
    )
    conf.set_defaults(func=_lean_conf)

    make = sub.add_parser("build", help="build one template from the newest backup")
    make.add_argument(
        "--class", dest="template_class", choices=build.CLASSES, required=True
    )
    make.add_argument(
        "--backup-dir", required=True, help="read-only mount of the backup share"
    )
    make.add_argument(
        "--workdir", required=True, help="scratch directory for the datadir and layer"
    )
    make.add_argument(
        "--auth-dump",
        help="optional auth dump to restore and scrub; default synthesises accounts",
    )
    make.add_argument(
        "--db-import-cmd",
        default="dbimport",
        help="command that builds the world and auth schemas (default: dbimport)",
    )
    make.add_argument(
        "--dry-run", action="store_true", help="print the step names and stop"
    )
    make.set_defaults(func=_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
