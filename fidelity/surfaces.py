"""The overseer outputs a scenario can be replayed through (#2281).

A surface is an existing production read path, called unchanged over a
reader, plus a projection of its output into the claim vocabulary the
fixture's `expect` uses. Nothing here decides what the realm credited.
"""

from __future__ import annotations

import re

from apiv2 import chronicle

_BOSSES = re.compile(r"(\d+) of (\d+) bosses")
_CLEARED = re.compile(r" cleared ")


def run_chronicle(args: dict, reader) -> dict:
    """The Chronicle feed for `args["guilds"]`, as GET /api/v2/chronicle builds it."""
    maps = {int(k): v for k, v in (args.get("maps") or {}).items()}
    return chronicle.build(reader, list(args["guilds"]), maps, args.get("kin") or [])


def claims_chronicle(payload: dict) -> dict:
    """Per run in the feed: the boss count it tells and whether it says cleared.

    A run's `kind` is "clear" for every run that finished on its last boss,
    side bosses standing, so what the feed says to a reader is its sentence.
    """
    runs = []
    for item in payload["items"]:
        if "run" not in item:
            continue
        counted = _BOSSES.search(item["text"])
        runs.append(
            {
                "run": item["run"],
                "credited": int(counted.group(1)) if counted else None,
                "of": int(counted.group(2)) if counted else None,
                "clear": bool(_CLEARED.search(item["text"])),
            }
        )
    return {"runs": sorted(runs, key=lambda r: r["run"])}


SURFACES = {"chronicle": (run_chronicle, claims_chronicle)}
