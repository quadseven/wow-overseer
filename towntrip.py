"""What a town trip between two dungeon runs has to do (infra#3357).

Pure module, same seam as materials.py and questshare.py: facts in, a plan
out. bridge.py reads the durability, the bags, the purse and the spellbook,
calls plan(), and turns each Errand into one `overseer_command` row with
kind='repair', kind='buy', kind='conjure' or kind='give'. mod-overseer's
DoRepair, DoBuy, the conjure resolver and DoGive perform the transactions and
read the world back; nothing here touches the world.

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

AND BUYING IS THE LAST OF THREE ANSWERS, NOT THE FIRST (infra#3464). The
table above was read on a day when the party leader was a MAGE who had known
how to conjure food since level 6 and water since level 4, had never once done
either, and was not asked to - this module's own note said "a conjure-and-share
pass would supply the party for nothing" and nothing acted on it. Conjured food
and water are free, unlimited, always level appropriate and BIND_NONE, so one
caster supplies five characters and kind='give' hands the stacks out. Every
axis beats buying, and it also survives the case buying does not: the counters
nearest this roster's instance belong to the other faction, and a family that
can only be fed by a friendly vendor is a family that goes hungry there.

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

# THE TWO WORDS THIS MODULE PLANS IN. `drink` is what a character wants and
# `water` is what a mage casts, and they are the same thing under two names -
# mod-overseer's conjure grammar takes `food` or `water` and nothing else. The
# mapping is named rather than inlined so the word a row carries is the word a
# test pins, which is the rule its own decision header states.
FOOD_KIND = "food"
DRINK_KIND = "drink"
CONJURE_WORD = {FOOD_KIND: "food", DRINK_KIND: "water"}

# THE GAME'S OWN CLASSIFICATION, and the reason the FOOD and DRINK tables
# above are for BUYING and never for COUNTING (infra#3464).
#
# item_template.spellcategory_1 is 11 for anything eaten and 59 for anything
# drunk. mod-playerbots asks exactly those two numbers of exactly that field
# (InventoryAction.cpp builds one visitor on each), mod-overseer declares the
# same pair as CONSUMABLE_CATEGORY_FOOD and CONSUMABLE_CATEGORY_DRINK in
# overseer_decisions.h, and the operator's own count of the family's stores
# uses them too.
#
# WHAT COUNTING BY THE TWELVE VENDOR ENTRIES INSTEAD GOT WRONG, measured on
# the live realm on 2026-09-09: Og carried 15 units of food and water and Bork
# 7, none of them from the tiers below - Og's are CONJURED and Bork's were
# looted. Counted against the entry list both read as zero, so a stack of
# twenty would have been bought for a character who had a stack already, into
# bags that were 78 items deep. A list of remembered ids is a second answer to
# "what is food" and it goes stale silently; this is the world's own.
CONSUMABLE_CATEGORY_FOOD = 11
CONSUMABLE_CATEGORY_DRINK = 59
CATEGORY_KIND = {
    CONSUMABLE_CATEGORY_FOOD: FOOD_KIND,
    CONSUMABLE_CATEGORY_DRINK: DRINK_KIND,
}

# item_template.Flags bit 1, ITEM_FLAG_CONJURED. Every `Conjured *` item
# carries it, it is what the core's own ItemTemplate::IsConjuredConsumable
# tests, and it is the fact that makes a stack free to remake and free to hand
# on: measured on this realm, `bonding` is 0 on every conjured row, so a
# conjured stack is tradable where a looted one may not be.
ITEM_FLAG_CONJURED = 0x2

# mod-overseer's own ceiling on one kind='conjure' row (CONJURE_UNITS_MAX in
# overseer_decisions.h). Each unit is half of a three second cast, so a
# hundred is already two and a half minutes of a character standing still, and
# a row asking for more is refused as malformed rather than obeyed. Restated
# here so this side never writes a row that side will not take.
CONJURE_UNITS_MAX = 100

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
class Stack:
    """One carried stack of something eaten or drunk, as the world holds it.

    `guid` is the item_instance a hand-off names, because a give moves exactly
    one row and `entry` would let the worldserver pick any matching stack off
    the holder's bags. `what` is FOOD_KIND or DRINK_KIND, decided from the
    world's own spell category rather than from a list of item ids.
    """

    guid: int
    entry: int
    name: str
    count: int
    what: str
    conjured: bool = False


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
    stacks: tuple[Stack, ...] = ()

    def carries(self, what: str) -> int:
        """Units of food or drink in the bags, however they got there."""
        return self.food_carried if what == FOOD_KIND else self.drink_carried

    def conjures(self, what: str) -> bool:
        """Whether this character can make `what` out of nothing."""
        ranks = CONJURE_FOOD if what == FOOD_KIND else CONJURE_WATER
        return bool(self.spells & ranks)

    def spare(self, what: str) -> tuple[Stack, ...]:
        """Conjured stacks this character could hand on and still be stocked.

        A stack is only spare when giving it away leaves a full stack behind,
        so the conjurer never feeds the party by starving itself - and only a
        CONJURED stack is offered, because that is the one this family can
        remake for free and the one measured to be tradable.
        """
        mine = tuple(s for s in self.stacks if s.what == what and s.conjured)
        keep = STACK
        out = []
        remaining = self.carries(what)
        for stack in sorted(mine, key=lambda s: s.guid):
            if remaining - stack.count < keep:
                continue
            remaining -= stack.count
            out.append(stack)
        return tuple(out)

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

    Every field is a FACT READ FROM THE WORLD, never an assumption: `repairs`
    is whether a reachable NPC carries the repair npcflag, `vendor` whether one
    carries the vendor npcflag, and `stocks` the set of item entries a
    reachable vendor's npc_vendor rows actually list. A planner that assumed
    any of them would produce rows the executor refuses.

    WHY `vendor` IS SEPARATE FROM `stocks`, AND NOT DERIVED FROM IT
    (infra#3464). They answer different questions. `stocks` is what a vendor
    will SELL, and it is empty for a merchant with no npc_vendor rows.
    `vendor` is whether one is standing there at all, which is the only thing
    a SALE needs: mod-overseer's own DoSell notes that VendorItemData is never
    consulted when a player sells TO a vendor, so a merchant with an empty or
    restricted stock still buys. Deriving "can we sell here" from `stocks`
    would refuse exactly the vendors that would have taken the greens.
    """

    repairs: bool = False
    stocks: frozenset[int] = frozenset()
    vendor: bool = False


@dataclass(frozen=True)
class Errand:
    """One `overseer_command` row, ready to insert.

    `taker` is the receiving character on a hand-off and empty on everything
    else; it becomes `overseer_command.target_arg`, which is the role that
    column already holds for kind='give'.
    """

    member: str
    kind: str  # 'repair', 'buy', 'conjure' or 'give'
    command: str
    why: str
    spend: int = 0  # copper ceiling; 0 when this side cannot price it
    taker: str = ""


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


def _wants(member: Member, what: str) -> bool:
    """Whether this character has any use for `what` at all.

    Everybody eats. Only a class whose resource is mana gets anything out of a
    drink, so conjuring or buying one for a warrior is a bag slot spent on a
    decoration - the same rule mod-overseer states as ClassRestoresManaByDrinking
    and the same reason MANA_CLASSES exists.
    """
    return what == FOOD_KIND or member.klass in MANA_CLASSES


def _buy(member: Member, town: Town, what: str) -> tuple[list[Errand], list[str]]:
    """Spend money on `what`, or say what stopped it. Unchanged rules."""
    errands: list[Errand] = []
    notes: list[str] = []
    table = FOOD if what == FOOD_KIND else DRINK
    carried = member.carries(what)
    short = STACK - carried
    if short <= 0:
        return errands, notes

    level, entry, name, price = _tier(table, member.level)
    if entry not in town.stocks:
        notes.append(f"no reachable vendor stocks {name} ({entry}) for {member.name}")
        return errands, notes

    # A stack is a slot. Asking for one when there is none produces
    # "bags cannot take the item", which is true but is a sell problem
    # and not a buy problem, so it is said here instead.
    if member.free_slots < 1:
        notes.append(
            f"{member.name} has no free bag slot for {name}; a sell pass has to run first"
        )
        return errands, notes

    ceiling = price * short
    if member.money < ceiling:
        notes.append(
            f"{member.name} cannot afford {short} x {name} "
            f"({ceiling} copper against {member.money})"
        )
        return errands, notes

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


def _hand_on(wanted, conjurers, what: str) -> tuple[list[Errand], set]:
    """Hand a conjurer's spare stacks to whoever has none. The cheapest route.

    One stack per taker and each stack used once, so two people short of food
    are never promised the same twenty units. Returns the errands and the
    names they supplied, because "supplied for free this pass" is what stops
    the buy half selling somebody a stack they are already being handed.
    """
    errands: list[Errand] = []
    supplied = set()
    offers = {giver.name: list(giver.spare(what)) for giver in conjurers}
    for member in wanted:
        if member.conjures(what):
            continue
        for giver in conjurers:
            if not offers[giver.name]:
                continue
            stack = offers[giver.name].pop(0)
            # THE GIVER IS THE ROW'S CHARACTER AND THE TAKER IS ITS ARGUMENT,
            # the same two roles kind='give' already carries everywhere else:
            # DoGive moves an item OUT of target_name's bags INTO target_arg's.
            errands.append(Errand(
                giver.name, "give", f"guid:{stack.guid}",
                f"{giver.name} conjured {stack.name} and {member.name} carries "
                f"{member.carries(what)} {what}",
                taker=member.name,
            ))
            supplied.add(member.name)
            break
    return errands, supplied


def _conjure_target(giver: Member, mouths: int, what: str) -> int:
    """Units this caster should end up carrying, under both ceilings.

    One stack for itself and one for each mouth still unfed, held under
    CONJURE_UNITS_MAX because mod-overseer refuses a row above it as malformed
    rather than clamping it, and under the free bag slots because a stack that
    has nowhere to go is a cast that ends in "bags cannot take the item".
    """
    room = max(0, int(giver.free_slots))
    stacks = min(1 + mouths, max(1, room), CONJURE_UNITS_MAX // STACK)
    return STACK * stacks


def _conjure(conjurers, dependents, what: str) -> tuple[list[Errand], list[str], set]:
    """Ask the casters for the party's worth. Free, and needs no town at all.

    ONE CONJURER COVERS THE PARTY. A second would double both the stock and
    the bag slots it costs, so once one has taken the mouths on, the rest only
    ever conjure for themselves.
    """
    errands: list[Errand] = []
    notes: list[str] = []
    supplied = set()
    for giver in conjurers:
        target = _conjure_target(giver, len(dependents), what)
        carried = giver.carries(what)
        if carried >= target:
            continue
        if int(giver.free_slots) < 1 and carried <= 0:
            notes.append(
                f"{giver.name} has no free bag slot to conjure {what} into; "
                "a sell pass has to run first"
            )
            continue
        mouths = (f" and {len(dependents)} other(s) with none"
                  if dependents else "")
        errands.append(Errand(
            giver.name, "conjure",
            f"{CONJURE_WORD[what]} up_to:{target}",
            f"carries {carried} {what}, wants {target} for itself{mouths}",
        ))
        supplied.add(giver.name)
        dependents = []
    return errands, notes, supplied


def _supply(members, town: Town, what: str) -> tuple[list[Errand], list[str]]:
    """Get one consumable into every bag that should have it (infra#3464).

    THREE ROUTES, IN THE ONLY ORDER THAT MAKES SENSE, and this is the whole of
    "prefer conjuring where it applies and buying where it does not":

      GIVE     A conjured stack the conjurer can spare goes to somebody with
               none. Conjured items are BIND_NONE, measured, so kind='give'
               moves them with nothing new built.
      CONJURE  A character who knows the spell makes its own, and makes the
               party's as well. It is free, unlimited, always level
               appropriate and it does not need a friendly town - which
               matters on a roster whose nearest counters belong to the other
               faction. `up_to:` is a TOTAL and not an amount to add, so the
               same row can be sent again after a partial run without
               doubling the stock.
      BUY      What conjuring cannot supply. Kept for everybody the first two
               did not reach THIS pass, rather than suppressed on the promise
               that a conjure will land later: a promise is not food, and the
               regression that would be is a family that stops buying and
               never receives.

    WHAT THIS DELIBERATELY DOES NOT DO IS SEQUENCE ITSELF. There is no state
    here and no waiting on a row: every pass re-reads the bags and asks again,
    so the hand-off simply becomes possible on the cycle after the conjure
    lands, and a conjure that produced nothing is asked for again. That is the
    same property `_towntrip_once` already relies on for the walk to town.
    """
    ordered = sorted(members, key=lambda m: m.name)
    wanted = [m for m in ordered if _wants(m, what) and m.carries(what) < STACK]
    if not wanted:
        return [], []

    conjurers = [m for m in ordered if m.conjures(what)]
    errands, supplied = _hand_on(wanted, conjurers, what)
    dependents = [m for m in wanted
                  if not m.conjures(what) and m.name not in supplied]
    made, notes, cast_for = _conjure(conjurers, dependents, what)
    errands.extend(made)
    supplied |= cast_for

    for member in wanted:
        # A conjurer is covered by its own row above, or was refused there
        # with a reason. Buying a mage water it makes for free is the spend
        # this module exists to avoid.
        if member.name in supplied or member.conjures(what):
            continue
        bought, said = _buy(member, town, what)
        errands.extend(bought)
        notes.extend(said)
    return errands, notes


def plan(members, town: Town) -> Plan:
    """Everything this trip should do, in the order it should do it.

    REPAIR BEFORE ANYTHING THAT SPENDS, ALWAYS, and it is the one ordering
    decision this module makes. Both spend from the same purse, and only one of them is about
    whether the next run can be survived: gear that breaks costs the run,
    while water that was not bought costs time. This side cannot price a
    repair - the cost comes out of DurabilityCosts.dbc, which is not in the
    database - so it cannot reserve money for one either. Putting the repair
    rows first is the whole of the reservation, and it is enough, because the
    executor refuses a purchase it cannot afford rather than overdrawing.

    AND THE FREE ROUTES BEFORE THE PAID ONE. `_supply` hands on what has
    already been conjured, then asks the casters for the rest, and only then
    buys - which is why a mage is never sold water, and why a party standing
    in a town that will not trade with it is still fed.

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
    # Food before drink because everybody eats and only the mana users drink,
    # so the first pass is the one that reaches the whole party.
    for what in (FOOD_KIND, DRINK_KIND):
        got, said = _supply(ordered, town, what)
        errands.extend(got)
        notes.extend(said)

    return Plan(tuple(errands), tuple(notes), tuple(blocked))


# ---------------------------------------------------------------- from rows --
#
# THE SAME SEAM bank.members_from_rows AND bank.family_from_skills SIT ON. The
# bridge holds the SQL and the connection; what a row MEANS is a decision, and a
# decision belongs on this side where a test can reach it without a database.
# Everything below takes the rows as the bridge's own queries name them and
# returns the value objects `plan` above already reads.

# The two npcflag bits this trip cares about, as the core defines them
# (UnitDefines.h: UNIT_NPC_FLAG_VENDOR 0x80, UNIT_NPC_FLAG_REPAIR 0x1000).
# Named here rather than in the SQL so the bit test is testable and so a reader
# does not have to decode a hex literal in a WHERE clause.
NPC_FLAG_VENDOR = 0x80
NPC_FLAG_REPAIR = 0x1000


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def town_from_rows(rows) -> Town:
    """What the counters within reach of the party can actually do.

    `rows` are the creature spawns near where the family is STANDING, one row
    per (spawn, item it sells), carrying `npcflag` and `item` as the bridge's
    query names them. `item` is NULL for a spawn that sells nothing, which is
    what a repairer with no vendor rows looks like.

    WHY THIS IS READ FROM WHERE THEY STAND AND NOT FROM A LIST OF TOWNS. There
    is no list. No vendor entry, name or coordinate appears anywhere in this
    repository and none is introduced here: the family is aimed at a ROLE, the
    worldserver resolves that role against live spawns on their own map and
    excludes any they may not interact with (mod-overseer#250), and this
    function then reads back what is actually around them once they arrive. So
    the town this trip visits is whichever one they were nearest to, and this
    side never has to know its name.

    BEFORE THEY ARRIVE THIS IS CORRECTLY EMPTY, and that is the mechanism
    rather than a shortcoming. An empty Town makes `plan` produce no errands and
    a note saying why, so a pass that runs while they are still walking writes
    nothing instead of writing rows the executor would refuse - which is the
    rule the module docstring above states and the reason a refused row is
    worse than no row.
    """
    repairs = False
    vendor = False
    stocks = set()
    for row in rows:
        flags = _int(row.get("npcflag"))
        if flags & NPC_FLAG_REPAIR:
            repairs = True
        if flags & NPC_FLAG_VENDOR:
            vendor = True
        entry = _int(row.get("item"))
        # A vendor's stock only counts when the spawn is actually a vendor. A
        # repairer that happens to have npc_vendor rows it cannot sell from
        # would otherwise make `plan` promise a purchase nobody can make.
        if entry and flags & NPC_FLAG_VENDOR:
            stocks.add(entry)
    return Town(repairs=repairs, stocks=frozenset(stocks), vendor=vendor)


def members_from_rows(rows, carried, spells, free_slots, names) -> tuple:
    """One Member per name, whether or not any row mentions them.

    The four inputs are four queries, kept separate because they are four
    different scopes and joining them in SQL would multiply rows against each
    other: `rows` is one row per worn item, `carried` one per carried
    consumable STACK, `spells` one per known spell, `free_slots` one
    number per holder.

    A NAME WITH NOTHING IS STILL A MEMBER, the same rule bank.members_from_rows
    states: "we could not see anything of theirs" is an honest reading and it
    produces a member who plans nothing, where dropping them would silently
    exclude somebody from every trip.

    A WORN ITEM WITH MaxDurability 0 CANNOT BREAK AND IS NOT BROKEN. Cloth,
    trinkets and rings all report zero, and `Equipped.fraction` already reads
    that as 1.0; it is repeated here only so a reader of the SQL does not
    "fix" the LEFT join into an INNER one and quietly drop every wearer whose
    item_template row is missing.
    """
    wanted = list(dict.fromkeys(names))
    worn = {name: [] for name in wanted}
    facts = {name: {} for name in wanted}

    for row in rows:
        holder = row.get("holder")
        if holder not in worn:
            continue
        facts[holder] = {
            "klass": str(row.get("klass") or "").strip().lower(),
            "level": _int(row.get("level")),
            "money": _int(row.get("money")),
        }
        maximum = _int(row.get("max_durability"))
        if maximum <= 0:
            continue
        worn[holder].append(
            Equipped(
                _int(row.get("entry")),
                str(row.get("item_name") or "worn"),
                _int(row.get("durability")),
                maximum,
            )
        )

    # ONE ROW PER CARRIED STACK, CLASSIFIED BY THE WORLD (infra#3464). `carried`
    # rows name a spell category and the item's own flags, and CATEGORY_KIND
    # turns those into food or drink; a row with neither category is not a
    # consumable and is dropped rather than guessed at.
    #
    # A row with no `guid` still counts toward the totals and simply cannot be
    # handed on, which is the honest reading of "we can see they have it but
    # not which stack it is" and keeps a purchase from being planned over it.
    stacks = {name: [] for name in wanted}
    food = {name: 0 for name in wanted}
    drink = {name: 0 for name in wanted}
    for row in carried:
        holder = row.get("holder")
        if holder not in food:
            continue
        what = CATEGORY_KIND.get(_int(row.get("spell_category"), -1))
        if what is None:
            continue
        count = _int(row.get("carried"))
        if count <= 0:
            continue
        if what == FOOD_KIND:
            food[holder] += count
        else:
            drink[holder] += count
        guid = _int(row.get("guid"))
        if guid > 0:
            stacks[holder].append(Stack(
                guid=guid, entry=_int(row.get("entry")),
                name=str(row.get("name") or "a bite"), count=count, what=what,
                conjured=bool(_int(row.get("item_flags")) & ITEM_FLAG_CONJURED),
            ))

    known = {name: set() for name in wanted}
    for row in spells:
        holder = row.get("holder")
        if holder in known:
            known[holder].add(_int(row.get("spell")))

    members = []
    for name in wanted:
        got = facts[name]
        members.append(
            Member(
                name,
                got.get("klass", ""),
                got.get("level", 0),
                got.get("money", 0),
                _int(free_slots.get(name)),
                tuple(worn[name]),
                food[name],
                drink[name],
                frozenset(known[name]),
                tuple(sorted(stacks[name], key=lambda s: s.guid)),
            )
        )
    return tuple(members)
