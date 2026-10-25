"""Jev's record, as sentences for the Decree console (#95).

The bridge writes one overseer_jev_judgment row per changed comparison: the
heuristic's answer, Jev's, the confidence, and which of the two the world got
(`acted`). This turns the recent rows into what the page draws: one line per
decision kind (how often the two agreed, how sure Jev was, how often its
answer was carried out) and one line per recent comparison. The page sets
textContent and composes nothing.

PURE: rows in, a dict of strings out. map_server reads the rows.
"""

from __future__ import annotations

TITLE = "Jev"
LEDE = (
    "Jev is asked the same questions the heuristics answer. Where a kind acts "
    "and Jev is sure enough, its answer is the one carried out; otherwise the "
    "heuristic's is. One record per changed answer."
)
EMPTY = (
    "No comparison is on record yet. With no key, or with every kind off, Jev "
    "is never asked, and the heuristics decide alone."
)

# What each kind asks, in words. A kind not named here is shown by its key.
KINDS = {
    "weapon_choice": "Weapon choice",
    "item_disposition": "What to do with a carried item",
    "guild_recipient": "Who in the guild gains most from an item",
    "dungeon_choice": "The next dungeon a family runs",
    "leveling_zone": "Where a family levels next",
    "quest_pick": "The family's quest",
    "profession_choice": "A family member's professions",
    "activity_choice": "A family's next activity",
    "movement": "How a family gets moving again",
    "family_intent": "What a family's leader is doing now",
    "item_keep": "What to do with a protected non-gear item",
    # Kinds added after this table was written, which the page showed by
    # their key ("raid_supply") until #567.
    "raid_supply": "Raid supplies to make or buy",
    "loot_council": "Who gets a dropped item",
    "guild_composition": "Which guild members form a group",
    "guild_dungeon": "Which dungeon a guild group runs",
    "run_recovery": "How a dungeon run recovers",
    "staging_stall": "What to do when a run cannot gather",
    "dungeon_step": "Whether a wiping family steps down to an easier dungeon",
}

# The protected non-gear items (#232) get their own short list: only where
# Jev and the heuristic differ, which is the part worth reading. They are
# asked often and would otherwise crowd every other kind out of `recent`.
KEEP_KIND = "item_keep"
KEEP_TITLE = "Protected items where Jev would differ"
KEEP_EMPTY = "No protected item on record where Jev and the heuristic differ."
KEEP_ROWS = 8

_ACTED = {
    "jev": "Jev's answer was carried out",
    "both": "both agreed, and that was carried out",
    "heuristic": "the heuristic's answer was carried out",
}


def _label(kind: str) -> str:
    return KINDS.get(str(kind), str(kind))


def _times(n: int) -> str:
    return "once" if n == 1 else "%d times" % n


def kind_line(kind: str, rows: list) -> str:
    """One kind's summary over its rows (newest first)."""
    answered = [r for r in rows if r.get("jev")]
    agreed = sum(1 for r in answered if r.get("agree"))
    confidences = [
        float(r["confidence"]) for r in answered if r.get("confidence") is not None
    ]
    mode = str(rows[0].get("mode") or "?") if rows else "?"
    parts = ["%s, %s:" % (_label(kind), mode)]
    parts.append(
        "%d record%s, %d answered"
        % (len(rows), "" if len(rows) == 1 else "s", len(answered))
    )
    if answered:
        parts[-1] += ", agreed on %d of %d (%d%%)" % (
            agreed,
            len(answered),
            round(100.0 * agreed / len(answered)),
        )
    if confidences:
        parts[-1] += ", mean confidence %.2f" % (sum(confidences) / len(confidences))
    carried = sum(1 for r in rows if r.get("acted") == "jev")
    parts[-1] += "; Jev's answer carried out %s." % _times(carried)
    return " ".join(parts)


def recent_line(row: dict) -> str:
    """One comparison: who, what, both answers, and which one acted."""
    subject = str(row.get("subject") or "?")
    thing = str(row.get("item_name") or "")
    about = "%s, %s" % (subject, thing) if thing else subject
    heuristic = str(row.get("heuristic") or "?")
    answer = str(row.get("jev") or "")
    if answer:
        confidence = row.get("confidence")
        sure = " at %.2f" % float(confidence) if confidence is not None else ""
        verdict = "agree" if row.get("agree") else "differ"
        said = "heuristic %s, Jev %s%s (%s)" % (heuristic, answer, sure, verdict)
    else:
        said = "heuristic %s, Jev gave no answer (%s)" % (
            heuristic,
            str(row.get("status") or "unknown"),
        )
    acted = _ACTED.get(str(row.get("acted") or ""), "who acted was not recorded")
    line = "%s: %s. %s; %s." % (_label(row.get("kind")), about, said, acted)
    facts = str(row.get("facts") or "").strip()
    return "%s Given: %s." % (line, facts) if facts else line


def keep_line(row: dict) -> str:
    """One item_keep disagreement: holder, item, both answers and why."""
    confidence = row.get("confidence")
    sure = " at %.2f" % float(confidence) if confidence is not None else ""
    return "%s, %s: heuristic %s, Jev %s%s (%s)." % (
        str(row.get("subject") or "?"),
        str(row.get("item_name") or "?"),
        str(row.get("heuristic") or "?"),
        str(row.get("jev") or "?"),
        sure,
        str(row.get("mode") or "?"),
    )


COMPARE = "compare"


def _percentile(values: list, pct: float) -> int:
    """Nearest-rank percentile of a non-empty list (the same rule as the
    bridge's hourly tally, jev.Tally)."""
    ordered = sorted(values)
    rank = max(1, -(-int(pct * len(ordered)) // 100))
    return int(ordered[min(rank, len(ordered)) - 1])


def _spread(rows: list) -> str:
    """ ", p50 N ms, p95 N ms" over the answered rows' round trip, or ""."""
    latencies = [int(r.get("latency_ms") or 0) for r in rows if r.get("jev")]
    if not latencies:
        return ""
    return ", p50 %d ms, p95 %d ms" % (
        _percentile(latencies, 50),
        _percentile(latencies, 95),
    )


def backend_kind_line(backend: str, kind: str, rows: list) -> str:
    """One comparison backend's record on one decision kind: how often it
    agreed with the active backend and how long it took, next to the other
    backends' lines of the same kind (#822)."""
    answered = [r for r in rows if r.get("jev")]
    judged = [r for r in answered if r.get("agree") is not None]
    agreed = sum(1 for r in judged if r.get("agree"))
    text = "%s, %s: %d question%s, %d answered" % (
        backend,
        _label(kind),
        len(rows),
        "" if len(rows) == 1 else "s",
        len(answered),
    )
    if judged:
        text += ", agreed on %d of %d (%d%%)" % (
            agreed,
            len(judged),
            round(100.0 * agreed / len(judged)),
        )
    text += _spread(rows)
    errors = len(rows) - len(answered)
    return text + ", %d error%s." % (errors, "" if errors == 1 else "s")


def backend_line(backend: str, rows: list) -> str:
    """One comparison backend's summary: its answers set beside the active
    backend's on the identical questions (#820)."""
    answered = [r for r in rows if r.get("jev")]
    judged = [r for r in answered if r.get("agree") is not None]
    agreed = sum(1 for r in judged if r.get("agree"))
    errors = sum(1 for r in rows if not r.get("jev"))
    latencies = [int(r.get("latency_ms") or 0) for r in answered]
    parts = "%d question%s, %d answered" % (
        len(rows),
        "" if len(rows) == 1 else "s",
        len(answered),
    )
    if judged:
        parts += ", agreed on %d of %d (%d%%)" % (
            agreed,
            len(judged),
            round(100.0 * agreed / len(judged)),
        )
    if latencies:
        parts += ", mean latency %d ms" % (sum(latencies) // len(latencies))
        parts += _spread(answered)
    parts += ", %d error%s" % (errors, "" if errors == 1 else "s")
    return "%s, asked alongside the active backend, never acting: %s." % (
        backend,
        parts,
    )


def _split_compare(rows) -> tuple:
    """(the judgment rows, comparison rows by backend)."""
    own, compared = [], {}
    for r in rows or ():
        if str(r.get("mode")) == COMPARE:
            compared.setdefault(str(r.get("backend") or "?"), []).append(r)
        else:
            own.append(r)
    return own, compared


def _by_kind(rows: list) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(str(r.get("kind") or "?"), []).append(r)
    return out


def view(rows, recent: int = 12) -> dict:
    """The Decree's Jev card from overseer_jev_judgment rows, newest first."""
    rows, compared = _split_compare(rows)
    by_kind: dict = {}
    for row in rows:
        by_kind.setdefault(str(row.get("kind") or "?"), []).append(row)
    order = [k for k in KINDS if k in by_kind] + sorted(
        k for k in by_kind if k not in KINDS
    )
    return {
        "title": TITLE,
        "lede": LEDE,
        "kinds": [kind_line(k, by_kind[k]) for k in order],
        "recent": [recent_line(r) for r in rows if str(r.get("kind")) != KEEP_KIND][
            : max(0, int(recent))
        ],
        "backends": [backend_line(b, compared[b]) for b in sorted(compared)],
        "backend_kinds": [
            backend_kind_line(b, k, kind_rows)
            for b in sorted(compared)
            for k, kind_rows in sorted(_by_kind(compared[b]).items())
        ],
        "empty": EMPTY,
        "keep_title": KEEP_TITLE,
        "keep_differ": [
            keep_line(r)
            for r in rows
            if str(r.get("kind")) == KEEP_KIND and r.get("jev") and not r.get("agree")
        ][:KEEP_ROWS],
        "keep_empty": KEEP_EMPTY,
    }
