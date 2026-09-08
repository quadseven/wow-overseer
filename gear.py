"""Which looted weapon or armour piece is an upgrade for a sibling, and who
should end up wearing it (mod-overseer#14, infra#2813).

WHY THIS EXISTS. The family rolls Group Loot, so an item lands on whoever won
the roll, never on whoever can use it - mod-playerbots' own loot-roll fix
(mod-playerbots' 0013 patch, mod-overseer#11's sibling issue) makes sure
SOMEBODY wins a rare drop rather than nobody, and that is exactly how Ugga
the priest ended up carrying seven weapons she can never equip, including a
green Severing Axe that is a real warrior drop. Nothing before this module
ever asked "is this an upgrade for someone standing next to me?" - loot lands
where the roll (or the timeout, #11) put it and stays there forever.

WHY "UPGRADE" CANNOT BE ITEM LEVEL ALONE. #2813 measured the failure mode
this module exists to avoid: a green two-handed axe beats a green one-handed
sword on every naive item-level comparison, while being a strict downgrade
for a character currently wielding a shield - equipping the axe silently
unslots the shield. is_upgrade_for() below is the class- AND role-aware test
the issue asked for: class-eligibility from the item's own AllowableClass
bitmask (the same bit mod-playerbots' CanBotUseToken and LootRollAction check
for the item's own holder, aimed here at a third party instead), and a
role guard that refuses a two-hander for anyone currently wearing something
in the off hand - not because this module knows who is "a tank", but because
it can OBSERVE, right now, that taking the two-hander would cost that
character an equipped item, which is the one fact available without a spec
or talent read this codebase has nowhere else needed.

WHY kind='trade' AND NOT NEW C++. infra#2597 built DoGive (a database move)
and a later patch (mod-overseer#14's own hand-off half) built DoTrade - a
real in-world trade through the core's own WorldSession handlers, so the
exchange renders and animates instead of an item appearing in a bag with no
visible cause. See mod_overseer.cpp's DoTrade banner and
2026_08_29_00_overseer_trade.sql for the mechanism itself; this module
supplies only the WHO and the WHAT, the same split materials.py and
professions.py already use for give and trainer errands. Reusing an existing
kind rather than inventing one is deliberate - see mod-overseer#14's own "Why"
section, which asks for exactly this hand-off, not a new one.

WHAT THIS MODULE DOES NOT DECIDE. It never proposes taking an item away from
a character who could use it themselves - plan() checks the HOLDER's own
eligibility first and leaves the item alone if the holder would also call it
an upgrade, so this can only ever move dead weight, never shuffle gear
sideways between two characters who both have a claim on it. It also never
sees an equipped item (bridge.py's fetch excludes bag 0/slot < 19, the exact
range materials._HOLDINGS_SQL already excludes for the same reason) or
anything that is not Class WEAPON or ARMOR - quest items, reagents and
consumables are invisible to it by construction, which is how "quest items
and equipped items are never traded away" (#14's own acceptance criterion)
is satisfied: not by a special-case check, but by never being asked about.

WHAT IS STILL UNVERIFIED. This module's tests are unit tests against
synthetic Holdings and CharacterStates - they prove the DECISION is right for
the inputs given, exactly as materials.py's own tests do, and say so for the
same reason: a `delivered` overseer_command row means nothing was verified
until it is watched happen. No drop has been watched moving through this path
on the running server.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# WoW's numeric class ids (characters.class / item_template.AllowableClass
# bit position), the same table panel.py's _CLASS_NAMES keys against.
# Duplicated rather than imported so this stays a pure, dependency-free
# decision module the way materials.py and professions.py are.
_CLASS_NAMES = {
    1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest",
    6: "Death Knight", 7: "Shaman", 8: "Mage", 9: "Warlock", 11: "Druid",
}

ITEM_CLASS_WEAPON = 2
ITEM_CLASS_ARMOR = 4

# InventoryType -> the equip "slot bucket" plan() compares an item against.
# Deliberately small and deliberately conservative: an inventory type not
# listed here is a piece this module has no opinion about and leaves alone -
# the same policy materials.REAGENTS applies to an unlisted material. A
# guessed mapping is how a mail chest ends up "fitting" a cloth caster.
_HEAD, _SHOULDER, _CHEST, _WAIST = "head", "shoulder", "chest", "waist"
_LEGS, _FEET, _WRIST, _HANDS, _BACK = "legs", "feet", "wrist", "hands", "back"
_MAIN_HAND, _OFF_HAND, _TWO_HAND, _RANGED = (
    "main_hand", "off_hand", "two_hand", "ranged",
)

_SLOT_BY_INVTYPE = {
    1: _HEAD, 3: _SHOULDER, 5: _CHEST, 6: _WAIST, 7: _LEGS, 8: _FEET,
    9: _WRIST, 10: _HANDS, 16: _BACK, 20: _CHEST,
    13: _MAIN_HAND, 21: _MAIN_HAND,
    14: _OFF_HAND, 22: _OFF_HAND, 23: _OFF_HAND,
    17: _TWO_HAND,
    15: _RANGED, 25: _RANGED, 26: _RANGED,
}

# The slot bucket(s) that occupy a character's off hand. A two-hander
# conflicts with any of them - the Severing Axe test (#2813).
_OFF_HAND_SLOTS = (_OFF_HAND,)


@dataclass(frozen=True)
class Holding:
    """One weapon or armour item sitting in a family member's BAGS (never
    equipped - bridge.py's fetch excludes bag 0/slot < 19, the same range
    materials._HOLDINGS_SQL excludes and for the same reason), eligible to be
    handed on if somebody else can actually use it.

    Field names mirror item_template's own columns (see mod-playerbots'
    0013 patch, which cites the same five: Quality, ItemLevel,
    RequiredLevel, Class/SubClass, AllowableClass) so a reader who already
    knows that patch recognises this shape immediately.
    """

    holder: str
    guid: int
    entry: int
    name: str
    quality: int
    item_level: int
    required_level: int
    allowable_class: int
    inventory_type: int
    item_class: int
    soulbound: bool = False


@dataclass(frozen=True)
class CharacterState:
    """What plan() needs to know about one live family member: which class
    they are (class-eligibility, from AllowableClass) and their currently
    EQUIPPED item level per slot bucket (upgrade-eligibility and the role
    guard) - both facts the Severing Axe scenario needs, and neither of
    which item level alone gives you.

    `equipped` maps a slot bucket (a value from _SLOT_BY_INVTYPE) to the
    item level of whatever is worn there now. A slot missing from this dict
    is treated as empty (item level 0) - nothing worn, so anything eligible
    counts as an upgrade.
    """

    name: str
    class_id: int
    level: int
    equipped: dict = field(default_factory=dict)

    def equipped_level(self, slot: str) -> int:
        return int(self.equipped.get(slot, 0))

    def has_off_hand(self) -> bool:
        return any(self.equipped_level(s) > 0 for s in _OFF_HAND_SLOTS)


@dataclass(frozen=True)
class Grant:
    """One item, moving from the family member who cannot use it to the one
    who can, by real in-world trade."""

    holder: str
    taker: str
    entry: int
    name: str
    guid: int
    reason: str
    said: str

    @property
    def command(self) -> str:
        """What mod-overseer's DoTrade parses out of `overseer_command.command`.

        `guid:` and not `entry:` - ParseGiveSpec (mod_overseer.cpp) accepts
        either, but only `guid:` names the exact item_instance that dropped.
        `entry:` lets the worldserver pick any matching stack off the
        holder's bags, which is fine for a reagent (materials.py uses guid:
        too, for the same accuracy reason) and for a unique drop is a silent
        chance to hand over the wrong copy.
        """
        return "guid:%d" % int(self.guid)


@dataclass(frozen=True)
class Plan:
    grants: tuple = ()
    # Held items that are gear (weapon/armor) but that this module declined
    # to move, and why - so a person reading the log can tell "nothing to
    # move" from "moved nothing on purpose".
    notes: tuple = ()


def _slot_for(holding: Holding) -> str:
    return _SLOT_BY_INVTYPE.get(int(holding.inventory_type), "")


def usable_by_class(holding: Holding, class_id: int) -> bool:
    """AllowableClass is a bitmask, bit (class_id - 1) - the same test
    mod-playerbots' CanBotUseToken (LootRollAction.cpp) applies for a token,
    generalised here to any piece of gear and aimed at a third party instead
    of the item's own holder."""
    if class_id < 1:
        return False
    return bool(int(holding.allowable_class) & (1 << (class_id - 1)))


def would_wear(holding: Holding, character: CharacterState) -> tuple:
    """Would this character actually put this on, ignoring who may own it.

    THE BINDING QUESTION IS NOT ASKED HERE, and that omission is the whole
    point of the split (infra#3449). "Can this item move to that character"
    and "would that character wear it" are different questions, and
    `is_upgrade_for` answers the first by answering the second and refusing
    anything soulbound. That refusal is right for a hand-off and WRONG for
    the character already holding it, who needs no hand-off at all: a
    soulbound green in Grog's own bags is still the best chest Grog owns.

    MEASURED ON THE DEV FAMILY, 2026-09-08. Asking `is_upgrade_for` about a
    holder's own bags calls 7 soulbound greens unwanted while they beat what
    that character is wearing, among them Grog's Watcher's Jerkin (item level
    30 against an equipped 23) and Og's Buccaneer's Orb. Two of those were
    already inside the four rows the shipped vendor pass would have sold.

    Returns (would_wear: bool, reason: str), the same pair `is_upgrade_for`
    returns and for the same reason: a False is logged as often as a True.
    """
    if holding.item_class not in (ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR):
        return False, "not gear (quest items, reagents and consumables are never considered)"
    if not usable_by_class(holding, character.class_id):
        cls = _CLASS_NAMES.get(character.class_id, "class %d" % character.class_id)
        return False, f"{cls} cannot equip it"
    if character.level < holding.required_level:
        return False, f"requires level {holding.required_level}"

    slot = _slot_for(holding)
    if not slot:
        return False, "inventory type %d has no known slot" % int(holding.inventory_type)

    # THE ROLE GUARD (the Severing Axe test, #2813). A two-hander is never an
    # upgrade for anyone currently wearing something in the off hand: taking
    # it would silently unequip a shield (or another off-hand piece), a
    # downgrade for the wearer's actual role even though the two-hander alone
    # carries the bigger item level. Nothing here claims to know the
    # character IS a shield tank - only that they are, right now, in the
    # world, wearing something a two-hander would knock off, which is the one
    # fact this module can observe rather than guess at.
    if slot == _TWO_HAND and character.has_off_hand():
        return False, "would displace an equipped off-hand item"

    current = character.equipped_level(slot)
    if current and holding.item_level <= current:
        return False, f"not an upgrade (currently equipped is item level {current})"

    return True, (
        f"empty {slot.replace('_', ' ')} slot" if not current
        else f"item level {holding.item_level} beats the equipped {current}"
    )


def is_upgrade_for(holding: Holding, character: CharacterState) -> tuple:
    """Would `holding` be a real upgrade for `character` - the class- and
    role-aware test #14 asked for, not "does item level beat item level".

    Soulbound is refused here and only here, because this question is asked
    about a hand-off: an item bound to whoever picked it up cannot reach a
    third party at all, so wanting it is beside the point. For the holder's
    own claim on their own bags, ask `would_wear` instead.

    Returns (is_upgrade: bool, reason: str). `reason` explains a False as
    much as a True, since plan() logs both rather than only the ones that
    move.
    """
    if holding.item_class not in (ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR):
        return False, "not gear (quest items, reagents and consumables are never considered)"
    if holding.soulbound:
        return False, "soulbound to the current holder"
    return would_wear(holding, character)


def plan(holdings, characters) -> Plan:
    """Every item that should move because it is dead weight where it sits
    and a real upgrade for someone else.

    Deterministic: sorted by (holder, guid), the same ordering rule
    materials.plan uses, so a re-run against unchanged bags and gear proposes
    an identical plan and bridge.py's dedupe sees the same key twice rather
    than a shuffled one that never matches.

    THE HOLDER GETS FIRST CLAIM. An item is only ever a candidate to move
    when it is NOT an upgrade for the character already holding it - checked
    before any sibling is considered. That is what stops this from ever
    taking something away from a character who has a legitimate use for it,
    and it is why "an item won by a character who cannot use it should reach
    the character who can" (this issue's own framing) is true of every grant
    this function proposes.

    ONE TAKER PER ITEM: whoever it is the biggest upgrade for (item level
    gained over what they currently have equipped in that slot), ties broken
    by name for a deterministic order. Never every eligible character, and
    never the smallest beneficiary - handing dead weight to whoever benefits
    most is the only rule that cannot regress into shuffling gear sideways
    forever.
    """
    by_name = {c.name: c for c in characters}
    grants = []
    notes = []
    for holding in sorted(holdings, key=lambda h: (h.holder, h.guid)):
        holder_state = by_name.get(holding.holder)
        if holder_state is not None:
            holder_upgrade, _ = is_upgrade_for(holding, holder_state)
            if holder_upgrade:
                # The holder has a legitimate claim on it; not this
                # module's business to move it, silently and correctly.
                continue

        candidates = []
        for character in characters:
            if character.name == holding.holder:
                continue
            upgrade, reason = is_upgrade_for(holding, character)
            if not upgrade:
                continue
            gain = holding.item_level - character.equipped_level(_slot_for(holding))
            candidates.append((gain, character.name, reason))

        if not candidates:
            notes.append(
                f"{holding.holder} holds {holding.name} (item level "
                f"{holding.item_level}) and nobody else in the family can use it"
            )
            continue

        candidates.sort(key=lambda c: (-c[0], c[1]))
        _, taker_name, reason = candidates[0]
        taker = by_name[taker_name]
        grants.append(Grant(
            holder=holding.holder, taker=taker.name, entry=holding.entry,
            name=holding.name, guid=holding.guid,
            reason=(
                f"{holding.holder} is holding {holding.name} (item level "
                f"{holding.item_level}) with no use for it, and {taker.name} "
                f"can: {reason}."
            ),
            said=f"{holding.holder} trade {taker.name} {holding.name}.",
        ))
    return Plan(grants=tuple(grants), notes=tuple(notes))


def lines(gear_plan: Plan) -> list:
    """The family saying it, "Name: words" - the shape professions.lines and
    materials.lines already speak in, so a hand-off is a line in party chat
    and never a silent database write."""
    return [f"{g.holder}: {g.said}" for g in gear_plan.grants]


# ---------------------------------------------------------------------------
# WHO IN THE FAMILY WANTS THIS, ASKED SO THAT A DISPOSAL RULE CAN HEAR "NOBODY"
#
# Everything above answers "should this move", and answers it for the give
# path. `claimant` asks the mirror question the sell path needs (infra#3449):
# before anything is sold, is there ANYBODY - the holder included - who would
# wear this? Disposal is the one decision that cannot be taken back, so the
# gate that guards it must be the same opinion that decides hand-offs, not a
# second one written next to it that will drift.
#
# THREE ANSWERS, NOT TWO. "Nobody wants it" and "I cannot tell" are different
# facts and collapsing them is how gear gets sold for want of a lookup table.
# Measured 2026-09-08: the family carries 3 green rings (InventoryType 11),
# and _SLOT_BY_INVTYPE has no entry for finger slots, so every one of them
# answers "no upgrade for anyone" to a naive reading. They are UNJUDGEABLE,
# which keeps them, and the deliberately small slot map (see its own comment)
# stays a refusal rather than becoming a licence.

# Nobody in the family would wear it. The only answer that permits disposal.
NOBODY = ""
# This module cannot form an opinion: not weapon or armour, an inventory type
# it has no slot for, or a holder it was given no character for. KEEPS.
UNJUDGEABLE = "?"


def claimant(holding: Holding, characters) -> str:
    """Who would wear this: the holder, a sibling, NOBODY, or UNJUDGEABLE.

    THE HOLDER IS ASKED FIRST AND ASKED SOULBOUND-BLIND, via `would_wear`.
    They are already carrying it, so no hand-off has to be legal for them to
    put it on, and asking `is_upgrade_for` here would call every soulbound
    upgrade unwanted - the exact failure `would_wear`'s docstring measures.

    Siblings are asked with `is_upgrade_for`, binding refusal and all,
    because reaching a sibling IS a hand-off. A sibling who could wear a
    soulbound piece never gets it, so their opinion does not protect it; the
    holder's does, and it was asked first.

    One name is returned rather than a ranking. Ranking who benefits most is
    `plan`'s job and stays there; this only has to answer whether disposal is
    off the table, and any single claimant settles that.
    """
    by_name = {c.name: c for c in characters}
    if holding.item_class not in (ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR):
        return UNJUDGEABLE
    if not _slot_for(holding):
        return UNJUDGEABLE
    holder = by_name.get(holding.holder)
    if holder is None:
        # A row whose holder nobody described. Refusing beats guessing that
        # the absent character had no use for their own gear.
        return UNJUDGEABLE
    if would_wear(holding, holder)[0]:
        return holder.name
    for character in sorted(characters, key=lambda c: c.name):
        if character.name == holding.holder:
            continue
        if is_upgrade_for(holding, character)[0]:
            return character.name
    return NOBODY


def claims(holdings, characters) -> dict:
    """`claimant` over many holdings, keyed by item guid for the sell path."""
    return {int(h.guid): claimant(h, characters) for h in holdings}


# ---------------------------------------------------------------------------
# FROM ROWS TO THE TWO SHAPES ABOVE
#
# The same seam bag_upgrade.members_from_rows and bank.members_from_rows use,
# and here for the same reason: which world row means what is a decision, it
# wants testing against rows written by hand, and bridge.py should stay a
# thing that fetches and writes rather than a thing that knows the 3.3.5 slot
# enums. Both functions are total - they never raise on a row they cannot
# read, they drop it, and a dropped row simply has no claimant.

# bag 0, slot 0..18 is what a character is WEARING. `characters_from_rows`
# reads exactly this range and `holdings_from_rows` never sees it, because
# the gear SQL excludes it - see _SURPLUS_GEAR_SQL.
EQUIPPED_POSITIONS = range(0, 19)


def characters_from_rows(rows, names) -> list:
    """One CharacterState per name, from equipped rows joined to characters.

    A NAME WITH NO USABLE ROW IS LEFT OUT, not defaulted. `claimant` answers
    UNJUDGEABLE for a holder it was given no character for, which keeps that
    character's gear; inventing a level-1 warrior for them instead would make
    every piece they carry look like nobody's upgrade and offer the lot to a
    vendor. The caller passes `names` so the order is the family's, not the
    query planner's.

    Rows carry name, class_id, level and, when something is worn in the slot,
    inventory_type and item_level. A LEFT JOIN row for a character wearing
    nothing at all still names them, and they get an empty equipped map.
    """
    seen = {}
    for row in rows:
        try:
            name = str(row["name"])
            if name not in names:
                continue
            class_id = int(row["class_id"])
            level = int(row["level"])
        except (KeyError, TypeError, ValueError):
            continue
        equipped = seen.setdefault(name, (class_id, level, {}))[2]
        try:
            slot = _SLOT_BY_INVTYPE.get(int(row["inventory_type"]), "")
            item_level = int(row["item_level"])
        except (KeyError, TypeError, ValueError):
            continue
        if slot:
            # Two rings, two trinkets, a main hand and an off hand all land in
            # one bucket. The BEST of them is what an upgrade has to beat,
            # because the worst is the one a new piece would displace.
            equipped[slot] = max(equipped.get(slot, 0), item_level)
    return [CharacterState(name=name, class_id=seen[name][0],
                           level=seen[name][1], equipped=seen[name][2])
            for name in names if name in seen]


def holdings_from_rows(rows) -> list:
    """Holdings from the carried-gear rows, dropping any this cannot describe.

    `soulbound` is read from the INSTANCE flag rather than the template's
    bonding, the same fact and the same bit bag_pressure.item_binding reads,
    because a bind-on-equip green somebody wore once is bound forever while
    its template still says it is tradable.
    """
    out = []
    for row in rows:
        try:
            out.append(Holding(
                holder=str(row["holder"]), guid=int(row["item_guid"]),
                entry=int(row.get("entry", 0)), name=str(row["name"]),
                quality=int(row["quality"]), item_level=int(row["item_level"]),
                required_level=int(row["required_level"]),
                allowable_class=int(row["allowable_class"]),
                inventory_type=int(row["inventory_type"]),
                item_class=int(row["item_class"]),
                soulbound=bool(int(row.get("instance_flags", 0) or 0) & 0x1),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out
