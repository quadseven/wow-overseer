"""Jev's first pilot: what to do with a carried item, asked in shadow (#95).

WHY ITEMS FIRST. The decision on #95 moved the first Jev pilot from the
leader's quest pick to item disposition. It is the operator's most visible
complaint (bags full of things nobody routes), and it is a closed choice over
routes the bag pipeline can already carry out, which is exactly Jev's shape.

SHADOW MEANS THE HEURISTIC STILL ACTS. For every carried piece of gear this
asks Jev the same question the pipeline answers, records both answers side by
side, and changes nothing in the world. `act` is a later operator decision,
per kind, once the record shows Jev agreeing where the heuristic is right and
differing where it is wrong.

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

KIND_DISPOSITION = "item_disposition"
KIND_WEAPON = "weapon_choice"

KEEP = "keep"
EQUIP = "equip"
VENDOR = "vendor"
AUCTION = "auction"
GIVE_PREFIX = "give:"

CARRIED = "carried"
WORN = "worn"

RARE = 3
ITEM_CLASS_WEAPON = bag_pressure.WEAPON_CLASS

# item_template.subclass for class 2 (WEAPON) that each class can be trained
# to wield in 3.3.5a. Used for ONE thing: not offering Jev a route the world
# would refuse. gear.py does not model weapon skills (AllowableClass is -1 on
# ordinary weapons), so without this a priest would be offered a two-handed
# sword. 14 (miscellaneous) and 20 (fishing pole) are open to everyone.
_AXE, _AXE2, _BOW, _GUN, _MACE, _MACE2, _POLEARM, _SWORD, _SWORD2 = range(9)
_STAFF, _FIST, _MISC, _DAGGER, _THROWN, _CROSSBOW, _WAND, _FISHING = (
    10,
    13,
    14,
    15,
    16,
    18,
    19,
    20,
)
_WEAPON_SKILLS = {
    1: {_AXE, _AXE2, _BOW, _GUN, _MACE, _MACE2, _POLEARM, _SWORD, _SWORD2}
    | {_STAFF, _FIST, _DAGGER, _THROWN, _CROSSBOW},  # Warrior
    2: {_AXE, _AXE2, _MACE, _MACE2, _POLEARM, _SWORD, _SWORD2},  # Paladin
    3: {_AXE, _AXE2, _BOW, _GUN, _POLEARM, _SWORD, _SWORD2}
    | {_STAFF, _FIST, _DAGGER, _THROWN, _CROSSBOW},  # Hunter
    4: {_AXE, _BOW, _GUN, _MACE, _SWORD, _FIST, _DAGGER, _THROWN, _CROSSBOW},  # Rogue
    5: {_MACE, _STAFF, _DAGGER, _WAND},  # Priest
    6: {_AXE, _AXE2, _MACE, _MACE2, _POLEARM, _SWORD, _SWORD2},  # Death Knight
    7: {_AXE, _AXE2, _MACE, _MACE2, _STAFF, _FIST, _DAGGER},  # Shaman
    8: {_SWORD, _STAFF, _DAGGER, _WAND},  # Mage
    9: {_SWORD, _STAFF, _DAGGER, _WAND},  # Warlock
    11: {_MACE, _MACE2, _POLEARM, _STAFF, _FIST, _DAGGER},  # Druid
}

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

    Class mask, armour training and required level are gear.py's own rules;
    the weapon skill is the one fact gear.py does not carry (see
    `_WEAPON_SKILLS`). Whether it is an UPGRADE is the judgment, and is left
    to the heuristic and to Jev.
    """
    if not bag_pressure.can_wear(holding, character):
        return False
    if int(holding.item_class) == ITEM_CLASS_WEAPON:
        subclass = int(holding.item_subclass)
        if subclass in (_MISC, _FISHING):
            return True
        return subclass in _WEAPON_SKILLS.get(int(character.class_id), set())
    return True


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


def options(row: dict, holding, characters) -> dict:
    """Every route this piece can take TODAY, as a Choice's criteria.

    `keep` is always there. The rest are offered only where the world could
    carry them out: `equip` when the holder can wield it, `give:<name>` for
    each other family member who can and only while the copy is not
    soulbound (GIVE cannot move a bound item), `vendor` when a vendor pays
    for it, `auction` under the auction pass's own filter.
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

    @classmethod
    def read(cls, gear_rows, worn_rows, names, keep_names=()) -> "Pipeline":
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
            selling=frozenset(c.item_guid for c in sales),
            keep_names=tuple(keep_names),
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


def heuristic(gear_rows, worn_rows, names, keep_names=()) -> dict:
    """item guid -> (route, why): what the shipped pipeline does with each piece."""
    pipeline = Pipeline.read(gear_rows, worn_rows, names, keep_names)
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


def wardrobes(characters, worn_items, describe, specs) -> dict:
    """name -> Wardrobe, from the worn rows (name, slot, entry)."""
    by_name = {}
    for c in characters:
        by_name[c.name] = Wardrobe(
            c.name, c.class_id, c.level, specs.get(c.name, ""), {}
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


def _who(w: Wardrobe, slots) -> dict:
    out = {
        "name": w.name,
        "class": class_name(w.class_id),
        "level": w.level,
    }
    if w.spec:
        out["talent_specialization"] = w.spec
    out["wearing_in_those_slots"] = [
        w.worn[s] for s in slots if s in w.worn
    ] or "nothing"
    return out


def disposition_question(holding, item: dict, closet: dict, offered: dict):
    """(state, questions) for one carried piece."""
    slots = _WORN_SLOTS.get(int(holding.inventory_type), ())
    holder = closet.get(holding.holder)
    others = [closet[n] for n in sorted(closet) if n != holding.holder]
    state = {
        "item": dict(item, copy_is_soulbound=bool(holding.soulbound)),
        "holder": _who(holder, slots) if holder else {"name": holding.holder},
        "family": [_who(w, slots) for w in others],
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
    state = {
        "character": {
            "name": wardrobe.name,
            "class": class_name(wardrobe.class_id),
            "level": wardrobe.level,
            **({"talent_specialization": wardrobe.spec} if wardrobe.spec else {}),
        },
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

    @property
    def agree(self) -> bool | None:
        return None if not self.jev else self.jev == self.heuristic

    @property
    def signature(self) -> tuple:
        """What has to change for a new record to be worth writing."""
        return (self.heuristic, self.jev, self.jev and round(self.confidence or 0, 2))

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
            "verdict=%s status=%s latency_ms=%d mode=%s why=%r"
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
    offered = options(row, holding, family.characters)
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
        closet=wardrobes(characters, worn_items, describe, specs or {}),
        pipeline=Pipeline.read(gear_rows, worn_rows, names, keep_names),
        modes=dict(modes or {}),
    )
    asks = _questions(family, gear_rows, describe)[: max(0, int(limit))]
    gate = asyncio.Semaphore(max(1, int(getattr(client, "concurrency", 1))))

    async def one(ask):
        base, state, questions, qid = ask
        async with gate:
            outcome = await client.ask(base.kind, state, questions)
        return _judged(base, outcome, qid)

    return list(await asyncio.gather(*(one(a) for a in asks)))


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
