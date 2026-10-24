"""Dark Iron plate: the plans, the reputation, the forge and the anvil (#480).

WHY THIS EXISTS. A tank's fire resistance post-raid set is five Dark Iron
pieces, and `fireplan` already names them as the next upgrade. What it could
not say is how a family gets one: the plans are not trained and not dropped,
they are sold by Lokhtos Darkbargainer inside Blackrock Depths for Thorium
Brotherhood reputation, and the bars they need can only be smelted at the
Black Forge. The Raid tab said "which nobody in the guild holds yet" and
stopped there. This module is the road, in the order a family walks it.

THE ROAD, IN FOUR GATES.

  1. REPUTATION. Lokhtos sells each plan at a rank, Friendly through Exalted.
     Reputation is earned in three stages, and only the last is his. The
     Restoring Fiery Flux Supplies turn-ins from Master Smith Burninate at
     Thorium Point reach Friendly, his Gaining Acceptance turn-ins (Dark Iron
     Residue) reach Honored, and Lokhtos' own Favor Amongst the Brotherhood
     turn-ins (Dark Iron Ore, Fiery Core, Lava Core, Core Leather, Blood of
     the Mountain) reach Revered and Exalted. The plan names the stage and its
     materials; it does not name a number of turn-ins, because the per-turn-in
     reputation is a realm fact and the realm's quest_template is the
     authority.

  2. THE PLAN. The plan item itself, bought from Lokhtos. No plan is trained.

  3. THE BARS. Smelt Dark Iron (spell 14891) is learned from The Spectral
     Chalice, a quest object beside Gloom'rel in the Summoners' Tomb, and it
     needs Mining 230 plus 20 Gold Bar, 10 Truesilver Bar and 2 Star Ruby.
     Eight Dark Iron Ore make one bar, and the smelt only works at the Black
     Forge (SpellFocusObject 543), not at an ordinary forge.

  4. THE PIECE. Every smithed Dark Iron piece is made at the Black Anvil in
     Blackrock Depths. That is a different focus from the Black Forge, and
     `craft.FOCUS_AIMS` carries no id for it yet, so this module plans the
     craft but does not hand the bridge a walk it cannot verify.

WHAT IS MEASURED AND WHAT IS NOT. The pieces, their craft spells, their fire
resistance and their reagents are from `data/bis/items.json` and the classic
spell pages. The plan item ids are 17051 (bracers), 19206 (helm), 17052
(leggings), 19207 (gauntlets) and 20040 (boots). The item book gives those
crafts skill 315 or 320, which is a later-era number: the classic cap is 300,
and the realm's own item_template is the authority for what its plans teach.
`skill_note` says so rather than pretending either number is measured here.

PURE MODULE: no MySQL, no clock. Constants and counts in, a named next step
and sentences out.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- the place --------------------------------------------------------------

LOKHTOS = 12944  # Lokhtos Darkbargainer, Grim Guzzler
BURNINATE = 14624  # Master Smith Burninate, Thorium Point
THORIUM_BROTHERHOOD = 59
BLACK_FORGE = 543  # the SpellFocusObject Smelt Dark Iron requires
SMELT_DARK_IRON = 14891
SPECTRAL_CHALICE = 4083  # the quest that teaches Smelt Dark Iron

# --- the items --------------------------------------------------------------

DARK_IRON_ORE = 11370
DARK_IRON_BAR = 11371
FIERY_CORE = 17010
LAVA_CORE = 17011
CORE_LEATHER = 17012
BLOOD_OF_THE_MOUNTAIN = 11382
DARK_IRON_RESIDUE = 18945
GOLD_BAR = 3577
TRUESILVER_BAR = 6037
STAR_RUBY = 7910
INCENDOSAUR_SCALE = 18944
IRON_BAR = 3575
HEAVY_LEATHER = 4234
KINGSBLOOD = 3820
COAL = 3857

ORE_PER_BAR = 8
SMELT_TEACHING = ((GOLD_BAR, 20), (TRUESILVER_BAR, 10), (STAR_RUBY, 2))

# The classic profession cap. The item book's 315 and 320 are later-era values.
CLASSIC_SKILL = 300

# --- the reputation ladder --------------------------------------------------

NEUTRAL, FRIENDLY, HONORED, REVERED, EXALTED = (
    "Neutral",
    "Friendly",
    "Honored",
    "Revered",
    "Exalted",
)
RANKS = (
    (NEUTRAL, 0),
    (FRIENDLY, 3000),
    (HONORED, 9000),
    (REVERED, 21000),
    (EXALTED, 42000),
)
RANK_VALUE = dict(RANKS)
RANK_ORDER = {name: i for i, (name, _points) in enumerate(RANKS)}

# The three repeatable stages of the reputation, and the rank each reaches.
# `options` is what one turn-in accepts: one tuple per acceptable turn-in.
@dataclass(frozen=True)
class Route:
    rank: str
    where: str
    quest: str
    materials: str
    options: tuple

    def said(self, rank: str) -> str:
        return "reach %s with the Thorium Brotherhood by repeating %s (%s) with %s" % (
            rank,
            self.quest,
            self.materials,
            self.where,
        )


FLUX = Route(
    FRIENDLY,
    "Master Smith Burninate at Thorium Point in the Searing Gorge",
    "the Restoring Fiery Flux Supplies turn-ins",
    "Iron, Kingsblood or Heavy Leather",
    (
        ((INCENDOSAUR_SCALE, 2), (IRON_BAR, 4), (COAL, 1)),
        ((INCENDOSAUR_SCALE, 2), (KINGSBLOOD, 2), (COAL, 4)),
        ((INCENDOSAUR_SCALE, 2), (HEAVY_LEATHER, 10), (COAL, 1)),
    ),
)
ACCEPTANCE = Route(
    HONORED,
    "Master Smith Burninate at Thorium Point in the Searing Gorge",
    "Gaining Acceptance",
    "4 Dark Iron Residue",
    (((DARK_IRON_RESIDUE, 4),),),
)
FAVOR = Route(
    EXALTED,
    "Lokhtos Darkbargainer in Blackrock Depths",
    "the Favor Amongst the Brotherhood turn-ins",
    "Dark Iron Ore, Fiery Core, Lava Core, Core Leather or Blood of the Mountain",
    (
        ((DARK_IRON_ORE, 10),),
        ((FIERY_CORE, 1),),
        ((LAVA_CORE, 1),),
        ((CORE_LEATHER, 2),),
        ((BLOOD_OF_THE_MOUNTAIN, 1),),
    ),
)
ROUTES = (FLUX, ACCEPTANCE, FAVOR)


@dataclass(frozen=True)
class Plan:
    """One Dark Iron piece and everything standing between a family and it."""

    entry: int  # the plan item Lokhtos sells
    name: str  # "Plans: Dark Iron Helm"
    rank: str  # the Thorium Brotherhood rank that unlocks it
    teaches: int  # the craft spell the plan teaches
    piece: int  # the item the craft makes
    piece_name: str
    slot: str  # the situational slot name
    fire: int
    bars: int
    reagents: tuple  # ((item entry, count), ...) besides the bars


# In the order the reputation ladder unlocks them, then heaviest first within
# a rank. This is the order a family buys and makes them, not the order a
# reader ranks their fire resistance.
PLANS = (
    Plan(
        17051,
        "Plans: Dark Iron Bracers",
        FRIENDLY,
        20874,
        17014,
        "Dark Iron Bracers",
        "wrist",
        18,
        4,
        ((FIERY_CORE, 2), (LAVA_CORE, 2)),
    ),
    Plan(
        19206,
        "Plans: Dark Iron Helm",
        HONORED,
        23636,
        19148,
        "Dark Iron Helm",
        "head",
        35,
        4,
        ((LAVA_CORE, 4), (FIERY_CORE, 2)),
    ),
    Plan(
        17052,
        "Plans: Dark Iron Leggings",
        REVERED,
        20876,
        17013,
        "Dark Iron Leggings",
        "legs",
        30,
        16,
        ((FIERY_CORE, 4), (LAVA_CORE, 6)),
    ),
    Plan(
        19207,
        "Plans: Dark Iron Gauntlets",
        REVERED,
        23637,
        19164,
        "Dark Iron Gauntlets",
        "hands",
        28,
        4,
        (
            (LAVA_CORE, 3),
            (FIERY_CORE, 5),
            (CORE_LEATHER, 4),
            (BLOOD_OF_THE_MOUNTAIN, 2),
        ),
    ),
    Plan(
        20040,
        "Plans: Dark Iron Boots",
        EXALTED,
        24399,
        20039,
        "Dark Iron Boots",
        "feet",
        28,
        6,
        ((LAVA_CORE, 3), (FIERY_CORE, 3), (CORE_LEATHER, 4)),
    ),
)
BY_PLAN = {p.entry: p for p in PLANS}
BY_PIECE = {p.piece: p for p in PLANS}
BY_SPELL = {p.teaches: p for p in PLANS}

ITEM_NAMES = {
    DARK_IRON_ORE: "Dark Iron Ore",
    DARK_IRON_BAR: "Dark Iron Bar",
    FIERY_CORE: "Fiery Core",
    LAVA_CORE: "Lava Core",
    CORE_LEATHER: "Core Leather",
    BLOOD_OF_THE_MOUNTAIN: "Blood of the Mountain",
    GOLD_BAR: "Gold Bar",
    TRUESILVER_BAR: "Truesilver Bar",
    STAR_RUBY: "Star Ruby",
}

# The turn-in items, in the order Lokhtos offers them.
TURNIN_NAMES = (
    "Dark Iron Ore, Fiery Core, Lava Core, Core Leather and Blood of the Mountain"
)

ROAD = (
    "Dark Iron plate (blacksmithing): Lokhtos Darkbargainer in Blackrock "
    "Depths sells the plans by Thorium Brotherhood rank, Friendly to Exalted; "
    "the bars are smelted at the Black Forge and every piece is made at the "
    "Black Anvil"
)

GRIND = "grind"
BUY = "buy"
LEARN = "learn"
SMELT = "smelt"
GATHER = "gather"
CRAFT = "craft"


@dataclass(frozen=True)
class Step:
    """The one thing to do next, and the plan it is for."""

    kind: str
    said: str
    plan: Plan | None = None


@dataclass(frozen=True)
class Pipeline:
    """The next step on the Dark Iron road, or none when every piece is made."""

    step: Step | None
    plan: Plan | None

    @property
    def done(self) -> bool:
        return self.step is None

    @property
    def line(self) -> str:
        if self.step is None:
            return "Dark Iron plate: every piece is made"
        return "Dark Iron plate: next %s" % self.step.said


def rank_index(rank: str) -> int:
    """The ladder position of `rank`, or -1 for a name not on it."""
    return RANK_ORDER.get(str(rank or ""), -1)


def rank_of(points: int) -> str:
    """The highest rank `points` reaches."""
    reached = NEUTRAL
    for name, need in RANKS:
        if int(points or 0) >= need:
            reached = name
    return reached


def skill_note() -> str:
    """What the item book says about these plans, and why it is not the last
    word: the classic cap is 300 and the realm's item_template decides."""
    return (
        "the item book gives these plans skill 315 or 320, past the classic cap "
        "of %d; read the realm's item_template for what they teach" % CLASSIC_SKILL
    )


def _counts(held) -> dict:
    return {int(entry): int(count) for entry, count in (held or {}).items()}


def _short(counts: dict, wanted) -> tuple:
    """The (entry, missing) pairs of `wanted` the counts do not cover."""
    out = []
    for entry, need in wanted:
        missing = int(need) - counts.get(int(entry), 0)
        if missing > 0:
            out.append((int(entry), missing))
    return tuple(out)


def _said(short) -> str:
    return " and ".join(
        "%d %s" % (count, ITEM_NAMES.get(entry, "item %d" % entry))
        for entry, count in short
    )


def next_plan(known=(), made=()) -> Plan | None:
    """The first piece not yet bought or made, in ladder order."""
    known = {int(e) for e in known or ()}
    made = {int(e) for e in made or ()}
    for plan in PLANS:
        if plan.entry not in known or plan.piece not in made:
            return plan
    return None


def plan(known=(), rank=NEUTRAL, held=None, smelt_known=False, made=()) -> Pipeline:
    """The next step toward the first Dark Iron piece still missing.

    `known` is the plan items the guild has bought and learned, `made` the
    piece items already worn, `rank` the guild's Thorium Brotherhood rank (a
    name or a point total), `held` a count per item entry, and `smelt_known`
    whether Smelt Dark Iron has been learned.
    """
    if isinstance(rank, int):
        rank = rank_of(rank)
    target = next_plan(known, made)
    if target is None:
        return Pipeline(None, None)

    known = {int(e) for e in known or ()}
    counts = _counts(held)

    if target.entry not in known:
        if rank_index(rank) < rank_index(target.rank):
            return Pipeline(
                Step(
                    GRIND,
                    "reach %s with the Thorium Brotherhood (faction %d) by "
                    "turning in %s to Lokhtos (npc %d) in Blackrock Depths, "
                    "then buy %s"
                    % (
                        target.rank,
                        THORIUM_BROTHERHOOD,
                        TURNIN_NAMES,
                        LOKHTOS,
                        target.name,
                    ),
                    target,
                ),
                target,
            )
        return Pipeline(
            Step(
                BUY,
                "buy %s from Lokhtos Darkbargainer (npc %d) in Blackrock "
                "Depths (Thorium Brotherhood %s)" % (target.name, LOKHTOS, target.rank),
                target,
            ),
            target,
        )

    if not smelt_known:
        return Pipeline(
            Step(
                LEARN,
                "learn Smelt Dark Iron (spell %d) from The Spectral Chalice "
                "(quest %d) beside Gloom'rel in Blackrock Depths (Mining 230; "
                "%s)" % (SMELT_DARK_IRON, SPECTRAL_CHALICE, _said(SMELT_TEACHING)),
                target,
            ),
            target,
        )

    missing_bars = target.bars - counts.get(DARK_IRON_BAR, 0)
    if missing_bars > 0:
        return Pipeline(
            Step(
                SMELT,
                "smelt %d Dark Iron Bar%s at the Black Forge (SpellFocusObject "
                "%d) in Blackrock Depths (%d Dark Iron Ore)"
                % (
                    missing_bars,
                    "" if missing_bars == 1 else "s",
                    BLACK_FORGE,
                    missing_bars * ORE_PER_BAR,
                ),
                target,
            ),
            target,
        )

    short = _short(counts, target.reagents)
    if short:
        return Pipeline(
            Step(
                GATHER,
                "gather %s for %s" % (_said(short), target.piece_name),
                target,
            ),
            target,
        )

    return Pipeline(
        Step(
            CRAFT,
            "craft %s at the Black Anvil in Blackrock Depths" % target.piece_name,
            target,
        ),
        target,
    )


def source(piece: int) -> str:
    """Where a Dark Iron piece comes from, said for `fireplan`, or "" for a
    piece this module does not know."""
    plan_ = BY_PIECE.get(int(piece or 0))
    if plan_ is None:
        return ""
    return "made at the Black Anvil from %s (Thorium Brotherhood, %s)" % (
        plan_.name,
        plan_.rank,
    )
