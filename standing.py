"""Pure builder for the Armory's standing view: what the five have LEARNED.

WHY THIS EXISTS. The Armory tab answers "what is he wearing" and "how is he
specced". Neither answers the question that actually decides whether this
family can supply itself: what have they LEARNED. Trades, weapon skill,
reputation - the three ledgers that a character fills in over a lifetime and
that nothing on this site has ever shown. Each one is a table of bare
integers in `acore_characters`, and every one of those integers needs a book
to become a sentence.

THE FACT THIS VIEW EXISTS TO MAKE VISIBLE (mod-overseer#160). Every green
and blue the family cannot wear becomes vendor trash, because nobody can
disenchant it. Listing the trades they DO hold does not show that - a list
of two professions looks like a list of two professions. So the gap is
computed and drawn as its own thing: which of the ten primary trades nobody
in the family holds, and for enchanting in particular, why that one costs
them something every time a dungeon drops.

And the gap is worse than absent. All five hold herbalism AND alchemy, and
the world's ceiling is two primaries (professions.MAX_PRIMARY, which reads
it off the core). So enchanting is not a thing somebody could simply go and
train - every one of the five would have to give up a trade they already
have first. `slots_free` is zero for all five and the page says so, because
"nobody has it" and "nobody CAN have it without losing something" are
different problems with different fixes.

WHERE THE NAMES COME FROM, AND WHY NOT FROM SQL. The obvious joins do not
work on this realm. Every `*_dbc` table in acore_world is EMPTY - the core
reads the real DBCs off disk - and `acore_world.faction` does not exist at
all:

    faction_dbc  skillline_dbc  skilllineability_dbc  talent_dbc
    talenttab_dbc  skillraceclassinfo_dbc  skilltiers_dbc

    SELECT COUNT(*)  ->  0, every one (verified live 2026-09-02)

An empty table joins to nothing WITHOUT ERROR, so a page built on those
joins is blank and confident about it. armory.py already hit this for
talents and answered it by freezing the client's own tables into a
committed book (tools/gen_talents.py, talents.json); this view needs three
more of them and gets them the same way, from tools/gen_standing.py into
standing.json. THE TALENT PANEL THEREFORE WORKS: it reads the same
TalentBook the Armory profile does, so the spec is named, not guessed, and
there is no honest-blank-panel case to report.

Same seam rule as armory, family and panel (infra#2597): the HTTP adapter
fetches rows and does nothing else. Every judgement - what counts as a
profession rather than a racial passive, when a skill is graded rather than
a yes/no proficiency, how a stored reputation becomes a rank and a bar -
lives here where the stdlib suite reaches it with no database.

Tickets: infra#3096 and infra#3139 (the tab this extends),
quadseven/mod-overseer#160 (the missing enchanter),
quadseven/mod-overseer#88 (the Armory area).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import armory
import bonds
import family
import goals
import professions
from panel import CLASS_COLOURS, _CLASS_NAMES, _RACE_NAMES

# SkillLine.dbc's own CategoryID. The names are the core's SkillCategory
# enum; the two this module cares about are WEAPON and ARMOR, because those
# are the ones with a cap that moves with level.
CATEGORY_ATTRIBUTE = 5
CATEGORY_WEAPON = 6
CATEGORY_CLASS = 7
CATEGORY_ARMOUR = 8
CATEGORY_SECONDARY = 9
CATEGORY_LANGUAGE = 10
CATEGORY_PROFESSION = 11
CATEGORY_GENERIC = 12

# What the page groups skills under. Not the same list as the categories
# above, and the two places they differ are both deliberate:
#
#   "defence" is skill 95, which SkillLine files under WEAPON. It is pulled
#   out because it is the one defensive number in the whole table and
#   burying it among fifteen weapon rows is how it stops being read.
#
#   "profession" and "secondary profession" cannot come from the category at
#   all. SkillLine's SECONDARY category holds first aid and cooking next to
#   `Racial - Gnome` and `Riding`, so a category rule would report a gnome's
#   racial passive as a trade. They are named by ID instead, from
#   goals.SKILL_IDS via professions - the module that already owns "which
#   number is which trade" for this service.
GROUP_PROFESSION = "profession"
GROUP_SECONDARY = "secondary profession"
GROUP_WEAPON = "weapon"
GROUP_DEFENCE = "defence"
GROUP_ARMOUR = "armour"
GROUP_CLASS = "class"
GROUP_LANGUAGE = "language"
GROUP_OTHER = "other"

# The order the page draws the groups in: what a person can act on first.
GROUP_ORDER = (
    GROUP_PROFESSION,
    GROUP_SECONDARY,
    GROUP_WEAPON,
    GROUP_DEFENCE,
    GROUP_ARMOUR,
    GROUP_CLASS,
    GROUP_LANGUAGE,
    GROUP_OTHER,
)

DEFENCE_SKILL = 95

_CATEGORY_GROUPS = {
    CATEGORY_WEAPON: GROUP_WEAPON,
    CATEGORY_ARMOUR: GROUP_ARMOUR,
    CATEGORY_CLASS: GROUP_CLASS,
    CATEGORY_LANGUAGE: GROUP_LANGUAGE,
    CATEGORY_PROFESSION: GROUP_PROFESSION,
    CATEGORY_SECONDARY: GROUP_OTHER,
    CATEGORY_ATTRIBUTE: GROUP_OTHER,
    CATEGORY_GENERIC: GROUP_OTHER,
}

# Weapon and defence skill cap: five per level, and it is the LEVEL that
# sets it, not the row. `character_skills.max` usually agrees, but it is
# written when the skill is touched, so a character who has levelled since
# can carry a stale ceiling. The level is the authority and any disagreement
# is reported rather than smoothed over (see `skill_entry`).
SKILL_PER_LEVEL = 5

# A skill whose maximum is this is not graded at all: it is a proficiency, a
# yes/no fact about whether the character may use the thing. Cloth, Leather,
# Mail, Shield and (for some classes) Dual Wield are all stored 1/1.
#
# THIS IS WHY THE PANEL IS NOT A WALL OF RED. Measured live, Bork's Leather
# is 1/1 at level 23. Compared against a level cap of 115 that reads as
# "114 short", which would be the single loudest number on his card and a
# complete fabrication - he is not missing 114 points of anything, he simply
# knows how to wear leather. Proficiencies are reported as known, and no cap
# arithmetic is done on them.
PROFICIENCY_MAX = 1

# Three rows in `character_skills` that are shaped exactly like a graded
# skill and are not one. Each was measured live on 2026-09-02, and each
# would otherwise print a large and entirely invented shortfall:
#
#   777 Mounts      value is HOW MANY MOUNTS the character owns; the max
#   778 Companions  tracks level x 5 and is not a target. Grug reads
#                   "Companions 1/135" - he owns one pet, he is not 134
#                   points short of anything.
#   183 GENERIC     an internal client placeholder ("GENERIC (DND)"). It
#                   sits at the level cap on every character alive and the
#                   game's own skill window never draws it.
#
# Reported with their value and no cap, the same as a proficiency.
UNGRADED = frozenset({183, 777, 778})

# The reputation ladder, from the core's own ReputationMgr. PointsInRank is
# the WIDTH of each rank and the ranks are cumulative from the bottom, which
# is what `reputation_rank` walks. Reputation_Cap + 1 is where the walk
# starts because exalted is the only rank that is not open-ended upward.
RANK_NAMES = (
    "Hated",
    "Hostile",
    "Unfriendly",
    "Neutral",
    "Friendly",
    "Honored",
    "Revered",
    "Exalted",
)
POINTS_IN_RANK = (36000, 3000, 3000, 3000, 6000, 12000, 21000, 1000)
REPUTATION_CAP = 42999
REPUTATION_BOTTOM = -42000
NEUTRAL = 3

# `character_reputation.flags`, from the core's FactionFlags. A faction the
# character has actually MET is one the client would draw: visible, and not
# overridden by either of the two hiding flags. Every other row in that
# table is a faction the world created a slot for and the character has
# never encountered - there are 105 of those per character and five that
# mean anything, so this predicate is the whole difference between a
# reputation panel and a data dump.
FLAG_VISIBLE = 0x01
FLAG_HIDDEN = 0x04
FLAG_INVISIBLE_FORCED = 0x08

# The trade the family has nobody for, and the reason this view exists.
# Named rather than derived: it is not just one absent profession among ten,
# it is the one whose absence costs them something on every dungeon run.
ENCHANTING = "enchanting"
ENCHANTING_WHY = (
    "nobody can disenchant, so every green and blue none of the five can "
    "wear is vendor trash instead of dust (mod-overseer#160)"
)

WOWHEAD = "https://www.wowhead.com/wotlk/%s=%d"


@dataclass(frozen=True)
class StandingBook:
    """The frozen client tables this view needs, loaded once at import.

    Same shape and the same reason as armory.TalentBook: a file committed
    beside the code, because the server database's own copies of these
    tables are empty. Built by tools/gen_standing.py.

    The file stores skills and recipes POSITIONALLY and interns icon names
    into a shared list, which is how it fits in 174KB instead of 390KB.
    That encoding is undone here, once, so no caller ever sees an index.
    """

    skills: dict[int, dict]
    factions: dict[int, dict]
    recipes: dict[int, dict]
    by_skill: dict[int, list[int]] = field(default_factory=dict)

    @classmethod
    def load(cls, static_dir: str) -> "StandingBook":
        with open(os.path.join(static_dir, "standing.json")) as f:
            book = json.load(f)
        icons = book["icons"]
        skills = {
            int(sid): {"name": name, "category": category, "icon": icons[icon]}
            for sid, (name, category, icon) in book["skills"].items()
        }
        recipes = {
            int(spell): {"name": name, "skill": skill, "rank": rank, "creates": creates}
            for spell, (name, skill, rank, creates) in book["recipes"].items()
        }
        factions = {int(fid): entry for fid, entry in book["factions"].items()}
        by_skill: dict[int, list[int]] = {}
        for spell, recipe in recipes.items():
            by_skill.setdefault(recipe["skill"], []).append(spell)
        for spells in by_skill.values():
            spells.sort(key=lambda s: (recipes[s]["rank"], recipes[s]["name"]))
        return cls(skills=skills, factions=factions, recipes=recipes, by_skill=by_skill)

    def skill_name(self, skill_id: int) -> str:
        """The skill's name, or a diagnosable placeholder for an unknown id.

        A blank cell would read as "this character has an unnamed skill";
        the number says which row to go and look at instead.
        """
        found = self.skills.get(skill_id)
        return found["name"] if found else f"skill {skill_id}"

    def faction_name(self, faction_id: int) -> str:
        found = self.factions.get(faction_id)
        return found["name"] if found else f"faction {faction_id}"


def wowhead(kind: str, entry: int) -> str:
    """The tooltip link, in the one format this service already uses."""
    return WOWHEAD % (kind, entry)


# SkillLine id -> trade name, for the ten primaries and three secondaries.
#
# Derived from professions.PRIMARY and professions.SECONDARY through
# goals.SKILL_IDS rather than restated, for the reason professions.py gives
# for not restating them itself: a second copy is a second thing to get
# wrong, and the two drift the first time either one is edited. Built once
# at import because `skill_group` is called for every skill row of every
# member and none of its three inputs can change while the process lives.
_TRADE_NAMES = {
    goals.SKILL_IDS[name]: name for name in professions.PRIMARY | professions.SECONDARY
}


def profession_ids() -> dict[int, str]:
    """SkillLine id -> trade name. A copy, so no caller can edit the table."""
    return dict(_TRADE_NAMES)


def skill_group(skill_id: int, category: int) -> str:
    """Which panel a skill belongs under."""
    name = _TRADE_NAMES.get(skill_id)
    if name in professions.PRIMARY:
        return GROUP_PROFESSION
    if name in professions.SECONDARY:
        return GROUP_SECONDARY
    if skill_id == DEFENCE_SKILL:
        return GROUP_DEFENCE
    return _CATEGORY_GROUPS.get(category, GROUP_OTHER)


def level_cap(level: int) -> int:
    """Weapon and defence skill cap for a character of this level."""
    return max(0, level) * SKILL_PER_LEVEL


def is_proficiency(skill_id: int, maximum: int) -> bool:
    """A skill with no meaningful ceiling, so no shortfall can be computed.

    Either a yes/no proficiency (armour, dual wield: stored 1/1) or one of
    the three counters in UNGRADED that wear a graded skill's shape without
    being one.
    """
    return maximum <= PROFICIENCY_MAX or skill_id in UNGRADED


def percent(value: int, of: int) -> float | None:
    """`value` as a percentage of `of`, or None when there is no scale.

    Rounded to one place: the bars this feeds are a few hundred pixels wide,
    so more precision than that is noise a reader cannot see anyway.
    """
    if of <= 0:
        return None
    return round(100.0 * value / of, 1)


def skill_entry(row: dict, level: int, book: StandingBook) -> dict:
    """One `character_skills` row -> the line a person reads.

    The cap depends on what KIND of skill it is, and getting that wrong is
    the whole difficulty of this function:

      a proficiency  has no cap and no progress - it is known or it is not
      weapon/defence caps at level x 5, from the LEVEL, not the stored max
      everything else caps at the stored max, which for a trade is its
                     current tier (75 apprentice, 150 journeyman, ...)

    `stale_max` is set when a weapon row's stored ceiling disagrees with the
    level. That is a real thing the core does - the row is rewritten when
    the skill is next used, so a character who dinged and has not swung
    since carries yesterday's ceiling - and it is surfaced rather than
    quietly corrected, because it is also what a genuinely stuck skill
    would look like.
    """
    skill_id = int(row["skill"])
    value, maximum = int(row["value"]), int(row["max"])
    entry = book.skills.get(skill_id)
    category = entry["category"] if entry else CATEGORY_GENERIC
    group = skill_group(skill_id, category)
    out = {
        "id": skill_id,
        "name": book.skill_name(skill_id),
        "icon": entry["icon"] if entry else "",
        "group": group,
        "value": value,
        "max": maximum,
        "wowhead": wowhead("skill", skill_id),
        "proficiency": is_proficiency(skill_id, maximum),
        "stale_max": False,
    }
    if out["proficiency"]:
        # Known, and nothing else to say. No cap, no bar, no shortfall.
        out.update(cap=None, short_by=None, percent=None)
        return out
    if group in (GROUP_WEAPON, GROUP_DEFENCE):
        cap = level_cap(level)
        out["stale_max"] = maximum != cap
    else:
        cap = maximum
    out["cap"] = cap
    out["short_by"] = max(0, cap - value)
    out["percent"] = percent(value, cap)
    return out


def trade_entry(
    entry: dict, name: str, book: StandingBook, known_spells: frozenset[int]
) -> dict:
    """A profession's skill line plus what its owner can actually make.

    `known` is the recipes this character holds; `total` is every recipe the
    trade has at any rank. Both are reported, because "knows 0" and "knows 0
    of 264" are the same fact told at two very different volumes, and the
    second is the one that makes the point.

    `gathers` marks a trade that makes nothing by design - herbalism,
    skinning and fishing have no recipes at all, so "0 of 0" would read as
    a failure where the truth is that gathering is what they are for.
    """
    spells = book.by_skill.get(entry["id"], [])
    known = sorted(
        (s for s in spells if s in known_spells),
        key=lambda s: (book.recipes[s]["rank"], book.recipes[s]["name"]),
    )
    return {
        **entry,
        "trade": name,
        "recipes": {
            "known": len(known),
            "total": len(spells),
            "gathers": not spells,
            "makes": [
                {
                    "spell": s,
                    "name": book.recipes[s]["name"],
                    "rank": book.recipes[s]["rank"],
                    # The recipe links to the ITEM it makes when it makes one,
                    # because that is the thing a person wants the tooltip for.
                    # An enchant makes no item and links to the spell instead.
                    "wowhead": (
                        wowhead("item", book.recipes[s]["creates"])
                        if book.recipes[s]["creates"]
                        else wowhead("spell", s)
                    ),
                }
                for s in known
            ],
        },
    }


def reputation_rank(total: int) -> int:
    """A reputation total -> its rank index, by the core's own walk.

    ReputationMgr::ReputationToRank: start above exalted and subtract each
    rank's width from the top down, returning the first rank whose floor the
    total has reached.
    """
    limit = REPUTATION_CAP + 1
    for index in range(len(RANK_NAMES) - 1, -1, -1):
        limit -= POINTS_IN_RANK[index]
        if total >= limit:
            return index
    return 0


def rank_floor(index: int) -> int:
    """The lowest total that still counts as this rank."""
    limit = REPUTATION_CAP + 1
    for i in range(len(RANK_NAMES) - 1, index - 1, -1):
        limit -= POINTS_IN_RANK[i]
    return limit


def base_reputation(entry: dict, race: int, class_id: int) -> int:
    """The reputation a character of this race and class STARTS with.

    ReputationMgr::GetBaseReputation, condition for condition. The four
    entries are tried in order and the first whose masks match wins; an
    entry with no race mask but some class mask matches any race, which is
    how "every warrior" is spelled in Faction.dbc.

    This is not a rounding detail. An Alliance character's base with their
    own capitals is 3000 or 4000, so leaving it out moves four of the
    family's twenty-five standings into the wrong RANK - Grug reads Friendly
    instead of Honored with Stormwind.
    """
    race_mask = 1 << (race - 1) if race > 0 else 0
    class_mask = 1 << (class_id - 1) if class_id > 0 else 0
    for base_race, base_class, value in entry.get("base", []):
        race_ok = bool(base_race & race_mask) or (base_race == 0 and base_class != 0)
        class_ok = bool(base_class & class_mask) or base_class == 0
        if race_ok and class_ok:
            return value
    return 0


def met(flags: int) -> bool:
    """Has this character actually encountered the faction?

    Visible, and not hidden by either override. Every character carries a
    row for every faction in the game; this is what tells the five that
    matter from the hundred that do not.
    """
    return bool(flags & FLAG_VISIBLE) and not (
        flags & (FLAG_HIDDEN | FLAG_INVISIBLE_FORCED)
    )


def reputation_entry(row: dict, book: StandingBook, race: int, class_id: int) -> dict:
    """One `character_reputation` row -> a named standing with a bar."""
    faction_id = int(row["faction"])
    entry = book.factions.get(faction_id, {})
    total = base_reputation(entry, race, class_id) + int(row["standing"])
    total = min(REPUTATION_CAP, max(REPUTATION_BOTTOM, total))
    index = reputation_rank(total)
    floor = rank_floor(index)
    span = POINTS_IN_RANK[index]
    into = total - floor
    return {
        "faction": faction_id,
        "name": book.faction_name(faction_id),
        "rank": index,
        "standing": RANK_NAMES[index],
        "total": total,
        "into": into,
        "span": span,
        "percent": percent(into, span),
        # Hostile ranks are worth drawing differently; the page should not
        # have to know that rank 3 is the neutral line.
        "friendly": index >= NEUTRAL,
        "wowhead": wowhead("faction", faction_id),
    }


def spec_summary(
    class_id: int, level: int, talent_rows: list[dict], book: armory.TalentBook
) -> dict:
    """A pile of learned spell ids -> the build, named, without the grid.

    Reads armory's OWN TalentBook and its budget rule rather than repeating
    either. The Armory profile already draws the full eleven-by-four
    trainer grid; this is the other view of the same rows - which tree, how
    deep, and what is actually in it - so the two are different shapes of
    one fact, not two implementations of it.
    """
    trees = {
        tid: {
            "id": tid,
            "name": t["name"],
            "icon": t["icon"],
            "points": 0,
            "talents": [],
        }
        for tid, t in book.trees_for(class_id)
    }
    order = [tid for tid, _ in book.trees_for(class_id)]
    unknown, spent = [], 0
    for row in sorted(talent_rows, key=lambda r: int(r["spell"])):
        spell = int(row["spell"])
        found = book.by_spell.get(spell)
        if found is None:
            # A point that is genuinely spent on something the frozen table
            # does not know. Counted and named by its spell id, never
            # dropped: a build that silently reads two points short is worse
            # than one that admits which point it cannot explain.
            unknown.append(f"spell {spell}")
            spent += 1
            continue
        talent, rank = found
        spent += rank
        tid = str(talent["tree"])
        if tid not in trees:
            unknown.append(talent["name"])
            continue
        trees[tid]["points"] += rank
        trees[tid]["talents"].append(
            {
                "name": talent["name"],
                "icon": talent["icon"],
                "rank": rank,
                "max_rank": len(talent["ranks"]),
                "row": talent["row"],
                "col": talent["col"],
                "wowhead": wowhead("spell", talent["ranks"][rank - 1]),
            }
        )
    for tree in trees.values():
        tree["talents"].sort(key=lambda t: (t["row"], t["col"]))
    ordered = [trees[tid] for tid in order]
    available = armory.talent_points_at(level, class_id)
    deepest = max(ordered, key=lambda t: t["points"], default=None)
    return {
        "trees": ordered,
        "distribution": "/".join(str(t["points"]) for t in ordered),
        "primary": deepest["name"] if deepest and deepest["points"] else None,
        "spent": spent,
        "available": available,
        "unspent": None if available is None else max(0, available - spent),
        "unknown": unknown,
    }


def trade_gap(held: set[str], book: StandingBook) -> dict:
    """Which primary trades the FAMILY has nobody for.

    A per-member list cannot show this. Five cards each reading "alchemy,
    herbalism" look complete; only the union of them shows that eight of the
    ten primaries have no owner at all, which is the finding this view was
    built to surface.
    """
    ids = {name: goals.SKILL_IDS[name] for name in professions.PRIMARY}
    missing = sorted(professions.PRIMARY - held)
    return {
        "held": sorted(held & professions.PRIMARY),
        "missing": [
            {
                "trade": name,
                "name": book.skill_name(ids[name]),
                "icon": book.skills.get(ids[name], {}).get("icon", ""),
                "recipes": len(book.by_skill.get(ids[name], [])),
                "wowhead": wowhead("skill", ids[name]),
                "why": ENCHANTING_WHY if name == ENCHANTING else "",
            }
            for name in missing
        ],
        "enchanting": ENCHANTING in missing,
        "enchanting_why": ENCHANTING_WHY,
    }


def trade_panel(
    entries: list[dict], book: StandingBook, known_spells: frozenset[int]
) -> dict:
    """The trades a character holds, and what standing in the way of more.

    `slots_free` is zero for all five today, and that is the point: the
    world's ceiling is two primaries (professions.MAX_PRIMARY, which reads
    it off the core), so a missing trade is not something anybody can
    simply go and train.
    """
    primary, secondary = [], []
    for entry in entries:
        trade = _TRADE_NAMES.get(entry["id"])
        if trade is None:
            continue
        built = trade_entry(entry, trade, book, known_spells)
        (primary if trade in professions.PRIMARY else secondary).append(built)
    return {
        "primary": primary,
        "secondary": secondary,
        "max_primary": professions.MAX_PRIMARY,
        "slots_free": max(0, professions.MAX_PRIMARY - len(primary)),
        "blocking": [p["trade"] for p in primary],
    }


def skill_panel(entries: list[dict], level: int) -> dict:
    """The skill groups, and one number for how far off the cap they are.

    The trades are left OUT of the groups: they go under `professions` with
    their recipes attached, and two homes for one fact is two things to
    keep in step - the page would have to name a group to know which copy
    to skip, which is the one thing sending the group list exists to stop.
    """
    groups: dict[str, list] = {
        group: []
        for group in GROUP_ORDER
        if group not in (GROUP_PROFESSION, GROUP_SECONDARY)
    }
    for entry in entries:
        if entry["group"] in groups:
            groups[entry["group"]].append(entry)
    graded = [
        e
        for e in entries
        if e["group"] in (GROUP_WEAPON, GROUP_DEFENCE) and not e["proficiency"]
    ]
    return {
        "groups": [
            {"group": group, "skills": groups[group]}
            for group in GROUP_ORDER
            if groups.get(group)
        ],
        "cap": level_cap(level),
        # One number for the whole card: how far the graded combat skills
        # are, in total, from what this level allows. Proficiencies cannot
        # reach it, which is what keeps it from being permanently wrong.
        "short_by": sum(e["short_by"] for e in graded),
        "at_cap": all(not e["short_by"] for e in graded) if graded else True,
    }


def reputation_panel(
    reputation_rows: list[dict], book: StandingBook, race: int, class_id: int
) -> list[dict]:
    """Only the factions actually met, deepest standing first.

    Name breaks the tie so the order is stable between polls rather than
    reshuffling under a reader's thumb.
    """
    met_rows = [
        reputation_entry(row, book, race, class_id)
        for row in reputation_rows
        if met(int(row["flags"]))
    ]
    met_rows.sort(key=lambda r: (-r["total"], r["name"]))
    return met_rows


def active_talents(char_row: dict, talent_rows: list[dict]) -> list[dict]:
    """Only the build the character is actually playing.

    character_talent holds BOTH specs, told apart by specMask. Summing them
    reports twice the points actually spent - the same trap armory._member
    documents, and the same guard.
    """
    active = 1 << int(char_row.get("activeTalentGroup") or 0)
    return [r for r in talent_rows if int(r["specMask"]) & active]


def _member(
    name: str,
    char_row: dict | None,
    skill_rows: list[dict],
    reputation_rows: list[dict],
    talent_rows: list[dict],
    known_spells: frozenset[int],
    book: StandingBook,
    talents: armory.TalentBook,
) -> dict:
    # bond_of, not FAMILY: the Horde five have bonds of their own, and
    # FAMILY is only the family this process drives (bonds.member says why).
    bond = bonds.bond_of(name)
    if char_row is None:
        return {
            "name": name,
            "role": bond.role if bond else "",
            "class": bond.char_class.title() if bond else "",
            "present": False,
        }
    level = int(char_row["level"])
    race, class_id = int(char_row["race"]), int(char_row["class"])
    # Highest first, name breaking the tie: what has been worked at leads,
    # and the order does not move between polls.
    entries = sorted(
        (skill_entry(row, level, book) for row in skill_rows),
        key=lambda e: (-e["value"], e["name"]),
    )
    return {
        "name": char_row["name"],
        "role": bond.role if bond else "",
        "present": True,
        "faction": _faction(race),
        "level": level,
        "class": _CLASS_NAMES.get(class_id, f"class {class_id}"),
        "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
        "race": _RACE_NAMES.get(race, f"race {race}"),
        "professions": trade_panel(entries, book, known_spells),
        "skills": skill_panel(entries, level),
        "reputations": reputation_panel(reputation_rows, book, race, class_id),
        "spec": spec_summary(
            class_id, level, active_talents(char_row, talent_rows), talents
        ),
    }


def build_standing(
    char_rows: list[dict],
    skill_rows: list[dict],
    reputation_rows: list[dict],
    talent_rows: list[dict],
    spell_rows: list[dict],
    book: StandingBook,
    talents: armory.TalentBook,
    families: list[tuple[str, list[str]]] | None = None,
) -> dict:
    """Every member's standing, in roster order, one side per family.

    Rows arrive keyed by character name and unfiltered, exactly as
    build_armory takes them: splitting them per member is this module's job
    so the adapter stays queries and nothing else. A member with no rows
    still gets a card, for the reason the Armory tab gives - a family view
    that quietly drops somebody is the failure it exists to prevent.

    `families` is every family the roster knows, as (key, names); None is
    bonds' one family. Each family gets its own trade gap, because "nobody
    in the family has enchanting" is a claim about one family: the Horde
    five holding a trade does not close the Alliance five's gap.
    """
    if families is None:
        families = [("", family.roster())]
    chars = {r["name"]: r for r in char_rows}
    skills: dict[str, list[dict]] = {}
    for row in skill_rows:
        skills.setdefault(row["name"], []).append(row)
    reputations: dict[str, list[dict]] = {}
    for row in reputation_rows:
        reputations.setdefault(row["name"], []).append(row)
    talent_by_name: dict[str, list[dict]] = {}
    for row in talent_rows:
        talent_by_name.setdefault(row["name"], []).append(row)
    spells: dict[str, set[int]] = {}
    for row in spell_rows:
        spells.setdefault(row["name"], set()).add(int(row["spell"]))

    groups = []
    for key, names in families:
        mine = [
            _member(
                name,
                chars.get(name),
                skills.get(name, []),
                reputations.get(name, []),
                talent_by_name.get(name, []),
                frozenset(spells.get(name, set())),
                book,
                talents,
            )
            for name in names
        ]
        groups.append((key, mine))
    # Alliance left, Horde right, by the Armory's own rule, so the two panels
    # of one tab cannot put a family on different sides.
    sides = armory.family_sides(groups)
    for side in sides:
        mine = side.pop("members")
        held = {
            p["trade"]
            for m in mine
            if m["present"]
            for p in m["professions"]["primary"]
        }
        side["gap"] = trade_gap(held, book)
    members = [m for side in sides for m in _members_of(side, groups)]
    return {
        "members": members,
        "sides": sides,
        "expected": len(members),
        # The first side's gap, for a page that predates the sides.
        "gap": sides[0]["gap"] if sides else trade_gap(set(), book),
        "groups": list(GROUP_ORDER),
    }


def _members_of(side: dict, groups: list[tuple[str, list[dict]]]) -> list[dict]:
    """The members of one side, in their roster order."""
    for key, members in groups:
        if key == side["family"]:
            return members
    return []


def _faction(race: int) -> str:
    """The side a race fights for, in the Armory's words for it."""
    if race in armory._ALLIANCE_RACES:
        return "alliance"
    if race in armory._HORDE_RACES:
        return "horde"
    return "neutral"
