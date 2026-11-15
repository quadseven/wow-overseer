"""The operator hold: one row that stands a family's automatic planning down (#2403).

An operator who wanted to drive a family by hand had to switch the campaign
planner, the activity choice and the attunement step off one environment
variable at a time, each needing a bridge restart, and every restart started
the council again (it writes a goal about two minutes after a start) and the
town errands with it. The leveling route had no switch at all. And the planner
switch alone never stopped the queue stepping an entry already queued.

ONE ROW, PER FAMILY, READ EVERY PASS. `overseer_operator_hold` holds a row per
family (the roster's `family` value, matched without case) or `*` for every
family. A row with an `expires_at` in the past holds nothing; NULL holds until
the row is deleted. The bridge reads the table on every pass of every writer it
covers, so setting or clearing a hold takes effect on the next pass with no
restart.

WHAT A HOLD STOPS. For a held family the bridge writes no job, goal, queue
entry or travel aim from these passes, and says one line per writer, at most
every SAY_EVERY_SECONDS, "held by operator: <reason>":

  * the campaign queue pass: the planner, the attunement step, the Upper
    Spire pass, the trade turn, the dungeon quests, town first and the queue
    step itself (an entry already queued is not stepped);
  * the council (no scene, no goal);
  * the activity choice;
  * the leveling route.

WHAT A HOLD LEAVES RUNNING. The bag, bank, mail, vendor and craft passes that
act inside the job the family already has, and the craft rhythm, which only
ever moves between gather and craft. A hold also undoes nothing: a job or aim
already written stays. Set the job the family should hold from the console.

THE ENVIRONMENT SWITCHES STILL WORK. CAMPAIGN_PLANNER, ATTUNEMENT_STEP and
JEV_MODE_ACTIVITY_CHOICE switched off still stop their writer for every family
at start; a hold stops it for one family without a restart. Either one off is
off.

SET AND CLEAR IT WITH ONE STATEMENT on acore_characters:

    INSERT INTO overseer_operator_hold (family, reason, expires_at, source)
    VALUES ('Grug', 'driving by hand', UTC_TIMESTAMP() + INTERVAL 4 HOUR, 'sql')
    ON DUPLICATE KEY UPDATE reason = VALUES(reason),
      expires_at = VALUES(expires_at), source = VALUES(source);

    DELETE FROM overseer_operator_hold WHERE family = 'Grug';

PURE MODULE, the same seam as priorities.py: rows in, decisions and lines out.
The bridge creates the table with CREATE_SQL when it starts and reads it with
SELECT_SQL.
"""

from __future__ import annotations

from dataclasses import dataclass

TABLE = "overseer_operator_hold"

# The family value that holds every family.
EVERY_FAMILY = "*"

# How often one writer repeats its line for one family while the hold stands.
SAY_EVERY_SECONDS = 600.0

# expires_at is UTC and is judged by the database's own clock in SELECT_SQL,
# so the bridge's zone never decides whether a hold is still live.
CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_operator_hold ("
    " family VARCHAR(32) NOT NULL,"
    " reason VARCHAR(255) NOT NULL DEFAULT '',"
    " expires_at DATETIME NULL DEFAULT NULL,"
    " source VARCHAR(64) NOT NULL DEFAULT '',"
    " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    " ON UPDATE CURRENT_TIMESTAMP,"
    " PRIMARY KEY (family)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

SELECT_SQL = (
    "SELECT family, reason, source, expires_at, "
    "(expires_at IS NULL OR expires_at > UTC_TIMESTAMP()) AS live "
    "FROM overseer_operator_hold"
)


@dataclass(frozen=True)
class Hold:
    """One live hold. `expires_at` is as the row gave it, or None."""

    family: str
    reason: str
    source: str = ""
    expires_at: object = None


def _live(row: dict) -> bool:
    try:
        return int(row.get("live", 1) or 0) == 1
    except (TypeError, ValueError):
        return False


def read(rows) -> dict:
    """lower-cased family -> Hold, for the live rows of SELECT_SQL."""
    out: dict = {}
    for row in rows or []:
        family = str(row.get("family") or "").strip()
        if not family or not _live(row):
            continue
        out[family.lower()] = Hold(
            family=family,
            reason=str(row.get("reason") or "").strip(),
            source=str(row.get("source") or ""),
            expires_at=row.get("expires_at"),
        )
    return out


def held(holds: dict, family: str):
    """The Hold that covers `family`, or None. The family's own row first,
    then the every-family row."""
    holds = holds or {}
    key = str(family or "").strip().lower()
    if key and key in holds:
        return holds[key]
    return holds.get(EVERY_FAMILY)


def line(writer: str, who: str, hold: Hold) -> str:
    """The one line a held writer says."""
    until = "until %s UTC" % hold.expires_at if hold.expires_at else "until cleared"
    return "%s: %s held by operator: %s (%s; it writes nothing)" % (
        writer,
        who,
        hold.reason or "no reason given",
        until,
    )


class Notice:
    """Says a held writer's line once per window, and again when the reason
    changes."""

    def __init__(self, every: float = SAY_EVERY_SECONDS):
        self.every = every
        self._said: dict = {}

    def due(self, writer: str, family: str, hold: Hold, now: float) -> bool:
        key = (writer, str(family or "").lower())
        said = self._said.get(key)
        if said is not None and said[0] == hold.reason and now - said[1] < self.every:
            return False
        self._said[key] = (hold.reason, now)
        return True
