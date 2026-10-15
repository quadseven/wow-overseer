"""GET /api/v2/health: the realm's open problems, as findings a planner can rank.

WHY. The guild's problems were found by someone reading the site and the
bridge's logs, then written up by hand. A planner that files tickets for this
repository reads this one list instead: each finding is one problem with a
stable key, how many it hits, how long it has lasted and the evidence, and
it is absent once the problem clears.

THE SHAPE (shared with the planner):

    {checked_at: ISO time, findings: [{key, title, area, affected, hours,
     impact, evidence, since}]}

`key` is the same for the same problem every time. `impact` drives priority:
affected x hours, or a kind's own loss measure where that reads truer (a
dungeon's is the member-hours spent inside runs that failed). `since` is an
ISO time, or null when the start is not on record (then `hours` is 0).
Findings become public tickets, so every string is ASCII and names only
characters in the game.

THE KINDS:

  stuck       a member the roster reads as stuck (members.stuck_view) for
              STUCK_HOURS or more
  dungeon     a dungeon whose runs that went in cleared under CLEAR_FLOOR of
              at least MIN_RUNS in the last day
  questers    a guild with questers missing from the realm, with the team
              sync's invites and the module's latest refusal reason
  bank        a family guild whose bank holds under a gold while members hold
              under a gold each

Read-only, like everything under /api/v2. An empty list means "looked and
found nothing"; a read that fails is a 503 from the map server, never an empty
list.
"""

from __future__ import annotations

import datetime as dt
import json

import council
from apiv2 import _scope, members, quests

STUCK_HOURS = 2.0
MIN_RUNS = 8
CLEAR_FLOOR = 0.30
RUN_DAYS = 1
RUNS_READ = 500
REFUSAL_HOURS = 48
COPPER_PER_GOLD = 10_000
TITLE_MAX = 90
EVIDENCE_MAX = 400

# The outcomes of a run that went in (guildrun.WENT_IN), the only ones that say
# anything about the dungeon.
WENT_IN = ("cleared", "wiped", "abandoned", "timed out")

# The marks the game's and the bridge's text use that ASCII has a plain twin for.
NON_ASCII = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
}

STUCK_AREAS = {"class quest": "quests", "hold": "gear", "ghost": "deaths"}

NOW_SQL = "SELECT UNIX_TIMESTAMP() AS now_at"
RUNS_SQL = (
    "SELECT keyword, outcome, members, seconds_inside, "
    "UNIX_TIMESTAMP(created_at) AS created_unix "
    "FROM overseer_guild_run WHERE guild IN ({holes}) AND state = 'ended' "
    "AND created_at >= NOW() - INTERVAL %s DAY ORDER BY id DESC LIMIT %s"
)
# The team sync's guild invites (bridge TEAM_SYNC_SOURCE), with the module's
# answer in `result` and `detail`.
INVITES_SQL = (
    "SELECT target_arg, status, detail, result, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_command WHERE kind = 'guild' AND source = 'teams' "
    "AND command = 'invite' AND created_at >= NOW() - INTERVAL %s HOUR "
    "ORDER BY id"
)
BANK_SQL = (
    "SELECT g.name AS guild, g.BankMoney AS bank, "
    "SUM(c.money < %s) AS broke, COUNT(c.guid) AS members "
    "FROM guild g LEFT JOIN guild_member gm ON gm.guildid = g.guildid "
    "LEFT JOIN characters c ON c.guid = gm.guid "
    "WHERE g.name IN ({holes}) GROUP BY g.guildid, g.name, g.BankMoney"
)
# The bank's money log (tab 100 holds the money events): when the gold last
# moved, the nearest record of when the bank ran dry.
BANK_MOVED_SQL = (
    "SELECT g.name AS guild, MAX(e.TimeStamp) AS at FROM guild_bank_eventlog e "
    "JOIN guild g ON g.guildid = e.guildid WHERE e.TabId = 100 "
    "AND g.name IN ({holes}) GROUP BY g.name"
)


# ------------------------------------------------------------------- helpers --


def ascii_text(value, most: int) -> str:
    """`value` as one line of printable ASCII, at most `most` characters."""
    text = " ".join(str(value or "").split())
    text = "".join(c if ord(c) < 128 else NON_ASCII.get(c, "?") for c in text)
    return text if len(text) <= most else text[: most - 3].rstrip() + "..."


def iso(at) -> str | None:
    if not at:
        return None
    return dt.datetime.fromtimestamp(int(at), dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def hours_since(at, now_at: int) -> float:
    if not at:
        return 0.0
    return round(max(0, now_at - int(at)) / 3600.0, 1)


def finding(key, title, area, affected, hours, evidence, since, impact=None) -> dict:
    affected = int(affected)
    hours = float(hours)
    return {
        "key": ascii_text(key, 120),
        "title": ascii_text(title, TITLE_MAX),
        "area": area,
        "affected": affected,
        "hours": hours,
        "impact": round(affected * hours if impact is None else float(impact), 1),
        "evidence": ascii_text(evidence, EVIDENCE_MAX),
        "since": iso(since),
    }


def _result(row) -> dict:
    raw = row.get("result")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def refused_invite(row) -> bool:
    """Whether the module turned an invite down. It answers a refusal with
    status `unchanged` and `result.outcome` "refused" (2,001 of 2,004 team
    sync invites on the dev realm, 2026-10-15), and a fault with `error`."""
    return str(row.get("status")) == "error" or _result(row).get("outcome") == "refused"


def refusal_reason(row) -> str:
    """Why the module turned an invite down: `result.reason`, else `detail`."""
    return str(_result(row).get("reason") or row.get("detail") or "").strip()


# --------------------------------------------------------------- the kinds --


def stuck_findings(stuck: dict, now_at: int) -> list:
    """One finding per member stuck STUCK_HOURS or more (members.stuck_view)."""
    out = []
    for m in stuck.get("members") or ():
        hours = hours_since(m.get("since"), now_at)
        if not m.get("since") or hours < STUCK_HOURS:
            continue
        name, step = m["name"], m.get("step") or "what it is doing"
        out.append(
            finding(
                "stuck:%s:%s" % (name, step),
                "%s is stuck: %s" % (name, step),
                STUCK_AREAS.get(m.get("kind"), "members"),
                1,
                hours,
                m.get("blocker") or "stuck with no reason on record",
                m.get("since"),
            )
        )
    return out


def _seats(members_text) -> int:
    return len([s for s in str(members_text or "").split(",") if s.split(":")[0]])


def dungeon_findings(runs: list, now_at: int, place=lambda k: k) -> list:
    """One finding per dungeon whose runs that went in cleared under
    CLEAR_FLOOR of at least MIN_RUNS. Impact is the member-hours spent inside
    the runs that failed."""
    by_keyword: dict = {}
    for r in runs or ():
        if r.get("outcome") in WENT_IN:
            by_keyword.setdefault(str(r.get("keyword") or ""), []).append(r)
    out = []
    for keyword, went in sorted(by_keyword.items()):
        if not keyword or len(went) < MIN_RUNS:
            continue
        cleared = sum(1 for r in went if r["outcome"] == "cleared")
        if cleared / len(went) >= CLEAR_FLOOR:
            continue
        failed = [r for r in went if r["outcome"] != "cleared"]
        lost = (
            sum(
                int(r.get("seconds_inside") or 0) * max(1, _seats(r.get("members")))
                for r in failed
            )
            / 3600.0
        )
        counts: dict = {}
        for r in failed:
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        how = ", ".join("%d %s" % (n, o) for o, n in sorted(counts.items()))
        first = min(int(r.get("created_unix") or now_at) for r in failed)
        name = place(keyword)
        out.append(
            finding(
                "dungeon-clear-rate:%s" % keyword,
                "%s runs clear %d of %d in a day" % (name, cleared, len(went)),
                "dungeons",
                len(failed),
                hours_since(first, now_at),
                "In the last %d hours %d of %d runs that went into %s cleared "
                "(%s); %.1f member-hours were spent inside the failed runs."
                % (RUN_DAYS * 24, cleared, len(went), name, how, lost),
                first,
                impact=lost,
            )
        )
    return out


def quester_findings(questers: dict, invites: list, now_at: int) -> list:
    """One finding per guild with questers missing from the realm, with what
    the team sync's invites got back over the last REFUSAL_HOURS."""
    missing: dict = {}
    for q in questers.get("questers") or ():
        if not q.get("present"):
            missing.setdefault(str(q.get("guild") or "the guild"), []).append(q["name"])
    if not missing:
        return []
    refused = [r for r in invites or () if refused_invite(r)]
    first = min((int(r["at"]) for r in refused if r.get("at")), default=0)
    reason = refusal_reason(refused[-1]) if refused else ""
    if refused:
        said = "%d of %d team sync invites in %d hours were refused" % (
            len(refused),
            len(invites),
            REFUSAL_HOURS,
        )
        said += ', the latest because "%s".' % reason if reason else "."
    elif invites:
        said = "%d team sync invites in %d hours, none refused." % (
            len(invites),
            REFUSAL_HOURS,
        )
    else:
        said = "No team sync invite in %d hours." % REFUSAL_HOURS
    total = sum(1 for _ in questers.get("questers") or ())
    out = []
    for guild, names in sorted(missing.items()):
        out.append(
            finding(
                "questers-missing:%s" % guild,
                "%d of the %s questers are not on the realm" % (len(names), guild),
                "recruiting",
                len(names),
                hours_since(first, now_at),
                "Missing: %s (of %d questers). %s" % (", ".join(names), total, said),
                first or None,
            )
        )
    return out


def bank_findings(banks: list, moved: dict, now_at: int) -> list:
    """One finding per guild whose bank holds under a gold while members hold
    under a gold each. Hours count from the bank's last money movement."""
    out = []
    for b in banks or ():
        bank, broke = int(b.get("bank") or 0), int(b.get("broke") or 0)
        if bank >= COPPER_PER_GOLD or broke <= 0:
            continue
        guild = str(b["guild"])
        at = moved.get(guild)
        out.append(
            finding(
                "guild-bank-empty:%s" % guild,
                "The %s guild bank holds under a gold" % guild,
                "guild",
                broke,
                hours_since(at, now_at),
                "The bank holds %d copper and %d of %d members hold under a "
                "gold each, so training and refunds wait. %s"
                % (
                    bank,
                    broke,
                    int(b.get("members") or 0),
                    "Its gold last moved at %s." % iso(at)
                    if at
                    else "Its money log is empty.",
                ),
                at,
            )
        )
    return out


def build(now_at, stuck, runs, questers, invites, banks, moved, place=lambda k: k):
    """Everything read, the payload out. Pure. Highest impact first."""
    found = (
        stuck_findings(stuck, now_at)
        + dungeon_findings(runs, now_at, place)
        + quester_findings(questers, invites, now_at)
        + bank_findings(banks, moved, now_at)
    )
    found.sort(key=lambda f: (-f["impact"], f["key"]))
    return {"checked_at": iso(now_at), "findings": found}


# ------------------------------------------------------------------ handler --


def place(keyword: str) -> str:
    """A run keyword as the place's name (council.keyword_place)."""
    try:
        return council.keyword_place(keyword)
    except Exception:  # noqa: BLE001 - an unknown keyword reads as itself
        return keyword


def health(_query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/health: the open problems, highest impact first."""
    rd = ctx.read
    now_at = int(rd.must(NOW_SQL)[0]["now_at"])
    guilds = sorted(_scope.guilds(ctx).values())
    marks = _scope.holes(len(guilds))
    runs = banks = []
    moved: dict = {}
    if guilds:
        runs = rd.rows(
            RUNS_SQL.format(holes=marks),
            (*guilds, RUN_DAYS, RUNS_READ),
            what="overseer_guild_run",
        )
        banks = rd.rows(
            BANK_SQL.format(holes=marks), (COPPER_PER_GOLD, *guilds), what="guild"
        )
        moved = {
            str(r["guild"]): int(r["at"] or 0)
            for r in rd.rows(
                BANK_MOVED_SQL.format(holes=marks),
                tuple(guilds),
                what="guild_bank_eventlog",
            )
        }
    invites = rd.rows(INVITES_SQL, (REFUSAL_HOURS,), what="overseer_command")
    _, stuck = members.stuck(_query, ctx)
    _, questers = quests.questers(_query, ctx)
    payload = build(
        now_at,
        stuck,
        [dict(r) for r in runs],
        questers,
        [dict(r) for r in invites],
        [dict(r) for r in banks],
        moved,
        place,
    )
    return 200, payload


ROUTES = {"/api/v2/health": health}
