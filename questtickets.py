"""Each broken quest becomes one GitHub issue under the questers epic (#926).

WHY THIS EXISTS. The quest ledger (questledger.py) records broken quests with
a reason, and a list of hundreds is read by nobody. A daily pass files one
issue per newly broken quest, so a broken quest reaches the people and lanes
that fix it.

ONE ISSUE PER QUEST, EVER. Several questers can break one quest, and that is
one issue. The ledger's `ticket` column holds the issue number on each broken
row of the quest; a later row of a filed quest takes the same number and
files nothing. The column reads FILING while a filing is in flight, set
before the request, so a crash between the request and the write can never
file twice: that row stays at FILING and `plan` reports it for a person.
Reopening an issue is the brain's call, never this pass's.

BOUNDED. At most MAX_PER_PASS issues a pass: each one queues paid or capped
work, and a first pass may find hundreds.

NO CREDENTIAL, NO PASS. `client_from_env` answers None until the App's Secret
is mounted and the three settings below name it, and the bridge then skips.

PURE but for `SqlStore` (a cursor) and `client_from_env` (HTTPS).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import questledger
import raidteams

# The open quest epic. #922 closed on 2026-11-01 and its part 2 is #1575;
# a ticket filed under a closed epic fails the plan check's epic row.
EPIC = int(os.environ.get("QUEST_TICKET_EPIC", "1575"))
REPO = os.environ.get("QUEST_TICKET_REPO", "quadseven/wow-overseer")
# The station holds a ticket with no `area:` label until a person adds one
# (#2759), so every issue filed here goes out under exactly one area. STATE
# is what any bridge-filed ticket carries; AREA is this filer's area of play
# (docs/agents/area-taxonomy.md). Another filer passes its own labels.
STATE_LABELS = ("loom:ticket", "loom:queued")
AREA = "area:questing"
LABELS = STATE_LABELS + (AREA,)
MAX_PER_PASS = 5
FILING = 0
MEMO_KIND = "quest_tickets"
MEMO_SUBJECT = "last_pass"
# Asked for at mint time, whatever the App could grant: sub-issues are part
# of the issues permission.
TOKEN_PERMISSIONS = {"issues": "write"}

HAS_COLUMN_SQL = (
    "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'overseer_quest_ledger' "
    "AND COLUMN_NAME = 'ticket'"
)
ADD_COLUMN_SQL = (
    "ALTER TABLE overseer_quest_ledger ADD COLUMN ticket INT UNSIGNED NULL AFTER reason"
)
BROKEN_SQL = (
    "SELECT quest, guid, character_name, reason, ticket FROM overseer_quest_ledger "
    "WHERE state = %s ORDER BY quest, guid"
)
COMPLETED_SQL = "SELECT DISTINCT quest FROM overseer_quest_ledger WHERE state = %s"
# A refusal the world gave one quester at its place and in its bags: the take or
# the hand-in was turned down ("no giver in reach", "not eligible", "the core
# will not reward it now"). Where another quester has completed the quest, such
# a row says nothing about the quest, so it files nothing by itself.
QUESTER_REFUSALS = (
    "the quest giver would not give it",
    "the turn-in NPC would not take it",
)
# The quester ledger keeps a broken reason once written. Explain this stored
# reason from the quest's world rows when it has no objective rows.
SCRIPTED_EVENT_REASON = (
    "the quest completes only by a scripted event no lone quester drives"
)
SCRIPTED_EVENT_NOTE = (
    "The world rows list no required item or creature/object objectives, "
    "so the stored reason is the only evidence of how it completes: a scripted event."
)
# The stored take reason from questers._giver_failure and the module's
# QuestErrandRefusal. The module uses different reasons for an object
# starter and for a quest without a starter relation.
NO_GIVER_IN_REACH = "the quest giver would not give it: no giver of that quest in reach"
TICKET_SQL = (
    "SELECT ticket FROM overseer_quest_ledger "
    "WHERE quest = %s AND ticket IS NOT NULL ORDER BY ticket DESC LIMIT 1"
)
LAST_PASS_SQL = (
    "SELECT since FROM overseer_bridge_memo WHERE kind = %s AND subject = %s"  # noqa: S105 - filing pass time, not a password
)
RECORD_PASS_SQL = (
    "INSERT INTO overseer_bridge_memo (kind, subject, value, since, expires) "  # noqa: S105 - filing pass time, not a password
    "VALUES (%s, %s, '{}', %s, %s) "
    "ON DUPLICATE KEY UPDATE since = VALUES(since), expires = VALUES(expires)"
)
SET_TICKET_SQL = (
    "UPDATE overseer_quest_ledger SET ticket = %s "
    "WHERE quest = %s AND state = %s AND ticket IS NULL"
)
FILED_SQL = (
    "UPDATE overseer_quest_ledger SET ticket = %s WHERE quest = %s AND ticket = %s"
)
RELEASE_SQL = (
    "UPDATE overseer_quest_ledger SET ticket = NULL WHERE quest = %s AND ticket = %s"
)
OBJECTIVES_SQL = (
    "SELECT guid, mobcount1, mobcount2, mobcount3, mobcount4, itemcount1, "
    "itemcount2, itemcount3, itemcount4, itemcount5, itemcount6 "
    "FROM character_queststatus WHERE quest = %s"
)
OBJECTIVE_COLUMNS = (
    "mobcount1",
    "mobcount2",
    "mobcount3",
    "mobcount4",
    "itemcount1",
    "itemcount2",
    "itemcount3",
    "itemcount4",
    "itemcount5",
    "itemcount6",
)


def ensure_column(cur) -> None:
    """Add `ticket` to a ledger table made before it existed. MySQL has no
    ADD COLUMN IF NOT EXISTS, so the catalog is asked first."""
    cur.execute(HAS_COLUMN_SQL)
    row = cur.fetchone()
    if not (row and int(row["n"])):
        cur.execute(ADD_COLUMN_SQL)


@dataclass(frozen=True)
class Plan:
    new: tuple  # (quest, rows) to file, oldest quest id first
    copies: tuple  # (quest, ticket): rows of a filed quest with no number yet
    stuck: tuple  # quest ids left at FILING by a filing that never finished


def _quest_ticket(group, quest: int, ticket_for) -> tuple[int | None, bool]:
    """(filed_ticket, has_filing_in_flight) for a quest's rows."""
    tickets = [r["ticket"] for r in group if r.get("ticket") is not None]
    filed = next((int(t) for t in tickets if int(t) != FILING), None)
    if filed is not None:
        return filed, False
    if tickets:
        return None, True
    if ticket_for:
        num = ticket_for(quest) if callable(ticket_for) else ticket_for.get(quest)
        if num is not None:
            if int(num) == FILING:
                return None, True
            return int(num), False
    return None, False


def _quester_bound(group) -> bool:
    """Every broken row of the quest is a refusal to one quester."""
    return all(str(r.get("reason") or "").startswith(QUESTER_REFUSALS) for r in group)


def plan(rows, ticket_for=None, completed=()) -> Plan:
    """What a pass does with the broken rows of the ledger. A quest in
    `completed` (some quester finished it) whose broken rows are all
    quester-bound refusals is not filed: the quest works."""
    by_quest: dict = {}
    for row in rows or ():
        by_quest.setdefault(int(row["quest"]), []).append(row)
    new, copies, stuck = [], [], []
    for quest, group in sorted(by_quest.items()):
        filed, has_filing = _quest_ticket(group, quest, ticket_for)
        tickets = [r["ticket"] for r in group if r.get("ticket") is not None]
        if filed is not None:
            if len(tickets) < len(group):
                copies.append((quest, filed))
        elif has_filing:
            stuck.append(quest)
        elif quest in completed and _quester_bound(group):
            continue
        else:
            new.append((quest, tuple(group)))
    return Plan(tuple(new), tuple(copies), tuple(stuck))


def initial_delay(
    last_pass: float | None,
    cycle: float,
    now: float,
    startup: float = 300.0,
) -> float:
    """How long the loop sleeps before its first pass.

    A fresh realm or an idle one waits min(cycle, startup) so the realm is
    up before the pass runs. When a pass ran inside cycle, a restart waits
    the rest of the cycle so a restart never starts a second pass inside a day.
    """
    if last_pass is None:
        return min(cycle, startup)
    elapsed = now - last_pass
    if elapsed < 0:
        return min(cycle, max(startup, cycle))
    if elapsed >= cycle:
        return min(cycle, startup)
    return max(min(cycle, startup), cycle - elapsed)


def url(number: int) -> str:
    return "https://github.com/%s/issues/%d" % (REPO, int(number))


def ticket_of(rows) -> dict | None:
    """The API's ticket for a quest's ledger rows: {number, url}, or None."""
    for row in rows or ():
        number = row.get("ticket")
        if number is not None and int(number) != FILING:
            return {"number": int(number), "url": url(int(number))}
    return None


def party_of(name: str) -> str:
    """The quester's guild and the names beside it in its questing party."""
    guild = questledger.guild_of(name)
    names = [q.name for q in raidteams.QUESTERS.get(guild, ()) if q.name != name]
    return "%s: %s" % (guild, ", ".join(names)) if guild else "party not measured"


def _objectives(row) -> str:
    if not row:
        return "not in the log now"
    return (
        ", ".join(
            "%s %d" % (c, int(row.get(c) or 0))
            for c in OBJECTIVE_COLUMNS
            if int(row.get(c) or 0)
        )
        or "all zero"
    )


def title(quest: int, info) -> str:
    return "Quest %d is broken: %s" % (
        quest,
        info.title if info else "not in the catalogue",
    )


def _world_rows(info) -> list[str]:
    """Render the catalogue's objective and source rows for a ticket."""
    lines = ["## World rows", ""]
    if info is None:
        return lines + ["World rows are not in the catalogue.", ""]
    lines.extend(
        [
            "- QuestLevel: %s; MinLevel: %s"
            % (
                getattr(info, "level", "not measured"),
                getattr(info, "min_level", "not measured"),
            ),
        ]
    )
    if getattr(info, "follows", 0):
        lines.append("- Previous quest: %d" % info.follows)
    for item in getattr(info, "items", ()):
        label = item["name"] or "item"
        source = []
        if item.get("provided"):
            source.append("provided when this quest is accepted")
        if item["droppers"]:
            source.append("creature entries " + ", ".join(map(str, item["droppers"])))
        if item["rewards"]:
            source.append("rewarded by quests " + ", ".join(map(str, item["rewards"])))
        if item.get("objects"):
            source.append(
                "gameobject loot entries " + ", ".join(map(str, item["objects"]))
            )
        if item["vendors"]:
            source.append(
                "sold by vendor entries " + ", ".join(map(str, item["vendors"]))
            )
        lines.append(
            "- Required item %d x%d (%s): %s"
            % (
                item["id"],
                item["count"],
                label,
                "; ".join(source) or "no source in the world rows",
            )
        )
    for objective in getattr(info, "objectives", ()):
        label = objective["name"] or "objective"
        lines.append(
            "- Required creature/object %d x%d (%s): %d spawn(s) on the quest's map, %d total"
            % (
                objective["entry"],
                objective["count"],
                label,
                objective["map_count"],
                objective["total_count"],
            )
        )
    if not getattr(info, "items", ()) and not getattr(info, "objectives", ()):
        lines.append("- No required item or creature/object rows.")
    return lines + [""]


def body(quest: int, info, rows, objectives, site: str) -> str:
    """The issue body. `site` is the site's public base; without one the
    Quests page is named by its route, since no host may be guessed."""
    counts = {int(r["guid"]): r for r in objectives or ()}
    lines = [
        "## Why",
        "",
        "The questers found this quest cannot be finished, and a broken quest "
        "stays broken until a ticket reaches someone who can fix it.",
        "",
        "## What",
        "",
        "Find out why this quest cannot be finished, and fix it.",
        "",
        "- Quest: %d, %s" % (quest, info.title if info else "not in the catalogue"),
        "- Zone: %s" % (info.zone_name if info and info.zone_name else "not measured"),
        "- Level: %s" % (info.level if info else "not measured"),
        "- Quests page: %s#/quests/%d"
        % (site.rstrip("/") + "/" if site else "", quest),
        "",
    ]
    lines.extend(_world_rows(info))
    no_giver_in_reach = False
    scripted_event = False
    for row in rows:
        name = str(row.get("character_name") or "")
        reason = row.get("reason") or "no reason recorded"
        no_giver_in_reach |= reason == NO_GIVER_IN_REACH
        scripted_event |= reason == SCRIPTED_EVENT_REASON
        lines += [
            "- Quester: %s (%s)" % (name, party_of(name)),
            "  - Reason: %s" % reason,
            "  - Last objective counts: %s" % _objectives(counts.get(int(row["guid"]))),
        ]
    if (
        scripted_event
        and info is not None
        and not getattr(info, "items", ())
        and not getattr(info, "objectives", ())
    ):
        lines += ["", SCRIPTED_EVENT_NOTE]
    if no_giver_in_reach:
        lines += [
            "",
            "The take step asks the world for a living creature linked to the quest "
            "within the 20-yard arrival radius. The refusal means none matched then; "
            "the stored rows do not distinguish a missing, distant, dead, or otherwise "
            "unavailable creature.",
        ]
    lines += [
        "",
        "## Acceptance criteria",
        "",
        "- [ ] A quester can finish this quest, or the ticket says why no one can",
        "- [ ] A test or a ledger row shows it",
        "- [ ] The ledger reason is gone or explained",
        "",
        "## Size",
        "",
        "S",
        "",
        "## Out of scope",
        "",
        "Any other broken quest. A reason string keyed on this quest's id: "
        "lanes cannot read the live world, and such strings have claimed causes "
        "the world database contradicts (#1953). Name a cause only from the "
        "world rows above or a fixture of them.",
        "",
        "Part of #%d" % EPIC,
    ]
    return "\n".join(lines)


class SqlStore:
    """The ledger through a cursor."""

    def __init__(self, cur):
        self.cur = cur

    def broken(self) -> list:
        self.cur.execute(BROKEN_SQL, (questledger.BROKEN,))
        return list(self.cur.fetchall())

    def completed(self) -> list:
        self.cur.execute(COMPLETED_SQL, (questledger.COMPLETED,))
        return [int(r["quest"]) for r in self.cur.fetchall()]

    def objectives(self, quest: int) -> list:
        self.cur.execute(OBJECTIVES_SQL, (quest,))
        return list(self.cur.fetchall())

    def ticket(self, quest: int) -> int | None:
        self.cur.execute(TICKET_SQL, (quest,))
        row = self.cur.fetchone()
        return int(row["ticket"]) if row and row.get("ticket") is not None else None

    def last_pass(self) -> float | None:
        self.cur.execute(LAST_PASS_SQL, (MEMO_KIND, MEMO_SUBJECT))
        row = self.cur.fetchone()
        return float(row["since"]) if row and row.get("since") is not None else None

    def record_pass(self, when: float) -> None:
        self.cur.execute(
            RECORD_PASS_SQL,
            (MEMO_KIND, MEMO_SUBJECT, float(when), float(when) + 30 * 86400.0),
        )

    def take(self, quest: int, ticket: int) -> None:
        self.cur.execute(SET_TICKET_SQL, (ticket, quest, questledger.BROKEN))

    def filed(self, quest: int, ticket: int) -> None:
        self.cur.execute(FILED_SQL, (ticket, quest, FILING))

    def release(self, quest: int) -> None:
        self.cur.execute(RELEASE_SQL, (quest, FILING))


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__:
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, Exception) and reason is not exc:
        return _is_timeout(reason)
    return False


def run(
    store,
    client,
    catalogue,
    site: str = "",
    now: float | None = None,
) -> dict:
    """One pass: {filed, copied, stuck, unlinked}. A refused filing frees its
    quest for the next pass and is raised, so the pass stops and the bridge
    logs it. A timed-out filing stays at FILING so it is not retried before a
    person looks. unlinked lists issues filed but not linked under the epic."""
    ticket_for = getattr(store, "ticket", None)
    done = store.completed() if hasattr(store, "completed") else ()
    todo = plan(store.broken(), ticket_for=ticket_for, completed=frozenset(done))
    for quest, ticket in todo.copies:
        store.take(quest, ticket)
    # The pass time is written before the first POST: a pass that files
    # some issues and then fails has still spent the day, so a restart must
    # not see it as never run.
    if hasattr(store, "record_pass"):
        store.record_pass(time.time() if now is None else float(now))
    known = {q.id: q for q in catalogue or ()}
    filed = 0
    for quest, rows in todo.new[:MAX_PER_PASS]:
        info = known.get(quest)
        text = body(quest, info, rows, store.objectives(quest), site)
        store.take(quest, FILING)
        try:
            number = client.file(title(quest, info), text)
        except Exception as exc:
            if not _is_timeout(exc):
                store.release(quest)
            raise
        store.filed(quest, number)
        filed += 1
    unlinked, client.unlinked = client.unlinked, []
    return {
        "filed": filed,
        "copied": len(todo.copies),
        "stuck": list(todo.stuck),
        "unlinked": unlinked,
    }


class Client:
    """Files an issue and links it under the epic. The link is best kept
    apart: the issue exists by then, so a refused link never files twice. It
    goes on unlinked for the pass to report, not silently."""

    def __init__(self, github, log=None, epic=None):
        self.github, self.log = github, log
        # The epic each issue is linked under: the quest epic unless a caller
        # names another (corpstickets.py files under its own).
        self.epic = EPIC if epic is None else int(epic)
        self.unlinked: list = []

    def file(self, heading: str, text: str, labels=None) -> int:
        """`labels` default to a broken quest's. Any set with no `area:`
        label, or more than one, is refused before a request is made."""
        labels = list(LABELS if labels is None else labels)
        areas = [x for x in labels if str(x).startswith("area:")]
        if len(areas) != 1:
            raise ValueError(
                "a filed ticket carries exactly one area: label, got %r" % (areas,)
            )
        made = self.github.call(
            "POST",
            "/issues",
            {"title": heading, "body": text, "labels": labels},
            ok=(201,),
        ).json()
        try:
            self.github.call(
                "POST",
                "/issues/%d/sub_issues" % self.epic,
                {"sub_issue_id": made["id"]},
                ok=(201,),
            )
        except Exception:
            self.unlinked.append(int(made["number"]))
            if self.log:
                self.log.exception(
                    "tickets: #%d is not linked under #%d", made["number"], self.epic
                )
        return int(made["number"])


def client_from_env(log=None, env=None, epic=None) -> Client | None:
    """The client when the App's settings are all present, else None."""
    env = os.environ if env is None else env
    app_id = env.get("QUEST_TICKET_APP_ID", "").strip()
    installation = env.get("QUEST_TICKET_INSTALLATION_ID", "").strip()
    key_path = env.get("QUEST_TICKET_KEY_PATH", "").strip()
    if not (app_id and installation and key_path):
        return None
    import realmroller_act as act

    token = act.AppToken(
        app_id, installation, key_path, REPO, permissions=TOKEN_PERMISSIONS
    )
    return Client(act.GitHub(REPO, token), log, epic)
