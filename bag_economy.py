"""The bags the family can MAKE, as opposed to the bags it was handed.

WHY THIS EXISTS. The family's two best bags per character are Netherweave
Bags, and they did not come from play. Measured on the realm 2026-09-05: a
single character named `Auctioneer` holds all 14,988 auction listings,
including 10 of the 16 Netherweave Bags that exist on it, and the family
bought the other 6. Netherweave is Outland cloth; the five are level 24 to 29.
Put precisely, in this realm's own numbers: `Netherweave Bag` is taught by
spell 26746 at tailoring 315, and 315 sits behind Master Tailoring, which
`trainer_spell` gates at character level 50. The family bought a bag 314 skill
points and roughly 24 character levels beyond anything it can reach. That is
what this module is the beginning of replacing.

Og is the tailor by the family's own roster (professions.ROSTER). His measured
tailoring on 2026-09-05 was `character_skills` value 1, max 75: Apprentice,
learned and never used once.

PURE MODULE, same seam as bag_upgrade.py, materials.py and professions.py:
tables in, arithmetic out. No MySQL, no bridge, no browser, nothing that writes
to the world. It decides; something else acts.

WHERE EVERY NUMBER BELOW CAME FROM
----------------------------------
Each row of `LADDER` mixes two kinds of fact, and they are not equally strong,
so they are recorded separately rather than blended.

FROM THIS REALM'S DATABASE, and therefore true for THIS realm:

  bag name, item entry, slots      acore_world.item_template, class=1
                                   subclass=0, column ContainerSlots
  skill rank, trainer-taught       acore_world.trainer_spell, ReqSkillLine=197,
                                   columns SpellId / ReqSkillRank / MoneyCost
  skill rank, pattern-taught       acore_world.item_template on the matching
                                   `Pattern: <bag>` row, columns
                                   RequiredSkillRank and spellid_2
  every reagent's item entry       acore_world.item_template by name
  the training tiers               acore_world.trainer_spell rows with
                                   ReqLevel > 0, which are the only five
  which reagents are bought        acore_world.npc_vendor, counted per item
  where each cloth drops           acore_world.creature_loot_template joined to
                                   creature_template, type=7 (humanoid),
                                   Chance >= 15

NOT AVAILABLE FROM THIS REALM'S DATABASE, which is worth knowing before anyone
tries again:

  spell -> created item      `acore_world.skilllineability_dbc` is EMPTY (0
                             rows) and `acore_world.spell_dbc` holds 4,492
                             custom rows containing NONE of the tailoring
                             recipes. `skilltiers_dbc` is empty too. So the
                             schema cannot say which trainer spell makes which
                             bag, and it carries no reagent list at all.
  reagent counts             same reason: reagents live in Spell.dbc, which
                             this deployment does not import.

So the recipe identities and the reagent counts were read off Wowhead's WotLK
(3.3.5a) data on 2026-09-05 and then CHECKED BACK against the realm, one
number at a time. All eleven checked. For the six pattern-taught recipes the
spell id equals `item_template.spellid_2` of the same-named pattern and the
rank equals its `RequiredSkillRank`; for the five trainer-taught recipes the
spell id appears in `trainer_spell` at exactly the stated rank; and every
produced bag's entry and ContainerSlots match `item_template`. Where the two
sources could disagree they did not, and where they could the realm wins.

THE SKILL CAPS. `skilltiers_dbc` being empty, the caps are derived instead:
every tier in `trainer_spell` is gated at `cap - 100` (50 for Journeyman's 150,
125 for Expert's 225, and so on up), and the realm's own `character_skills`
confirms 75, 150 and 225 as observed maxima. 300, 375 and 450 follow the same
arithmetic, and nobody on this realm is high enough to have shown one.

WHAT THIS MODULE DELIBERATELY DOES NOT ANSWER: how many crafts it takes to
raise a skill from one value to another. That needs the core's skill-up roll,
and guessing it would be exactly the kind of invented number the rest of this
docstring exists to avoid. The plan is expressed in crafts and in cloth per
craft, both of which are exact.
"""
from __future__ import annotations

from dataclasses import dataclass

# `Member` and `Bag` are already this service's answer to "what is a
# character's bag situation", and `deficit` wants the shape the bridge already
# builds for bag_upgrade.plan_family_bags. A second dataclass with the same
# four fields would be a second thing to keep in step.
from bag_upgrade import BAG_POSITIONS, Member  # noqa: F401  (re-exported)

TAILORING = 197


@dataclass(frozen=True)
class Reagent:
    """One line of a recipe, with the realm's item entry for it."""
    item: str
    entry: int
    count: int


@dataclass(frozen=True)
class Bolt:
    """A cloth-to-bolt conversion, which is where gathered cloth goes.

    The family loots CLOTH; every bag recipe consumes BOLTS. Nothing in the
    plan makes sense without this step, and it carries its own skill rank, so
    a tailor can be able to make a bag's bolts and not the bag.

    `grey` is the skill at which the craft stops teaching anything, and it is
    the reason bolts are the levelling craft at all: a bolt is the cheapest
    repeatable thing in the trade, and its grey says exactly how far it can
    carry a tailor before something else has to.
    """
    name: str
    entry: int
    cloth: str
    cloth_entry: int
    per_bolt: int
    spell: int
    rank: int
    grey: int


@dataclass(frozen=True)
class Rung:
    """One bag Og could make, and what is needed to decide whether to.

    `taught_by` is "trainer" or "pattern", and it is not decoration: a trainer
    rung costs `cost` copper at a tailoring trainer and is always available,
    while a pattern rung costs nothing to learn and everything to FIND, the
    pattern being a world drop. A planner that treated the two alike would
    queue an errand that cannot be finished.
    """
    bag: str
    entry: int
    slots: int
    rank: int
    spell: int
    taught_by: str
    cost: int = 0
    pattern: int = 0
    reagents: tuple = ()


@dataclass(frozen=True)
class Tier:
    """One tailoring training step: what it needs and what it unlocks."""
    name: str
    spell: int
    rank: int
    level: int
    cost: int
    cap: int


@dataclass(frozen=True)
class Band:
    """Where a cloth actually drops, in character levels.

    `lo` and `hi` are the lowest minlevel and highest maxlevel among HUMANOID
    creatures dropping it at 15% or better on this realm. Cloth comes off
    humanoids, so "who is likely to get this" is a question about who fights
    things in this band.
    """
    cloth: str
    entry: int
    lo: int
    hi: int
    kinds: int


# The five rows in `trainer_spell` with ReqLevel > 0. Apprentice is not among
# them because it is gated on nothing, and its cap is the 75 that Og's
# `character_skills` row already shows.
APPRENTICE = Tier("Apprentice Tailoring", 0, 0, 5, 0, 75)
TIERS = (
    APPRENTICE,
    Tier("Journeyman Tailoring", 3912, 50, 10, 500, 150),
    Tier("Expert Tailoring", 3913, 125, 20, 5000, 225),
    Tier("Artisan Tailoring", 12181, 200, 35, 50000, 300),
    Tier("Master Tailoring", 26791, 275, 50, 100000, 375),
    Tier("Grand Master Tailoring", 51308, 350, 65, 350000, 450),
)

# Bolt of Linen Cloth is the one recipe here that `trainer_spell` does not
# carry, because it is not sold: it arrives with Apprentice Tailoring itself.
# That is also why it is the only thing a skill-1 tailor can make, and its grey
# of 50 lands exactly on the rank Journeyman is gated at.
BOLTS = {
    2996: Bolt("Bolt of Linen Cloth", 2996, "Linen Cloth", 2589, 2, 2963, 1,
               50),
    2997: Bolt("Bolt of Woolen Cloth", 2997, "Wool Cloth", 2592, 3, 2964, 75,
               105),
    4305: Bolt("Bolt of Silk Cloth", 4305, "Silk Cloth", 4306, 4, 3839, 125,
               145),
    4339: Bolt("Bolt of Mageweave", 4339, "Mageweave Cloth", 4338, 4, 3865,
               175, 185),
    14048: Bolt("Bolt of Runecloth", 14048, "Runecloth", 14047, 4, 18401, 250,
                260),
    21840: Bolt("Bolt of Netherweave", 21840, "Netherweave Cloth", 21877, 5,
                26745, 300, 325),
}

# Vendors stock threads and dyes in bulk on this realm (87 to 186 vendors
# each); cloth and leather are stocked by one vendor or none. The split is
# therefore measured, not assumed, and it is what lets `shopping_list` say
# which reagents are a walk to a trade supplier and which are a fight.
_STOCKED = frozenset({2320, 2321, 4291, 8343, 14341, 2604, 2605, 2325})


def _r(item, entry, count=1):
    return Reagent(item, entry, count)


# Ordered by the rank that unlocks it, which is the order Og meets them in.
LADDER = (
    Rung("Linen Bag", 4238, 6, 45, 3755, "trainer", cost=100, reagents=(
        _r("Bolt of Linen Cloth", 2996, 3), _r("Coarse Thread", 2320, 3))),
    Rung("Red Linen Bag", 5762, 6, 70, 6686, "pattern", pattern=5771,
         reagents=(_r("Bolt of Linen Cloth", 2996, 4), _r("Fine Thread", 2321),
                   _r("Red Dye", 2604))),
    Rung("Woolen Bag", 4240, 8, 80, 3757, "trainer", cost=200, reagents=(
        _r("Bolt of Woolen Cloth", 2997, 3), _r("Fine Thread", 2321))),
    Rung("Green Woolen Bag", 4241, 8, 95, 3758, "pattern", pattern=4292,
         reagents=(_r("Bolt of Woolen Cloth", 2997, 4), _r("Green Dye", 2605),
                   _r("Fine Thread", 2321))),
    Rung("Red Woolen Bag", 5763, 8, 115, 6688, "pattern", pattern=5772,
         reagents=(_r("Bolt of Woolen Cloth", 2997, 4), _r("Red Dye", 2604),
                   _r("Fine Thread", 2321))),
    Rung("Small Silk Pack", 4245, 10, 150, 3813, "trainer", cost=800,
         reagents=(_r("Bolt of Silk Cloth", 4305, 3),
                   _r("Heavy Leather", 4234, 2), _r("Fine Thread", 2321, 3))),
    Rung("Green Silk Pack", 5764, 10, 175, 6693, "pattern", pattern=5774,
         reagents=(_r("Bolt of Silk Cloth", 4305, 4),
                   _r("Heavy Leather", 4234, 3), _r("Fine Thread", 2321, 3),
                   _r("Green Dye", 2605))),
    Rung("Black Silk Pack", 5765, 10, 185, 6695, "pattern", pattern=5775,
         reagents=(_r("Bolt of Silk Cloth", 4305, 5), _r("Black Dye", 2325),
                   _r("Fine Thread", 2321, 4))),
    Rung("Mageweave Bag", 10050, 12, 225, 12065, "trainer", cost=5000,
         reagents=(_r("Bolt of Mageweave", 4339, 4),
                   _r("Silken Thread", 4291, 2))),
    Rung("Runecloth Bag", 14046, 14, 260, 18405, "pattern", pattern=14468,
         reagents=(_r("Bolt of Runecloth", 14048, 5),
                   _r("Rugged Leather", 8170, 2), _r("Rune Thread", 14341))),
    Rung("Netherweave Bag", 21841, 16, 315, 26746, "trainer", cost=15000,
         reagents=(_r("Bolt of Netherweave", 21840, 4),
                   _r("Rune Thread", 14341))),
)

CLOTH_BANDS = {
    2589: Band("Linen Cloth", 2589, 5, 26, 396),
    2592: Band("Wool Cloth", 2592, 10, 32, 308),
    4306: Band("Silk Cloth", 4306, 23, 65, 462),
    4338: Band("Mageweave Cloth", 4338, 23, 57, 236),
    14047: Band("Runecloth", 14047, 48, 80, 568),
    21877: Band("Netherweave Cloth", 21877, 56, 73, 483),
}


# ---------------------------------------------------------------- the ladder

def tier_for(cap: int) -> Tier:
    """The training tier a measured `character_skills.max` corresponds to.

    Reads the cap rather than the value, because the cap is what a tier grants
    and the value is only how far along it the tailor is. Anything
    unrecognised falls back to Apprentice: a strange cap should make the
    planner cautious, not make it throw.
    """
    for tier in reversed(TIERS):
        if cap >= tier.cap:
            return tier
    return APPRENTICE


def next_tier(cap: int) -> Tier | None:
    """The training step above `cap`, or None at Grand Master."""
    for tier in TIERS:
        if tier.cap > cap:
            return tier
    return None


def can_train(tier: Tier, skill: int, level: int, money: int) -> bool:
    """Whether a trainer would actually teach `tier` right now.

    All three gates are the trainer's own, out of `trainer_spell`: the skill
    rank, the character level and the price. Money is checked here because a
    plan that says "train" to a tailor who cannot pay is a plan that stalls at
    the trainer with the walk already spent.
    """
    return skill >= tier.rank and level >= tier.level and money >= tier.cost


def reachable_cap(level: int) -> int:
    """The highest cap `level` allows, ignoring skill and money.

    This is the ceiling that matters for the family right now: Artisan needs
    character level 35, so a level 26 tailor cannot pass 225 however much
    cloth he burns. It is why the Netherweave Bags they own are not a target.
    """
    best = APPRENTICE.cap
    for tier in TIERS:
        if level >= tier.level:
            best = max(best, tier.cap)
    return best


def craftable(skill: int, *, known=()) -> tuple:
    """Every rung Og can make at `skill` this second.

    A pattern rung is craftable only once the pattern has been learned, so it
    is included only when its spell id is in `known`. That is the whole
    difference between "he has the skill" and "he has the recipe", and
    collapsing it would make the planner promise bags nobody can start.
    """
    known = set(known)
    return tuple(r for r in LADDER
                 if r.rank <= skill
                 and (r.taught_by == "trainer" or r.spell in known))


def within_reach(level: int) -> tuple:
    """Every rung `level` could ever reach, however much skill is ground out."""
    cap = reachable_cap(level)
    return tuple(r for r in LADDER if r.rank <= cap)


def levelling_craft(skill: int) -> Bolt | None:
    """The bolt that still teaches something at `skill`, if any.

    Bolts are the levelling craft because they are the cheapest repeatable
    thing in the trade and the family already loots their input. None means
    the bolt chain has run dry at this skill and the tailor has to make
    GARMENTS to climb: that really happens, between the linen bolt's grey at
    50 and the woolen bolt's rank of 75, and a planner that pretended
    otherwise would send Og to grind a recipe the world has stopped paying.
    """
    for bolt in sorted(BOLTS.values(), key=lambda b: -b.rank):
        if bolt.rank <= skill < bolt.grey:
            return bolt
    return None


# --------------------------------------------------------------- the deficit

@dataclass(frozen=True)
class Deficit:
    """What one character would gain from one more bag of a given size.

    `weakest` is the worn bag the new one would displace, and it is the whole
    measurement: a character with an empty bag position gains the new bag's
    full size, and a character whose smallest worn bag is already bigger gains
    nothing at all and must not be sent one.
    """
    who: str
    worn_slots: int
    weakest: int
    empty_positions: int
    gain: int


def _worn_sizes(member) -> list:
    return sorted(bag.slots for bag in member.worn)


def deficit(members, slots: int) -> tuple:
    """Rank the family by what a `slots`-slot bag would be worth to each.

    Sorted by gain, then by how little the character carries overall, then by
    name. The middle key breaks the tie that matters: two characters both
    replacing a 6 should be served in the order of who has less room in total.
    The last key exists only so the answer is stable between runs.
    """
    out = []
    for member in members:
        sizes = _worn_sizes(member)
        empty = max(0, member.positions - len(sizes))
        weakest = sizes[0] if sizes else 0
        gain = slots if empty else max(0, slots - weakest)
        out.append(Deficit(member.name, sum(sizes), weakest, empty, gain))
    return tuple(sorted(out, key=lambda d: (-d.gain, d.worn_slots, d.who)))


def worth_making(members, slots: int) -> tuple:
    """Only the characters a `slots` bag would actually help."""
    return tuple(d for d in deficit(members, slots) if d.gain > 0)


def first_useful_rung(members, level: int | None = None, *,
                      known=()) -> Rung | None:
    """The lowest rung that would be an upgrade for somebody.

    LOWEST, not biggest, on purpose. The biggest bag is what the family wants
    eventually; the lowest useful one is what it can have next, and this
    module's job is the next step. A rung that helps nobody is skipped
    outright, which is how `Linen Bag` (6 slots) drops out: every measured
    character already wears at least a 6.

    `level` is an optional ceiling, and leaving it off is the useful default.
    A target the tailor's level cannot reach is still the right ANSWER - it is
    what turns "nothing to do" into "Artisan Tailoring needs level 35" - so
    the ceiling belongs in the explanation rather than in the search.
    """
    known = set(known)
    rungs = LADDER if level is None else within_reach(level)
    for rung in rungs:
        if rung.taught_by == "pattern" and rung.spell not in known:
            continue
        if worth_making(members, rung.slots):
            return rung
    return None


# ------------------------------------------------------------- the gathering

def cloth_for(rung: Rung) -> Band | None:
    """The cloth a rung eats, walked through its bolt."""
    for reagent in rung.reagents:
        bolt = BOLTS.get(reagent.entry)
        if bolt is not None:
            return CLOTH_BANDS.get(bolt.cloth_entry)
    return None


def raw_cost(rung: Rung, count: int = 1) -> dict:
    """Everything `count` of `rung` needs, expanded down to gathered cloth.

    Bolts are replaced by the cloth they are made of, because bolts are not
    lootable and cloth is: a shopping list denominated in bolts tells the
    family to find something no creature drops. Keyed by item entry so a
    caller can match it against an inventory without matching on names.
    """
    need: dict = {}
    for reagent in rung.reagents:
        want = reagent.count * count
        bolt = BOLTS.get(reagent.entry)
        if bolt is None:
            need[reagent.entry] = need.get(reagent.entry, 0) + want
        else:
            entry = bolt.cloth_entry
            need[entry] = need.get(entry, 0) + want * bolt.per_bolt
    return need


def _reagent_names() -> dict:
    names = {b.cloth_entry: b.cloth for b in BOLTS.values()}
    for rung in LADDER:
        for reagent in rung.reagents:
            names.setdefault(reagent.entry, reagent.item)
    return names


def shopping_list(rung: Rung, count: int = 1, held=None) -> tuple:
    """What is still missing, split into what is bought and what is fought.

    Returns (entry, name, short, how) rows, `how` being "buy" for the threads
    and dyes every trade supplier stocks and "gather" for cloth and leather.
    The split is measured from `npc_vendor` (see `_STOCKED`), and it matters
    because the two halves are completely different errands: one is a walk to
    a town, the other is a decision about what to kill.
    """
    held = dict(held or {})
    names = _reagent_names()
    rows = []
    for entry, want in sorted(raw_cost(rung, count).items()):
        short = want - held.get(entry, 0)
        if short > 0:
            rows.append((entry, names.get(entry, str(entry)), short,
                         "buy" if entry in _STOCKED else "gather"))
    return tuple(rows)


def gatherers(band: Band, levels) -> tuple:
    """Who is level-appropriate for the humanoids that drop this cloth.

    A character far above the band is not a better farmer, he is a worse one:
    grey mobs are the ones that stop dropping. So the answer is membership of
    the band, not "the highest level", and it comes back in the order the
    family should be asked.
    """
    inside = [(name, lvl) for name, lvl in levels.items()
              if band.lo <= lvl <= band.hi]
    return tuple(name for name, _ in sorted(inside, key=lambda p: (-p[1],
                                                                  p[0])))


# ------------------------------------------------------------- the next step

@dataclass(frozen=True)
class Step:
    """The one thing to do next, and the sentence that explains it.

    `kind` is "train", "learn", "gather" or "craft". A caller that understands
    none of them should still be able to show `said`, which is why the
    sentence is part of the answer rather than something a UI reassembles.
    """
    kind: str
    said: str
    rung: Rung | None = None
    tier: Tier | None = None
    item: int = 0
    count: int = 0
    who: tuple = ()


def coin(amount: int) -> str:
    """Copper as a person reads it, so a plan can quote a trainer's price."""
    gold, rest = divmod(amount, 10000)
    silver, copper = divmod(rest, 100)
    parts = [f"{gold}g"] if gold else []
    if silver:
        parts.append(f"{silver}s")
    if copper or not parts:
        parts.append(f"{copper}c")
    return " ".join(parts)


def next_step(*, tailor, skill, cap, level, money, members, levels,
              held=None, known=()) -> Step:
    """One recommendation, chosen in the order the world imposes.

    The order is not a preference, it is the sequence of gates: a tailor
    cannot pass his cap, cannot craft a recipe he was never taught, and cannot
    craft anything without the reagents. So training comes before learning,
    learning before gathering, gathering before the craft, and the first gate
    that is actually shut is the answer.
    """
    target = first_useful_rung(members, known=known)
    if target is None:
        return Step("craft", f"{tailor} has no bag worth making: every rung "
                             "within reach is already matched or beaten by "
                             "what the family wears.")

    if target.rank > cap:
        tier = next_tier(cap)
        if tier is None:
            return Step("train", f"{tailor} needs tailoring {target.rank} for "
                                 f"{target.bag} and has no tier left to "
                                 "train.", rung=target)
        if can_train(tier, skill, level, money):
            return Step("train", f"{tailor} trains {tier.name} for "
                                 f"{coin(tier.cost)}, raising his cap from "
                                 f"{cap} to {tier.cap} and putting "
                                 f"{target.bag} at tailoring {target.rank} in "
                                 "reach.", rung=target, tier=tier)
        if skill < tier.rank:
            bolt = levelling_craft(skill)
            how = (f" {bolt.name} still pays at this skill and stops at "
                   f"{bolt.grey}; each one eats {bolt.per_bolt} "
                   f"{bolt.cloth}." if bolt else
                   " No bolt pays at this skill, so the climb has to come "
                   "off the trainer's garment recipes.")
            return Step("train", f"{tailor} must raise tailoring from {skill} "
                                 f"to {tier.rank} before a trainer will teach "
                                 f"{tier.name}. He is capped at {cap} until "
                                 f"then, and {target.bag} needs "
                                 f"{target.rank}.{how}",
                        rung=target, tier=tier,
                        item=bolt.cloth_entry if bolt else 0)
        if level < tier.level:
            return Step("train", f"{tailor} is level {level} and {tier.name} "
                                 f"needs level {tier.level}, so {target.bag} "
                                 "is out of reach until he levels.",
                        rung=target, tier=tier)
        return Step("train", f"{tailor} cannot afford {tier.name} at "
                             f"{coin(tier.cost)}.", rung=target, tier=tier)

    if target.taught_by == "pattern" and target.spell not in set(known):
        return Step("learn", f"{tailor} needs the pattern for {target.bag} "
                             f"(item {target.pattern}); it is a world drop, "
                             "not a trainer purchase.", rung=target)

    if target.rank > skill:
        return Step("train", f"{tailor} is at tailoring {skill} and "
                             f"{target.bag} needs {target.rank}. His cap is "
                             f"{cap}, so the skill is the only thing in the "
                             "way.", rung=target)

    missing = shopping_list(target, 1, held)
    for entry, name, short, how in missing:
        if how != "gather":
            continue
        band = CLOTH_BANDS.get(entry)
        who = gatherers(band, levels) if band else ()
        where = (f", which drops from humanoids level {band.lo} to {band.hi}"
                 if band else "")
        asked = (f" Ask {', '.join(who)}." if who
                 else " Nobody in the family is in that level band.")
        return Step("gather", f"{tailor} needs {short} more {name}{where}, "
                              f"for one {target.bag}.{asked}",
                    rung=target, item=entry, count=short, who=who)
    if missing:
        entry, name, short, _ = missing[0]
        return Step("gather", f"{tailor} needs {short} more {name} for one "
                              f"{target.bag}; a trade supplier stocks it.",
                    rung=target, item=entry, count=short)

    return Step("craft", f"{tailor} makes one {target.bag} "
                         f"({target.slots} slots).", rung=target)
