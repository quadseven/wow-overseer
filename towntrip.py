"""What a town trip between two dungeon runs has to do (infra#3357).

Pure module, same seam as materials.py and questshare.py: facts in, a plan
out. bridge.py reads the durability, the bags, the purse and the spellbook,
calls plan(), and turns each Errand into one `overseer_command` row with
kind='repair' or kind='buy'. mod-overseer's DoRepair and DoBuy perform the
transactions and read the world back; nothing here touches the world.

WHY THIS EXISTS. The roster is set to a hundred runs of one instance
(overseer_roster.dungeon_runs_wanted = 100 for all five). A hundred runs
without maintenance is not a hundred runs: durability only ever falls, and
consumables were never bought in the first place. Measured on the live
roster on the day this was written:

    member  class    lvl  durability  worst item  food  drink  free slots
    Grug    warrior   29      99.5%       94.3%     0      0       14
    Grog    paladin   27      99.1%       96.7%     0      0        7
    Og      mage      26      99.7%       95.0%     0      0        9
    Bork    rogue     26     100.0%      100.0%     1      0        4
    Ugga    priest    24      99.4%       95.0%     0      0        4

Two things fall out of that table, and they are the two halves of this module.

DURABILITY IS NOT THE URGENT PROBLEM, YET. Ten missing points across nine
items, right after a full clear. It is easy to read that as "repair is not
needed" and wrong to: the loss is MONOTONIC and dominated by deaths, at 10%
of an item's maximum each, and this roster's death table holds over three
thousand rows across eight days. Ten deaths take an item from full to broken,
and a broken item contributes no stats at all. So the threshold below is not
about whether the gear is bad now; it is about how many deaths of headroom
the next run has.

CONSUMABLES ARE THE URGENT PROBLEM. Four of five carry no food and no drink,
and the two whose mana decides whether a dungeon finishes - the only healer
and the only mage - carry nothing to drink at all. A party with no water
spends most of an instance sitting on the floor waiting to regenerate.

WHAT THIS DECIDES AND WHAT IT DOES NOT. It answers "what does this trip have
to do", never "where is the town" (travel is its own errand and its own
verb), never "what should be sold" (that is the vendor-sell planner's
question, and it needs the whole family's bags at once), and never "can we
afford it" in gold, because the repair price comes out of DBC tables this
side cannot read. What it does instead is ORDER the errands so the money
arrives before it is spent, and report what the town cannot supply as a note
rather than as a purchase that will be refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Food and drink, by the level at which the next tier opens. Every row was
# read out of item_template: class 0, subclass 5, and spellcategory_1 of 11
# for food or 59 for drink. All six of each stack to 20 and every vendor that
# carries them carries an unlimited supply, which is what makes "one stack" a
# sane unit to buy. Keyed by required level so the rule below can be "the best
# tier this character is old enough for" and nothing more clever.
#
# Prices are the undiscounted BuyPrice in copper. They are used only to set
# the `max:` ceiling on the buy row; the reputation discount at the counter
# can only bring the real price DOWN, so a ceiling computed from these can
# never refuse a purchase that should have gone through.
FOOD = (
    (1, 787, "Slitherskin Mackerel", 25),
    (5, 4592, "Longjaw Mud Snapper", 20),
    (15, 4593, "Bristle Whisker Catfish", 500),
    (25, 4594, "Rockscale Cod", 1000),
    (35, 21552, "Striped Yellowtail", 2000),
    (45, 8957, "Spinefin Halibut", 4000),
)

DRINK = (
    (1, 159, "Refreshing Spring Water", 25),
    (5, 1179, "Ice Cold Milk", 125),
    (15, 1205, "Melon Juice", 500),
    (25, 1708, "Sweet Nectar", 1000),
    (35, 1645, "Moonberry Juice", 2000),
    (45, 8766, "Morning Glory Dew", 4000),
)

# A full stack, which is also exactly one bag slot. Buying less wastes the
# trip; buying more wastes a slot on a roster whose tightest member has four.
STACK = 20

# Which classes run on mana and therefore need something to drink. Named
# rather than derived, because "does this class drink" is a fact about the
# game and not about the row.
MANA_CLASSES = frozenset(
    {"priest", "mage", "paladin", "druid", "shaman", "hunter", "warlock"}
)

# The conjure ranks measured in this roster's own character_spell. A mage who
# knows one of these makes the thing for free and should not be sold it.
# Lower ranks stay in the spellbook when a higher one is learned, so this set
# keeps answering correctly as he levels; a rank nobody has measured yet only
# means a stack of water bought that was not needed, which is the safe way to
# be wrong.
CONJURE_FOOD = frozenset({587, 597, 990})
CONJURE_WATER = frozenset({5504, 5505, 5506})

# Spell reagents, keyed by the spell that consumes them. DELIBERATELY EMPTY.
# At the levels this roster is at, no class in it consumes a reagent: the
# priest's and paladin's reagent spells are all level 48 and up, the mage's
# Arcane Brilliance is 56, and a rogue's poisons are the only reagent-shaped
# consumable that applies below 40 - and the rogue on this roster knows no
# poison spell at all (character_spell has none of the poison ids). An empty
# table is the honest answer, and it is a table rather than a `return ()` so
# that the shape is here for when somebody measures one.
REAGENT_SPELLS: dict[int, tuple[int, str, int]] = {}

# Repair thresholds, and the argument for each.
#
# ANY_DAMAGE is why a repair is planned at all: the trip to town is happening
# anyway, repair cost is linear in the points missing so nothing is saved by
# waiting, and `repair all` is one row and a few copper. There is no reason
# to arrive at a repairer and not use it.
#
# FLOOR is the different question: below what point is it unsafe to start
# another run. One death costs 10% of an item's maximum. A run that wipes the
# party three times costs 30 points off a 100-point item, so a floor of 35%
# leaves three and a half deaths of headroom, which is about what a run on
# this roster actually costs. Above the floor a missed repair is untidy;
# below it, the next run can break something, and a broken item gives no
# stats at all.
ANY_DAMAGE = 1.0
FLOOR = 0.35


@dataclass(frozen=True)
class Equipped:
    """One worn item's durability, as item_instance holds it."""

    entry: int
    name: str
    durability: int
    max_durability: int

    @property
    def fraction(self) -> float:
        if self.max_durability <= 0:
            return 1.0
        return self.durability / self.max_durability


@dataclass(frozen=True)
class Member:
    """One character, as the database describes it right now."""

    name: str
    klass: str
    level: int
    money: int  # copper
    free_slots: int
    equipped: tuple[Equipped, ...] = ()
    food_carried: int = 0
    drink_carried: int = 0
    spells: frozenset[int] = frozenset()

    @property
    def durability(self) -> float:
        """Everything worn, as one fraction. 1.0 when nothing can wear out."""
        total = sum(e.max_durability for e in self.equipped)
        if total <= 0:
            return 1.0
        return sum(e.durability for e in self.equipped) / total

    @property
    def worst(self) -> float:
        """The item that breaks first. This is the number the floor is about."""
        wearable = [e for e in self.equipped if e.max_durability > 0]
        if not wearable:
            return 1.0
        return min(e.fraction for e in wearable)


@dataclass(frozen=True)
class Town:
    """What the town the party is standing in can actually do for them.

    Both fields are FACTS READ FROM THE WORLD, never assumptions: `repairs` is
    whether a reachable NPC carries the repair npcflag, and `stocks` is the
    set of item entries a reachable vendor's npc_vendor rows actually list.
    A planner that assumed either would produce rows the executor refuses.
    """

    repairs: bool = False
    stocks: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Errand:
    """One `overseer_command` row, ready to insert."""

    member: str
    kind: str  # 'repair' or 'buy'
    command: str
    why: str
    spend: int = 0  # copper ceiling; 0 when this side cannot price it


@dataclass(frozen=True)
class Plan:
    errands: tuple[Errand, ...] = ()
    notes: tuple[str, ...] = ()
    blocked: tuple[str, ...] = field(default=())


def _tier(table, level: int):
    """The best row in FOOD or DRINK this level is old enough for."""
    best = table[0]
    for row in table:
        if row[0] <= level:
            best = row
    return best


def _repair(member: Member, town: Town) -> tuple[list[Errand], list[str], list[str]]:
    errands: list[Errand] = []
    notes: list[str] = []
    blocked: list[str] = []

    damaged = [e for e in member.equipped if 0 < e.max_durability and e.fraction < ANY_DAMAGE]
    if not damaged:
        return errands, notes, blocked

    if not town.repairs:
        # Named as blocked rather than emitted as a row that would come back
        # "repairer not in range". The commonest cause is not distance: the
        # nearest repairers to this roster's instance belong to the other
        # faction, and the core turns those down for being unfriendly however
        # close the character stands.
        blocked.append(
            f"{member.name} has {len(damaged)} damaged item(s) and no repairer is reachable"
        )
        return errands, notes, blocked

    worst = member.worst
    why = f"{len(damaged)} damaged item(s), worst at {worst:.0%}"
    if worst < FLOOR:
        why += f"; below the {FLOOR:.0%} floor, so another run can break it"
    errands.append(Errand(member.name, "repair", "all", why))
    return errands, notes, blocked


def _restock(member: Member, town: Town) -> tuple[list[Errand], list[str]]:
    errands: list[Errand] = []
    notes: list[str] = []

    wants = [("food", FOOD, member.food_carried, CONJURE_FOOD)]
    if member.klass in MANA_CLASSES:
        wants.append(("drink", DRINK, member.drink_carried, CONJURE_WATER))

    for what, table, carried, conjures in wants:
        if member.spells & conjures:
            notes.append(
                f"{member.name} conjures {what} and is not sold any; a conjure-and-share "
                "pass would supply the party for nothing"
            )
            continue
        short = STACK - carried
        if short <= 0:
            continue

        level, entry, name, price = _tier(table, member.level)
        if entry not in town.stocks:
            notes.append(f"no reachable vendor stocks {name} ({entry}) for {member.name}")
            continue

        # A stack is a slot. Asking for one when there is none produces
        # "bags cannot take the item", which is true but is a sell problem
        # and not a buy problem, so it is said here instead.
        if member.free_slots < 1:
            notes.append(
                f"{member.name} has no free bag slot for {name}; a sell pass has to run first"
            )
            continue

        ceiling = price * short
        if member.money < ceiling:
            notes.append(
                f"{member.name} cannot afford {short} x {name} "
                f"({ceiling} copper against {member.money})"
            )
            continue

        why = f"carries {carried} {what}, wants a stack of {STACK}"
        nxt = [row for row in table if row[0] > member.level]
        if nxt and nxt[0][0] - member.level <= 1:
            why += f"; one level short of {nxt[0][2]}"
        errands.append(
            Errand(
                member.name,
                "buy",
                f"entry:{entry} count:{short} max:{ceiling}",
                why,
                ceiling,
            )
        )
    return errands, notes


def plan(members, town: Town) -> Plan:
    """Everything this trip should do, in the order it should do it.

    REPAIR BEFORE BUY, ALWAYS, and it is the one ordering decision this module
    makes. Both spend from the same purse, and only one of them is about
    whether the next run can be survived: gear that breaks costs the run,
    while water that was not bought costs time. This side cannot price a
    repair - the cost comes out of DurabilityCosts.dbc, which is not in the
    database - so it cannot reserve money for one either. Putting the repair
    rows first is the whole of the reservation, and it is enough, because the
    executor refuses a purchase it cannot afford rather than overdrawing.

    Anything the town cannot supply comes back in `notes`, and anything that
    stops a run from being safe to start comes back in `blocked`. Neither is
    an errand, because a row that will be refused is worse than no row: it
    costs a poll, it fills the queue, and it reads in the log like something
    that was tried.
    """
    errands: list[Errand] = []
    notes: list[str] = []
    blocked: list[str] = []

    ordered = sorted(members, key=lambda m: m.name)
    for member in ordered:
        got, said, stopped = _repair(member, town)
        errands.extend(got)
        notes.extend(said)
        blocked.extend(stopped)
    for member in ordered:
        got, said = _restock(member, town)
        errands.extend(got)
        notes.extend(said)

    return Plan(tuple(errands), tuple(notes), tuple(blocked))
