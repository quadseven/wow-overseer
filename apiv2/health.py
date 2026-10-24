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
              under a gold each. Gold the guild master withdrew for the fund's
              letters and has not posted yet (guildfund.Ledger.carried) counts
              as the bank's: the fund withdraws the whole bank to post it, so
              0 copper in the vault with the gold in the master's purse is
              gold in transit, not a bank that has run dry.
  family-run-loop
              a family whose last LOOP_RUNS or more dungeon runs in the last
              LOOP_HOURS, all on the map it ran last, ended without a clear
              (any outcome but dungeonpace.COMPLETE). Keyed by family and map.
              Impact is the failed runs x the run-hours they took. It is gone
              once a run of that map clears or the family runs another map.
              Its "most often because" is the run row's ended_reason, which
              for a stall is the cleanup; scripts/diagnose_finding.py prints
              why each run stopped, from the archived worldserver log.

Read-only, like everything under /api/v2. An empty list means "looked and
found nothing"; a read that fails is a 503 from the map server, never an empty
list.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import achievements
import council
import dungeonpace
import dungeonstall
import guildfund
import guildrun
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
LOOP_RUNS = 3
LOOP_HOURS = 24


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

# The family campaigns' own runs (overseer_dungeon_run has no family column:
# a run is the family's whose leader is one of its names), newest first.
FAMILY_RUNS_SQL = (
    "SELECT id, leader_name, map_id, state, outcome, ended_reason, "
    "UNIX_TIMESTAMP(started_at) AS started_unix, "
    "UNIX_TIMESTAMP(ended_at) AS ended_unix FROM overseer_dungeon_run "
    "WHERE leader_name IN ({holes}) AND started_at >= NOW() - INTERVAL %s HOUR "
    "ORDER BY id DESC LIMIT %s"
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


_PAREN = re.compile(r"\s*\([^)]*\)")


def _step_key(step: str) -> str:
    """The step without its per-member detail in parentheses ("Following Zug
    (0 yards behind)" is the step "Following Zug")."""
    return " ".join(_PAREN.sub("", step).split()) or step


def stuck_findings(stuck: dict, now_at: int) -> list:
    """One finding per step that members are stuck on STUCK_HOURS or more
    (members.stuck_view), not one per member: five members held on the same
    step are one problem, and one finding per member filed five tickets for
    one bug (2026-10-15). A follower held by its leader's hold (`follows`,
    members.follower_blocker) counts on the leader's step: one hold that keeps
    a family is one finding, not one for the leader and one for the family."""
    groups: dict = {}
    listed = list(stuck.get("members") or ())
    steps = {m.get("name"): m.get("step") for m in listed}
    for m in listed:
        hours = hours_since(m.get("since"), now_at)
        if not m.get("since") or hours < STUCK_HOURS:
            continue
        step = steps.get(m.get("follows")) or m.get("step")
        step = _step_key(step or "what it is doing")
        groups.setdefault((step, m.get("kind")), []).append((m, hours))
    out = []
    for (step, kind), rows in sorted(groups.items(), key=lambda kv: kv[0][0]):
        # The member whose own hold it is speaks for the group, before a follower.
        rows.sort(key=lambda r: (-r[1], bool(r[0].get("follows")), r[0]["name"]))
        names = [m["name"] for m, _ in rows]
        first, longest = rows[0]
        title = (
            "%s is stuck: %s" % (names[0], step)
            if len(names) == 1
            else "%d members are stuck: %s" % (len(names), step)
        )
        who = "" if len(names) == 1 else "%s; " % ", ".join(names)
        out.append(
            finding(
                "stuck:%s" % step,
                title,
                STUCK_AREAS.get(kind, "members"),
                len(names),
                longest,
                who + (first.get("blocker") or "stuck with no reason on record"),
                min(m.get("since") for m, _ in rows),
                impact=sum(h for _, h in rows),
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


def streak(rows: list) -> list:
    """The ended runs of `rows` (one family's, oldest first) from the newest
    back to the first that cleared or ran another map, oldest first. A run
    still open on that map is passed over: it has not ended either way."""
    if not rows:
        return []
    map_id = int(rows[-1].get("map_id") or 0)
    out = []
    for r in reversed(rows):
        if int(r.get("map_id") or 0) != map_id:
            break
        if str(r.get("outcome") or "") == dungeonpace.COMPLETE:
            break
        if r.get("state") == "ended":
            out.append(r)
    return out[::-1]


def family_streaks(runs: list, families: dict) -> dict:
    """(family, map id) -> its run rows, for every family whose streak is
    LOOP_RUNS or more. A run led by nobody in `families` is no family's."""
    family_of = {n: key for key, names in families.items() for n in names}
    by_family: dict = {}
    for r in sorted(runs or (), key=lambda r: int(r.get("id") or 0)):
        key = family_of.get(str(r.get("leader_name") or ""))
        if key:
            by_family.setdefault(key, []).append(r)
    out = {}
    for key, rows in sorted(by_family.items()):
        failed = streak(rows)
        if len(failed) >= LOOP_RUNS:
            out[(key, int(failed[0]["map_id"]))] = failed
    return out


def furthest_mask(ids: set, events: list) -> int:
    """The encounter mask with the most encounters any of the runs `ids` was
    credited (the timeline's `boss` rows, dungeonstall.mask_of), 0 for none."""
    masks = [
        dungeonstall.mask_of(e.get("detail"))
        for e in events or ()
        if e.get("kind") == "boss" and int(e.get("run_id") or 0) in ids
    ]
    return max(
        (m for m in masks if m is not None),
        key=lambda m: (bin(m).count("1"), m),
        default=0,
    )


def _loop_evidence(family, name, rows, mask, lost) -> str:
    counts: dict = {}
    reasons: dict = {}
    for r in rows:
        outcome = str(r.get("outcome") or "") or "closed unseen"
        counts[outcome] = counts.get(outcome, 0) + 1
        reason = str(r.get("ended_reason") or "").strip()
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    how = ", ".join("%d %s" % (n, o) for o, n in sorted(counts.items()))
    said = "Ended: %s." % how
    if reasons:
        common = max(sorted(reasons), key=lambda k: reasons[k])
        said += ' Most often because "%s".' % common
    furthest = (
        "encounter mask %d (%d encounters)" % (mask, bin(mask).count("1"))
        if mask
        else "no encounter credited"
    )
    return (
        "%s's family ran %s %d times running in %d hours with no clear. %s "
        "The furthest any run got: %s. %.1f run-hours went into them."
        % (family, name, len(rows), LOOP_HOURS, said, furthest, lost)
    )


def family_loop_findings(streaks: dict, events: list, now_at: int) -> list:
    """One finding per family repeating a map with no clear (family_streaks).
    Impact is the failed runs x the run-hours they took."""
    out = []
    for (family, map_id), rows in sorted(streaks.items()):
        lost = (
            sum(
                max(0, int(r.get("ended_unix") or 0) - int(r.get("started_unix") or 0))
                for r in rows
            )
            / 3600.0
        )
        mask = furthest_mask({int(r["id"]) for r in rows}, events)
        name = achievements.dungeon_name(map_id)
        first = int(rows[0].get("started_unix") or now_at)
        out.append(
            finding(
                "family-run-loop:%s:%d" % (family, map_id),
                "%s's family ran %s %d times without a clear"
                % (family, name, len(rows)),
                "dungeons",
                len(rows),
                hours_since(first, now_at),
                _loop_evidence(family, name, rows, mask, lost),
                first,
                impact=len(rows) * lost,
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
    streaks=None,
    events=(),
):
    """Everything read, the payload out. Pure. Highest impact first."""
    found = (
        stuck_findings(stuck, now_at)
        + dungeon_findings(runs, now_at, place)
        + family_loop_findings(streaks or {}, events, now_at)
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


def family_reads(rd, families: dict) -> tuple[dict, list]:
    """The family streaks (family_streaks) and the timeline rows of their runs."""
    names = [n for group in families.values() for n in group]
    if not names:
        return {}, []
    runs = rd.rows(
        FAMILY_RUNS_SQL.format(holes=_scope.holes(len(names))),
        (*names, LOOP_HOURS, RUNS_READ),
        what="overseer_dungeon_run",
    )
    streaks = family_streaks([dict(r) for r in runs], families)
    ids = sorted(int(r["id"]) for rows in streaks.values() for r in rows)
    if not ids:
        return streaks, []
    events = rd.rows(
        dungeonstall.EVENTS_SQL.format(holes=_scope.holes(len(ids))),
        tuple(ids),
        what="overseer_dungeon_run_event",
    )
    return streaks, [dict(e) for e in events]


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
    invites = rd.rows(INVITES_SQL, (REFUSAL_HOURS,), what="overseer_command")
    streaks, events = family_reads(rd, ctx.families.families())
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
        streaks,
        events,
    )
    return 200, payload


ROUTES = {"/api/v2/health": health}
