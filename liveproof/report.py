"""List tickets proven in BOTH of the last two verdict files; close on --apply.

A single proof can be a batch artifact, so a ticket qualifies only when the
newest two verdict files (from liveproof/run.py) both say `proven` for it.
By default this prints the gh commands it would run (a dry run). Only
--apply runs them, comment first and close second, and it skips an issue
that is already closed. See docs/LIVEPROOF.md (#2125).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

PATTERN = "verdicts-*.json"


def latest_two(directory: Path | str):
    """The two newest verdict files, oldest first, or None when fewer exist."""
    files = sorted(Path(directory).glob(PATTERN), key=lambda p: p.name)
    return files[-2:] if len(files) >= 2 else None


def _proven(doc: dict) -> dict:
    return {
        (r["repo"], r["ticket"]): r
        for r in doc.get("results", [])
        if r.get("verdict") == "proven"
    }


def proven_in_both(prev: dict, last: dict) -> list[dict]:
    before, after = _proven(prev), _proven(last)
    return [
        {
            "ticket": ticket,
            "repo": repo,
            "prev_run": prev.get("run_at", ""),
            "last_run": last.get("run_at", ""),
            "prev_evidence": before[(repo, ticket)]["evidence"],
            "evidence": after[(repo, ticket)]["evidence"],
        }
        for repo, ticket in sorted(set(before) & set(after))
    ]


def _plain(text: object) -> str:
    """ASCII with no mention syntax: evidence comes from the database."""
    return str(text).encode("ascii", "replace").decode("ascii").replace("@", "")


def comment_body(item: dict) -> str:
    return (
        "Live proof passed in two consecutive runs "
        f"({_plain(item['prev_run'])} and {_plain(item['last_run'])}).\n\n"
        f"Evidence, latest run: {_plain(item['evidence'])}\n"
        f"Evidence, previous run: {_plain(item['prev_evidence'])}\n\n"
        "Closing on that proof. Reopen if the behavior regresses.\n\n"
        "-- liveproof"
    )


def commands(item: dict) -> list[list[str]]:
    base = [item["ticket"], "-R", item["repo"]]
    return [
        ["gh", "issue", "comment", *base, "--body", comment_body(item)],
        ["gh", "issue", "close", *base],
    ]


def _show(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def _state(item: dict) -> str:
    res = subprocess.run(
        [
            "gh",
            "issue",
            "view",
            item["ticket"],
            "-R",
            item["repo"],
            "--json",
            "state",
            "--jq",
            ".state",
        ],
        capture_output=True,
        text=True,
    )
    return res.stdout.strip() if res.returncode == 0 else "UNKNOWN"


def apply(item: dict) -> bool:
    if _state(item) != "OPEN":
        print(f"skip {item['repo']}#{item['ticket']}: not open")
        return False
    comment, close = commands(item)
    if subprocess.run(comment, capture_output=True, text=True).returncode != 0:
        print(f"comment failed on {item['repo']}#{item['ticket']}; not closing")
        return False
    if subprocess.run(close, capture_output=True, text=True).returncode != 0:
        print(f"close failed on {item['repo']}#{item['ticket']}")
        return False
    print(f"closed {item['repo']}#{item['ticket']}")
    return True


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=str(here / "verdicts"))
    ap.add_argument(
        "--apply",
        action="store_true",
        help="run the gh comment and close commands (default: print them)",
    )
    args = ap.parse_args(argv)

    pair = latest_two(args.dir)
    if pair is None:
        print("liveproof report: fewer than two verdict files; nothing to compare")
        return 0
    prev, last = (json.loads(p.read_text()) for p in pair)
    items = proven_in_both(prev, last)
    print(f"runs compared: {pair[0].name} and {pair[1].name}")
    if not items:
        print("No ticket was proven in both runs.")
        return 0
    print(f"{len(items)} ticket(s) proven in both runs.")
    if not args.apply:
        print(
            "Dry run: nothing is commented or closed. Commands that --apply would run:"
        )
        for item in items:
            for cmd in commands(item):
                print(_show(cmd))
        return 0
    for item in items:
        apply(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
