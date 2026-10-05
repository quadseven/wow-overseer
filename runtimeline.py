"""The run timeline: how each family's recent dungeon runs went, step by step.

WHY IT EXISTS. The worldserver logs enough that its container log rotates
within minutes, so "why did the last Ragefire run fail" could only be answered
from an external log search. mod-overseer now writes each run's phase changes
and decisions to `overseer_dungeon_run_event` (mod-overseer#616), one row each,
and this module turns those rows into the Dungeons tab's timeline.

WHAT IT DOES NOT DO IS DECIDE. Every sentence here is the module's row, or a
title built from the row's own numbers. The page prints these strings and
turns a tone name into a class; it composes nothing.

HOW ROWS BECOME RUNS. A run row does not exist until somebody is on the
instance map, so the first phases of a run carry run id 0. The rows are split
into runs instead by what they say: a phase row out of IDLE opens a run, a
change of campaign or run number opens one, and a row after an `ended` or
`released` row opens one, except the phase row back to IDLE that closes it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import council

try:
    from zoneinfo import ZoneInfo

    _ZONE = ZoneInfo("America/New_York")
    _ZONE_LABEL = "ET"
except Exception:  # noqa: BLE001 - no tz database in the image: UTC, and say so
    _ZONE = timezone.utc
    _ZONE_LABEL = "UTC"

# How many runs each family shows, newest first. The current one and the last
# few are what a failure is diagnosed from; more is scrolling.
RUNS_PER_FAMILY = 4
# How far back the read goes. The module keeps 14 days; the tab needs hours.
WINDOW_HOURS = 48
# A cap on the read, so a runaway writer cannot make the tab heavy.
ROW_LIMIT = 2000

# Outcomes that are the run going as planned. Anything else that ends a run is
# a failure of some kind and is drawn as one.
_GOOD_OUTCOMES = {"complete"}
_PLAIN_OUTCOMES = {"left", "emptied"}

# Tones are role names the stylesheet knows, never colours.
_EVENT_TONES = {
    "boss": "good",
    "complete": "good",
    "dc_on_all": "good",
    "stalled": "bad",
    "released": "bad",
    "dc_on_refused": "warn",
    "dc_not_accepted": "warn",
    "brain_not_moving": "warn",
    "busy_ceiling": "warn",
    "dc_skip": "warn",
    "staging_rearm": "warn",
    # mod-overseer never stops a campaign on failures: it recovers, and says
    # which recovery and which answer to a repeated staging take-back.
    "recovery": "warn",
    "staging_stall": "warn",
    "reset_retry": "warn",
    "evacuated": "warn",
}


# The coordinator's phase names (mod_overseer.cpp, DungeonRunPhase) as a reader
# says them (#567). A phase this table does not know is shown lower-cased with
# its underscores as spaces, never dropped.
PHASES = {
    "IDLE": "waiting",
    "RESET": "resetting the dungeon",
    "REPAIRING": "repairing",
    "GATHERING": "walking to the door",
    "BARRIER": "waiting for everyone at the door",
    "ENTER": "going in together",
    "STAGED_INSIDE": "everyone inside",
    "CLEARING": "clearing",
    "EXIT": "walking out",
    "RECOVERING": "recovering",
}

# How a run ended, from the outcome word the module writes (#567). Same
# fallback as PHASES.
OUTCOMES = {
    "complete": "cleared",
    "left": "walked out",
    "emptied": "the dungeon was already empty",
    "wipe": "wiped",
    "split_failed": "the family split",
    "staging_failed": "the family never gathered at the door",
    "reset_failed": "the dungeon would not reset",
    "evacuated": "pulled out",
}


def _words(table: dict, key: str) -> str:
    key = str(key or "").strip()
    return table.get(key) or key.lower().replace("_", " ")


def phase_line(detail: str) -> str:
    """ "IDLE -> RESET (gnomeregan, ...)" as "now resetting the dungeon"."""
    head = detail.split(" (", 1)[0]
    if " -> " not in head:
        return detail
    return "now " + _words(PHASES, head.split(" -> ", 1)[1])


def ended_line(detail: str) -> str:
    """ "split_failed: the family is split ..." with the outcome in words."""
    outcome, _, reason = str(detail or "").partition(":")
    said = _words(OUTCOMES, outcome)
    reason = reason.strip().replace("BARRIER", "the wait at the door")
    return "%s: %s" % (said, reason) if reason else said


def _outcome(detail: str) -> str:
    """The outcome word of an `ended` row, whose detail is "outcome: reason"."""
    return detail.split(":", 1)[0].strip()


def _tone(row: dict) -> str:
    kind = row.get("kind") or ""
    if kind == "ended":
        outcome = _outcome(row.get("detail") or "")
        if outcome in _GOOD_OUTCOMES:
            return "good"
        return "plain" if outcome in _PLAIN_OUTCOMES else "bad"
    if kind == "phase":
        return "phase"
    return _EVENT_TONES.get(kind, "plain")


def _starts_new_run(run: dict | None, row: dict) -> bool:
    if run is None:
        return True
    kind = row.get("kind") or ""
    detail = row.get("detail") or ""
    if kind == "phase" and detail.startswith("IDLE ->"):
        return True
    key = (int(row.get("campaign_id") or 0), int(row.get("run_number") or 0))
    if key != (0, 0) and run["key"] != (0, 0) and key != run["key"]:
        return True
    if run["ended"]:
        # The phase change back to IDLE is the end of the same run.
        return not (kind == "phase" and row.get("phase") == "IDLE")
    return False


def split_runs(rows: list[dict]) -> list[dict]:
    """One family's rows, oldest first, split into runs, oldest first."""
    runs: list[dict] = []
    run: dict | None = None
    for row in rows:
        if _starts_new_run(run, row):
            run = {"key": (0, 0), "ended": None, "rows": []}
            runs.append(run)
        key = (int(row.get("campaign_id") or 0), int(row.get("run_number") or 0))
        if run["key"] == (0, 0) and key != (0, 0):
            run["key"] = key
        run["rows"].append(row)
        if row.get("kind") in ("ended", "released") and run["ended"] is None:
            run["ended"] = row
    return runs


def _clock(age_seconds, now: datetime) -> str:
    """When a row was written, in the operator's clock, from its age.

    The age comes from the database's own NOW(), so a database clock in a
    different zone from this process's cannot shift the times shown.
    """
    if age_seconds is None:
        return ""
    at = now - timedelta(seconds=int(age_seconds))
    return at.astimezone(_ZONE).strftime("%H:%M:%S")


def _ago(age_seconds) -> str:
    if age_seconds is None:
        return "at an unknown time"
    seconds = int(age_seconds)
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return "%d %s%s ago" % (count, unit, "" if count == 1 else "s")
    return "just now"


def _title(run: dict) -> str:
    """ "Gnomeregan, run 9" (#567).

    The campaign id and the run row id are the module's record numbers and
    stay out of the title; the run number counts this campaign's runs, which
    is the number the home banner's queue line counts too.
    """
    _campaign, number = run["key"]
    portal = next((r.get("portal") for r in run["rows"] if r.get("portal")), "")
    place = council.keyword_place(portal) if portal else "A dungeon"
    return "%s, run %d" % (place, number) if number else place


def _summary(run: dict, latest: bool) -> tuple[str, str]:
    """The line under a run's title, and its tone."""
    ended = run["ended"]
    last = run["rows"][-1]
    if ended is not None:
        age = _ago(ended.get("age_seconds"))
        if ended.get("kind") == "released":
            return "let go %s: %s" % (age, ended.get("detail") or ""), "bad"
        return "ended %s: %s" % (age, ended_line(ended.get("detail") or "")), _tone(
            ended
        )
    phase = _words(PHASES, last.get("phase") or "IDLE")
    if latest:
        return (
            "under way, now %s (last change %s)"
            % (phase, _ago(last.get("age_seconds"))),
            "live",
        )
    return (
        "no end was recorded; the last step was %s, %s. A server restart "
        "ends a run without recording it" % (_ago(last.get("age_seconds")), phase)
    ), "plain"


def _event(row: dict, now: datetime) -> dict:
    who = ("%s: " % row["character_name"]) if row.get("character_name") else ""
    said = row.get("detail") or row.get("kind") or ""
    if row.get("kind") == "phase":
        said = phase_line(said)
    elif row.get("kind") == "ended":
        said = ended_line(said)
    return {
        "at": _clock(row.get("age_seconds"), now),
        "line": who + said,
        "tone": _tone(row),
    }


def _run_card(run: dict, latest: bool, now: datetime) -> dict:
    line, tone = _summary(run, latest=latest)
    return {
        "title": _title(run),
        "line": line,
        "tone": tone,
        "open": latest,
        "events": [_event(r, now) for r in run["rows"]],
    }


def _family_block(family: str, rows: list[dict], now: datetime, limit: int) -> dict:
    shown = split_runs(rows)[-limit:][::-1]
    drawn = [_run_card(run, index == 0, now) for index, run in enumerate(shown)]
    if drawn:
        head = "The last %d run%s, newest first." % (
            len(drawn),
            "" if len(drawn) == 1 else "s",
        )
    else:
        head = "No run in the last %d hours." % WINDOW_HOURS
    return {"title": family, "line": head, "runs": drawn}


def build_run_timeline(
    rows: list[dict],
    families: dict[str, list[str]],
    now: datetime | None = None,
    present: bool = True,
    runs_per_family: int = RUNS_PER_FAMILY,
) -> dict:
    """The timeline payload for every family.

    `rows` are overseer_dungeon_run_event rows with an `age_seconds` column,
    in any order. `families` maps a family to its members, from the roster;
    a family with no rows still gets a line saying so. `present` is False when
    the table does not exist yet.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if not present:
        return {
            # overseer_dungeon_run_event does not exist yet on this realm.
            "line": "No run timeline yet: this realm's world server does not "
            "record runs step by step until it is updated.",
            "families": [],
        }

    by_family: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda r: int(r.get("id") or 0)):
        by_family.setdefault(row.get("family") or "", []).append(row)

    names = list(families) + sorted(f for f in by_family if f and f not in families)
    return {
        "line": "Each run step by step, as the world server recorded it, times "
        "in %s. Kept for 14 days." % _ZONE_LABEL,
        "families": [
            _family_block(f, by_family.get(f, []), now, runs_per_family) for f in names
        ],
    }
