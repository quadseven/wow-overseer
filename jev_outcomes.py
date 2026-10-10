"""What followed each time Jev overrode the heuristic, kept and fed back (#584).

WHY THIS EXISTS. #583 found that the kinds which override the heuristic most
(activity_choice, family_intent and others: 1,786 overrides) record no outcome
at all, so nobody can tell whether those overrides were better or worse, and
Jev, which is stateless per request, never sees what its earlier answers led
to. jev_recovery is the pattern that works: record what followed each
decision, then show the next question the recent outcomes of the same kind of
choice. This module is that pattern made reusable.

CONTROL ARM (#820). Every disagreement is recorded whichever side acted
(`acted` = jev, heuristic or both), plus a sample of agreements
(JEV_OUTCOME_AGREE_SAMPLE, default 0.1), so the outcome of Jev carried out
can be set against the outcome of the heuristic on the same kind of
question. Only `acted = 'jev'` rows are fed back into a question as history.

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
import os
import random

# The share of AGREEMENTS recorded as a control arm (#820). Every
# disagreement is recorded; without agreements beside them there is nothing
# to compare an override's outcome with.
DEFAULT_SAMPLE = 0.1

HISTORY_LIMIT = 8

TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_jev_outcome ("
    " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " kind VARCHAR(32) NOT NULL,"
    " subject VARCHAR(24) NOT NULL,"
    " chose VARCHAR(40) NOT NULL,"
    " instead_of VARCHAR(40) NOT NULL,"
    " confidence FLOAT NULL DEFAULT NULL,"
    " acted VARCHAR(10) NOT NULL DEFAULT 'jev',"
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
    "confidence, before_state, acted) VALUES (%s, %s, %s, %s, %s, %s, %s)"
)
# A table made before `acted` held only overrides, so the column defaults to
# 'jev' for those rows.
ACTED_COLUMN_SQL = (
    "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
    "WHERE TABLE_SCHEMA = DATABASE() "
    "  AND TABLE_NAME = 'overseer_jev_outcome' AND COLUMN_NAME = 'acted'"
)
ADD_ACTED_SQL = (
    "ALTER TABLE overseer_jev_outcome "
    "ADD COLUMN acted VARCHAR(10) NOT NULL DEFAULT 'jev' AFTER confidence"
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
    "WHERE kind = %s AND scored_at IS NOT NULL AND acted = 'jev' "
    "ORDER BY id DESC LIMIT %s"
)


def sample_rate(environ=None) -> float:
    """JEV_OUTCOME_AGREE_SAMPLE as a probability; unreadable is the default."""
    env = os.environ if environ is None else environ
    raw = str(env.get("JEV_OUTCOME_AGREE_SAMPLE", "") or "").strip()
    if not raw:
        return DEFAULT_SAMPLE
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SAMPLE
    return value if 0.0 <= value <= 1.0 else DEFAULT_SAMPLE


def record_args(
    judgment, before: dict, sample: float | None = None, rand=random.random
) -> tuple | None:
    """INSERT_SQL's arguments for a judgment Jev answered, or None.

    Every disagreement is recorded, whoever acted; an agreement is recorded
    at the sample rate. No answer from Jev has no outcome to score.
    """
    if not getattr(judgment, "jev", ""):
        return None
    if judgment.jev == judgment.heuristic:
        rate = sample_rate() if sample is None else sample
        if rate <= 0.0 or rand() >= rate:
            return None
    acted = str(getattr(judgment, "acted", "") or "heuristic")
    return (
        judgment.kind[:32],
        judgment.subject[:24],
        judgment.jev[:40],
        judgment.heuristic[:40],
        judgment.confidence,
        snapshot_text(before),
        acted[:10],
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
