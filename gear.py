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

import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

import weaponskill

# The stuck text names times the way the reader reads them: the operator's
# clock, not UTC. Same convention as runtimeline's operator clock.
try:
    from zoneinfo import ZoneInfo

    _READER_ZONE = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 - no tz database in the image: name UTC as UTC
    _READER_ZONE = timezone.utc


def _reader_due(retry_at) -> str:
    """The retry time as the reader reads it ("03:00"), or "later".

    `retry_at` is the staged retry instant in UTC; the note names it on the
    reader's clock so "tries again at 03:00" means 03:00 where the reader is.
    A hold with no readable refusal time has no retry to name: "later".
    """
    if not isinstance(retry_at, datetime):
        return "later"
    at = (
        retry_at
        if retry_at.tzinfo is not None
        else retry_at.replace(tzinfo=timezone.utc)
    )
    return at.astimezone(_READER_ZONE).strftime("%H:%M")


# The two verbs the world executor understands for moving one item from one
# character's bags into another's, and the single fact that decides between
# them. See `deliverable` for the measurement; in short, DoTrade tests that
# the two are within TRADE_DISTANCE and DoGive does not test position at all.
TRADE = "trade"
GIVE = "give"

# TRADE_DISTANCE (ObjectDefines.h:29), measured in two dimensions because
# DoTrade measures it in two - it calls IsWithinDistInMap(..., false).
TRADE_YARDS = 11.11

# WoW's numeric class ids (characters.class / item_template.AllowableClass
# bit position), the same table panel.py's _CLASS_NAMES keys against.
# Duplicated rather than imported so this stays a pure, dependency-free
# decision module the way materials.py and professions.py are.
_CLASS_NAMES = {
    1: "Warrior",
    2: "Paladin",
    3: "Hunter",
    4: "Rogue",
    5: "Priest",
    6: "Death Knight",
    7: "Shaman",
    8: "Mage",
    9: "Warlock",
    11: "Druid",
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
    "main_hand",
    "off_hand",
    "two_hand",
    "ranged",
)

_SLOT_BY_INVTYPE = {
    1: _HEAD,
    3: _SHOULDER,
    5: _CHEST,
    6: _WAIST,
    7: _LEGS,
    8: _FEET,
    9: _WRIST,
    10: _HANDS,
    16: _BACK,
    20: _CHEST,
    13: _MAIN_HAND,
    21: _MAIN_HAND,
    14: _OFF_HAND,
    22: _OFF_HAND,
    23: _OFF_HAND,
    17: _TWO_HAND,
    15: _RANGED,
    25: _RANGED,
    26: _RANGED,
}

# character_inventory equipment positions (bag 0, slot < 19). InventoryType
# 13 means a weapon that can go in either hand; the worn row's position is the
# fact that distinguishes a main-hand copy from an off-hand copy.
_EQUIPMENT_SLOT_MAIN_HAND = 15
_EQUIPMENT_SLOT_OFF_HAND = 16

# The slot bucket(s) that occupy a character's off hand. A two-hander
# conflicts with any of them - the Severing Axe test (#2813).
_OFF_HAND_SLOTS = (_OFF_HAND,)

# ---------------------------------------------------------------------------
# WHAT A CLASS CAN ACTUALLY WEAR, WHICH AllowableClass DOES NOT SAY
#
# AllowableClass is -1 on essentially every piece of armour in the game - it
# exists to restrict a libram or a class token, not to say a priest cannot
# wear mail. So `usable_by_class` alone answers YES for a warrior asked about
# a cloth robe and, far worse, YES for a priest asked about mail boots.
#
# MEASURED 2026-09-11: the planner proposed handing Battleforge Boots (mail)
# to Ugga, who is a priest, and 7 of the 24 cross-member upgrades the family
# is sitting on are held by somebody who physically cannot equip them. The
# holder-first-claim rule in `plan` reads that same false YES, so a priest
# hoarding mail counts as having a claim on it and the piece never moves at
# all - the refusal and the misdelivery are the same missing fact.
#
# item_template.subclass for class 4 (ARMOR). 5 is the buckler, gated as a
# shield by its InventoryType (see `wearable_armor`), and
# 7-10 are librams, idols, totems and sigils, which AllowableClass really
# does gate - so only 1-4 and 6 are decided here.
ARMOR_MISC, ARMOR_CLOTH, ARMOR_LEATHER, ARMOR_MAIL, ARMOR_PLATE = 0, 1, 2, 3, 4
ARMOR_SHIELD = 6

# Class id -> the armour types it is trained in, and the level it trains.
# Everyone wears cloth from level 1, so cloth is the floor rather than a row.
# The two entries that are not level 1 are the ones that matter to a family
# at 38-39: a warrior or paladin is in MAIL until Plate Mail at 40, and a
# hunter or shaman is in LEATHER until Mail at 40.
_ARMOR_TRAINED_AT = {
    1: ((ARMOR_MAIL, 1), (ARMOR_PLATE, 40)),  # Warrior
    2: ((ARMOR_MAIL, 1), (ARMOR_PLATE, 40)),  # Paladin
    3: ((ARMOR_LEATHER, 1), (ARMOR_MAIL, 40)),  # Hunter
    4: ((ARMOR_LEATHER, 1),),  # Rogue
    5: (),  # Priest - cloth only
    6: ((ARMOR_PLATE, 1),),  # Death Knight
    7: ((ARMOR_LEATHER, 1), (ARMOR_MAIL, 40)),  # Shaman
    8: (),  # Mage - cloth only
    9: (),  # Warlock - cloth only
    11: ((ARMOR_LEATHER, 1),),  # Druid
}

# A shield is not "heavier armour", it is its own proficiency.
_SHIELD_CLASSES = frozenset({1, 2, 7})

# A Holding built without the fact. NOT STATED is not the same as "misc", and
# it means this check abstains rather than guesses - the same shape
# `bag_pressure.gear_candidates` gives `fits=None`. bridge.py always states
# it; tests written before the fact existed do not have to.
SUBCLASS_UNSTATED = -1


# ---------------------------------------------------------------------------
# WHICH WEAPONS A CLASS CAN SWING, WHICH AllowableClass DOES NOT SAY EITHER
#
# The armour table above exists because AllowableClass is -1 on almost every
# piece. Weapons are the same: Destiny, a two-hand sword, carries -1, so
# `usable_by_class` says a warlock can wield it. Measured on the dev realm
# 2026-09-22, a level 60 warlock guildmate carried Destiny and two other
# two-handers she can never swing, and the question "who in the guild gains
# most from this" (#174) cannot be asked honestly while the answer includes
# every caster in the guild.
#
# item_template.subclass for class 2 (WEAPON). The fishing pole (20) and the
# miscellaneous weapon (14) are not decided here; `wieldable_weapon` abstains
# on them the way `wearable_armor` abstains on a libram.
WEAPON_AXE, WEAPON_AXE2, WEAPON_BOW, WEAPON_GUN = 0, 1, 2, 3
WEAPON_MACE, WEAPON_MACE2, WEAPON_POLEARM = 4, 5, 6
WEAPON_SWORD, WEAPON_SWORD2, WEAPON_STAFF = 7, 8, 10
WEAPON_FIST, WEAPON_DAGGER, WEAPON_THROWN = 13, 15, 16
WEAPON_CROSSBOW, WEAPON_WAND = 18, 19

_ALL_MELEE_AND_RANGED = frozenset(
    {
        WEAPON_AXE,
        WEAPON_AXE2,
        WEAPON_BOW,
        WEAPON_GUN,
        WEAPON_MACE,
        WEAPON_MACE2,
        WEAPON_POLEARM,
        WEAPON_SWORD,
        WEAPON_SWORD2,
        WEAPON_STAFF,
        WEAPON_FIST,
        WEAPON_DAGGER,
        WEAPON_THROWN,
        WEAPON_CROSSBOW,
    }
)

# Class id -> the weapon subclasses its trainers teach by level 60 in 3.3.5.
_WEAPON_SKILLS = {
    1: _ALL_MELEE_AND_RANGED,  # Warrior: everything but a wand
    2: frozenset(
        {
            WEAPON_AXE,
            WEAPON_AXE2,
            WEAPON_MACE,
            WEAPON_MACE2,
            WEAPON_POLEARM,
            WEAPON_SWORD,
            WEAPON_SWORD2,
        }
    ),  # Paladin
    3: _ALL_MELEE_AND_RANGED - {WEAPON_MACE, WEAPON_MACE2},  # Hunter
    4: frozenset(
        {
            WEAPON_AXE,
            WEAPON_BOW,
            WEAPON_GUN,
            WEAPON_MACE,
            WEAPON_SWORD,
            WEAPON_FIST,
            WEAPON_DAGGER,
            WEAPON_THROWN,
            WEAPON_CROSSBOW,
        }
    ),  # Rogue
    5: frozenset({WEAPON_MACE, WEAPON_STAFF, WEAPON_DAGGER, WEAPON_WAND}),  # Priest
    6: frozenset(
        {
            WEAPON_AXE,
            WEAPON_AXE2,
            WEAPON_MACE,
            WEAPON_MACE2,
            WEAPON_POLEARM,
            WEAPON_SWORD,
            WEAPON_SWORD2,
        }
    ),  # Death Knight
    7: frozenset(
        {
            WEAPON_AXE,
            WEAPON_AXE2,
            WEAPON_MACE,
            WEAPON_MACE2,
            WEAPON_STAFF,
            WEAPON_FIST,
            WEAPON_DAGGER,
        }
    ),  # Shaman
    8: frozenset({WEAPON_SWORD, WEAPON_STAFF, WEAPON_DAGGER, WEAPON_WAND}),  # Mage
    9: frozenset({WEAPON_SWORD, WEAPON_STAFF, WEAPON_DAGGER, WEAPON_WAND}),  # Warlock
    11: frozenset(
        {
            WEAPON_MACE,
            WEAPON_MACE2,
            WEAPON_POLEARM,
            WEAPON_STAFF,
            WEAPON_FIST,
            WEAPON_DAGGER,
        }
    ),  # Druid
}

_KNOWN_WEAPON_SUBCLASSES = _ALL_MELEE_AND_RANGED | {WEAPON_WAND}


def class_wields(holding: Holding, character: CharacterState) -> bool:
    """Can this character's class wield this weapon at all, learned or not.

    Abstains - returns True - for anything that is not a weapon, for a
    subclass this table does not decide, for a class it does not list, and
    for a row that never stated its subclass, which is the same abstention
    `wearable_armor` makes and for the same reason.
    """
    if int(holding.item_class) != ITEM_CLASS_WEAPON:
        return True
    subclass = int(holding.item_subclass)
    if subclass not in _KNOWN_WEAPON_SUBCLASSES:
        return True
    skills = _WEAPON_SKILLS.get(int(character.class_id))
    if skills is None:
        return True
    return subclass in skills


def weapon_trained(holding: Holding, character: CharacterState) -> bool:
    """Has this character learned the weapon skill this piece needs.

    THE CLASS SAYS WHAT CAN BE LEARNED, NOT WHAT IS (#393). Measured on
    wow-dev 2026-09-28: Og, a level 35 mage, carried Silithid Ripper, a
    one-hand sword, with no Swords skill (character_skills 43 absent). A
    mage's class can wield a sword, so the sword was planned as Og's and the
    equip pass asked three times; the core refuses to equip a weapon whose
    skill is not learned, and Og stayed unarmed. `weapon_skills` is the
    learned set, read from character_skills; None means it was not read, and
    the answer abstains to True, which is the class-only judgement as before.
    """
    if character.weapon_skills is None:
        return True
    if int(holding.item_class) != ITEM_CLASS_WEAPON:
        return True
    subclass = int(holding.item_subclass)
    if subclass not in _KNOWN_WEAPON_SUBCLASSES:
        return True
    return subclass in character.weapon_skills


def wieldable_weapon(holding: Holding, character: CharacterState) -> bool:
    """Can this character wield this weapon now: the class can, and, when the
    learned skills were read, the skill is learned (#393)."""
    return class_wields(holding, character) and weapon_trained(holding, character)


# ---------------------------------------------------------------------------
# THE ROLE, WHICH DECIDES WHETHER A SHIELD IS WORTH KEEPING
#
# The off-hand guard in `would_wear` refuses a two-hander to anybody wearing a
# shield, because it cannot tell a tank from a damage dealer who happens to
# carry one. Measured 2026-09-22: the family's Retribution paladin wore a one
# hand axe and a shield, so every two-hander the guild found for him was
# refused on his behalf. `role` is that missing fact, filled from the same
# party packing the lineup uses (raidlineup.party_roles). ROLE_UNKNOWN keeps
# the old guard exactly, so a character nobody assigned a role is judged as
# before.
ROLE_UNKNOWN = ""
ROLE_TANK = "tank"
ROLE_HEALER = "healer"
ROLE_DAMAGE = "damage"

# Warrior, paladin and death knight: the classes whose damage specs are built
# around a two-hander, so a shield on one of them in a damage role is a spare
# rather than a job.
_TWO_HANDER_CLASSES = frozenset({1, 2, 6})


def prefers_two_hander(character: CharacterState) -> bool:
    """Would a two-hander replace this character's shield rather than cost it."""
    return (
        str(character.role) == ROLE_DAMAGE
        and int(character.class_id) in _TWO_HANDER_CLASSES
    )


# ---------------------------------------------------------------------------
# WHAT A TANK'S OFF HAND IS FOR
#
# Measured on the dev realm 2026-09-26, after the operator lowered the family
# to its natural levels. Grug, the Protection warrior who tanks for the
# Alliance family, went from 60 to 38, and every shield in his reach needed 39
# to 58. Grog handed him a Sorcerer Sphere (InventoryType 23, held in the off
# hand, armour subclass 0) and the equip pass put it on, because an empty off
# hand read as item level 0 and `wearable_armor` abstains on subclass 0. He
# died four times in thirteen minutes in Desolace. The item-level comparison
# was not wrong about the numbers; nothing asked what the off hand is for.
#
# InventoryType of the three things an off hand can hold besides a one-hander.
INVTYPE_SHIELD = 14
INVTYPE_WEAPON_OFF_HAND = 22
INVTYPE_HOLDABLE = 23

# What is worn in the off hand, read from its InventoryType.
OFF_HAND_NONE = ""
OFF_HAND_SHIELD = "shield"
OFF_HAND_HELD = "held"
OFF_HAND_WEAPON = "weapon"
_OFF_HAND_KIND = {
    INVTYPE_SHIELD: OFF_HAND_SHIELD,
    INVTYPE_HOLDABLE: OFF_HAND_HELD,
    INVTYPE_WEAPON_OFF_HAND: OFF_HAND_WEAPON,
}
_OFF_HAND_SAID = {
    OFF_HAND_HELD: "a held-in-off-hand piece",
    OFF_HAND_WEAPON: "an off-hand weapon",
}

# Warrior, rogue and death knight have no mana: a held-in-off-hand is a
# caster's piece and nothing on one is ever for them.
_NO_HELD_CLASSES = frozenset({1, 4, 6})
# A paladin in a damage role is Retribution, a melee fighter: the same answer
# mod-overseer's scorer gives its melee role.
_PALADIN = 2


def shield_tank(character: CharacterState) -> bool:
    """A tank whose class holds a shield: warrior, paladin (shaman never
    tanks in a party). A feral druid in a tank seat is a tank without one."""
    return (
        str(character.role) == ROLE_TANK and int(character.class_id) in _SHIELD_CLASSES
    )


def is_shield(holding: Holding) -> bool:
    return int(holding.inventory_type) == INVTYPE_SHIELD


def _off_hand_refusal(holding: Holding, character: CharacterState) -> str:
    """Why this off-hand piece is not for this character, or ""."""
    kind = _OFF_HAND_KIND.get(int(holding.inventory_type), OFF_HAND_NONE)
    melee_paladin = (
        int(character.class_id) == _PALADIN and str(character.role) == ROLE_DAMAGE
    )
    if kind == OFF_HAND_HELD and melee_paladin:
        return "a held-in-off-hand piece is a caster's, and a Retribution paladin has no use for one"
    if kind == OFF_HAND_HELD and int(character.class_id) in _NO_HELD_CLASSES:
        cls = _CLASS_NAMES.get(character.class_id, "class %d" % character.class_id)
        return f"a held-in-off-hand piece is a caster's, and a {cls} has no use for one"
    if kind in (OFF_HAND_HELD, OFF_HAND_WEAPON) and shield_tank(character):
        return (
            "%s is never a tank's: a tank holds a shield in the off hand"
            % (_OFF_HAND_SAID[kind])
        )
    return ""


def _shield_over_other(holding: Holding, character: CharacterState) -> bool:
    """A shield for a shield tank whose off hand holds something else."""
    return (
        is_shield(holding)
        and shield_tank(character)
        and character.off_hand_kind not in (OFF_HAND_NONE, OFF_HAND_SHIELD)
    )


def heaviest_armor(class_id: int, level: int) -> int:
    """The heaviest armour subclass this character is trained in right now."""
    best = ARMOR_CLOTH
    for subclass, trained_at in _ARMOR_TRAINED_AT.get(int(class_id), ()):
        if int(level) >= trained_at:
            best = max(best, subclass)
    return best


def wearable_armor(holding: Holding, character: CharacterState) -> bool:
    """Can this character's class physically equip this piece of armour.

    Abstains - returns True - for anything that is not armour, for a subclass
    AllowableClass genuinely does gate, and for a row that never stated its
    subclass. Refusing on a fact nobody supplied would stop every hand-off on
    an older world image; guessing the other way is how a mail chest ends up
    "fitting" a cloth caster, which is the failure this exists to stop.
    """
    if int(holding.item_class) != ITEM_CLASS_ARMOR:
        return True
    subclass = int(holding.item_subclass)
    # A buckler (subclass 5) is held in the shield slot and the world refuses
    # it to a class with no shield skill, so the slot decides, not the subclass.
    if subclass == ARMOR_SHIELD or is_shield(holding):
        return int(character.class_id) in _SHIELD_CLASSES
    if subclass not in (ARMOR_CLOTH, ARMOR_LEATHER, ARMOR_MAIL, ARMOR_PLATE):
        return True
    return subclass <= heaviest_armor(character.class_id, character.level)


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
    # item_template.subclass - for armour, cloth/leather/mail/plate, which is
    # the fact AllowableClass does not carry. SUBCLASS_UNSTATED means the row
    # did not say and `wearable_armor` abstains.
    item_subclass: int = SUBCLASS_UNSTATED
    # The item carries a spell (item_template.spellid_1..5): an on-use, an
    # on-equip or a chance-on-hit effect. Item level cannot price one, so a
    # ranking that compares item levels is only a floor for it (#174).
    has_effect: bool = False


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
    # ROLE_TANK, ROLE_HEALER, ROLE_DAMAGE or ROLE_UNKNOWN. See
    # `prefers_two_hander`: only a damage role on a two-hander class changes
    # anything, and unknown keeps the off-hand guard.
    role: str = ROLE_UNKNOWN
    # OFF_HAND_SHIELD, OFF_HAND_HELD, OFF_HAND_WEAPON, or OFF_HAND_NONE for an
    # empty off hand or one this row could not read. What decides whether a
    # shield is an upgrade for a tank whatever the item levels say.
    off_hand_kind: str = OFF_HAND_NONE
    # The weapon subclasses (item_template.subclass) this character has
    # learned the skill for, from character_skills, or None when that was
    # not read. None keeps the class-only judgement (#393).
    weapon_skills: frozenset | None = None

    def equipped_level(self, slot: str) -> int:
        return int(self.equipped.get(slot, 0))

    def has_off_hand(self) -> bool:
        return any(self.equipped_level(s) > 0 for s in _OFF_HAND_SLOTS)


@dataclass(frozen=True)
class Grant:
    """One item, moving from the family member who cannot use it to the one
    who can.

    `verb` is how it moves, and it is a fact about where the two of them are
    standing rather than a taste: TRADE while they are close enough for the
    core to run a real trade, MAIL when they are apart and the holder stands
    at a mailbox, and never GIVE, which mod-overseer#566 refuses outside trade
    range (#189). `plan` does not set it -
    it answers WHO and WHAT and has never been able to see the world - so it
    stays TRADE until `deliverable` has looked.

    `alternates` is the REST of the ranking, best first, as fully formed
    Grants for the same item with a different taker. It exists because a
    ranking and a refusal are different jobs and were being done by one value
    (infra#4198): `plan` collapsed four eligible siblings to the one who gained
    most, and `deliverable` then found that one had no bag room and dropped the
    item, with three siblings who had room never asked. Carrying the runners-up
    keeps the split the two functions already have - `plan` says who SHOULD
    have it and cannot see the world, `deliverable` says who CAN take it right
    now and is the only half that looks - instead of teaching `plan` about bag
    slots. `deliverable` empties this on whatever it emits, so a Grant that
    reaches the insert path carries one taker and nothing else.
    """

    holder: str
    taker: str
    entry: int
    name: str
    guid: int
    reason: str
    said: str
    verb: str = TRADE
    alternates: tuple = ()

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
        if self.verb == MAIL:
            return "send item:%d subject:%s" % (int(self.guid), self.name)
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


def _rogue_can_dual_wield_one_hander(
    holding: Holding, character: CharacterState
) -> bool:
    """Whether this generic one-hand weapon can improve a rogue's hands.

    `_cannot_wear` separately checks weapon skill and class eligibility. The
    equip command does not name a hand; Playerbot's scorer chooses the slot.
    """
    return (
        int(character.class_id) == 4
        and int(character.level) >= 10
        and int(holding.inventory_type) == 13
        and int(holding.item_class) == ITEM_CLASS_WEAPON
    )


def usable_by_class(holding: Holding, class_id: int) -> bool:
    """AllowableClass is a bitmask, bit (class_id - 1) - the same test
    mod-playerbots' CanBotUseToken (LootRollAction.cpp) applies for a token,
    generalised here to any piece of gear and aimed at a third party instead
    of the item's own holder."""
    if class_id < 1:
        return False
    return bool(int(holding.allowable_class) & (1 << (class_id - 1)))


def _cannot_wear(holding: Holding, character: CharacterState) -> str:
    """Why this character may not put this on at all, or "": class, armour
    training, weapon skill, level, a known slot and the off hand's use."""
    cls = _CLASS_NAMES.get(character.class_id, "class %d" % character.class_id)
    if not usable_by_class(holding, character.class_id):
        return f"{cls} cannot equip it"
    # AllowableClass said yes, which for armour it says to everyone. Whether
    # the class is trained in that armour type is a separate fact and the one
    # that stops mail reaching the priest - see _ARMOR_TRAINED_AT.
    if not wearable_armor(holding, character):
        return f"{cls} is not trained in that armour type"
    if not class_wields(holding, character):
        return f"{cls} cannot wield that weapon type"
    if not weapon_trained(holding, character):
        return f"{character.name or cls} has not learned that weapon skill"
    if character.level < holding.required_level:
        return f"requires level {holding.required_level}"
    if not _slot_for(holding):
        return "inventory type %d has no known slot" % int(holding.inventory_type)
    return _off_hand_refusal(holding, character)


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
        return (
            False,
            "not gear (quest items, reagents and consumables are never considered)",
        )
    refusal = _cannot_wear(holding, character)
    if refusal:
        return False, refusal
    slot = _slot_for(holding)

    # THE ROLE GUARD (the Severing Axe test, #2813). A two-hander is never an
    # upgrade for anyone currently wearing something in the off hand: taking
    # it would silently unequip a shield (or another off-hand piece), a
    # downgrade for the wearer's actual role even though the two-hander alone
    # carries the bigger item level. Nothing here claims to know the
    # character IS a shield tank - only that they are, right now, in the
    # world, wearing something a two-hander would knock off, which is the one
    # fact this module can observe rather than guess at.
    #
    # A DAMAGE ROLE ON A TWO-HANDER CLASS LIFTS IT (#174), and then the
    # two-hander has to beat the main hand it replaces, not the empty two-hand
    # bucket: the Retribution paladin wearing a one-hander at 52 is not
    # upgraded by a two-hander at 40.
    two_hand = _two_hander_decision(holding, character, slot)
    if two_hand is not None:
        return two_hand

    current = character.equipped_level(slot)
    weaker_hand = _rogue_can_dual_wield_one_hander(holding, character)
    if weaker_hand:
        current = min(
            character.equipped_level(_MAIN_HAND),
            character.equipped_level(_OFF_HAND),
        )
    if current and _shield_over_other(holding, character):
        return (
            True,
            "a tank's off hand holds %s (item level %d), and a shield belongs there"
            % (
                _OFF_HAND_SAID.get(character.off_hand_kind, "something else"),
                current,
            ),
        )
    if current and holding.item_level <= current:
        if weaker_hand:
            return (
                False,
                f"not an upgrade (the weaker hand is item level {current})",
            )
        return False, f"not an upgrade (currently equipped is item level {current})"

    if weaker_hand:
        return True, (
            "empty weaker weapon hand"
            if not current
            else f"item level {holding.item_level} beats the weaker hand's {current}"
        )
    return True, (
        f"empty {slot.replace('_', ' ')} slot"
        if not current
        else f"item level {holding.item_level} beats the equipped {current}"
    )


def _two_hander_decision(
    holding: Holding, character: CharacterState, slot: str
) -> tuple | None:
    """Decide a two-hander that would displace something from the off hand."""
    if slot != _TWO_HAND or not character.has_off_hand():
        return None
    if not prefers_two_hander(character):
        return False, "would displace an equipped off-hand item"
    current = max(
        character.equipped_level(_TWO_HAND), character.equipped_level(_MAIN_HAND)
    )
    if current and holding.item_level <= current:
        return False, (
            f"not an upgrade (the main hand worn now is item level {current})"
        )
    return True, (
        f"item level {holding.item_level} two-hander beats the "
        f"{current} main hand, and a damage role has no use for the shield"
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
        return (
            False,
            "not gear (quest items, reagents and consumables are never considered)",
        )
    if holding.soulbound:
        return False, "soulbound to the current holder"
    return would_wear(holding, character)


def worn_against(holding: Holding, character: CharacterState) -> int:
    """The item level this piece would replace on this character.

    A two-hander replaces whichever weapon is in the hands, so it is measured
    against the better of the two-hand and main-hand buckets; everything else
    against its own bucket.
    """
    slot = _slot_for(holding)
    worn = character.equipped_level(slot)
    if _rogue_can_dual_wield_one_hander(holding, character):
        worn = min(
            character.equipped_level(_MAIN_HAND),
            character.equipped_level(_OFF_HAND),
        )
    if slot == _TWO_HAND:
        worn = max(worn, character.equipped_level(_MAIN_HAND))
    if _shield_over_other(holding, character):
        # An orb or a blade in a shield tank's off hand is worth nothing to
        # him, so all of the shield is a gain.
        worn = 0
    return int(worn)


def upgrade_gain(holding: Holding, character: CharacterState) -> tuple:
    """(gain, reason): how many item levels a hand-off would add, 0 for none.

    THE SAME OPINION AS `is_upgrade_for`, WITH THE HANDS SETTLED (#174).
    `is_upgrade_for` compares within one slot bucket, which reads the two-hand
    bucket as empty for anybody holding a one-hander; `_hand_refusal` is the
    rule `equips` already applies for exactly that, so a hand-off is refused
    on the same grounds a holder's own equip would be. A piece this returns a
    gain for is one its receiver's own equip pass would put on.
    """
    upgrade, reason = is_upgrade_for(holding, character)
    if not upgrade:
        return 0, reason
    refusal = _hand_refusal(holding, character)
    if refusal:
        return 0, refusal
    gain = int(holding.item_level) - worn_against(holding, character)
    if gain <= 0:
        return 0, "not an upgrade"
    return gain, reason


# ---------------------------------------------------------------------------
# THE WEAKEST SLOT (#174)
#
# Measured on the dev family 2026-09-22: the level 60 Protection warrior wore
# an item level 30 dagger in the main hand with a shield, while every other
# worn piece he had was 42 to 56. Nothing asked which slot was furthest behind,
# so nothing looked for a weapon. This is that question, over the same slot
# buckets every other judgement here uses.
#
# THE WEAPON COUNTS DOUBLE. Every melee swing, a tank's threat and a caster's
# spell power off a staff all start from the weapon, and the armour slots
# share the rest of the character's stats roughly evenly. Without the weight a
# level 29 cloak and a level 30 dagger read as the same problem, and they are
# not. A hunter's weapon is the ranged one, so for a hunter the weights swap.
#
# Rings, necks and trinkets are not judged: `_SLOT_BY_INVTYPE` has no bucket
# for them, and that refusal is kept here rather than guessed around.

_ARMOUR_BUCKETS = (
    _HEAD,
    _SHOULDER,
    _CHEST,
    _WAIST,
    _LEGS,
    _FEET,
    _WRIST,
    _HANDS,
    _BACK,
)
_HUNTER = 3
WEAPON_WEIGHT = 2


@dataclass(frozen=True)
class Weakest:
    """One character's weakest judged slot, and how far behind their level."""

    name: str
    slot: str  # a bucket; "weapon" for the main/two hand pair
    item_level: int
    level: int
    shortfall: int  # weighted item levels below the character level

    @property
    def label(self) -> str:
        return "main hand" if self.slot == "weapon" else self.slot.replace("_", " ")

    @property
    def said(self) -> str:
        return "%s, item level %d at level %d" % (
            self.label,
            self.item_level,
            self.level,
        )


def bucket_of(holding: Holding) -> str:
    """The weakest-slot bucket a piece would fill: "weapon" for either hand."""
    slot = _slot_for(holding)
    return "weapon" if slot in (_MAIN_HAND, _TWO_HAND) else slot


def weakest_slot(character: CharacterState):
    """The judged slot furthest below this character's level, or None.

    Armour buckets always count, and an empty one counts as item level 0 -
    a missing helmet is a real gap. The off hand and the ranged slot count
    only when something is worn there, because a two-hander leaves the off
    hand empty on purpose and most classes carry a ranged piece as a stat
    stick. None when every judged slot is at or above the character's level.
    """
    level = int(character.level)
    hunter = int(character.class_id) == _HUNTER
    weapon = max(
        character.equipped_level(_MAIN_HAND), character.equipped_level(_TWO_HAND)
    )
    judged = [(b, character.equipped_level(b), 1) for b in _ARMOUR_BUCKETS]
    judged.append(("weapon", weapon, 1 if hunter else WEAPON_WEIGHT))
    if character.equipped_level(_OFF_HAND):
        judged.append((_OFF_HAND, character.equipped_level(_OFF_HAND), 1))
    if hunter or character.equipped_level(_RANGED):
        judged.append(
            (_RANGED, character.equipped_level(_RANGED), WEAPON_WEIGHT if hunter else 1)
        )
    best = None
    for bucket, item_level, weight in judged:
        shortfall = weight * max(0, level - int(item_level))
        if shortfall <= 0:
            continue
        if best is None or shortfall > best.shortfall:
            best = Weakest(
                name=character.name,
                slot=bucket,
                item_level=int(item_level),
                level=level,
                shortfall=shortfall,
            )
    return best


def tank_claim(holding: Holding, characters) -> str:
    """The family's shield tank this shield should go to first, or "".

    THE ONE EXCEPTION TO THE HOLDER'S FIRST CLAIM. A raiding guild gears its
    tank first on a tank's piece, and a shield is the tank's piece: to a
    Retribution paladin carrying one it is a spare (`prefers_two_hander`), to
    the tank it is the off hand. So a tradable shield that is an upgrade for a
    shield tank who is not its holder goes to that tank, even when the holder
    could wear it too. The best gain wins between two tanks, then the name.

    Soulbound is refused by `is_upgrade_for`, so a shield bound to its holder
    never moves: the natural rules have no way to hand it over.
    """
    if not is_shield(holding) or holding.soulbound:
        return ""
    holder = next((c for c in characters if c.name == holding.holder), None)
    if holder is not None and shield_tank(holder) and would_wear(holding, holder)[0]:
        # A tank holding a shield he would wear keeps it: tank to tank is
        # the ordinary holder-first rule.
        return ""
    best = None
    for character in characters:
        if character.name == holding.holder or not shield_tank(character):
            continue
        if not is_upgrade_for(holding, character)[0]:
            continue
        gain = int(holding.item_level) - worn_against(holding, character)
        if gain <= 0:
            continue
        key = (-gain, character.name)
        if best is None or key < best:
            best = key
    return best[1] if best else ""


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

    THE RUNNERS-UP ARE CARRIED RATHER THAN DISCARDED (infra#4198). One taker
    per item is still the answer this function gives; what changed is that
    "whoever benefits most" is no longer allowed to double as "and if that one
    cannot take it, nobody does". Measured on wow-dev 2026-09-19: Arachnidian
    Pauldrons sat in Og's bags, four siblings could wear them, this function
    picked Ugga (gain 12) and `deliverable` dropped the item because Ugga was
    at 0 free slots of 62 - while Grog (gain 10, 6 free), Grug (gain 10, 12
    free) and Bork (gain 1, 11 free) were never asked. One grant proposed, one
    grant withheld, nothing moved. The ranking is still this function's and
    still space-blind; `deliverable` walks it in order and takes the first
    taker the world will actually accept.
    """
    by_name = {c.name: c for c in characters}
    grants = []
    notes = []
    for holding in sorted(holdings, key=lambda h: (h.holder, h.guid)):
        holder_state = by_name.get(holding.holder)
        tank = tank_claim(holding, characters)
        if tank:
            # THE TANK'S SHIELD, ahead of the holder (see `tank_claim`).
            _, reason = is_upgrade_for(holding, by_name[tank])
            grant = _grant_for(holding, by_name[tank], reason)
            grants.append(
                replace(
                    grant,
                    reason=f"{holding.holder} is holding {holding.name} (item level "
                    f"{holding.item_level}), and {tank} tanks for the family: {reason}.",
                )
            )
            continue
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
            gain = holding.item_level - worn_against(holding, character)
            candidates.append((gain, character.name, reason))

        if not candidates:
            notes.append(
                f"{holding.holder} holds {holding.name} (item level "
                f"{holding.item_level}) and nobody else in the family can use it"
            )
            continue

        candidates.sort(key=lambda c: (-c[0], c[1]))
        ranked = [
            _grant_for(holding, by_name[name], reason) for _, name, reason in candidates
        ]
        grants.append(replace(ranked[0], alternates=tuple(ranked[1:])))
    return Plan(grants=tuple(grants), notes=tuple(notes))


def _grant_for(holding: Holding, taker: CharacterState, reason: str) -> Grant:
    """One item and one named taker, as the sentence an operator will read.

    Lifted out of `plan` so that the runners-up are spelled exactly like the
    front-runner: `deliverable` may promote any of them, and a promoted grant
    whose `reason` still named somebody else would be a log line that lies
    about what just happened.
    """
    return Grant(
        holder=holding.holder,
        taker=taker.name,
        entry=holding.entry,
        name=holding.name,
        guid=holding.guid,
        reason=(
            f"{holding.holder} is holding {holding.name} (item level "
            f"{holding.item_level}) with no use for it, and {taker.name} "
            f"can: {reason}."
        ),
        said=f"{holding.holder} trade {taker.name} {holding.name}.",
    )


def lines(gear_plan: Plan) -> list:
    """The family saying it, "Name: words" - the shape professions.lines and
    materials.lines already speak in, so a hand-off is a line in party chat
    and never a silent database write."""
    return [f"{g.holder}: {g.said}" for g in gear_plan.grants]


# ---------------------------------------------------------------------------
# WHETHER THE ANSWER CAN ACTUALLY LAND, WHICH IS A DIFFERENT QUESTION
#
# Everything above decides WHO should end up wearing a piece. None of it can
# see the world, and for a fortnight nothing else looked either: the pass
# wrote a kind='trade' row for every grant and hoped.
#
# MEASURED ON THE LIVE REALM, 2026-09-11. 755 trade rows, aimed at exactly the
# right people. 41 delivered. The other 714: 343 `characters are too far apart
# to trade`, 169 `target not online`, 146 `receiver bags are full`, 29
# `receiver not online`, 15 `one of the characters is on a flight path`, 10
# `giver is dead`. Five per cent. Over the same hours the reagent pass's
# kind='give' rows delivered 107 of 182, and the ONLY thing give ever failed
# on was a full receiver.
#
# WHY THE TWO VERBS DIFFER THAT MUCH. DoGive (mod_overseer.cpp) tests three
# things: the receiver is online, the item is not soulbound, the bags have
# room. DoTrade tests all three AND that both are alive, neither is in
# flight, neither is stunned, neither is logging out, neither is already
# trading, and that they are within TRADE_DISTANCE - the check its own
# comment calls "normally false for a travelling group rather than rarely
# false". Measured the same night, the five were 157 to 744 yards apart.
#
# SO THE VERB IS CHOSEN FROM AN OBSERVED FACT AND NOT FROM A PREFERENCE. The
# aesthetic argument for trade is real and it survives intact: an exchange
# between two characters standing together renders and animates, and that is
# worth having on a stream. An exchange between two characters 744 yards
# apart renders NOTHING - it was only ever going to become an error row - so
# nothing is given up by moving that one to give. Trade when it can be
# watched, give when it cannot.
#
# SUPERSEDED BY THE MODULE ITSELF (#189). mod-overseer#566 made DoGive refuse
# exactly that far case: a give now needs the two on one map and inside
# TRADE_DISTANCE, like a trade. So apart is a wait (the family walks together
# and trades on a later pass), or a letter when the holder already stands at
# a mailbox. `deliverable` never answers GIVE.
#
# WHY NO TRAVEL ERRAND IS WRITTEN TO CLOSE THE DISTANCE INSTEAD. Because the
# family already has one writer for travel aims and adding a second is the
# bug this repo most recently fixed (#3554, "aim only the leader at the
# vendor, not all five holders"). A hand-off that waits for the party to
# converge on its own is free; a hand-off that steers people is a second
# hand on the wheel.


@dataclass(frozen=True)
class Spot:
    """Where one character is standing, including the copy of the map."""

    map_id: int
    x: float
    y: float
    instance_id: int | None = 0


def _within_trade_range(here: Spot, there: Spot) -> bool:
    """Close enough for the core to open a trade window.

    MAP AND INSTANCE ARE CHECKED BEFORE THE DISTANCE. A map id names an
    instance template, so two characters at the same coordinates in separate
    copies of one dungeon are not together. Unknown instance ids fail closed.
    """
    if (
        here.instance_id is None
        or there.instance_id is None
        or int(here.map_id) != int(there.map_id)
        or int(here.instance_id) != int(there.instance_id)
    ):
        return False
    # STRICTLY inside: the core's own compare is strict (mod-overseer's
    # test_give_range.cpp pins exactly-at-11.11 as refused), so planning a
    # hand-over at exactly TRADE_YARDS would only ever become an error row.
    return math.hypot(here.x - there.x, here.y - there.y) < TRADE_YARDS


def spots_from_rows(rows) -> dict:
    """name -> Spot, from fresh snapshot rows, dropping what it cannot read.

    A NAME MISSING FROM THE RESULT IS NOT IN THE WORLD. The caller filters
    `overseer_snapshot` on `updated_at`, so a character who logged out simply
    has no fresh row - which makes one read answer both "where are they" and
    "are they there at all", the two facts that account for 541 of the 714
    refusals.
    """
    spots = {}
    for name, row in dict(rows or {}).items():
        try:
            instance = row.get("instance_id", 0)
            spots[str(name)] = Spot(
                map_id=int(row["map_id"]),
                x=float(row["pos_x"]),
                y=float(row["pos_y"]),
                instance_id=None if instance is None else int(instance),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return spots


def deliverable(grants, position_rows=None, free_slots=None, at_mailbox=None) -> Plan:
    """The hand-offs that can land right now, each carrying the verb to use.

    EXACTLY ONE NOTE PER WITHHELD GRANT, so a caller can report "decided N,
    queued M, held back K" without being handed a second count to trust.

    `position_rows=None` and `free_slots=None` both mean NOBODY ASKED, and
    the result is what this pass did before either gate existed - the same
    default, for the same reason, that `bag_pressure.gear_candidates` gives
    `fits=None`. bridge.py always asks. A caller that asks and gets back a
    mapping which does not mention somebody has asked and been told that
    character is not there, which is a different fact and blocks the row.

    ROOM IS BUDGETED ACROSS THE PASS RATHER THAN CHECKED PER GRANT. Og was
    measured at 62 of 62 slots used while eight pieces were waiting for him;
    checking "has room" eight times against one free slot writes seven rows
    that were doomed when they were written. Unknown capacity counts as no
    room, the direction `materials.retryable_stuck` already takes.

    A FULL TAKER NOW COSTS THAT TAKER THE ITEM AND NOT THE ITEM ITS MOVE
    (infra#4198). The room test itself was right and is unchanged: one free
    slot on the RECEIVER, never "more room than the giver", never a comparison
    between the two. What was wrong is what a failed test did - it withheld the
    piece entirely, because `plan` had already thrown away every other sibling
    who could wear it. `grant.alternates` is that ranking, so this walks it and
    takes the first taker who is both in the world and has a slot. The gain
    ordering still decides BETWEEN takers; it no longer decides WHETHER.

    STILL EXACTLY ONE NOTE PER WITHHELD ITEM. An item is withheld only when
    every ranked taker was refused, and the note names them all with the wall
    each one hit, so "nobody had room" and "nobody was online" stay tellable
    apart at a glance.

    APART IS NO LONGER A GIVE (#189). mod-overseer#566 made DoGive refuse
    outside trade range, so a taker who is seen but not beside the holder is
    either posted to, when `at_mailbox` names the holder as standing at a
    mailbox now, or waits with a note: a family walks together and the trade
    happens on a later pass. `at_mailbox=None` means nobody offered the post.
    """
    asked_where = position_rows is not None
    asked_room = free_slots is not None
    spots = spots_from_rows(position_rows)
    room = {str(k): int(v or 0) for k, v in dict(free_slots or {}).items()}
    posting = {str(n) for n in (at_mailbox or ())}

    out, notes = [], []
    for grant in grants:
        here = spots.get(grant.holder)
        if asked_where and here is None:
            # The GIVER is one fact about the item, not about a taker, so it
            # refuses the whole ranking at once rather than once per name.
            notes.append(
                f"{grant.name} stays with {grant.holder}: {grant.holder} "
                f"is not in the world right now"
            )
            continue
        chosen, verb = None, TRADE
        walls = {"absent": [], "crowded": [], "apart": []}
        facts = (here, spots, room, posting, asked_where, asked_room)
        for option in (grant,) + tuple(grant.alternates):
            verb, wall = _delivery_wall(option, *facts)
            if wall:
                walls[wall].append(option.taker)
                continue
            chosen = option
            break
        if chosen is None:
            notes.append(
                _withheld(grant, walls["crowded"], walls["absent"], walls["apart"])
            )
            continue
        if asked_room:
            room[chosen.taker] -= 1
        out.append(replace(chosen, verb=verb, alternates=()))
    return Plan(grants=tuple(out), notes=tuple(notes))


def _joined(names: list) -> str:
    """ "Ugga", "Ugga and Grog", "Ugga, Grog and Grug"."""
    if len(names) <= 1:
        return "".join(names)
    return "%s and %s" % (", ".join(names[:-1]), names[-1])


def _delivery_wall(option, here, spots, room, posting, asked_where, asked_room):
    """(verb, "") when this taker can have the item now, else ("", wall).

    The wall is "absent" (not in the world), "crowded" (no free slot) or
    "apart" (outside trade range with the holder at no mailbox, #189).
    """
    there = spots.get(option.taker)
    if asked_where and there is None:
        return "", "absent"
    if asked_room and room.get(option.taker, 0) <= 0:
        return "", "crowded"
    if not asked_where or _within_trade_range(here, there):
        return TRADE, ""
    if option.holder in posting:
        return MAIL, ""
    return "", "apart"


def _withheld(grant: Grant, crowded: list, absent: list, apart=()) -> str:
    """The one note for an item every ranked taker refused.

    Both walls are named when both were hit. A note that said only "no free
    bag slot" for a ranking where two takers were offline and one was full
    would send the next reader looking at bags for a presence problem.
    """
    walls = []
    if crowded:
        walls.append(
            "%s %s no free bag slot to receive it (no slot-freeing step is "
            "available and no direct equip path is available)"
            % (_joined(crowded), "have" if len(crowded) > 1 else "has")
        )
    if absent:
        walls.append(
            "%s %s not in the world right now"
            % (_joined(absent), "are" if len(absent) > 1 else "is")
        )
    if apart:
        walls.append(
            "%s is beside none of %s, so it waits until they stand together"
            % (grant.holder, _joined(list(apart)))
        )
    return "%s stays with %s: %s" % (grant.name, grant.holder, ", and ".join(walls))


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
    tank = tank_claim(holding, characters)
    if tank:
        return tank
    if would_wear(holding, holder)[0]:
        return holder.name
    for character in sorted(characters, key=lambda c: c.name):
        if character.name == holding.holder:
            continue
        if is_upgrade_for(holding, character)[0]:
            return character.name
    if _holder_would_train_for(holding, holder):
        return holder.name
    return NOBODY


def _holder_would_train_for(holding: Holding, holder: CharacterState) -> bool:
    """Would the holder wear this weapon once a weapon master taught the skill.

    A sibling who can wield it now was asked first and wins it. When none
    can, the holder keeps it rather than see it sold: the weapon-master walk
    (weaponskill, #399) trains the holder for a weapon they CARRY, so selling
    it would take away the reason to walk (#393). `equips` still refuses to
    put it on until the skill is learned.
    """
    if holder.weapon_skills is None or weapon_trained(holding, holder):
        return False
    if int(holding.item_subclass) not in weaponskill.WEAPON_SKILLS:
        return False
    return would_wear(holding, replace(holder, weapon_skills=None))[0]


def claims(holdings, characters) -> dict:
    """`claimant` over many holdings, keyed by item guid for the sell path."""
    return {int(h.guid): claimant(h, characters) for h in holdings}


# ---------------------------------------------------------------------------
# PUTTING ON WHAT THE HOLDER WOULD WEAR (#146)
#
# `claimant` has answered "the holder" about a carried piece since infra#3449,
# and that answer KEEPS the piece: it is never sold and never handed on. But
# nothing ever put it on. Measured on wow-dev 2026-09-22, 15 of 24 carried
# gear pieces across the family came back FIT_HOLDER - Grog carrying Cabalist
# Chestpiece (item level 50) over a worn 41, Bork Dervish Boots (28) over 23,
# Ugga Watcher's Handwraps (28) over 22 - riding in the bags and costing a
# slot each.
#
# THE SAME OPINION, ASKED ONCE MORE. A piece is equipped only when `claimant`
# names its own holder, which is `would_wear` on the holder: class, armour
# training, level, a known slot, the off-hand guard and a strict item level
# gain. Nothing new decides whether it is an upgrade.
#
# WHAT IS LEFT ALONE, ON PURPOSE. UNJUDGEABLE stays in the bag: rings, necks,
# trinkets and idols have no slot in `_SLOT_BY_INVTYPE`, and "cannot be
# settled from the numbers" is not a licence to guess. On top of that, the
# weapon hands are a place where one item level comparison per bucket is not
# the whole story, so three shapes are refused rather than judged:
#
#   * a one-hander or an off-hand piece while a two-hander is worn - putting
#     it on takes the two-hander off, and the bucket comparison cannot see it;
#   * a two-hander that does not beat the worn main hand - the two-hand
#     bucket reads empty for anyone holding a one-hander, which would make any
#     two-hander look like a free upgrade;
#   * an off-hand piece in a plan that also puts on a two-hander.
#
# ONE PIECE PER SLOT PER HOLDER, the best one. Two carried chests are one
# equip, and the loser stays for the ordinary disposition next cycle.

# The weapon buckets that share a character's hands. Main hand and two hand
# are one choice, because wearing either replaces the other.
_WEAPON_GROUP = {_MAIN_HAND: "weapon", _TWO_HAND: "weapon"}


@dataclass(frozen=True)
class Equip:
    """One carried piece its own holder should be wearing, and why."""

    holder: str
    guid: int
    entry: int
    name: str
    slot: str
    item_level: int
    worn_level: int
    reason: str

    @property
    def command(self) -> str:
        """The mod-playerbots chat command that puts it on (kind='bot').

        `e` is EquipAction, which reads item ids out of `Hitem:<id>:` through
        ChatHelper::parseItems and equips the first carried copy it finds.
        mod-overseer hands a kind='bot' row to PlayerbotAI::HandleCommand as
        a whisper from the character itself, the same road `nc +new rpg`
        takes. The entry and not the guid, because that is all the verb
        reads; two carried copies of one entry are the same piece to wear.
        """
        return "e Hitem:%d:0" % int(self.entry)


def equip_entry(command) -> int:
    """The item entry an `Equip.command` names, or 0 for anything else."""
    text = str(command or "")
    marker = "Hitem:"
    at = text.find(marker)
    if at < 0:
        return 0
    digits = text[at + len(marker) :].split(":", 1)[0]
    return int(digits) if digits.isdigit() else 0


def _hand_refusal(holding: Holding, character: CharacterState) -> str:
    """Why this weapon-hand piece is not a clear upgrade, or "" if it is."""
    slot = _slot_for(holding)
    if slot in (_MAIN_HAND, _OFF_HAND) and character.equipped_level(_TWO_HAND):
        return "would take off the two-hander worn now"
    if slot == _TWO_HAND and holding.item_level <= character.equipped_level(_MAIN_HAND):
        return (
            "does not beat the main hand worn now (item level %d)"
            % character.equipped_level(_MAIN_HAND)
        )
    return ""


def bot_wont_wear(holding: Holding, character: CharacterState) -> bool:
    """The member's bot will not put this piece on, whatever the item levels
    say (#830): a hunter and a melee weapon. Asked only where an `e` row is
    built, so who may hold or receive the piece is unchanged."""
    return weaponskill.bot_wont_wear(
        character.class_id, holding.item_class, holding.inventory_type
    )


def equips(holdings, characters) -> tuple:
    """Every carried piece its holder should put on now, best per slot.

    Deterministic: holders by name, then one pick per slot (highest item
    level, then lowest guid), so an unchanged bag proposes the same rows and
    the caller's dedupe sees the same key.
    """
    by_name = {c.name: c for c in characters}
    best: dict = {}
    for holding in holdings:
        character = by_name.get(holding.holder)
        if character is None:
            continue
        if claimant(holding, characters) != holding.holder:
            continue
        if not weapon_trained(holding, character):
            # Kept for the weapon-master walk, not worn: the core refuses
            # a weapon whose skill is not learned (#393).
            continue
        if _hand_refusal(holding, character) or bot_wont_wear(holding, character):
            continue
        slot = _slot_for(holding)
        group = _WEAPON_GROUP.get(slot, slot)
        key = (holding.holder, group)
        worn = worn_against(holding, character)
        pick = Equip(
            holder=holding.holder,
            guid=int(holding.guid),
            entry=int(holding.entry),
            name=holding.name,
            slot=slot,
            item_level=int(holding.item_level),
            worn_level=int(worn),
            reason=would_wear(holding, character)[1],
        )
        held = best.get(key)
        if held is None or (pick.item_level, -pick.guid) > (
            held.item_level,
            -held.guid,
        ):
            best[key] = pick
    two_handed = {e.holder for e in best.values() if e.slot == _TWO_HAND}
    out = [
        e for e in best.values() if not (e.slot == _OFF_HAND and e.holder in two_handed)
    ]
    return tuple(sorted(out, key=lambda e: (e.holder, e.slot, e.guid)))


def chosen_equip(holding: Holding, character: CharacterState, reason: str):
    """An Equip for a piece a second judge chose for its own holder, or None.

    The same row `equips` writes, for a piece `equips` would not pick: Jev in
    act mode (#95), on the weapon swaps item level cannot settle. The caller
    has already asked whether the holder can wear it at all; this only builds
    the row, and refuses a piece that is not its holder's or has no slot.
    """
    slot = _slot_for(holding)
    if not slot or character.name != holding.holder:
        return None
    if bot_wont_wear(holding, character):
        return None
    worn = worn_against(holding, character)
    return Equip(
        holder=holding.holder,
        guid=int(holding.guid),
        entry=int(holding.entry),
        name=holding.name,
        slot=slot,
        item_level=int(holding.item_level),
        worn_level=int(worn),
        reason=str(reason),
    )


def merge_equips(wanted, withheld, chosen) -> tuple:
    """`wanted` without the `withheld` guids, with each `chosen` Equip in.

    A chosen piece displaces whatever `wanted` held for the same holder and
    slot group, and a chosen two-hander displaces an off-hand piece too, the
    rule `equips` keeps for its own picks. One row per slot, as before.
    """
    held = {int(g) for g in withheld or ()}
    out = [e for e in wanted if int(e.guid) not in held]
    for pick in chosen or ():
        group = _WEAPON_GROUP.get(pick.slot, pick.slot)
        out = [
            e
            for e in out
            if not (
                e.holder == pick.holder
                and (
                    _WEAPON_GROUP.get(e.slot, e.slot) == group
                    or (pick.slot == _TWO_HAND and e.slot == _OFF_HAND)
                )
            )
        ]
        out.append(pick)
    return tuple(sorted(out, key=lambda e: (e.holder, e.slot, e.guid)))


def since_level_change(history, changed) -> list:
    """The equip attempts made at each character's CURRENT level.

    A LEVEL CHANGE RE-OPENS EVERY SLOT. Repeated world refusals hold a piece
    back for staged retry windows; a level is the commonest reason and a
    level change retires it. The natural lowering of 2026-09-26 changed every
    family member's level at once, and every slot's question with it, so the
    attempts before the change say nothing about the answer after it.

    `history` rows carry target_name and created_at; `changed` maps a name to
    the time of its last level change. A row without a time, or a character
    with no recorded change, is kept.
    """
    out = []
    for row in history or ():
        at = row.get("created_at")
        since = (changed or {}).get(str(row.get("target_name", "")))
        if at is not None and since is not None and at < since:
            continue
        out.append(row)
    return out


# WHAT THE WORLD SAYS WHEN IT WILL NOT PUT A PIECE ON. mod-overseer writes
# `error` or `unchanged` with a `detail` saying why. `delivered` says only
# that the command was handed over; `applied` says the world put the item on.
WORLD_REFUSALS = frozenset({"error", "unchanged"})

# EVERY ANSWER IS READ BY WHAT THE MEMBER CAN DO ABOUT IT (#1088). mod-overseer
# writes Player::CanEquipItem's answer as "<name or InventoryResult> <code>"
# (Item.h InventoryResult), "not carried" when the piece is not in the bags,
# and "the bot did not put the item on" when the core would take it and the
# bot did not. The staged wait this replaces, (15, 30, memory window) by try,
# parked every third refusal for 24 hours whatever it said: Cronk 10.8 hours
# on 21, Bonk 10.3 on 38/21/39, Ezzo 8.6 on 21, Durg 8 on 60, on 2026-10-18.
#
# So the answer, not the try count, decides, and no answer holds a member for
# longer than ROOM_WAIT_MINUTES. An answer the member cannot clear in that
# time SETTLES the upgrade instead (EquipDropped): it is not asked again, a
# plain reason says why, it is never a hold or a stuck reason, and it is
# reopened only by the change that can clear it (the holder's level or
# skills, what it wears there, or its bags), never by a timer:
#
#   PASSING  a state of the holder that passes by itself (#869): stunned (37),
#            dead (38), casting or the swap timer (39), in combat (60),
#            disarmed (61), in an arena (78), the item locked (36) or the
#            holder busy (58). Asked again after REFUSAL_WAIT_MINUTES.
#   ROOM     the bags are too full for what the equip moves: items cannot be
#            swapped (21, the two-hander over a shield), bag or inventory full
#            (4, 50, 53 and 56, BAG_FULL3 and BAG_FULL4, and 62, BAG_FULL6).
#            The member makes the room (equip_room, the guild pass's
#            make-room step) and the piece is asked the pass a slot frees.
#            With none freed in ROOM_WAIT_MINUTES it is settled until the
#            bags have the room.
#   GONE     the piece is not carried or not found (23, 32, 54, "not
#            carried"): never held. Settled until the bags change; the next
#            bag read drops a piece that has left them.
#   FINAL    nothing the member does now clears it: level, skill,
#            proficiency, the slot, a class that can never use it, a
#            two-hander or dual wield in the way, rank, reputation,
#            unique-equipped, arena rating. Settled at once.
#   RETRY    anything else, the bot's own read-back among it: asked once more
#            after REFUSAL_WAIT_MINUTES, then settled.
REFUSAL_PASSING = "passing"
REFUSAL_ROOM = "room"
REFUSAL_GONE = "gone"
REFUSAL_FINAL = "final"
REFUSAL_RETRY = "retry"
# A settled upgrade the world took `give_up` commands for and never put on,
# with no refusal to say why (#869's silent give-up).
SETTLED_SILENT = "silent"
REFUSAL_WAIT_MINUTES = 15
ROOM_WAIT_MINUTES = 30
# The RETRY answers an upgrade gets before it is settled.
RETRY_ANSWERS = 2
_PASSING_REFUSALS = frozenset({36, 37, 38, 39, 58, 60, 61, 78})
_ROOM_REFUSALS = frozenset({4, 21, 50, 53, 56, 62})
_GONE_REFUSALS = frozenset({23, 32, 54})
# code -> why the member cannot wear it, in the reader's words.
_FINAL_REFUSALS = {
    1: "its level is too low",
    2: "it lacks the skill",
    3: "the piece does not go in that slot",
    8: "it lacks the proficiency",
    9: "it has no slot free for it",
    10: "it can never use that item",
    11: "it can never use that item",
    12: "it has no slot free for it",
    13: "a two-hander is worn",
    14: "it cannot dual wield",
    18: "it has no slot free for it",
    20: "the piece cannot be equipped",
    63: "its rank is too low",
    64: "its reputation is too low",
    67: "it is unique-equipped and one is already worn",
    75: "it already wears the most of that socketed gem",
    76: "it is unique-equipped and one is already worn",
    80: "its arena rating is too low",
}
_REFUSAL_CODE = re.compile(r"\b(?:InventoryResult|EQUIP_ERR_[A-Z0-9_]+) (\d+)\b")
_NOT_CARRIED = "not carried"

# What change in the bags reopens a settled upgrade, by how it was settled. A
# room answer reopens when the bags have the room it was short of, a piece the
# world could not find when the bags change at all, an unknown or silent one
# when a slot frees; a FINAL answer is not about the bags.
_REOPEN_ON_RISE = frozenset({REFUSAL_RETRY, SETTLED_SILENT})
_REOPEN_ON_CHANGE = frozenset({REFUSAL_GONE})


def _refusal_code(detail):
    """The InventoryResult a refusal detail names, or None."""
    found = _REFUSAL_CODE.search(str(detail or ""))
    return int(found.group(1)) if found is not None else None


def refusal_kind(detail) -> str:
    """What the member can do about a refusal detail: one REFUSAL_ kind."""
    if str(detail or "").strip().lower() == _NOT_CARRIED:
        return REFUSAL_GONE
    code = _refusal_code(detail)
    if code in _PASSING_REFUSALS:
        return REFUSAL_PASSING
    if code in _ROOM_REFUSALS:
        return REFUSAL_ROOM
    if code in _GONE_REFUSALS:
        return REFUSAL_GONE
    if code in _FINAL_REFUSALS:
        return REFUSAL_FINAL
    return REFUSAL_RETRY


def _drop_words(detail) -> str:
    """Why an upgrade is settled, for its note."""
    words = _FINAL_REFUSALS.get(_refusal_code(detail))
    detail = str(detail or "").strip()
    return "%s (%s)" % (words, detail) if words else detail


# Equip.slot -> the bag 0 equipment slots a piece put on there would displace.
# Both the item-level buckets and equipscore's groups, so a hold can see when
# what is worn there has changed. A slot not here has no worn signature, and
# only a level change or the piece leaving the bags lifts its hold.
_EQUIPMENT_SLOTS = {
    "head": (0,),
    "neck": (1,),
    "shoulder": (2,),
    "chest": (4,),
    "waist": (5,),
    "legs": (6,),
    "feet": (7,),
    "wrist": (8,),
    "hands": (9,),
    "finger": (10, 11),
    "trinket": (12, 13),
    "back": (14,),
    _MAIN_HAND: (15,),
    _TWO_HAND: (15, 16),
    _OFF_HAND: (16,),
    _RANGED: (17,),
}
# A settled hand piece remembers both hands: what the main hand holds decides
# the off hand's answer (13, an off hand while a two-hander is worn, clears
# the pass a one-hander replaces the two-hander).
_HAND_SLOTS = (15, 16)


@dataclass
class WorldHold:
    """A short wait on one answered equip row: a passing state of the holder
    (PASSING) or the first answer nobody named (RETRY).

    `worn` is what sat in the piece's slot when the hold began; `lifted` says
    the hold is over for this row (that slot changed, the piece left the
    bags, or its retry time came), so the same answer never holds the piece a
    second time. The retry comes REFUSAL_WAIT_MINUTES after the refusal, or
    after the pass that first saw it when the row has no time.
    """

    row_id: int
    worn: tuple
    lifted: bool = False
    retry_at: object = None
    refusal_at: object = None
    kind: str = REFUSAL_PASSING
    seen: object = None


@dataclass
class RoomWait:
    """An upgrade waiting on room in its holder's bags (#1088).

    The world refused it for room (`row_id` names that answer and `need` is
    one slot more than the holder had then), or room_needed says it is short
    before it is asked (`row_id` is the newest answer then, 0 for none).
    `free_at` is the free slots when the wait began or last gained one and
    `since` when that was. The make-room step works on it, the piece is asked
    the pass the room is there, and with no slot freed in ROOM_WAIT_MINUTES
    it is settled (EquipDropped) until the bags have the room.
    """

    row_id: int
    worn: tuple
    wanted: str
    need: int
    free_at: object
    since: datetime
    lifted: bool = False
    at: object = None


@dataclass
class EquipDropped:
    """An upgrade settled with a plain reason: never a hold and never a stuck
    reason (#1088).

    The piece is not asked again, with `note` saying why, until a change that
    can clear the reason: what is worn where it goes (`worn`, both hands for
    a hand piece), the wanted piece (`wanted`), the holder's level or skills
    (`mark`, WearerFacts.mark, None when unread), or its bags (`free_at`, by
    `kind`: a ROOM settle reopens when `need` slots are free). Never a
    timer: the record outlives its answer row's memory window, and a newer
    answer replaces it. `lifted` says it was reopened, so the same answer
    never settles the piece twice.
    """

    row_id: int
    worn: tuple
    wanted: str
    note: str
    lifted: bool = False
    kind: str = REFUSAL_FINAL
    mark: object = None
    free_at: object = None
    need: int = 0
    since: object = None
    at: object = None


@dataclass
class BotKeep:
    """An equip the bot answered with its own scoring verdict, not a refusal.

    The world answers an equip `unchanged` with a `detail` like "the bot
    keeps Lavishly Jeweled Ring: Viridian Band scores 2.25 against 5.40"
    when its own scorer prefers what is worn. That is the bot's choice, so
    it is never a world hold and never a stuck reason: the piece stays
    unwantable until what is worn in its slot (`worn`) or the wanted piece
    (`wanted`) changes. `note` is the reader-worded line for the member's
    gear notes.
    """

    row_id: int
    worn: tuple
    wanted: str
    note: str
    lifted: bool = False


# WHAT THE PASS KNOWS BEFORE IT ASKS (#1088). The world refuses an equip it
# can never take with a FINAL answer, and every such answer was one command
# written to learn what the tables already say. So the equip pass reads the
# holder's level and skills and the piece's requirements, and an equip whose
# answer is known is never written: its note says why, and it is judged again
# every pass, so it is asked the pass the holder can wear it.
_DUAL_WIELD_SKILL = 118
_UNIQUE_EQUIPPABLE = 0x80000
# InventoryType: a one-hand weapon and an off-hand weapon need Dual Wield in
# the off hand; a shield or a held-in-off-hand piece does not.
_DUAL_WIELD_TYPES = frozenset({13, 22})


@dataclass(frozen=True)
class WearerFacts:
    """A holder's level and skills ((skill id, value), ...)."""

    level: int
    skills: tuple = ()

    def skill(self, skill_id) -> int:
        return next((v for s, v in self.skills if s == int(skill_id)), 0)

    @property
    def mark(self) -> tuple:
        """What a settled upgrade remembers of its holder: a change in its
        level or in the skills it holds reopens it."""
        return int(self.level), frozenset(s for s, v in self.skills if v > 0)


@dataclass(frozen=True)
class ItemFacts:
    """The item_template requirements an equip is judged against."""

    required_level: int = 0
    required_skill: int = 0
    required_skill_rank: int = 0
    required_reputation: int = 0
    required_spell: int = 0
    max_count: int = 0
    flags: int = 0
    inventory_type: int = 0


def _whole(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def wearers_from_rows(rows) -> dict:
    """name -> WearerFacts from rows naming `name`, `level` and `skills`
    ("<skill id>:<value>,..."). A row this cannot read is dropped."""
    out = {}
    for row in rows or ():
        try:
            name, level = str(row["name"]), int(row["level"] or 0)
        except (KeyError, TypeError, ValueError):
            continue
        skills = []
        for part in str(row.get("skills") or "").split(","):
            skill, sep, value = part.strip().partition(":")
            if sep and skill.isdigit() and value.lstrip("-").isdigit():
                skills.append((int(skill), int(value)))
        out[name] = WearerFacts(level, tuple(sorted(skills)))
    return out


def items_from_rows(rows) -> dict:
    """entry -> ItemFacts from rows naming `entry` and the ItemFacts fields."""
    out = {}
    for row in rows or ():
        entry = _whole(row.get("entry"))
        if entry:
            out[entry] = ItemFacts(
                **{f: _whole(row.get(f)) for f in ItemFacts.__dataclass_fields__}
            )
    return out


def wear_refusal(equip, item, wearer, worn) -> str:
    """Why the world would refuse `equip` for a reason its holder cannot clear
    now, in the reader's words, or "" when nothing says so (or nothing was
    read). The level, a skill rank (RequiredSkill, the core's 2), Dual Wield
    for a weapon in the off hand (14), and a unique-equipped piece one copy of
    which is worn (67). A reputation or a spell is not read here (character
    reputation is kept relative to a race's base, which only the client data
    holds), so such a piece is not asked, the rule equipscore keeps."""
    if item is None or wearer is None:
        return ""
    if item.required_level > wearer.level:
        return "it needs level %d and is %d" % (item.required_level, wearer.level)
    if item.required_skill:
        has, needs = wearer.skill(item.required_skill), max(1, item.required_skill_rank)
        if has < needs:
            return "it needs skill %d at %d and has %d" % (
                item.required_skill,
                needs,
                has,
            )
    if item.required_reputation:
        return "it asks a reputation this pass cannot read"
    if item.required_spell:
        return "it asks a spell this pass cannot read"
    if (
        equip.slot == _OFF_HAND
        and item.inventory_type in _DUAL_WIELD_TYPES
        and not wearer.skill(_DUAL_WIELD_SKILL)
    ):
        return "it cannot dual wield"
    unique = item.max_count == 1 or item.flags & _UNIQUE_EQUIPPABLE
    pieces = (worn or {}).get(equip.holder, {})
    if unique and any(int(e) == int(equip.entry) for e, _n in pieces.values()):
        return "it is unique-equipped and one is already worn"
    return ""


# THE ROOM IN THE BAGS, GENERAL BAGS ONLY (#1088). A piece an equip moves out
# of a hand goes into the backpack or a bag anything goes in (item_template
# class 1, subclass 0). A quiver or an ammo pouch (class 11) takes ammunition
# only, and a soul, herb, enchanting or mining bag (class 1, another subclass)
# only its own kind, so their free slots are no room for a shield, nor for
# loot, a purchase or a letter: counted as room they had the world refuse 21
# once per miscount.
_GENERAL_BAG = (1, 0)


def general_bag_room(rows) -> dict:
    """name -> (free bag slots, all bag slots) over the backpack and the
    general bags worn.

    `rows` name `name`, `bag_slot` (0 for the backpack, 19 to 22 for a worn
    bag), `size`, `bag_class`, `bag_subclass` and `used` (the items in it).
    A bag of any other kind, or one whose template is unread, adds nothing.
    """
    out: dict = {}
    for row in rows or ():
        try:
            name, slot = str(row["name"]), int(row["bag_slot"])
        except (KeyError, TypeError, ValueError):
            continue
        free, total = out.get(name, (0, 0))
        kind = (_whole(row.get("bag_class")), _whole(row.get("bag_subclass")))
        if slot == 0 or (row.get("bag_class") is not None and kind == _GENERAL_BAG):
            size = _whole(row.get("size"))
            free, total = free + max(0, size - _whole(row.get("used"))), total + size
        out[name] = (free, total)
    return out


def _bot_keep(row):
    """(kept, challenger, challenger_score, kept_score) for a bot-keeps answer.

    The detail shape is "the bot keeps <kept>: <challenger> scores <a>
    against <b>", where <a> is the challenger's score and <b> the kept
    piece's. Scores are returned as written, for the reader-worded note.
    Anything else - a real refusal, a bare `unchanged`, another status -
    is not a keep, and a row this cannot read returns None.
    """
    try:
        status = str(row.get("status", ""))
        detail = str(row.get("detail", "")).strip()
    except (AttributeError, TypeError):
        return None
    if status != "unchanged" or not detail.lower().startswith("the bot keeps "):
        return None
    kept, colon, rest = detail[len("the bot keeps ") :].partition(":")
    challenger, sep, scores = rest.strip().partition(" scores ")
    challenger_score, against, kept_score = scores.partition(" against ")
    try:
        float(challenger_score)
        float(kept_score)
    except ValueError:
        return None
    if not colon or not sep or not against:
        return None
    kept, challenger = kept.strip(), challenger.strip()
    if not kept or not challenger:
        return None
    return kept, challenger, challenger_score.strip(), kept_score.strip()


def member_gear_notes(holds) -> dict:
    """holder -> the reader-worded lines for their gear notes: the bot's own
    kept choices and the upgrades settled with a reason.

    A member whose bot keeps its own better-scored piece is choosing, not
    stuck, and one whose upgrade is settled is not held either: both read
    here, never on the stuck list. A record this cannot read is dropped.
    """
    out = {}
    for key, rec in (holds or {}).items():
        try:
            holder = str(key[0])
        except (TypeError, IndexError):
            continue
        if isinstance(rec, (BotKeep, EquipDropped)) and not rec.lifted:
            out.setdefault(holder, []).append(rec.note)
    return {holder: tuple(lines) for holder, lines in out.items()}


def latest_answers(history, open_statuses) -> dict:
    """(holder, command) -> the newest row the world has answered.

    `history` is oldest first, as `_equip_history` reads it; a row whose
    status is still in `open_statuses` has not been answered yet.
    """
    out = {}
    for row in history or ():
        if str(row.get("status", "")) in open_statuses:
            continue
        out[(str(row.get("target_name", "")), str(row.get("command", "")))] = row
    return out


def worn_pieces(rows) -> dict:
    """holder -> {equipment slot: (entry, name)} from worn rows carrying
    holder, equipment_slot, entry and name. A row this cannot read is dropped."""
    out: dict = {}
    for row in rows or ():
        try:
            holder = str(row["holder"])
            slot = int(row["equipment_slot"])
            entry = int(row["entry"])
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(holder, {})[slot] = (entry, str(row.get("name") or ""))
    return out


def _worn_for(equip, worn) -> tuple:
    """What is worn where `equip` would go: ((slot, entry, name), ...)."""
    pieces = (worn or {}).get(equip.holder, {})
    return tuple(
        (slot,) + tuple(pieces[slot])
        for slot in _EQUIPMENT_SLOTS.get(equip.slot, ())
        if slot in pieces
    )


def _settle_signature(equip, worn) -> tuple:
    """What a settled upgrade remembers was worn: both hands for a hand piece
    (_HAND_SLOTS), else what `_worn_for` names."""
    if equip.slot not in (_MAIN_HAND, _OFF_HAND, _TWO_HAND):
        return _worn_for(equip, worn)
    pieces = (worn or {}).get(equip.holder, {})
    return tuple(
        (slot,) + tuple(pieces[slot]) for slot in _HAND_SLOTS if slot in pieces
    )


def room_needed(equip, worn) -> int:
    """The free bag slots `equip` needs before the world will put it on.

    What a piece displaces goes into the bag slot the piece leaves, so a
    one-for-one swap needs none. That includes a ring or a trinket over two
    worn ones: it goes into one of the two slots and displaces one piece
    (Blingz's Viridian Band was held back on that miscount, #1088).

    A two-hander over a worn off hand is the one equip that needs a slot of
    its own: Player::CanEquipItem stores the off hand before the swap, while
    the two-hander still sits in its bag slot, and with no free slot refuses
    InventoryResult 21, "items cannot be swapped", whatever the main hand
    holds. Three members with full bags were held a day each on it. A
    warrior with Titan's Grip keeps the off hand, but that is a 3.3.5 talent
    no member under level 60 has, so it is not read here.
    """
    pieces = (worn or {}).get(equip.holder, {})
    if equip.slot == _TWO_HAND and _EQUIPMENT_SLOT_OFF_HAND in pieces:
        return 1
    return 0


def _room_short(equip, worn, free_slots) -> int:
    """How many more free bag slots `equip` needs than its holder has: 0 when
    it has room, or when its bags were not read."""
    free = (free_slots or {}).get(equip.holder)
    if free is None:
        return 0
    return max(0, room_needed(equip, worn) - int(free))


def _over(equip, worn) -> str:
    """What `equip` would be put on over, as the notes name it ("" for an
    empty slot)."""
    over = " and ".join(name for _slot, _entry, name in _worn_for(equip, worn))
    return " over %s" % over if over else ""


def _minutes(since, now) -> int:
    if not isinstance(since, datetime):
        return 0
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return max(0, int((now - since).total_seconds() // 60))


def equip_room(wanted, worn, free_slots, holds=None, now=None) -> dict:
    """holder -> (free slots needed, "to put on <piece> over <worn>", minutes
    its bags have stood at this count) for each holder in `wanted` too full
    to put a piece on.

    With `holds`, as equips_to_queue left them: short by a RoomWait (the
    world refused the piece for room, or room_needed said so first) or by an
    upgrade settled for room whose bags still lack it; a piece settled for
    another reason, or one its holder cannot wear, asks no room. Without, by
    room_needed against the free slots read. A settled
    upgrade stays named on purpose: a member busy elsewhere while its wait ran
    still makes the room when it is free, up to
    guildjobs.ROOM_STEPS_PER_STATE steps for one count of free slots. The
    guild jobs pass makes the room (guildjobs.equip_room_step); the equip is
    asked again the pass the room is there. A holder short for two pieces is
    named for the one that needs the most.
    """
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    for equip in sorted(wanted, key=lambda e: (e.holder, e.slot, e.guid)):
        free = (free_slots or {}).get(equip.holder)
        if free is None:
            continue
        rec = (holds or {}).get((equip.holder, equip.command))
        if holds is None:
            need, since = room_needed(equip, worn), now
        elif isinstance(rec, RoomWait) and not rec.lifted:
            need, since = rec.need, rec.since
        elif (
            isinstance(rec, EquipDropped)
            and not rec.lifted
            and rec.kind == REFUSAL_ROOM
        ):
            need, since = rec.need, rec.since or now
        else:
            # Judged by equips_to_queue and not short of room: it has the
            # room, or something other than room keeps it from being asked.
            continue
        if need <= int(free):
            continue
        if need > out.get(equip.holder, (0, "", 0))[0]:
            words = "to put on %s%s" % (equip.name, _over(equip, worn))
            out[equip.holder] = (need, words, _minutes(since, now))
    return out


def _room_note(equip, worn, need, free) -> str:
    return (
        "%s leaves %s in its bags: putting it on%s needs %d free bag slot(s) "
        "and it has %d"
    ) % (equip.holder, equip.name, _over(equip, worn), need, int(free))


def _refused(row) -> bool:
    return (
        row is not None
        and str(row.get("status", "")) in WORLD_REFUSALS
        and bool(str(row.get("detail") or "").strip())
    )


def recent_asks(rows) -> set:
    """(holder, command) asked inside the retry window and not refused since.

    The retry window is there because a piece put on a minute ago still reads
    as carried until the world saves. A refused row put nothing on, so it
    never blocks a retry: its hold (equips_to_queue) says when to ask again,
    and the window held a 15 minute hold for two hours (Shinyhair's 38s,
    2026-10-19, at 01:52, 03:54 and 05:56). `rows` carry target_name,
    command, status, detail and `recent`.
    """
    return {
        (str(row.get("target_name", "")), str(row.get("command", "")))
        for row in rows or ()
        if row.get("recent") and not _refused(row)
    }


def retry_answers(rows) -> dict:
    """(holder, command) -> the RETRY answers in `rows`: the unknown refusals
    and the bot's own read-back, the count RETRY_ANSWERS is judged against.
    An accepted, unanswered or other refused row is not one."""
    out: dict = {}
    for row in rows or ():
        if _refused(row) and _bot_keep(row) is None:
            if refusal_kind(row.get("detail")) == REFUSAL_RETRY:
                key = (str(row.get("target_name", "")), str(row.get("command", "")))
                out[key] = out.get(key, 0) + 1
    return out


@dataclass
class _Pass:
    """What one equips_to_queue pass judges every piece against."""

    answers: dict
    worn: dict
    holds: dict
    tries: dict
    retries: dict
    now: datetime
    free_slots: dict
    wearers: dict
    items: dict
    recent: set
    online: object
    give_up: int

    def free(self, holder):
        free = (self.free_slots or {}).get(holder)
        return None if free is None else int(free)

    def mark(self, holder):
        wearer = (self.wearers or {}).get(holder)
        return wearer.mark if wearer is not None else None


def _row_id(row) -> int:
    return int(row.get("id", 0)) if row is not None else 0


def _forget(holds, keys, answers, holders, wearers) -> None:
    """Drop or lift the records no longer about this pass's pieces.

    A hold or a bot-keeps record goes with its answer row (a newer answer is
    judged afresh) and lifts, or goes, when its piece is no longer wanted from
    one of `holders`. A room wait or a settled upgrade outlives its row's
    memory window, because a settle reopens on a change, never a timer; a
    newer answer replaces it. Only when this pass read the holder and not its
    level and skills is one whose row has gone forgotten, because a level
    change cannot then be told from age. The family's pass and the guild's
    share `holds`, so another pass's holders are left as they are.
    """
    for key in list(holds):
        rec, row = holds[key], answers.get(key)
        gone = key not in keys and key[0] in holders
        if isinstance(rec, (WorldHold, BotKeep)):
            if row is None or _row_id(row) != rec.row_id:
                del holds[key]
            elif gone and isinstance(rec, BotKeep):
                del holds[key]
            elif gone:
                rec.lifted = True
        elif gone or (row is not None and _row_id(row) > rec.row_id):
            del holds[key]
        elif (
            row is None
            and rec.row_id
            and isinstance(rec, EquipDropped)
            and key[0] in holders
            and key[0] not in (wearers or {})
        ):
            del holds[key]


def _answered_at(rec):
    return rec.refusal_at if isinstance(rec, WorldHold) else getattr(rec, "at", None)


def _handled(rec, row) -> bool:
    """`row` is already acted on: a lifted record on it (the piece is asked
    again), or the room wait it began. The world answers a retry on the same
    row, with a new time, so the time is part of the answer too."""
    return (
        rec is not None
        and rec.row_id == _row_id(row)
        and _answered_at(rec) == (row or {}).get("created_at")
        and (rec.lifted or isinstance(rec, RoomWait))
    )


def _reopened(rec, equip, p) -> bool:
    """A settled upgrade whose reason may have cleared (EquipDropped)."""
    if rec.worn != _settle_signature(equip, p.worn) or rec.wanted != equip.name:
        return True
    mark = p.mark(equip.holder)
    if rec.mark is not None and mark is not None and mark != rec.mark:
        return True
    free = p.free(equip.holder)
    if free is None:
        return False
    if rec.kind == REFUSAL_ROOM:
        return free >= max(1, rec.need)
    if rec.free_at is None or (rec.kind in _REOPEN_ON_RISE and free < rec.free_at):
        # The first read, or bags that filled since: a slot freed from here
        # is the change that reopens it.
        rec.free_at = free
        return False
    if rec.kind in _REOPEN_ON_RISE:
        return free > rec.free_at
    return rec.kind in _REOPEN_ON_CHANGE and free != rec.free_at


def _settle(equip, row, kind, note, p, need=0, since=None) -> str:
    p.holds[(equip.holder, equip.command)] = EquipDropped(
        row_id=_row_id(row),
        at=(row or {}).get("created_at"),
        worn=_settle_signature(equip, p.worn),
        wanted=equip.name,
        note=note,
        kind=kind,
        mark=p.mark(equip.holder),
        free_at=p.free(equip.holder),
        need=need,
        since=since,
    )
    return note


_UNTIL_CHANGE = "not asked again until its level, skills or what it wears there change"
_UNTIL_ANY = (
    "not asked again until its level, skills, bags or what it wears there change"
)


def _refusal_note(equip, row, kind, p) -> str:
    """The settled note for a refusal row of `kind`."""
    detail = str(row.get("detail")).strip()
    if kind == REFUSAL_GONE:
        return (
            "%s cannot find %s in its bags (%s); not asked again until its bags change"
            % (
                equip.holder,
                equip.name,
                detail,
            )
        )
    if kind == REFUSAL_RETRY:
        return "%s cannot wear %s: the world answered %s %d time(s); %s" % (
            equip.holder,
            equip.name,
            detail,
            (p.retries or p.tries or {}).get((equip.holder, equip.command), 1),
            _UNTIL_ANY,
        )
    return "%s cannot wear %s: %s; %s" % (
        equip.holder,
        equip.name,
        _drop_words(detail),
        _UNTIL_CHANGE,
    )


def _settles_now(equip, kind, p) -> bool:
    """A refusal of `kind` the member cannot clear now: a final or gone
    answer, or the RETRY_ANSWERS-th answer nobody named."""
    if kind in (REFUSAL_FINAL, REFUSAL_GONE):
        return True
    tried = (p.retries if p.retries is not None else p.tries or {}).get(
        (equip.holder, equip.command), 1
    )
    return kind == REFUSAL_RETRY and int(tried) >= RETRY_ANSWERS


def _utc(at):
    """`at` with a UTC zone when it is a naive datetime, else as given."""
    if isinstance(at, datetime) and at.tzinfo is None:
        return at.replace(tzinfo=timezone.utc)
    return at


def _start_room_wait(equip, row, created, p) -> None:
    """A room refusal: wait for the bag slots the world asked for."""
    free = p.free(equip.holder)
    p.holds[(equip.holder, equip.command)] = RoomWait(
        row_id=_row_id(row),
        worn=_worn_for(equip, p.worn),
        wanted=equip.name,
        need=max(room_needed(equip, p.worn), 1 if free is None else free + 1),
        free_at=free,
        since=created if isinstance(created, datetime) else p.now,
        at=row.get("created_at"),
    )


def _short_hold(equip, row, rec, kind, created, p):
    """A passing refusal, or the first one nobody named: hold the piece
    REFUSAL_WAIT_MINUTES from the answer. The note while it holds, else None
    (lifted: the wait is over, or what is worn there changed)."""
    hold = (
        rec
        if isinstance(rec, WorldHold)
        and not rec.lifted
        and rec.row_id == _row_id(row)
        and rec.refusal_at == row.get("created_at")
        else None
    )
    worn_now = _worn_for(equip, p.worn)
    if hold is None:
        hold = p.holds[(equip.holder, equip.command)] = WorldHold(
            row_id=_row_id(row),
            worn=worn_now,
            refusal_at=row.get("created_at"),
            kind=kind,
            seen=p.now,
        )
    elif hold.worn != worn_now:
        hold.lifted = True
        return None
    base = created if isinstance(created, datetime) else hold.seen
    hold.retry_at = base + timedelta(minutes=REFUSAL_WAIT_MINUTES)
    if hold.retry_at <= p.now:
        hold.lifted = True
        return None
    return "%s keeps %s over %s: %s; tries again at %s" % (
        equip.holder,
        " and ".join(name for _slot, _entry, name in worn_now) or "nothing",
        equip.name,
        str(row.get("detail")).strip(),
        _reader_due(hold.retry_at),
    )


def _on_refusal(equip, row, rec, p):
    """Act on a refusal row nothing has acted on yet: settle it, start a room
    wait, or hold it a short while. The note when the piece is not asked this
    pass, else None (a lifted hold, or a room wait the room step judges)."""
    kind = refusal_kind(row.get("detail"))
    if _settles_now(equip, kind, p):
        return _settle(equip, row, kind, _refusal_note(equip, row, kind, p), p)
    created = _utc(row.get("created_at"))
    if kind == REFUSAL_ROOM:
        _start_room_wait(equip, row, created, p)
        return None
    return _short_hold(equip, row, rec, kind, created, p)


def _on_room(equip, row, rec, p):
    """The note when `equip` waits on room in its bags this pass, else None.

    A room wait lifts the pass the room is there. One whose bags gained no
    slot in ROOM_WAIT_MINUTES is settled for room: a member with nothing it
    may sell, mail or destroy, a family member (the family's own town run
    makes its room), or one busy elsewhere, carries on with its play and
    asks again when its bags have the room."""
    key = (equip.holder, equip.command)
    free = p.free(equip.holder)
    worn_now = _worn_for(equip, p.worn)
    wait = rec if isinstance(rec, RoomWait) and not rec.lifted else None
    if wait is not None and wait.worn != worn_now:
        wait.lifted, wait = True, None
    need = room_needed(equip, p.worn)
    if wait is not None:
        need = max(need, wait.need)
    if free is not None and free >= need:
        if wait is not None:
            wait.lifted = True
        return None
    if free is None and wait is None:
        return None
    if wait is None:
        wait = p.holds[key] = RoomWait(
            _row_id(row),
            worn_now,
            equip.name,
            need,
            free,
            p.now,
            at=(row or {}).get("created_at"),
        )
    elif free is not None and (wait.free_at is None or free > wait.free_at):
        wait.free_at, wait.since = free, p.now
    if free is None:
        note = (
            "%s leaves %s in its bags: putting it on%s needs %d free bag slot(s) "
            "and its bags were not read"
        ) % (equip.holder, equip.name, _over(equip, p.worn), need)
    else:
        note = _room_note(equip, p.worn, need, free)
    if p.now - wait.since < timedelta(minutes=ROOM_WAIT_MINUTES):
        return note
    return _settle(
        equip,
        {"id": wait.row_id, "created_at": wait.at},
        REFUSAL_ROOM,
        "%s waits for bag room to wear %s: putting it on%s needs %d free bag "
        "slot(s) and it has %s; asked again when its bags have the room"
        % (
            equip.holder,
            equip.name,
            _over(equip, p.worn),
            need,
            "an unread count" if free is None else free,
        ),
        p,
        need=need,
        since=wait.since,
    )


def _on_bot_keep(equip, row, rec, p) -> bool:
    """Record or keep a bot-keeps answer: True while it settles the piece."""
    key = (equip.holder, equip.command)
    worn_now = _worn_for(equip, p.worn)
    if isinstance(rec, BotKeep) and rec.row_id == _row_id(row):
        if rec.worn != worn_now or rec.wanted != equip.name:
            rec.lifted = True
        return not rec.lifted
    if rec is not None and rec.row_id == _row_id(row):
        # A lifted keep that then waited on room: the answer is acted on.
        return False
    kept, challenger, challenger_score, kept_score = _bot_keep(row)
    p.holds[key] = BotKeep(
        row_id=_row_id(row),
        worn=worn_now,
        wanted=equip.name,
        note=f"keeps {kept}: it scores {kept_score} to {challenger}'s {challenger_score}",
    )
    return True


def _held_note(equip, row, rec, keeps, p):
    """The note when `equip` is held back before the world is asked: a piece
    its holder cannot wear, a settled upgrade nothing has reopened, a refusal
    being acted on, or a wait for bag room. None when nothing holds it."""
    why = wear_refusal(
        equip,
        (p.items or {}).get(int(equip.entry)),
        (p.wearers or {}).get(equip.holder),
        p.worn,
    )
    if why:
        return "%s cannot wear %s: %s; not asked until that changes" % (
            equip.holder,
            equip.name,
            why,
        )
    if isinstance(rec, EquipDropped) and not rec.lifted:
        if not _reopened(rec, equip, p):
            return rec.note
        rec.lifted = True
    if not keeps and _refused(row) and not _handled(rec, row):
        note = _on_refusal(equip, row, rec, p)
        if note:
            return note
    return _on_room(equip, row, p.holds.get((equip.holder, equip.command)), p) or None


def _ask_now(equip, row, p) -> tuple:
    """(ask it now, the note when not or "") for a piece nothing holds back."""
    key = (equip.holder, equip.command)
    # Never queue an equip for an offline member (#869): the world cannot act
    # on it, and it just piles up retries.
    if p.online is not None and equip.holder not in p.online:
        return False, "%s is offline; equip of %s held until they are online" % (
            equip.holder,
            equip.name,
        )
    # The world already put this entry on. A later bag snapshot can show it
    # carried again after another gear pass replaces it; repeating the same
    # command is not an equip refusal and must not become a hold.
    if str((row or {}).get("status", "")) == "applied" or key in p.recent:
        return False, ""
    # A SILENT give-up (#869): the world took the command `give_up` times and
    # the piece is still in the bags, with no refusal to say why. Settled with
    # that reason, never a day's hold; a lifted settle is asked once more.
    rec = p.holds.get(key)
    attempts = int((p.tries or {}).get(key, 0))
    if attempts >= p.give_up and not _refused(row) and not _handled(rec, row):
        return False, _settle(
            equip,
            row,
            SETTLED_SILENT,
            "%s cannot wear %s: the world took %d equip command(s) and it is still "
            "in its bags; %s" % (equip.holder, equip.name, attempts, _UNTIL_ANY),
            p,
        )
    return True, ""


def _judge(equip, p) -> tuple:
    """(ask it now, the note when not or "") for one wanted piece."""
    key = (equip.holder, equip.command)
    row, rec = p.answers.get(key), p.holds.get(key)
    # The bot keeps its own better-scored piece by choice: not a refusal, no
    # stuck reason, not wanted again until its slot's gear or the piece
    # changes (#994). The reader-worded line is in `member_gear_notes`.
    keeps = _bot_keep(row) is not None
    if keeps and _on_bot_keep(equip, row, rec, p):
        return False, ""
    note = _held_note(equip, row, rec, keeps, p)
    if note is not None:
        return False, note
    return _ask_now(equip, row, p)


def world_held(wanted, holds) -> int:
    """How many of `wanted` are held on the world's answer this pass: a short
    hold or a room wait. A bot-keeps answer is the bot's own choice and a
    settled upgrade is not held, so neither counts."""
    return sum(
        1
        for e in wanted
        if isinstance((holds or {}).get((e.holder, e.command)), (WorldHold, RoomWait))
        and not holds[(e.holder, e.command)].lifted
    )


def equips_to_queue(
    wanted,
    recent,
    tries,
    give_up=3,
    answers=None,
    worn=None,
    holds=None,
    holders=None,
    now=None,
    memory_hours=24,
    online=None,
    free_slots=None,
    wearers=None,
    items=None,
    retries=None,
) -> tuple:
    """Which equips to write now, and a note for each one held back.

    `recent` is the (holder, command) pairs already written inside the retry
    window and not refused since (recent_asks). The world's save lags the
    bags by up to fifteen minutes (PlayerSaveInterval), so a piece put on a
    minute ago still reads as carried, and asking again inside the window
    would be the duplicate.

    NO EQUIP REFUSAL A MEMBER CAN CLEAR ITSELF IS EVER A LONG HOLD (#1088).
    `answers` is the newest answered row per (holder, command), from
    `latest_answers`. A refusal is read by what the member can do about it
    (refusal_kind): a passing state of the holder, or the first answer
    nobody named, waits REFUSAL_WAIT_MINUTES; bags too full wait for the
    room, at most ROOM_WAIT_MINUTES; anything the member cannot clear now
    settles the upgrade (EquipDropped) with its reason, never a hold and
    never a stuck reason, until a change can clear it: the holder's level or
    skills (`wearers`, holder -> WearerFacts), what it wears there (`worn`,
    from `worn_pieces`) or its bags (`free_slots`). `tries` counts (holder,
    command) over the memory window and `retries` the RETRY answers in it
    (retry_answers; `tries` when None). `memory_hours` is kept for the
    callers; nothing waits for it any longer.

    An `unchanged` answer whose detail is the bot's own scoring verdict ("the
    bot keeps ...") is the bot's choice, not a refusal: it is recorded as a
    BotKeep instead (#994), never held on and never given a stuck reason.
    An `applied` answer ends this attempt. `holds` is the caller's dict of
    records, kept between passes and updated in place; `holders` are the
    members this pass read, by default the holders of `wanted`.

    A PIECE ITS HOLDER CANNOT WEAR IS NOT ASKED. `items` (entry -> ItemFacts)
    and `wearers` say so before the world does (wear_refusal): the note says
    why, and it is judged again every pass.

    A PIECE ITS HOLDER HAS NO BAG ROOM FOR IS NOT ASKED (#1088). `free_slots`
    is holder -> free general bag slots, None or a missing holder when unread.
    An equip that needs more free slots than its holder has (room_needed: a
    two-hander over a worn off hand) is never written, because the world can
    only refuse it; its note says so in plain words, and `equip_room` names
    the shortfall for the guild jobs pass to make the room. The piece is
    asked the pass the room is there.
    """
    del memory_hours
    holds = {} if holds is None else holds
    if holders is None:
        holders = {e.holder for e in wanted}
    p = _Pass(
        answers=answers or {},
        worn=worn,
        holds=holds,
        tries=tries or {},
        retries=retries,
        now=now or datetime.now(timezone.utc),
        free_slots=free_slots,
        wearers=wearers,
        items=items,
        recent=recent,
        online=online,
        give_up=int(give_up),
    )
    _forget(
        holds, {(e.holder, e.command) for e in wanted}, p.answers, set(holders), wearers
    )
    queue, notes = [], []
    for equip in wanted:
        ask, note = _judge(equip, p)
        if note:
            notes.append(note)
        if ask:
            queue.append(equip)
    return tuple(queue), tuple(notes)


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


def _worn_slot(row: dict, inventory_type: int) -> tuple[str, str]:
    """Resolve the gear bucket and off-hand kind from an equipped row."""
    slot = _SLOT_BY_INVTYPE.get(inventory_type, "")
    kind = _OFF_HAND_KIND.get(inventory_type, OFF_HAND_NONE)
    if inventory_type != 13:
        return slot, kind
    try:
        equipment_slot = int(row["equipment_slot"])
    except (KeyError, TypeError, ValueError):
        return slot, kind
    if equipment_slot == _EQUIPMENT_SLOT_OFF_HAND:
        return _OFF_HAND, OFF_HAND_WEAPON
    if equipment_slot == _EQUIPMENT_SLOT_MAIN_HAND:
        return _MAIN_HAND, kind
    return slot, kind


def characters_from_rows(rows, names, roles=None) -> list:
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

    `roles` maps a name to ROLE_TANK, ROLE_HEALER or ROLE_DAMAGE; a name it
    does not mention, and every name when it is None, is ROLE_UNKNOWN.

    A row may carry `weapon_skills`, the weapon subclasses the character has
    learned (bridge reads them from character_skills, #393). A row without
    the key, or with None, leaves the character's skills unread.
    """
    roles = dict(roles or {})
    seen = {}
    off_hands = {}
    skills = {}
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
        if name not in skills:
            skills[name] = weapon_skills_of(row)
        try:
            inventory_type = int(row["inventory_type"])
            item_level = int(row["item_level"])
        except (KeyError, TypeError, ValueError):
            continue
        # Generic one-hand weapons fit either hand; retain the position read
        # from character_inventory instead of collapsing both into main hand.
        slot, kind = _worn_slot(row, inventory_type)
        if slot:
            # Two rings, two trinkets, a main hand and an off hand all land in
            # one bucket. The BEST of them is what an upgrade has to beat,
            # because the worst is the one a new piece would displace.
            equipped[slot] = max(equipped.get(slot, 0), item_level)
        if kind:
            off_hands[name] = kind
    return [
        CharacterState(
            name=name,
            class_id=seen[name][0],
            level=seen[name][1],
            equipped=seen[name][2],
            role=str(roles.get(name, ROLE_UNKNOWN) or ROLE_UNKNOWN),
            off_hand_kind=off_hands.get(name, OFF_HAND_NONE),
            weapon_skills=skills.get(name),
        )
        for name in names
        if name in seen
    ]


def weapon_skills_of(row):
    """The learned weapon subclasses a row carries, or None when unread."""
    try:
        held = row["weapon_skills"]
    except (KeyError, TypeError):
        return None
    if held is None:
        return None
    try:
        return frozenset(int(sub) for sub in held)
    except (TypeError, ValueError):
        return None


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
            out.append(
                Holding(
                    holder=str(row["holder"]),
                    guid=int(row["item_guid"]),
                    entry=int(row.get("entry", 0)),
                    name=str(row["name"]),
                    quality=int(row["quality"]),
                    item_level=int(row["item_level"]),
                    required_level=int(row["required_level"]),
                    allowable_class=int(row["allowable_class"]),
                    inventory_type=int(row["inventory_type"]),
                    item_class=int(row["item_class"]),
                    soulbound=bool(int(row.get("instance_flags", 0) or 0) & 0x1),
                    item_subclass=int(row.get("item_subclass", SUBCLASS_UNSTATED)),
                    has_effect=bool(int(row.get("has_effect", 0) or 0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# THE GUILD'S LOOT, RANKED (#174)
#
# Everything above moves the family's own gear. Nothing moved a guildmate's
# loot to whoever in the guild gains most from it. Measured on the dev realm
# 2026-09-22: a level 60 warlock guildmate carried Destiny (a bind-on-equip
# epic two-hand sword, item level 57) she can never swing, while the family's
# Retribution paladin wore a one-hander at item level 52.
#
# THE SAME OPINION, RANKED. `upgrade_gain` decides whether a receiver gains
# and by how much; `rank_receivers` only orders the answers. It is one pure
# function, candidates and an item in and receivers out, so a second scorer
# (the Jev Score proposed in #95) can sit beside it on the same inputs and be
# compared row for row.
#
# "SURE" IS A CLAIM ABOUT THE NUMBERS. Item level prices stats. It cannot
# price a chance-on-hit or an on-use spell, so for an item carrying one the
# gain is only a floor - the module's own equip rule says the same, "cannot
# be settled from the numbers". Such an item is ranked and reported and never
# moved by this heuristic: it is the case a better scorer exists for.
#
# A HAND-OVER MUST HAPPEN IN THE WORLD. kind='give' moves an item between two
# online characters at any distance, which is a database write wearing a
# hand-over's name: a sword left Silithus and arrived in Winterspring in the
# same second. `route_deliverable` never picks it. There are two honest ways:
#
#     trade   the two are within TRADE_YARDS already; the core runs a real
#             trade between them.
#     mail    the holder is at a mailbox and posts it; the core charges the
#             postage and applies its delivery delay, and the family's own
#             mail pass collects it later. Family receivers only, because
#             nothing makes a guildmate's bot collect post.
#
# Neither is arranged here. `guildroute.plan_mail_runs` walks a waiting
# holder to the nearest mailbox: a roster family's leader by the town slot,
# a guildmate's bot off the roster by the module's `walk-to-mailbox` row
# (quadseven/mod-overseer#570, #185). A worldserver without that row makes
# the pass wait for the meeting or the mailbox and say which one.

MAIL = "mail"

# The smallest gain worth a hand-over across the guild. One or two item levels
# is inside the noise of how stats are budgeted.
CLEAR_GAIN = 3

# Hand-overs one pass may write, across the whole guild.
PER_PASS = 2


@dataclass(frozen=True)
class Candidate:
    """One online guild member who could receive an item."""

    character: CharacterState
    family: bool = False

    @property
    def name(self) -> str:
        return self.character.name


@dataclass(frozen=True)
class Ranked:
    """One receiver for one item, as `rank_receivers` scored them."""

    name: str
    gain: int  # item levels over what the receiver wears there now
    family: bool
    fills_weakest: bool  # the item goes in the receiver's weakest slot
    sure: bool  # False when item level cannot price the item (an effect)
    reason: str


def rank_receivers(holding: Holding, candidates) -> tuple:
    """Every candidate this item is a real upgrade for, best first.

    Ordered by gain, then family before guildmate, then the receiver whose
    weakest slot it fills, then by name, so two passes over unchanged facts
    rank identically. The holder is never a candidate and a soulbound item
    ranks nobody. Pure, and the seam a second scorer sits beside.
    """
    if holding.soulbound:
        return ()
    sure = not holding.has_effect
    bucket = bucket_of(holding)
    out = []
    for candidate in candidates:
        character = candidate.character
        if character.name == holding.holder:
            continue
        gain, reason = upgrade_gain(holding, character)
        if gain <= 0:
            continue
        weakest = weakest_slot(character)
        out.append(
            Ranked(
                name=character.name,
                gain=int(gain),
                family=bool(candidate.family),
                fills_weakest=weakest is not None and weakest.slot == bucket,
                sure=sure,
                reason=reason,
            )
        )
    out.sort(key=lambda r: (-r.gain, not r.family, not r.fills_weakest, r.name))
    return tuple(out)


@dataclass(frozen=True)
class Route:
    """One guildmate item, one receiver, and how it travels once `verb` is set."""

    holder: str
    taker: str
    guid: int
    entry: int
    name: str
    gain: int
    family: bool
    fills_weakest: bool
    reason: str
    verb: str = ""
    alternates: tuple = ()

    @property
    def command(self) -> str:
        """What the executor parses: DoTrade's guid spec, or a mail `send`."""
        if self.verb == MAIL:
            return "send item:%d subject:%s" % (int(self.guid), self.name)
        return "guid:%d" % int(self.guid)

    @property
    def said(self) -> str:
        """The log line: holder, receiver, item, gain and why."""
        return "%s -> %s by %s, %s (item %d), +%d item levels - %s" % (
            self.holder,
            self.taker,
            self.verb or "?",
            self.name,
            int(self.guid),
            int(self.gain),
            self.reason,
        )


def _route(holding: Holding, ranked: Ranked) -> Route:
    return Route(
        holder=holding.holder,
        taker=ranked.name,
        guid=int(holding.guid),
        entry=int(holding.entry),
        name=holding.name,
        gain=ranked.gain,
        family=ranked.family,
        fills_weakest=ranked.fills_weakest,
        reason=ranked.reason,
    )


def route_plan(holdings, candidates, clear_gain: int = CLEAR_GAIN) -> Plan:
    """Every guildmate item that should go to somebody who gains more.

    Plan.grants carries Routes here, best gain first, each with its
    runners-up for `route_deliverable` to walk.

    THE HOLDER IS ASKED FIRST, soulbound-blind, with `would_wear`, and an item
    its holder would wear never moves. A holder with no Candidate (nothing
    read about what they wear) is left alone rather than presumed to have no
    use for their own gear. A family holder is not this pass's: the family's
    own passes already decide those items, and two writers for one item is
    the bug this project has fixed more than once.
    """
    by_name = {c.name: c for c in candidates}
    routes, notes = [], []
    for holding in sorted(holdings, key=lambda h: (h.holder, int(h.guid))):
        holder = by_name.get(holding.holder)
        if holder is None or holder.family or holding.soulbound:
            continue
        if would_wear(holding, holder.character)[0]:
            continue
        ranked = rank_receivers(holding, candidates)
        if not ranked:
            continue
        if not ranked[0].sure:
            notes.append(
                "%s carries %s, best for %s by item level (+%d), but it has an "
                "effect item level cannot price, so it is not moved"
                % (holding.holder, holding.name, ranked[0].name, ranked[0].gain)
            )
            continue
        clear = [r for r in ranked if r.gain >= int(clear_gain)]
        if not clear:
            notes.append(
                "%s carries %s; the best gain is %s's +%d, under the %d a "
                "hand-over needs"
                % (
                    holding.holder,
                    holding.name,
                    ranked[0].name,
                    ranked[0].gain,
                    int(clear_gain),
                )
            )
            continue
        first = _route(holding, clear[0])
        routes.append(
            replace(first, alternates=tuple(_route(holding, r) for r in clear[1:]))
        )
    routes.sort(key=lambda r: (-r.gain, r.holder, r.guid))
    return Plan(grants=tuple(routes), notes=tuple(notes))


def route_deliverable(
    routes, position_rows, at_mailbox, free_slots, per_pass=PER_PASS
) -> Plan:
    """The routes that can happen in the world now, each with its verb.

    TRADE when the holder and a ranked receiver are within trade range and
    the receiver has a free slot. MAIL when the holder is at a mailbox and the
    receiver is family. Never GIVE. Otherwise the item waits, with one note
    naming what it waits on. A receiver takes at most one item per pass, and
    at most `per_pass` routes come back.
    """
    spots = spots_from_rows(position_rows)
    room = {str(k): int(v or 0) for k, v in dict(free_slots or {}).items()}
    posting = {str(n) for n in (at_mailbox or ())}
    out, notes, taken = [], [], set()
    for route in routes:
        if len(out) >= int(per_pass):
            notes.append(
                "%s stays with %s this pass: %d hand-overs is the limit per pass"
                % (route.name, route.holder, int(per_pass))
            )
            continue
        here = spots.get(route.holder)
        if here is None:
            notes.append(
                "%s stays with %s: %s is not in the world"
                % (route.name, route.holder, route.holder)
            )
            continue
        chosen = None
        walls = {"taken": [], "absent": [], "full": [], "apart": []}
        for option in (route,) + tuple(route.alternates):
            verb, wall = _verb_for(option, here, spots, room, posting, taken)
            if verb:
                chosen = replace(option, verb=verb, alternates=())
                break
            walls[wall].append(option.taker)
        if chosen is None:
            notes.append(_route_withheld(route, posting, walls))
            continue
        if chosen.verb == TRADE:
            room[chosen.taker] = room.get(chosen.taker, 0) - 1
        taken.add(chosen.taker)
        out.append(chosen)
    return Plan(grants=tuple(out), notes=tuple(notes))


def _few(names: list) -> str:
    """Up to three names, then how many more: a note stays one line."""
    if len(names) <= 3:
        return _joined(names)
    return "%s and %d more" % (", ".join(names[:3]), len(names) - 3)


def _verb_for(option, here, spots, room, posting, taken) -> tuple:
    """(verb, "") when this receiver can take the item now, else ("", wall).

    The wall is which of four things stopped it: "taken" (already has one
    coming this pass), "absent" (not in the world), "full" (beside the holder
    with no free slot) or "apart" (neither beside the holder nor reachable by
    post).
    """
    if option.taker in taken:
        return "", "taken"
    there = spots.get(option.taker)
    if there is None:
        return "", "absent"
    if _within_trade_range(here, there):
        if room.get(option.taker, 0) <= 0:
            return "", "full"
        return TRADE, ""
    if option.family and option.holder in posting:
        return MAIL, ""
    return "", "apart"


def _route_withheld(route, posting, walls: dict) -> str:
    """The one note for a route no ranked receiver could take this pass."""
    taken_by, absent = walls["taken"], walls["absent"]
    full, apart = walls["full"], walls["apart"]
    said = []
    if apart:
        said.append(
            "%s is beside none of %s%s"
            % (
                route.holder,
                _few(apart),
                "" if route.holder in posting else ", and at no mailbox",
            )
        )
    if full:
        said.append(
            "%s ha%s no free bag slot (no slot-freeing step is available and "
            "no direct equip path is available)"
            % (_few(full), "ve" if len(full) > 1 else "s")
        )
    if absent:
        said.append(
            "%s %s not in the world"
            % (_few(absent), "are" if len(absent) > 1 else "is")
        )
    if taken_by:
        said.append(
            "%s already ha%s one coming"
            % (_few(taken_by), "ve" if len(taken_by) > 1 else "s")
        )
    return "%s stays with %s: %s" % (route.name, route.holder, "; ".join(said))
