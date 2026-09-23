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
    "dungeon_choice": "The council's dungeon",
    "quest_pick": "The family's quest",
    "profession_choice": "A family member's professions",
    "activity_choice": "A family's next activity",
}

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


def view(rows, recent: int = 12) -> dict:
    """The Decree's Jev card from overseer_jev_judgment rows, newest first."""
    rows = list(rows or ())
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
        "recent": [recent_line(r) for r in rows[: max(0, int(recent))]],
        "empty": EMPTY,
    }
