"""The record of every Discord order the bridge acted on (#1499).

WHY. An operator gives the family orders in Discord: a campaign queue, a goal,
a job. Each order's own rows say WHAT the family is doing, and the
`overseer_command` source column says a Discord user asked for a job. Nothing
said, afterwards, who typed which sentence and which rows that sentence
became. quadseven/mod-overseer#150 asks for exactly that: "every order is
queryable afterwards: who, what was said, what was written". This is that
record, one row per order:

    SELECT author, text, kind, rows_written, created_at
      FROM overseer_order ORDER BY id DESC LIMIT 20;

WHAT IS RECORDED. Only an order that wrote something, and only one that came
from a person in Discord (a directive source of `discord:<user id>`). A
refusal or a question changed nothing, so there is nothing to record; an
automatic pass that reuses the same writer (the craft rhythm setting a job,
say) was not an order. Both are filtered by `build`, which returns None.

WRITTEN AFTER THE ORDER, NEVER BEFORE, and a failure to write it never undoes
or blocks the order: the record describes what happened, it is not part of
it. The bridge logs a failed write and carries on.

PURE MODULE: no MySQL, no Discord. The bridge runs CREATE_SQL at start-up and
INSERT_SQL with `Record.params()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

TABLE = "overseer_order"

# Discord's own message limit is 2000 characters, so `text` holds any order
# whole. `rows_written` is TEXT: a job order writes one row per member.
# utf8mb4_0900_ai_ci NAMED, like every other bridge-owned table
# (campaignqueue.CREATE_SQL, tests/test_collation_split.py).
CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_order ("
    "id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, "
    "channel_id VARCHAR(32) NOT NULL DEFAULT '', "
    "author VARCHAR(64) NOT NULL, "
    "text VARCHAR(2000) NOT NULL, "
    "kind VARCHAR(16) NOT NULL, "
    "rows_written TEXT NOT NULL, "
    "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
    "PRIMARY KEY (id), "
    "KEY idx_author_created (author, created_at), "
    "KEY idx_created (created_at)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci "
    "COMMENT='One row per Discord order the bridge acted on: who, what was "
    "said, what was written (wow-overseer#1499)'"
)

INSERT_SQL = (
    "INSERT INTO overseer_order (channel_id, author, text, kind, rows_written) "
    "VALUES (%s, %s, %s, %s, %s)"
)

# The order kinds the bridge records today, one per Discord writer.
QUEUE = "queue"
GOAL = "goal"
JOB = "job"

DISCORD_SOURCE = "discord:"

MAX_TEXT = 2000


@dataclass(frozen=True)
class Written:
    """One row an order wrote: its table and what identifies it there."""

    table: str
    key: str


@dataclass(frozen=True)
class Record:
    channel_id: str
    author: str
    text: str
    kind: str
    rows: tuple

    def rows_json(self) -> str:
        """`rows_written`: a JSON array of {"table", "key"}, in write order."""
        return json.dumps([{"table": r.table, "key": r.key} for r in self.rows])

    def params(self) -> tuple:
        """INSERT_SQL's parameters, in its column order."""
        return (
            self.channel_id[:32],
            self.author[:64],
            self.text[:MAX_TEXT],
            self.kind[:16],
            self.rows_json(),
        )


def build(kind: str, source: str, text: str, channel_id, rows) -> Record | None:
    """The record of one order, or None when there is nothing to record.

    None for an order that wrote no row, and for a write whose source is not
    a person in Discord. `source` is the directive's own (`discord:<id>`),
    kept whole as the author so it reads the same as overseer_command.source.
    """
    rows = tuple(rows or ())
    source = str(source or "")
    if not rows or not source.startswith(DISCORD_SOURCE):
        return None
    return Record(
        channel_id="" if channel_id is None else str(channel_id),
        author=source,
        text=str(text or ""),
        kind=kind,
        rows=rows,
    )


def ids(table: str, row_ids) -> tuple:
    """Written rows for `row_ids` in `table`, keyed `id=<n>`; falsy ids skipped."""
    return tuple(Written(table, "id=%d" % int(i)) for i in row_ids or () if i)
