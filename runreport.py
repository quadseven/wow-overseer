"""The report every ended dungeon run leaves, for Discord and the family page.

WHY IT EXISTS (mod-overseer#152). A dungeon run already writes its row
(`overseer_dungeon_run`, #144) and its events (`loot_won`, `boss_kill`, ...,
#971), and the module joins the two in the view `overseer_dungeon_run_summary`.
Nothing read that view, so a run ended and nobody heard how it went. A match
ends with a report; so does a run now.

ONE QUERY, ONE BUILDER, TWO READERS. The bridge posts the report to Discord
when a run ends and the map server shows it on the family page's run cards.
Both run the SQL below and hand the rows to `build`, and the Discord text is
`render(build(...))`, so the two cannot show different numbers for one run id.

WHAT IS COUNTED, AND FROM WHICH ROWS.

  loot      every `loot_won` row of the run, one line each, with the item's
            quality from the world's item_template. Nothing else is loot.
  bosses    `boss_kill` rows, one per creature however many members saw it.
  upgrades  `item_equip` rows for an item the same member WON IN THIS RUN.
            item_equip is a periodic re-scan of worn gear (recap.py says why),
            so an equip row inside the window alone would list everything the
            group walked in wearing. An item won and then worn is an upgrade.
  quests    `quest_reward` rows: quests turned in during the run.
  deaths    `overseer_death` rows of the leader and members inside the run's
            window, each with what killed it. overseer_event's `death` kind
            has no killer and is coalesced per hour, so it is not used.

A WIPE IS NEVER A QUIET SUCCESS. The outcome is the run row's own word. A run
whose outcome is `wipe` says so on its first line and lists its deaths, and
says "none recorded" when the death table holds none, rather than printing an
empty report that reads like a clean clear.

Pure: rows in, a dict and text out. No pymysql: `read` takes a fetch
function, which the bridge (bridge._read_run_report) and the map server
(map_server._run_reports) each make from their own connection.
"""

from __future__ import annotations

import achievements
from armory import QUALITY_NAMES

# The marker that a run's report reached Discord, written only AFTER Discord
# accepted the message (the house rule: persist after the side effect). The
# primary key is what makes "one message per run" hold across ticks: a run
# with a row here is never posted again.
CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_dungeon_run_report ("
    " run_id INT UNSIGNED NOT NULL,"
    " message_id BIGINT UNSIGNED NOT NULL DEFAULT 0,"
    " outcome VARCHAR(16) NOT NULL DEFAULT '',"
    " posted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " PRIMARY KEY (run_id)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)
MARK_SQL = (
    "INSERT IGNORE INTO overseer_dungeon_run_report (run_id, message_id, outcome) "
    "VALUES (%s, %s, %s)"
)

# How far back an ended run is still owed a report. A bridge restart inside
# this window still posts the run; older runs (the history before this
# shipped, or a run whose post kept failing for an hour) are not posted, so a
# first start does not flood the channel with every run on record.
OWED_MINUTES = 60
# At most this many reports per tick, oldest first.
OWED_LIMIT = 5

PENDING_SQL = (
    "SELECT r.id FROM overseer_dungeon_run r "
    "LEFT JOIN overseer_dungeon_run_report p ON p.run_id = r.id "
    "WHERE r.state = 'ended' AND r.ended_at > NOW() - INTERVAL %s MINUTE "
    "AND p.run_id IS NULL ORDER BY r.ended_at, r.id LIMIT %s"
)

RUN_SQL = (
    "SELECT id, leader_name, members, map_id, run_number, state, outcome, "
    "ended_reason, started_at, ended_at, "
    "TIMESTAMPDIFF(SECOND, started_at, COALESCE(ended_at, NOW())) AS duration_seconds "
    "FROM overseer_dungeon_run WHERE id = %s"
)

RUNS_SQL = (
    "SELECT id, leader_name, members, map_id, run_number, state, outcome, "
    "ended_reason, started_at, ended_at, "
    "TIMESTAMPDIFF(SECOND, started_at, COALESCE(ended_at, NOW())) AS duration_seconds "
    "FROM overseer_dungeon_run WHERE id IN ({holes})"
)

# The summary view, with each looted item's quality. Ordered so a report reads
# in the order things happened.
EVENTS_SQL = (
    "SELECT s.character_name, s.kind, s.subject_id, s.subject_name, s.detail, "
    "s.occurrences, it.Quality AS quality "
    "FROM overseer_dungeon_run_summary s "
    "LEFT JOIN acore_world.item_template it "
    "ON s.kind = 'loot_won' AND it.entry = s.subject_id "
    "WHERE s.run_id = %s ORDER BY s.first_seen, s.character_name, s.subject_id"
)

EVENTS_MANY_SQL = (
    "SELECT s.run_id, s.character_name, s.kind, s.subject_id, s.subject_name, "
    "s.detail, s.occurrences, it.Quality AS quality "
    "FROM overseer_dungeon_run_summary s "
    "LEFT JOIN acore_world.item_template it "
    "ON s.kind = 'loot_won' AND it.entry = s.subject_id "
    "WHERE s.run_id IN ({holes}) ORDER BY s.first_seen, s.character_name, s.subject_id"
)

# Deaths of the run's members inside its window; {holes} is one %s per name.
DEATHS_SQL = (
    "SELECT character_name, killer_name FROM overseer_death "
    "WHERE character_name IN ({holes}) AND created_at >= %s AND created_at <= %s "
    "ORDER BY id"
)

DEATHS_MANY_SQL = (
    "SELECT character_name, killer_name, created_at FROM overseer_death "
    "WHERE character_name IN ({holes}) AND created_at >= %s AND created_at <= %s "
    "ORDER BY id"
)

# The supervisor who oversaw this run, from the queue entry that launched it.
# Matches the run's leader_name (family head) to the queue's family, and the
# run's map_id to the queue's keyword via dungeonpath.PORTAL_MAPS.
SUPERVISOR_SQL = (
    "SELECT q.supervisor FROM overseer_dungeon_queue q "
    "WHERE q.family = %s AND q.supervisor <> '' "
    "ORDER BY q.id DESC LIMIT 1"
)


def members(run: dict) -> list[str]:
    """The leader, then each member, once each, in the order the row has them."""
    names: list[str] = []
    for name in [run.get("leader_name") or ""] + str(run.get("members") or "").split(
        ","
    ):
        name = name.strip()
        if name and name not in names:
            names.append(name)
    return names


def deaths_query(run: dict) -> tuple[str, tuple] | None:
    """The deaths read for this run, or None for a run with no one in it."""
    names = members(run)
    if not names or run.get("started_at") is None:
        return None
    ended = run.get("ended_at") or run["started_at"]
    holes = ", ".join(["%s"] * len(names))
    return DEATHS_SQL.format(holes=holes), (*names, run["started_at"], ended)


def outcome(run: dict) -> str:
    """The run row's own outcome word; `ended` when it wrote none."""
    word = str(run.get("outcome") or "").strip()
    return word or ("ended" if run.get("state") == "ended" else "under way")


def _quality(row: dict) -> str:
    q = row.get("quality")
    return QUALITY_NAMES.get(int(q), "unknown") if q is not None else "unknown"


def _by_member(names: list[str], items: list[dict]) -> list[dict]:
    """Group `items` by their `member`, roster order first, strangers last."""
    order = list(names) + sorted({i["member"] for i in items} - set(names))
    return [
        {"member": n, "items": [i for i in items if i["member"] == n]}
        for n in order
        if any(i["member"] == n for i in items)
    ]


def _unique(items: list) -> list:
    """`items` with repeats dropped, first sighting kept."""
    out: list = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _of_kind(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e.get("kind") == kind]


def _subject(e: dict, fallback: str) -> str:
    return e.get("subject_name") or "%s %s" % (fallback, e.get("subject_id"))


def _loot(events: list[dict]) -> list[dict]:
    """One entry per loot_won row, never merged: each row is an item won."""
    return [
        {
            "member": e.get("character_name") or "",
            "item": _subject(e, "item"),
            "entry": int(e.get("subject_id") or 0),
            "quality": _quality(e),
            "detail": e.get("detail") or "",
        }
        for e in _of_kind(events, "loot_won")
    ]


def _bosses(events: list[dict]) -> list[str]:
    return _unique([_subject(e, "creature") for e in _of_kind(events, "boss_kill")])


def _upgrades(events: list[dict], loot: list[dict]) -> list[dict]:
    """item_equip rows for an item the same member won in this run."""
    won = {(i["member"], i["entry"]) for i in loot}
    return _unique(
        [
            {"member": e.get("character_name") or "", "item": _subject(e, "item")}
            for e in _of_kind(events, "item_equip")
            if (e.get("character_name") or "", int(e.get("subject_id") or 0)) in won
        ]
    )


def _quests(events: list[dict]) -> list[dict]:
    return _unique(
        [
            {
                "member": e.get("character_name") or "",
                "item": e.get("subject_name") or "",
            }
            for e in _of_kind(events, "quest_reward")
        ]
    )


def _deaths(deaths: list[dict]) -> list[dict]:
    return [
        {
            "member": d.get("character_name") or "",
            "item": d.get("killer_name") or "unknown",
        }
        for d in deaths
    ]


def _identity(run: dict, map_name: str, supervisor: str = "") -> dict:
    """The run row's own facts, as the report heading reads them."""
    seconds = run.get("duration_seconds")
    word = outcome(run)
    return {
        "run_id": int(run.get("id") or 0),
        "run_number": int(run.get("run_number") or 0),
        "leader": run.get("leader_name") or "",
        "map_id": int(run.get("map_id") or 0),
        "map_name": map_name or "map %s" % (run.get("map_id") or 0),
        "ended": run.get("state") == "ended",
        "outcome": word,
        "wipe": word == "wipe",
        "reason": run.get("ended_reason") or "",
        "duration_seconds": int(seconds) if seconds is not None else None,
        "supervisor": supervisor,
    }


def build(
    run: dict,
    events: list[dict],
    deaths: list[dict],
    map_name: str = "",
    supervisor: str = "",
) -> dict:
    """The report for one run, from RUN_SQL's row, EVENTS_SQL's rows and
    DEATHS_SQL's rows. Everything the page draws and Discord prints is here."""
    names = members(run)
    loot = _loot(events)
    report = _identity(run, map_name, supervisor)
    report["members"] = names
    report["bosses"] = _bosses(events)
    for key, items in (
        ("loot", loot),
        ("death", _deaths(deaths)),
        ("upgrade", _upgrades(events, loot)),
        ("quest", _quests(events)),
    ):
        report[key if key == "loot" else key + "s"] = _by_member(names, items)
        report[key + "_count"] = len(items)
    return report


def read(fetch, run_id: int) -> dict | None:
    """The report for `run_id`, through `fetch(sql, params) -> rows`, or None
    when the run row is gone. The one place both readers run the queries."""
    rows = fetch(RUN_SQL, (run_id,))
    if not rows:
        return None
    run = rows[0]
    events = fetch(EVENTS_SQL, (run_id,))
    asked = deaths_query(run)
    deaths = fetch(*asked) if asked else []
    # Fetch the supervisor from the queue entry that launched this run.
    supervisor = ""
    leader = run.get("leader_name")
    if leader:
        sup_rows = fetch(SUPERVISOR_SQL, (leader,))
        if sup_rows:
            supervisor = sup_rows[0].get("supervisor") or ""
    return build(
        run,
        events,
        deaths,
        achievements.dungeon_name(int(run.get("map_id") or 0)),
        supervisor,
    )


def _deaths_by_run(fetch, runs_by_id: dict[int, dict]) -> dict[int, list[dict]]:
    """Fetch deaths for a batch of runs in one query and filter per run window."""
    windows: list[tuple[int, set[str], object, object]] = []
    all_names: list[str] = []
    seen_names: set[str] = set()
    for run_id, run in runs_by_id.items():
        names = members(run)
        start = run.get("started_at")
        if not names or start is None:
            continue
        end = run.get("ended_at") or start
        windows.append((run_id, set(names), start, end))
        for name in names:
            if name not in seen_names:
                seen_names.add(name)
                all_names.append(name)
    if not windows:
        return {}
    min_start = min(w[2] for w in windows)
    max_end = max(w[3] for w in windows)
    holes = ", ".join(["%s"] * len(all_names))
    death_rows = fetch(
        DEATHS_MANY_SQL.format(holes=holes), (*all_names, min_start, max_end)
    )
    out: dict[int, list[dict]] = {}
    for run_id, name_set, start, end in windows:
        out[run_id] = [
            d
            for d in death_rows
            if d.get("character_name") in name_set
            and d.get("created_at") is not None
            and start <= d["created_at"] <= end
        ]
    return out


def read_many(fetch, run_ids) -> dict[int, dict]:
    """Read reports for many run ids in at most three batched SQL queries."""
    ids = list(dict.fromkeys(int(r) for r in run_ids))
    if not ids:
        return {}
    holes = ", ".join(["%s"] * len(ids))
    run_rows = fetch(RUNS_SQL.format(holes=holes), tuple(ids))
    if not run_rows:
        return {}
    runs_by_id = {int(r["id"]): r for r in run_rows}
    found_ids = [run_id for run_id in ids if run_id in runs_by_id]
    event_holes = ", ".join(["%s"] * len(found_ids))
    event_rows = fetch(EVENTS_MANY_SQL.format(holes=event_holes), tuple(found_ids))
    events_by_run: dict[int, list[dict]] = {run_id: [] for run_id in found_ids}
    for row in event_rows:
        rid = int(row["run_id"])
        if rid in events_by_run:
            events_by_run[rid].append(row)
    deaths_by_run = _deaths_by_run(fetch, {i: runs_by_id[i] for i in found_ids})
    return {
        run_id: build(
            runs_by_id[run_id],
            events_by_run[run_id],
            deaths_by_run.get(run_id, []),
            achievements.dungeon_name(int(runs_by_id[run_id].get("map_id") or 0)),
        )
        for run_id in found_ids
    }


def card(report: dict) -> dict:
    """What a family page run card carries: the run id, the outcome and the
    same lines Discord prints, plus the counts."""
    return {
        "run_id": report["run_id"],
        "outcome": report["outcome"],
        "wipe": report["wipe"],
        "lines": lines(report),
        "counts": {
            "bosses": len(report["bosses"]),
            "deaths": report["death_count"],
            "loot": report["loot_count"],
            "upgrades": report["upgrade_count"],
            "quests": report["quest_count"],
        },
    }


def duration(seconds: int | None) -> str:
    if seconds is None:
        return "duration not recorded"
    minutes, secs = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return "%dh %02dm" % (hours, minutes) if hours else "%dm %02ds" % (minutes, secs)


def _loot_line(group: dict) -> str:
    return "%s: %s" % (
        group["member"],
        ", ".join("%s (%s)" % (i["item"], i["quality"]) for i in group["items"]),
    )


def _plain_line(group: dict, joiner: str = ", ") -> str:
    return "%s: %s" % (group["member"], joiner.join(i["item"] for i in group["items"]))


def _death_line(group: dict) -> str:
    return "%s: %s" % (
        group["member"],
        ", ".join("killed by %s" % i["item"] for i in group["items"]),
    )


# Each grouped section: its heading, the report keys, what an empty one says,
# and how one member's line reads.
_SECTIONS = (
    ("Deaths", "deaths", "death_count", " none recorded", _death_line),
    ("Loot", "loot", "loot_count", " none", _loot_line),
    ("Upgrades equipped", "upgrades", "upgrade_count", " none", _plain_line),
    ("Quests completed", "quests", "quest_count", " none", _plain_line),
)


def _head(report: dict) -> str:
    sup = report.get("supervisor")
    if sup:
        return "Run report #%d: %s, run %s, %s, outcome %s, supervisor %s" % (
            report["run_id"],
            report["map_name"],
            report["run_number"] or "unnumbered",
            duration(report["duration_seconds"]),
            report["outcome"].upper() if report["wipe"] else report["outcome"],
            sup,
        )
    return "Run report #%d: %s, run %s, %s, outcome %s" % (
        report["run_id"],
        report["map_name"],
        report["run_number"] or "unnumbered",
        duration(report["duration_seconds"]),
        report["outcome"].upper() if report["wipe"] else report["outcome"],
    )


def lines(report: dict) -> list[str]:
    """The report as lines, the same lines on Discord and the page."""
    out = [_head(report)]
    if report["reason"]:
        out.append("Why it ended: %s" % report["reason"])
    out.append("Group: %s" % (", ".join(report["members"]) or "nobody recorded"))
    out.append(
        "Bosses killed (%d): %s"
        % (len(report["bosses"]), ", ".join(report["bosses"]) or "none")
    )
    for title, key, count, empty, line in _SECTIONS:
        groups = report[key]
        out.append("%s (%d):%s" % (title, report[count], "" if groups else empty))
        out += ["  " + line(g) for g in groups]
    return out


# Discord's message limit, less a little room.
DISCORD_LIMIT = 1990


def render(report: dict, limit: int = DISCORD_LIMIT) -> str:
    """The Discord message: one message, never more. A run so rich it would
    not fit loses detail lines from the end, never a heading, and says how
    many lines are on the family page instead; every heading carries its
    count, so the numbers still match the page."""
    kept = lines(report)
    dropped = 0
    while len("\n".join(kept)) > limit:
        details = [i for i, line in enumerate(kept) if line.startswith("  ")]
        if not details:
            return "\n".join(kept)[:limit]
        if dropped:
            kept.pop()  # the previous tail note
        kept.pop(details[-1])
        dropped += 1
        kept.append("(%d more lines on the family page)" % dropped)
    return "\n".join(kept)
