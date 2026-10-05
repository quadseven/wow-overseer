"""What followed each time Jev overrode the heuristic, kept and fed back (#584).

WHY THIS EXISTS. #583 found that the kinds which override the heuristic most
(activity_choice, family_intent and others: 1,786 overrides) record no outcome
at all, so nobody can tell whether those overrides were better or worse, and
Jev, which is stateless per request, never sees what its earlier answers led
to. jev_recovery is the pattern that works: record what followed each
decision, then show the next question the recent outcomes of the same kind of
choice. This module is that pattern made reusable.

HOW IT WORKS.

  record   When a kind's answer is carried out over the heuristic's
           (acted = jev), the bridge writes one overseer_jev_outcome row:
           the kind, the family, what Jev chose instead of what, its
           confidence, and `before`, a small snapshot the kind defines.
  score    The next time that family is asked the same kind, after at least
           the kind's own wait, each open row is scored: the kind turns
           `before` and the facts now into one line (`outcome`), written
           once. A row never scored (the family went quiet) stays open.
  feed     The kind's question carries the last HISTORY_LIMIT scored rows
           of that kind, every family, oldest first (`history`), the way
           jev_recovery carries `recent_recoveries_and_what_followed`.

The rows are the record a later pass can score by hand or by query; the kind
decides what "what followed" means, because only it knows what it changed.

PURE: SQL and row shaping only; the bridge runs the statements.
"""

from __future__ import annotations

import json

HISTORY_LIMIT = 8

TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_jev_outcome ("
    " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " kind VARCHAR(32) NOT NULL,"
    " subject VARCHAR(24) NOT NULL,"
    " chose VARCHAR(40) NOT NULL,"
    " instead_of VARCHAR(40) NOT NULL,"
    " confidence FLOAT NULL DEFAULT NULL,"
    " before_state VARCHAR(255) NOT NULL DEFAULT '',"
    " outcome VARCHAR(255) NULL DEFAULT NULL,"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " scored_at TIMESTAMP NULL DEFAULT NULL,"
    " PRIMARY KEY (id), KEY idx_open (kind, subject, scored_at),"
    " KEY idx_kind_time (kind, created_at)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)
INSERT_SQL = (
    "INSERT INTO overseer_jev_outcome (kind, subject, chose, instead_of, "
    "confidence, before_state) VALUES (%s, %s, %s, %s, %s, %s)"
)
OPEN_SQL = (
    "SELECT id, chose, instead_of, before_state, "
    "TIMESTAMPDIFF(MINUTE, created_at, NOW()) AS minutes FROM overseer_jev_outcome "
    "WHERE kind = %s AND subject = %s AND scored_at IS NULL ORDER BY id"
)
# Guarded on the row still open, so two passes cannot score it twice.
SCORE_SQL = (
    "UPDATE overseer_jev_outcome SET outcome = %s, scored_at = NOW() "
    "WHERE id = %s AND scored_at IS NULL"
)
HISTORY_SQL = (
    "SELECT subject, chose, instead_of, confidence, outcome FROM overseer_jev_outcome "
    "WHERE kind = %s AND scored_at IS NOT NULL ORDER BY id DESC LIMIT %s"
)


def record_args(judgment, before: dict) -> tuple | None:
    """INSERT_SQL's arguments for a judgment carried out over the heuristic,
    or None for any other: only an override has an outcome to score."""
    if getattr(judgment, "acted", "") != "jev" or not judgment.jev:
        return None
    return (
        judgment.kind[:32],
        judgment.subject[:24],
        judgment.jev[:40],
        judgment.heuristic[:40],
        judgment.confidence,
        snapshot_text(before),
    )


def snapshot_text(before: dict) -> str:
    """`before` as compact JSON, or "" when it does not fit the column."""
    text = json.dumps(before, sort_keys=True, separators=(",", ":"), default=str)
    return text if len(text) <= 255 else ""


def before_of(row: dict) -> dict:
    """The snapshot an open row was recorded with; {} when unreadable."""
    try:
        value = json.loads(str(row.get("before_state") or "") or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def history(rows: list) -> list:
    """HISTORY_SQL rows (newest first) as the question's list, oldest first."""
    out = []
    for row in reversed(rows):
        confidence = row.get("confidence")
        out.append(
            {
                "family": str(row.get("subject") or ""),
                "jev_chose": str(row.get("chose") or ""),
                "instead_of": str(row.get("instead_of") or ""),
                "confidence": None
                if confidence is None
                else round(float(confidence), 2),
                "then": str(row.get("outcome") or ""),
            }
        )
    return out
