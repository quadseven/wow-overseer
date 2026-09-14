"""What the guild still needs before it can raid, and how far along it is.

THE QUESTION THIS ANSWERS, in the operator's own words: "resource goal
tracking for like molten core mats like fire res etc, all the amazing flasks
... get enough for all guild members to have maximum potions and flasks and
repair bots". Nothing on this site could answer any part of it. The Bags tab
says what one character is carrying, the bank plan says what should move
between them, and neither of them knows what a raid asks for, so "are we ready
for Molten Core" had no page at all.

WHY MOLTEN CORE AND NOT NORTHREND. This realm runs a 3.3.5a client with
`MaxPlayerLevel = 60`, which is the operator's deliberate choice and is
reasoned out in full in
`production/oke/manifests/wow-dev/config/worldserver.overrides.conf` rather
than here. The short version that file proves against this realm's own
`creature_template`: the level 60 raid tier IS the endgame, and Onyxia and
Naxxramas in this client are the level 80 rebuilds and are not part of it.

ONE RAID IS MODELLED AND THE PAGE SAYS SO. Molten Core, whole, honestly. The
other three at this cap are listed by name and by map id with nothing claimed
about them, because a view that half-answered four raids would read as having
answered all four, and the half nobody checked is the half somebody farms for.

THE SPLIT THIS MODULE EXISTS TO KEEP. Every number on this page is either
something this realm's database said, or something a community of players
agreed on years ago. They are not the same kind of fact and they are not
recorded the same way:

  MEASURED, from this realm's own tables, and therefore true HERE:
    who is in the guild, and their levels and classes
    every member's profession skills and the value of each
    which craft spells each member has actually learned
    the skill rank each recipe needs, where the realm states it
    whether an item exists here at all, and its name, quality, item level
    the fire resistance every worn item gives
    how many of everything the roster holds, in bags and in the bank
    whether a reagent is sold, dropped, or gathered on this realm

  CONVENTION, agreed by players and stated in no table this service reaches:
    which consumables a Molten Core night calls for
    how many of each per member
    the fire resistance a main tank is usually asked for
    THE REAGENT LIST OF EVERY RECIPE, and how much one cast makes

THE REAGENT WALL, AND IT IS THE SAME ONE bag_economy.py HIT. Reagents live in
`Spell.dbc`, which this deployment does not import: `acore_world.spell_dbc`
carries custom rows only and `skilllineability_dbc` is empty. So no query here
or anywhere can say what a flask is made of. bag_economy.py answered that for
eleven tailoring bags by writing the recipes down and CHECKING each number
back against the realm; this module cannot do the checking half, because it is
not allowed to open the database, so it does something else instead:

  THE PLAN IS WRITTEN IN ITEM NAMES, AND THE REALM RESOLVES THEM. Every
  product and every reagent below is a name, and `item_template` turns it into
  an entry, a quality and an item level at read time. A name this realm spells
  differently, or does not carry at all, resolves to nothing and the goal says
  so by name. A hand-written entry id would have been a silent lie; a
  hand-written name is a claim the realm gets to refuse out loud.

PURE MODULE, same seam as dungeonplan.py and recap.py: rows in, sentences out.
No MySQL, no browser, nothing that writes to the world. Every sentence a
reader sees is composed here so a Python test can read it, which is the rule
`test_recap_tab.ThePageDecidesNothing` keeps and this view is held to rather
than exempted from.

WHAT THIS MODULE DELIBERATELY DOES NOT DO:

  It does not decide who tanks, so it does not decide who needs fire
  resistance. It reports what every member's worn gear actually gives and
  prints the convention beside it.

  It does not say how many crafts raise a skill from one value to another.
  That needs the core's skill-up roll and bag_economy.py already refuses to
  guess it for the same reason.

  It does not follow a reagent further than one craft deep. Stonescale Oil is
  the one reagent here that is itself a recipe, and it is modelled; a herb is
  a herb.

  It does not price anything. What a Black Lotus costs on this realm's auction
  house is a real question and wealth.py is where it would be asked.
"""
from __future__ import annotations

import bank
import professions

# --- the raids at this cap -------------------------------------------------
#
# Map ids, so a reader can check every one of these against the world's own
# `dungeon_access_template` rather than against this file. Only the first is
# modelled, and `modelled` is carried per row so the page can say which is
# which instead of leaving a short list to pass for a complete one.
MOLTEN_CORE = 409

RAIDS = (
    {"map_id": MOLTEN_CORE, "name": "Molten Core", "modelled": True},
    {"map_id": 469, "name": "Blackwing Lair", "modelled": False},
    {"map_id": 309, "name": "Zul'Gurub", "modelled": False},
    {"map_id": 509, "name": "Ruins of Ahn'Qiraj", "modelled": False},
    {"map_id": 531, "name": "Ahn'Qiraj Temple", "modelled": False},
)

# WHY THE TWO EVERYBODY ASSUMES ARE NOT ON THAT LIST. Onyxia's Lair and
# Naxxramas exist in a 3.3.5a client, and both are the level 80 rebuilds: the
# 3.2.2 Onyxia and the Northrend Naxxramas. The original level 60 versions are
# not in this client's data at all, so at a 60 cap they are not content that
# is merely unfinished, they are content that is not there. Stated here
# because it is the single easiest thing on this page to get wrong, and the
# reasoning it comes from is written out against this realm's own
# creature_template in the worldserver override config rather than re-derived.
OUT_OF_TIER = (
    "Onyxia's Lair and Naxxramas are in this client but are its level 80 "
    "rebuilds, so neither is part of the level 60 tier and neither is listed "
    "above. The realm's own worldserver override config proves that against "
    "creature_template rather than from memory.")

# --- the statuses a goal can be in -----------------------------------------
#
# FOUR, AND THE FOURTH IS THE WHOLE POINT. "short" is an evening of farming.
# "unreachable" is nobody on the roster having the profession, which no amount
# of farming changes, and a page that drew the two the same way would put a
# repair bot on a shopping list forever. They are ordered worst first because
# that is the order a reader wants them in.
UNREACHABLE = "unreachable"
BLOCKED = "blocked"
SHORT = "short"
MET = "met"
STATUS_ORDER = (UNREACHABLE, BLOCKED, SHORT, MET)

# --- where a reagent comes from, as this realm answers it -------------------
VENDOR = "vendor"
CREATURE = "creature"
NODE = "node"


class Reagent:
    """One line of a recipe: an item name and how many of it per cast.

    A NAME AND NOT AN ENTRY ID, and that is the whole design. See the module
    docstring: the realm resolves the name, so a name it does not carry is a
    refusal a reader can see rather than a wrong number a reader cannot.
    """

    __slots__ = ("name", "count")

    def __init__(self, name: str, count: int = 1):
        self.name = name
        self.count = count


class Recipe:
    """One craft: the spell that makes a thing, and what it takes.

    `spell` is the craft spell id and is MEASURED ground: `character_spell`
    says who has learned it, and `item_template.spellid_2` or
    `trainer_spell.SpellId` says what skill rank it needs. The spell ids below
    come from the committed standing.json, which tools/gen_standing.py froze
    out of the client's own Spell.dbc and SkillLineAbility.dbc, so they are
    client data rather than anybody's memory.

    `reagents` is the half nothing here can check, and `makes` is stated as
    ONE on purpose. See MAKES_ONE below.
    """

    __slots__ = ("spell", "product", "trade", "reagents")

    def __init__(self, spell: int, product: str, trade: str,
                 reagents: tuple = ()):
        self.spell = spell
        self.product = product
        self.trade = trade
        self.reagents = reagents


# HOW MUCH ONE CAST MAKES IS NOT KNOWN HERE, AND THE FLOOR IS WHAT IS USED.
# The number of items a craft produces is in Spell.dbc like the reagents are,
# so this deployment cannot read it. Community data for the WotLK re-release
# says the level 60 flasks make two per cast; the original 3.3.5a data may
# well say one, and THIS REALM'S answer is not readable from here at all.
#
# So every craft is counted at one per cast, which is the floor rather than a
# guess. The direction of the error is chosen deliberately: over-counting the
# herbs is a wasted afternoon and under-counting them is a raid night that
# stops because the flasks ran out. The footer says which way it leans and by
# how much, so a reader who knows the realm's real yield can halve it.
MAKES_ONE = 1

# --- the recipes, and every reagent line in them ---------------------------
#
# WHERE THESE CAME FROM, SAID ONCE HERE RATHER THAN PER ROW. The spell ids and
# the product names are the committed standing.json's, frozen from the
# client's own Spell.dbc. The REAGENT LINES were read from community data for
# 3.3.5a and are not checked back against this realm, because checking them
# means opening the database and this module is not allowed to. That is a
# weaker claim than bag_economy.py's eleven checked recipes and it is stated
# in the page's own footer rather than left for somebody to discover.
#
# What makes it safe to act on anyway is that every name below is resolved
# against `item_template` at read time. A reagent this realm does not carry
# under that name is reported by name as unresolved, on the goal it belongs
# to, instead of quietly becoming a zero.
#
# THAT CAVEAT HAS NOW BEEN SETTLED FOR SEVEN OF THE EIGHT, FROM OUTSIDE THIS
# MODULE, AND EVERY LINE PROVED CORRECT. The paragraph above is right that
# checking means opening the database and that this module may not - so the
# check was done by the pass that built `raidcraft.py`, which reads the running
# worldserver's own `Spell.dbc` (md5 543b9fe61355b6a77a01714d52fea2e5, matched
# against the pod's `md5sum` on 2026-09-14) rather than any database at all.
# Reagent by reagent and count by count, all seven Alchemy recipes below agree
# with the server: the three flasks, Greater Fire Protection Potion, Major
# Healing Potion, Major Mana Potion and Stonescale Oil. See the block at the
# foot of raidcraft.py for the full list of what was read.
#
# NOTHING HERE IS EDITED ON THE STRENGTH OF THAT, because there was nothing to
# correct, and a note is the honest way to record a check that found nothing
# rather than a change that pretends it found something. The EIGHTH recipe -
# the Engineering Field Repair Bot (22704) - was not checked and stays exactly
# as unverified as the footer already says: nobody on the roster holds
# Engineering at a rank that could cast it, so it was outside that pass's
# scope. `MAKES_ONE` is also untouched and is still the floor it says it is:
# how many items one cast produces is a different Spell.dbc field from the
# reagents, and it was not part of what that pass measured.
ALCHEMY = "alchemy"
ENGINEERING = "engineering"

CRYSTAL_VIAL = "Crystal Vial"
BLACK_LOTUS = "Black Lotus"
DREAMFOIL = "Dreamfoil"
ICECAP = "Icecap"
MOUNTAIN_SILVERSAGE = "Mountain Silversage"
GOLDEN_SANSAM = "Golden Sansam"
GROMSBLOOD = "Gromsblood"
STONESCALE_OIL = "Stonescale Oil"
STONESCALE_EEL = "Stonescale Eel"
ELEMENTAL_FIRE = "Elemental Fire"

FLASK_OF_SUPREME_POWER = "Flask of Supreme Power"
FLASK_OF_DISTILLED_WISDOM = "Flask of Distilled Wisdom"
FLASK_OF_THE_TITANS = "Flask of the Titans"
GREATER_FIRE_PROTECTION = "Greater Fire Protection Potion"
MAJOR_HEALING_POTION = "Major Healing Potion"
MAJOR_MANA_POTION = "Major Mana Potion"
FIELD_REPAIR_BOT = "Field Repair Bot 74A"

RECIPES = (
    Recipe(17637, FLASK_OF_SUPREME_POWER, ALCHEMY, (
        Reagent(DREAMFOIL, 7), Reagent(MOUNTAIN_SILVERSAGE, 3),
        Reagent(BLACK_LOTUS), Reagent(CRYSTAL_VIAL))),
    Recipe(17636, FLASK_OF_DISTILLED_WISDOM, ALCHEMY, (
        Reagent(DREAMFOIL, 7), Reagent(ICECAP, 3),
        Reagent(BLACK_LOTUS), Reagent(CRYSTAL_VIAL))),
    Recipe(17635, FLASK_OF_THE_TITANS, ALCHEMY, (
        Reagent(GROMSBLOOD, 7), Reagent(STONESCALE_OIL, 3),
        Reagent(BLACK_LOTUS), Reagent(CRYSTAL_VIAL))),
    Recipe(17574, GREATER_FIRE_PROTECTION, ALCHEMY, (
        Reagent(ELEMENTAL_FIRE), Reagent(DREAMFOIL),
        Reagent(CRYSTAL_VIAL))),
    Recipe(17556, MAJOR_HEALING_POTION, ALCHEMY, (
        Reagent(GOLDEN_SANSAM, 2), Reagent(MOUNTAIN_SILVERSAGE),
        Reagent(CRYSTAL_VIAL))),
    Recipe(17580, MAJOR_MANA_POTION, ALCHEMY, (
        Reagent(DREAMFOIL, 3), Reagent(ICECAP, 2),
        Reagent(CRYSTAL_VIAL))),
    # THE ONE REAGENT HERE THAT IS ITSELF A CRAFT. Every other reagent above
    # is picked, fished, bought or killed for; this one is an alchemy cast in
    # its own right, and a plan that stopped at "you need three Stonescale
    # Oil" would send somebody to look for a thing nothing drops.
    Recipe(17551, STONESCALE_OIL, ALCHEMY, (Reagent(STONESCALE_EEL),)),
    # UNREACHABLE TODAY, AND LISTED ANYWAY. Nobody on the roster has
    # Engineering, so this craft has no caster. It is written out in full
    # because "what would it take" is a real question even when the answer is
    # "a profession nobody took", and a goal that vanished from the page
    # because it was impossible would read as a goal already met.
    Recipe(22704, FIELD_REPAIR_BOT, ENGINEERING, (
        Reagent("Thorium Bar", 16), Reagent("Fused Wiring", 2),
        Reagent("Delicate Copper Wire"), Reagent("Copper Bar"),
        Reagent("Essence of Fire"), Reagent("Essence of Air"),
        Reagent("Essence of Water"), Reagent("Essence of Earth"),
        Reagent("Living Essence"), Reagent("Essence of Undeath"))),
)

RECIPE_BY_PRODUCT = {recipe.product: recipe for recipe in RECIPES}

# --- what a Molten Core night calls for ------------------------------------
#
# EVERY NUMBER IN THIS BLOCK IS A CONVENTION AND NOT A MEASUREMENT. Molten
# Core gates nobody on consumables: the instance lets a party in at any
# resistance carrying nothing at all, and no table in this realm states a
# requirement, because there is not one. These are what guilds asked their
# raiders for, per member, per night. They are here so the page has something
# to count against, and the page says out loud that they are a starting point
# a reader may move rather than a number the world handed over.
#
# WHICH FLASK IS NOT DECIDED HERE. All three level 60 flasks satisfy the flask
# goal, because which one suits a character depends on their spec, and spec is
# not readable from any table this service has. A guild bank holds whichever
# it has; this counts all three toward the same goal and lists them apart in
# the breakdown so a reader can see the mix.
PER_MEMBER_PER_NIGHT = 1
FIRE_PROTECTION_PER_MEMBER = 5
HEALING_POTIONS_PER_MEMBER = 5
MANA_POTIONS_PER_MEMBER = 5
REPAIR_BOTS_PER_NIGHT = 1

# The fire resistance commonly asked of whoever tanks the last boss, and of
# nobody else. A RANGE and not a number, because the guilds that wrote it down
# did not agree on one, and a single figure here would read as this realm's
# own answer. WHO tanks is not decided on this page, so every member's
# measured total is printed and none of them is called short.
TANK_FIRE_RESISTANCE_LOW = 150
TANK_FIRE_RESISTANCE_HIGH = 200

FIRE_RESISTANCE = "fire resistance"


def plan_item_names() -> tuple:
    """Every item name this page will ask the realm about, products first.

    PUBLIC, AND CALLED BEFORE THE READS, for the same reason
    dungeonplan.map_ids is: the reads bind a list, and a name they do not bind
    comes back with no row and renders as an item this realm does not carry.
    Deriving the list from the plan itself is what stops the two drifting.
    """
    names = []
    for recipe in RECIPES:
        if recipe.product not in names:
            names.append(recipe.product)
        for reagent in recipe.reagents:
            if reagent.name not in names:
                names.append(reagent.name)
    return tuple(names)


def craft_spells() -> tuple:
    """Every craft spell id, so the roster's known spells can be bound."""
    return tuple(recipe.spell for recipe in RECIPES)


def _a(word: str) -> str:
    """"a flask" or "an engineering craft".

    A HELPER FOR ONE LETTER, and it is here because the trade names are DATA
    rather than literals: the sentences below are assembled from
    professions.skill_id's own vocabulary, and "a engineering craft" is what
    came out the first time one of them was dropped into a sentence written
    around "alchemy". A page that is careful about which numbers it claims and
    sloppy about its own English reads as careless about both.
    """
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def casts_for(short: int) -> int:
    """How many casts a shortfall of `short` items is.

    ONE LINE OF ARITHMETIC WITH A CONSTANT IN IT, and it is a function so that
    MAKES_ONE is load-bearing rather than a comment. The day somebody learns
    what this realm's flasks actually yield, this is the one place that
    changes, and every total on the page follows it.
    """
    if short <= 0:
        return 0
    return -(-short // MAKES_ONE)


def _count(count: int, one: str, many: str) -> str:
    """"1 flask" or "7 flasks", counted rather than suffixed.

    A HELPER FOR THE REASON dungeonplan._dungeon_count IS ONE. Every number on
    this page comes from a list the world handed over, so every one of them
    can be one: a roster of one, a guild of one, a single reagent short. "1
    flasks short" is the sentence that appears on the day something has gone
    wrong, which is the day the page is being read closely.
    """
    return "%d %s" % (count, one if count == 1 else many)


def _members(char_rows: list, roster: list) -> list:
    """The roster, with the level and class the realm gave each of them.

    A NAME WITH NO ROW IS STILL A MEMBER. A guild member who has never logged
    in on this realm, or whose row failed a degraded read, is somebody the
    raid still needs consumables for, and dropping them would quietly lower
    every total on the page. Their level reads as unknown and says so.
    """
    by_name = {row["name"]: row for row in char_rows if row.get("name")}
    out = []
    for name in roster:
        row = by_name.get(name) or {}
        out.append({
            "name": name,
            "level": int(row["level"]) if row.get("level") is not None else None,
            "class": row.get("class"),
            "known": bool(row),
        })
    return out


def roster_from_guild(guild_rows: list, family: list) -> dict:
    """Who this page counts for, and which list that came from.

    THE GOAL IS PER MEMBER OF THE GUILD AND THERE IS NO GUILD YET, which is
    not a reason to hardcode five. `guild_rows` are the members of whichever
    guild the family are actually in, and when there is one they are the
    answer: a guild of forty is forty flasks, and nothing on this page should
    have to be edited on the day that happens.

    THE FAMILY ARE THE FALLBACK AND THE PAGE SAYS SO, rather than letting a
    roster of five pass for a guild roster. Two states are kept apart that a
    single list would collapse: counting a real guild, and counting the family
    because no guild exists to count.
    """
    names = sorted({row["name"] for row in guild_rows if row.get("name")})
    guilds = sorted({row["guild_name"] for row in guild_rows
                     if row.get("guild_name")})
    if names and len(guilds) == 1:
        return {"names": names, "guild": guilds[0], "from_guild": True,
                "split": False}
    if names and len(guilds) > 1:
        # THE FAMILY IN TWO GUILDS IS NOT A GUILD ROSTER. Counting the union
        # would invent a raid group nobody is in, and picking one would be
        # this page choosing which guild is the real one. It counts the family
        # and says what it saw.
        return {"names": sorted(family), "guild": "", "from_guild": False,
                "split": True}
    return {"names": sorted(family), "guild": "", "from_guild": False,
            "split": False}


def _roster_line(roster: dict, members: list) -> str:
    """Who is being counted, and where that list came from.

    Every total below is this number times a per-member convention, so a
    reader who disagrees with a total has to be able to see what it was
    multiplied by.
    """
    who = _count(len(members), "member", "members")
    if not members:
        return ("nothing here knows who would be raiding, so there is nobody "
                "to count consumables for")
    if roster.get("from_guild"):
        return "counting %s of %s" % (who, roster["guild"])
    if roster.get("split"):
        return ("the family are in more than one guild, so this counts the "
                "family itself: %s. A guild roster would replace it." % who)
    return ("there is no guild yet, so this counts the family itself: %s. "
            "Every total below is per member, so a guild replaces this number "
            "without anything here being rewritten." % who)


def _items(item_rows: list) -> dict:
    """item name -> the one row this realm has for it.

    A DUPLICATE NAME IS RECORDED RATHER THAN RESOLVED. Two rows under one name
    means this page cannot say which entry a holding is, and quietly keeping
    the first would make every count on that item unprovable. `twin` is what
    the goal prints when it happens.
    """
    out: dict = {}
    for row in item_rows:
        name = row.get("item_name")
        if not name:
            continue
        seated = out.get(name)
        if seated is None:
            out[name] = {
                "name": name,
                "entry": int(row["entry"]),
                "quality": row.get("quality"),
                "item_level": row.get("item_level"),
                "twin": False,
            }
            continue
        seated["twin"] = True
    return out


def _placed(holding_rows: list, roster: list) -> tuple:
    """What the roster holds, keyed (member, item), carried and banked apart.

    THE PLACEMENT IS bank.py's AND NOT THIS MODULE'S, and that is reuse rather
    than tidiness. Working out which `character_inventory` slot is a worn bag,
    which is a bank bag, which is the backpack and which is the paper doll is
    a two-pass job over container guids that bank.py already does, correctly,
    for the Bags tab. A second copy here would be a second opinion about where
    a stack is, and the two would disagree about the same stack on the same
    evening the first time either was touched.

    TWO DICTIONARIES AND NOT ONE WITH A FLAG. "Do we have enough" and "can we
    bring it" are different questions and a raid is the second one: a stack in
    a bank in a capital is not in the raid. The banked total is a SUBSET of
    the held total rather than a sibling of it, so a caller cannot accidentally
    add the two together.

    Anything WORN is excluded, because bank.py places a paper-doll slot as
    neither carried nor banked. That is right here too: a flask on a paper
    doll is not a thing anybody has.
    """
    members = bank.members_from_rows(holding_rows, sorted(roster))
    held: dict = {}
    banked: dict = {}
    for member in members:
        for holding in member.carried:
            key = (member.name, holding.item.name)
            held[key] = held.get(key, 0) + holding.count
        for holding in member.banked:
            key = (member.name, holding.item.name)
            held[key] = held.get(key, 0) + holding.count
            banked[key] = banked.get(key, 0) + holding.count
    return held, banked


def _skills(skill_rows: list) -> dict:
    """name -> {skill id: value}, from character_skills and nothing else.

    The world's answer to what somebody can actually do, as opposed to
    professions.ROSTER, which is the family's answer to what they MEANT to do.
    craftpleas.py confused the two and answered "Og know tailoring" over a
    character with herbalism, which is the reason these are kept apart here.
    """
    out: dict = {}
    for row in skill_rows:
        name = row.get("name")
        if not name:
            continue
        out.setdefault(name, {})[int(row["skill"])] = int(row.get("value") or 0)
    return out


def _known(spell_rows: list) -> dict:
    """name -> the set of craft spells that character has actually learned."""
    out: dict = {}
    for row in spell_rows:
        name = row.get("name")
        if not name:
            continue
        out.setdefault(name, set()).add(int(row["spell"]))
    return out


def _ranks(recipe_rows: list, trainer_rows: list) -> dict:
    """craft spell -> the skill rank THIS REALM says it needs, or absent.

    MEASURED, AND FROM TWO PLACES BECAUSE RECIPES ARRIVE TWO WAYS. A recipe
    taught by an item has its rank on that item's own `item_template` row
    (`RequiredSkillRank`, beside the `spellid_2` that teaches the craft), and
    bag_economy.py proved that join against this realm. A recipe taught by a
    trainer has it in `trainer_spell.ReqSkillRank` instead. A craft in neither
    is a craft this realm does not state a rank for, and that is an absent key
    rather than a zero: zero would read as "anybody can make it".
    """
    out: dict = {}
    for row in trainer_rows:
        spell = row.get("spell")
        if spell is None:
            continue
        out[int(spell)] = int(row.get("skill_rank") or 0)
    for row in recipe_rows:
        spell = row.get("teaches")
        if spell is None:
            continue
        # The item wins over the trainer row: it is the row that names the
        # rank beside the recipe a reader would actually go and find.
        out[int(spell)] = int(row.get("skill_rank") or 0)
    return out


def _sources(vendor_rows: list, creature_rows: list, object_rows: list) -> dict:
    """item entry -> how this realm says that item is come by.

    THE MEASURED HALF OF "A REAGENT WITH NO KNOWN SOURCE", and the one that
    turns this page into a farm plan. A herb is a `gameobject_loot_template`
    row because a herb node is a game object; a vial is an `npc_vendor` row; an
    elemental's mote is a `creature_loot_template` row. A reagent in none of
    the three is not a reagent that cannot be got, it is a reagent NOTHING
    THIS PAGE READS accounts for, and the two are said differently.
    """
    out: dict = {}
    for row in object_rows:
        out.setdefault(int(row["item"]), []).append(NODE)
    for row in creature_rows:
        out.setdefault(int(row["item"]), []).append(CREATURE)
    for row in vendor_rows:
        out.setdefault(int(row["item"]), []).append(VENDOR)
    return out


def _source_line(where: list) -> str:
    """How a reagent is come by, in this realm's own terms."""
    if not where:
        return ("nothing this page reads sells it, drops it or grows it on "
                "this realm")
    said = []
    if NODE in where:
        said.append("gathered from a node")
    if CREATURE in where:
        said.append("dropped by a creature")
    if VENDOR in where:
        said.append("sold by a vendor")
    return ", ".join(said)


def _fire_resistance(worn_rows: list, roster: set) -> dict:
    """name -> the fire resistance that character's worn gear actually gives.

    THE ONE NUMBER ON THE RESISTANCE GOAL THAT IS MEASURED. `item_template`
    carries `fire_res` per item and the paper doll read already selects it, so
    this is a sum over rows rather than an estimate. It counts WORN items
    only, which is what a resistance total means, and it does not count
    enchantments or buffs: an enchantment lives in `item_instance.enchantments`
    as an id into a table this sum does not read, and a buff is not a fact
    about gear at all. The footer says both.
    """
    out = {name: 0 for name in roster}
    for row in worn_rows:
        name = row.get("name")
        if name not in out:
            continue
        out[name] += int(row.get("fire_res") or 0)
    return out


def _resistance_member_line(who: str, value: int) -> str:
    """One character's measured fire resistance, with no verdict on it."""
    if not value:
        return "%s: nothing worn gives any fire resistance" % who
    return "%s: %d from worn gear" % (who, value)


def _resistance_line(values: dict, members: list) -> str:
    """The fire resistance the roster is actually wearing, counted.

    NOBODY IS CALLED SHORT HERE, because being short depends on tanking and
    this page does not decide who tanks. It counts who has any at all, which
    is a fact, and prints the convention beside it as a convention.
    """
    if not members:
        return "there is nobody to measure"
    wearing = [m["name"] for m in members if values.get(m["name"], 0) > 0]
    if not wearing:
        return ("not one of the %d is wearing anything with fire resistance "
                "on it" % len(members))
    if len(wearing) == len(members):
        best = max(values.get(m["name"], 0) for m in members)
        return ("all %d are wearing some, the highest %d"
                % (len(members), best))
    return ("%d of the %d %s wearing some: %s"
            % (len(wearing), len(members),
               "is" if len(wearing) == 1 else "are",
               ", ".join(sorted(wearing))))


def _resistance_convention() -> str:
    """What the number beside the measurement is, and what it is not."""
    return ("Molten Core admits a party at any resistance and this realm's "
            "tables state no requirement, because there is not one. What "
            "guilds asked for was %d to %d unbuffed on whoever tanks the last "
            "boss and nothing at all on everybody else. Who tanks is not "
            "decided on this page, so nobody above is called short."
            % (TANK_FIRE_RESISTANCE_LOW, TANK_FIRE_RESISTANCE_HIGH))




def _holders(trade: str, members: list, skills: dict) -> list:
    """Who on this roster actually holds a trade, by the world's own answer.

    `character_skills` and not professions.ROSTER. The two are different
    questions and craftpleas.py answering the second while asking the first is
    how "Og know tailoring" reached party chat over a character with
    herbalism. The roster's assignment is a plan; this is what is true.
    """
    skill = professions.skill_id(trade)
    return sorted(m["name"] for m in members
                  if skills.get(m["name"], {}).get(skill))


def _recipe_blockers(recipe: Recipe, members: list, skills: dict, known: dict,
                     ranks: dict, items: dict, sources: dict,
                     skills_read: bool = True) -> tuple:
    """Everything standing between this roster and one more of this item.

    THE MOST USEFUL OUTPUT ON THE PAGE, because a blocked reason turns into an
    errand and a shortfall is only a number. Returned worst first, with the
    status the reasons add up to.

    THE UNREACHABLE CASE IS NOT A SHORTFALL. A trade nobody on the roster holds
    is not something the roster can farm its way out of: somebody has to take a
    profession, or bring one. It returns early because every check below it is
    a question about a crafter who does not exist, and answering those would
    bury the one reason that matters under four that do not apply.

    `skills_read` IS THE GUARD ON THAT CLAIM AND IT IS TESTED FIRST, before
    the trade is looked at, which is why it is described here before the check
    it guards. It is not defensive programming. Every read behind this page is guarded against a missing
    table and a missing column, exactly as the recap's and the dungeon plan's
    are, and a guard that fires hands back an EMPTY LIST. An empty
    `character_skills` read looks identical to a roster that has taken no
    professions, and calling that "nobody here has alchemy, somebody must take
    the trade" would be this page turning its own failed read into an errand
    for a person. Unknown is a different answer from none, and it is BLOCKED
    rather than unreachable: the goal may be perfectly reachable and this page
    cannot presently tell.

    TWO KINDS OF REASON COME BACK, AND ONLY ONE OF THEM DECIDES THE STATUS.
    A BLOCKER is something this page knows stops the craft today: nobody has
    learned the recipe, the skill is under the rank this realm states, a
    reagent this realm does not carry. An UNKNOWN is something this page
    cannot answer: no rank is stated anywhere, or no table it reads accounts
    for where a reagent comes from. Folding the second into the first marked a
    goal "blocked" over a flask a 300 alchemist could have made that evening,
    purely because the realm states no rank for it, which is the page reporting
    its own blind spot as the guild's problem. Both are printed; only blockers
    move the status.
    """
    blocked = []
    unknown = []
    if not skills_read:
        return BLOCKED, (
            "this realm's character_skills read came back empty, so who holds "
            "%s cannot be answered here and nothing below about skill is "
            "reliable" % recipe.trade,), ()
    holders = _holders(recipe.trade, members, skills)
    if not holders:
        return UNREACHABLE, (
            "nobody on this roster has %s, and %s is %s craft: no amount of "
            "gathering finishes this one, somebody has to take the trade"
            % (recipe.trade, recipe.product, _a(recipe.trade)),), ()

    learned = [name for name in holders if recipe.spell in known.get(name, ())]
    if not learned:
        blocked.append(
            "nobody has learned this recipe yet: %s is held by %s, and the "
            "craft itself is on nobody's spell list"
            % (recipe.trade, ", ".join(holders)))

    rank = ranks.get(recipe.spell)
    skill = professions.skill_id(recipe.trade)
    if rank is None:
        unknown.append(
            "this realm states no %s rank for this recipe, in item_template "
            "or in trainer_spell, so whether anybody is high enough is not a "
            "question this page can answer" % recipe.trade)
    else:
        best = max(skills.get(name, {}).get(skill, 0) for name in holders)
        if best < rank:
            blocked.append(
                "the recipe needs %s %d and the best on this roster is %d"
                % (recipe.trade, rank, best))

    for reagent in recipe.reagents:
        row = items.get(reagent.name)
        if row is None:
            blocked.append(
                "this realm carries no item called %s, so that reagent is "
                "missing from the count below rather than zero" % reagent.name)
            continue
        if row["twin"]:
            blocked.append(
                "this realm carries more than one item called %s, so a "
                "holding of it cannot be matched to one entry" % reagent.name)
        if not sources.get(row["entry"]) and reagent.name not in RECIPE_BY_PRODUCT:
            # A REAGENT THAT IS ITSELF A CRAFT IS NOT SOURCELESS, and the
            # first version said it was: Stonescale Oil is in no vendor, loot
            # or node table on this realm because nothing drops it, which is
            # exactly what being made rather than found looks like. Reported
            # as a blocker it sent a reader looking for a thing that cannot be
            # found. Its own recipe is printed on the reagent row instead.
            unknown.append(
                "nothing this page reads sells, drops or grows %s on this "
                "realm, so where it comes from is unanswered here"
                % reagent.name)

    return (BLOCKED if blocked else MET), tuple(blocked), tuple(unknown)


def _reagent_row(reagent: Reagent, casts: int, items: dict, sources: dict,
                 totals: dict, depth: int) -> dict:
    """One reagent line, counted against what the roster already holds.

    ONE CRAFT DEEP AND THE ROW SAYS SO WHEN IT STOPS. A reagent that is itself
    a recipe carries that recipe inline, because a plan that said "three
    Stonescale Oil" and stopped would send somebody to look for a thing
    nothing on this realm drops. It does not recurse past that: `depth` is
    what keeps a cycle in the recipe table from becoming a hang, and the one
    reagent here that needs the second level is the only one that has it.
    """
    row = items.get(reagent.name)
    wanted = reagent.count * casts
    have = totals.get(reagent.name, 0)
    entry = row["entry"] if row else 0
    made_by = RECIPE_BY_PRODUCT.get(reagent.name)
    short = max(wanted - have, 0)
    out = {
        "name": reagent.name,
        "entry": entry,
        "per_cast": reagent.count,
        "need": wanted,
        "held": have,
        "short": short,
        "known_here": bool(row),
        "source": _reagent_source(reagent.name, row, sources.get(entry, [])),
        "line": _reagent_line(reagent.name, wanted, have, bool(row)),
        "made": [],
        "made_line": "",
    }
    if made_by is not None and depth > 0:
        out["made_line"] = _made_line(reagent.name, short, made_by.trade)
        out["made"] = [_reagent_row(sub, short, items, sources, totals,
                                    depth - 1)
                       for sub in made_by.reagents]
    return out


def _reagent_source(name: str, row, where: list) -> str:
    """How this reagent is come by, with "made" kept apart from "unknown".

    THE TWO LOOK IDENTICAL IN THE TABLES and they are opposite answers.
    Stonescale Oil appears in no vendor, loot or node row on this realm for
    the same reason a flask does not: nothing drops it, somebody makes it.
    Reported as "no known source" it sends a reader hunting for something that
    cannot be hunted.
    """
    if row is None:
        return "this realm carries no item under that name"
    if name in RECIPE_BY_PRODUCT and not where:
        return "made rather than found, by %s" % RECIPE_BY_PRODUCT[name].trade
    return _source_line(where)


def _made_line(name: str, short: int, trade: str) -> str:
    """Why a reagent carries a recipe of its own, said as English at any count.

    IT IS A SENTENCE BUILT AROUND A NUMBER, which is the shape that reads
    correctly at twelve and wrongly at one unless both are written out. The
    first version said "the 1 of them short are themselves an alchemy craft",
    and the page it appears on is one whose whole argument is that it is
    careful.
    """
    if short == 1:
        return ("%s is made rather than found: the one that is short is "
                "itself %s craft, and this is what it takes"
                % (name, _a(trade)))
    return ("%s is made rather than found: the %d that are short are each %s "
            "craft, and this is what they take" % (name, short, _a(trade)))


def _reagent_line(name: str, wanted: int, have: int, known_here: bool) -> str:
    """One reagent, counted against what is already in the bags and the bank."""
    if not known_here:
        return ("%s: this realm carries no item under that name, so nothing "
                "here can count it" % name)
    if not wanted:
        return "%s: none needed, %d held" % (name, have)
    if have >= wanted:
        return "%s: %d needed, %d already held" % (name, wanted, have)
    return ("%s: %d needed, %d held, %d short"
            % (name, wanted, have, wanted - have))


def _recipe_card(recipe: Recipe, casts: int, members: list, skills: dict,
                 known: dict, ranks: dict, items: dict, sources: dict,
                 totals: dict, skills_read: bool = True) -> dict:
    """One way of making up a shortfall, and everything in the way of it.

    A CARD PER RECIPE AND NOT ONE PER GOAL, because three flasks satisfy one
    flask goal and they do not share a recipe. A single reagent list under a
    goal like that would be one of the three presented as the answer, and a
    reader would farm to it.
    """
    status, blocked, unknown = _recipe_blockers(recipe, members, skills, known,
                                                ranks, items, sources,
                                                skills_read)
    rank = ranks.get(recipe.spell)
    return {
        "product": recipe.product,
        "trade": recipe.trade,
        "spell": recipe.spell,
        "status": status,
        "blocked": list(blocked),
        "unknown": list(unknown),
        "line": _cast_line(recipe, casts),
        "rank_line": _rank_line(recipe, rank),
        "who_line": _who_line(recipe, members, skills, known),
        "reagents": [_reagent_row(reagent, casts, items, sources, totals, 1)
                     for reagent in recipe.reagents],
    }


def _cast_line(recipe: Recipe, casts: int) -> str:
    """What making the whole shortfall as this one recipe would cost.

    THE YIELD ASSUMPTION IS SAID WHERE IT IS USED and not only in the footer.
    A reader who knows this realm's flasks make two per cast needs to see
    which number to halve, on the row it is on.
    """
    if not casts:
        return ("nothing is short, so this is what one more would take"
                if recipe.reagents else "nothing is short")
    return ("made entirely as %s that is %s, counting one per cast because "
            "how much a cast makes is not readable on this deployment"
            % (recipe.product, _count(casts, "cast", "casts")))


def _rank_line(recipe: Recipe, rank) -> str:
    """What skill this realm says the recipe needs, or that it says nothing.

    An absent rank is NOT zero and the sentence keeps them apart: zero would
    read as "anybody can make it", which is the opposite of what a missing
    row means.
    """
    if rank is None:
        return ("this realm states no %s rank for it, in item_template or in "
                "trainer_spell" % recipe.trade)
    return "this realm asks for %s %d" % (recipe.trade, rank)


def _who_line(recipe: Recipe, members: list, skills: dict,
              known: dict) -> str:
    """Who could cast this today, by the world's own answer rather than a plan.

    NAMED RATHER THAN COUNTED when somebody can, because the next thing a
    reader does with this page is go and ask that character. Counted by nobody
    when nobody can: the blocked reason above already says why, and a second
    sentence saying "0 of 5" would be the same fact drawn twice.
    """
    holders = _holders(recipe.trade, members, skills)
    if not holders:
        return "nobody here holds %s at all" % recipe.trade
    learned = [name for name in holders if recipe.spell in known.get(name, ())]
    if learned:
        return "already known by %s" % ", ".join(learned)
    if len(holders) == 1:
        return ("%s holds %s and has not learned this craft"
                % (holders[0], recipe.trade))
    return ("%s is held by %s, and none of them has learned this craft"
            % (recipe.trade, ", ".join(holders)))


def _supply_members(members: list, products: tuple, per_member: int,
                    held: dict, banked: dict) -> list:
    """What each member holds toward this goal, against what it asks of them.

    PER MEMBER AND NOT JUST A TOTAL, because a bank with forty flasks in it
    and thirty-nine raiders carrying none is not a guild that is ready, and
    one number cannot tell those two apart.
    """
    out = []
    for member in members:
        have = sum(held.get((member["name"], product), 0)
                   for product in products)
        in_bank = sum(banked.get((member["name"], product), 0)
                      for product in products)
        out.append({
            "who": member["name"],
            "level": member["level"],
            "need": per_member,
            "held": have,
            "banked": in_bank,
            "short": max(per_member - have, 0),
            "line": _supply_member_line(member["name"], per_member, have,
                                        in_bank),
        })
    return out


def _supply_member_line(who: str, need: int, have: int, in_bank: int) -> str:
    """One member's share of a supply goal, and where their share is sitting.

    THE BANK HALF IS NOT DECORATION. A stack sitting in a bank in a capital is
    not in the raid, so a member who "has" five and banked all five has a
    different evening ahead from one carrying them, and the sentence says
    which it is.
    """
    if have >= need and in_bank:
        return ("%s holds %d of the %d asked for, %d of them in the bank"
                % (who, have, need, in_bank))
    if have >= need:
        return "%s holds %d of the %d asked for" % (who, have, need)
    if in_bank:
        return ("%s holds %d of the %d asked for and is %d short, %d of what "
                "they do hold in the bank"
                % (who, have, need, need - have, in_bank))
    return ("%s holds %d of the %d asked for and is %d short"
            % (who, have, need, need - have))


def _product_rows(products: tuple, items: dict, held: dict) -> list:
    """The items that satisfy this goal, counted across the whole roster.

    THREE FLASKS SATISFY ONE FLASK GOAL and this breakdown is what keeps that
    honest. The goal counts them together because which flask suits whom
    depends on a spec no table here carries; these rows say what the mix
    actually is, so a reader can make that choice with the numbers in front
    of them.
    """
    rows = []
    for product in products:
        row = items.get(product)
        total = sum(count for (_, name), count in held.items()
                    if name == product)
        rows.append({
            "name": product,
            "entry": row["entry"] if row else 0,
            "quality": row["quality"] if row else None,
            "item_level": row["item_level"] if row else None,
            "known_here": bool(row),
            "held": total,
            "line": _product_line(product, total, bool(row)),
        })
    return rows


def _product_line(product: str, total: int, known_here: bool) -> str:
    """One product and how many of it the roster holds between them."""
    if not known_here:
        return "%s: this realm carries no item under that name" % product
    if not total:
        return "%s: none held" % product
    return "%s: %d held" % (product, total)


def _supply_line(name: str, need: int, have: int, status: str) -> str:
    """The headline on a supply goal: the count first, then what it means.

    "BLOCKED" AND "SHORT" ARE DIFFERENT SENTENCES over the same arithmetic. A
    goal forty short and craftable tonight and a goal forty short because
    nobody knows the recipe are the same number and completely different
    evenings, and the number alone cannot tell them apart.
    """
    if status == UNREACHABLE:
        return ("%s: nobody on this roster can make it, so the %d it asks for "
                "is not a farming problem" % (name, need))
    if have >= need:
        return "%s: %d needed, %d held" % (name, need, have)
    return "%s: %d needed, %d held, %d short" % (name, need, have, need - have)


def _need_line(per_member: int, members: int, need: int) -> str:
    """Where a total came from, said as the multiplication it is.

    A TOTAL WITH NO WORKING IS A NUMBER NOBODY CAN DISAGREE WITH, and this one
    is a convention multiplied by a roster. Both halves are printed, so a
    reader who wants three flasks each instead of one can redo it rather than
    taking this page's word for the product.
    """
    if not members:
        return "there is nobody to count for, so the total is nothing"
    return ("%d per member, times %s, is %d. The per-member number is a "
            "convention rather than anything this realm states."
            % (per_member, _count(members, "member", "members"), need))


def _goal_status(cards: list, short: int) -> str:
    """What a goal's state is, once every way of making it has been read.

    THE LADDER, AND THE ORDER OF IT IS THE FINDING.

    HAVING ENOUGH IS CHECKED FIRST, AND IT HAS TO BE. Every rung below this
    one is about MAKING the thing, and nobody has to make one when the roster
    already holds what the goal asks for. The first version asked "can anybody
    make this" first, so a guild that had already bought a repair bot would
    have been told "nobody on this roster can make it, so the 1 it asks for is
    not a farming problem" over a goal that was finished. That sentence is
    true about the craft and useless about the goal, and a reader would have
    gone looking for an Engineer they did not need.

    UNREACHABLE THEN, AND IT OUTRANKS BLOCKED, because a trade nobody holds is
    not something more farming fixes. BLOCKED when EVERY way of making it is
    blocked, and merely SHORT when one of them is clear: a goal with three
    recipes under it is only blocked if all three are.
    """
    if not short:
        return MET
    if cards and all(card["status"] == UNREACHABLE for card in cards):
        return UNREACHABLE
    if cards and all(card["status"] != MET for card in cards):
        return BLOCKED
    return SHORT


def _chips(status: str, need: int, have: int, blockers: int) -> list:
    """The three or four words that survive a collapsed row on a phone.

    `tone` is a ROLE NAME and never a colour, exactly as dungeonplan's are:
    the stylesheet decides what "no" looks like on each of the two grounds
    this page is drawn on, and a module that chose a colour would be choosing
    it for only one of them.
    """
    out = []
    if status == UNREACHABLE:
        out.append({"text": "no one can make it", "tone": "no"})
    elif status == MET:
        out.append({"text": "enough", "tone": "up"})
    elif status == BLOCKED:
        out.append({"text": "blocked", "tone": "no"})
    else:
        out.append({"text": "short", "tone": "unsure"})
    if need:
        out.append({"text": "%d needed" % need, "tone": ""})
    out.append({"text": "%d held" % have, "tone": "up" if have else ""})
    if blockers:
        out.append({"text": _count(blockers, "blocker", "blockers"),
                    "tone": "no"})
    return out


def _recipes_line(products: tuple) -> str:
    """Why there is more than one shopping list under one goal.

    THE MIX IS THE READER'S CHOICE AND THE PAGE SAYS SO. Each list below
    prices the WHOLE shortfall as one recipe, so they are alternatives rather
    than a sum, and a reader adding them together would farm three times what
    is needed.
    """
    if len(products) == 1:
        return ""
    return ("%s satisfy this goal and they do not share a recipe. Each list "
            "below is the whole shortfall made as that one, so they are "
            "alternatives and not a sum; any mix lands between them."
            % _count(len(products), "item", "items"))


def _supply_goal(key: str, name: str, products: tuple, per_member: int,
                 members: list, items: dict, held: dict, banked: dict,
                 skills: dict, known: dict, ranks: dict, sources: dict,
                 skills_read: bool = True) -> dict:
    """One "enough of this for everybody" goal, whole.

    `products` is every item that satisfies it, and each gets its own recipe
    card: the goal is the count, and how the count is made up is a separate
    question with as many answers as there are recipes.
    """
    need = per_member * len(members)
    have = sum(count for (_, item), count in held.items() if item in products)
    short = max(need - have, 0)
    totals = _totals(held)
    casts = casts_for(short)
    cards = [_recipe_card(RECIPE_BY_PRODUCT[product], casts, members, skills,
                          known, ranks, items, sources, totals, skills_read)
             for product in products]
    status = _goal_status(cards, short)
    blockers = sum(len(card["blocked"]) for card in cards)
    return {
        "key": key,
        "name": name,
        "kind": "supply",
        "status": status,
        "need": need,
        "held": have,
        "short": short,
        "per_member": per_member,
        "line": _supply_line(name, need, have, status),
        "need_line": _need_line(per_member, len(members), need),
        "recipes_line": _recipes_line(products),
        "members": _supply_members(members, products, per_member, held,
                                   banked),
        "products": _product_rows(products, items, held),
        "recipes": cards,
        "chips": _chips(status, need, have, blockers),
    }


def _totals(held: dict) -> dict:
    """item -> how many the whole roster holds, bags and bank together."""
    out: dict = {}
    for (_, name), count in held.items():
        out[name] = out.get(name, 0) + count
    return out


def _repair_goal(members: list, items: dict, held: dict, banked: dict,
                 skills: dict, known: dict, ranks: dict, sources: dict,
                 skills_read: bool = True) -> dict:
    """The repair bot, which is a goal this roster cannot finish.

    NOT PER MEMBER. One bot serves whoever stands near it, so the number is
    per raid night and not per person; per member it would have asked for
    forty of a thing one of which is plenty.

    IT IS ON THE PAGE BECAUSE THE OPERATOR ASKED FOR IT, and the answer is not
    "not yet". Nobody on this roster has Engineering, so this is the goal that
    proves the page can tell an unfinished thing from an impossible one. A
    goal that disappeared because it was impossible would read exactly like a
    goal already met.
    """
    recipe = RECIPE_BY_PRODUCT[FIELD_REPAIR_BOT]
    have = sum(count for (_, item), count in held.items()
               if item == FIELD_REPAIR_BOT)
    need = REPAIR_BOTS_PER_NIGHT
    short = max(need - have, 0)
    card = _recipe_card(recipe, casts_for(short), members, skills, known,
                        ranks, items, sources, _totals(held), skills_read)
    status = _goal_status([card], short)
    return {
        "key": "repair",
        "name": "A repair bot for the raid",
        "kind": "supply",
        "status": status,
        "need": need,
        "held": have,
        "short": short,
        "per_member": 0,
        "line": _supply_line(recipe.product, need, have, status),
        "need_line": ("one per raid night rather than one each: a bot serves "
                      "whoever stands near it. That it is one and not one "
                      "apiece is a convention like every other count here."),
        "recipes_line": "",
        "members": [],
        "products": _product_rows((FIELD_REPAIR_BOT,), items, held),
        "recipes": [card],
        "chips": _chips(status, need, have, len(card["blocked"])),
    }


def _resistance_goal(members: list, worn_rows: list, roster: set) -> dict:
    """Fire resistance, measured on the gear and compared to nothing.

    THE ONE GOAL WITH NO SHORTFALL ON IT, and that is the honest shape rather
    than a gap somebody should fill in. Every other goal here counts against a
    target because a consumable is a thing you either have or do not.
    Resistance has a target only once somebody has decided who tanks, and
    nothing on this page decides that, so it reports the measurement and
    prints the convention beside it as a convention.
    """
    values = _fire_resistance(worn_rows, roster)
    return {
        "key": "fireres",
        "name": "Fire resistance on worn gear",
        "kind": "measure",
        "status": MET,
        "need": 0,
        "held": 0,
        "short": 0,
        "per_member": 0,
        "line": _resistance_line(values, members),
        "need_line": _resistance_convention(),
        "recipes_line": "",
        "members": [{"who": m["name"], "level": m["level"],
                     "need": 0, "held": values.get(m["name"], 0),
                     "banked": 0, "short": 0,
                     "line": _resistance_member_line(
                         m["name"], values.get(m["name"], 0))}
                    for m in members],
        "products": [],
        "recipes": [],
        "chips": [{"text": FIRE_RESISTANCE, "tone": ""},
                  {"text": "measured, not scored", "tone": "unsure"}],
    }


def _headline(goals: list, members: list) -> str:
    """The one line at the top. Counts, never a recommendation."""
    if not members:
        return ("nothing here knows who would be raiding, so there is nothing "
                "to count consumables against")
    unreachable = len([g for g in goals if g["status"] == UNREACHABLE])
    met = len([g for g in goals if g["status"] == MET])
    line = ("%d of %s met toward Molten Core"
            % (met, _count(len(goals), "goal", "goals")))
    if unreachable:
        return ("%s, and %s cannot be finished by this roster at all"
                % (line, "one of them" if unreachable == 1
                   else "%d of them" % unreachable))
    return line


def _strip(goals: list, members: list) -> list:
    """Four tiles, because four is what fits two across on a phone.

    Every one is a COUNT of rows on this page rather than a score invented for
    the strip, so a reader who distrusts a tile can go and count what it came
    from.
    """
    def many(status):
        return str(len([g for g in goals if g["status"] == status]))
    return [
        {"label": "members counted", "value": str(len(members)), "tone": ""},
        {"label": "goals met", "value": many(MET), "tone": "up"},
        {"label": "goals short", "value": many(SHORT), "tone": "unsure"},
        {"label": "cannot be finished", "value": many(UNREACHABLE),
         "tone": "no"},
    ]


def _others() -> list:
    """The raids at this cap that are not modelled, said as not modelled.

    A SHORT LIST READS EXACTLY LIKE A COMPLETE ONE. The only thing that can
    tell a reader Blackwing Lair was never asked about is a row that says so,
    so every raid at the cap gets one and four of the five say plainly that
    nothing above counted anything toward them.
    """
    return [{"name": raid["name"], "map_id": raid["map_id"],
             "modelled": raid["modelled"],
             "line": ("modelled above" if raid["modelled"] else
                      "not modelled: nothing on this page counts anything "
                      "toward it, and an empty goal list would read as "
                      "readiness")}
            for raid in RAIDS]


def _others_line() -> str:
    """Why there is one raid above and five rows below it."""
    return ("Molten Core is the only raid modelled here. The rest of the tier "
            "is listed so a reader can see it was left out on purpose rather "
            "than forgotten. " + OUT_OF_TIER)


def _order(goals: list) -> None:
    """Worst first, then by name so the list does not move on its own.

    THE RULE IS PRINTED ON THE PAGE, because a list in an order is read as a
    finding whether or not anybody meant it to be. What this roster cannot
    finish is first, then what is blocked on a recipe or a skill, then what is
    merely short, then what is already enough.
    """
    goals.sort(key=lambda g: (STATUS_ORDER.index(g["status"]), g["name"]))


def build_raidgoals(item_rows: list, recipe_rows: list, trainer_rows: list,
                    char_rows: list, skill_rows: list, spell_rows: list,
                    holding_rows: list, worn_rows: list, vendor_rows: list,
                    creature_rows: list, object_rows: list,
                    guild_rows: list, roster: list) -> dict:
    """What the guild still needs before Molten Core, and how far along it is.

    `roster` is bonds' family and is the FALLBACK rather than the answer:
    `guild_rows` are the members of whichever guild the family are actually
    in, and when there is one they are who the goals are counted for. No guild
    exists on this realm yet, and the page says that rather than letting five
    characters pass for a raid group.

    `item_rows` are `item_template` rows for every name plan_item_names()
    lists, and they are what turn this module's hand-written plan into
    something this realm has agreed to. A name with no row is reported BY NAME
    on the goal it belongs to rather than counting as zero.

    `recipe_rows` and `trainer_rows` are the two places this realm actually
    states a craft's required skill rank. Either, both or neither may answer
    for a given craft; neither answering is an absent rank and not a zero.

    `holding_rows` are the Bags tab's own `character_inventory` read, handed
    to bank.members_from_rows here rather than placed by the caller: where a
    stack is sitting is bank.py's answer on this page exactly as it is on
    that one.

    `worn_rows` are the paper-doll read with item_template's `fire_res` on it,
    and they are the only measured half of the resistance goal.
    """
    chosen = roster_from_guild(guild_rows, roster)
    members = _members(char_rows, chosen["names"])
    names = {member["name"] for member in members}

    items = _items(item_rows)
    held, banked = _placed(holding_rows, sorted(names))
    skills = _skills(skill_rows)
    known = _known(spell_rows)
    ranks = _ranks(recipe_rows, trainer_rows)
    sources = _sources(vendor_rows, creature_rows, object_rows)
    # AN EMPTY READ IS NOT AN ANSWER ABOUT THE ROSTER. See _recipe_blockers:
    # the guarded reads behind this page hand back [] on a degraded schema,
    # and "nobody has alchemy" is a claim this page must not make out of its
    # own failure to read.
    skills_read = bool(skill_rows)

    flasks = (FLASK_OF_SUPREME_POWER, FLASK_OF_DISTILLED_WISDOM,
              FLASK_OF_THE_TITANS)
    goals = [
        _supply_goal("flasks", "A flask each", flasks, PER_MEMBER_PER_NIGHT,
                     members, items, held, banked, skills, known, ranks,
                     sources, skills_read),
        _supply_goal("fireprot", "Fire protection potions",
                     (GREATER_FIRE_PROTECTION,), FIRE_PROTECTION_PER_MEMBER,
                     members, items, held, banked, skills, known, ranks,
                     sources, skills_read),
        _supply_goal("healing", "Healing potions", (MAJOR_HEALING_POTION,),
                     HEALING_POTIONS_PER_MEMBER, members, items, held, banked,
                     skills, known, ranks, sources, skills_read),
        _supply_goal("mana", "Mana potions", (MAJOR_MANA_POTION,),
                     MANA_POTIONS_PER_MEMBER, members, items, held, banked,
                     skills, known, ranks, sources, skills_read),
        _repair_goal(members, items, held, banked, skills, known, ranks,
                     sources, skills_read),
        _resistance_goal(members, worn_rows, names),
    ]
    _order(goals)

    return {
        "line": _headline(goals, members),
        "roster_line": _roster_line(chosen, members),
        "raid_line": (
            "Molten Core, map %d, is the level 60 tier's first raid and the "
            "one this page models. It gates nobody on consumables and nobody "
            "on resistance: everything counted below is what a group brings "
            "so the night goes better, not what the instance demands."
            % MOLTEN_CORE),
        "strip": _strip(goals, members),
        "order": (
            "Ordered by what a reader can act on: what this roster cannot "
            "finish at all first, then what is blocked on a recipe or a "
            "skill, then what is merely short, then what is already enough, "
            "and by name inside each so the list does not move on its own."),
        "goals": goals,
        "others": _others(),
        "others_line": _others_line(),
        "basis": _basis(),
        "empty_note": ("nothing here knows who would be raiding, so there is "
                       "nothing to count consumables against"
                       if not members else ""),
    }


def _basis() -> str:
    """What this page read, and every number on it the world did not say.

    THE HOUSE RULE IS THAT A VIEW SAYS WHAT IT DOES NOT COVER, and the loot
    board's and the dungeon plan's footers are the precedent. The weakest
    claim on this page is stated FIRST, because a reader who takes a
    hand-written reagent list for a measurement will farm to it.
    """
    return (
        "THE REAGENT LISTS ARE NOT MEASURED. Reagents live in Spell.dbc, "
        "which this deployment does not import: acore_world.spell_dbc carries "
        "custom rows only and skilllineability_dbc is empty, so no query here "
        "can say what a flask is made of. The recipes above were read from "
        "community data for 3.3.5a and, unlike bag_economy.py's eleven "
        "tailoring recipes, they were NOT checked back against this realm. "
        "What makes them safe to act on is that every item is named rather "
        "than numbered: item_template resolves each name at read time, and a "
        "name this realm does not carry is reported by name on the goal it "
        "belongs to instead of counting as zero. "
        "HOW MUCH ONE CAST MAKES IS NOT READABLE EITHER, for the same reason, "
        "so every craft is counted at one item per cast. That is the floor "
        "and not a guess: community data for the WotLK re-release says the "
        "level 60 flasks make two, so if this realm agrees then every flask "
        "reagent total above is double what is needed. It leans that way on "
        "purpose, because a wasted afternoon is cheaper than a raid that runs "
        "out. "
        "HOW MANY OF EACH A MEMBER SHOULD CARRY IS A CONVENTION, and so is "
        "which consumables a Molten Core night calls for at all: the instance "
        "admits a party carrying nothing, and no table on this realm states a "
        "requirement, because there is not one. The per-member number is "
        "printed beside every total so it can be disagreed with. "
        "MEASURED, from this realm's own tables: who is in the guild and "
        "their levels from guild_member and characters, every member's "
        "profession skills from character_skills, which craft spells each has "
        "actually learned from character_spell, the skill rank a recipe needs "
        "wherever item_template or trainer_spell states one, whether each "
        "item exists here and its quality and item level from item_template, "
        "how many of everything the roster holds across bags and bank through "
        "the same character_inventory read the Bags tab makes, and whether "
        "each reagent is sold, dropped or gathered on this realm, from "
        "npc_vendor, creature_loot_template and gameobject_loot_template. "
        "FIRE RESISTANCE IS SUMMED FROM WORN GEAR ONLY, off item_template's "
        "own fire_res column. Enchantments are not counted, because an "
        "enchantment is an id into a table this sum does not read, and buffs "
        "are not counted because a buff is not a fact about gear. "
        "A REAGENT IS FOLLOWED ONE CRAFT DEEP AND NO FURTHER. Stonescale Oil "
        "is the only reagent here that is itself a recipe and it carries its "
        "own line; everything under that is picked, fished, bought or killed "
        "for. "
        "WHAT IS NOT ASKED HERE AT ALL: what anything costs, how many crafts "
        "raise a skill from one value to another, which flask suits which "
        "character, and who tanks. The last two are choices, and a page that "
        "made them would be deciding the thing it went out of its way not to "
        "decide.")
