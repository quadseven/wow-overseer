"""The clip ledger: which events earn a clip request, as rows for overseer_clip.

Pure, like eventclips: rows in, rows out, no database and no clock reads. The
map server reads the realm, calls plan_requests, and writes what comes back.
The policy (what is major, how wide the window is, what retention keeps) stays
in eventclips; this module is the wiring around it.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Callable, Iterable, Mapping
from urllib.parse import quote

import achievements
import eventclips
import eye
import places

log = logging.getLogger(__name__)

STATES = ("pending", "cutting", "ready", "no_view", "failed", "expired", "deleted")

# The request channel and the clip ledger. This module writes requests; the
# stream agent polls pending rows and writes the outcome back. event_key is
# unique, so a restarted scan cannot write an event twice.
DDL = (
    "CREATE TABLE IF NOT EXISTS overseer_clip ("
    " id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,"
    " kind VARCHAR(16) NOT NULL,"
    " `character` VARCHAR(24) NOT NULL,"
    " stream_path VARCHAR(64) NOT NULL DEFAULT '',"
    " event_key VARCHAR(96) NOT NULL,"
    " event_at DATETIME NOT NULL,"
    " window_start DATETIME NOT NULL,"
    " window_end DATETIME NOT NULL,"
    " state VARCHAR(12) NOT NULL DEFAULT 'pending',"
    " file_name VARCHAR(128) NULL,"
    " detail TEXT NULL,"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    "   ON UPDATE CURRENT_TIMESTAMP,"
    " UNIQUE KEY uq_event_key (event_key),"
    " KEY idx_state_window (state, window_end)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
)

LOOT_QUALITY_KEY = "subject_quality"
# overseer_event.first_seen is the module's flush time, so it trails the real
# event by up to one flush. The window starts that much earlier.
FLUSH_INTERVAL = timedelta(seconds=5)
# How much recent video the stream agent keeps; older events cannot be cut.
AGENT_BUFFER = timedelta(minutes=10)
# How old a late event may be and still get a failed row. The site reads its
# recent candidates over the same span; anything older is history.
LATE_HORIZON = timedelta(minutes=20)
# The longest a scan looks back, however long ago the last one completed.
MAX_LATE_HORIZON = timedelta(hours=24)


def scan_horizon(now: datetime, last_scan: datetime | None) -> timedelta:
    """How far back this scan looks for events to record.

    LATE_HORIZON in steady state; back to the last completed scan when that is
    longer; MAX_LATE_HORIZON at most. No last scan (the first scan after a
    process start) looks back the maximum, so a gap cannot drop events.
    """
    if last_scan is None:
        return MAX_LATE_HORIZON
    return min(max(LATE_HORIZON, now - last_scan), MAX_LATE_HORIZON)


# The Chronicle's own "earliest qualifying row" rule, so a first here is the
# same first the Chronicle shows.
earliest = achievements._earliest


NOT_IN_A_RUN = "subject not streamed and not in a run"
NO_STREAMED_IN_RUN = "no streamed family member in the run"
RUN_AMBIGUOUS = "run ambiguous"


# A view is live while its clock is no older than this: the bound past which
# the eye read calls the same clock stale, so the two agree on a view.
VIEW_LIVE_SECONDS = eye.STALE_AFTER_SECONDS


def view_live(seen, segment, now, within=VIEW_LIVE_SECONDS) -> bool:
    """Is a streamed view live, by the cutter's clocks (epoch seconds)?

    `segment` is when the view's recorder wrote its newest segment and `seen`
    when the cutter's poll last named the view. A view with a segment clock is
    judged by it alone: a recorder that still runs over a picture that stopped
    moving is polled every time and is not live. A view with no clock at all
    was never named by the cutter and is not live.
    """
    clock = seen if segment is None else segment
    return clock is not None and now - clock <= within


def _with_view(detail, extra):
    return "%s; %s" % (detail, extra) if detail else extra


class Views:
    """Which live view films an event, by fixed decision 1: the subject's own,
    else the leader of the run the subject is in, else a streamed family member
    in that run (roster order), else none.

    The run is the Chronicle's own join, achievements.in_run: the same map and
    the event time inside the run's window, which runs to `now` for a run still
    in progress. Who was in the run is the Chronicle's presence rule too: the
    leader, plus anyone with an event inside it (achievements._who_was_there).

    Two families can be inside one dungeon at once, so a run belongs to an
    event only when the run's leader is in the subject's family, and presence
    is limited to the leader's family. When the subject's family is unknown,
    one matching run is taken and several are ambiguous: no guess.

    `live_of(name, path)` says whether a streamed view is live right now. With
    it, a streamed tier whose view is down is passed over for the first tier
    in the same order whose view is live. When no tier reads live, the first
    streamed tier is still asked, as it is without `live_of`: the read is of
    this moment, not of the event's, and its clocks are empty after a restart,
    so the cutter, which holds the footage, keeps the last word.
    """

    def __init__(self, path_of, roster, runs, rows, now, families=None, live_of=None):
        self.path_of = path_of
        self.live_of = live_of
        self.roster = list(roster)
        self.runs = sorted(runs, key=lambda r: (r["started_at"], r["id"]))
        self.rows = [r for r in rows if r.get("map") is not None]
        self.now = now
        self.families = [frozenset(names) for names in (families or {}).values()]
        # The tiers the last pick tried: (tier, name, path), path "" for a
        # view that was not there. Read by plan_requests for a suppressed row.
        self.tried = []

    def _family_of(self, name):
        for names in self.families:
            if name in names:
                return names
        return None

    def _matches(self, who, at, map_id):
        """The runs holding this event: (runs, ambiguous)."""
        if map_id is None:
            return [], False
        found = [
            run
            for run in self.runs
            if achievements.in_run(run, at, int(map_id), self.now)
        ]
        family = self._family_of(who)
        if family is not None:
            return [r for r in found if r["leader_name"] in family][:1], False
        return found, len(found) > 1

    def _present(self, run):
        family = self._family_of(run["leader_name"])
        return {
            r["character_name"]
            for r in self.rows
            if (family is None or r["character_name"] in family)
            and achievements.in_run(run, r["first_seen"], int(r["map"]), self.now)
        }

    def _tiers(self, who, leader, members):
        """(tier, name) in the order the views are tried."""
        yield "subject", who
        if leader is None:
            return
        if leader != who:
            yield "leader", leader
        present = set(members)
        for name in self.roster:
            if name in present and name not in (who, leader):
                yield "party member", name

    def pick(self, who, leader, members, detail, reason=NOT_IN_A_RUN):
        """(path, detail) for `who`; `leader` is None when no run is known."""
        self.tried = []
        down = None  # the first streamed tier, when its view was not live
        for tier, name in self._tiers(who, leader, members):
            path = self.path_of(name)
            self.tried.append((tier, name, path))
            if not path:
                continue
            note = (
                detail
                if tier == "subject"
                else _with_view(detail, "view: %s (%s)" % (name, tier))
            )
            if self.live_of is None or self.live_of(name, path):
                return path, note
            down = down or (path, note)
        if down:
            return down
        return "", _with_view(detail, reason if leader is None else NO_STREAMED_IN_RUN)

    def for_event(self, who, at, map_id, detail):
        found, ambiguous = self._matches(who, at, map_id)
        if ambiguous:
            return self.pick(who, None, (), detail, RUN_AMBIGUOUS)
        if not found:
            return self.pick(who, None, (), detail)
        run = found[0]
        return self.pick(who, run["leader_name"], self._present(run), detail)

    def for_run(self, who, members, detail):
        """A cleared run, already resolved. Its card lists everyone the
        tables place inside, so the members are cut to the leader's family."""
        family = self._family_of(who)
        if family is not None:
            members = [m for m in members if m in family]
        return self.pick(who, who, members, detail)


def _request(key, kind, who, views, at, window, detail, map_id=None, members=None):
    start, end = window
    if members is None:
        path, detail = views.for_event(who, at, map_id, detail)
    else:
        path, detail = views.for_run(who, members, detail)
    return {
        "event_key": key,
        "kind": kind,
        "character": who,
        "stream_path": path,
        "event_at": at,
        "window_start": start,
        "window_end": end,
        "state": "pending",
        "detail": detail,
        "tried": list(views.tried),
    }


def _window(at, equip_at=None):
    return eventclips.clip_window(
        at, equip_at=equip_at, pre_roll=eventclips.PRE_ROLL + FLUSH_INTERVAL
    )


def _equip_at(loot_row, rows):
    """The first equip of this exact item by this character, or None."""
    guid = loot_row.get("item_guid")
    if not guid:
        return None
    seen = [
        r["first_seen"]
        for r in rows
        if r.get("kind") == "item_equip"
        and r.get("item_guid") == guid
        and r.get("character_name") == loot_row["character_name"]
        and r["first_seen"] >= loot_row["first_seen"]
    ]
    return min(seen) if seen else None


def _loot_requests(rows, guilds, now, views):
    out = []
    for row in rows:
        if row.get("kind") != "item_loot":
            continue
        member = row.get("guild") in guilds
        kind = eventclips.trigger_kind(
            {
                "kind": "item_loot",
                "family_member": member,
                "family_guild": member,
                "quality": row.get(LOOT_QUALITY_KEY),
            }
        )
        if kind is None:
            continue
        at = row["first_seen"]
        equip = _equip_at(row, rows)
        if equip is None and now < at + eventclips.EQUIP_WAIT:
            continue  # the window end is not known yet
        out.append(
            _request(
                "loot:%s" % row["id"],
                kind,
                row["character_name"],
                views,
                at,
                _window(at, equip),
                row.get("subject_name") or "",
                row.get("map"),
            )
        )
    return out


def boss_key(subject_id, family) -> str:
    """The ledger key of one family's first kill of a boss. The ledger and
    the Chronicle feed both build it here."""
    return "boss_kill:%s:%s" % (subject_id, family)


def clear_key(map_id, family) -> str:
    """The ledger key of one family's first clear of a dungeon. The ledger
    and the run card both build it here."""
    return "clear:%s:%s" % (map_id, family)


def level_key(character) -> str:
    """The ledger key of a character's level 60 moment."""
    return "level_60:%s" % character


def first_kills(rows, roster, path_of):
    """The earliest family kill of each boss. Rows tied on the earliest time
    go to a streamed member, then to roster order, so the pick never depends
    on row order."""
    order = {name: i for i, name in enumerate(roster)}
    by_boss = {}
    for r in rows:
        if r.get("kind") == "boss_kill" and r["character_name"] in order:
            by_boss.setdefault(r["subject_id"], []).append(r)
    picks = []
    for group in by_boss.values():
        first = earliest(group, "first_seen")["first_seen"]
        tied = [r for r in group if r["first_seen"] == first]
        picks.append(
            min(
                tied,
                key=lambda r: (
                    not path_of(r["character_name"]),
                    order[r["character_name"]],
                ),
            )
        )
    return picks


# The family of a call without `families`: the whole roster counts as one.
ROSTER_FAMILY = "roster"


def _event_requests(rows, roster, views, families=None):
    out = []
    groups = dict(families) if families else {ROSTER_FAMILY: roster}
    for family, members in groups.items():
        for row in first_kills(rows, list(members), views.path_of):
            at = row["first_seen"]
            kind = eventclips.trigger_kind(
                {"kind": "boss_kill", "family_member": True, "first_kill": True}
            )
            out.append(
                _request(
                    boss_key(row["subject_id"], family),
                    kind,
                    row["character_name"],
                    views,
                    at,
                    _window(at),
                    row.get("subject_name") or "",
                    row.get("map"),
                )
            )
    for row in rows:
        if row.get("kind") != "level_up" or row["character_name"] not in roster:
            continue
        kind = eventclips.trigger_kind(
            {"kind": "level_up", "family_member": True, "level": row.get("level")}
        )
        if kind is None:
            continue
        at = row["first_seen"]
        who = row["character_name"]
        out.append(
            _request(
                level_key(who),
                kind,
                who,
                views,
                at,
                _window(at),
                "",
                row.get("map"),
            )
        )
    return out


def _clear_requests(runs, roster, views, families=None):
    out = []
    groups = dict(families) if families else {ROSTER_FAMILY: roster}
    by_key = {}
    for run in runs:
        for family, members in groups.items():
            if run["leader"] in members:
                by_key.setdefault((run["map_id"], family), []).append(run)
    for (map_id, family), group in by_key.items():
        run = earliest(group, "at")
        kind = eventclips.trigger_kind(
            {"kind": "clear", "family_member": True, "first_clear": True}
        )
        out.append(
            _request(
                clear_key(map_id, family),
                kind,
                run["leader"],
                views,
                run["at"],
                _window(run["at"]),
                run.get("dungeon") or "",
                members=run.get("members") or (),
            )
        )
    return out


def expired_reasons(
    rows: Iterable[Mapping],
    *,
    now: datetime,
    max_age: timedelta = eventclips.MAX_AGE,
    max_count: int = eventclips.MAX_CLIPS,
) -> dict:
    """{id: reason} for ready ledger rows that fall outside the retention bounds.

    The reason names the cap that fired: the age cap when the row is older
    than it, else the count cap. Marks only: the caller sets state to
    expired. No file is deleted here or there. Rows in any other state hold
    no saved clip, so they neither count toward the cap nor expire.
    """
    ready = [
        {"id": r["id"], "saved_at": r["created_at"]}
        for r in rows
        if r.get("state") == "ready"
    ]
    kept = {
        c["id"]
        for c in eventclips.retain(ready, now=now, max_age=max_age, max_count=max_count)
    }
    cutoff = now - max_age
    out = {}
    for c in ready:
        if c["id"] in kept:
            continue
        if c["saved_at"] < cutoff:
            out[c["id"]] = "expired: age cap (%d days)" % max_age.days
        else:
            out[c["id"]] = "expired: count cap (%d)" % max_count
    return out


def plan_requests(
    *,
    loot_rows: Iterable[Mapping],
    event_rows: Iterable[Mapping],
    cleared_runs: Iterable[Mapping],
    family_guilds: Iterable[str],
    roster: Iterable[str],
    now: datetime,
    existing_keys: Iterable[str],
    path_of: Callable[[str], str],
    runs: Iterable[Mapping] = (),
    families: Mapping[str, Iterable[str]] | None = None,
    late_horizon: timedelta = LATE_HORIZON,
    live_of: Callable[[str, str], bool] | None = None,
) -> list[dict]:
    """The ledger rows to insert now, oldest event first.

    `late_horizon` is how old an event may be and still get a failed row
    (see scan_horizon).

    `runs` are the dungeon runs, open or ended, that an event may sit in; an
    event row names its map as `map`. `families` maps each family to its
    members; a run is matched to an event within the subject's family only.

    `live_of(name, path)` says whether a streamed view is live; a view that is
    down gives way to a live one in the same run (see Views).
    """
    guilds = frozenset(family_guilds)
    order = list(roster)
    names = frozenset(order)
    loot_rows, event_rows = list(loot_rows), list(event_rows)
    views = Views(
        path_of, order, list(runs), loot_rows + event_rows, now, families, live_of
    )
    rows = _loot_requests(loot_rows, guilds, now, views)
    rows += _event_requests(event_rows, order, views, families)
    rows += _clear_requests(list(cleared_runs), names, views, families)
    rows.sort(key=lambda r: r["event_at"])
    seen = set(existing_keys)
    out = []
    for row in rows:
        if row["event_key"] in seen:
            continue
        if row["window_start"] < now - AGENT_BUFFER:
            # Footage older than the agent's buffer no longer exists to be
            # cut. A recent event is recorded as failed, so no cutter is
            # offered it; an event older than late_horizon is history that
            # only decides what is a first, and is not recorded.
            if row["event_at"] < now - late_horizon:
                continue
            seen.add(row["event_key"])
            row["state"] = "failed"
            row["detail"] = "; ".join(p for p in (row["detail"], LATE_DETAIL) if p)
        else:
            seen.add(row["event_key"])
            if not row["stream_path"]:
                row["state"] = "no_view"
        if row["state"] != "no_view":
            row.pop("tried", None)
        out.append(row)
    return out


def suppression_line(
    row: Mapping, reads: Callable[[str, str], str] | None = None
) -> str:
    """One log line for a suppressed (no_view) row: the tiers tried, who was
    asked at each, and why none gave a view, so the cause is readable from the
    log and not only from the Chronicle note. `reads(name, path)` adds the
    liveness read (poll and frame age) for EVERY tier, including one with no
    streamed path: a suppressed row's tiers all lack a path, so the read of the
    path that tier would have broadcast on is what shows the view was down."""
    tiers = []
    for tier, name, path in row.get("tried") or ():
        read = reads(name, path) if reads else ""
        shown = "path %s" % path if path else "not streamed"
        tiers.append(
            "%s %s: %s%s" % (tier, name, shown, " (%s)" % read if read else "")
        )
    return "clip suppressed: %s (%s) for %s at %s; tried %s; %s" % (
        row.get("event_key", "?"),
        row["kind"],
        row["character"],
        row["event_at"],
        "; ".join(tiers) or "no tier",
        row.get("detail") or NO_VIEW_LINE,
    )


# --- timing out rows the agent never finished ----------------------------

# The agent keeps AGENT_BUFFER of video; a pending row this long past its window
# end can no longer be cut, so it is declared failed (buffer plus 5 minutes).
PENDING_TIMEOUT = timedelta(minutes=15)
PENDING_FAILED_DETAIL = "no cutter picked this up before the footage aged out"
LATE_DETAIL = "seen after the footage left the buffer"
# A cutting row nobody has touched for this long lost its cutter mid-cut.
CUTTING_TIMEOUT = timedelta(minutes=10)
CUTTING_FAILED_DETAIL = "cutter went silent"

_STALE_SELECT = (
    "SELECT id, state, window_end, updated_at FROM overseer_clip"
    " WHERE state IN ('pending', 'cutting')"
)
# Each update names the state it replaces, so a row the agent moved on since
# the read (ready, failed, ...) matches nothing and is left alone. The reason
# is appended to the detail, so the planner's view text stays in front of it.
_TO_FAILED = (
    "UPDATE overseer_clip SET state = %s, detail = "
    "CONCAT_WS('; ', NULLIF(detail, ''), NULLIF(%s, ''))"
    " WHERE id = %s AND state = %s"
)


def stale_changes(rows: Iterable[Mapping], *, now: datetime) -> list[dict]:
    """The state changes owed to rows that sat too long: pending past its
    window end by more than PENDING_TIMEOUT and cutting not updated for more
    than CUTTING_TIMEOUT both become failed, each with its own detail."""
    out = []
    for r in rows:
        if r.get("state") == "pending" and r["window_end"] < now - PENDING_TIMEOUT:
            out.append(
                {
                    "id": r["id"],
                    "from": "pending",
                    "to": "failed",
                    "detail": PENDING_FAILED_DETAIL,
                }
            )
        elif r.get("state") == "cutting" and r["updated_at"] < now - CUTTING_TIMEOUT:
            out.append(
                {
                    "id": r["id"],
                    "from": "cutting",
                    "to": "failed",
                    "detail": CUTTING_FAILED_DETAIL,
                }
            )
    return out


def time_out(cur, *, now: datetime) -> dict:
    """Read the in-flight rows and time out the stale ones through `cur`.

    Returns how many rows each change actually took (a conditional update that
    matched nothing is not counted)."""
    cur.execute(_STALE_SELECT)
    counts = {"no_view": 0, "failed": 0}
    for change in stale_changes(cur.fetchall(), now=now):
        cur.execute(
            _TO_FAILED,
            (change["to"], change["detail"], change["id"], change["from"]),
        )
        counts[change["to"]] += 1 if cur.rowcount else 0
    return counts


# --- removing the files of expired rows ----------------------------------

_EXPIRED_SELECT = "SELECT id, file_name FROM overseer_clip WHERE state = 'expired'"
_TO_DELETED = (
    "UPDATE overseer_clip SET state = 'deleted',"
    " detail = CONCAT_WS('; ', NULLIF(detail, ''), NULLIF(%s, ''))"
    " WHERE id = %s AND state = 'expired'"
)
FILE_MISSING_DETAIL = "file was already missing"


def delete_expired(cur, root: str) -> int:
    """Remove each expired clip and its poster, then mark the row deleted.

    A missing file, or a stored name that is not one plain file name, still
    ends in deleted, with a note. A file that cannot be removed for another
    reason leaves its row expired, logs one warning, and the pass goes on.
    Returns how many rows the update took.
    """
    cur.execute(_EXPIRED_SELECT)
    done = 0
    for r in cur.fetchall():
        note, error = _remove_expired_files(root, r.get("file_name") or "")
        if error:
            log.warning(
                "expired clip %s: files not removed, row stays expired: %s",
                r["id"],
                error.strerror or error,
            )
            continue
        cur.execute(_TO_DELETED, (note, r["id"]))
        done += 1 if cur.rowcount else 0
    return done


def _remove_expired_files(root: str, name: str) -> tuple[str, OSError | None]:
    if not name or name != os.path.basename(name) or name.startswith("."):
        return FILE_MISSING_DETAIL, None
    paths = [name]
    poster = poster_name(name)
    if poster:
        paths.append(poster)
    note = FILE_MISSING_DETAIL
    for index, file_name in enumerate(paths):
        try:
            os.unlink(os.path.join(root, file_name))
        except FileNotFoundError:
            continue
        except OSError as exc:
            return note, exc
        if index == 0:
            note = ""
    return note, None


def _count(value) -> int:
    """One tick count as a number. `time_out` answers its count per new state
    ({"no_view": n, "failed": n}), and those add up; a missing count is 0."""
    if isinstance(value, dict):
        return sum(int(v or 0) for v in value.values())
    return int(value or 0)


def tick_line(scan, swept) -> str:
    """The one log line for a clip tick, or "" for a tick that did nothing.

    `scan` is what the scan answered (None when it failed) and `swept` what
    the sweeps answered. A count either side left out reads as zero, so the
    scan with no roster and a sweep with no clip folder need no special case.
    Both sides carry `timed_out` as `time_out` answers it, a dict per state.
    """
    scan_counts = scan if isinstance(scan, dict) else {}
    swept = swept if isinstance(swept, dict) else {}
    planned = _count(scan_counts.get("written"))
    expired = _count(scan_counts.get("expired"))
    timed_out = _count(scan_counts.get("timed_out")) + _count(swept.get("timed_out"))
    deleted = _count(swept.get("deleted"))
    partial = _count(swept.get("partial"))
    if not (planned or expired or timed_out or deleted or partial):
        return ""
    tail = "timed out %d, files deleted %d, partial uploads removed %d" % (
        timed_out,
        deleted,
        partial,
    )
    if not isinstance(scan, dict):
        return "clip sweep after a failed scan: " + tail
    return "clip scan: planned %d, expired %d, %s" % (planned, expired, tail)


# --- reading the ledger back out: the shelf and the story links ----------

CLIPS_PATH = "/clips/"
NO_VIEW_LINE = "No live view was up, so no clip was saved."
FAILED_LINE = "No clip was saved."
SHELF_EMPTY = "No clips have been saved yet."
SHELF_LIMIT = 100
MISSED_LIMIT = 1000


def clip_url(file_name: str) -> str:
    """The path a saved clip is served at, mount-relative (the page adds the
    mount). The name is quoted, so a stored name cannot add a path segment."""
    return CLIPS_PATH + quote(file_name, safe="")


def poster_name(file_name: str) -> str | None:
    """The JPEG frame name saved beside an MP4 clip, or None for another name."""
    if not file_name or not file_name.lower().endswith(".mp4"):
        return None
    return file_name[:-4] + "-poster.jpg"


def loot_event_ids(rows: Iterable[Mapping]) -> list[int]:
    """The event ids needed to enrich ready loot clips, in ledger order."""
    found = set()
    for row in rows:
        if row.get("kind") != "loot" or row.get("state") != "ready":
            continue
        if not row.get("file_name"):
            continue
        match = re.fullmatch(r"loot:(\d+)", str(row.get("event_key") or ""))
        if match:
            found.add(int(match.group(1)))
    return sorted(found)


def _loot_event_id(row: Mapping) -> int | None:
    match = re.fullmatch(r"loot:(\d+)", str(row.get("event_key") or ""))
    return int(match.group(1)) if match else None


def item_entries(event_rows: Iterable[Mapping]) -> list[int]:
    """The distinct item entries in the shelf's matching loot events."""
    return sorted(
        {
            int(row["subject_id"])
            for row in event_rows
            if row.get("kind") == "item_loot" and row.get("subject_id")
        }
    )


def run_context_window(
    event_rows: Iterable[Mapping],
) -> tuple[list[int], datetime | None, datetime | None]:
    """(instance maps, earliest event, latest event) to bound the run read."""
    events = [
        row
        for row in event_rows
        if row.get("kind") == "item_loot" and places.is_instance(row.get("map"))
    ]
    times = [_as_datetime(row.get("first_seen")) for row in events]
    times = [at for at in times if at is not None]
    maps = sorted({int(row["map"]) for row in events if row.get("map") is not None})
    if not maps or not times:
        return [], None, None
    return maps, min(times), max(times)


def _as_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _loot_item(event: Mapping, templates: Mapping, icons: Mapping) -> dict:
    entry = int(event.get("subject_id") or 0)
    template = templates.get(entry) or {}
    quality = template.get("quality", template.get("Quality"))
    if quality is None:
        quality = event.get("subject_quality")
    display = template.get("displayid")
    return {
        "entry": entry,
        "name": template.get("name")
        or template.get("item_name")
        or event.get("subject_name")
        or "",
        "quality": quality,
        "icon": icons.get(display) if display is not None else None,
    }


def _loot_context(event: Mapping, runs: Iterable[Mapping], zones: Mapping) -> str:
    map_id = event.get("map")
    if map_id is None:
        return ""
    map_id = int(map_id)
    if not places.is_instance(map_id):
        zone = zones.get(int(event.get("zone") or 0))
        return places.zone_display(zone) if zone else places.map_name(map_id)

    place = places.map_name(map_id)
    at = _as_datetime(event.get("first_seen"))
    matches = []
    if at is not None:
        for run in runs:
            start = _as_datetime(run.get("started_at"))
            end = _as_datetime(run.get("ended_at"))
            if (
                int(run.get("map_id") or 0) == map_id
                and start is not None
                and start <= at
                and (end is None or at <= end)
            ):
                matches.append(run)
    context = place
    if len(matches) == 1:
        context += " run %s" % matches[0]["id"]
    source = str(event.get("source") or "").strip()
    if source:
        context += ", " + source
    return context


def _iso(t) -> str | None:
    return t.isoformat() if isinstance(t, datetime) else (t or None)


_VIEW_NOTE = re.compile(r"view: ([A-Za-z]{2,12}) \((leader|party member)\)")
# What a story says under a clip filmed from another member's view: whose
# view it is and which tier of the view rule that member was.
VIEW_LINE = "Filmed from the view of %s (%s)."


def _other_view(row: Mapping):
    """(member, tier) when the clip is from another member's view, else None."""
    # The planner writes the marker at the start of a "; " part. Any other
    # text in the detail, such as a cutter's note, is never read for it.
    for part in (row.get("detail") or "").split("; "):
        found = _VIEW_NOTE.match(part)
        if found:
            return found.group(1), found.group(2)
    return None


def view_owner(row: Mapping) -> str:
    """Whose eyes a clip shows: the member the detail names, else the subject."""
    other = _other_view(row)
    return other[0] if other else row["character"]


SUBJECT_KINDS = ("loot", "boss_kill")


def subject(row: Mapping) -> str:
    """The item of a loot clip or the boss of a boss first kill, or "".

    The planner writes the event's subject name as the first part of the
    detail; a view marker or a later note is never taken for it.
    """
    if row.get("kind") not in SUBJECT_KINDS:
        return ""
    first = (row.get("detail") or "").split("; ")[0]
    return "" if _VIEW_NOTE.match(first) else first.strip()


def failed_line(row: Mapping) -> str:
    """The note for a failed row: its recorded reason, without the planner's
    view text (the "view:" parts of the detail)."""
    parts = [
        p
        for p in (row.get("detail") or "").split("; ")
        if p.strip() and not _VIEW_NOTE.match(p)
    ]
    if not parts:
        return FAILED_LINE
    return "%s: %s." % (FAILED_LINE[:-1], "; ".join(parts).rstrip(". "))


MISSED_STATES = ("no_view", "failed")


def missed(rows: Iterable[Mapping]) -> list:
    """The moments that left no clip, counted per event day, newest day first.

    A no_view row had no live view up; a failed row was recorded but not cut.
    Each is counted, never listed as a card: [{day, no_view, failed}]. A row
    with no event time has no day and is not counted."""
    days: dict = {}
    for r in rows:
        state, at = r.get("state"), _iso(r.get("event_at"))
        if state in MISSED_STATES and at:
            days.setdefault(str(at)[:10], dict.fromkeys(MISSED_STATES, 0))[state] += 1
    return [{"day": day, **days[day]} for day in sorted(days, reverse=True)]


def repeats(rows: Iterable[Mapping]) -> dict:
    """Where each ready clip stands among repeats of its item: {id: (nth, of)}.

    Two drops of one item by one character are two real moments that read as a
    duplicate. Clips of the same kind, character and subject are numbered oldest
    first, so a card can say "2 of 2". A clip with no subject is never counted."""
    groups: dict = {}
    for r in rows:
        if r.get("state") == "ready" and r.get("file_name") and subject(r):
            key = (r.get("kind"), r.get("character"), subject(r))
            groups.setdefault(key, []).append(r)
    out: dict = {}
    for group in groups.values():
        group.sort(key=lambda r: (str(_iso(r.get("event_at")) or ""), r["id"]))
        for n, r in enumerate(group, 1):
            out[r["id"]] = (n, len(group))
    return out


def shelf(
    rows: Iterable[Mapping],
    *,
    event_rows: Iterable[Mapping] = (),
    item_rows: Iterable[Mapping] = (),
    run_rows: Iterable[Mapping] = (),
    icons: Mapping | None = None,
    zones: Mapping | None = None,
) -> dict:
    """The /api/clips payload: ready rows with a file, newest event first, and
    the moments missed per day (`missed`). A clip of an item its character
    caught more than once carries `nth` and `of`. Loot event and item rows add
    the item data and the event's dungeon or zone context."""
    rows = list(rows)
    run_rows = list(run_rows)
    again = repeats(rows)
    ready = [r for r in rows if r.get("state") == "ready" and r.get("file_name")]
    ready.sort(
        key=lambda r: (str(_iso(r.get("event_at")) or ""), r["id"]), reverse=True
    )
    events = {int(row["id"]): row for row in event_rows if row.get("id") is not None}
    templates = {
        int(row["entry"]): row for row in item_rows if row.get("entry") is not None
    }
    icons = icons or {}
    zones = zones or {}
    clips = []
    for row in ready[:SHELF_LIMIT]:
        event_id = _loot_event_id(row)
        event = events.get(event_id) if event_id is not None else None
        item = (
            _loot_item(event, templates, icons)
            if event and event.get("subject_id")
            else row.get("item")
        )
        context = _loot_context(event, run_rows, zones) if event else row.get("context")
        poster = poster_name(row["file_name"])
        clip = {
            "id": row["id"],
            "kind": row["kind"],
            "character": row["character"],
            "view_owner": view_owner(row),
            "subject": subject(row),
            "at": _iso(row.get("event_at")),
            "url": clip_url(row["file_name"]),
        }
        if poster:
            clip["poster"] = clip_url(poster)
        if row["id"] in again and again[row["id"]][1] > 1:
            clip.update(nth=again[row["id"]][0], of=again[row["id"]][1])
        if item:
            clip["item"] = item
        if context:
            clip["context"] = context
        clips.append(clip)
    return {
        "clips": clips,
        "missed": missed(rows),
        "empty": SHELF_EMPTY,
    }


def link(row: Mapping | None) -> dict:
    """What a story or timeline entry adds for its event's ledger row.

    A ready row with a file adds `clip` (url and kind, plus `view_note` when
    the clip was filmed from another member's view: it names that member and
    the tier, leader or party member). A no_view row adds
    `clip_note`, saying no live view was up. A failed row adds `clip_note`
    with its recorded reason. Any other state, or no row at all, adds
    nothing: the entry says nothing about clips.
    """
    if not row:
        return {}
    if row.get("state") == "ready" and row.get("file_name"):
        clip = {"url": clip_url(row["file_name"]), "kind": row["kind"]}
        other = _other_view(row)
        if other:
            clip["view_note"] = VIEW_LINE % other
        return {"clip": clip}
    if row.get("state") == "no_view":
        return {"clip_note": NO_VIEW_LINE}
    if row.get("state") == "failed":
        return {"clip_note": failed_line(row)}
    return {}
