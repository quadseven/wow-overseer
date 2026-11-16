"""The realm maintenance notice: what whoever takes the worldserver down writes first.

The notice lives as a JSON annotation on the worldserver Deployment, so it is
written in the same API the scale goes through, survives the pod being gone,
and needs no new secret to read. `realm-maintenance up` moves it to a second
annotation (the last notice) so a watcher can say why the realm restarted.

    {reason, who, started_at, expected_back}   the open notice
    {... , ended_at}                           the last notice

`who` is an agent or role label, never a person's name. Times are UTC, ISO
8601 with a trailing Z.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

NOTICE_KEY = "realm-maintenance-notice"
LAST_KEY = "realm-maintenance-last"
MAX_ETA = timedelta(hours=24)
_ETA = re.compile(r"^(\d+)([smh])$")
_UNIT = {"s": 1, "m": 60, "h": 3600}
_REQUIRED = ("reason", "who", "started_at", "expected_back")


def parse_eta(text: str) -> timedelta:
    """`90s`, `20m` or `2h` as a timedelta; anything else raises ValueError."""
    match = _ETA.match((text or "").strip())
    if not match:
        raise ValueError("eta must look like 90s, 20m or 2h")
    eta = timedelta(seconds=int(match.group(1)) * _UNIT[match.group(2)])
    if eta <= timedelta(0):
        raise ValueError("eta must be positive")
    if eta > MAX_ETA:
        raise ValueError("eta may not exceed 24h")
    return eta


def iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


def new_notice(reason: str, who: str, now: datetime, eta: timedelta) -> dict:
    return {
        "reason": reason,
        "who": who,
        "started_at": iso(now),
        "expected_back": iso(now + eta),
    }


def parse_notice(raw: str | None) -> dict | None:
    """The notice an annotation holds, or None when absent or malformed."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or any(k not in data for k in _REQUIRED):
        return None
    if (
        parse_time(data["started_at"]) is None
        or parse_time(data["expected_back"]) is None
    ):
        return None
    return data


def retire(notice: dict, now: datetime) -> dict:
    return {**notice, "ended_at": iso(now)}
