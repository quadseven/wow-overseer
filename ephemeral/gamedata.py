"""Small fixed game facts the decree format names by word.

Map names live in the client's Map.dbc, skill names in SkillLine.dbc, and the
boss slots come from the server's instance scripts. List them here once for
lint, the seed compiler, and the judge.
"""

# Instance map names a decree may use in `arrange: instance:`, to map ids.
INSTANCE_MAPS = {
    "Ragefire Chasm": 389,
    "Wailing Caverns": 43,
    "The Deadmines": 36,
    "Shadowfang Keep": 33,
    "Blackfathom Deeps": 48,
    "The Stockade": 34,
    "Gnomeregan": 90,
    "Razorfen Kraul": 47,
    "Scarlet Monastery": 189,
    "Razorfen Downs": 129,
    "Uldaman": 70,
    "Zul'Farrak": 209,
    "Maraudon": 349,
    "The Temple of Atal'Hakkar": 109,
    "Blackrock Depths": 230,
    "Blackrock Spire": 229,
    "Dire Maul": 429,
    "Stratholme": 329,
    "Scholomance": 289,
    "Onyxia's Lair": 249,
    "Molten Core": 409,
    "Zul'Gurub": 309,
    "Blackwing Lair": 469,
    "Ruins of Ahn'Qiraj": 509,
    "Temple of Ahn'Qiraj": 531,
    "Naxxramas": 533,
}

# Typed encounter selectors use the boss slots written by the pinned core.
INSTANCE_ENCOUNTERS = {
    "Magmus": ("Blackrock Depths", (5,)),
    "Majordomo Executus": ("Molten Core", (8,)),
    "Ragnaros": ("Molten Core", (9,)),
    "Any Molten Core boss": ("Molten Core", tuple(range(10))),
    "Any Razorfen Downs boss": ("Razorfen Downs", ()),
}

# Maps whose instance script keeps no boss states in its save. The core still
# sets a bit of `instance.completedEncounters` for each DungeonEncounter.dbc
# credit, so a selector on these maps reads that mask instead of `data`. Which
# bit is which boss lives only in that client file, so these selectors accept
# any bit.
ENCOUNTER_MASK_MAPS = frozenset({"Razorfen Downs"})

# Profession and secondary skill lines a decree may set, to skill ids.
SKILLS = {
    "Alchemy": 171,
    "Blacksmithing": 164,
    "Enchanting": 333,
    "Engineering": 202,
    "Herbalism": 182,
    "Inscription": 773,
    "Jewelcrafting": 755,
    "Leatherworking": 165,
    "Mining": 186,
    "Skinning": 393,
    "Tailoring": 197,
    "Cooking": 185,
    "First Aid": 129,
    "Fishing": 356,
}

# `guild:<Guild>:<role>` roles a decree may name, to the skill that defines them.
ROLE_SKILLS = {
    "alchemist": "Alchemy",
    "blacksmith": "Blacksmithing",
    "enchanter": "Enchanting",
    "engineer": "Engineering",
    "herbalist": "Herbalism",
    "scribe": "Inscription",
    "jeweler": "Jewelcrafting",
    "leatherworker": "Leatherworking",
    "miner": "Mining",
    "skinner": "Skinning",
    "tailor": "Tailoring",
    "cook": "Cooking",
    "fisher": "Fishing",
}

# overseer_command.kind values (the live ENUM). `gm` is listed so lint can name
# it in its refusal: bot sessions are SEC_PLAYER, so a gm command does nothing.
COMMAND_KINDS = (
    "bot chat gm probe give share trade job sell bank auction mail repair buy "
    "bind hearth summon conjure cast guild quest naturalize disenchant"
).split()

# Config keys the world baseline owns; a decree must not set them.
BASELINE_CONFIG_KEYS = {
    "Overseer.RequireClient",
    "Overseer.Raid.RequireHeadClient",
    "Playerbots.MinRandomBots",
    "Playerbots.MaxRandomBots",
    "RealmID",
}

QUEST_STATES = {"incomplete": 3, "complete": 1}  # character_queststatus.status
