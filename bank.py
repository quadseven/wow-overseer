"""What a person walks to the bank to put down, and what they come back for.

THE CAPABILITY IS BUILT AND NOTHING USES IT. mod-overseer#207 landed
`kind='bank'` - `deposit guid:<n>`, `withdraw guid:<n>`, `buy slot`, driven
through the core's own bank packet handlers with a banker in interaction
range. Nothing in this process has ever written such a row, so the family's
bank has stayed exactly as empty as it was before the executor existed.

MEASURED ON THE DEV FAMILY, 2026-09-04. Every member had a bank-side item
count of zero and had never had anything else, while four of the five were at
zero free bag slots and material transfers were failing with "receiver bags
are full". The bags were full of things nobody wanted to sell: reagents for
crafts the family has not taken, stacks that will matter in ten levels. That
is the pile a person walks to a bank with, and the game already has the place
to put it.

WHAT THIS MODULE DOES NOT DECIDE, AND WHY THAT MATTERS. It does not decide
whether an item is worth keeping. `disposition.decide` answers that already -
binding first, refusals before disposals, unknowns resolved to KEEP - and its
BANK verdict is the whole input here. Answering it a second time is how two
modules that agree today drift apart by Christmas. What this module adds is
the part disposition cannot see from one item: how much room is on each side
of the counter, which character is standing where, and what order the moves
go in.

    disposition    one item   -> one route, with a reason
    bank           one family -> an ordered list of bank moves that fit

THE MIRROR IS THE POINT. A deposit is only half of using a bank. An item goes
down when the family cannot use it yet and comes back when it can - the cloth
returns when somebody is actually a tailor. Both halves read the SAME verdict
from the same module, which is what makes the pair stable: an item goes down
when disposition says BANK and comes back when disposition says it belongs in
the bags (WITHDRAW_ROUTES below), and no verdict is ever both.

AND IT CANNOT OSCILLATE, which is worth being explicit about because a pass
that deposits on Monday and withdraws on Tuesday would look exactly like a
working feature while burning the queue. `reagent_held` is counted across the
WHOLE family and BOTH sides of the counter, so moving a stack over the counter
does not change the number that decided to move it. The only thing that
changes a verdict is the family changing - somebody learning a trade, a stack
being spent - which is precisely when a person would change their mind too.

FAIL CLOSED, the same rule disposition is written to. A row that cannot be
read is dropped and counted, never guessed at. A character whose room could
not be measured gets no moves rather than moves that will be refused. A
deposit is never planned for an item the character is not carrying, because
the executor's answer to that is `item not carried` and a queue full of those
is indistinguishable from a broken bank.

WHAT IS DELIBERATELY NOT HERE. `buy slot` is in the executor's grammar and is
not emitted by this module. Buying a bank BAG slot buys a place to put a bag,
and a bank bag position with no bag in it holds nothing at all; the family's
spare bags are already being handed to whoever has an empty bag position
(bag_upgrade), which is worth strictly more than parking one in the bank. When
there is a spare bag with nowhere better to go AND the 28 base slots are full,
that is the change that should add it, with the purse read at the time.

PURE MODULE: no MySQL, no core, no auction house, no browser. Every number
here is arithmetic over rows somebody else fetched.
"""
from __future__ import annotations

from dataclasses import dataclass

import disposition
import materials

# The two verbs this module emits. `buy slot` is the third the executor takes
# and is argued about in the docstring.
DEPOSIT = "deposit"
WITHDRAW = "withdraw"

# Player inventory geography, 3.3.5 slot constants, bag = 0 rows. The same
# ranges panel.py draws from and bag_upgrade.py sets aside; named again here
# rather than imported because these two are the halves this module has to
# tell apart and a reader should not have to open two files to check them.
#
#     bag 0, slot  0..18   worn equipment
#     bag 0, slot 19..22   the four bag positions       -> carried
#     bag 0, slot 23..38   the built-in backpack        -> carried
#     bag = a worn bag     inside one of the four       -> carried
#     bag 0, slot 39..66   the 28 bank item slots       -> banked
#     bag 0, slot 67..73   the seven bank bag positions -> banked (furniture)
#     bag = a bank bag     inside the bank              -> banked
#
# Anything else - keyring, buyback, currency - is a real possession this module
# has no verb for, so it is neither carried nor banked and is left alone.
BAG_POSITIONS = range(19, 23)
BACKPACK_SLOTS = range(23, 39)
BANK_ITEM_SLOTS = range(39, 67)
BANK_BAG_POSITIONS = range(67, 74)

# The backpack is always there and always sixteen. Not read from anywhere
# because there is nowhere to read it from: it is not an item and has no
# item_template row.
BACKPACK_SIZE = len(BACKPACK_SLOTS)

# The bank's own item slots, before any bank bag is bought. Twenty-eight in
# 3.3.5, and the reason `buy slot` can wait: the family has used none of them.
BANK_SIZE = len(BANK_ITEM_SLOTS)

# How many moves one visit to a banker is allowed to queue per character.
#
# A judgement, not a game constant, which is why it is named. The family
# reaches a banker by one leader walking there and the rest following, and a
# pass that queued forty rows against that one arrival would spend the whole
# retry window on a journey that may not have finished. Eight is roughly what
# a person clears out in one stop, and the next cycle takes the rest.
VISIT_LIMIT = 8

# item_template.class values this module has an opinion about. Containers are
# excluded from deposits: an empty one is worth more in somebody's empty bag
# position (bag_upgrade), and a full one is refused by the executor with
# `a bag with items in it cannot be moved`.
ITEM_CLASS_CONTAINER = 1
ITEM_CLASS_WEAPON = 2
ITEM_CLASS_ARMOR = 4
ITEM_CLASS_QUEST = 12

# item_template.bonding, 3.3.5. 3 is bind-on-use, which behaves as
# bind-on-equip until somebody uses it, and 4 is a quest bind, which is
# soulbound. Anything this table does not name is read as soulbound, because
# that is the reading that closes the most doors rather than the fewest.
_BONDING = {
    0: disposition.BIND_NONE,
    1: disposition.BIND_ON_PICKUP,
    2: disposition.BIND_ON_EQUIP,
    3: disposition.BIND_ON_EQUIP,
    4: disposition.BIND_ON_PICKUP,
}

BAGS = "bags"
BANK = "bank"

# The verdicts that mean "this belongs in the bags", and so the only ones
# that fetch something back out of the bank.
#
# NOT SIMPLY "anything disposition no longer banks". A banked item whose
# verdict is VENDOR or AUCTION or DISENCHANT is one somebody wants to be
# RID of, and hauling it out of the bank so that a different pass can carry
# it to a merchant is a feature with its own argument and its own travel -
# not a side effect of this one. Left alone, it costs nothing where it is.
#
# GIVE is here because a give moves what the giver is CARRYING, so a
# sibling's upgrade sitting in a bank is unreachable until somebody takes
# it out. This module never produces that verdict itself - it passes
# `upgrade_for_sibling=False` - so today the list is KEEP in practice, and
# GIVE is named so the day it does fire the answer is already right.
WITHDRAW_ROUTES = (disposition.KEEP, disposition.GIVE)


@dataclass(frozen=True)
class Holding:
    """One stack, where it is sitting, and what disposition needs to route it.

    `guid` is item_instance.guid and it is not optional: the bank grammar has
    no `entry:` form, on purpose, because the same entry can sit in the bags
    AND in the bank at once and a move by entry would then have two right
    answers on opposite sides of the counter.
    """
    holder: str
    guid: int
    place: str            # BAGS or BANK
    count: int
    container_slots: int  # >0 when the stack is itself a bag
    item: disposition.Item


@dataclass(frozen=True)
class Member:
    """One character's two sides of the counter, as the caller measured them.

    `bag_free` and `bank_free` are counted here rather than in SQL so that the
    counting can be tested against rows written by hand. A character whose
    rows were unreadable is still a Member, with no holdings, which is the
    answer that plans nothing rather than the answer that plans something
    wrong.
    """
    name: str
    level: int
    bag_free: int
    bank_free: int
    carried: tuple = ()
    banked: tuple = ()


@dataclass(frozen=True)
class Move:
    """One bank command, with the reason it is worth sending written into it."""
    character: str
    verb: str        # DEPOSIT or WITHDRAW
    guid: int
    item: str
    count: int
    why: str


@dataclass(frozen=True)
class Plan:
    """The ordered moves, and everything the pass refused to do and why.

    `notes` is not decoration. A bank pass that plans nothing looks identical
    whether the family has nothing to bank, the rows would not parse, or the
    bank is full - and those three want three different responses from a
    person reading the log.
    """
    moves: tuple = ()
    notes: tuple = ()


def _int(value, default=0):
    """Read a number a database driver may hand over as almost anything."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def item_from_row(row):
    """One `disposition.Item` from one joined item_template row, or None.

    Every field defaults to the dangerous answer the way disposition.Item
    does, and a row missing the field that decides danger is refused outright
    rather than filled in. `auction_value` and `disenchant_skill_required` are
    passed as None on purpose: this process reads neither an auction house nor
    a disenchant threshold, and disposition's answer to an unknown price is to
    take the route that is known.
    """
    try:
        name = row["name"]
    except (KeyError, TypeError):
        return None
    # A LEFT JOIN miss on acore_world.item_template hands back NULL, and
    # str(None) is the string "None" - an item name that matches nothing,
    # routes as an ordinary green and reads as a real answer in the log.
    # An item this process cannot name is one it must not move.
    if not isinstance(name, str) or not name.strip():
        return None
    item_class = _int(row.get("item_class"), ITEM_CLASS_QUEST)
    return disposition.Item(
        name=name,
        quality=_int(row.get("quality")),
        known=True,
        binding=_BONDING.get(_int(row.get("bonding"), 1),
                             disposition.BIND_ON_PICKUP),
        quest_item=item_class == ITEM_CLASS_QUEST,
        equipment=item_class in (ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR),
        required_level=_int(row.get("required_level")),
        sell_price=_int(row.get("sell_price")),
        auction_value=None,
        reagent_for=materials.REAGENTS.get(name),
        disenchant_skill_required=None,
    )


def _place(bag, slot, worn_bags, bank_bags):
    """Which side of the counter one (bag, slot) pair is on, or ''.

    The empty string is a real answer and means "somewhere this module has no
    verb for": worn equipment, the keyring, buyback. Those are possessions,
    they are simply not moveable across a bank counter by this grammar.
    """
    if bag == 0:
        if slot in BAG_POSITIONS or slot in BACKPACK_SLOTS:
            return BAGS
        if slot in BANK_ITEM_SLOTS or slot in BANK_BAG_POSITIONS:
            return BANK
        return ""
    if bag in worn_bags:
        return BAGS
    if bag in bank_bags:
        return BANK
    return ""


def _stack_order(holding):
    """Biggest pile first, then by name, then by guid.

    Biggest first because the point of a bank trip is bag slots and every
    stack is worth exactly one slot whatever its size - so when the visit
    limit bites, the pile that took longest to accumulate goes down first.
    The name and guid tiebreaks are not cosmetic: two stacks of Linen Cloth
    are indistinguishable by size, and a plan that reordered them between
    cycles would make the dedupe window useless and the log unreadable.
    """
    return (-holding.count, holding.item.name, holding.guid)


def members_from_rows(rows, names):
    """One Member per name, whether or not any row mentions them.

    `rows` carry holder, level, item_guid, count, name, quality, sell_price,
    required_level, bonding, item_class, container_slots, bag and slot, as the
    bridge's SQL names them. A name with no rows at all is still a Member,
    which is the honest reading of "we could not see anything of theirs".

    TWO PASSES, because a row's meaning depends on another row. An item inside
    container 4211 is carried if 4211 is worn in a bag position and banked if
    4211 is sitting in a bank bag position, and nothing about the item's own
    row says which. bag_upgrade.members_from_rows has the same shape for the
    same reason.
    """
    wanted = list(dict.fromkeys(names))
    levels = {name: 0 for name in wanted}
    worn_bags = {name: set() for name in wanted}
    bank_bags = {name: set() for name in wanted}
    for row in rows:
        holder = row.get("holder")
        if holder not in levels:
            continue
        levels[holder] = max(levels[holder], _int(row.get("level")))
        bag, slot = _int(row.get("bag"), -1), _int(row.get("slot"), -1)
        if bag != 0:
            continue
        if slot in BAG_POSITIONS:
            worn_bags[holder].add(_int(row.get("item_guid")))
        elif slot in BANK_BAG_POSITIONS:
            bank_bags[holder].add(_int(row.get("item_guid")))

    carried = {name: [] for name in wanted}
    banked = {name: [] for name in wanted}
    # Room starts at what the character has before anything is counted in: the
    # backpack is always there, the bank's 28 slots are always there, and a
    # bag adds its own capacity wherever it is worn.
    bag_room = {name: BACKPACK_SIZE for name in wanted}
    bank_room = {name: BANK_SIZE for name in wanted}
    for row in rows:
        holder = row.get("holder")
        if holder not in levels:
            continue
        bag, slot = _int(row.get("bag"), -1), _int(row.get("slot"), -1)
        guid = _int(row.get("item_guid"))
        slots = _int(row.get("container_slots"))
        place = _place(bag, slot, worn_bags[holder], bank_bags[holder])
        if place == BAGS and bag == 0 and slot in BAG_POSITIONS:
            # A worn bag occupies a bag POSITION, not an inventory slot, so it
            # adds room and costs none.
            bag_room[holder] += slots
            continue
        if place == BANK and bag == 0 and slot in BANK_BAG_POSITIONS:
            bank_room[holder] += slots
            continue
        if place == BAGS:
            bag_room[holder] -= 1
        elif place == BANK:
            bank_room[holder] -= 1
        else:
            continue
        item = item_from_row(row)
        if item is None or guid <= 0:
            # The slot is still occupied - that is why the room was counted
            # above - but nothing can be said about what is in it, so it is
            # not a candidate for anything.
            continue
        holding = Holding(holder=holder, guid=guid, place=place,
                          count=max(1, _int(row.get("count"), 1)),
                          container_slots=slots, item=item)
        (carried if place == BAGS else banked)[holder].append(holding)

    return tuple(
        Member(name=name, level=levels[name],
               bag_free=max(0, bag_room[name]),
               bank_free=max(0, bank_room[name]),
               carried=tuple(sorted(carried[name], key=_stack_order)),
               banked=tuple(sorted(banked[name], key=_stack_order)))
        for name in sorted(wanted)
    )


def family_from_skills(held, *, vendor_reachable=True, auction_reachable=False,
                       bank_reachable=True, reagent_keep=None):
    """The `disposition.Family` this family actually is today.

    `held` is name -> {profession: value}, as the bridge reads it out of
    `character_skills`. What goes into Family.professions is what SOMEBODY
    has, at the best skill anybody has, because the question disposition asks
    is "can this family use this reagent at all" and the answer does not
    depend on whose bags it is in.

    A PROFESSION NOBODY HAS IS ABSENT, NOT ZERO, and that distinction is the
    whole reason the bank ever has anything to do. disposition reads a missing
    profession as "nobody has yet" and routes its reagent to the bank; a zero
    would read as somebody having it at skill zero and route the reagent to
    the bags of a crafter who does not exist.

    THE DEFAULTS ARE THE MEASURED WORLD, not optimism. A vendor is reachable
    because the vendor pass walks the leader to one (infra#3311). A banker is
    reachable because this pass walks the leader to one, which is the change
    this module is part of. The auction house is NOT reachable: nothing in
    this process writes an `auction` row, the ENUM value notwithstanding, and
    telling disposition otherwise would have it route items to a listing that
    is never made.
    """
    best: dict = {}
    for skills in (held or {}).values():
        for profession, value in (skills or {}).items():
            best[profession] = max(best.get(profession, 0), _int(value))
    kwargs = {}
    if reagent_keep is not None:
        kwargs["reagent_keep"] = reagent_keep
    return disposition.Family(
        enchanting_skill=best.get("enchanting", 0),
        professions=best,
        vendor_reachable=vendor_reachable,
        auction_reachable=auction_reachable,
        bank_reachable=bank_reachable,
        **kwargs,
    )


def reagent_totals(members):
    """material -> how much of it the family holds, BOTH sides of the counter.

    Counting the bank side is what makes the pair of verbs stable. If a
    deposit reduced the number that decided to deposit, a family sitting just
    above `reagent_keep` would bank a stack, drop below the line, withdraw it
    again, and do that forever - and every cycle of it would look like a
    working bank pass in the log.
    """
    totals: dict = {}
    for member in members:
        for holding in tuple(member.carried) + tuple(member.banked):
            if not holding.item.reagent_for:
                continue
            key = holding.item.name
            totals[key] = totals.get(key, 0) + holding.count
    return totals


def _verdict(holding, family, level, totals):
    """What disposition says about this stack, in this family, right now."""
    return disposition.decide(
        holding.item, family, character_level=level,
        upgrade_for_sibling=False,
        reagent_held=totals.get(holding.item.name, holding.count),
    )


def plan(members, family, *, visit_limit=VISIT_LIMIT):
    """Every bank move worth making, in the order it should be sent.

    DEPOSITS BEFORE WITHDRAWALS, per character, and the withdrawal budget is
    the bag room that will exist AFTER the deposits land. Running them the
    other way round would refuse withdrawals this order allows, and would do
    it on exactly the characters that need the bank most - the ones with no
    free slots at all.

    `upgrade_for_sibling` is passed as False throughout, deliberately. Whether
    a green suits somebody else better is the give pass's question, it is
    answered against the whole family's worn kit, and answering it here with a
    shrug would be a second opinion nobody asked for.
    """
    totals = reagent_totals(members)
    moves, notes = [], []
    for member in sorted(members, key=lambda m: m.name):
        deposits = []
        room = member.bank_free
        for holding in member.carried:
            if len(deposits) >= visit_limit:
                notes.append("%s has more to bank than one visit carries; the "
                             "rest waits for the next trip" % member.name)
                break
            if holding.container_slots > 0:
                # An empty spare bag belongs in somebody's empty bag position
                # and a full one cannot be moved at all. Either way the bank
                # is the wrong place for it.
                continue
            verdict = _verdict(holding, family, member.level, totals)
            if verdict.route != disposition.BANK:
                continue
            if room <= 0:
                notes.append("%s's bank is full, so %s stays in the bags"
                             % (member.name, holding.item.name))
                continue
            room -= 1
            deposits.append(Move(
                character=member.name, verb=DEPOSIT, guid=holding.guid,
                item=holding.item.name, count=holding.count,
                why=verdict.why))

        withdrawals = []
        # Every deposit hands a bag slot back, so the room to receive a
        # withdrawal is larger than it was measured.
        space = member.bag_free + len(deposits)
        for holding in member.banked:
            if len(deposits) + len(withdrawals) >= visit_limit:
                break
            if holding.container_slots > 0:
                continue
            verdict = _verdict(holding, family, member.level, totals)
            if verdict.route not in WITHDRAW_ROUTES:
                continue
            if space <= 0:
                notes.append("%s has no room to take %s back out"
                             % (member.name, holding.item.name))
                continue
            space -= 1
            withdrawals.append(Move(
                character=member.name, verb=WITHDRAW, guid=holding.guid,
                item=holding.item.name, count=holding.count,
                why="%s is wanted in the bags again - %s"
                    % (holding.item.name, verdict.why)))
        moves.extend(deposits)
        moves.extend(withdrawals)
    return Plan(moves=tuple(moves), notes=tuple(dict.fromkeys(notes)))


def command(move):
    """The exact command text mod-overseer's DoBank takes for one move.

    `guid:` and nothing else. The grammar has no `entry:` form on purpose,
    and the guid must be non-zero: zero is what every "not found" path in the
    core returns, so a row asking for it would be answered by whichever item
    that path happened to find.
    """
    return "%s guid:%d" % (move.verb, move.guid)


# WHAT A BANK ERRAND SHOULD DO NEXT (infra#3728). Three words for the same
# reason towntrip.errand_step and bag_pressure.vendor_errand_step use three:
# "do not aim" and "hand the column back" are opposite intentions that both
# read as "no write this pass", and that is how the missing half stayed
# invisible in all three passes at once.
BANK_ERRAND_AIM = "aim"
BANK_ERRAND_HOLD = "hold"
BANK_ERRAND_RELEASE = "release"


def errand_step(rows_outstanding: int, moves_unasked: bool) -> str:
    """What to do with the leader's `banker` aim this pass (infra#3728).

    THE SAME LATCH AS THE SELL PASS'S, IN THE SAME COLUMN. `_bank_once` wrote
    `travel_npc = 'banker'` and nothing ever wrote it back; `banker` is one of
    the four aims `IsMaintenanceErrand` covers, so mod-overseer reaches "errand
    done, releasing" on arrival and then deliberately SKIPS the column write
    (infra#3655), naming the bridge as the half that clears it. The bridge never
    did, in any of the four passes.

    TWO INPUTS RATHER THAN THE TOWN TRIP'S THREE, AND THE DIFFERENCE IS REAL.
    A town-trip repair row cannot even be WRITTEN until a repairer is in reach,
    so that pass has to know whether the family has arrived before it can tell a
    finished trip from one that has not started. A bank row is written from
    wherever the family happens to be standing and waits `pending` until its
    holder reaches the counter (mod-overseer#209, infra#3311) - the rows and the
    aim are created in the SAME pass - so a queue this pass wrote and the world
    has fully answered is complete evidence about this errand's own work, with
    no "has not started yet" window for an arrival test to close.

    AND AN ANSWER IS AN ANSWER, INCLUDING A REFUSAL. `banker not in range` is
    what DoBank says to a holder still on the road, and counting refusals as
    outstanding would rebuild the latch one table over - the same trap
    `_outstanding_sales` describes against 17,536 all-time `vendor not in range`
    rows. The honest consequence, stated rather than hidden: a trip whose rows
    were all refused for range ends this errand, and the pass tries again once
    the retry window lets it re-ask. That is a bounded hourly retry instead of a
    permanent parking space, and on this realm it is not theoretical - measured
    2026-09-13, `kind='bank'` stands at 141 error against 1 delivered all time,
    every one of those refusals arriving while the column stayed set.

    NOT KNOWING IS A REASON TO HOLD. A negative count is the bridge reporting
    that it could not read the queue at all; reading that as "finished" is the
    fail-open direction and it walks the family away from rows already queued.

    `moves_unasked` IS WHETHER THIS PASS STILL HAS A MOVE TO MAKE that it has
    not already queued inside the retry window - bank.plan's own answer, minus
    what `_recent_bank_keys` says was asked recently. It is NOT "the bags look
    full": `character_inventory` is written on PlayerSaveInterval, measured at
    900 seconds on this realm, so for up to a quarter of an hour after a deposit
    lands the item still reads as carried and `plan` proposes it again. That
    staleness therefore pushes towards AIM and never towards RELEASE, which is
    the safe direction - it holds a finished errand a few minutes too long
    rather than ending a live one - and the retry window stops the re-proposal
    becoming a second row.
    """
    if rows_outstanding != 0:
        return BANK_ERRAND_HOLD
    if moves_unasked:
        return BANK_ERRAND_AIM
    return BANK_ERRAND_RELEASE


def lines(moves):
    """One log line per move, for a person reading the pass afterwards.

    Takes the moves rather than the Plan so the caller can log what it
    actually WROTE. A pass that logs its plan and writes half of it, because
    the other half was already queued inside the retry window, is a log that
    lies about what the family did.
    """
    return ["%s: %s %d %s (%s) - %s"
            % (move.character, move.verb, move.count, move.item,
               command(move), move.why)
            for move in moves]
