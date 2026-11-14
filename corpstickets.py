"""A blocked guild corps member becomes one GitHub issue (#2399).

WHY THIS EXISTS. On the dev realm on 2026-11-13 a read of one day's command
rows found guild members blocked all day with nothing telling anybody: one
refused 675 walks as standing "outside the classic world", one asked for the
same vendor walk 73 times and was refused "in combat" every time, two hit the
realm's crossing cap more than 80 times each, and one was refused 44 buys for
bag room. The quest ledger already files an issue per broken quest
(questtickets.py); this files one per blocked member and blocker kind.

WHAT IS A BLOCKER, read from 24 hours of a member's command rows:

  dead-loop   one refusal reason DEAD_LOOP_MIN times or more, and not one row
              of the member's came back applied or delivered.
  off-world   the same, when the reason is the classic gate's "outside the
              classic world".
  full-bags   FULL_BAGS_MIN refusals or more for bag room, whatever else
              succeeded: the member keeps working, but loot and buys stop.

ONE ISSUE PER MEMBER AND KIND, EVER. The memo row `corps_tickets` /
`<name>:<kind>` holds the issue number, and FILING while a filing is in
flight, so a crash between the request and the write never files twice; a
row left at FILING is reported for a person. Reopening is a person's call.

BOUNDED. At most MAX_PER_PASS issues a pass. NO CREDENTIAL, NO PASS: the
client is questtickets' App client, None until the App is configured.

PURE but for `SqlStore` (a cursor).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import raidteams

EPIC = int(os.environ.get("CORPS_TICKET_EPIC", "2396"))
MAX_PER_PASS = 5
FILING = 0
MEMO_KIND = "corps_tickets"
MEMO_DAYS = 365

DEAD_LOOP_MIN = 20
FULL_BAGS_MIN = 10

DEAD_LOOP, OFF_WORLD, FULL_BAGS = "dead-loop", "off-world", "full-bags"
OK_STATUSES = frozenset({"applied", "delivered"})
BAG_REASONS = (
    "bags cannot take the item",
    "no free bag slot",
    "no room in the bags",
)
OFF_WORLD_REASON = "outside the classic world"

# The guilds whose non-roster members are the corps, and their 24 hours of
# rows. Chat rows say nothing about a member's work. The command log collates
# utf8mb4_0900_ai_ci and the character and roster names do not (measured on
# the dev realm), so both name lists are cast to the command log's collation.
ROWS_SQL = (
    "SELECT oc.target_name, oc.status, oc.source, oc.result "
    "FROM overseer_command oc "
    "WHERE oc.created_at > NOW() - INTERVAL 24 HOUR AND oc.kind <> 'chat' "
    "AND oc.target_name IN ("
    " SELECT c.name COLLATE utf8mb4_0900_ai_ci FROM guild_member gm"
    " JOIN guild g ON g.guildid = gm.guildid"
    " JOIN characters c ON c.guid = gm.guid WHERE g.name IN ({holes})) "
    "AND oc.target_name NOT IN ("
    " SELECT name COLLATE utf8mb4_0900_ai_ci FROM overseer_roster)"
)
MEMO_SQL = "SELECT subject, value FROM overseer_bridge_memo WHERE kind = %s"
WRITE_SQL = (
    "INSERT INTO overseer_bridge_memo (kind, subject, value, since, expires) "
    "VALUES (%s, %s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE value = VALUES(value), since = VALUES(since), "
    "expires = VALUES(expires)"
)
DELETE_SQL = "DELETE FROM overseer_bridge_memo WHERE kind = %s AND subject = %s"


def guilds() -> tuple:
    return tuple(sorted(raidteams.GROUPS))


def holes(n: int) -> str:
    return ", ".join(["%s"] * max(1, int(n)))


@dataclass(frozen=True)
class Blocker:
    name: str
    kind: str
    reason: str
    count: int
    sources: tuple = ()

    @property
    def key(self) -> str:
        return "%s:%s" % (self.name, self.kind)


def reason_of(row) -> str:
    """The refusal reason of a row, numbers folded so one reason groups."""
    text = row.get("result") or ""
    try:
        body = json.loads(text) if text else {}
    except (TypeError, ValueError):
        body = {}
    reason = (
        str(body.get("reason") or body.get("outcome") or "")
        if isinstance(body, dict)
        else ""
    )
    return re.sub(r"\d+", "N", reason).strip()


def _source(row) -> str:
    return ":".join(str(row.get("source") or "").split(":")[:2])


def blockers(rows) -> list:
    """Every Blocker the rows show, by name, then kind."""
    by_name: dict = {}
    for row in rows or ():
        by_name.setdefault(str(row.get("target_name") or ""), []).append(row)
    out = []
    for name in sorted(n for n in by_name if n):
        mine = by_name[name]
        ok = any(str(r.get("status")) in OK_STATUSES for r in mine)
        reasons: dict = {}
        bags = []
        for r in mine:
            if str(r.get("status")) != "error":
                continue
            why = reason_of(r)
            if not why:
                continue
            reasons.setdefault(why, []).append(r)
            if any(b in why for b in BAG_REASONS):
                bags.append(r)
        if not ok and reasons:
            why, worst = max(reasons.items(), key=lambda kv: (len(kv[1]), kv[0]))
            if len(worst) >= DEAD_LOOP_MIN:
                kind = OFF_WORLD if OFF_WORLD_REASON in why else DEAD_LOOP
                out.append(Blocker(name, kind, why, len(worst), _sources(worst)))
        if len(bags) >= FULL_BAGS_MIN:
            out.append(
                Blocker(name, FULL_BAGS, reason_of(bags[0]), len(bags), _sources(bags))
            )
    return out


def _sources(rows) -> tuple:
    return tuple(sorted({_source(r) for r in rows if _source(r)}))


KIND_WORDS = {
    DEAD_LOOP: "is refused the same step all day",
    OFF_WORLD: "stands where the classic gate refuses every walk",
    FULL_BAGS: "is refused for bag room",
}


def title(b: Blocker) -> str:
    return "Corps member %s %s: %d refusals in 24 hours" % (
        b.name,
        KIND_WORDS.get(b.kind, "is blocked"),
        b.count,
    )


def body(b: Blocker, epic: int = EPIC) -> str:
    sources = ", ".join("`%s`" % s for s in b.sources) or "unknown"
    return "\n".join(
        [
            "## Why",
            "",
            "The bridge's corps blocker pass (`corpstickets.py`) read the last 24 "
            "hours of command rows for %s and found a `%s` blocker: %d rows "
            'refused "%s"%s. Rows came from %s.'
            % (
                b.name,
                b.kind,
                b.count,
                b.reason,
                ", and no row succeeded" if b.kind != FULL_BAGS else "",
                sources,
            ),
            "",
            "## What",
            "",
            "- Find why the step keeps being asked while the refusal never clears, "
            "and give the member a step it can take or a backoff with a reason.",
            "",
            "## Acceptance criteria",
            "",
            "- [ ] The cause is named on this ticket from the rows and the code.",
            "- [ ] A unit test pins the fix or the backoff.",
            "- [ ] Live: the member's refusals of this reason over 24 hours fall "
            "below %d." % (FULL_BAGS_MIN if b.kind == FULL_BAGS else DEAD_LOOP_MIN),
            "",
            "Size: S",
            "",
            "## Out of scope",
            "",
            "- Other members and other blocker kinds: each has its own ticket.",
            "",
            "Part of #%d" % epic,
            "",
            "-- filed by the bridge's corps blocker pass",
        ]
    )


@dataclass(frozen=True)
class Plan:
    new: tuple = ()  # Blocker, not yet filed
    stuck: tuple = ()  # keys left at FILING


def plan(found, known) -> Plan:
    """`known` key -> ticket number (FILING while in flight)."""
    new = tuple(b for b in found if b.key not in known)
    stuck = tuple(sorted(k for k, t in (known or {}).items() if int(t) == FILING))
    return Plan(new=new, stuck=stuck)


class SqlStore:
    def __init__(self, cur):
        self.cur = cur

    def rows(self) -> list:
        names = guilds()
        self.cur.execute(ROWS_SQL.format(holes=holes(len(names))), names)
        return list(self.cur.fetchall())

    def known(self) -> dict:
        self.cur.execute(MEMO_SQL, (MEMO_KIND,))
        out = {}
        for r in self.cur.fetchall():
            try:
                out[str(r["subject"])] = int(json.loads(r["value"] or "{}")["ticket"])
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def mark(self, key: str, ticket: int, now: float) -> None:
        self.cur.execute(
            WRITE_SQL,
            (
                MEMO_KIND,
                key,
                json.dumps({"ticket": int(ticket)}),
                float(now),
                float(now) + MEMO_DAYS * 86400.0,
            ),
        )

    def release(self, key: str) -> None:
        self.cur.execute(DELETE_SQL, (MEMO_KIND, key))


def run(store, client, now: float) -> dict:
    """One pass: {found, filed, stuck, unlinked}. A refused filing frees its
    key for the next pass and is raised; a filing that never answered stays at
    FILING for a person."""
    found = blockers(store.rows())
    todo = plan(found, store.known())
    filed = []
    for b in todo.new[:MAX_PER_PASS]:
        store.mark(b.key, FILING, now)
        try:
            number = client.file(title(b), body(b))
        except Exception as exc:
            if "Timeout" not in type(exc).__name__:
                store.release(b.key)
            raise
        store.mark(b.key, number, now)
        filed.append("%s #%d" % (b.key, number))
    unlinked, client.unlinked = list(getattr(client, "unlinked", [])), []
    return {
        "found": len(found),
        "filed": filed,
        "stuck": list(todo.stuck),
        "unlinked": unlinked,
    }
