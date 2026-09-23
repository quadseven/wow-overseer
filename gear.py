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
from dataclasses import dataclass, field, replace

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
# item_template.subclass for class 4 (ARMOR). 5 is an unused buckler slot and
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


def wieldable_weapon(holding: Holding, character: CharacterState) -> bool:
    """Can this character's class wield this weapon at all.

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
    if subclass == ARMOR_SHIELD:
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
        return (
            False,
            "not gear (quest items, reagents and consumables are never considered)",
        )
    if not usable_by_class(holding, character.class_id):
        cls = _CLASS_NAMES.get(character.class_id, "class %d" % character.class_id)
        return False, f"{cls} cannot equip it"
    # AllowableClass said yes, which for armour it says to everyone. Whether
    # the class is trained in that armour type is a separate fact and the one
    # that stops mail reaching the priest - see _ARMOR_TRAINED_AT.
    if not wearable_armor(holding, character):
        cls = _CLASS_NAMES.get(character.class_id, "class %d" % character.class_id)
        return False, f"{cls} is not trained in that armour type"
    if not wieldable_weapon(holding, character):
        cls = _CLASS_NAMES.get(character.class_id, "class %d" % character.class_id)
        return False, f"{cls} cannot wield that weapon type"
    if character.level < holding.required_level:
        return False, f"requires level {holding.required_level}"

    slot = _slot_for(holding)
    if not slot:
        return False, "inventory type %d has no known slot" % int(
            holding.inventory_type
        )

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
    if slot == _TWO_HAND and character.has_off_hand():
        if not prefers_two_hander(character):
            return False, "would displace an equipped off-hand item"
        current = max(
            character.equipped_level(_TWO_HAND), character.equipped_level(_MAIN_HAND)
        )
        if current and holding.item_level <= current:
            return (
                False,
                f"not an upgrade (the main hand worn now is item level {current})",
            )
        return True, (
            f"item level {holding.item_level} two-hander beats the "
            f"{current} main hand, and a damage role has no use for the shield"
        )

    current = character.equipped_level(slot)
    if current and holding.item_level <= current:
        return False, f"not an upgrade (currently equipped is item level {current})"

    return True, (
        f"empty {slot.replace('_', ' ')} slot"
        if not current
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
    if slot == _TWO_HAND:
        worn = max(worn, character.equipped_level(_MAIN_HAND))
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
    """Where one character is standing, as the world last reported it."""

    map_id: int
    x: float
    y: float


def _within_trade_range(here: Spot, there: Spot) -> bool:
    """Close enough for the core to open a trade window.

    THE MAP IS CHECKED BEFORE THE DISTANCE, and not as a formality: three of
    the five hearth to Eastern Kingdoms while the dungeon is on Kalimdor, and
    coordinates on two different maps are not comparable at all. Subtracting
    them yields a number, and that number would have put an ocean inside
    eleven yards.
    """
    if int(here.map_id) != int(there.map_id):
        return False
    return math.hypot(here.x - there.x, here.y - there.y) <= TRADE_YARDS


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
            spots[str(name)] = Spot(
                map_id=int(row["map_id"]), x=float(row["pos_x"]), y=float(row["pos_y"])
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
            "%s %s no free bag slot to receive it"
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
        if _hand_refusal(holding, character):
            continue
        slot = _slot_for(holding)
        group = _WEAPON_GROUP.get(slot, slot)
        key = (holding.holder, group)
        worn = character.equipped_level(slot)
        if slot == _TWO_HAND:
            worn = max(worn, character.equipped_level(_MAIN_HAND))
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
    worn = character.equipped_level(slot)
    if slot == _TWO_HAND:
        worn = max(worn, character.equipped_level(_MAIN_HAND))
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


def equips_to_queue(wanted, recent, tries, give_up=3) -> tuple:
    """Which equips to write now, and a note for each one held back.

    `recent` is the (holder, command) pairs already written inside the retry
    window. The world's save lags the bags by up to fifteen minutes
    (PlayerSaveInterval), so a piece put on a minute ago still reads as
    carried, and asking again inside the window would be the duplicate.

    `tries` counts (holder, command) over the longer memory window. A piece
    asked for `give_up` times and still carried is one the world will not put
    on for a reason this side cannot see - combat, a proficiency the numbers
    do not show - so it is held and said, rather than asked for every window
    for ever.
    """
    queue, notes = [], []
    least = max(1, int(give_up))
    for equip in wanted:
        key = (equip.holder, equip.command)
        if key in recent:
            continue
        if int(tries.get(key, 0)) >= least:
            notes.append(
                "%s still carries %s after %d equip command(s); held until the "
                "memory window passes" % (equip.holder, equip.name, int(tries[key]))
            )
            continue
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
    """
    roles = dict(roles or {})
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
    return [
        CharacterState(
            name=name,
            class_id=seen[name][0],
            level=seen[name][1],
            equipped=seen[name][2],
            role=str(roles.get(name, ROLE_UNKNOWN) or ROLE_UNKNOWN),
        )
        for name in names
        if name in seen
    ]


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
            "%s ha%s no free bag slot" % (_few(full), "ve" if len(full) > 1 else "s")
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
