"""GET /api/v2/zone-danger: the routing rule's current family danger lists.

The module publishes the canonical, faction-filtered result beside presence
snapshots. This endpoint reads those rows, never death records or commands.
Missing, stale and malformed samples remain unknown, not measured empty lists.
"""

from __future__ import annotations

import json

import zone_danger
from apiv2._scope import holes


def page(query: dict, ctx) -> tuple[int, dict]:
    if query:
        return 400, {"error": "no query parameters accepted"}
    rosters = ctx.families.families()
    names = [members[0] for members in rosters.values() if members]
    rows = (
        ctx.read.rows(
            "SELECT name,result,UNIX_TIMESTAMP() AS now_at FROM overseer_zone_danger "  # noqa: S608 - only generated placeholders; names are bound
            f"WHERE name IN ({holes(len(names))}) "
            "AND updated_at >= NOW() - INTERVAL 30 SECOND",
            tuple(names),
            what="overseer_zone_danger",
        )
        if names
        else []
    )
    by_name = {row["name"]: row for row in rows}
    families = []
    for family, members in rosters.items():
        name = members[0] if members else ""
        entry = {"family": family, "sampled_for": name, "status": "error"}
        row = by_name.get(name)
        if row is None:
            entry["error"] = (
                "No current routing sample. The member may be offline or the module is not reporting."
            )
        else:
            try:
                danger = zone_danger.normalize(json.loads(row["result"]))
                if int(row["now_at"]) - danger["sampled_at"] > 30:
                    raise ValueError("routing sample is stale")
                entry.update(status="online", danger=danger)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                entry["error"] = str(exc)
        families.append(entry)
    return 200, {"families": families}


ROUTES = {"/api/v2/zone-danger": page}
