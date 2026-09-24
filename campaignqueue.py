"""A family's dungeon campaign queue: run A N times, then B M times (#209).

A family's campaign on its own is one dungeon keyword (the roster's
`job = 'dungeon:<keyword>'`) and one cap (`dungeon_runs_wanted` against
`dungeon_runs_done`). Nothing moved a family on to its next dungeon when a
cap was reached, so an order like "Ragefire Chasm 50 times, then Wailing
Caverns 50 times" needed a person to switch it by hand a day or more in.

THE QUEUE IS AN ORDERED LIST OF (keyword, runs) PER FAMILY, held in a table
the bridge owns (TABLE below). The bridge's queue pass starts the head entry,
advances when the leader's `dungeon_runs_done` reaches the head's count, and
returns the family to `quest` when the list is empty. This module decides;
bridge.py and map_server.py only read rows in and run the statements named
here.

PER FAMILY, KEYED BY THE ROSTER'S `family` VALUE, which is the head's name
(decree.family_label says "Zug's family" off the same key). mod-overseer runs
one run coordinator today and is moving to one per family
(quadseven/mod-overseer#555); every family's queue is advanced off its own
leader's row either way, so nothing here changes when that lands. A realm
whose roster predates the `family` column has one family, keyed ''.

PURE MODULE: no MySQL, no Discord. Rows in, decisions and sentences out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import achievements
import campaignplan
import council
import jobs
import raidrun

TABLE = "overseer_dungeon_queue"

QUEUED = "queued"
ACTIVE = "active"
DONE = "done"
CANCELLED = "cancelled"
PENDING = (QUEUED, ACTIVE)

# The source every job row the queue writes carries, so the Decree's read-back
# and the log can tell a queue advance from any other job order.
SOURCE = "overseer:queue"

# The campaign columns are SMALLINT UNSIGNED (decree.CAMPAIGN_CEILING says
# why), and an entry's count is written straight into dungeon_runs_wanted.
RUNS_CEILING = 65535

# A queue is a plan for days, not a playlist. Ten entries is more than the
# classic path has doors a family could use at one level, and a bound keeps a
# pasted paragraph from becoming a hundred rows.
MAX_ENTRIES = 10

# The key column is the roster's own `family` value, the head's name.
FAMILY_WIDTH = 32

CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_dungeon_queue ("
    " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " family VARCHAR(32) NOT NULL DEFAULT '',"
    " position SMALLINT UNSIGNED NOT NULL,"
    " keyword VARCHAR(32) NOT NULL,"
    " runs_wanted SMALLINT UNSIGNED NOT NULL,"
    " status ENUM('queued','active','done','cancelled') NOT NULL"
    " DEFAULT 'queued',"
    " source VARCHAR(64) NOT NULL DEFAULT '',"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " started_at TIMESTAMP NULL DEFAULT NULL,"
    " finished_at TIMESTAMP NULL DEFAULT NULL,"
    " PRIMARY KEY (id), KEY idx_family_status (family, status, position)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

# `source` rides along so the planner (campaignplan.py) can tell its own
# entries from an operator's order.
SELECT_PENDING_SQL = (
    "SELECT id, family, position, keyword, runs_wanted, status, source "
    "FROM overseer_dungeon_queue WHERE status IN ('queued', 'active') "
    "ORDER BY family, position, id"
)

# Setting a queue REPLACES the family's pending one: an order is the whole
# plan, never an append, so two orders cannot interleave into a third plan
# nobody gave.
CANCEL_SQL = (
    "UPDATE overseer_dungeon_queue SET status = 'cancelled', "
    "finished_at = NOW() WHERE family = %s AND status IN ('queued', 'active')"
)

INSERT_SQL = (
    "INSERT INTO overseer_dungeon_queue "
    "(family, position, keyword, runs_wanted, source) "
    "VALUES (%s, %s, %s, %s, %s)"
)

# Guarded on the status it moves FROM, so a queue replaced between the read
# and the write is not revived by a pass that read the old one.
START_SQL = (
    "UPDATE overseer_dungeon_queue SET status = 'active', started_at = NOW() "
    "WHERE id = %s AND status = 'queued'"
)
FINISH_SQL = (
    "UPDATE overseer_dungeon_queue SET status = 'done', finished_at = NOW() "
    "WHERE id = %s AND status = 'active'"
)

# What the validation reads: each member's saved level, race and map. The
# `characters` row and not the snapshot, for the reason
# map_server._fetch_council gives: a family that logged out ten minutes ago
# still has a level.
LEVEL_ROWS_SQL = (
    "SELECT name, level, race, map AS map_id FROM characters WHERE name IN (%s)"
)


def level_rows_sql(count: int) -> str:
    """LEVEL_ROWS_SQL with `count` placeholders; values are always bound."""
    return LEVEL_ROWS_SQL % ", ".join(["%s"] * max(count, 1))


@dataclass(frozen=True)
class Entry:
    keyword: str
    runs: int


@dataclass(frozen=True)
class Plan:
    """A queue order: a refusal, or the entries to write. Never both."""

    family: str
    refusal: str
    entries: tuple
    clear: bool
    says: str


@dataclass(frozen=True)
class Move:
    """One queue pass for one family.

    finish    queue id to mark done, or 0
    start     queue id to mark active once its job is written, or 0
    keyword   the dungeon job to write to every enabled member, or ""
    wanted    the cap written with it
    reset     set dungeon_runs_done back to 0, because a new entry counts
              from nothing
    quest     return every member to job=quest (the queue ran out)
    why       the sentence the bridge logs
    """

    finish: int = 0
    start: int = 0
    keyword: str = ""
    wanted: int = 0
    reset: bool = False
    quest: bool = False
    why: str = ""

    @property
    def writes(self) -> bool:
        return bool(self.finish or self.start or self.keyword or self.quest)


# --- naming a dungeon ----------------------------------------------------------


def _fold(text: str) -> str:
    text = str(text or "").lower().replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9-]+", " ", text).split())


def _names() -> dict:
    """Every way a person may name a door, folded, -> its keyword.

    The keyword itself, the keyword with spaces for hyphens, the place as
    council.keyword_place says it, and the dungeon's own name for the map's
    front door. "the" is optional everywhere, so "deadmines" and "the
    deadmines" are one name.
    """
    names: dict = {}
    for keyword in sorted(jobs.PORTAL_KEYWORDS):
        for said in (
            keyword,
            keyword.replace("-", " "),
            council.keyword_place(keyword),
        ):
            names.setdefault(_fold(said), keyword)
    for keyword, (map_id, _wing) in council.DUNGEON_KEYWORDS.items():
        if keyword in jobs.PORTAL_KEYWORDS and council.front_door(map_id) == keyword:
            names.setdefault(_fold(achievements.dungeon_name(map_id)), keyword)
    for said, keyword in list(names.items()):
        if said.startswith("the "):
            names.setdefault(said[4:], keyword)
    return names


def keyword_for(text: str) -> str | None:
    """The portal or raid keyword `text` names, or None.

    A raid is named here and nowhere in the planner's vocabulary: an order is
    the only road to one (raidrun.py).
    """
    said = _fold(text)
    if said.startswith("the "):
        said = said[4:]
    return _names().get(said) or raidrun.keyword_for(said)


def _place(keyword: str) -> str:
    """How a queue entry's door is said: a raid by name, a dungeon as council says."""
    if raidrun.is_raid(keyword):
        return raidrun.place(keyword)
    return council.keyword_place(keyword)


# --- reading an order ----------------------------------------------------------

_SPLIT = re.compile(r",|;|\bthen\b|\band\b|\bafter that\b", re.IGNORECASE)
# A count is one whole word, "50", "x50" or "50x", matched against that word
# alone: no pattern here ever scans a whole sentence for digits.
_COUNT = re.compile(r"x?(\d{1,6})x?")
_FILLER = frozenset({"run", "runs", "times", "time", "clear", "of"})

# Longer than any real order; a pasted paragraph is refused before it is read.
MAX_ORDER_CHARS = 400


def parse_entries(text: str) -> tuple:
    """(entries, refusal) from "ragefire 50, then wailing caverns 50 times".

    Each part names one door and one count, in either order. The whole order
    is refused on the first part that does not, because a queue with a hole
    in it is a different plan from the one that was asked for.
    """
    text = str(text or "")
    if len(text) > MAX_ORDER_CHARS:
        return (), "That order is %d characters; a queue order is at most %d." % (
            len(text),
            MAX_ORDER_CHARS,
        )
    parts = [p.strip() for p in _SPLIT.split(text) if p and p.strip()]
    if not parts:
        return (), (
            "Say which dungeons, and how many runs of each: "
            '"ragefire 50, then wailing 50".'
        )
    if len(parts) > MAX_ENTRIES:
        return (), "A queue holds at most %d dungeons; that order names %d." % (
            MAX_ENTRIES,
            len(parts),
        )
    entries = []
    for part in parts:
        words = _fold(part).split()
        counts = [m.group(1) for m in map(_COUNT.fullmatch, words) if m]
        if len(counts) != 1:
            return (), ('"%s" needs exactly one number: how many runs of it.' % part)
        runs = int(counts[0])
        if not 1 <= runs <= RUNS_CEILING:
            return (), (
                '"%s" asks for %d runs; a queue entry is 1 to %d runs, the '
                "campaign column's own range." % (part, runs, RUNS_CEILING)
            )
        name = " ".join(
            w for w in words if w not in _FILLER and not _COUNT.fullmatch(w)
        )
        keyword = keyword_for(name)
        if keyword is None:
            return (), (
                '"%s" is not a dungeon the overseer has a door for. The doors '
                "are: %s."
                % (
                    " ".join(name.split()),
                    ", ".join(sorted(jobs.PORTAL_KEYWORDS | jobs.RAID_KEYWORDS)),
                )
            )
        entries.append(Entry(keyword, runs))
    return tuple(entries), ""


def plan(family: str, entries: tuple, level_rows: list) -> Plan:
    """Validate a whole queue for one family against its members' rows.

    Every entry must be a door this family can use today: a known portal
    keyword, not withheld, not inside the other faction's capital, not above
    the weakest member's level, and on their continent or reachable from it.
    council.door_refusal is the one place those rules are written (#204,
    #207), the same rules the council proposes by.
    """
    if not entries:
        return Plan(family, "The queue names no dungeon.", (), False, "")
    for entry in entries:
        why = (
            raidrun.refusal(entry.keyword, entry.runs, level_rows)
            if raidrun.is_raid(entry.keyword)
            else council.door_refusal(entry.keyword, level_rows)
        )
        if why:
            return Plan(
                family,
                "Not queued: %s for %s - %s. Nothing was written."
                % (_place(entry.keyword), _family(family), why),
                (),
                False,
                "",
            )
    return Plan(
        family,
        "",
        tuple(entries),
        False,
        "Queued for %s: %s." % (_family(family), _plain(entries)),
    )


def clear(family: str) -> Plan:
    return Plan(
        family,
        "",
        (),
        True,
        "The queue for %s is cleared. The job it last wrote stays until "
        "another order changes it." % _family(family),
    )


def _family(family: str) -> str:
    return "%s's family" % family if family else "the family"


def _plain(entries) -> str:
    return ", then ".join("%s %d" % (_place(e.keyword), e.runs) for e in entries)


# --- the Discord order form ----------------------------------------------------

_ORDER = re.compile(
    r"^\s*queue\b\s*(?:for\s+)?"
    r"(?:(?P<family>[a-z]+)(?:'s)?(?:\s+family)?\s*:)?(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Order:
    """A queue order heard in the overseer's own channel.

    family  the family named before the colon, "" when none was
    text    what follows: the entries, "clear", or "" to be told the queue
    """

    family: str
    text: str

    @property
    def clear(self) -> bool:
        return _fold(self.text) in ("clear", "stop", "cancel", "empty")


def parse_order(text: str) -> Order | None:
    """ "queue Zug: ragefire 50, then wailing 50" -> Order, or None.

    Only a message that STARTS with "queue" is one. A dungeon's name inside
    an ordinary sentence is not an order, the same rule jobs.parse_order keeps.
    """
    found = _ORDER.match(str(text or ""))
    if found is None:
        return None
    return Order(
        family=(found.group("family") or ""), text=(found.group("rest") or "").strip()
    )


def pick_family(asked: str, keys: list) -> tuple:
    """(family key, refusal) for a name matched against the roster's keys."""
    if asked:
        for key in keys:
            if key.lower() == asked.lower():
                return key, ""
        return "", "%s is not a family on the roster. The families are: %s." % (
            asked,
            ", ".join(k or "(unnamed)" for k in keys) or "none",
        )
    if len(keys) == 1:
        return keys[0], ""
    return "", (
        'Name the family: "queue <family>: ragefire 50, then wailing 50". '
        "The families are: %s." % (", ".join(k or "(unnamed)" for k in keys) or "none")
    )


# --- advancing -----------------------------------------------------------------


def pending_by_family(queue_rows: list) -> dict:
    """family -> its queued and active rows, in queue order."""
    out: dict = {}
    for row in sorted(
        queue_rows or [],
        key=lambda r: (int(r.get("position") or 0), int(r.get("id") or 0)),
    ):
        if str(row.get("status") or "") in PENDING:
            out.setdefault(str(row.get("family") or ""), []).append(row)
    return out


def families(roster_rows: list) -> dict:
    """family -> {"leader": row, "names": [enabled names]} off the roster.

    The leader is the `lead = 1` row, failing that the member whose name is
    the family key (the column defaults to the head's name), failing both the
    first by name, which is the rule townslot.other_cohorts keeps. Only
    enabled rows count: a disabled character is not driven by anything.
    """
    grouped: dict = {}
    for row in roster_rows or []:
        if _flag(row, "enabled", 1) and str(row.get("name") or "").strip():
            grouped.setdefault(str(row.get("family") or "").strip(), []).append(row)
    out = {}
    for key, rows in grouped.items():
        rows = sorted(rows, key=lambda r: str(r.get("name")))
        out[key] = {
            "leader": _leader_of(key, rows),
            "names": [str(r["name"]) for r in rows],
        }
    return out


def _flag(row: dict, column: str, default: int = 0) -> bool:
    try:
        return int(row.get(column, default) or 0) == 1
    except (TypeError, ValueError):
        return False


def _leader_of(key: str, rows: list) -> dict:
    return (
        next((r for r in rows if _flag(r, "lead")), None)
        or next((r for r in rows if str(r.get("name")) == key), None)
        or rows[0]
    )


def step(rows: list, leader: dict | None) -> Move:
    """What one pass does for one family's pending rows.

    `leader` is the family's leader's roster row (job, dungeon_runs_done):
    both columns are per character and the coordinator counts against the
    leader's, so that is the row read. None or a missing count is "cannot be
    seen", and nothing is written on it.

    Advances when done reaches the head's count, writing the next entry's job
    and resetting the cap; returns the family to quest when none is left. An
    active entry whose job has been knocked off the leader's row (a relog, or
    the vendor pass evacuating a full-bagged party) is re-asserted, which is
    the queue owning the family's job while it is active.
    """
    if not rows:
        return Move(why="nothing is queued")
    head = rows[0]
    keyword = str(head["keyword"])
    runs = int(head["runs_wanted"])
    place = _place(keyword)
    if str(head["status"]) == QUEUED:
        return Move(
            start=int(head["id"]),
            keyword=keyword,
            wanted=runs,
            reset=True,
            why="starting %s, %d runs" % (place, runs),
        )
    if leader is None or leader.get("dungeon_runs_done") is None:
        return Move(why="the leader's run count cannot be read, so %s holds" % place)
    done = int(leader["dungeon_runs_done"])
    if done >= runs:
        if len(rows) > 1:
            nxt = rows[1]
            return Move(
                finish=int(head["id"]),
                start=int(nxt["id"]),
                keyword=str(nxt["keyword"]),
                wanted=int(nxt["runs_wanted"]),
                reset=True,
                why="%s is done at %d of %d; moving on to %s, %d runs"
                % (
                    place,
                    done,
                    runs,
                    _place(str(nxt["keyword"])),
                    int(nxt["runs_wanted"]),
                ),
            )
        return Move(
            finish=int(head["id"]),
            quest=True,
            why="%s is done at %d of %d and the queue is empty; back to %s"
            % (place, done, runs, jobs.DEFAULT),
        )
    want = jobs.job_for(keyword)
    if str(leader.get("job") or "").strip().lower() != want:
        return Move(
            keyword=keyword,
            wanted=runs,
            why="%s is at %d of %d but the leader is on job=%s; re-asserting %s"
            % (place, done, runs, leader.get("job") or "(none)", want),
        )
    return Move(why="%s, %d of %d" % (place, done, runs))


# --- saying it -----------------------------------------------------------------

# Who chose a planned entry, as the queue line says it. An operator's order is
# said bare: it is the queue's ordinary entry, and everything else is marked.
CHOOSERS = {
    campaignplan.SOURCE_JEV: "Jev's choice",
    campaignplan.SOURCE: "planned",
}


def chooser(row: dict) -> str:
    """ "Jev's choice", "planned", or "" for an operator's entry."""
    return CHOOSERS.get(str(row.get("source") or ""), "")


def _marked(row: dict, said: str) -> str:
    by = chooser(row)
    return "%s (%s)" % (said, by) if by else said


def progress_line(rows: list, done: int | None) -> str:
    """ "Ragefire Chasm 12 of 50, then Wailing Caverns 50", or "" when empty.

    `done` is the leader's dungeon_runs_done, which counts the ACTIVE head
    only. A head not yet started says so rather than borrowing a count that
    belongs to the campaign before it.
    """
    if not rows:
        return ""
    parts = []
    for i, row in enumerate(rows):
        place = _place(str(row["keyword"]))
        runs = int(row["runs_wanted"])
        if i == 0 and str(row["status"]) == ACTIVE and done is not None:
            said = "%s %d of %d" % (place, min(int(done), runs), runs)
        elif i == 0:
            said = "%s %d (starting)" % (place, runs)
        else:
            said = "%s %d" % (place, runs)
        parts.append(_marked(row, said))
    return ", then ".join(parts)


def view(rows: list, done: int | None, family: str = "") -> dict:
    """The queue as the site draws it: a line and its entries."""
    line = progress_line(rows, done)
    return {
        "line": ("Queue: %s." % line) if line else "",
        "done": done,
        "entries": [
            {
                "keyword": str(r["keyword"]),
                "place": _place(str(r["keyword"])),
                "runs": int(r["runs_wanted"]),
                "status": str(r["status"]),
                "by": chooser(r),
            }
            for r in rows or []
        ],
        "family": family,
    }


def views(queue_rows: list, roster_rows: list) -> dict:
    """family -> view(...) for every family on the roster or in the queue.

    Progress is read off each family's own leader, the row the coordinator
    counts against; a family with nothing queued gets an empty view, so the
    site can draw "nothing is queued" rather than guess.
    """
    pending = pending_by_family(queue_rows)
    fams = families(roster_rows)
    out = {}
    for key in sorted(set(pending) | set(fams)):
        leader = fams.get(key, {}).get("leader") or {}
        done = leader.get("dungeon_runs_done")
        out[key] = view(pending.get(key, []), None if done is None else int(done), key)
    return out
