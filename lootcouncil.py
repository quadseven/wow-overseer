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

FIRST CALL. A raiding guild gears its main tank first on a tank's piece, and
its healers first on a healer's piece (mod-overseer's LootCouncilPriority).
Measured on the dev realm on 2026-09-24: Big Bad Pauldrons from Zul'Farrak,
90% survival to a tank, went to the Retribution paladin at 40% new over the
main tank at 36%, and Jev agreed at 0.47. Each candidate now carries
`main_tank`, `role_piece` and `priority` (0 the main tank on a tank's piece,
1 another tank on one, 2 a healer on a healer's piece, 3 everybody else), the
options say so, and the instructions give the rule in words. A row written by
an older module carries none of them, and every candidate reads as priority 3,
which is the ranking it was written with.

THE FIT GATES (#2124). The module scores wearability as proficiency: a
warrior CAN wear mail, so an epic mail piece carrying spirit and intellect
was handed to the main tank as a tank's piece on its armor and stamina
alone, over the shaman whose own armor class mail is and whose stats those
are. When the caller hands over the item card, the council gates on fit
before anything is handed out: a candidate is shut out when their class
does not wear the piece's armor class as their own, or when the piece's
stats beyond stamina are none their role builds on, whenever another
offered candidate fits on both counts. A piece whose stats beyond stamina
are all caster stats is never a tank's piece, whatever its armor says.
With no card to read, or nobody fitting, the gates stay silent and the
council runs as it always has.

A USER BEFORE A GREED ROLL. The case: Kang the Decapitator, an epic
two-handed axe, upgraded nobody in a party of five level 60s, so the
council named nobody and everybody greeded. The priest won it over the warrior and the paladin who could swing it, traded it on,
and the copy was sold to a vendor. A member who can USE a drop outranks a
greed roll by one who cannot: when the decision lands on nobody while the
candidates hold both somebody who can use it (the module's `wearable`) and
somebody who cannot, the piece goes to the best user instead (a fitting
wearer first, the family first, then the module's score). Where everybody
can use it, or nobody can, the greed roll stands: no non-user can win it.
An armor piece moves only to a user it fits, so a leather drop is not
handed to a warrior as a rule.

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
import re
from dataclasses import dataclass, replace

import jev
from jev_items import Judgment
from statweights import CASTER, HEALER, TANK, UNKNOWN, stat_weights

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
    "The family's own members come first, then the guild's raiders. Like a "
    "raiding guild, the council gears its main tank first: a certain upgrade "
    "that is a tank's piece (mostly armor, stamina, defense and block) goes "
    "to the main tank before anyone, then to another tank, even when someone "
    "else would gain a bigger share. A certain upgrade that is a healer's "
    "piece (spirit or mana regeneration) goes to a healer first. Otherwise, "
    "give it to the one it improves most in the role they play: stats that "
    "suit the class and specialization (a protection warrior values stamina, "
    "defense, armor and block), and the biggest real upgrade. Choose nobody "
    "only if it is not a real upgrade for anyone. A piece goes only to a "
    "member whose class wears its armor class as their own when such a "
    "member is among the candidates and the piece's stats fit their role: "
    "plate is the warrior's, paladin's and death knight's own armor, mail "
    "the hunter's and shaman's, leather the rogue's and druid's, cloth the "
    "priest's, mage's and warlock's. A piece whose stats beyond stamina "
    "are all caster stats (intellect, spirit, spell power, mana "
    "regeneration) is a caster's piece, never a tank's, whatever its "
    "armor and stamina say."
)

# LootCouncilPriority's tiers, as the module writes them.
MAIN_TANK_CALL, TANK_CALL, HEALER_CALL, NO_CALL = 0, 1, 2, 3
_CALL_WORDS = {
    MAIN_TANK_CALL: "first call as the main tank on a tank's piece",
    TANK_CALL: "first call as a tank on a tank's piece",
    HEALER_CALL: "first call as a healer on a healer's piece",
}


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
    main_tank: bool = False
    role_piece: bool = False
    priority: int = NO_CALL

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


def _priority(value) -> int:
    """A LootCouncilPriority tier; anything else, or nothing, is no call."""
    tier = _int(value, NO_CALL)
    return tier if tier in (MAIN_TANK_CALL, TANK_CALL, HEALER_CALL) else NO_CALL


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
                main_tank=bool(c.get("main_tank")),
                role_piece=bool(c.get("role_piece")),
                priority=_priority(c.get("priority")),
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
    upgrade, family first, the way the module ranks them (first call before
    the size of the upgrade)."""
    return tuple(
        sorted(
            (c for c in council.candidates if c.upgrades),
            key=lambda c: (
                not c.family,
                c.comparison != "better",
                c.priority,
                -c.upgrade_percent,
                c.name,
            ),
        )
    )


# ---------------------------------------------------------------------------
# THE FIT GATES (#2124)

# The armor class each class wears as its own: gear's armor training table
# (gear.py's _ARMOR_TRAINED_AT) read at the grade the class ends at, plate
# for a warrior from 40, mail for a shaman from 40. The council's row
# carries no candidate level, so the gate reads every class at that final
# grade; where that misreads a young group, no candidate fits and the gate
# stays silent rather than guess.
OWN_ARMOR = {
    "Warrior": "Plate",
    "Paladin": "Plate",
    "Death Knight": "Plate",
    "Hunter": "Mail",
    "Shaman": "Mail",
    "Rogue": "Leather",
    "Druid": "Leather",
    "Priest": "Cloth",
    "Mage": "Cloth",
    "Warlock": "Cloth",
}
ARMOR_KINDS = frozenset(OWN_ARMOR.values())

# The item card's white lines ("+20 Spirit") -> statweights' stat names.
_CARD_STATS = {
    "Agility": "agility",
    "Strength": "strength",
    "Intellect": "intellect",
    "Spirit": "spirit",
    "Stamina": "stamina",
}

# The card's green "Equip:" lines that name a stat statweights prices, as
# (prefix, stat); the first match wins, so spell hit is read before hit.
_EFFECT_STATS = (
    ("Increases defense rating by", "defense"),
    ("Increases your dodge rating by", "dodge"),
    ("Increases your parry rating by", "parry"),
    ("Increases the block value of your shield by", "block_value"),
    ("Improves spell hit rating by", "spell_hit"),
    ("Improves spell critical strike rating by", "crit"),
    ("Improves melee critical strike rating by", "crit"),
    ("Improves ranged critical strike rating by", "crit"),
    ("Improves critical strike rating by", "crit"),
    ("Improves melee hit rating by", "hit"),
    ("Improves ranged hit rating by", "hit"),
    ("Improves hit rating by", "hit"),
    ("Increases spell power by", "spell_power"),
    ("Increases attack power by", "attack_power"),
)

# How a stat is named in a council reason.
_STAT_WORDS = {
    "agility": "agility",
    "strength": "strength",
    "intellect": "intellect",
    "spirit": "spirit",
    "spell_power": "spell power",
    "mana_regeneration": "mana regeneration",
    "defense": "defense",
    "dodge": "dodge",
    "parry": "parry",
    "block_value": "block value",
    "hit": "hit",
    "spell_hit": "spell hit",
    "crit": "critical strike",
    "attack_power": "attack power",
}

# A role builds on a stat it prices above half a point of armor per point;
# the consolation prices (a tank's 0.5 for crit, 0.3 for attack power) do
# not make a piece fit that role.
_FIT_WEIGHT = 0.5


@dataclass(frozen=True)
class _Piece:
    """One drop read from its item card: its armor class, the stats it
    carries (statweights' names, in card order, stamina kept), and whether
    it is a caster's piece."""

    armor_kind: str
    stats: tuple
    caster: bool


def _card_stats(item: dict) -> tuple:
    """The stats an item card names, in card order: the white lines first,
    then the green Equip lines statweights prices."""
    out = []
    for line in item.get("stats") or ():
        parts = str(line).split()
        stat = _CARD_STATS.get(parts[-1]) if parts else None
        if stat and stat not in out:
            out.append(stat)
    for line in item.get("effects") or ():
        text = str(line)
        if text.startswith("Equip: "):
            text = text[len("Equip: ") :]
        stat = None
        if text.startswith("Restores") and "mana per 5 sec" in text:
            stat = "mana_regeneration"
        else:
            for prefix, name in _EFFECT_STATS:
                if text.startswith(prefix):
                    stat = name
                    break
        if stat and stat not in out:
            out.append(stat)
    return tuple(out)


def _piece(item) -> _Piece | None:
    """The fit facts of one drop, or None when there is nothing to gate on:
    no card, or a card for something that is not an armor piece. A weapon's
    fit is a proficiency, which the module already scored as `wearable`."""
    if not isinstance(item, dict):
        return None
    kind = item.get("kind")
    if kind not in ARMOR_KINDS:
        return None
    stats = _card_stats(item)
    defining = [s for s in stats if s != "stamina"]
    tank, healer, caster = (
        stat_weights(TANK),
        stat_weights(HEALER),
        stat_weights(CASTER),
    )
    is_caster = bool(defining) and all(
        tank.get(s, 0) == 0 and (healer.get(s, 0) > 0 or caster.get(s, 0) > 0)
        for s in defining
    )
    return _Piece(kind, stats, is_caster)


def _fits(c: Candidate, piece: _Piece) -> bool:
    """Does this piece fit this candidate: their class wears its armor
    class as their own, and its stats beyond stamina are stats their role
    builds on."""
    if OWN_ARMOR.get(c.class_name) != piece.armor_kind:
        return False
    weights = stat_weights(c.role)
    return any(weights.get(s, 0) > _FIT_WEIGHT for s in piece.stats if s != "stamina")


def _fit_gate(council: Council, item) -> tuple:
    """(shown, piece, shut): the offered candidates, the piece's fit facts,
    and the offered candidates the gates shut out.

    The gates fire only when they can name a wearer: a candidate who fits
    must be among the offered. With nobody fitting, or no facts to read,
    every offered candidate is shown and the council runs as it always has.
    """
    members = offered(council)
    piece = _piece(item)
    if piece is None or not any(_fits(c, piece) for c in members):
        return members, piece, ()
    shown = tuple(c for c in members if _fits(c, piece))
    shut = tuple(c for c in members if not _fits(c, piece))
    return shown, piece, shut


def _stat_words(piece: _Piece) -> str:
    """The piece's stats beyond stamina, as a reason names them."""
    words = [_STAT_WORDS.get(s, s) for s in piece.stats if s != "stamina"]
    if len(words) > 1:
        return ", ".join(words[:-1]) + " and " + words[-1]
    return words[0] if words else "stamina alone"


def _fit_reason(piece: _Piece, replaced: Candidate, pick: Candidate) -> str:
    """Why the gates moved the piece from the module's pick: the armor
    class and the stats, stated in the open."""
    why = []
    if OWN_ARMOR.get(replaced.class_name) != piece.armor_kind:
        why.append(
            "%s is not a %s's own armor class"
            % (piece.armor_kind.lower(), replaced.class_name.lower())
        )
    if piece.caster:
        why.append(
            "its %s are caster stats, not a %s's" % (_stat_words(piece), replaced.role)
        )
    elif not _fits(replaced, piece):
        why.append("its %s do not fit a %s" % (_stat_words(piece), replaced.role))
    return "%s; %s wears %s and the stats fit their role" % (
        "; ".join(why),
        pick.name,
        piece.armor_kind.lower(),
    )


def _gated_pick(members: tuple, shut: tuple, name: str):
    """(pick, replaced) when the fit gates shut out the name a decision was
    about to land on: the first shown candidate takes the piece, and the
    reason names the one replaced. None when the name stands."""
    if not shut or name not in {c.name for c in shut}:
        return None
    replaced = next(c for c in shut if c.name == name)
    return members[0], replaced


def _fit_note(c: Candidate, piece: _Piece | None, shut: tuple) -> str:
    """The fit clause a fitting candidate's option carries when the gates
    shut somebody out: the reasoning, where the council reads it."""
    if not shut or piece is None or not _fits(c, piece):
        return ""
    return "; %s is their own armor class, and its %s fit their role" % (
        piece.armor_kind.lower(),
        _stat_words(piece),
    )


def _tank_call_on_caster_piece(c: Candidate, piece: _Piece | None) -> bool:
    """The module called this candidate first as a tank on a tank's piece,
    and the piece is a caster's: the call does not stand (#2124)."""
    return (
        piece is not None and piece.caster and c.priority in (MAIN_TANK_CALL, TANK_CALL)
    )


def option(c: Candidate, fit_note: str = "", piece: _Piece | None = None) -> str:
    """One candidate as a Choice option, and the reason shown if Jev picks it."""
    who = " ".join(p for p in (c.spec, c.class_name) if p) or "member"
    if c.role and c.role != UNKNOWN:
        who += ", playing " + c.role
    if c.main_tank:
        who += " (the main tank)"
    elif c.tank:
        who += " (a tank)"
    side = "in the family" if c.family else "a guild raider"
    call = None if _tank_call_on_caster_piece(c, piece) else _CALL_WORDS.get(c.priority)
    if call:
        side += ", " + call
    if c.comparison == "better":
        size = "%d%% of its worth is new to them" % c.upgrade_percent
    else:
        size = "an upgrade the numbers cannot settle"
    levels = (
        ", %+d item levels over what they wear" % c.item_level_gain
        if c.item_level_gain
        else ""
    )
    return "%s gets it: %s, %s; %s%s%s." % (c.name, who, side, size, levels, fit_note)


def nobody_option(council: Council) -> str:
    if council.kind == MASTER:
        return "Nobody: it is not a real upgrade for anyone, so the master looter holds it."
    return "Nobody: it is not a real upgrade for anyone, so everybody greeds."


def _criteria(council: Council, members: tuple, piece, shut: tuple) -> dict:
    """The Choice criteria over the shown candidates, plus nobody: the
    question Jev is asked and the decision read from one build, so the
    reason a pick carries is the option that was on the table."""
    criteria = {c.name: option(c, _fit_note(c, piece, shut), piece) for c in members}
    criteria[NOBODY] = nobody_option(council)
    return criteria


def question(council: Council, item: dict | None):
    """(state, questions) for one drop, or None when nobody is offered."""
    members, piece, shut = _fit_gate(council, item)
    if not members:
        return None
    criteria = _criteria(council, members, piece, shut)
    candidates = []
    for c in members:
        facts = {
            "name": c.name,
            "in_the_family": c.family,
            "class": c.class_name,
            "talent_specialization": c.spec,
            "role": c.role,
            "tank": c.tank,
            "main_tank": c.main_tank,
            "a_piece_for_their_role": c.role_piece
            and not _tank_call_on_caster_piece(c, piece),
            "first_call": "none"
            if _tank_call_on_caster_piece(c, piece)
            else _CALL_WORDS.get(c.priority, "none"),
            "upgrade_percent_of_its_worth": c.upgrade_percent,
            "item_levels_over_what_they_wear": c.item_level_gain,
            "certain_upgrade": c.comparison == "better",
            "stat_weights": stat_weights(c.role),
        }
        if piece is not None:
            facts["wears_the_pieces_armor_class"] = (
                OWN_ARMOR.get(c.class_name) == piece.armor_kind
            )
        candidates.append(facts)
    state = {
        "item": item or {"name": council.item_name},
        "dropped_from": council.source or "a roll in the family's party",
        "candidates": candidates,
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


def decide(
    council: Council, outcome: jev.Outcome, rule: jev.Policy, item=None
) -> Decision:
    """Who gets it, why, and who decided, for one row.

    Jev's pick acts when the policy says so and it is one of the offered
    names (or nobody); otherwise the module's heuristic pick stands. The
    item card, when the caller has it, arms the fit gates: a name the
    gates shut out is not an offered name, for Jev or for the heuristic.
    """
    heuristic = council.heuristic or NOBODY
    members, piece, shut = _fit_gate(council, item)
    criteria = _criteria(council, members, piece, shut)
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
    answer = (outcome.answers or {}).get("to")
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
    if fresh and answer.choice in {c.name for c in shut}:
        # An agreement with the heuristic counts as Jev's at any confidence,
        # and the policy's agreement path never asks whether the name may
        # act. A name the fit gates shut out may not act, even by agreement.
        acted = jev.HEURISTIC
    pick, reason = _pick_and_reason(
        council, acted, answer if fresh else None, criteria, members, piece, shut
    )
    recipient = "" if pick == NOBODY else pick
    recipient, reason, moved = _user_over_greed(council, item, recipient, reason)
    if moved:
        acted = jev.HEURISTIC
    judgment = replace(base, acted=acted)
    return Decision(council.key, recipient, _fit(reason), acted, judgment)


def _pick_and_reason(
    council: Council,
    acted: str,
    answer,
    criteria: dict,
    members: tuple = (),
    piece: _Piece | None = None,
    shut: tuple = (),
) -> tuple:
    """(pick, reason): Jev's pick with the option it chose, or the heuristic's
    with its own reason and, when Jev answered, what Jev was unsure of. A
    heuristic pick the fit gates shut out moves to the first shown candidate,
    and the reason says why, in armor and stats."""
    if acted in (jev.JEV, jev.BOTH):
        said = "Jev" if acted == jev.JEV else "Jev agreed"
        reason = "%s (%.2f): %s" % (
            said,
            float(answer.confidence),
            criteria[answer.choice],
        )
        return answer.choice, reason
    fallback = council.heuristic or NOBODY
    gated = _gated_pick(members, shut, fallback)
    if gated is not None:
        pick, replaced = gated
        reason = "Heuristic: %s" % _fit_reason(piece, replaced, pick)
        if answer is not None:
            reason += " (Jev was unsure: %.2f for %s)" % (
                float(answer.confidence),
                answer.choice,
            )
        return pick.name, reason
    reason = "Heuristic: %s" % (council.heuristic_why or "the biggest upgrade")
    if answer is not None:
        reason += " (Jev was unsure: %.2f for %s)" % (
            float(answer.confidence),
            answer.choice,
        )
    return fallback, reason


def _users(council: Council, piece: _Piece | None) -> tuple:
    """The candidates who can use the drop, best first, when a candidate who
    cannot is also present; () when everybody can or nobody can, because a
    greed roll then cannot hand it to a non-user. Upgrades come first in the
    order they are offered, then a fitting wearer, the family, the module's
    score and the name. An armor piece with a card goes only to a user it
    fits (their own armor class, stats their role builds on): equipping is
    not using it when the piece is armor below the wearer's class, so with
    no fitting user the greed roll stands. A weapon has no armor fit, and
    `wearable` (the proficiency) decides alone."""
    users = [c for c in council.candidates if c.wearable]
    if not users or len(users) == len(council.candidates):
        return ()
    if piece is not None:
        users = [c for c in users if _fits(c, piece)]
    upgrades = {c.name: n for n, c in enumerate(offered(council))}
    return tuple(
        sorted(
            users,
            key=lambda c: (
                upgrades.get(c.name, len(upgrades)),
                not (piece is not None and _fits(c, piece)),
                not c.family,
                -c.score,
                c.name,
            ),
        )
    )


# The words the module's candidate reasons use for a weapon: its refusal
# ("no proficiency with this weapon"), the off-hand refusals, and the
# weapon kinds it names (GearWeaponKindName). Read only when there is no
# item card, as the one sign left that the drop is a weapon.
_WEAPON_WORDS = re.compile(
    r"\b(weapon|axe|mace|sword|polearm|staff|bow|gun|crossbow|dagger|fist|"
    r"thrown|wand)\b",
    re.IGNORECASE,
)


def _known_weapon(council: Council) -> bool:
    """Does the row itself show the drop is a weapon: a candidate's reason
    names one. Armor, or a row whose reasons name nothing, is not known."""
    return any(_WEAPON_WORDS.search(c.why or "") for c in council.candidates)


def card_missing(council: Council, item) -> str | None:
    """One line naming a drop decided without its item card, or None when
    the card is there. With no card a drop not known to be a weapon keeps
    the greed roll, and the line says which way this one went."""
    if isinstance(item, dict):
        return None
    if _known_weapon(council):
        went = "the row names a weapon, so a member who can use it still comes first"
    else:
        went = "armor or unknown, so the greed roll stands"
    return "loot council: %s (%s) has no item card - %s" % (
        council.item_name or "item %d" % council.item_entry,
        council.key,
        went,
    )


def _user_over_greed(council: Council, item, recipient: str, reason: str):
    """(recipient, reason, moved): a nobody turned into the best user while a
    non-user is present, with why; anything else as it was.

    The fit gates in `decide` read only the offered candidates, the ones the
    drop upgrades; on this path nobody upgrades, so that set is empty and
    the gates cannot have shut a user out before this runs.

    WITH NO ITEM CARD the armor fit cannot be read, so `wearable` alone
    would hand a leather drop to a warrior over the greed roll. Without a
    card only a drop the row shows to be a weapon moves; armor, or a drop
    the row does not name, keeps the greed roll (fail closed)."""
    if recipient:
        return recipient, reason, False
    if not isinstance(item, dict) and not _known_weapon(council):
        return recipient, reason, False
    users = _users(council, _piece(item))
    if not users:
        return recipient, reason, False
    pick = users[0]
    cannot = [c.name for c in council.candidates if not c.wearable]
    named = "nobody was named" if pick.upgrades else "nobody it upgrades"
    why = (
        "Heuristic: %s; %s can use it and %s cannot, so it goes to a member "
        "who can use it rather than a greed roll"
        % (
            named,
            pick.name,
            ", ".join(cannot[:4]) + (" and others" if len(cannot) > 4 else ""),
        )
    )
    return pick.name, why, True


def skipped(council: Council, item=None) -> Decision:
    """The heuristic's decision for a row with nobody to ask about. The
    item card, when the caller has it, arms the fit gates here too: the
    unasked path hands out more loot than any other."""
    members, piece, shut = _fit_gate(council, item)
    recipient = council.heuristic
    why = council.heuristic_why or "nobody it upgrades"
    gated = _gated_pick(members, shut, recipient)
    if gated is not None:
        pick, replaced = gated
        recipient = pick.name
        why = _fit_reason(piece, replaced, pick)
    reason = "Heuristic: %s" % why
    recipient, reason, _moved = _user_over_greed(council, item, recipient, reason)
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
    return Decision(council.key, recipient, _fit(reason), jev.HEURISTIC, judgment)


async def answer(client, council: Council, describe, rule: jev.Policy) -> Decision:
    """Ask Jev about one row and decide it. `describe(entry)` is the item card."""
    item = describe(council.item_entry)
    asked = question(council, item)
    if asked is None or rule.mode == jev.OFF:
        return skipped(council, item)
    state, questions = asked
    wait = float(getattr(client, "timeout", 0.0))
    outcome = await client.ask(KIND, state, questions, wait=wait)
    return decide(council, outcome, rule, item)


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
