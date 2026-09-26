"""Which two professions a character in another family takes, asked of Jev (#211).

WHY THIS EXISTS. `professions.ROSTER` is the Alliance family's assignment,
written by hand and keyed by their names. Every other family on the roster has
no row in it, so nothing ever decided what they should learn. Measured on
wow-dev 2026-09-23: the Horde family (Zug warrior 20, Oz mage 19, Uzza priest
17, Zrog shaman 17, Zork druid 16) held no primary profession at all.

WHAT IS DECIDED HERE, AND WHAT IS NOT. Only the empty primary slots. A primary
a character already holds is kept whatever its value, so nothing here ever
asks for an unlearn. The choice becomes `overseer_trade` learn rows (the
family's record of the decision) and the `overseer_roster.professions`
permission, and from there the same machinery the Alliance family uses takes
over: mod-overseer's DriveProfessions writes `learn_skill`, `learnaim` walks
the leader to a trainer, and TrainOnArrival buys the trade through
Trainer::TeachSpell. Nothing is granted.

JEV CHOOSES, IN ACT MODE BY DEFAULT. The operator asked for Jev to make this
decision. For each character with an open slot, Jev is shown the character,
the family's professions so far (held or already chosen) and every pair the
rules below allow, and picks one. Its answer is used when
`JEV_MODE_PROFESSION_CHOICE` is `act` (the default here, unlike jev.py's
shadow default) and its confidence reaches
`JEV_PROFESSION_CHOICE_MIN_CONFIDENCE`. Otherwise, and whenever Jev is slow,
down, busy or has no key, the class heuristic below decides. Both answers are
recorded side by side either way.

THE RULES A PAIR MUST PASS, all taken from professions.py rather than restated:

  * two primaries (`professions.MAX_PRIMARY`), every held one included;
  * never inscription or jewelcrafting (`professions.UNASSIGNED`: the guild
    covers those);
  * an armour-making craft only for a class that wears that armour
    (`professions.CRAFT_ARMOUR` against `professions.ARMOUR`);
  * at least one craft, because two gathering trades make nothing;
  * a craft nobody else in the family has already taken, so the family covers
    more trades rather than doubling one. Dropped only when no pair survives
    it.

PURE: rows in, decisions and records out. The only I/O is through the Jev
client the caller hands in, so the whole choice is testable with a fake one.
"""

from __future__ import annotations

import itertools
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

import jev
import learnaim
import professions
import trainjob

KIND = "profession_choice"
MODE_ENV = "JEV_MODE_" + KIND.upper()
MIN_CONFIDENCE_ENV = "JEV_PROFESSION_CHOICE_MIN_CONFIDENCE"
DEFAULT_MIN_CONFIDENCE = 0.5

JEV = "jev"
HEURISTIC = "heuristic"

CHOOSABLE = tuple(sorted(professions.PRIMARY - set(professions.UNASSIGNED)))

# What each trade gives the family, in the words Jev and the log are shown.
MAKES = {
    "alchemy": "potions and elixirs now, raid flasks later; uses herbs",
    "blacksmithing": "plate armour, weapons and sharpening stones; uses ore",
    "enchanting": (
        "weapon and armour enchants for the family and the raid; disenchants "
        "unwanted green gear and tailored goods for its materials"
    ),
    "engineering": (
        "a field repair bot, a portable mailbox, bombs and scopes; uses ore"
    ),
    "herbalism": "gathers herbs, which alchemy turns into potions",
    "leatherworking": "leather armour, armour kits and later bags; uses leather",
    "mining": "gathers ore, which blacksmithing and engineering use",
    "skinning": "skins beasts, which leatherworking uses",
    "tailoring": (
        "cloth armour and BAGS for the whole family; runs on looted cloth, "
        "so it needs no gathering trade"
    ),
}

# The heuristic's first choices by the armour a class wears, best first. The
# first pair that passes the rules and doubles nobody's craft wins.
PREFERENCES = {
    "plate": (
        ("mining", "blacksmithing"),
        ("mining", "engineering"),
        ("herbalism", "alchemy"),
    ),
    "mail": (
        ("mining", "engineering"),
        ("herbalism", "alchemy"),
        ("mining", "blacksmithing"),
    ),
    "leather": (
        ("skinning", "leatherworking"),
        ("herbalism", "alchemy"),
        ("mining", "engineering"),
    ),
    "cloth": (
        ("tailoring", "enchanting"),
        ("herbalism", "alchemy"),
        ("mining", "engineering"),
    ),
}

_WHY = {
    ("mining", "blacksmithing"): "a plate wearer makes the plate it wears",
    ("mining", "engineering"): (
        "engineering makes the repair bot the family and the raid lean on, "
        "and mining feeds it"
    ),
    ("herbalism", "alchemy"): (
        "herbalism feeds alchemy, the family's potions and the raid's flasks"
    ),
    ("skinning", "leatherworking"): (
        "a leather wearer skins what it kills and makes the leather it wears"
    ),
    ("tailoring", "enchanting"): (
        "a cloth wearer makes the family's bags from looted cloth, and "
        "enchanting pairs with it"
    ),
}


@dataclass(frozen=True)
class Member:
    """One character as the choice sees it.

    `held` is the primary professions in `character_skills` with their values.
    `chosen` is the primaries already decided for it in `overseer_trade`
    (planned or learned). Both are kept; only what is left is chosen.
    """

    name: str
    class_name: str
    level: int = 0
    held: Mapping[str, int] = field(default_factory=dict)
    chosen: tuple = ()


def _ordered(pair) -> tuple:
    """Gathering trade first, then by name, so one pair has one spelling."""
    return tuple(sorted(pair, key=lambda s: (s not in professions.GATHERING, s)))


def key_of(pair) -> str:
    return "+".join(_ordered(pair))


def kept(member: Member) -> tuple:
    """What this character keeps: held primaries first, then chosen ones."""
    out: list = []
    for skill in sorted(member.held):
        if skill in professions.PRIMARY and skill not in out:
            out.append(skill)
    for skill in member.chosen:
        if skill in professions.PRIMARY and skill not in out:
            out.append(skill)
    return tuple(out[: professions.MAX_PRIMARY])


def _suits(skill: str, class_name: str) -> bool:
    made = professions.CRAFT_ARMOUR.get(skill)
    return made is None or made == professions.armour_for(class_name)


def taken_crafts(decided: Mapping[str, Sequence], except_name: str) -> frozenset:
    """The crafts the rest of the family already holds or has chosen."""
    return frozenset(
        skill
        for name, skills in decided.items()
        if name != except_name
        for skill in skills
        if skill in professions.CRAFTING
    )


def options(member: Member, keep: Sequence, taken: frozenset = frozenset()) -> dict:
    """Every pair this character may end up with, as a Choice's criteria.

    Empty when there is nothing to choose (both slots already kept).
    """
    keep = tuple(keep)
    if len(keep) >= professions.MAX_PRIMARY:
        return {}
    pool = sorted(set(CHOOSABLE) | set(keep))
    pairs = []
    for pair in itertools.combinations(pool, professions.MAX_PRIMARY):
        if not set(keep) <= set(pair):
            continue
        new = [s for s in pair if s not in keep]
        if not all(_suits(s, member.class_name) for s in new):
            continue
        if not any(s in professions.CRAFTING for s in pair):
            continue
        pairs.append(_ordered(pair))
    fresh = [p for p in pairs if not any(s in taken for s in p if s not in keep)]
    chosen = fresh or pairs
    return {
        key_of(pair): "%s learns %s: %s."
        % (
            member.name,
            " and ".join(pair),
            "; ".join(
                "%s makes %s" % (s, MAKES[s])
                if s in professions.CRAFTING
                else "%s %s" % (s, MAKES[s])
                for s in pair
            ),
        )
        for pair in sorted(chosen, key=key_of)
    }


def heuristic(member: Member, offered: Mapping[str, str]) -> tuple:
    """(pair key, why): the class's first preference among `offered`."""
    armour = professions.armour_for(member.class_name)
    for pair in PREFERENCES.get(armour, ()):
        key = key_of(pair)
        if key in offered:
            return key, "%s wears %s; %s" % (
                member.name,
                armour,
                _WHY.get(tuple(pair), "its class's first free pair"),
            )
    first = sorted(offered)[0]
    return first, "%s: no class preference is free, so the first allowed pair" % (
        member.name
    )


def question(member: Member, family: Sequence, decided: Mapping, offered: Mapping):
    """(state, questions) for one character's pair."""
    state = {
        "character": {
            "name": member.name,
            "class": member.class_name,
            "level": int(member.level),
            "wears": professions.armour_for(member.class_name) or "unknown",
            "already_holds": list(kept(member)) or "no primary profession",
        },
        "family": [
            {
                "name": other.name,
                "class": other.class_name,
                "level": int(other.level),
                "professions": list(decided.get(other.name, ())) or "not chosen yet",
            }
            for other in sorted(family, key=lambda m: m.name)
            if other.name != member.name
        ],
        "needs": [
            "bags now: the family carries little more than its starting backpacks",
            "potions, armour and repairs while the family levels together",
            "later a guild raid, which needs flasks, enchants and a repair bot",
        ],
    }
    instructions = (
        "`character` is a World of Warcraft (3.3.5a) character in a family of "
        "adventurers who level together and will later raid with their guild. "
        "Choose the two primary professions `character` should learn. Suit "
        "its class and the armour it wears, complement the professions the "
        "rest of `family` already has so the family covers more trades rather "
        "than doubling one, prefer a gathering trade that feeds a craft "
        "somebody in the family holds, and weigh what the family `needs`."
    )
    return state, {"pair": jev.choice(instructions, dict(offered))}


@dataclass(frozen=True)
class Judgment:
    """Jev's answer beside the heuristic's, shaped for overseer_jev_judgment.

    The same columns jev_items.Judgment fills; `item_*` are empty because the
    subject here is a character's professions, not an item.
    """

    subject: str
    heuristic: str
    heuristic_why: str
    mode: str
    status: str
    jev: str = ""
    confidence: float | None = None
    probabilities: dict | None = None
    latency_ms: int = 0
    model: str = ""
    kind: str = KIND
    item_guid: int = 0
    item_entry: int = 0
    item_name: str = "professions"

    @property
    def holder(self) -> str:
        return self.subject

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    def probabilities_json(self, limit: int = 1000) -> str:
        """The distribution, most likely first, trimmed to fit its column."""
        if not self.probabilities:
            return ""
        ranked = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        while ranked:
            text = json.dumps(
                {k: round(v, 4) for k, v in ranked}, separators=(",", ":")
            )
            if len(text) <= limit:
                return text
            ranked = ranked[:-1]
        return ""


@dataclass(frozen=True)
class Decision:
    """One character's pair, who chose it, and why."""

    character: str
    pair: tuple
    learn: tuple
    source: str
    why: str
    judgment: Judgment | None = None

    def reason(self) -> str:
        """The sentence stored with each overseer_trade learn row."""
        return "%s takes %s, chosen by %s: %s." % (
            self.character,
            " + ".join(self.pair),
            self.source,
            self.why,
        )

    def line(self) -> str:
        """One structured log line: Jev's answer beside the heuristic's."""
        j = self.judgment
        if j is None:
            return "trades: kind=%s subject=%s chosen=%s source=%s why=%r" % (
                KIND,
                self.character,
                key_of(self.pair),
                self.source,
                self.why,
            )
        answer = "jev=%s conf=%.2f" % (j.jev, j.confidence or 0.0) if j.jev else "jev=-"
        verdict = "no-answer" if j.agree is None else ("agree" if j.agree else "differ")
        return (
            "trades: kind=%s subject=%s chosen=%s source=%s heuristic=%s %s "
            "verdict=%s status=%s latency_ms=%d mode=%s why=%r"
            % (
                KIND,
                self.character,
                key_of(self.pair),
                self.source,
                j.heuristic,
                answer,
                verdict,
                j.status,
                j.latency_ms,
                j.mode,
                self.why,
            )
        )


def mode(environ=None) -> str:
    """off / shadow / act for this decision. ACT when the switch is unset.

    The operator asked for Jev to decide this, so unset means act. A value
    that is set is read by jev.mode, so a typo falls back to shadow there and
    says so.
    """
    env = os.environ if environ is None else environ
    if not str(env.get(MODE_ENV, "") or "").strip():
        return jev.ACT
    return jev.mode(KIND, env)


def min_confidence(environ=None) -> float:
    """The confidence Jev's pick needs to act, clamped to [0, 1]."""
    env = os.environ if environ is None else environ
    try:
        value = float(env.get(MIN_CONFIDENCE_ENV, DEFAULT_MIN_CONFIDENCE))
    except (TypeError, ValueError):
        return DEFAULT_MIN_CONFIDENCE
    if not math.isfinite(value):
        return DEFAULT_MIN_CONFIDENCE
    return min(1.0, max(0.0, value))


def _pair(key: str) -> tuple:
    return tuple(key.split("+"))


def decide(
    member: Member,
    keep: Sequence,
    offered: Mapping[str, str],
    outcome,
    *,
    mode_now: str,
    floor: float,
) -> Decision:
    """The pair, from Jev in act mode when it answered well enough, else the
    heuristic. `outcome` is a jev.Outcome, or None when Jev was not asked."""
    h_key, h_why = heuristic(member, offered)
    judgment = None
    chosen_key, source, why = h_key, HEURISTIC, h_why
    if outcome is not None:
        judgment = Judgment(
            subject=member.name,
            heuristic=h_key,
            heuristic_why=h_why,
            mode=mode_now,
            status=outcome.status,
            latency_ms=outcome.latency_ms,
        )
        if outcome.answers is not None:
            answer = outcome.answers["pair"]
            judgment = replace(
                judgment,
                jev=answer.choice,
                confidence=answer.confidence,
                probabilities=dict(answer.probabilities),
                model=outcome.model,
            )
            if mode_now == jev.ACT and answer.confidence >= floor:
                chosen_key, source = answer.choice, JEV
                why = "Jev picked %s at confidence %.2f (heuristic: %s, because %s)" % (
                    answer.choice,
                    answer.confidence,
                    h_key,
                    h_why,
                )
            elif mode_now == jev.ACT:
                why = "%s (Jev picked %s at confidence %.2f, below %.2f)" % (
                    h_why,
                    answer.choice,
                    answer.confidence,
                    floor,
                )
        else:
            why = "%s (Jev gave no answer: %s)" % (h_why, outcome.status)
    pair = _pair(chosen_key)
    return Decision(
        character=member.name,
        pair=pair,
        learn=tuple(s for s in pair if s not in keep),
        source=source,
        why=why,
        judgment=judgment,
    )


async def choose(client, members: Sequence, *, mode_now: str, floor: float) -> tuple:
    """A Decision for every character with an open primary slot.

    One character at a time, highest level first, so each question shows the
    pairs already chosen before it and the set stays complementary.
    """
    members = list(members)
    decided = {m.name: kept(m) for m in members}
    out = []
    for member in sorted(members, key=lambda m: (-int(m.level), m.name)):
        keep = decided[member.name]
        offered = options(member, keep, taken_crafts(decided, member.name))
        if not offered:
            continue
        outcome = None
        if mode_now != jev.OFF and len(offered) > 1:
            state, questions = question(member, members, decided, offered)
            outcome = await client.ask(KIND, state, questions)
        decision = decide(
            member, keep, offered, outcome, mode_now=mode_now, floor=floor
        )
        decided[member.name] = decision.pair
        out.append(decision)
    return tuple(out)


# ---------------------------------------------------------------------------
# ROWS IN, AND WHAT THE BRIDGE WRITES


def members_from(characters, skills: Mapping, trades) -> list:
    """Members from `characters` rows (name, class_name, level), observed
    `skills` (name -> {profession: value}) and `trades` rows (character_name,
    skill_name, verb, status)."""
    chosen: dict = {}
    for row in trades or ():
        if str(row.get("verb", "learn")) != "learn":
            continue
        skill = str(row.get("skill_name") or "")
        if skill in professions.PRIMARY:
            chosen.setdefault(str(row["character_name"]), []).append(skill)
    out = []
    for row in characters or ():
        name = str(row["name"])
        held = {
            s: int(v)
            for s, v in (skills.get(name) or {}).items()
            if s in professions.PRIMARY
        }
        out.append(
            Member(
                name=name,
                class_name=str(row.get("class_name") or ""),
                level=int(row.get("level") or 0),
                held=held,
                chosen=tuple(sorted(set(chosen.get(name, ())))),
            )
        )
    return out


def with_decisions(members: Sequence, decisions: Sequence) -> list:
    """The members with each decision's new trades added to `chosen`."""
    by_name = {d.character: d for d in decisions}
    out = []
    for m in members:
        d = by_name.get(m.name)
        out.append(replace(m, chosen=tuple(m.chosen) + tuple(d.learn)) if d else m)
    return out


def wanted_ids(member: Member) -> str:
    """The `overseer_roster.professions` value: primaries only, sorted ids."""
    return ",".join(
        str(i) for i in sorted(professions.skill_id(s) for s in kept(member))
    )


def declarations(members: Sequence, current: Mapping[str, str]) -> list:
    """[(professions, name)] for every member whose column should change.

    A member with nothing kept is left alone: an empty permission is no
    decision, and writing one would erase a value somebody set by hand.
    """
    out = []
    for m in sorted(members, key=lambda m: m.name):
        ids = wanted_ids(m)
        if ids and ids != str(current.get(m.name) or ""):
            out.append((ids, m.name))
    return out


def learn_rows(roster, trades, declared: Mapping[str, str]) -> list:
    """learnaim.Row for each roster row, with `declared` as its permission."""
    traded: dict = {}
    settled: dict = {}
    for row in trades or ():
        if str(row.get("verb", "learn")) != "learn":
            continue
        name = str(row["character_name"])
        skill = int(row.get("skill_id") or 0)
        traded.setdefault(name, set()).add(skill)
        if row.get("status") == "learned":
            settled.setdefault(name, set()).add(skill)
    return [
        learnaim.Row(
            character=str(row["name"]),
            learn_skill=int(row.get("learn_skill") or 0),
            travel_npc=str(row.get("travel_npc") or ""),
            leads=bool(int(row.get("lead") or 0)),
            wanted=trainjob.parse_wanted(
                declared.get(str(row["name"]), row.get("professions") or "")
            ),
            traded=tuple(sorted(traded.get(str(row["name"]), ()))),
            settled=tuple(sorted(settled.get(str(row["name"]), ()))),
        )
        for row in roster or ()
    ]


# ---------------------------------------------------------------------------
# WHO LEADS THE FAMILY TO A TRAINER


def next_lead(rows: Sequence, *, leader: str, head: str, expired=frozenset()) -> str:
    """Who should lead this family now.

    Only the leader walks, and TrainOnArrival acts on the character that
    arrived, so a learn errand needs its own character to lead. This hands
    the lead to the first character (by name) with an outstanding learn
    errand, and back to the family's head when none is left.

    It never takes the lead from a leader that is on a journey (a non-empty
    `travel_npc`), so no errand in progress is stranded; a leader with its
    own outstanding learn keeps the lead; and a character whose borrowed lead
    has run past its bound (`expired`) is skipped, so one errand the world
    cannot finish does not hold the family for ever.
    """
    rows = list(rows or ())
    names = {r.character for r in rows}
    waiting = sorted(
        r.character
        for r in rows
        if learnaim.outstanding(r) and r.character not in expired
    )
    if leader in waiting:
        return leader
    current = next((r for r in rows if r.character == leader), None)
    if current is not None and str(current.travel_npc or "").strip():
        return leader
    if waiting:
        return waiting[0]
    if head in names:
        return head
    return leader


def campaign_lead(rows: Sequence, *, head: str) -> str:
    """The lead a family's staging campaign hands back to its head, or "".

    A LEARN ERRAND BORROWS THE LEAD; A CAMPAIGN NEVER KEEPS A BORROWER. While
    a campaign owns the traveller (#227) no learn trip is aimed, so no borrow
    is live, and `next_lead` is not asked at all. A borrower that already held
    the lead when the campaign armed therefore kept it for the whole campaign.
    Measured on the dev realm 2026-09-25: a trainee took the Horde lead for an
    alchemy learn, the Ragefire campaign armed, and every run from then on was
    led by that trainee instead of the head, who carries the game client and
    tanks. Every worldserver restart re-formed the party under the borrower,
    because the roster's `lead` flag is what mod-overseer enforces.

    Returns the head when a borrower (anyone else) holds the flag and the head
    is on the roster; "" when the head already leads, or is not a member here,
    which leaves the flag alone rather than writing a family with no leader.
    """
    rows = list(rows or ())
    if not head or head not in {r.character for r in rows}:
        return ""
    if any(r.character == head and r.leads for r in rows):
        return ""
    return head


def led_by(rows: Sequence, lead: str) -> list:
    """The rows as they read once `lead` holds the family's lead flag."""
    return [replace(r, leads=(r.character == lead)) for r in rows or ()]


def borrow_clock(
    since: Mapping[str, float], rows: Sequence, lead: str, head: str, now: float
) -> dict:
    """name -> when it first borrowed the lead for the errand it still has.

    An entry lasts while its character's learn errand is outstanding, so a
    borrower that has run out its bound stays skipped rather than getting a
    fresh clock the next time the lead comes free. It goes when the errand
    does (learned, cleared, or replaced by the next trade).
    """
    waiting = {r.character for r in rows or () if learnaim.outstanding(r)}
    out = {n: float(t) for n, t in since.items() if n in waiting}
    if lead and lead != head and lead in waiting and lead not in out:
        out[lead] = float(now)
    return out


def expired(since: Mapping[str, float], now: float, limit_seconds: float) -> frozenset:
    """The borrowers whose lead has run past `limit_seconds`."""
    return frozenset(n for n, t in since.items() if now - float(t) > limit_seconds)
