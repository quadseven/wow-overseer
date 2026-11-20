"""Pure event, clip-window, and retention rules for major family moments."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Mapping

PRE_ROLL = timedelta(seconds=30)
TAIL = timedelta(seconds=15)
EQUIP_WAIT = timedelta(minutes=5)
MAX_CLIPS = 200
MAX_AGE = timedelta(days=30)
COUNT_ENV = "CLIP_MAX_COUNT"
AGE_ENV = "CLIP_MAX_AGE_DAYS"


def retention_caps(environ: Mapping) -> tuple[int, timedelta, list[str]]:
    """(max_count, max_age, lines) from the environment.

    A missing value uses the default silently; an invalid one (not a whole
    number of at least one) uses the default and adds one line to log."""
    lines: list[str] = []
    values = []
    for name, default in ((COUNT_ENV, MAX_CLIPS), (AGE_ENV, MAX_AGE.days)):
        raw = environ.get(name)
        if raw is None or not str(raw).strip():
            values.append(default)
            continue
        try:
            value = int(str(raw).strip())
        except ValueError:
            value = 0
        if value < 1:
            lines.append(
                "clip retention: %s=%r is not a whole number of 1 or more, "
                "using %d" % (name, raw, default)
            )
            value = default
        values.append(value)
    return values[0], timedelta(days=values[1]), lines


def trigger_kind(event: Mapping) -> str | None:
    """Return the clip kind for a qualifying, already-scoped event row.

    The caller scopes event rows to family members and family guilds, and
    annotates first kills/clears from the same family history used by the
    Chronicle. This function applies only the stable significance rules.
    """
    kind = event.get("kind")
    if kind == "item_loot":
        if event.get("family_member") and event.get("family_guild"):
            try:
                if int(event.get("quality") or 0) >= 4:
                    return "loot"
            except (TypeError, ValueError):
                return None
        return None
    if kind == "boss_kill" and event.get("family_member") and event.get("first_kill"):
        return "boss_kill"
    if kind == "clear" and event.get("family_member") and event.get("first_clear"):
        return "clear"
    if kind == "level_up" and event.get("family_member"):
        try:
            if int(event.get("level") or 0) == 60:
                return "level_60"
        except (TypeError, ValueError):
            return None
    return None


def clip_window(
    event_at: datetime,
    *,
    equip_at: datetime | None = None,
    pre_roll: timedelta = PRE_ROLL,
    equip_wait: timedelta = EQUIP_WAIT,
    tail: timedelta = TAIL,
) -> tuple[datetime, datetime]:
    """Return the saved interval, extending loot through a timely matching equip.

    `equip_at` must already refer to the same item instance as the loot event.
    An equip before the loot, or later than the bounded wait, cannot extend the
    clip; in both cases the loot event plus its tail is the honest fallback.
    """
    end_event = event_at
    if equip_at is not None and event_at <= equip_at <= event_at + equip_wait:
        end_event = equip_at
    return event_at - pre_roll, end_event + tail


def retain(
    clips: list[Mapping],
    *,
    now: datetime,
    max_age: timedelta = MAX_AGE,
    max_count: int = MAX_CLIPS,
) -> list[Mapping]:
    """Return the newest clips within both retention bounds, newest first."""
    if max_count <= 0 or max_age.total_seconds() < 0:
        return []
    cutoff = now - max_age
    eligible = [clip for clip in clips if clip["saved_at"] >= cutoff]
    eligible.sort(
        key=lambda clip: (clip["saved_at"], str(clip.get("id", ""))),
        reverse=True,
    )
    return eligible[:max_count]
