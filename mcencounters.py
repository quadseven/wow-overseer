"""What each Molten Core boss asks of a raid, and what a lineup lacks for it.

WHY THIS EXISTS. raidlineup.py seats forty raiders in eight groups of five and
raidteams.py holds the operator's approved seats, but neither said whether a
lineup could meet the bosses. The old answer was a template: one tank and one
healer in every group. The bosses do not ask for that. They ask for a few
tanks, curse and magic dispels, crowd control on adds, interrupts, fear
protection, a Tranquilizing Shot and a fire resistance source. This module
writes those asks down boss by boss and counts them against a lineup, so the
Raid tab can say "Lucifron lacks 1 curse dispeller" instead of "group 6 has no
healer".

It reads, it never seats. Nothing here changes who sits where; an approved
lineup stays exactly as the operator approved it (raidteams.py).

WHERE THE ASKS COME FROM. Each encounter names the spells or mechanics that
create the ask, read from the Molten Core boss scripts of the core this realm
pins (the MoltenCore directory of the core fork, at AC_CORE_SHA in
UPSTREAM-PINS.env):

- Lucifron casts Lucifron's Curse (19703) and Impending Doom (19702).
- Magmadar casts Panic (19408), a fear, and Frenzy (19451).
- Gehennas casts Gehennas' Curse (19716).
- Garr's Firesworn can be banished; Eruption (20482) and Separation Anxiety
  (23492) strip and block the banish, so a warlock re-banishes on a cycle.
- Shazzrah casts Shazzrah's Curse (19713) and buffs himself with Magic
  Grounding (19714), which an offensive dispel removes.
- Baron Geddon casts Ignite Mana (19659) and Inferno (19695).
- Golemagg calls his two Core Ragers to him (20544); they must be held.
- Sulfuron's Flamewaker Priests cast Dark Mending (19775) and Shadow Word:
  Pain (19776).
- Majordomo Executus fights with eight adds (his script counts them down from
  eight: polymorph immunity, 21087, lands when four remain) and teleports his
  target, wiping threat (20538).
- Ragnaros knocks back his tank with Wrath of Ragnaros (20566) and summons
  eight Sons of Flame (21108).

The fire resistance source is one, not one a group: the operator read the
realm's Spell.dbc (wow-overseer#684) and Fire Resistance Aura and the Fire
Resistance Totem's aura are APPLY_AREA_AURA_RAID, 40 and 30 yards.

The counts are planning numbers. The scripts say which mechanic exists; how
many hands it takes (two curse dispellers so one death does not stop the
fight) is a judgement, kept here in one table so a change is one line.

WHAT IT DOES NOT CHECK YET. A capability is read from the class alone: a mage
counts as a curse dispeller whatever its level. The level each class learns a
spell at, read from this server's spell and trainer data, is a follow-up.
"""

from __future__ import annotations

from typing import NamedTuple

# WotLK class ids, as the realm's `characters.class` column stores them. The
# same numbers as raidlineup.py; repeated so this module imports nothing.
WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST = 1, 2, 3, 4, 5
DEATH_KNIGHT, SHAMAN, MAGE, WARLOCK, DRUID = 6, 7, 8, 9, 11

# The seat word a dedicated tank carries (raidroles.SEAT_TANK).
TANK_SEAT = "tank"


class Capability(NamedTuple):
    """Who can bring one thing a boss asks for."""

    classes: frozenset
    one: str
    many: str


TANKS = "tanks"
CURSE_DISPEL = "curse_dispel"
MAGIC_DISPEL = "magic_dispel"
OFFENSIVE_DISPEL = "offensive_dispel"
BANISH = "banish"
CROWD_CONTROL = "crowd_control"
INTERRUPT = "interrupt"
FEAR_PROTECTION = "fear_protection"
TRANQUILIZING_SHOT = "tranquilizing_shot"
FIRE_RESISTANCE = "fire_resistance"

# Tanks are counted from the seat, not the class: a warrior in a damage seat
# is not holding Golemagg's ragers. Every other capability is the class.
CAPABILITIES = {
    TANKS: Capability(frozenset(), "tank", "tanks"),
    # Remove Curse. A shaman's Cleanse Spirit is a talent, so it is not counted.
    CURSE_DISPEL: Capability(
        frozenset({MAGE, DRUID}), "curse dispeller", "curse dispellers"
    ),
    # A friendly magic dispel: a priest's Dispel Magic, a paladin's Cleanse.
    MAGIC_DISPEL: Capability(
        frozenset({PRIEST, PALADIN}), "magic dispeller", "magic dispellers"
    ),
    # Taking a buff off an enemy: Dispel Magic on a hostile target, Purge.
    OFFENSIVE_DISPEL: Capability(frozenset({PRIEST, SHAMAN}), "purger", "purgers"),
    BANISH: Capability(frozenset({WARLOCK}), "banisher", "banishers"),
    # Crowd control that holds a humanoid add: Polymorph, Freezing Trap, Sap.
    CROWD_CONTROL: Capability(
        frozenset({MAGE, HUNTER, ROGUE}), "crowd controller", "crowd controllers"
    ),
    INTERRUPT: Capability(
        frozenset({WARRIOR, ROGUE, SHAMAN, MAGE, DEATH_KNIGHT}),
        "interrupter",
        "interrupters",
    ),
    # Fear Ward, Tremor Totem, Berserker Rage.
    FEAR_PROTECTION: Capability(
        frozenset({PRIEST, SHAMAN, WARRIOR}), "fear protector", "fear protectors"
    ),
    TRANQUILIZING_SHOT: Capability(
        frozenset({HUNTER}), "Tranquilizing Shot", "Tranquilizing Shots"
    ),
    # Fire Resistance Aura or Fire Resistance Totem: raid-wide, so one is enough.
    FIRE_RESISTANCE: Capability(
        frozenset({PALADIN, SHAMAN}),
        "fire resistance source",
        "fire resistance sources",
    ),
}


class Encounter(NamedTuple):
    boss: str
    needs: dict
    why: str


# In the order a raid meets them.
ENCOUNTERS = (
    Encounter(
        "Lucifron",
        {TANKS: 3, CURSE_DISPEL: 2, MAGIC_DISPEL: 2},
        "Lucifron and his two Flamewaker Protectors are held apart; "
        "Lucifron's Curse is decursed and Impending Doom dispelled.",
    ),
    Encounter(
        "Magmadar",
        {TANKS: 1, FEAR_PROTECTION: 1, TRANQUILIZING_SHOT: 1},
        "Panic fears the raid and the tank; Frenzy is removed by Tranquilizing Shot.",
    ),
    Encounter(
        "Gehennas",
        {TANKS: 3, CURSE_DISPEL: 2},
        "Gehennas and his two Flamewakers are held apart; Gehennas' Curse cuts "
        "healing taken and is decursed.",
    ),
    Encounter(
        "Garr",
        {TANKS: 2, BANISH: 2},
        "Garr is held while the Firesworn are banished, and banished again "
        "after each Eruption.",
    ),
    Encounter(
        "Shazzrah",
        {TANKS: 1, CURSE_DISPEL: 2, OFFENSIVE_DISPEL: 1},
        "Shazzrah's Curse is decursed and Magic Grounding purged off him.",
    ),
    Encounter(
        "Baron Geddon",
        {TANKS: 1, MAGIC_DISPEL: 2, FIRE_RESISTANCE: 1},
        "Ignite Mana is dispelled; Inferno burns the melee.",
    ),
    Encounter(
        "Golemagg",
        {TANKS: 3},
        "Golemagg and his two Core Ragers each need a tank.",
    ),
    Encounter(
        "Sulfuron Harbinger",
        {TANKS: 2, INTERRUPT: 4, MAGIC_DISPEL: 2},
        "The four Flamewaker Priests' Dark Mending is interrupted and their "
        "Shadow Word: Pain dispelled.",
    ),
    Encounter(
        "Majordomo Executus",
        {TANKS: 4, CROWD_CONTROL: 4, INTERRUPT: 4},
        "Eight adds: the four Flamewaker Elites are tanked and the four healers "
        "held by crowd control until half are dead, then interrupted.",
    ),
    Encounter(
        "Ragnaros",
        {TANKS: 2, FIRE_RESISTANCE: 1},
        "Wrath of Ragnaros knocks the tank back, so a second tank takes over; "
        "Sons of Flame are burned down by the raid.",
    ),
)


def _have(placed: list) -> dict:
    """How many of each capability the placed raiders bring."""
    have = {name: 0 for name in CAPABILITIES}
    for member in placed:
        if member.get("seat") == TANK_SEAT:
            have[TANKS] += 1
        class_id = member.get("class_id")
        for name, capability in CAPABILITIES.items():
            if class_id in capability.classes:
                have[name] += 1
    return have


def compose(placed: list) -> list:
    """Each boss with what it needs, what the lineup has, and what it lacks.

    `placed` is the lineup's seated raiders, each with `class_id` and `seat`.
    A row is {"boss", "needs", "have", "lacks", "why"}; `lacks` maps a
    capability to how many more it takes, and is empty when the boss is met.
    """
    have = _have(placed)
    out = []
    for encounter in ENCOUNTERS:
        needs = dict(encounter.needs)
        mine = {name: have[name] for name in needs}
        lacks = {
            name: want - mine[name] for name, want in needs.items() if mine[name] < want
        }
        out.append(
            {
                "boss": encounter.boss,
                "needs": needs,
                "have": mine,
                "lacks": lacks,
                "why": encounter.why,
            }
        )
    return out


def _lack_words(lacks: dict) -> str:
    parts = []
    for name, short in lacks.items():
        capability = CAPABILITIES[name]
        parts.append(
            "%d %s" % (short, capability.one if short == 1 else capability.many)
        )
    return ", ".join(parts)


def encounter_line(report: list) -> str:
    """One sentence for the Raid tab: every boss the lineup falls short for."""
    short = [row for row in report if row["lacks"]]
    if not short:
        return "The lineup brings what every Molten Core boss asks for."
    return (
        "Molten Core: "
        + "; ".join(
            "%s lacks %s" % (row["boss"], _lack_words(row["lacks"])) for row in short
        )
        + "."
    )
