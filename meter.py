"""The family meter: what the `meter` probe says, made safe for the page.

mod-overseer's `meter` probe (OverseerMeterScript) answers for a whole family
from any one member: damage, healing and damage taken per member over the
current fight or the last one, per-second rates, and each member's threat on
the family leader's target. The site asks one member per family and passes
the answer through this module, which keeps only the fields it knows and
coerces their types, so a malformed row from the worldserver cannot reach the
browser as anything but an error line.

Pure: dicts in, dicts out. The probe round trip lives in map_server.
"""

from __future__ import annotations

_COUNTS = ("damage", "dps", "healing", "hps", "taken", "threat_pct")


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float = -1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize(result) -> dict:
    """The probe's JSON object, kept to known fields with known types.

    Raises ValueError when it is not a meter answer at all, so the caller
    reports an error rather than an empty fight.
    """
    if not isinstance(result, dict) or not isinstance(result.get("members"), list):
        raise ValueError("not a meter answer")
    members = []
    for row in result["members"]:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        member: dict = {"name": str(row["name"])}
        for key in _COUNTS:
            member[key] = _int(row.get(key), -1 if key == "threat_pct" else 0)
        member["threat"] = _float(row.get("threat"))
        members.append(member)
    # Highest damage first, the way every meter reads.
    members.sort(key=lambda m: (-m["damage"], m["name"]))
    return {
        "live": bool(result.get("live")),
        "seconds": max(1, _int(result.get("seconds"), 1)),
        "target": str(result.get("target") or ""),
        "members": members,
    }


def family_entry(family: str, response: dict) -> dict:
    """One family's block for /api/meter, from one probe response."""
    entry = {"family": family, "status": response.get("status", "error")}
    if entry["status"] == "online":
        entry.update(response["meter"])
    else:
        entry["error"] = str(response.get("error") or "no answer")
        entry["members"] = []
    return entry


def payload(families: list, responses: dict, sampled_at: int) -> dict:
    """The /api/meter body: every family, in roster order."""
    return {
        "sampled_at": sampled_at,
        "families": [family_entry(name, responses.get(name, {})) for name in families],
    }
