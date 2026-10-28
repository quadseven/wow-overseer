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

HEURISTIC ARM FROM A COMPARISON (#820). While the active backend gives no
answer (Jev answering 402), a comparison backend's answer is set against the
heuristic's (jev.compare_rows), and each disagreement is recorded here with
`acted = 'heuristic'` and `backend` naming the comparison backend
(`compare_record_args`). It is scored like any other row, so the scorecard
(SCORECARD below) reads what followed when the heuristic acted against that
backend's advice.

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

PURE: SQL and row shaping only; the bridge runs the statements. The stored
scorecard queries (SCORECARD, #820) are at the end.
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
    " backend VARCHAR(12) NOT NULL DEFAULT '',"
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
    "confidence, before_state, acted, backend) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
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
# `backend` arrived with the heuristic arm from a comparison (#820): which
# backend's answer `chose` is. A row written before it reads ''.
BACKEND_COLUMN_SQL = (
    "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
    "WHERE TABLE_SCHEMA = DATABASE() "
    "  AND TABLE_NAME = 'overseer_jev_outcome' AND COLUMN_NAME = 'backend'"
)
ADD_BACKEND_SQL = (
    "ALTER TABLE overseer_jev_outcome "
    "ADD COLUMN backend VARCHAR(12) NOT NULL DEFAULT '' AFTER acted"
)
OPEN_SQL = (
    "SELECT id, chose, instead_of, before_state, "
    "TIMESTAMPDIFF(MINUTE, created_at, NOW()) AS minutes FROM overseer_jev_outcome "
    "WHERE kind = %s AND subject = %s AND scored_at IS NULL ORDER BY id"
)
# A kind's open rows of every subject that have waited at least the given
# minutes, oldest first and bounded: for a kind scored by its own read rather
# than at one family's next question (guild_recipient).
OPEN_KIND_SQL = (
    "SELECT id, subject, chose, instead_of, before_state, "
    "TIMESTAMPDIFF(MINUTE, created_at, NOW()) AS minutes FROM overseer_jev_outcome "
    "WHERE kind = %s AND scored_at IS NULL "
    "AND created_at <= NOW() - INTERVAL %s MINUTE ORDER BY id LIMIT %s"
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
    judgment,
    before: dict,
    sample: float | None = None,
    rand=random.random,
    backend: str = "",
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
        str(getattr(judgment, "backend", "") or backend)[:12],
    )


def compare_record_args(row: dict) -> tuple | None:
    """INSERT_SQL's arguments for one comparison row (jev.compare_rows), or
    None.

    Only a row the client marked with a snapshot is recorded: one set against
    the heuristic, which acted, where the comparison backend disagreed. It is
    the heuristic arm: `chose` is the comparison backend's answer, `instead_of`
    the heuristic's, `acted` heuristic.
    """
    before = row.get("before")
    if not isinstance(before, dict) or not row.get("answer"):
        return None
    return (
        str(row["kind"])[:32],
        str(row.get("subject") or "")[:24],
        str(row["answer"])[:40],
        str(row.get("active_answer") or "")[:40],
        row.get("confidence"),
        snapshot_text(before),
        "heuristic",
        str(row.get("backend") or "")[:12],
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


# ---------------------------------------------------------------------------
# THE SCORECARD (#820), stored as queries.
#
# WHAT IT ANSWERS. For a candidate backend run in compare mode beside the
# heuristic: per decision kind, how many questions it was asked, how often it
# answered, erred or timed out, its latency, how often it agreed with the side
# it was compared with, and, for the kinds that score what followed, which side
# the outcome favoured.
#
# TWO QUERIES, BOTH READ ONLY, both plain SQL that MySQL and SQLite run alike
# (the tests run them on SQLite), with `%s` placeholders and every literal
# percent sign doubled, the way the driver expects:
#
#   JUDGMENT_SQL  (backend, since) -> per kind: the comparison rows
#                 (overseer_jev_judgment, mode `compare`, jev.compare_rows).
#                 A timeout is an ordinary outcome and counts as an error.
#   OUTCOME_SQL   (since) -> per kind, backend and arm (`acted`): the recorded
#                 disagreements (overseer_jev_outcome, this module), how many
#                 were scored, and which side each scored outcome favoured.
#
# WHICH SIDE AN OUTCOME FAVOURED. Each scoring kind writes its own outcome line
# (jev_activity.outcome_words, jev_family_intent.outcome_words,
# jev_items.recipient_outcome_words). READINGS maps a kind to two LIKE patterns
# over that line: one where what followed went the way of the side that ACTED,
# one where it went the way of the side that did not. A heuristic-arm row
# (`acted` heuristic) that went the acted side's way favours the heuristic; a
# Jev-arm row (`acted` jev) that went the acted side's way favours the backend.
# A line matching neither is `unclear`. The readings are weak evidence by
# design: they say what followed, not what would have followed the other way.
#
#   activity_choice   the queue moved (acted side) / did not move (other)
#   family_intent     the request was settled (acted side) / still requested
#                     or the leader is on the other pick anyway (other)
#   guild_recipient   worn by the heuristic pick (acted side, heuristic arm) /
#                     worn by the other pick (other)
#
# Read only; whoever reads the scorecard runs it.

# kind -> (patterns where the acted side was favoured, patterns where the
# other side was). Any pattern matching is enough.
READINGS = {
    "activity_choice": (
        ("%queue now %",),
        ("%the queue did not move%",),
    ),
    "family_intent": (
        ("%no longer requested%",),
        ("%still requested%", "%the leader is still on it%"),
    ),
    "guild_recipient": (
        ("%worn by % (the heuristic pick)%",),
        ("%worn by % (the other pick)%",),
    ),
}

JUDGMENT_SQL = (
    "SELECT kind, COUNT(*) AS questions, "
    "SUM(CASE WHEN status IN ('answered', 'cached') THEN 1 ELSE 0 END) AS answered, "
    "SUM(CASE WHEN status = 'timeout' THEN 1 ELSE 0 END) AS timeouts, "
    "SUM(CASE WHEN status IN ('error', 'timeout', 'invalid') THEN 1 ELSE 0 END) "
    "AS errors, "
    "SUM(CASE WHEN agree = 1 THEN 1 ELSE 0 END) AS agreed, "
    "SUM(CASE WHEN agree = 0 THEN 1 ELSE 0 END) AS disagreed, "
    "AVG(CASE WHEN status = 'answered' THEN latency_ms END) AS mean_ms, "
    "MAX(CASE WHEN status = 'answered' THEN latency_ms END) AS max_ms "
    "FROM overseer_jev_judgment "
    "WHERE mode = 'compare' AND backend = %s AND created_at >= %s "
    "GROUP BY kind ORDER BY questions DESC, kind"
)


def _matches(patterns) -> str:
    """`outcome LIKE p` for each pattern, OR'd; FALSE for none. The patterns
    are this module's constants, never input. A literal % is doubled, since
    the driver formats the query with its `%s` arguments."""
    if not patterns:
        return "1 = 0"
    return (
        "("
        + " OR ".join("outcome LIKE '%s'" % p.replace("%", "%%") for p in patterns)
        + ")"
    )


def _reading(side: int) -> str:
    """A CASE over kind: whether the outcome favoured the acted side (0) or
    the other side (1)."""
    arms = " ".join(
        "WHEN kind = '%s' THEN %s" % (kind, _matches(pair[side]))
        for kind, pair in sorted(READINGS.items())
    )
    return "(CASE %s ELSE 1 = 0 END)" % arms


_ACTED_SIDE = _reading(0)
_OTHER_SIDE = _reading(1)
_SCORED = "scored_at IS NOT NULL"

OUTCOME_SQL = (
    "SELECT kind, backend, acted, COUNT(*) AS disagreements, "
    "SUM(CASE WHEN {scored} THEN 1 ELSE 0 END) AS scored, "
    "SUM(CASE WHEN {scored} AND ((acted = 'jev' AND {other}) "
    "OR (acted <> 'jev' AND {acted})) THEN 1 ELSE 0 END) AS favoured_heuristic, "
    "SUM(CASE WHEN {scored} AND ((acted = 'jev' AND {acted}) "
    "OR (acted <> 'jev' AND {other})) THEN 1 ELSE 0 END) AS favoured_backend, "
    "SUM(CASE WHEN {scored} AND NOT {acted} AND NOT {other} THEN 1 ELSE 0 END) "
    "AS unclear "
    "FROM overseer_jev_outcome "
    "WHERE chose <> instead_of AND created_at >= %s "
    "GROUP BY kind, backend, acted ORDER BY kind, backend, acted"
).format(scored=_SCORED, acted=_ACTED_SIDE, other=_OTHER_SIDE)
