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

# Deaths of the run's members inside its window; {holes} is one %s per name.
DEATHS_SQL = (
    "SELECT character_name, killer_name FROM overseer_death "
    "WHERE character_name IN ({holes}) AND created_at >= %s AND created_at <= %s "
    "ORDER BY id"
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


def build(
    run: dict, events: list[dict], deaths: list[dict], map_name: str = ""
) -> dict:
    """The report for one run, from RUN_SQL's row, EVENTS_SQL's rows and
    DEATHS_SQL's rows. Everything the page draws and Discord prints is here."""
    names = members(run)
    loot = [
        {
            "member": e.get("character_name") or "",
            "item": e.get("subject_name") or "item %s" % e.get("subject_id"),
            "entry": int(e.get("subject_id") or 0),
            "quality": _quality(e),
            "detail": e.get("detail") or "",
        }
        for e in events
        if e.get("kind") == "loot_won"
    ]
    won = {(i["member"], i["entry"]) for i in loot}

    bosses: list[str] = []
    for e in events:
        if e.get("kind") == "boss_kill":
            name = e.get("subject_name") or "creature %s" % e.get("subject_id")
            if name not in bosses:
                bosses.append(name)

    upgrades = []
    for e in events:
        key = (e.get("character_name") or "", int(e.get("subject_id") or 0))
        if e.get("kind") == "item_equip" and key in won:
            item = {
                "member": key[0],
                "item": e.get("subject_name") or "item %s" % key[1],
            }
            if item not in upgrades:
                upgrades.append(item)

    quests = []
    for e in events:
        if e.get("kind") == "quest_reward":
            item = {
                "member": e.get("character_name") or "",
                "item": e.get("subject_name") or "",
            }
            if item not in quests:
                quests.append(item)

    died = [
        {
            "member": d.get("character_name") or "",
            "item": d.get("killer_name") or "unknown",
        }
        for d in deaths
    ]

    seconds = run.get("duration_seconds")
    return {
        "run_id": int(run.get("id") or 0),
        "run_number": int(run.get("run_number") or 0),
        "leader": run.get("leader_name") or "",
        "members": names,
        "map_id": int(run.get("map_id") or 0),
        "map_name": map_name or "map %s" % (run.get("map_id") or 0),
        "ended": run.get("state") == "ended",
        "outcome": outcome(run),
        "wipe": outcome(run) == "wipe",
        "reason": run.get("ended_reason") or "",
        "duration_seconds": int(seconds) if seconds is not None else None,
        "bosses": bosses,
        "loot": _by_member(names, loot),
        "loot_count": len(loot),
        "deaths": _by_member(names, died),
        "death_count": len(died),
        "upgrades": _by_member(names, upgrades),
        "upgrade_count": len(upgrades),
        "quests": _by_member(names, quests),
        "quest_count": len(quests),
    }


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
    return build(
        run, events, deaths, achievements.dungeon_name(int(run.get("map_id") or 0))
    )


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


def lines(report: dict) -> list[str]:
    """The report as lines, the same lines on Discord and the page."""
    head = "Run report #%d: %s, run %s, %s, outcome %s" % (
        report["run_id"],
        report["map_name"],
        report["run_number"] or "unnumbered",
        duration(report["duration_seconds"]),
        report["outcome"].upper() if report["wipe"] else report["outcome"],
    )
    out = [head]
    if report["reason"]:
        out.append("Why it ended: %s" % report["reason"])
    out.append("Group: %s" % (", ".join(report["members"]) or "nobody recorded"))
    out.append(
        "Bosses killed (%d): %s"
        % (len(report["bosses"]), ", ".join(report["bosses"]) or "none")
    )
    out.append(
        "Deaths (%d):%s"
        % (report["death_count"], "" if report["deaths"] else " none recorded")
    )
    out += [
        "  %s: %s"
        % (g["member"], ", ".join("killed by %s" % i["item"] for i in g["items"]))
        for g in report["deaths"]
    ]
    out.append(
        "Loot (%d):%s" % (report["loot_count"], "" if report["loot"] else " none")
    )
    out += ["  " + _loot_line(g) for g in report["loot"]]
    out.append(
        "Upgrades equipped (%d):%s"
        % (report["upgrade_count"], "" if report["upgrades"] else " none")
    )
    out += ["  " + _plain_line(g) for g in report["upgrades"]]
    out.append(
        "Quests completed (%d):%s"
        % (report["quest_count"], "" if report["quests"] else " none")
    )
    out += ["  " + _plain_line(g) for g in report["quests"]]
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
