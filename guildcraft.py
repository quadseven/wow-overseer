"""Every trade the guild holds, every recipe it is missing, and where to farm it.

THE TWO HALVES OF ONE REQUEST. The operator asked for "a guild profession
view" and, in the same breath, "we'll need to do farm runs for profession
recipes and then get recipe mats". A list of who has what is the first half and
it is the easy half; the useful half is the second one, because a recipe nobody
knows is only actionable once the page can say WHERE it comes from and WHAT it
would take to learn it. So every missing recipe on this page carries its source
and its skill arithmetic, and a recipe with neither says so rather than being
dropped off the end of the list.

WHAT IT DOES NOT DO IS DECIDE. It counts, it orders on a rule it prints above
the list, and it reports a gap as a gap. The rule that a page renders and does
not decide is `test_recap_tab.ThePageDecidesNothing`, and this module keeps the
other half of it: every sentence a reader sees is written here, so a Python
test can read it.

A GUILD THAT DOES NOT EXIST YET. Measured on this realm: 1,628 characters,
twenty guilds, and the family is in none of them. So the covered roster is the
family PLUS whoever shares a guild with them, which is the family alone today
and becomes the guild the day one exists, with nothing here to change. The
headline says which of those two it is looking at rather than letting five
names pass for a guild.

WHERE THE FACTS COME FROM, AND WHICH OF THEM THIS REALM CANNOT ANSWER
---------------------------------------------------------------------
The strong ones, read from this realm's own tables:

  who holds a trade, and how far   `character_skills`, value and max
  which recipes they know          `character_spell`, matched against the
                                   craft spell a recipe ITEM teaches
  which trade a recipe belongs to  `item_template.RequiredSkill` on the recipe
                                   item, and `trainer_spell.ReqSkillLine` for
                                   the ones a trainer teaches
  what a recipe asks for           `item_template.RequiredSkillRank` and
                                   `RequiredLevel` on the same row
  who sells it                     `acore_world.npc_vendor`
  what drops it                    `acore_world.creature_loot_template`,
                                   direct rows only
  which quest hands it over        `acore_world.quest_template`, the four
                                   fixed rewards and the six choices
  where any of those stand         `acore_world.creature` position, named
                                   through the committed zones.json

The weak one, and it is weak for a reason worth writing down. THE SPELL TO
SKILL LINE MAP IS NOT IN THIS DATABASE. `acore_world.skilllineability_dbc` is
EMPTY on this realm (0 rows, measured 2026-09-05 for the bag ladder in
bag_economy.py) and `spell_dbc` holds 4,492 custom rows containing none of the
trade recipes, because DBC data ships inside the client files the worldserver
reads and this service will never see them. So a craft spell can be turned into
a name here only when a recipe ITEM teaches it, through that item's own
`spellid_2`. Trainer-taught crafts are therefore COUNTED AND NEVER NAMED on
this page, out of `trainer_spell`, which does carry the skill line. Saying "Og
knows 6 of the 14 crafts his trainer teaches at this rank" is true and useful;
inventing the six names would not be.

THE COST, BECAUSE IT IS A CROSS PRODUCT. Every character against every trade
against every recipe in it. The reads are batched the way the recap's and the
dungeon plan's are: whole-set queries in two phases, none of them per recipe
and none of them per character, and nothing in this module goes back to the
database.
"""
from __future__ import annotations

import goals
import professions
import recap

# `item_template.class` for a recipe, pattern, plan, formula, design, technique
# or manual. 3.3.5a ItemClass, the same number wealth.py already prints as
# "Recipe", and the one filter that turns a forty-thousand row item table into
# the few thousand rows this page is about.
RECIPE_CLASS = 9

# The maps a character can stand on. Anything else is an instance, and an
# instance is named by the site's own name for it rather than by a zone
# rectangle, because zones.json holds no rectangles inside a dungeon.
CONTINENT_MAPS = (0, 1, 530, 571)

# HOW MANY CHARACTERS THIS PAGE WILL READ SPELLS FOR. The family is five and
# the biggest guild on this realm is nowhere near this, so today it binds
# nothing; it exists because `character_spell` is the one read here that grows
# with the roster rather than with the world, and a guild of four hundred would
# turn a page into a scan. A roster cut short says so in its own coverage line,
# because a list that is simply SHORT reads exactly like a complete one.
MEMBER_CEILING = 60

# HOW MANY MISSING RECIPES A TRADE PRINTS. The page is read on a phone and a
# trade at skill 75 can be missing eighty recipes, which is a list nobody
# scrolls. The count of what was left out is printed beside the ones that are
# shown, and the ORDER that decided which is printed above the whole list, so a
# reader can tell a trimmed list from a finished one.
LISTED_MISSING = 12

# And how many known ones. Higher, because knowing a recipe is the answer to
# "who do I ask for this", and a reader looking for one name wants the list
# long rather than ranked.
LISTED_KNOWN = 20

# How many sources one recipe prints before it says how many more there are. A
# recipe can be on thirty vendors, and printing them is not a farm plan, it is
# a wall.
SOURCES_SHOWN = 3

# The three ways a recipe ITEM reaches a character in this database. ROLE
# NAMES rather than display words: the sentence beside each one is written
# below, where a Python test can read it.
VENDOR = "vendor"
DROP = "drop"
QUEST = "quest"

# What a missing recipe's skill arithmetic came out as. ROLE NAMES again, and
# the page turns them into a chip tone; the stylesheet is the only thing that
# knows this site is drawn on two grounds.
NOW = "now"
SHORT = "short"
LEVEL_GATED = "level"

# skill id -> the lowercase word this service already uses for it. Inverted
# from goals.SKILL_IDS rather than restated: that table was verified live
# against `character_skills` across a hundred characters and against the core's
# own SharedDefines.h enum, and a second copy is a second thing to get wrong.
SKILL_WORDS = {number: word for word, number in goals.SKILL_IDS.items()}


def recipe_skills() -> list[int]:
    """Every skill id the reads bind, sorted.

    PUBLIC, AND CALLED BY THE FETCH, so the queries cannot fall behind the
    module's idea of which trades this page is about. The gathering trades are
    in here even though no recipe item names one: a trade with no recipes still
    gets a row saying so, and leaving them out of the bind list would have made
    "no recipes exist for this trade" and "nobody asked" the same empty answer.
    """
    return sorted(goals.SKILL_IDS.values())


def covered_names(roster: list[str], guild_rows: list[dict],
                  ceiling: int = MEMBER_CEILING) -> list[str]:
    """Who this page reads, family first and then their guild.

    PUBLIC FOR THE SAME REASON `recipe_skills` IS: the skills and spells reads
    bind this list, and a name the page draws a row for but never read spells
    for would render as "knows nothing", which is a claim rather than a gap.

    The family comes first and is never cut, because the five are the reason
    this page exists and a guild large enough to push them off the end would be
    answering somebody else's question.
    """
    seen = list(dict.fromkeys(roster))
    others = sorted({row["name"] for row in guild_rows} - set(seen))
    return (seen + others)[:ceiling]


def _guild_of(guild_rows: list[dict]) -> str:
    """The one guild these rows belong to, or "" when there is not exactly one.

    A character belongs to one guild at a time and the read is bounded to the
    guilds the covered characters are in, so two names means the family has
    SPLIT across two. That is a real state and it is reported as the count it
    is rather than by picking one of them and drawing the page under it.
    """
    names = sorted({row["guild"] for row in guild_rows if row.get("guild")})
    return names[0] if len(names) == 1 else ""


def _guild_line(guild_rows: list[dict], roster: list[str],
                covered: list[str]) -> str:
    """Who this page is about, and whether that is a guild at all.

    THE HONEST SHAPE OF "THERE IS NO GUILD YET". The family is in none of the
    realm's twenty guilds, so a page headed "the guild" over five names would
    be asserting something that has not happened. It says the five are five,
    and it starts saying "the guild" on the day the rows arrive, with nothing
    here to change.
    """
    guild = _guild_of(guild_rows)
    kin = len(roster)
    if not guild_rows:
        return ("%d characters, and not one of them is in a guild, so this is "
                "the family rather than a guild" % kin)
    if not guild:
        names = sorted({row["guild"] for row in guild_rows if row.get("guild")})
        return ("the family is split across %d guilds (%s), so this covers "
                "everybody in all of them" % (len(names), ", ".join(names)))
    extra = len(covered) - kin
    if extra <= 0:
        return ("the guild %s, whose only members are the %d this site already "
                "follows" % (guild, kin))
    return ("the guild %s: the %d this site follows and %d more who share it"
            % (guild, kin, extra))


def _coverage_line(covered: list[str], guild_rows: list[dict], ceiling: int,
                   recipes: int, trades: int) -> str:
    """What the list had to work with, and what it could not reach.

    THE ANSWER TO "WHY IS THE ONE I WANT NOT IN HERE", which is a question
    asked while scanning rather than after reaching the bottom. Three states
    have to stay apart and only this sentence can keep the third visible: a
    trade with nothing missing, a trade whose recipes were trimmed for length,
    and a character whose spells were never read at all.
    """
    everyone = len({row["name"] for row in guild_rows} | set(covered))
    cut = everyone - len(covered)
    said = ("%d characters read against %d trades, and %d recipe items"
            % (len(covered), trades, recipes))
    if cut > 0:
        return (said + ". %d more share the guild and were NOT read: this page "
                "stops at %d characters, so those are missing from every count "
                "above rather than known to hold nothing." % (cut, ceiling))
    return said + ". Every character this page covers was read."


def _skill_word(skill: int) -> str:
    """The word for a skill id, or the number when nothing here names it."""
    return SKILL_WORDS.get(int(skill)) or "skill %d" % int(skill)


def _kind_of(word: str) -> str:
    """Which family of trade this is, in the vocabulary professions.py owns."""
    if word in professions.GATHERING:
        return "gathering"
    if word in professions.CRAFTING:
        return "crafting"
    if word in professions.SECONDARY:
        return "secondary"
    return "trade"


def _place(map_id, x, y, geo, names: dict) -> str:
    """Where a spawn stands, as a place a person could walk to.

    TWO ANSWERS AND THEY COME FROM DIFFERENT PLACES. A continent spawn is named
    by the zone rectangle that contains it, out of the committed zones.json the
    live map already places characters with. An instance spawn is inside a
    dungeon, where zones.json holds no rectangles at all, so it is named by the
    site's own name for that map. Running the second through the first is how
    "an unknown place" would come to stand where "The Deadmines" is the answer.

    "" is never returned. A spawn this page cannot place SAYS so, because a
    blank where a zone should be reads as a zone whose name is missing rather
    than as a creature nothing here can find.
    """
    if map_id is None or x is None or y is None:
        return "somewhere this page cannot place"
    map_id = int(map_id)
    if map_id in CONTINENT_MAPS:
        return geo.zone_name(map_id, float(x), float(y))
    return names.get(map_id) or "map %d" % map_id


def _chance_line(chance) -> str:
    """How likely this row is, in the loot table's own number, and no further.

    DELIBERATELY WEAKER THAN THE LOOT BOARD'S SENTENCE, and the basis says so
    rather than letting it read as the same claim. `recap._chance` can say "one
    roll shared between the 4 rows in its group" because it holds every row of
    that creature's table and can count the group. This page holds only the
    rows that carry a RECIPE, so it can count nothing, and a percentage
    invented for a grouped row is a number somebody would plan a farm run
    around.
    """
    value = float(chance or 0)
    if value > 0:
        return "%g%% on the table's own row" % value
    return ("the loot table gives no chance on this row, which is what a row "
            "sharing one roll with others in its group looks like")


def _vendor_line(row: dict, geo, names: dict) -> str:
    """One vendor, named and placed."""
    return "sold by %s in %s" % (
        row.get("name") or "an unnamed vendor",
        _place(row.get("map"), row.get("position_x"), row.get("position_y"),
               geo, names))


def _drop_line(row: dict, geo, names: dict) -> str:
    """One creature that drops it, with the levels it is found at.

    THE LEVEL BAND IS THE HALF THAT MAKES IT A PLAN. "Drops from a Defias
    Conjurer" is a fact; "drops from a Defias Conjurer, level 20 to 21, in
    Westfall" is somewhere a family of thirty-somethings can go and clear.
    """
    low = int(row.get("minlevel") or 0)
    high = int(row.get("maxlevel") or 0)
    if low and high and low != high:
        band = "level %d to %d" % (low, high)
    elif low:
        band = "level %d" % low
    else:
        band = "a level this page cannot read"
    return "drops from %s, %s, in %s: %s" % (
        row.get("name") or "an unnamed creature", band,
        _place(row.get("map"), row.get("position_x"), row.get("position_y"),
               geo, names),
        _chance_line(row.get("Chance")))


def _quest_line(row: dict) -> str:
    """One quest that hands it over, with the level it is written for."""
    level = int(row.get("QuestLevel") or 0)
    title = row.get("LogTitle") or "an unnamed quest"
    if level > 0:
        return "rewarded by the quest %s, written for level %d" % (title, level)
    return ("rewarded by the quest %s, which carries no level in the quest "
            "table" % title)


def _sources_for(entry: int, vendors: dict, drops: dict, quests: dict, geo,
                 names: dict) -> list[dict]:
    """Every way this database says the recipe item can be got.

    VENDOR FIRST, THEN QUEST, THEN DROP, and that is a COST order rather than a
    preference: a vendor is a walk with a known ending, a quest is a walk with a
    known ending behind some work, and a drop is a number of kills nobody here
    can predict. It is printed above the list rather than left for a reader to
    infer from the order they happen to be in.
    """
    out = []
    for row in vendors.get(entry, []):
        out.append({"kind": VENDOR, "line": _vendor_line(row, geo, names)})
    for row in quests.get(entry, []):
        out.append({"kind": QUEST, "line": _quest_line(row)})
    for row in drops.get(entry, []):
        out.append({"kind": DROP, "line": _drop_line(row, geo, names)})
    return out


def _source_line(sources: list[dict], shown: int) -> str:
    """The one line a collapsed recipe shows about where it comes from.

    "NO SOURCE THIS PAGE CAN SEE" IS NOT "NO SOURCE". The reads behind this
    follow `creature_loot_template` direct rows only, exactly as the loot board
    and the dungeon plan do, so a recipe sitting behind
    `reference_loot_template` (which is where most world drops live) arrives
    here with nothing attached. Saying "nowhere" would be the page asserting
    the absence of a thing it declined to look for.
    """
    if not sources:
        return ("no vendor, quest or direct drop row in this database carries "
                "it, which is also what a world drop behind a reference loot "
                "table looks like from here")
    where = ", ".join(sorted({source["kind"] for source in sources}))
    rows = ("1 source row" if len(sources) == 1
            else "%d source rows" % len(sources))
    if len(sources) <= shown:
        return "%s read, all listed here (%s)" % (rows, where)
    return ("%s read (%s); the %d cheapest to reach are listed here"
            % (rows, where, shown))


def _reach(rank: int, level_needed: int, best: dict | None) -> str:
    """Which of the three states this recipe is in for the best holder.

    A ROLE NAME AND NEVER A COLOUR. The page turns it into a chip tone, and the
    stylesheet is the only thing that knows there are two grounds.
    """
    if best is None:
        return SHORT
    if level_needed and int(best.get("level") or 0) < level_needed:
        return LEVEL_GATED
    return NOW if int(best.get("value") or 0) >= rank else SHORT


def _reach_line(word: str, rank: int, level_needed: int,
                best: dict | None) -> str:
    """What it would take to learn this one, counted against a real character.

    THE WHOLE POINT OF THE SENTENCE IS THAT A RECIPE OUT OF REACH LOOKS OUT OF
    REACH. A list of recipes with a skill number beside each reads as a shopping
    list and a reader acts on it; the arithmetic against the person who would
    actually learn it is what turns "requires 110" into "he is 35 short of it
    and his training already allows that much".

    BOTH GATES ARE NAMED, because they fail differently. Skill is ground out by
    crafting; a character level is ground out by playing, and a recipe behind
    one is not made reachable by any amount of cloth.
    """
    if best is None:
        return ("nobody in the guild holds %s, so nothing here can learn it yet"
                % word)
    who = best["who"]
    have = int(best.get("value") or 0)
    ceiling = int(best.get("max") or 0)
    level = int(best.get("level") or 0)
    if level_needed and level < level_needed:
        return ("it asks for character level %d and %s is %d, so no amount of "
                "%s gets to it" % (level_needed, who, level, word))
    if have >= rank:
        return ("it asks for %s %d and %s has %d, so it can be used the day it "
                "is in their bags" % (word, rank, who, have))
    if ceiling and rank > ceiling:
        # REACHED WHEN ANOTHER HOLDER HAS TRAINED FURTHER. The listed recipes
        # are bounded by the HIGHEST ceiling in the guild and this sentence is
        # measured against the highest ground SKILL, which are not always the
        # same person: a recipe above this one's training but under somebody
        # else's is listed, and saying it flatly needs a trainer tier would be
        # untrue of the guild. It says whose training stops where, and the
        # holder lines above it are what name the other one.
        return ("it asks for %s %d; %s has %d and their own training stops at "
                "%d, so a trainer tier has to come before any crafting does"
                % (word, rank, who, have, ceiling))
    return ("it asks for %s %d; %s has %d, which is %d short"
            % (word, rank, who, have, rank - have))


def _recipe_chips(rank: int, word: str, reach: str,
                  sources: list[dict]) -> list[dict]:
    """The three or four words that have to survive being collapsed on a phone.

    Cut from the sentences below them and cut HERE, so a page that trimmed
    "it asks for tailoring 110" down to "tailoring 110" would not be writing
    the short version itself and letting the two drift.
    """
    chips = [{"text": "%s %d" % (word, rank), "tone": ""}]
    if reach == NOW:
        chips.append({"text": "in reach", "tone": "up"})
    elif reach == LEVEL_GATED:
        chips.append({"text": "behind a level", "tone": "no"})
    else:
        chips.append({"text": "out of reach", "tone": "no"})
    if not sources:
        chips.append({"text": "no source read", "tone": "unsure"})
    else:
        for kind in (VENDOR, QUEST, DROP):
            if any(source["kind"] == kind for source in sources):
                chips.append({"text": kind, "tone": ""})
    return chips


def _required_level(row: dict) -> int:
    """The character level a recipe item asks for, under either column name.

    The shared `_ITEM_TEMPLATE_COLUMNS` this read borrows aliases the column to
    `required_level`, which is what `recap.item_payload` reads; a row built
    straight off `item_template` carries the raw name. Accepting both is the
    same accommodation item_payload already makes for quality and item level,
    and it is what lets a fixture be written either way round.
    """
    return int(row.get("RequiredLevel") or row.get("required_level") or 0)


def _recipe_card(row: dict, word: str, best: dict | None, vendors: dict,
                 drops: dict, quests: dict, icons: dict, geo, names: dict,
                 book) -> dict:
    """One recipe nobody in the guild knows, as the page draws it."""
    entry = int(row["entry"])
    rank = int(row.get("RequiredSkillRank") or 0)
    level_needed = _required_level(row)
    sources = _sources_for(entry, vendors, drops, quests, geo, names)
    reach = _reach(rank, level_needed, best)
    payload = recap.item_payload(entry, row, icons, book)
    payload.update(
        rank=rank,
        required_level=level_needed,
        reach=reach,
        reach_line=_reach_line(word, rank, level_needed, best),
        sources=sources[:SOURCES_SHOWN],
        source_line=_source_line(sources, SOURCES_SHOWN),
        chips=_recipe_chips(rank, word, reach, sources),
    )
    return payload


def _known_card(row: dict, word: str, knowers: list[str], icons: dict,
                book) -> dict:
    """One recipe somebody in the guild already knows.

    NAMED BY WHO KNOWS IT rather than by the trade, because the question this
    list answers is "who do I ask", and a trade with two holders is a trade
    where that is not obvious.
    """
    entry = int(row["entry"])
    rank = int(row.get("RequiredSkillRank") or 0)
    payload = recap.item_payload(entry, row, icons, book)
    payload.update(
        rank=rank,
        knowers=knowers,
        line=("%s can make this, and it asks for %s %d"
              % (" and ".join(knowers), word, rank)),
    )
    return payload


def _holder_line(holder: dict, word: str) -> str:
    """One character's standing in one trade, in their own two numbers.

    THE MAX IS NOT DECORATION. A skill of 1 out of 75 and a skill of 1 out of
    300 are different characters: the first has just been taught the trade and
    the second has trained four tiers and never used one of them. The value
    alone reads as the same person.
    """
    value = int(holder.get("value") or 0)
    ceiling = int(holder.get("max") or 0)
    if not ceiling:
        return ("%s holds %s at %d, and this database gives no ceiling for it"
                % (holder["who"], word, value))
    if value >= ceiling:
        return ("%s holds %s at %d of %d, which is as far as their training "
                "goes" % (holder["who"], word, value, ceiling))
    return "%s holds %s at %d of %d" % (holder["who"], word, value, ceiling)


def _trade_line(word: str, holders: list[dict], kind: str) -> str:
    """The headline on a trade card. Who holds it, or plainly that nobody does."""
    if not holders:
        if kind == "gathering":
            return "nobody in the guild gathers with %s" % word
        return "nobody in the guild holds %s" % word
    if len(holders) == 1:
        return _holder_line(holders[0], word)
    who = ", ".join(holder["who"] for holder in holders)
    return "%d of them hold %s: %s" % (len(holders), word, who)


def _recipes_line(kind: str, known: int, missing: int, listed: int,
                  holders: list[dict], total: int) -> str:
    """What this trade can and cannot make, counted rather than judged.

    FOUR ANSWERS AND THEY MUST NOT COLLAPSE INTO ONE. A gathering trade has no
    recipes at all; a trade nobody holds has recipes nobody can learn; a trade
    whose recipes are all known has nothing to farm for; and a trade with a
    list had that list TRIMMED, which is the one a reader cannot see for
    themselves.

    `total` IS EVERY RECIPE ITEM READ FOR THE TRADE, and it is a separate
    argument rather than `known + missing` because those two are both ZERO for
    a trade nobody holds. That sum would have printed "0 recipe items exist for
    engineering", which is a statement about the world and a false one, over
    the trade the whole page exists to point at.
    """
    if kind == "gathering":
        return ("a gathering trade: nothing is crafted from it, so there are "
                "no recipes here to be missing")
    if not holders:
        return ("%d recipe items exist for it in this database and nobody here "
                "can learn one until somebody takes the trade" % total)
    said = "%d of its recipe items are already known" % known
    if not missing:
        return (said + ", and none of the rest sit under the training already "
                "held")
    under = ("1 more sits under the training already held" if missing == 1
             else "%d more sit under the training already held" % missing)
    if missing > listed:
        return "%s, and %s; the %d cheapest to reach are listed" % (said, under,
                                                                    listed)
    return "%s, and %s, all listed" % (said, under)


def _trainer_line(word: str, taught: int, held: int, ceiling: int) -> str:
    """What the trainer still has, counted, because it cannot be named here.

    THE ONE THING THIS REALM'S DATABASE CANNOT TELL ANYBODY. `trainer_spell`
    carries the skill line and the rank, so the COUNT is exact; what it does
    not carry is a name, and neither does anything else here, because
    `skilllineability_dbc` is empty and Spell.dbc is client data. A page that
    invented the names would be inventing the only part a reader would act on.
    """
    if not taught:
        return ""
    if not ceiling:
        return ("this realm's trainers teach %d %s crafts; nobody here holds "
                "the trade, so none of them are counted as known"
                % (taught, word))
    left = taught - held
    if left <= 0:
        return ("every one of the %d %s crafts a trainer teaches at or under "
                "skill %d is already known" % (taught, word, ceiling))
    known = ("1 of them is known" if held == 1
             else "%d of them are known" % held)
    visits = ("1 is a trainer visit" if left == 1
              else "%d are a trainer visit" % left)
    return ("a trainer teaches %d %s crafts at or under skill %d and %s, so %s "
            "rather than a farm run. This page can count them and cannot name "
            "them: the basis below says why"
            % (taught, word, ceiling, known, visits))


def _assigned_line(word: str, assigned_to: list[str],
                   holders: list[dict]) -> str:
    """The difference between a trade the family MEANT to have and one it HAS.

    TWO TABLES THAT ARE ALLOWED TO DISAGREE, AND THE GAP IS THE FINDING.
    `overseer_roster.professions` is what the family decided and what
    mod-overseer is permitted to keep; `character_skills` is what the world
    actually granted at a trainer. professions.py's whole design is that the
    first never causes the second, so a plan that has not happened yet shows up
    here as exactly that instead of as a page quietly reading the plan as the
    world.
    """
    if not assigned_to:
        return ""
    held_by = {holder["who"] for holder in holders}
    waiting = [who for who in assigned_to if who not in held_by]
    if not waiting:
        return "assigned to %s in the roster, and held" % ", ".join(assigned_to)
    return ("assigned to %s in the roster, and %s does not hold it in "
            "character_skills yet"
            % (", ".join(assigned_to), " nor ".join(waiting)))


def _trade_chips(word: str, kind: str, holders: list[dict], known: int,
                 missing: int) -> list[dict]:
    """The chips a collapsed trade row carries.

    Facts already in the sentences below it, cut to chip length HERE so the two
    cannot drift, and `tone` is a ROLE NAME rather than a colour.
    """
    chips = [{"text": kind, "tone": ""}]
    if not holders:
        chips.append({"text": "nobody holds it", "tone": "no"})
        return chips
    best = max(int(holder.get("value") or 0) for holder in holders)
    ceiling = max(int(holder.get("max") or 0) for holder in holders)
    chips.append({"text": ("%s %d of %d" % (word, best, ceiling) if ceiling
                           else "%s %d" % (word, best)),
                  "tone": "up" if ceiling and best >= ceiling else ""})
    if kind == "gathering":
        return chips
    chips.append({"text": "%d known" % known, "tone": "up" if known else ""})
    chips.append({"text": "%d to find" % missing,
                  "tone": "" if missing else "up"})
    return chips


def _best_holder(holders: list[dict]) -> dict | None:
    """Whose skill the reach arithmetic is measured against.

    THE HIGHEST VALUE AND NOT THE HIGHEST CEILING. The question a missing
    recipe answers is "could anybody use this today", and that is the skill
    somebody has actually ground, not the tier they paid for. A tie goes to the
    name, so the sentence does not change between two identical answers.
    """
    if not holders:
        return None
    return sorted(holders, key=lambda h: (-int(h.get("value") or 0),
                                          -int(h.get("max") or 0),
                                          h["who"]))[0]


def _gap_line(word: str, kind: str, assigned_to: list[str]) -> str:
    """Why a trade nobody holds is missing, said in the terms it is missing in.

    A TRADE IN professions.UNASSIGNED IS NOT AN OVERSIGHT. It names the
    trade(s) the family's own table deliberately leaves open for a guild to
    cover, so a page listing one beside an accident would be reporting a
    decision as a defect. Engineering used to be the one - it moved to
    inscription and jewelcrafting when Grog's assignment changed (#2831
    update) - and the count and wording below are read from
    professions.PRIMARY / professions.UNASSIGNED rather than typed in, so
    this sentence cannot go stale the next time that table is edited again.
    """
    if word in professions.UNASSIGNED:
        claimed = len(professions.PRIMARY) - len(professions.UNASSIGNED)
        this_one = "this one" if len(professions.UNASSIGNED) == 1 else "these"
        return ("%s: left open on purpose. The family's own trade table gives "
                "its five characters the other %d primaries and names %s as "
                "the gap a guild is meant to fill, so it is a decision "
                "waiting on members rather than a mistake"
                % (word, claimed, this_one))
    if assigned_to:
        return ("%s: assigned to %s in the roster, and not held by anybody in "
                "character_skills yet" % (word, ", ".join(assigned_to)))
    if kind == "gathering":
        return ("%s: nobody gathers it, so every craft that runs on it runs on "
                "the auction house or on nothing" % word)
    if kind == "secondary":
        return ("%s: a secondary trade, which costs nobody a profession slot "
                "and which nobody here has picked up" % word)
    return ("%s: nobody holds it and nobody is assigned it, so nothing the "
            "guild makes can come from it" % word)


def _headline(trades: list[dict], gaps: list[dict], covered: list[str]) -> str:
    """The one line at the top. Counts, never a recommendation."""
    if not covered:
        return ("nothing here knows who the guild are, so it cannot say what "
                "they can make")
    if not trades:
        return ("this database listed no trades this page could read, so there "
                "is nothing to compare")
    held = len([trade for trade in trades if trade["holders"]])
    to_find = sum(trade["missing_count"] for trade in trades)
    if not to_find:
        return ("%d of %d trades held, and not one recipe under the training "
                "already held is missing" % (held, len(trades)))
    return ("%d of %d trades held, %d recipes missing that the training "
            "already allows, and %d trades nobody holds at all"
            % (held, len(trades), to_find, len(gaps)))


def _gaps_line(gaps: list[dict]) -> str:
    """How many trades nobody holds, counted rather than named twice.

    NEVER THE WORD "ONE" WHEN IT IS COUNTING. Every count on this page comes
    from a list the world handed over, so every one of them can be one, and
    "1 trades" is the class of mistake that appears on the day something has
    gone wrong, which is the day the page is read closely.
    """
    if not gaps:
        return "every trade this page reads is held by somebody"
    if len(gaps) == 1:
        return "1 trade is held by nobody"
    return "%d trades are held by nobody" % len(gaps)


def _order() -> str:
    """The rule the list is in, printed above the list rather than implied.

    A LIST IN AN ORDER IS READ AS A FINDING whether or not anybody meant it to
    be, so this is not optional furniture: without it the trade at the top
    reads as the trade to work on, which is a recommendation this module does
    not make.
    """
    return ("Trades the guild holds first, then the ones nobody holds; within "
            "each, the crafting trades before the gathering and secondary "
            "ones, then most missing recipes first, then by name so the order "
            "does not move on its own. Inside a trade, a missing recipe with a "
            "source read comes before one without, then the lowest skill "
            "requirement, then the name. A source is listed vendor first, then "
            "quest, then drop: a vendor is a walk with a known ending and a "
            "drop is a number of kills nothing here can predict.")


def _basis(trainer_rows: list[dict], roster_read: bool) -> str:
    """What this page read, and the several things it cannot say.

    THE HOUSE RULE IS THAT THE LIST SAYS WHAT IT DOES NOT COVER, and the loot
    board's own footer is the precedent. The weakest claim goes first, because
    a reader who takes a short list for a complete one will act on it.
    """
    named = ("A craft a TRAINER teaches is counted and never named. "
             "skilllineability_dbc is empty on this realm and spell_dbc holds "
             "custom rows only, because that data ships inside the client "
             "files the worldserver reads and this service never sees them, so "
             "a craft spell can be turned back into a name here only when a "
             "recipe ITEM teaches it. The trainer counts come from "
             "trainer_spell, which does carry the skill line and the rank."
             if trainer_rows else
             "This realm's trainer_spell returned nothing readable, so the "
             "trainer counts are absent rather than zero: a trade with no "
             "trainer line is not a trade whose trainer teaches nothing.")
    assignment = (
        "The trade a character is ASSIGNED comes from "
        "overseer_roster.professions, which is what the family decided and "
        "never what the world granted: a trade assigned and not held is "
        "printed as exactly that."
        if roster_read else
        "overseer_roster.professions could not be read this time, so no trade "
        "is reported as assigned; that is a missing column and not a family "
        "that has decided nothing.")
    return (
        "Recipes are item_template rows of class 9, which is every recipe, "
        "pattern, plan, formula, design, technique and manual in this world "
        "database, matched to a trade by their own RequiredSkill column. What "
        "a character KNOWS is character_spell matched against the craft spell "
        "each of those items teaches in spellid_2. " + named + " Sources are "
        "read three ways and no further: npc_vendor for who sells it, "
        "creature_loot_template DIRECT ROWS ONLY for what drops it, and "
        "quest_template's four fixed rewards and six choices for what hands it "
        "over. Loot behind reference_loot_template is NOT followed, which is "
        "where most world drops live, so a recipe with no source read here is "
        "one this page did not look hard enough for rather than one with "
        "nowhere to come from. Drop chance is the loot table's own number on "
        "that one row and nothing more: the Chronicle's loot board is the page "
        "that can say what a shared roll means, because it holds every row of "
        "a creature's table and this one holds only the rows carrying a "
        "recipe. Where a vendor or a creature stands is ONE of its spawn rows, "
        "the lowest by guid, named through the committed zones.json on a "
        "continent and by this site's own map name inside a dungeon; anything "
        "that roams or is spawned in several places has more than one and only "
        "one is named here. Whether a recipe is in reach is RequiredSkillRank "
        "and RequiredLevel against that character's own character_skills value "
        "and their level, so it is what the world would allow rather than what "
        "a plan says. " + assignment + " What a recipe COSTS in materials is "
        "not read here at all: this page answers where a recipe comes from, "
        "and the reagent list lives in Spell.dbc, which this deployment does "
        "not import.")


def _by_item(rows: list[dict]) -> dict:
    """Source rows bucketed by the recipe item they are a source for."""
    out: dict = {}
    for row in rows:
        out.setdefault(int(row["item"]), []).append(row)
    return out


def _holders_of(skill: int, skills: dict, members: dict) -> list[dict]:
    """Everybody covered who holds this trade, best first.

    A SKILL ROW IS NOT A TRADE. `character_skills` holds languages, Defense and
    every weapon skill beside the trades, which is the trap bridge.py already
    names: a module reasoning about trade slots over those rows is reasoning
    about nothing. The read narrows to `recipe_skills()` before this ever runs,
    and this looks up by id rather than scanning, so an unrelated skill cannot
    arrive here even if the read widened.
    """
    found = []
    for who, rows in skills.items():
        row = rows.get(skill)
        if row is None:
            continue
        found.append({
            "who": who,
            "value": int(row.get("value") or 0),
            "max": int(row.get("max") or 0),
            "level": int((members.get(who) or {}).get("level") or 0),
        })
    found.sort(key=lambda h: (-h["value"], -h["max"], h["who"]))
    return found


def _assigned_map(roster_rows: list[dict]) -> dict:
    """skill id -> the characters the roster column assigns it to.

    The column is a comma-separated list of skill ids, which is what
    professions.wanted_ids writes into it. Anything unparseable is skipped
    rather than guessed at: a malformed row should cost one character's
    assignment and not the page.
    """
    out: dict = {}
    for row in roster_rows:
        for piece in str(row.get("professions") or "").split(","):
            piece = piece.strip()
            if not piece.isdigit():
                continue
            out.setdefault(int(piece), []).append(row["name"])
    for who in out.values():
        who.sort()
    return out


def _beyond_line(word: str, beyond: int, ceiling: int) -> str:
    """How many recipes sit above the training already bought.

    WITHOUT THIS THE BOUND IS INVISIBLE. A trade showing twelve missing recipes
    at skill 75 looks like a trade with twelve recipes left in it, when it is a
    trade with several hundred and one trainer visit between them.
    """
    if not beyond or not ceiling:
        return ""
    if beyond == 1:
        return ("1 more recipe item exists for it above skill %d, which is "
                "behind the next trainer tier rather than behind a farm run"
                % ceiling)
    return ("%d more recipe items exist for it above skill %d, which are "
            "behind the next trainer tier rather than behind a farm run"
            % (beyond, ceiling))


def _known_head(count: int, listed: int) -> str:
    """The label over the known list, written HERE and not on the page.

    A HEADING IS A SENTENCE. "already known" composed in JavaScript is a claim
    no Python test can reach, which is the whole contract this view is held to,
    and it is also the one place a trimmed list would stop admitting it was
    trimmed. "" when there is nothing to head, so the page draws no empty
    label.
    """
    if not count:
        return ""
    if count > listed:
        return ("what somebody here can already make: %d of them, and the %d "
                "cheapest to learn are shown" % (count, listed))
    return ("what somebody here can already make" if count > 1 else
            "the one thing somebody here can already make")


def _missing_head(count: int, listed: int) -> str:
    """The label over the missing list. Same rule as `_known_head`."""
    if not count:
        return ""
    if count > listed:
        return ("what nobody here knows yet: %d of them, and the %d cheapest "
                "to reach are shown" % (count, listed))
    return ("what nobody here knows yet" if count > 1 else
            "the one thing nobody here knows yet")


def _trade_card(skill: int, recipes: list[dict], holders: list[dict],
                known_spells: dict, assigned_to: list[str],
                trainer: list[dict], vendors: dict, drops: dict, quests: dict,
                icons: dict, geo, names: dict, book) -> dict:
    """One trade as the page draws it, minus its place in the order.

    ONE PASS OVER THE RECIPES, which is what keeps a cross product cheap: the
    known list and the missing list are two filters of the same loop rather
    than two loops, and neither goes back to the database for a source. `rank`
    is stamped on afterwards, because where a trade landed among the others is
    not a fact about the trade.
    """
    word = _skill_word(skill)
    kind = _kind_of(word)
    best = _best_holder(holders)
    ceiling = max((holder["max"] for holder in holders), default=0)
    held_by = {holder["who"] for holder in holders}
    known: list[dict] = []
    missing: list[dict] = []
    beyond = 0
    for row in recipes:
        spell = int(row.get("spellid_2") or 0)
        knowers = sorted(who for who in held_by
                         if spell and spell in known_spells.get(who, ()))
        if knowers:
            known.append(_known_card(row, word, knowers, icons, book))
            continue
        if not holders:
            continue
        # UNDER THE TRAINING ALREADY HELD, and that bound is the world's own
        # number rather than a horizon invented here. A trade capped at 75 has
        # a few dozen recipes under it and several hundred above, and the
        # several hundred are not a list anybody can act on: they are behind a
        # trainer tier nobody has bought. The count above the bound is still
        # printed, so the bound itself is visible.
        if ceiling and int(row.get("RequiredSkillRank") or 0) > ceiling:
            beyond += 1
            continue
        missing.append(_recipe_card(row, word, best, vendors, drops, quests,
                                    icons, geo, names, book))
    # SOURCED FIRST, THEN CLOSEST TO REACH. A recipe this page can point at is
    # the one a reader can do something about tonight; one with no source read
    # is still listed, below the rest, saying so on its own row.
    missing.sort(key=lambda r: (not r["sources"], r["rank"], r["name"]))
    known.sort(key=lambda r: (r["rank"], r["name"]))
    in_band = [row for row in trainer
               if not ceiling or int(row.get("ReqSkillRank") or 0) <= ceiling]
    trainer_known = len([row for row in in_band
                         if any(int(row.get("SpellId") or 0)
                                in known_spells.get(who, ()) for who in held_by)])
    return {
        "skill": skill,
        "name": word,
        "kind": kind,
        "held": bool(holders),
        "holders": holders,
        # ONLY WHEN THEY ADD SOMETHING. With one holder `line` above IS that
        # holder's line, and a summary stays on screen when the row is opened,
        # so emitting both printed the same sentence twice under its own
        # heading. With two or more, `line` names them and these say how far
        # each has got, which is the thing the count cannot carry.
        "holder_lines": ([_holder_line(holder, word) for holder in holders]
                         if len(holders) > 1 else []),
        "line": _trade_line(word, holders, kind),
        "assigned": assigned_to,
        "assigned_line": _assigned_line(word, assigned_to, holders),
        "known": known[:LISTED_KNOWN],
        "known_count": len(known),
        "known_head": _known_head(len(known), LISTED_KNOWN),
        "missing": missing[:LISTED_MISSING],
        "missing_count": len(missing),
        "missing_head": _missing_head(len(missing), LISTED_MISSING),
        "recipes_line": _recipes_line(kind, len(known), len(missing),
                                      LISTED_MISSING, holders, len(recipes)),
        "beyond_line": _beyond_line(word, beyond, ceiling) if holders else "",
        "trainer_line": _trainer_line(word, len(in_band), trainer_known,
                                      ceiling),
        "chips": _trade_chips(word, kind, holders, len(known), len(missing)),
    }


def _place_them(trades: list[dict]) -> None:
    """Put the trades in order and tell each one where it landed.

    THE ORDER IS ONE RULE AND THE PAGE PRINTS IT: held before unheld, crafting
    before the rest, then the most missing recipes, then the name so the list
    does not move on its own. `rank` is decided here and never counted off the
    position a page drew a row at, which would agree today and disagree the
    first time somebody filtered the list, with nothing failing.
    """
    kinds = {"crafting": 0, "secondary": 1, "gathering": 2, "trade": 3}
    trades.sort(key=lambda t: (not t["held"], kinds.get(t["kind"], 3),
                               -t["missing_count"], t["name"]))
    for place, trade in enumerate(trades, start=1):
        trade["rank"] = place


def build_guildcraft(guild_rows: list[dict], member_rows: list[dict],
                     skill_rows: list[dict], spell_rows: list[dict],
                     roster_rows: list[dict], recipe_rows: list[dict],
                     trainer_rows: list[dict], vendor_rows: list[dict],
                     drop_rows: list[dict], quest_rows: list[dict],
                     icons: dict, roster: list[str], names: dict, geo,
                     book=None, roster_read: bool = True) -> dict:
    """Who can make what, what nobody can make, and where to go and get it.

    `guild_rows` are the guild the covered characters share, and an empty list
    is a real answer: the family is in none of this realm's twenty guilds, so
    the page covers five characters and says which of the two it is looking at.

    `recipe_rows` are `item_template` rows of class 9 narrowed to the trades
    `recipe_skills()` names. They arrive ONCE for every trade at the same time
    and are bucketed here, because the obvious shape for this view is a query
    per trade and that is fourteen round trips on an endpoint with no auth in
    front of it.

    `roster_read` is False when `overseer_roster.professions` could not be
    read, which is a real state on a world whose db-import image predates that
    column (infra#2757). No trade is then reported as assigned, and the basis
    says the column was missing rather than letting a silent absence read as a
    family that has decided nothing.

    `geo` is a transform.Geometry, loaded from the committed zones.json, and it
    is what turns a vendor's spawn position into a place somebody can walk to.

    `book` is an armory.ItemBook and is what turns a recipe's name into a
    TOOLTIP. Optional for the same reason it is optional in
    `recap.item_payload`: without it every row still renders, with its name in
    its quality colour and its link out.
    """
    covered = covered_names(roster, guild_rows)
    wanted = set(covered)
    members = {row["name"]: row for row in member_rows
               if row["name"] in wanted}
    skills: dict = {}
    for row in skill_rows:
        if row["name"] in wanted:
            skills.setdefault(row["name"], {})[int(row["skill"])] = row
    known_spells: dict = {who: set() for who in covered}
    for row in spell_rows:
        if row["name"] in known_spells:
            known_spells[row["name"]].add(int(row["spell"]))

    assigned = _assigned_map(roster_rows)
    by_skill: dict = {}
    for row in recipe_rows:
        by_skill.setdefault(int(row.get("RequiredSkill") or 0), []).append(row)
    trainer_by_skill: dict = {}
    for row in trainer_rows:
        trainer_by_skill.setdefault(int(row.get("ReqSkillLine") or 0),
                                    []).append(row)
    vendors = _by_item(vendor_rows)
    drops = _by_item(drop_rows)
    quests = _by_item(quest_rows)

    trades = [
        _trade_card(skill, by_skill.get(skill, []),
                    _holders_of(skill, skills, members), known_spells,
                    assigned.get(skill, []), trainer_by_skill.get(skill, []),
                    vendors, drops, quests, icons, geo, names, book)
        for skill in recipe_skills()]
    _place_them(trades)
    gaps = [{"name": trade["name"], "skill": trade["skill"],
             "line": _gap_line(trade["name"], trade["kind"],
                               trade["assigned"])}
            for trade in trades if not trade["holders"]]

    return {
        "line": _headline(trades, gaps, covered),
        "guild_line": _guild_line(guild_rows, roster, covered),
        "coverage": _coverage_line(covered, guild_rows, MEMBER_CEILING,
                                   len(recipe_rows), len(trades)),
        "gaps": gaps,
        "gaps_line": _gaps_line(gaps),
        "order": _order(),
        "trades": trades,
        "basis": _basis(trainer_rows, roster_read),
        "empty_note": ("this database listed no trades this page could read, "
                       "so there is nothing to compare" if not trades else ""),
    }
