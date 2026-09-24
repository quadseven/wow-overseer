"""Jev's first pilot: what to do with a carried item, asked in shadow (#95).

WHY ITEMS FIRST. The decision on #95 moved the first Jev pilot from the
leader's quest pick to item disposition. It is the operator's most visible
complaint (bags full of things nobody routes), and it is a closed choice over
routes the bag pipeline can already carry out, which is exactly Jev's shape.

SHADOW MEANS THE HEURISTIC STILL ACTS. For every carried piece of gear this
asks Jev the same question the pipeline answers and records both answers side
by side.

ACT MEANS JEV'S ANSWER IS CARRIED OUT, through the heuristic's own command
paths and never a new one (see `act_plan`). What each kind may do, and at what
confidence, is `POLICY_DEFAULTS`; the operator overrides either per kind with
JEV_MODE_<KIND> and JEV_THRESHOLD_<KIND>. Live comparisons on the dev realm
(2026-09-22): weapon_choice agreed with the heuristic 4 of 5 at a mean
confidence of 0.95; item_disposition agreed 42 of 92 at 0.35 to 0.46.

TWO QUESTIONS, BOTH CHOICES:

  item_disposition  "what should the holder do with this piece?" over exactly
                    the routes that can happen to it today (see `options`).
  weapon_choice     "which weapons serve this character better in their
                    role: the carried one, or what they wield now?" Asked only
                    where the numbers cannot settle it: an on-hit or equip
                    effect on either side, or a two-hander that would take a
                    shield or off-hand piece off. gear.py compares item levels
                    and refuses a two-hander over an off-hand outright; neither
                    rule can weigh "Chance on hit: Increases Strength by 200"
                    against a shield for a Retribution paladin.

WHAT JEV IS NEVER OFFERED. A route with no executor. Disenchanting has no verb
in mod-overseer at all (disposition.py's EXECUTABLE_TODAY note has the audit),
so it is not an option; the choice set is the honest one. Handing a piece to a
guild member outside the family waits on the guild-wide routing in #174.

PURE: rows in, questions and records out. The only I/O is through the Jev
client the caller hands in, so the whole pass is testable with a fake one.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace

import bag_pressure
import disposition
import jev
import raidlineup
import statweights
from gear import wieldable_weapon

KIND_DISPOSITION = "item_disposition"
KIND_WEAPON = "weapon_choice"

# Each kind's default switch, threshold and agreement rule (jev.policy).
#
#   weapon_choice     act at 0.85. The record shows it right where it is sure.
#   item_disposition  act at 0.80, and an answer that agrees with the
#                     heuristic counts as Jev's at any confidence. Its record
#                     runs at 0.35 to 0.46, so in practice this acts only where
#                     the two agree, which changes nothing in the world: it is
#                     shadow in effect until Jev is sure of a different route.
#                     Only `keep` and `equip` have an act path (see act_plan).
POLICY_DEFAULTS = {
    KIND_WEAPON: dict(default_mode=jev.ACT, default_threshold=0.85),
    KIND_DISPOSITION: dict(
        default_mode=jev.ACT, default_threshold=0.80, on_agreement=True
    ),
}


def policies(environ=None) -> dict:
    """kind -> jev.Policy for the two item kinds."""
    return {
        kind: jev.policy(kind, environ=environ, **defaults)
        for kind, defaults in POLICY_DEFAULTS.items()
    }


KEEP = "keep"
EQUIP = "equip"
VENDOR = "vendor"
AUCTION = "auction"
GIVE_PREFIX = "give:"
# The bank policy's route (bankpolicy, #320): a second set for the holder's
# own bank, or raid supplies and gear kept for later for the guild bank. It
# has no act path here, because the bank passes already carry it out.
BANK = "bank"

CARRIED = "carried"
WORN = "worn"

RARE = 3
ITEM_CLASS_WEAPON = bag_pressure.WEAPON_CLASS

# InventoryType -> the equipment slots (bag 0) a piece of that type goes in.
# The slots are what the world stores; a question about a ring has to show
# both rings worn, and a question about a weapon has to show both hands.
_HANDS = (15, 16)
_WORN_SLOTS = {
    1: (0,),
    2: (1,),
    3: (2,),
    5: (4,),
    20: (4,),
    6: (5,),
    7: (6,),
    8: (7,),
    9: (8,),
    10: (9,),
    11: (10, 11),
    12: (12, 13),
    16: (14,),
    13: _HANDS,
    17: _HANDS,
    21: _HANDS,
    14: _HANDS,
    22: _HANDS,
    23: _HANDS,
    15: (17,),
    25: (17,),
    26: (17,),
    28: (17,),
}
_TWO_HAND = 17


def class_name(class_id: int) -> str:
    return raidlineup.CLASS_NAMES.get(int(class_id), "class %d" % int(class_id))


def can_wield(holding, character) -> bool:
    """Could this character put the piece on at all, better or not.

    Class mask, armour training, required level and weapon skill are gear.py's
    shared eligibility rules. Whether it is an UPGRADE is the judgment, and
    is left to the heuristic and to Jev.
    """
    if not bag_pressure.can_wear(holding, character):
        return False
    return wieldable_weapon(holding, character)


def _money(copper: int) -> str:
    copper = int(copper or 0)
    gold, silver, rest = copper // 10000, copper // 100 % 100, copper % 100
    parts = []
    if gold:
        parts.append("%dg" % gold)
    if silver:
        parts.append("%ds" % silver)
    if rest or not parts:
        parts.append("%dc" % rest)
    return " ".join(parts)


def auctionable(row: dict) -> bool:
    """The auction pass's own filter: bind on equip, unbound copy, below rare."""
    return (
        bag_pressure.item_binding(row) == disposition.BIND_ON_EQUIP
        and int(row.get("quality", 0) or 0) < RARE
    )


def options(row: dict, holding, characters, banked: str = "") -> dict:
    """Every route this piece can take TODAY, as a Choice's criteria.

    `keep` is always there. The rest are offered only where the world could
    carry them out: `equip` when the holder can wield it, `give:<name>` for
    each other family member who can and only while the copy is not
    soulbound (GIVE cannot move a bound item), `vendor` when a vendor pays
    for it, `auction` under the auction pass's own filter, and `bank` when
    the bank policy files it (#320), in the policy's own words.
    """
    by_name = {c.name: c for c in characters}
    holder = by_name.get(holding.holder)
    name = holding.name
    out = {KEEP: "%s leaves %s in their bags for now." % (holding.holder, name)}
    if holder is not None and can_wield(holding, holder):
        out[EQUIP] = "%s puts %s on, replacing what they wear there now." % (
            holding.holder,
            name,
        )
    if not holding.soulbound:
        for character in sorted(characters, key=lambda c: c.name):
            if character.name == holding.holder:
                continue
            if can_wield(holding, character):
                out[GIVE_PREFIX + character.name] = (
                    "%s hands %s to %s, a level %d %s in the family, to wear."
                    % (
                        holding.holder,
                        name,
                        character.name,
                        character.level,
                        class_name(character.class_id),
                    )
                )
    price = int(row.get("sell_price", 0) or 0)
    if price > 0:
        out[VENDOR] = "%s sells %s to a vendor for %s." % (
            holding.holder,
            name,
            _money(price),
        )
    if auctionable(row):
        out[AUCTION] = "%s lists %s on the auction house for another player to buy." % (
            holding.holder,
            name,
        )
    if banked:
        out[BANK] = "%s banks %s. %s" % (holding.holder, name, banked)
    return out


@dataclass(frozen=True)
class Pipeline:
    """What the shipped passes decided about this family's carried gear.

    Read off the same opinions the passes act on, never re-decided here:
    `gear.claims` (through bag_pressure) for who would wear a piece,
    `bag_pressure.holder_equips` for what the equip pass puts on, and
    `bag_pressure.gear_candidates` for what the vendor pass sells.
    """

    claimants: dict  # item guid -> a name, CLAIM_NOBODY or CLAIM_UNJUDGEABLE
    equipping: frozenset  # item guids the equip pass puts on
    selling: frozenset  # item guids the vendor pass sells
    keep_names: tuple = ()
    # item guid -> the bank policy's line for it (#320). The sell passes skip
    # these, so the heuristic's route for them is the bank.
    banked: dict = None

    @classmethod
    def read(
        cls, gear_rows, worn_rows, names, keep_names=(), banked=None
    ) -> "Pipeline":
        fits = bag_pressure.family_fits(gear_rows, worn_rows, names)
        equips = bag_pressure.holder_equips(
            gear_rows, worn_rows, names, keep_names=keep_names
        )
        sales = bag_pressure.gear_candidates(
            gear_rows,
            disposition.Family(vendor_reachable=True),
            available=disposition.EXECUTABLE_TODAY,
            fits=fits,
            keep_names=keep_names,
        )
        return cls(
            claimants=bag_pressure.family_claimants(gear_rows, worn_rows, names),
            equipping=frozenset(e.guid for e in equips),
            selling=frozenset(c.item_guid for c in sales) - frozenset(banked or {}),
            keep_names=tuple(keep_names),
            banked=dict(banked or {}),
        )

    def route(self, row: dict, guid: int, holder: str) -> tuple:
        """(route, why) for one carried piece.

        When both the auction and the vendor pass would take a piece,
        whichever counter the leader reaches first wins; it is recorded as
        `auction`, the pass that asks first when both are open.
        """
        who = self.claimants.get(guid, bag_pressure.CLAIM_UNJUDGEABLE)
        if bag_pressure.owner_keeps(row.get("name", ""), self.keep_names):
            return KEEP, "the operator marked it never to be disposed of"
        if guid in (self.banked or {}):
            return BANK, self.banked[guid]
        if guid in self.equipping:
            return EQUIP, "an upgrade its holder would wear"
        if who == holder:
            return (
                KEEP,
                "its holder would wear it, but the equip pass puts on a "
                "better carried piece for that slot or will not judge this "
                "weapon-hand swap",
            )
        if who == bag_pressure.CLAIM_UNJUDGEABLE:
            return KEEP, "cannot be settled from the numbers: no slot rule covers it"
        if who != bag_pressure.CLAIM_NOBODY:
            return GIVE_PREFIX + who, "an upgrade for %s" % who
        if auctionable(row):
            return AUCTION, "nobody in the family would wear it, and it can be listed"
        if guid in self.selling:
            return VENDOR, "nobody in the family would wear it"
        return KEEP, "nobody would wear it, and no route is open to it"


def _guid_holder(row: dict):
    try:
        return int(row["item_guid"]), str(row["holder"])
    except (KeyError, TypeError, ValueError):
        return None


def heuristic(gear_rows, worn_rows, names, keep_names=(), banked=None) -> dict:
    """item guid -> (route, why): what the shipped pipeline does with each piece."""
    pipeline = Pipeline.read(gear_rows, worn_rows, names, keep_names, banked)
    out = {}
    for row in gear_rows:
        key = _guid_holder(row)
        if key is not None:
            out[key[0]] = pipeline.route(row, *key)
    return out


# ---------------------------------------------------------------------------
# WHAT JEV IS SHOWN

# Tooltip fields that say nothing about whether an item is worth wearing, and
# only cost tokens: the vendor price is offered as an option's own words, and
# flavor text, durability, set membership and the raw quality number are not
# part of the judgment.
_CARD_DROPS = ("sell_price", "flavor", "durability", "set", "quality")
_QUALITY = {0: "poor", 1: "common", 2: "uncommon", 3: "rare", 4: "epic", 5: "legendary"}


def item_card(tooltip) -> dict | None:
    """The Armory's tooltip for an item, trimmed to what the judgment needs.

    The same reading a person sees on the Armory page (armory.template_tooltip),
    so Jev and the operator are shown one description of an item, not two.
    """
    if not tooltip:
        return None
    card = {
        k: v
        for k, v in tooltip.items()
        if k not in _CARD_DROPS and v not in (None, "", [], {})
    }
    quality = tooltip.get("quality")
    if quality in _QUALITY:
        card["quality"] = _QUALITY[quality]
    return card


@dataclass(frozen=True)
class Wardrobe:
    """What one character wears, slot by slot, as item descriptions."""

    name: str
    class_id: int
    level: int
    spec: str
    worn: dict  # equipment slot -> item description (dict)
    # The family's head (bonds.HOUSES), who tanks for it by the operator's
    # decision. Said to Jev with the tank flag (#194).
    head: bool = False

    @property
    def role(self) -> str:
        """statweights' role for this class and talent tree."""
        return statweights.role_for(self.class_id, self.spec)


def wardrobes(characters, worn_items, describe, specs, heads=()) -> dict:
    """name -> Wardrobe, from the worn rows (name, slot, entry). `heads` are
    the families' heads, marked on their Wardrobe."""
    heads = frozenset(heads or ())
    by_name = {}
    for c in characters:
        by_name[c.name] = Wardrobe(
            c.name, c.class_id, c.level, specs.get(c.name, ""), {}, c.name in heads
        )
    for row in worn_items:
        try:
            name, slot, entry = str(row["name"]), int(row["slot"]), int(row["entry"])
        except (KeyError, TypeError, ValueError):
            continue
        if name in by_name and entry > 0:
            described = describe(entry)
            if described:
                by_name[name].worn[slot] = described
    return by_name


def upgrade_slots(inventory_type) -> tuple:
    """The worn slots an upgrade is measured against: the main hand for a
    main-hand or two-handed weapon, the off hand for a shield or held item,
    and otherwise every slot the piece fits, the weakest of which it replaces
    (a ring, a trinket)."""
    kind = int(inventory_type or 0)
    if kind in (13, 17, 21):
        return (_HANDS[0],)
    if kind in (14, 22, 23):
        return (_HANDS[1],)
    return _WORN_SLOTS.get(kind, ())


def upgrade_item_levels(w: Wardrobe, slots, item_level) -> int | None:
    """How many item levels `item_level` is over the weakest piece worn in
    `slots` (the one it would replace), or None when unknown. An empty slot
    counts as item level 0: all of it is an upgrade."""
    try:
        level = int(item_level)
    except (TypeError, ValueError):
        return None
    if not slots:
        return None
    worn = []
    for s in slots:
        if s not in w.worn:
            return level
        try:
            worn.append(int(w.worn[s].get("item_level")))
        except (TypeError, ValueError, AttributeError):
            return None
    return level - min(worn)


def _who(w: Wardrobe, slots, item_level=None, measure=None) -> dict:
    """One character as a question shows them: class, level, talent tree,
    role, the tank and head flags, what the role values (statweights), and
    what they wear where the item goes, with the upgrade size in item levels
    when the caller knows the item's (#194)."""
    out = {
        "name": w.name,
        "class": class_name(w.class_id),
        "level": w.level,
    }
    if w.spec:
        out["talent_specialization"] = w.spec
    role = w.role
    out["role"] = role
    out["tank"] = role == statweights.TANK
    if w.head:
        out["family_head"] = True
    weights = statweights.stat_weights(role)
    if weights:
        out["stat_weights"] = weights
    out["wearing_in_those_slots"] = [
        w.worn[s] for s in slots if s in w.worn
    ] or "nothing"
    gain = upgrade_item_levels(w, slots if measure is None else measure, item_level)
    if gain is not None:
        out["upgrade_item_levels"] = gain
    return out


def disposition_question(holding, item: dict, closet: dict, offered: dict):
    """(state, questions) for one carried piece."""
    slots = _WORN_SLOTS.get(int(holding.inventory_type), ())
    measure = upgrade_slots(holding.inventory_type)
    holder = closet.get(holding.holder)
    others = [closet[n] for n in sorted(closet) if n != holding.holder]
    state = {
        "item": dict(item, copy_is_soulbound=bool(holding.soulbound)),
        "holder": _who(holder, slots, holding.item_level, measure)
        if holder
        else {"name": holding.holder},
        "family": [_who(w, slots, holding.item_level, measure) for w in others],
    }
    instructions = (
        "`holder` carries `item` in their bags. They are a World of Warcraft "
        "character in a family of adventurers who share a guild, and every "
        "one of them is described with what they wear in the slots `item` "
        "would go in. Choose what a thoughtful player would do with `item` "
        "now: put it on if it is better for the holder's class and role than "
        "what they wear, hand it to the family member it improves most, sell "
        "or list it if nobody would use it, or keep it if none of those is "
        "clearly right."
    )
    return state, {"route": jev.choice(instructions, offered)}


def needs_weapon_question(item: dict, holding, wardrobe: Wardrobe) -> bool:
    """True where item levels cannot settle a weapon comparison."""
    if int(holding.item_class) != ITEM_CLASS_WEAPON:
        return False
    if int(holding.inventory_type) not in (13, 17, 21, 22):
        return False
    worn = [wardrobe.worn[s] for s in _HANDS if s in wardrobe.worn]
    if not worn:
        return False
    if item.get("effects") or any(w.get("effects") for w in worn):
        return True
    return int(holding.inventory_type) == _TWO_HAND and 16 in wardrobe.worn


def weapon_question(holding, item: dict, wardrobe: Wardrobe):
    """(state, questions) for "the carried weapon, or what is wielded now?"."""
    worn = [wardrobe.worn[s] for s in _HANDS if s in wardrobe.worn]
    worn_names = " and ".join(w.get("name", "?") for w in worn)
    who = "a level %d %s%s" % (
        wardrobe.level,
        (wardrobe.spec + " ") if wardrobe.spec else "",
        class_name(wardrobe.class_id),
    )
    character = _who(
        wardrobe, _HANDS, holding.item_level, upgrade_slots(holding.inventory_type)
    )
    del character["wearing_in_those_slots"]
    state = {
        "character": character,
        "carried": item,
        "worn": worn,
    }
    instructions = (
        "`character` is %s. Which serves them better in the role their class "
        "and specialization play: wielding `carried`, or keeping the weapons "
        "in `worn`? Weigh weapon damage and speed, stats, and any on-hit or "
        "equip effects, and what that role needs from its hands." % who
    )
    criteria = {
        CARRIED: "%s wields %s instead of %s."
        % (wardrobe.name, holding.name, worn_names),
        WORN: "%s keeps %s." % (wardrobe.name, worn_names),
    }
    return state, {"better": jev.choice(instructions, criteria)}


def weapon_heuristic(holding, character, pipeline: Pipeline) -> tuple:
    """(carried|worn, why): what the pipeline does, and what it cannot see.

    For the holder, `carried` only when the equip pass puts it on, which
    already refuses the weapon-hand swaps item level cannot judge. For
    anybody else, `carried` only when the gear hand-off names them. The
    reason is gear.py's own, with what it leaves out said.
    """
    if character.name == holding.holder:
        answer = CARRIED if int(holding.guid) in pipeline.equipping else WORN
    else:
        named = pipeline.claimants.get(int(holding.guid))
        answer = CARRIED if named == character.name else WORN
    _, why = bag_pressure.wear_reason(holding, character)
    return (
        answer,
        "%s; cannot be settled from the numbers: effects and the off hand "
        "are not weighed" % why,
    )


# ---------------------------------------------------------------------------
# THE RECORD


@dataclass(frozen=True)
class Judgment:
    """One comparison: the heuristic's answer and Jev's, for one question."""

    kind: str
    subject: str  # the character the question is about
    holder: str
    item_guid: int
    item_entry: int
    item_name: str
    heuristic: str
    heuristic_why: str
    mode: str
    status: str
    jev: str = ""
    confidence: float | None = None
    probabilities: dict | None = None
    latency_ms: int = 0
    model: str = ""
    # jev.JEV, jev.BOTH or jev.HEURISTIC once the act plan has run; "" until
    # then. Recorded, so the record says which answer the world got.
    acted: str = ""

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    @property
    def signature(self) -> tuple:
        """What has to change for a new record to be worth writing."""
        return (
            self.heuristic,
            self.jev,
            self.jev and round(self.confidence or 0, 2),
            self.acted,
        )

    @property
    def key(self) -> tuple:
        return (self.kind, self.subject, self.item_guid)

    def probabilities_json(self) -> str:
        if not self.probabilities:
            return ""
        return json.dumps(
            {k: round(v, 4) for k, v in sorted(self.probabilities.items())},
            separators=(",", ":"),
        )

    def line(self) -> str:
        """The structured log line: key=value, one comparison per line."""
        if self.jev:
            verdict = "agree" if self.agree else "differ"
            answer = "jev=%s conf=%.2f" % (self.jev, self.confidence or 0.0)
        else:
            verdict = "no-answer"
            answer = "jev=-"
        return (
            "jev-shadow: kind=%s subject=%s holder=%s item=%d:%s heuristic=%s %s "
            "verdict=%s status=%s latency_ms=%d mode=%s acted=%s why=%r"
            % (
                self.kind,
                self.subject,
                self.holder,
                self.item_entry,
                self.item_name.replace(" ", "_"),
                self.heuristic,
                answer,
                verdict,
                self.status,
                self.latency_ms,
                self.mode,
                self.acted or "-",
                self.heuristic_why,
            )
        )


def _judged(base: Judgment, outcome: jev.Outcome, qid: str) -> Judgment:
    if outcome.answers is None:
        return replace(base, status=outcome.status, latency_ms=outcome.latency_ms)
    answer = outcome.answers[qid]
    return replace(
        base,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
    )


@dataclass(frozen=True)
class _Family:
    """Everything one pass reads once and every question consults."""

    characters: tuple
    closet: dict  # name -> Wardrobe
    pipeline: Pipeline
    modes: dict

    def mode(self, kind: str) -> str:
        return self.modes.get(kind, jev.SHADOW)


def _disposition_ask(family: _Family, holding, row: dict, item: dict, base: dict):
    """The item_disposition question for one piece, or None when not asked."""
    mode = family.mode(KIND_DISPOSITION)
    if mode == jev.OFF:
        return None
    offered = options(
        row,
        holding,
        family.characters,
        (family.pipeline.banked or {}).get(int(holding.guid), ""),
    )
    if len(offered) < 2:
        return None
    route, why = family.pipeline.route(row, int(holding.guid), holding.holder)
    state, questions = disposition_question(holding, item, family.closet, offered)
    judgment = Judgment(
        kind=KIND_DISPOSITION,
        subject=holding.holder,
        heuristic=route,
        heuristic_why=why,
        mode=mode,
        status="",
        **base,
    )
    return judgment, state, questions, "route"


def _weapon_asks(family: _Family, holding, item: dict, base: dict) -> list:
    """The weapon_choice question for each member it is a real question for."""
    mode = family.mode(KIND_WEAPON)
    if mode == jev.OFF:
        return []
    asks = []
    for character in sorted(family.characters, key=lambda c: c.name):
        wardrobe = family.closet.get(character.name)
        if wardrobe is None or not can_wield(holding, character):
            continue
        if character.name != holding.holder and holding.soulbound:
            continue
        if not needs_weapon_question(item, holding, wardrobe):
            continue
        state, questions = weapon_question(holding, item, wardrobe)
        answer, why = weapon_heuristic(holding, character, family.pipeline)
        judgment = Judgment(
            kind=KIND_WEAPON,
            subject=character.name,
            heuristic=answer,
            heuristic_why=why,
            mode=mode,
            status="",
            **base,
        )
        asks.append((judgment, state, questions, "better"))
    return asks


def _questions(family: _Family, gear_rows, describe) -> list:
    """Every (Judgment, state, questions, qid) this pass would ask, in order."""
    rows = {}
    for row in gear_rows:
        key = _guid_holder(row)
        if key is not None:
            rows[key[0]] = row
    holdings = bag_pressure.carried_holdings(gear_rows)
    asks = []
    for holding in sorted(holdings, key=lambda h: (h.holder, int(h.guid))):
        row = rows.get(int(holding.guid))
        if row is None or holding.holder not in family.closet:
            continue
        item = describe(int(holding.entry)) or {
            "name": holding.name,
            "item_level": holding.item_level,
        }
        base = dict(
            holder=holding.holder,
            item_guid=int(holding.guid),
            item_entry=int(holding.entry),
            item_name=holding.name,
        )
        ask = _disposition_ask(family, holding, row, item, base)
        if ask is not None:
            asks.append(ask)
        asks.extend(_weapon_asks(family, holding, item, base))
    return asks


async def shadow_pass(
    client: jev.Client,
    *,
    gear_rows,
    worn_rows,
    worn_items,
    names,
    describe,
    specs=None,
    keep_names=(),
    modes=None,
    limit: int = 16,
    heads=(),
    banked=None,
) -> list:
    """Ask Jev about each carried piece, beside the heuristic. Acts on nothing.

    `describe(entry)` returns an item description (the Armory's tooltip dict)
    or None. `modes` maps a kind to jev.OFF/SHADOW/ACT; a kind that is OFF is
    not asked at all. `limit` bounds the questions one pass may send, so a
    newly full bag is judged over a few passes rather than in one burst; the
    order is fixed (holder, then item guid) so every piece gets its turn.
    """
    characters = tuple(bag_pressure.family_characters(worn_rows, names))
    family = _Family(
        characters=characters,
        closet=wardrobes(characters, worn_items, describe, specs or {}, heads),
        pipeline=Pipeline.read(gear_rows, worn_rows, names, keep_names, banked),
        modes=dict(modes or {}),
    )
    asks = _questions(family, gear_rows, describe)[: max(0, int(limit))]
    gate = asyncio.Semaphore(max(1, int(getattr(client, "concurrency", 1))))
    # Queued for a free slot rather than `busy` behind another kind (#267):
    # 97 of 480 answers in one day were `busy`. An act pass that waits on
    # this still gives up at its own deadline, so this costs it nothing.
    wait = float(getattr(client, "timeout", 0.0))

    async def one(ask):
        base, state, questions, qid = ask
        async with gate:
            outcome = await client.ask(base.kind, state, questions, wait=wait)
        return _judged(base, outcome, qid)

    return list(await asyncio.gather(*(one(a) for a in asks)))


# ---------------------------------------------------------------------------
# ACTING ON THE ANSWERS (#95)
#
# NEVER A NEW ACTION. Jev's answer reaches the world only through the two
# passes that already run: the family hand-off (`_hand_gear`) and the holder's
# own equip (`_equip_upgrades`, the `e Hitem:` row). Acting can therefore do
# exactly three things: put a piece on its own holder, leave a piece the equip
# pass would put on in the bags, and leave a piece the hand-off would move with
# its holder. A route Jev prefers that has no such path (a sale, a listing, a
# hand-off to somebody the heuristic did not name) is recorded as the
# heuristic's, because the heuristic's is the one that happened.
#
# ONLY A FRESH ANSWER ACTS. Answered or cached for this cycle's own question
# (the cache is keyed on the exact state, so a changed wardrobe is a changed
# question). The caller waits at most the client's own deadline; past it the
# heuristic acts and the late answers are recorded as the heuristic's.

_FRESH = (jev.ANSWERED, jev.CACHED)
# Routes an equip may stand in for without racing another pass over the same
# piece in the same cycle. A sale or a listing reads the same stale rows.
_EQUIP_OVER = (KEEP, EQUIP)


@dataclass(frozen=True)
class ActPlan:
    """What this cycle's passes do differently because Jev answered."""

    equip: dict  # item guid -> why: put on its own holder
    no_equip: frozenset  # item guids the equip pass leaves in the bags
    no_give: frozenset  # item guids the family hand-off leaves with the holder
    judgments: tuple  # every judgment, `acted` set

    @property
    def changes(self) -> bool:
        return bool(self.equip or self.no_equip or self.no_give)


def _equip_why(j: Judgment) -> str:
    return "Jev judged it the better choice for %s (%s, confidence %.2f)" % (
        j.subject,
        j.kind,
        j.confidence or 0.0,
    )


def _gives(route: str) -> bool:
    return route.startswith(GIVE_PREFIX)


def _weapon_can(j: Judgment, route: str) -> bool:
    """A weapon answer acts only on the holder's own weapon, and `carried`
    only where no sale or listing will race the equip for the same piece."""
    if j.subject != j.holder:
        return False
    return j.jev == WORN or route in _EQUIP_OVER or _gives(route)


def _disposition_can(j: Judgment) -> bool:
    """`keep` can withhold an equip or a hand-off; `equip` can stand in for
    keeping it or handing it off. Nothing else has an act path."""
    if j.jev == KEEP:
        return j.heuristic == EQUIP or _gives(j.heuristic)
    if j.jev == EQUIP:
        return j.heuristic == KEEP or _gives(j.heuristic)
    return False


def _who_acts(policies: dict, j: Judgment, can: bool) -> str:
    rule = policies.get(j.kind)
    if rule is None or j.status not in _FRESH or not j.jev:
        return jev.HEURISTIC
    return rule.acted(j.heuristic, j.jev, j.confidence, can_act=can)


def _change(j: Judgment, equip: dict, no_equip: set, no_give: set) -> None:
    """What Jev's answer on one piece does to the two passes."""
    if j.jev in (CARRIED, EQUIP):
        equip[j.item_guid] = _equip_why(j)
        no_give.add(j.item_guid)
    elif j.jev == WORN or j.heuristic == EQUIP:
        no_equip.add(j.item_guid)
    else:
        no_give.add(j.item_guid)


def act_plan(judgments, policies: dict, routes: dict) -> ActPlan:
    """Who acts on each judgment, and the three changes that follow.

    `policies` is kind -> jev.Policy; `routes` is item guid -> the pipeline's
    route (`heuristic()`'s first element), which says what else will happen to
    a piece this cycle. weapon_choice is settled first and wins a piece it
    acts on; item_disposition then acts only on pieces left.
    """
    equip, no_equip, no_give, taken = {}, set(), set(), set()
    marked = {}
    ordered = [j for j in judgments if j.kind == KIND_WEAPON] + [
        j for j in judgments if j.kind == KIND_DISPOSITION
    ]
    for j in ordered:
        if j.kind == KIND_WEAPON:
            can = _weapon_can(j, routes.get(j.item_guid, ""))
        else:
            can = j.item_guid not in taken and _disposition_can(j)
        acted = _who_acts(policies, j, can)
        if acted == jev.JEV:
            taken.add(j.item_guid)
            _change(j, equip, no_equip, no_give)
        marked[id(j)] = replace(j, acted=acted)
    return ActPlan(
        equip=equip,
        no_equip=frozenset(no_equip),
        no_give=frozenset(no_give),
        judgments=tuple(
            marked.get(id(j), replace(j, acted=jev.HEURISTIC)) for j in judgments
        ),
    )


def heuristic_acted(judgments) -> list:
    """Every judgment marked as the heuristic's: the answer came too late, or
    nothing waited for it, so the heuristic is what the world got."""
    return [replace(j, acted=jev.HEURISTIC) for j in judgments]


# ---------------------------------------------------------------------------
# WHICH GUILD MEMBER GAINS MOST (#184, #267)
#
# gear.rank_receivers orders the guild members an item is a real upgrade for,
# by item level. It cannot price an effect or say what a role needs from a
# slot. Jev is asked ONE Choice per item: which of the ranked candidates it
# improves most, each option naming the member's class, role, what they wear
# there and the ranking's own item-level gain. Jev's pick is compared with the
# ranking's.
#
# WHY A CHOICE AND NOT A SCORE PER CANDIDATE (#267). The first cut asked one
# Score per candidate and recorded the winner's Score confidence. That number
# measures how near the expected score sits to one of the rubric's levels, not
# how sure Jev is that this member beats the others: a probe on the dev realm
# answered 2.65 with 0.65, 2.12 with 0.12 and 0.25 with 0.75. Over one day
# its confidence averaged 0.32 and cleared 0.80 on 6% of answers, while one
# request carried up to 60 questions and 16 of 607 timed out. The Choice's
# confidence is about the pick itself: the same probe gave 0.84 and 0.88 on a
# clear plate helm, 0.62 on a robe two casters wanted and 0.29 on a crossbow a
# rogue and a hunter both wanted.
#
# ACTING NEVER WIDENS THE SET. Jev's pick replaces the route's receiver only
# when that member is already one of the route's own receivers (its taker or
# an alternate, every one of them clear of gear.CLEAR_GAIN) and the Choice's
# confidence reaches the threshold. The reordered route is delivered by the
# same `route_deliverable` and written by the same insert as the heuristic's.
# An item the ranking refuses to move (an effect item level cannot price, or
# no clear gain) is asked and recorded and never moved.

KIND_GUILD = "guild_recipient"
NOBODY = "nobody"
# 0.75: the probe's clear calls answered 0.84 to 0.88 and its genuine
# toss-ups 0.26 to 0.65, so this acts on the first and never the second.
POLICY_DEFAULTS[KIND_GUILD] = dict(default_mode=jev.ACT, default_threshold=0.75)
# The candidates one question offers, best ranked first. The route's taker is
# always among them.
MAX_RECIPIENTS = 6

RECIPIENT_INSTRUCTIONS = (
    "`item` is being handed to one member of a World of Warcraft guild. Every "
    "one of `candidates` could use it and is described with what they wear in "
    "the slots `item` would go in. Choose the member `item` improves most in "
    "the role their class and specialization play, the way a thoughtful guild "
    "shares loot: armor and stats that suit the class, and the biggest real "
    "upgrade over what they wear."
)


def guild_policy(environ=None) -> jev.Policy:
    return jev.policy(KIND_GUILD, environ=environ, **POLICY_DEFAULTS[KIND_GUILD])


@dataclass(frozen=True)
class RecipientAsk:
    """One guild item, its ranked candidates and the heuristic's pick."""

    holding: object
    ranked: tuple  # gear.Ranked, best first
    heuristic: str  # the route's taker, or NOBODY when it is not moved
    why: str

    @property
    def offered(self) -> tuple:
        """The candidates the question offers: the best MAX_RECIPIENTS, and
        the route's taker even when it ranks below them."""
        head = tuple(self.ranked[:MAX_RECIPIENTS])
        if self.heuristic != NOBODY and all(r.name != self.heuristic for r in head):
            head += tuple(r for r in self.ranked if r.name == self.heuristic)[:1]
        return head


def recipient_asks(holdings, candidates, routes, rank) -> list:
    """RecipientAsk per holding the ranking scores anybody for.

    `rank(holding, candidates)` is bag_pressure.rank_receivers; `routes` are
    the route plan's grants, whose taker is the heuristic's pick. Items with a
    route come first, so a pass cut short by its limit spends its questions
    where an answer can act.
    """
    routed = {(r.holder, int(r.guid)): r for r in routes}
    out = []
    for holding in sorted(holdings, key=lambda h: (h.holder, int(h.guid))):
        ranked = tuple(rank(holding, candidates))
        if not ranked:
            continue
        route = routed.get((holding.holder, int(holding.guid)))
        if route is not None:
            pick, why = route.taker, "+%d item levels, %s" % (route.gain, route.reason)
        elif not ranked[0].sure:
            pick, why = NOBODY, "an effect item level cannot price; not moved"
        else:
            pick, why = NOBODY, "no gain clear enough to move it"
        out.append(RecipientAsk(holding, ranked, pick, why))
    out.sort(key=lambda a: a.heuristic == NOBODY)
    return out


def _worn_there(w: Wardrobe | None, slots) -> str:
    """What `w` wears in the item's slots, in words, for an option."""
    if w is None:
        return "what they wear there is unknown"
    worn = [w.worn[s] for s in slots if s in w.worn]
    if not worn:
        return "nothing worn there"
    return "replacing " + " and ".join(
        "%s (item level %s)" % (d.get("name", "an item"), d.get("item_level", "?"))
        for d in worn
    )


def recipient_option(r, w: Wardrobe | None, slots) -> str:
    """One candidate as a Choice option: who, their role, what it replaces,
    and the ranking's own item-level gain."""
    who = [r.name, "gets it:"]
    if w is not None:
        role = " ".join(p for p in (w.spec, class_name(w.class_id)) if p)
        who.append("the level %d %s," % (w.level, role))
    elif r.family:
        who.append("a member of the holder's family,")
    return "%s %s, +%d item levels%s." % (
        " ".join(who),
        _worn_there(w, slots),
        int(r.gain),
        "" if r.sure else " (it has an effect item level cannot price)",
    )


def recipient_question(ask: RecipientAsk, item: dict, closet: dict):
    """(state, questions): one Choice over the offered candidates."""
    slots = _WORN_SLOTS.get(int(ask.holding.inventory_type), ())
    members, criteria = [], {}
    for r in ask.offered:
        w = closet.get(r.name)
        who = (
            _who(
                w,
                slots,
                ask.holding.item_level,
                upgrade_slots(ask.holding.inventory_type),
            )
            if w is not None
            else {"name": r.name}
        )
        who["in_the_holders_family"] = bool(r.family)
        members.append(who)
        criteria[r.name] = recipient_option(r, w, slots)
    state = {"item": item, "candidates": members}
    return state, {"to": jev.choice(RECIPIENT_INSTRUCTIONS, criteria)}


def recipient_judgment(ask: RecipientAsk, outcome: jev.Outcome, mode: str) -> Judgment:
    """The comparison for one item: the ranking's pick beside Jev's.

    `confidence` and `probabilities` are the Choice's own.
    """
    h = ask.holding
    base = Judgment(
        kind=KIND_GUILD,
        subject=h.holder,
        holder=h.holder,
        item_guid=int(h.guid),
        item_entry=int(h.entry),
        item_name=h.name,
        heuristic=ask.heuristic,
        heuristic_why=ask.why,
        mode=mode,
        status=outcome.status,
        latency_ms=outcome.latency_ms,
    )
    if outcome.answers is None:
        return base
    answer = outcome.answers["to"]
    return replace(
        base,
        model=outcome.model,
        jev=answer.choice,
        confidence=answer.confidence,
        probabilities=answer.probabilities,
    )


async def recipient_pass(client, asks, describe, closet, mode, limit=16) -> list:
    """Ask Jev about each guild item; the judgments, `acted` unset.

    A question queues for a free client slot for up to the client's own
    deadline rather than meeting `busy` behind another kind's burst (#267).
    """
    if mode == jev.OFF:
        return []
    gate = asyncio.Semaphore(max(1, int(getattr(client, "concurrency", 1))))
    wait = float(getattr(client, "timeout", 0.0))

    async def one(ask):
        h = ask.holding
        item = describe(int(h.entry)) or {"name": h.name, "item_level": h.item_level}
        state, questions = recipient_question(ask, item, closet)
        async with gate:
            outcome = await client.ask(KIND_GUILD, state, questions, wait=wait)
        return recipient_judgment(ask, outcome, mode)

    return list(await asyncio.gather(*(one(a) for a in asks[: max(0, int(limit))])))


def reroute(plan, judgments, policy: jev.Policy) -> tuple:
    """(plan, judgments): the route plan with Jev's pick first where it acts,
    and every judgment with `acted` set.

    A route Jev acts on keeps every receiver it had, reordered so Jev's pick
    is the taker and the rest follow as alternates in the ranking's order, so
    `route_deliverable` still falls back through them when Jev's pick cannot
    take it now.
    """
    by_item = {(j.holder, j.item_guid): j for j in judgments}
    out_routes, acted = [], {}
    for route in plan.grants:
        j = by_item.get((route.holder, int(route.guid)))
        if j is None:
            out_routes.append(route)
            continue
        options = (replace(route, alternates=()),) + tuple(route.alternates)
        names = [o.taker for o in options]
        fresh = j.status in _FRESH and bool(j.jev)
        who = (
            policy.acted(j.heuristic, j.jev, j.confidence, can_act=j.jev in names)
            if fresh
            else jev.HEURISTIC
        )
        acted[(j.holder, j.item_guid)] = who
        if who != jev.JEV:
            out_routes.append(route)
            continue
        first = options[names.index(j.jev)]
        rest = tuple(o for o in options if o.taker != j.jev)
        out_routes.append(replace(first, alternates=rest))
    marked = tuple(
        replace(j, acted=acted.get((j.holder, j.item_guid), jev.HEURISTIC))
        for j in judgments
    )
    return replace(plan, grants=tuple(out_routes)), marked


def withhold_gifts(plan, act: ActPlan | None):
    """The family hand-off plan without the pieces Jev keeps with their
    holder, one note per piece withheld, the way the plan's own notes read."""
    if act is None or not act.no_give:
        return plan
    kept, notes = [], list(plan.notes)
    for grant in plan.grants:
        if int(grant.guid) in act.no_give:
            notes.append(
                "%s keeps %s rather than handing it to %s: Jev acted on it"
                % (grant.holder, grant.name, grant.taker)
            )
        else:
            kept.append(grant)
    return replace(plan, grants=tuple(kept), notes=tuple(notes))


def specs_for(names, family_bonds, trees_for) -> dict:
    """name -> talent specialization name, where the family table states one.

    `family_bonds` is bonds.FAMILY (spec_tab and class per member) and
    `trees_for(class_id)` is armory.TalentBook.trees_for. A member the table
    does not describe gets no entry, and the question simply omits it.
    """
    class_ids = {v.lower(): k for k, v in raidlineup.CLASS_NAMES.items()}
    out = {}
    for name in names:
        bond = family_bonds.get(name)
        if bond is None:
            continue
        class_id = class_ids.get(str(getattr(bond, "char_class", "")).lower())
        tab = getattr(bond, "spec_tab", None)
        if class_id is None or tab is None:
            continue
        trees = trees_for(class_id)
        if 0 <= int(tab) < len(trees):
            out[name] = str(trees[int(tab)][1].get("name", ""))
    return out
