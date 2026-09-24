"""The loot council: who a dropped item goes to, decided by Jev (#194).

WHY THIS EXISTS. Measured on the dev realm on 2026-09-24: the level 60
Alliance family wore the weakest gear in its own raid, average item level 39
to 45 against the raiders' 67. A group-loot roll puts a drop on whoever wins a
random number, and the raid had no loot rules at all. mod-overseer now runs
the two rules a real guild runs (its #642): need before greed for the family's
party, and master loot under the raid leader for its raid. For every weapon or
armour drop it writes an `overseer_loot_council` row with each candidate
already scored by its own gear rule, and this module answers the row.

THE QUESTION IS ONE CHOICE over the candidates the drop upgrades, plus
"nobody". Each option says who the candidate is (class, talent tree, role, the
tank flag), whether they are in the family, and the size of the upgrade: the
share of the piece's worth that is new to them and the item levels over what
they wear. The instructions give the council's rule in words: family first,
then the biggest real upgrade for the role, then the guild's raiders.

WHO ACTS. `loot_council` acts at 0.75, and an answer that agrees with the
heuristic counts as Jev's at any confidence. 0.75 is guild_recipient's
threshold, set from the same Choice probe (its clear calls answered 0.84 to
0.88 and its toss-ups 0.26 to 0.65). Below it, or with no answer, the
module's heuristic pick stands, and the row says so. Jev is never offered a
member the module did not score as an upgrade, so acting never widens the set.

JEV'S REASON. Jev returns a typed choice and never prose, so the reason the
Chronicle and Bags show is the option Jev chose, word for word, with its
confidence: the same sentence Jev was shown.

PURE: rows in, questions and decisions out. The only I/O is through the Jev
client the caller hands in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

import jev
from jev_items import Judgment
from statweights import UNKNOWN, stat_weights

KIND = "loot_council"
NOBODY = "nobody"
# See the module docstring for 0.75 and the agreement rule.
POLICY_DEFAULTS = dict(default_mode=jev.ACT, default_threshold=0.75, on_agreement=True)

# The row's `decided_by`: Jev's pick where it differed, both where they
# agreed, and the heuristic otherwise. The same three words as jev.ACTED.
DECIDED_BY = (jev.JEV, jev.BOTH, jev.HEURISTIC)

# The row's kinds, as the module writes them.
ROLL = "roll"
MASTER = "master"

# `reason` is VARCHAR(255).
REASON_BYTES = 255

INSTRUCTIONS = (
    "A World of Warcraft guild is handing out `item`, which just dropped, the "
    "way a thoughtful loot council would. `candidates` are the members it "
    "would upgrade, each with their class, talent specialization, role and "
    "how much of the item's worth is new to them over what they wear now. "
    "The family's own members come first, then the guild's raiders. Among "
    "them, give it to the one it improves most in the role they play: stats "
    "that suit the class and specialization (a protection warrior values "
    "stamina, defense, armor and block), and the biggest real upgrade. "
    "Choose nobody only if it is not a real upgrade for anyone."
)


def policy(environ=None) -> jev.Policy:
    return jev.policy(KIND, environ=environ, **POLICY_DEFAULTS)


# ---------------------------------------------------------------------------
# THE ROW


@dataclass(frozen=True)
class Candidate:
    name: str
    family: bool
    wearable: bool
    comparison: str  # better, not_better, undecided
    gain: float
    score: float
    upgrade_percent: int
    item_level_gain: int
    role: str
    class_name: str
    spec: str
    tank: bool
    why: str

    @property
    def upgrades(self) -> bool:
        """Is this a candidate the module scored as an upgrade at all?"""
        return self.wearable and self.comparison in ("better", "undecided")


@dataclass(frozen=True)
class Council:
    key: str
    kind: str
    family: str
    source: str
    item_entry: int
    item_name: str
    candidates: tuple
    heuristic: str  # a name, or "" for nobody
    heuristic_why: str


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def candidates_from_json(text) -> tuple:
    """The module's LootCandidatesJson, parsed; () for anything unreadable."""
    try:
        raw = json.loads(text or "[]")
    except (TypeError, ValueError):
        return ()
    out = []
    for c in raw if isinstance(raw, list) else ():
        if not isinstance(c, dict) or not c.get("name"):
            continue
        out.append(
            Candidate(
                name=str(c["name"]),
                family=bool(c.get("family")),
                wearable=bool(c.get("wearable")),
                comparison=str(c.get("comparison") or "not_better"),
                gain=_float(c.get("gain")),
                score=_float(c.get("score")),
                upgrade_percent=_int(c.get("upgrade_percent")),
                item_level_gain=_int(c.get("item_level_gain")),
                role=str(c.get("role") or UNKNOWN),
                class_name=str(c.get("class") or ""),
                spec=str(c.get("spec") or ""),
                tank=bool(c.get("tank")),
                why=str(c.get("why") or ""),
            )
        )
    return tuple(out)


def council_from_row(row: dict) -> Council | None:
    key = str(row.get("council_key") or "")
    if not key:
        return None
    return Council(
        key=key,
        kind=str(row.get("kind") or ""),
        family=str(row.get("family") or ""),
        source=str(row.get("source") or ""),
        item_entry=_int(row.get("item_entry")),
        item_name=str(row.get("item_name") or ""),
        candidates=candidates_from_json(row.get("candidates")),
        heuristic=str(row.get("heuristic") or ""),
        heuristic_why=str(row.get("heuristic_why") or ""),
    )


# ---------------------------------------------------------------------------
# THE QUESTION


def offered(council: Council) -> tuple:
    """The candidates the question offers: every one the module scored as an
    upgrade, family first, the way the module ranks them."""
    return tuple(
        sorted(
            (c for c in council.candidates if c.upgrades),
            key=lambda c: (
                not c.family,
                c.comparison != "better",
                -c.upgrade_percent,
                c.name,
            ),
        )
    )


def option(c: Candidate) -> str:
    """One candidate as a Choice option, and the reason shown if Jev picks it."""
    who = " ".join(p for p in (c.spec, c.class_name) if p) or "member"
    if c.role and c.role != UNKNOWN:
        who += ", playing " + c.role
    if c.tank:
        who += " (a tank)"
    side = "in the family" if c.family else "a guild raider"
    if c.comparison == "better":
        size = "%d%% of its worth is new to them" % c.upgrade_percent
    else:
        size = "an upgrade the numbers cannot settle"
    levels = (
        ", %+d item levels over what they wear" % c.item_level_gain
        if c.item_level_gain
        else ""
    )
    return "%s gets it: %s, %s; %s%s." % (c.name, who, side, size, levels)


def nobody_option(council: Council) -> str:
    if council.kind == MASTER:
        return "Nobody: it is not a real upgrade for anyone, so the master looter holds it."
    return "Nobody: it is not a real upgrade for anyone, so everybody greeds."


def question(council: Council, item: dict | None):
    """(state, questions) for one drop, or None when nobody is offered."""
    members = offered(council)
    if not members:
        return None
    criteria = {c.name: option(c) for c in members}
    criteria[NOBODY] = nobody_option(council)
    state = {
        "item": item or {"name": council.item_name},
        "dropped_from": council.source or "a roll in the family's party",
        "candidates": [
            {
                "name": c.name,
                "in_the_family": c.family,
                "class": c.class_name,
                "talent_specialization": c.spec,
                "role": c.role,
                "tank": c.tank,
                "upgrade_percent_of_its_worth": c.upgrade_percent,
                "item_levels_over_what_they_wear": c.item_level_gain,
                "certain_upgrade": c.comparison == "better",
                "stat_weights": stat_weights(c.role),
            }
            for c in members
        ],
    }
    return state, {"to": jev.choice(INSTRUCTIONS, criteria)}


# ---------------------------------------------------------------------------
# THE DECISION


@dataclass(frozen=True)
class Decision:
    key: str
    recipient: str  # a name, or "" for nobody
    reason: str
    decided_by: str
    judgment: Judgment


def _fit(text: str) -> str:
    raw = text.encode("utf-8")[:REASON_BYTES]
    return raw.decode("utf-8", "ignore")


def decide(council: Council, outcome: jev.Outcome, rule: jev.Policy) -> Decision:
    """Who gets it, why, and who decided, for one row.

    Jev's pick acts when the policy says so and it is one of the offered
    names (or nobody); otherwise the module's heuristic pick stands.
    """
    heuristic = council.heuristic or NOBODY
    members = offered(council)
    criteria = {c.name: option(c) for c in members}
    criteria[NOBODY] = nobody_option(council)
    base = Judgment(
        kind=KIND,
        subject=council.heuristic or council.family or "-",
        holder=council.family or "-",
        item_guid=0,
        item_entry=council.item_entry,
        item_name=council.item_name,
        heuristic=heuristic,
        heuristic_why=council.heuristic_why,
        mode=rule.mode,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
    )
    answer = None
    if outcome.answers is not None and "to" in outcome.answers:
        answer = outcome.answers["to"]
    if answer is not None:
        base = replace(
            base,
            model=outcome.model,
            jev=answer.choice,
            confidence=answer.confidence,
            probabilities=answer.probabilities,
        )
    fresh = outcome.status in (jev.ANSWERED, jev.CACHED) and answer is not None
    acted = (
        rule.acted(
            heuristic, answer.choice, answer.confidence, answer.choice in criteria
        )
        if fresh
        else jev.HEURISTIC
    )
    judgment = replace(base, acted=acted)
    if acted in (jev.JEV, jev.BOTH):
        pick = answer.choice
        said = "Jev" if acted == jev.JEV else "Jev agreed"
        reason = "%s (%.2f): %s" % (said, float(answer.confidence), criteria[pick])
    else:
        pick = heuristic
        reason = "Heuristic: %s" % (council.heuristic_why or "the biggest upgrade")
        if fresh:
            reason += " (Jev was unsure: %.2f for %s)" % (
                float(answer.confidence),
                answer.choice,
            )
    recipient = "" if pick == NOBODY else pick
    return Decision(council.key, recipient, _fit(reason), acted, judgment)


def skipped(council: Council) -> Decision:
    """The heuristic's decision for a row with nobody to ask about."""
    reason = "Heuristic: %s" % (council.heuristic_why or "nobody it upgrades")
    judgment = Judgment(
        kind=KIND,
        subject=council.heuristic or council.family or "-",
        holder=council.family or "-",
        item_guid=0,
        item_entry=council.item_entry,
        item_name=council.item_name,
        heuristic=council.heuristic or NOBODY,
        heuristic_why=council.heuristic_why,
        mode=jev.OFF,
        status="unasked",
        acted=jev.HEURISTIC,
    )
    return Decision(
        council.key, council.heuristic, _fit(reason), jev.HEURISTIC, judgment
    )


async def answer(client, council: Council, describe, rule: jev.Policy) -> Decision:
    """Ask Jev about one row and decide it. `describe(entry)` is the item card."""
    asked = question(council, describe(council.item_entry))
    if asked is None or rule.mode == jev.OFF:
        return skipped(council)
    state, questions = asked
    wait = float(getattr(client, "timeout", 0.0))
    outcome = await client.ask(KIND, state, questions, wait=wait)
    return decide(council, outcome, rule)


# ---------------------------------------------------------------------------
# WHAT THE CHRONICLE AND BAGS SHOW

EMPTY = "The loot council has not handed anything out in the last fortnight."
BASIS = (
    "Every weapon and armor drop a family's party or raid handed out, newest "
    "first: who got it and why. Jev decides when it is sure; otherwise the "
    "module's own rule does (family first, then the biggest upgrade)."
)
COUNCIL_LIMIT = 60


def _iso(t):
    return t.isoformat() if hasattr(t, "isoformat") else (t or None)


def award(row: dict) -> dict:
    """One row as the page draws it."""
    given = str(row.get("given_to") or "")
    recipient = str(row.get("recipient") or "")
    status = str(row.get("status") or "")
    return {
        "item_entry": _int(row.get("item_entry")),
        "item_name": str(row.get("item_name") or ""),
        "quality": _int(row.get("item_quality")),
        "kind": str(row.get("kind") or ""),
        "family": str(row.get("family") or ""),
        "source": str(row.get("source") or ""),
        "to": given or recipient,
        "status": status,
        "decided_by": str(row.get("decided_by") or ""),
        "reason": str(row.get("reason") or ""),
        "outcome": str(row.get("outcome") or ""),
        "item_guid": _int(row.get("item_guid")),
        "at": _iso(
            row.get("given_at") or row.get("decided_at") or row.get("opened_at")
        ),
    }


def board(rows: list) -> dict:
    """The Chronicle's loot council list: decided rows, newest first."""
    out = [award(r) for r in rows if str(r.get("status") or "") != "open"]
    return {"awards": out[:COUNCIL_LIMIT], "empty": EMPTY, "basis": BASIS}


def by_item_guid(rows: list) -> dict:
    """item guid -> the award, for the rows that reached an item."""
    return {a["item_guid"]: a for a in map(award, rows) if a["item_guid"]}


def said(award_row: dict) -> str:
    """The one line Bags shows under an item the council handed out."""
    who = award_row.get("to") or "nobody"
    source = award_row.get("source")
    head = "Loot council: to %s" % who + (" from %s" % source if source else "")
    reason = award_row.get("reason") or ""
    return "%s. %s" % (head, reason) if reason else head + "."


# The Bags tab's strip, beside guildroute's "04 guild hand-overs".
VIEW_INDEX = "05"
VIEW_LABEL = "loot council"
VIEW_EMPTY = "The loot council has not handed anything out in the last day."


def line(award_row: dict) -> str:
    """One award as a sentence: who got what, from where, and why."""
    who = award_row.get("to") or "nobody"
    item = award_row.get("item_name") or "an item"
    source = award_row.get("source")
    status = award_row.get("status")
    head = "%s to %s%s" % (item, who, " from %s" % source if source else "")
    if status == "failed":
        head += " (not handed over: %s)" % (
            award_row.get("outcome") or "no reason given"
        )
    reason = award_row.get("reason") or ""
    return "%s. %s" % (head, reason) if reason else head + "."


def view(rows: list) -> dict:
    """The Bags tab's loot council strip, and the line each awarded item's
    tooltip carries, keyed by item guid as a string (JSON object keys)."""
    awards = [award(r) for r in rows if str(r.get("status") or "") != "open"]
    return {
        "index": VIEW_INDEX,
        "label": VIEW_LABEL,
        "lines": [line(a) for a in awards[:COUNCIL_LIMIT]],
        "empty": VIEW_EMPTY,
        "by_guid": {str(a["item_guid"]): said(a) for a in awards if a["item_guid"]},
    }


def annotate_tips(payload, by_guid: dict) -> int:
    """Add the loot council's line to the tooltip of every item it handed
    out, wherever the Bags payload draws that item. Returns how many.

    The tooltip line is composed on this side, never in the page (the Bags
    tab's rule), so the council's reason is appended to `tip` here.
    """
    if not by_guid:
        return 0
    count = 0
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            guid = node.get("guid")
            if guid is not None and "tip" in node and str(guid) in by_guid:
                line = by_guid[str(guid)]
                if line not in node["tip"]:
                    node["tip"] = "%s\n%s" % (node["tip"], line)
                    count += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return count
