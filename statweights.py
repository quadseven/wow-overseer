"""Stat weights per role, and the role a class and talent tree play (#194).

What a question to Jev about gear says a character values. The loot council,
item_disposition and weapon_choice all show these facts, so a protection
warrior is asked about as somebody who values stamina, defense, armor and
block, and a holy priest as somebody who values intellect and spirit.

MIRRORED FROM mod-overseer, which is the one rule: `StatWeight`,
`ArmourWeight` and `DpsWeight` in src/overseer_decisions.cpp price every stat
in armour points for one role, and `GearRoleFor` in src/mod_overseer.cpp
picks the role from the class and the talent tree. The council's rows carry
upgrades the module scored with those weights; the facts here show a
question the same weights, so both halves weigh an item the one way. A
change to the module's table is a change to this one.
"""

from __future__ import annotations

TANK, MELEE, RANGED, HEALER, CASTER = "tank", "melee", "ranged", "healer", "caster"
UNKNOWN = "unknown"

STAT_WEIGHTS = {
    TANK: {
        "armor": 1.0,
        "defense": 3.0,
        "dodge": 2.5,
        "parry": 2.5,
        "stamina": 2.0,
        "block": 1.5,
        "block_value": 1.0,
        "strength": 1.5,
        "agility": 1.2,
        "hit": 1.0,
        "crit": 0.5,
        "attack_power": 0.3,
        "weapon_dps": 4.0,
    },
    MELEE: {
        "strength": 2.0,
        "agility": 2.0,
        "hit": 1.5,
        "crit": 1.5,
        "stamina": 1.0,
        "attack_power": 1.0,
        "armor": 0.3,
        "defense": 0.3,
        "weapon_dps": 8.0,
    },
    RANGED: {
        "agility": 2.5,
        "hit": 1.5,
        "crit": 1.5,
        "stamina": 1.0,
        "attack_power": 1.0,
        "intellect": 0.3,
        "strength": 0.2,
        "armor": 0.15,
        "weapon_dps": 8.0,
    },
    HEALER: {
        "intellect": 2.5,
        "spirit": 2.0,
        "mana_regeneration": 2.0,
        "spell_power": 1.5,
        "stamina": 1.0,
        "crit": 0.8,
        "armor": 0.1,
        "weapon_dps": 1.0,
    },
    CASTER: {
        "spell_power": 2.0,
        "intellect": 2.0,
        "spell_hit": 2.0,
        "crit": 1.5,
        "stamina": 1.0,
        "spirit": 0.8,
        "armor": 0.1,
        "weapon_dps": 1.0,
    },
}

# (class id, talent tree name) -> role, GearRoleFor's table. A class with one
# role whatever its tree is keyed with tree None.
_ROLES = {
    (1, "Arms"): MELEE,
    (1, "Fury"): MELEE,
    (1, "Protection"): TANK,
    (2, "Holy"): HEALER,
    (2, "Protection"): TANK,
    (2, "Retribution"): MELEE,
    (3, None): RANGED,
    (4, None): MELEE,
    (5, "Discipline"): HEALER,
    (5, "Holy"): HEALER,
    (5, "Shadow"): CASTER,
    (6, "Blood"): TANK,
    (6, "Frost"): MELEE,
    (6, "Unholy"): MELEE,
    (7, "Elemental"): CASTER,
    (7, "Enhancement"): MELEE,
    (7, "Restoration"): HEALER,
    (8, None): CASTER,
    (9, None): CASTER,
    (11, "Balance"): CASTER,
    (11, "Feral Combat"): MELEE,
    (11, "Restoration"): HEALER,
}


def role_for(class_id, spec: str) -> str:
    """The role a class and talent tree play, or UNKNOWN."""
    try:
        cid = int(class_id)
    except (TypeError, ValueError):
        return UNKNOWN
    return _ROLES.get((cid, None)) or _ROLES.get((cid, str(spec or ""))) or UNKNOWN


def stat_weights(role: str) -> dict:
    """What one point of each stat is worth to this role, in armor points.
    Empty for an unknown role: no opinion, rather than a guess."""
    return dict(STAT_WEIGHTS.get(role, {}))
