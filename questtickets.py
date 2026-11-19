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
    retired: tuple  # (quest, ticket): tickets to retire as completed


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


def _retire_tickets(store) -> tuple:
    """Return (quest, ticket) tuples of tickets to retire for completed quests with only quester-bound broken rows."""
    
    retired = []
    completed = store.completed() if hasattr(store, "completed") else ()
    
    broken = store.broken() if hasattr(store, "broken") else []
    by_quest: dict = {}
    for row in broken:
        by_quest.setdefault(int(row["quest"]), []).append(row)
    
    for quest, group in by_quest.items():
        if quest in completed and _quester_bound(group):
            ticket = store.ticket(quest) if hasattr(store, "ticket") else None
            if ticket is not None:
                retired.append((quest, ticket))
    
    return tuple(retired)


def plan(rows, ticket_for=None, completed=()) -> Plan:
    """What a pass does with the broken rows of the ledger. A quest in
    `completed` (some quester finished it) whose broken rows are all
    quester-bound refusals is not filed: the quest works."""
    
    class _Store:
        def __init__(self, rows, completed):
            self.rows = rows
            self._completed = completed
        
        def broken(self):
            return self.rows
        
        def completed(self):
            return self._completed
        
        def ticket(self, quest):
            for row in self.rows:
                if int(row.get("quest")) == quest and row.get("ticket") is not None:
                    return int(row["ticket"])
            return None
    
    store = _Store(rows, completed)
    retired = _retire_tickets(store)
    
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
    return Plan(tuple(new), tuple(copies), tuple(stuck), tuple(retired))