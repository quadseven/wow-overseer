"""The class trainer spells a guild member's own AI never casts (#771).

WHY THIS EXISTS. #771 asks that a member save first for "the class spells its
strategy casts". A guild member off the roster is a random playerbot: in a
fight its class AI casts spells BY NAME (mod-playerbots' class actions,
`CastSpellAction(botAI, "frostbolt")` and the like), always at the highest rank
it knows. A spell its AI never names is never cast by it, so a rank of one is
gold spent on nothing: a mage's sixteen portals and teleports, a hunter's eight
tracking spells, a rogue's Pick Lock.

HOW THE TABLE WAS MADE (2026-10-10). Every class trainer spell of this world
(`trainer_spell` of the trainers with Type 0, by class) was named from the
client's Spell.dbc. A spell stays OUT of this table, and so counts as cast,
when:

  * its lower-cased name is a string in its class's action and strategy
    sources of mod-playerbots at commit 79bd428 (src/Ai/Class/<class>/);
  * it is passive (Spell.dbc Attributes & 0x40: Dual Wield, Parry, Plate
    Mail, Mail): it works without a cast;
  * it is a class mount (Summon Warhorse, Summon Charger, Summon Felsteed,
    Dreadsteed): mod-playerbots' `mount` strategy casts the mount spells the
    character knows;
  * it is Ritual of Summoning: the guild jobs cast it for a summoner
    (guildjobs.RITUAL_OF_SUMMONING).

Everything else is below, by class id and name. A spell the world adds later
is not here, so it counts as cast: the safe side is to save for it.

PURE MODULE: a table and one question. No MySQL, no clock.
"""

from __future__ import annotations

NEVER_CAST = {
    2: {  # paladin
        "Divine Intervention": (19752,),
        "Hand of Protection": (1022, 5599, 10278),
        "Hand of Sacrifice": (6940,),
        "Hand of Salvation": (1038,),
        "Turn Evil": (10326,),
    },
    3: {  # hunter
        "Aspect of the Beast": (13161,),
        "Beast Lore": (1462,),
        "Call Stabled Pet": (62757,),
        "Counterattack": (20909, 20910, 27067, 48998, 48999),
        "Eagle Eye": (6197,),
        "Eyes of the Beast": (1002,),
        "Flare": (1543,),
        "Freezing Arrow": (60192,),
        "Frost Trap": (13809,),
        "Master's Call": (53271,),
        "Snake Trap": (34600,),
        "Track Beasts": (1494,),
        "Track Demons": (19878,),
        "Track Dragonkin": (19879,),
        "Track Elementals": (19880,),
        "Track Giants": (19882,),
        "Track Hidden": (19885,),
        "Track Humanoids": (19883,),
        "Track Undead": (19884,),
    },
    4: {  # rogue
        "Deadly Throw": (26679, 48673, 48674),
        "Disarm Trap": (1842,),
        "Hemorrhage": (17347, 17348, 26864, 48660),
        "Pick Lock": (1804,),
        "Pick Pocket": (921,),
        "Shiv": (5938,),
    },
    5: {  # priest
        "Mind Control": (605,),
        "Mind Vision": (2096, 10909),
        "Prayer of Fortitude": (21562, 21564, 25392, 48162),
        "Prayer of Shadow Protection": (27683, 39374, 48170),
        "Prayer of Spirit": (27681, 32999, 48074),
    },
    6: {  # death knight
        "Anti-Magic Shell": (48707,),
        "Path of Frost": (3714,),
        "Raise Ally": (61999,),
        "Rune of Cinderglacier": (53341,),
        "Rune of Lichbane": (53331,),
        "Rune of Razorice": (53343,),
        "Rune of Spellbreaking": (54447,),
        "Rune of Spellshattering": (53342,),
        "Rune of Swordbreaking": (54446,),
        "Rune of Swordshattering": (53323,),
        "Rune of the Fallen Crusader": (53344,),
        "Rune of the Nerubian Carapace": (70164,),
        "Rune of the Stoneskin Gargoyle": (62158,),
    },
    7: {  # shaman
        "Astral Recall": (556,),
        "Call of the Ancestors": (66843,),
        "Call of the Spirits": (66844,),
        "Earth Elemental Totem": (2062,),
        "Far Sight": (6196,),
        "Ghost Wolf": (2645,),
        "Hex": (51514,),
        "Sentry Totem": (6495,),
    },
    8: {  # mage
        "Amplify Magic": (1008, 8455, 10169, 10170, 27130, 33946, 43017),
        "Arcane Brilliance": (23028, 27127, 43002),
        "Arcane Explosion": (
            1449,
            8437,
            8438,
            8439,
            10201,
            10202,
            27080,
            27082,
            42920,
            42921,
        ),
        "Conjure Refreshment": (42955, 42956),
        "Dampen Magic": (604, 8450, 8451, 10173, 10174, 33944, 43015),
        "Portal: Dalaran": (53142,),
        "Portal: Darnassus": (11419,),
        "Portal: Exodar": (32266,),
        "Portal: Ironforge": (11416,),
        "Portal: Orgrimmar": (11417,),
        "Portal: Shattrath": (33691, 35717),
        "Portal: Silvermoon": (32267,),
        "Portal: Stonard": (49361,),
        "Portal: Stormwind": (10059,),
        "Portal: Theramore": (49360,),
        "Portal: Thunder Bluff": (11420,),
        "Portal: Undercity": (11418,),
        "Ritual of Refreshment": (43987, 58659),
        "Slow Fall": (130,),
        "Teleport: Dalaran": (53140,),
        "Teleport: Darnassus": (3565,),
        "Teleport: Exodar": (32271,),
        "Teleport: Ironforge": (3562,),
        "Teleport: Orgrimmar": (3567,),
        "Teleport: Shattrath": (33690, 35715),
        "Teleport: Silvermoon": (32272,),
        "Teleport: Stonard": (49358,),
        "Teleport: Stormwind": (3561,),
        "Teleport: Theramore": (49359,),
        "Teleport: Thunder Bluff": (3566,),
        "Teleport: Undercity": (3563,),
    },
    9: {  # warlock
        "Dark Pact": (18937, 18938, 27265, 59092),
        "Death Coil": (6789, 17925, 17926, 27223, 47859, 47860),
        "Demonic Circle: Summon": (48018,),
        "Demonic Circle: Teleport": (48020,),
        "Detect Invisibility": (132,),
        "Enslave Demon": (1098, 11725, 11726, 61191),
        "Eye of Kilrogg": (126,),
        "Health Funnel": (755, 3698, 3699, 3700, 11693, 11694, 11695, 27259, 47856),
        "Howl of Terror": (5484, 17928),
        "Ritual of Souls": (29893, 58887),
        "Sense Demons": (5500,),
    },
    11: {  # druid
        "Gift of the Wild": (21849, 21850, 26991, 48470),
        "Soothe Animal": (2908, 8955, 9901, 26995),
        "Track Humanoids": (5225,),
    },
}

_NEVER = {
    class_id: frozenset(s for ids in spells.values() for s in ids)
    for class_id, spells in NEVER_CAST.items()
}


def casts(class_id, spell) -> bool:
    """Whether a member of `class_id` casts `spell` (or holds it passively)."""
    try:
        return int(spell) not in _NEVER.get(int(class_id), frozenset())
    except (TypeError, ValueError):
        return True
