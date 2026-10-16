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
  family-run-loop
              a family repeating a dungeon three or more times in 24 hours
              ending without a clear
  questers    a guild with questers missing from the realm, with the team
              sync's invites and the module's latest refusal reason
  bank        a family guild whose bank holds under a gold while members hold
              under a gold each. Gold the guild master withdrew for the fund's
              letters and has not posted yet (guildfund.Ledger.carried) counts
              as the bank's: the fund withdraws the whole bank to post it, so
              0 copper in the vault with the gold in the master's purse is
              gold in transit, not a bank that has run dry.

Read-only, like everything under /api/v2. An empty list means "looked and
found nothing"; a read that fails is a 503 from the map server, never an empty
list.
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import re

import campaignplan
import council
import decree
import guildfund
import guildrun
import places
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
FAMILY_LOOP_MIN_RUNS = 3
FAMILY_LOOP_HOURS = 24
CLEARED_OUTCOMES = frozenset({"cleared", "complete"})


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
# The team sync's guild invites (bridge TEAM_SYNC_SOURCE), with the module's
# answer in `result` and `detail`.
INVITES_SQL = (
    "SELECT target_arg, status, detail, result, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_command WHERE kind = 'guild' AND source = 'teams' "
    "AND command = 'invite' AND created_at >= NOW() - INTERVAL %s HOUR "
    "ORDER BY id"
)
BANK_SQL = (
    "SELECT g.name AS guild, g.BankMoney AS bank, lc.name AS master, "
    "lc.money AS purse, SUM(c.money < %s) AS broke, COUNT(c.guid) AS members "
    "FROM guild g LEFT JOIN guild_member gm ON gm.guildid = g.guildid "
    "LEFT JOIN characters c ON c.guid = gm.guid "
    "LEFT JOIN characters lc ON lc.guid = g.leaderguid "
    "WHERE g.name IN ({holes}) "
    "GROUP BY g.guildid, g.name, g.BankMoney, lc.name, lc.money"
)
# The guild fund's rows in the command log (what guildfund.ledger reads).
FUND_SQL = (
    "SELECT target_name, target_arg, command, source, status, result, "
    "TIMESTAMPDIFF(MINUTE, created_at, NOW()) AS age FROM overseer_command "
    "WHERE source LIKE 'guildfund:%'"
)
# The bank's money log (tab 100 holds the money events): when the gold last
# moved, the nearest record of when the bank ran dry.
BANK_MOVED_SQL = (
    "SELECT g.name AS guild, MAX(e.TimeStamp) AS at FROM guild_bank_eventlog e "
    "JOIN guild g ON g.guildid = e.guildid WHERE e.TabId = 100 "
    "AND g.name IN ({holes}) GROUP BY g.name"
)
FAMILY_RUNS_SQL = (
    "SELECT id, map_id, portal_keyword, outcome, leader_name, "
    "UNIX_TIMESTAMP(started_at) AS started_unix "
    "FROM overseer_dungeon_run WHERE state = 'ended' "
    "AND leader_name IN ({holes}) AND started_at >= NOW() - INTERVAL %s HOUR "
    "ORDER BY id"
)
FAMILY_EVENTS_SQL = (
    "SELECT run_id, kind, detail FROM overseer_dungeon_run_event "
    "WHERE run_id IN ({holes}) AND kind IN ('boss', 'stalled') ORDER BY id"
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
        if r.get("outcome") in guildrun.WENT_IN:
            by_keyword.setdefault(str(r.get("keyword") or ""), []).append(r)
    out = []
    for keyword, went in sorted(by_keyword.items()):
        if not keyword or len(went) < MIN_RUNS:
            continue
        cleared = sum(1 for r in went if r["outcome"] == guildrun.CLEARED)
        if cleared / len(went) >= CLEAR_FLOOR:
            continue
        failed = [r for r in went if r["outcome"] != guildrun.CLEARED]
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


_MASK = re.compile(r"\(mask \d+ -> (\d+)\)")


def _mask_of(detail: str) -> int | None:
    found = _MASK.search(str(detail or ""))
    return int(found.group(1)) if found else None


def _run_ts(r: dict) -> int | None:
    val = r.get("started_unix") or r.get("created_unix") or r.get("started_at")
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, dt.datetime):
        return int(val.replace(tzinfo=dt.timezone.utc).timestamp())
    return None


def _map_id_of(r: dict) -> int | None:
    try:
        mid = int(r.get("map_id") or 0)
        if mid > 0:
            return mid
    except (TypeError, ValueError):
        pass
    kw = str(r.get("portal_keyword") or "")
    if kw:
        for run_info in campaignplan.RUNS:
            if run_info.keyword == kw:
                return run_info.map_id
    return None


def _map_name(map_id, place=None) -> str:
    if place is not None:
        try:
            res = place(map_id)
            if res and res != map_id and not (
                isinstance(map_id, int) and res == str(map_id)
            ):
                return str(res)
        except Exception:
            pass
    return places.map_name(map_id)


def _family_label(family: str) -> str:
    if not family:
        return "the family"
    if family.endswith("'s family") or family.endswith(" family"):
        return family
    return decree.family_label(family)


def _highest_mask(streak: list, events: list | None) -> int:
    masks = []
    for r in streak:
        if "mask" in r:
            try:
                masks.append(int(r["mask"]))
            except (ValueError, TypeError):
                pass
        rid = int(r.get("id") or 0)
        if rid and events:
            for e in events:
                if int(e.get("run_id") or 0) == rid and e.get("kind") == "boss":
                    m = _mask_of(e.get("detail"))
                    if m is not None:
                        masks.append(m)
    return max(masks, default=0)


def _streak_on_latest_map(fam_runs: list) -> list:
    """The trailing contiguous run streak on the latest map ending without clear."""
    if not fam_runs:
        return []
    latest = fam_runs[-1]
    if str(latest.get("outcome") or "") in CLEARED_OUTCOMES:
        return []
    latest_map = _map_id_of(latest)
    if latest_map is None:
        return []
    streak = []
    for r in reversed(fam_runs):
        if _map_id_of(r) != latest_map:
            break
        if str(r.get("outcome") or "") in CLEARED_OUTCOMES:
            break
        streak.append(r)
    streak.reverse()
    return streak


def family_run_loop_findings(
    runs: list | None,
    now_at: int,
    events: list | None = None,
    place=None,
) -> list:
    """One finding per family whose last 3 or more runs in 24 hours on the
    same map ended without a clear (any outcome other than cleared).
    Absent once a run of that map clears or the family moves to another map."""
    by_family: dict[str, list] = {}
    for r in runs or ():
        ts = _run_ts(r)
        if ts is not None and (now_at - ts) > FAMILY_LOOP_HOURS * 3600:
            continue
        fam = str(r.get("family") or r.get("leader_name") or "family")
        by_family.setdefault(fam, []).append(r)

    out = []
    for family, fam_runs in sorted(by_family.items()):
        fam_runs.sort(key=lambda r: (_run_ts(r) or 0, int(r.get("id") or 0)))
        streak = _streak_on_latest_map(fam_runs)
        if len(streak) < FAMILY_LOOP_MIN_RUNS:
            continue

        latest_map = _map_id_of(streak[-1])
        count = len(streak)
        first_ts = _run_ts(streak[0])
        hours = hours_since(first_ts, now_at)

        reasons = [
            str(r.get("outcome") or r.get("reason") or "failed") for r in streak
        ]
        common_reason = collections.Counter(reasons).most_common(1)[0][0]
        highest_mask = _highest_mask(streak, events)

        map_title = _map_name(latest_map, place)
        label = _family_label(family)
        out.append(
            finding(
                "family-run-loop:%s:%s" % (family, latest_map),
                "%s ran %s %d times with no clear" % (label, map_title, count),
                "dungeons",
                count,
                hours,
                "%s ran %s %d times in 24 hours with no clear "
                "(common ended reason: %s, highest encounter mask reached: %d)."
                % (label, map_title, count, common_reason, highest_mask),
                first_ts,
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


def with_carried(banks: list, fund_rows: list) -> list:
    """The bank rows with `carried`: the fund gold each guild master withdrew
    and has not posted, no more than its purse holds (as the bridge reads it)."""
    out = []
    for b in banks or ():
        master = str(b.get("master") or "")
        held = guildfund.ledger(fund_rows, master).carried if master else 0
        out.append({**b, "carried": min(held, max(0, int(b.get("purse") or 0)))})
    return out


def bank_findings(banks: list, moved: dict, now_at: int) -> list:
    """One finding per guild whose bank, with the fund gold its master carries,
    holds under a gold while members hold under a gold each. Hours count from
    the bank's last money movement."""
    out = []
    for b in banks or ():
        bank = int(b.get("bank") or 0) + int(b.get("carried") or 0)
        broke = int(b.get("broke") or 0)
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


def build(
    now_at,
    stuck,
    runs,
    questers,
    invites,
    banks,
    moved,
    place=lambda k: k,
    family_runs=None,
    family_events=None,
):
    """Everything read, the payload out. Pure. Highest impact first."""
    found = (
        stuck_findings(stuck, now_at)
        + dungeon_findings(runs, now_at, place)
        + family_run_loop_findings(family_runs, now_at, family_events, place)
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
    runs = banks = fund = []
    moved: dict = {}
    if guilds:
        runs = guildrun.ended_since(rd, guilds, RUN_DAYS, RUNS_READ)
        banks = rd.rows(
            BANK_SQL.format(holes=marks), (COPPER_PER_GOLD, *guilds), what="guild"
        )
        fund = rd.rows(FUND_SQL, what="overseer_command")
        moved = {
            str(r["guild"]): int(r["at"] or 0)
            for r in rd.rows(
                BANK_MOVED_SQL.format(holes=marks),
                tuple(guilds),
                what="guild_bank_eventlog",
            )
        }
    fams = ctx.server.FAMILIES.families() if hasattr(ctx.server, "FAMILIES") else {}
    family_of = {
        name: fam_key for fam_key, members in fams.items() for name in members
    }
    leaders = sorted(family_of)
    family_runs = []
    family_events = []
    if leaders:
        family_runs = [
            dict(r)
            for r in rd.rows(
                FAMILY_RUNS_SQL.format(holes=_scope.holes(len(leaders))),
                (*leaders, FAMILY_LOOP_HOURS),
                what="overseer_dungeon_run",
            )
        ]
        for r in family_runs:
            if not r.get("family") and r.get("leader_name") in family_of:
                r["family"] = family_of[r["leader_name"]]
        run_ids = [int(r["id"]) for r in family_runs if r.get("id")]
        if run_ids:
            family_events = [
                dict(e)
                for e in rd.rows(
                    FAMILY_EVENTS_SQL.format(holes=_scope.holes(len(run_ids))),
                    tuple(run_ids),
                    what="overseer_dungeon_run_event",
                )
            ]
    invites = rd.rows(INVITES_SQL, (REFUSAL_HOURS,), what="overseer_command")
    _, stuck = members.stuck(_query, ctx)
    _, questers = quests.questers(_query, ctx)
    payload = build(
        now_at,
        stuck,
        [dict(r) for r in runs],
        questers,
        [dict(r) for r in invites],
        with_carried([dict(r) for r in banks], [dict(r) for r in fund]),
        moved,
        place,
        family_runs,
        family_events,
    )
    return 200, payload


ROUTES = {"/api/v2/health": health}
