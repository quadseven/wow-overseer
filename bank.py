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

ONE QUESTION DISPOSITION DOES NOT ASK IS ANSWERED HERE (#233): is this stack
used from the bags at all? Disposition's verdicts are about keeping and
selling, and a gem, a recipe nobody can learn yet or a lockbox is worth
keeping and never used from a bag. The keeper rule (the block above
`Storage`) stores those, and it is the only judgement this module makes on
its own. Disposition's BANK verdict is still read, after the keeper rule.

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

from dataclasses import dataclass, field

import disposition
import goals
import guildbank
import materials
import recipebook

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

# Where a deposit lands. PERSONAL is the holder's own bank, the `kind='bank'`
# row this module has always written. GUILD is tab 0 of the holder's guild
# bank, the `bank deposit-item guid:<n>` row guildbank.format_item_deposit
# renders and `_guild_bank_once` queues from the vault.
PERSONAL = "personal"
GUILD = "guild"

# Tab 0 is the only tab the item verb deposits into (mod-overseer's
# BankDepositItem, "TAB 0 ONLY, v1"), and a 3.3.5 guild bank tab has 98 slots
# (GUILD_BANK_MAX_SLOTS in the core). A full tab makes the core no-op the
# move, so the planner never offers more stacks than the tab has room for.
GUILD_TAB_SLOTS = 98

# item_template.class values the keeper rule reads beside the four above.
ITEM_CLASS_CONSUMABLE = 0
ITEM_CLASS_GEM = 3
ITEM_CLASS_REAGENT = 5
ITEM_CLASS_TRADE_GOODS = 7
ITEM_CLASS_RECIPE = 9
ITEM_CLASS_MISC = 15

# item_instance.flags bit 1: ITEM_FIELD_FLAG_SOULBOUND. A bind-on-equip copy
# somebody has worn is bound even though its template says bonding 2.
_INSTANCE_SOULBOUND = 0x1

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
    place: str  # BAGS or BANK
    count: int
    container_slots: int  # >0 when the stack is itself a bag
    item: disposition.Item
    # The facts the keeper rule reads (#233). Every default is the answer
    # that stores nothing: entry 0 names no trade, rank 0 gates nothing, a
    # lock id of 0 is not a lockbox, and `bound` True keeps a stack out of
    # the guild bank.
    template_id: int = 0
    required_rank: int = 0
    lock_id: int = 0
    start_quest: int = 0
    bound: bool = True


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
    verb: str  # DEPOSIT or WITHDRAW
    guid: int
    item: str
    count: int
    why: str
    # PERSONAL for the holder's own bank, GUILD for the guild bank's tab 0.
    # Only a DEPOSIT is ever GUILD: nothing here withdraws from a guild bank.
    to: str = PERSONAL


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
    # The GUILD deposits, kept apart from `moves` because a different pass
    # walks to a different place to write them: `moves` are answered by a
    # banker, these by a guild vault.
    guild: tuple = ()


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
        binding=_BONDING.get(_int(row.get("bonding"), 1), disposition.BIND_ON_PICKUP),
        quest_item=item_class == ITEM_CLASS_QUEST,
        equipment=item_class in (ITEM_CLASS_WEAPON, ITEM_CLASS_ARMOR),
        required_level=_int(row.get("required_level")),
        sell_price=_int(row.get("sell_price")),
        auction_value=None,
        reagent_for=materials.REAGENTS.get(name),
        disenchant_skill_required=None,
        item_class=item_class,
        bag_family=_int(row.get("bag_family")),
        required_skill=_int(row.get("required_skill")),
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
        holding = Holding(
            holder=holder,
            guid=guid,
            place=place,
            count=max(1, _int(row.get("count"), 1)),
            container_slots=slots,
            item=item,
            template_id=_int(row.get("entry")),
            required_rank=_int(row.get("required_rank")),
            lock_id=_int(row.get("lock_id")),
            start_quest=_int(row.get("start_quest")),
            bound=(
                item.binding == disposition.BIND_ON_PICKUP
                or bool(_int(row.get("instance_flags")) & _INSTANCE_SOULBOUND)
            ),
        )
        (carried if place == BAGS else banked)[holder].append(holding)

    return tuple(
        Member(
            name=name,
            level=levels[name],
            bag_free=max(0, bag_room[name]),
            bank_free=max(0, bank_room[name]),
            carried=tuple(sorted(carried[name], key=_stack_order)),
            banked=tuple(sorted(banked[name], key=_stack_order)),
        )
        for name in sorted(wanted)
    )


def family_from_skills(
    held,
    *,
    vendor_reachable=True,
    auction_reachable=False,
    bank_reachable=True,
    reagent_keep=None,
):
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


# ---------------------------------------------------------------------------
# WHAT STAYS IN THE BAGS (#233)
#
# MEASURED ON THE DEV REALM 2026-09-23. A level 60 priest with 30 bag slots
# sat at 0 free, and this pass logged "nothing to put down" every cycle. It
# only ever banked what `disposition.decide` routed to BANK, and that verdict
# fires for one case: a material in `materials.REAGENTS` (six names) for a
# trade nobody has. Everything else falls to the old-green branch, which
# answers VENDOR for anything with a price - and the vendor pass then refuses
# it, because it sells Quality 1 and below. So 48 uncut gems, 8 recipes, 3
# lockboxes and a Libram were routed to a sale nobody would make, and the one
# place that could take them never saw a BANK verdict.
#
# THE KEEPER RULE ANSWERS A DIFFERENT QUESTION FROM DISPOSITION'S. Disposition
# asks "is this worth keeping". This asks "is it used FROM THE BAGS", which is
# the question a person asks at the bank counter. A gem nobody carrying it
# cuts, a recipe its holder cannot learn yet, a lockbox, another trade's stock
# and an uncommon keepsake are all worth keeping and none of them is used from
# a bag, so they go to storage. What the holder's own trades use stays, up to
# `disposition.REAGENT_KEEP` of each item, and only the stacks past that are
# stored - the same whole-stacks, largest-first rule `profession_keeps` uses,
# so the vendor pass and this one agree about which stacks are the shelf.
#
# WHAT IT NEVER TOUCHES. Quest-class stacks and anything that starts a quest
# (the quest rule's, bag_pressure.QUEST_NEEDED_SQL), consumables, weapons and
# armour (the gear passes'), bags, and trade stock no trade in the family
# claims at Quality 1 or below (the vendor's goods).
#
# TRADABLE KEEPERS GO TO THE GUILD BANK, the rest to the personal bank. The
# guild bank is shared, so a gem stored there is reachable by whoever takes up
# jewelcrafting; a bound stack can never enter it (mod-overseer's
# BankDepositItem refuses a soulbound item) and goes to the holder's own bank.
# The guild is only offered what its tab 0 has room for, and only from a
# holder whose rank carries the deposit-item right there.


@dataclass(frozen=True)
class Storage:
    """What the keeper rule needs to know beyond one stack.

    `trades` maps a holder to the trades that holder works (lower-case).
    `family_trades` is every trade the family works: stock one of those claims
    is protected from the vendor for somebody, so it is stored rather than
    left to a sale that will never happen. `skills` is holder ->
    {skill_id: value}, for the recipe test. `named` is entry -> the trades
    whose recipes buy it (bridge.REAGENT_TRADES). `guild_depositors` and
    `guild_free` describe the guild bank's tab 0. `routed` maps a recipe's
    guid to the crafter the designated-crafters register sends it to (#248):
    such a recipe stays in the bags for the hand-off, and comes out of the
    bank for it.
    """

    trades: dict = field(default_factory=dict)
    family_trades: frozenset = frozenset()
    skills: dict = field(default_factory=dict)
    named: dict = field(default_factory=dict)
    guild_depositors: frozenset = frozenset()
    guild_free: int = 0
    stock_cap: int = disposition.REAGENT_KEEP
    routed: dict = field(default_factory=dict)


def _trades_and_skills(held, worked_by):
    """holder -> worked trades, and holder -> {skill_id: value}."""
    trades: dict = {}
    skills: dict = {}
    for name, profs in (held or {}).items():
        own = trades.setdefault(str(name), set())
        ids = skills.setdefault(str(name), {})
        for profession, value in (profs or {}).items():
            profession = str(profession).strip().lower()
            if _int(value) > 0:
                own.add(profession)
            skill_id = goals.SKILL_IDS.get(profession)
            if skill_id:
                ids[skill_id] = _int(value)
    for name, declared in (worked_by or {}).items():
        trades.setdefault(str(name), set()).update(
            str(t).strip().lower() for t in declared if str(t).strip()
        )
    return trades, skills


def _guild_room(guild):
    """(members whose rank may deposit on tab 0, tab 0's free slots)."""
    if not guild or _int(guild.get("purchased_tabs")) <= 0:
        return frozenset(), 0
    rights = {_int(r) for r in guild.get("deposit_rank_ids", ())}
    depositors = frozenset(
        name
        for name, rank in dict(guild.get("member_ranks") or {}).items()
        if _int(rank, -1) in rights
    )
    free = max(0, GUILD_TAB_SLOTS - _int(guild.get("tab0_items"), GUILD_TAB_SLOTS))
    return depositors, free


def storage_from(held, worked_by=None, named=None, guild=None, routed=None):
    """The Storage this family is today, from what the bridge already reads.

    `held` is name -> {profession: value} (`_fetch_trade_skills`), `worked_by`
    is name -> declared trades (`_worked_by`), and `guild` is
    `_fetch_guild_bank_setup`'s answer or None. A trade counts as worked when
    the holder holds any skill in it or is declared to work it, the same
    union the vendor pass protects stock for.

    THE GUILD IS OPEN ONLY ON FACTS. No purchased tab, no member rank, or a
    rank without the right on tab 0, and the guild takes nothing: the core
    no-ops every one of those deposits without an error, so a guess here is a
    queue of refusals.
    """
    trades, skills = _trades_and_skills(held, worked_by)
    depositors, free = _guild_room(guild)
    return Storage(
        trades={name: frozenset(t) for name, t in trades.items()},
        family_trades=frozenset(t for own in trades.values() for t in own),
        skills=skills,
        named=dict(named or {}),
        guild_depositors=depositors,
        guild_free=free,
        routed=dict(routed or {}),
    )


# The classes the keeper rule never stores: quest items (the quest rule's),
# consumables (eaten from the bags), weapons and armour (the gear passes') and
# bags (bag_upgrade's).
_NEVER_STORED = frozenset(
    {
        ITEM_CLASS_QUEST,
        ITEM_CLASS_CONSUMABLE,
        ITEM_CLASS_WEAPON,
        ITEM_CLASS_ARMOR,
        ITEM_CLASS_CONTAINER,
    }
)


def _claims(holding, trades, named):
    """The first of `trades` that claims this stack as its stock, or ''.

    The craft tables first, then the item's own material name, then its bag,
    the order `disposition._trade_of` argues for.
    """
    trade = disposition._trade_of(
        holding.template_id, holding.item.bag_family, trades, named
    )
    if trade:
        return trade
    material = materials.REAGENTS.get(holding.item.name)
    if material and material in trades:
        return material
    return ""


def _learnable(holding, storage):
    """Could the holder learn this recipe today (recipebook.within_reach)?"""
    return recipebook.within_reach(
        holding.item.required_skill,
        holding.required_rank,
        storage.skills.get(holding.holder, {}),
    )


def stock_surplus(carried, storage):
    """The guids of own-trade stock past the cap, per holder and item.

    Whole stacks, largest first, at least one stack always kept: the rule
    `disposition._stock_keeps` applies to the family's shelf, applied here to
    one holder's bags. 25 Empty Vial against a cap of 40 is no surplus; three
    stacks of 20 Silverleaf keep two and store one.
    """
    by_key: dict = {}
    for holding in carried:
        trades = storage.trades.get(holding.holder, frozenset())
        if holding.item.item_class in _NEVER_STORED:
            continue
        if not _claims(holding, trades, storage.named):
            continue
        by_key.setdefault((holding.holder, holding.template_id), []).append(holding)
    surplus = set()
    for stacks in by_key.values():
        kept = 0
        for holding in sorted(stacks, key=_stack_order):
            if kept and kept + holding.count > storage.stock_cap:
                surplus.add(holding.guid)
                continue
            kept += holding.count
    return frozenset(surplus)


def storage_reason(holding, storage, surplus=frozenset()):
    """Why this stack belongs in storage and not in the bags, or ''.

    '' is the common answer and means "not this rule's business": the bags
    keep it, or another pass (the vendor, the gear passes, the quest rule)
    decides it. `surplus` is `stock_surplus` over the holder's carried stacks,
    and only matters for the holder's own trade stock.
    """
    item = holding.item
    if holding.container_slots > 0 or item.item_class in _NEVER_STORED:
        return ""
    if holding.start_quest > 0 or item.quest_item:
        return ""
    trades = storage.trades.get(holding.holder, frozenset())
    if disposition.recipe(item):
        if _learnable(holding, storage) or holding.guid in storage.routed:
            return ""
        return (
            "%s teaches a trade or a rank %s does not have yet, so it waits "
            "in storage rather than in a bag slot" % (item.name, holding.holder)
        )
    if item.item_class == ITEM_CLASS_MISC and holding.lock_id > 0:
        return "%s is a lockbox, and a closed box is not used from the bags" % item.name
    own = _claims(holding, trades, storage.named)
    if own:
        if holding.guid in surplus:
            return "%s is past the %d %s keeps for %s" % (
                item.name,
                storage.stock_cap,
                holding.holder,
                own,
            )
        return ""
    if item.item_class == ITEM_CLASS_GEM:
        return "%s is a gem and %s does not cut gems" % (item.name, holding.holder)
    claimed = _claims(holding, storage.family_trades, storage.named)
    if claimed:
        return "%s feeds %s, which %s does not work" % (
            item.name,
            claimed,
            holding.holder,
        )
    if item.quality >= 2:
        return "%s is kept but never used from the bags" % item.name
    return ""


def _stored(member, storage):
    """(holding, why) for every carried stack the keeper rule stores, in order.

    SURPLUS FIRST: stacks nobody in the bags uses at all go before the surplus
    of the holder's own stock, and inside each group the biggest pile goes
    first, because every stack is worth one slot whatever its size.
    """
    surplus = stock_surplus(member.carried, storage)
    found = []
    for holding in member.carried:
        why = storage_reason(holding, storage, surplus)
        if why:
            found.append((holding.guid in surplus, _stack_order(holding), holding, why))
    found.sort(key=lambda found_row: (found_row[0], found_row[1]))
    return [(holding, why) for _own, _order, holding, why in found]


def _verdict(holding, family, level, totals):
    """What disposition says about this stack, in this family, right now."""
    return disposition.decide(
        holding.item,
        family,
        character_level=level,
        upgrade_for_sibling=False,
        reagent_held=totals.get(holding.item.name, holding.count),
    )


def _deposit_candidates(member, family, totals, storage):
    """(holding, why, keeper) in deposit order: the keeper rule first."""
    candidates = [
        (holding, why, True)
        for holding, why in (_stored(member, storage) if storage else [])
    ]
    chosen = {holding.guid for holding, _why, _keeper in candidates}
    for holding in member.carried:
        if holding.guid in chosen or holding.container_slots > 0:
            # An empty spare bag belongs in somebody's empty bag position
            # and a full one cannot be moved at all. Either way the bank
            # is the wrong place for it.
            continue
        verdict = _verdict(holding, family, member.level, totals)
        if verdict.route == disposition.BANK:
            candidates.append((holding, verdict.why, False))
    return candidates


def _deposit(member, holding, why, to=PERSONAL):
    return Move(
        character=member.name,
        verb=DEPOSIT,
        guid=holding.guid,
        item=holding.item.name,
        count=holding.count,
        why=why,
        to=to,
    )


def _plan_deposits(member, candidates, storage, guild_room, visit_limit, notes):
    """(personal deposits, guild deposits, guild room left) for one member.

    A keeper that may go to the guild goes there while the tab has room and
    this member's vault visit has room; past either, it is offered to the
    banker, because the two trips are separate and a stack that leaves the
    bags by either one has done what it was planned for.
    """
    deposits, sent = [], []
    room = member.bank_free
    for holding, why, keeper in candidates:
        to_guild = (
            keeper and not holding.bound and member.name in storage.guild_depositors
        )
        if to_guild and guild_room <= 0:
            notes.append(
                "the guild bank's tab is full, so %s goes to %s's own bank"
                % (holding.item.name, member.name)
            )
        if to_guild and guild_room > 0 and len(sent) < visit_limit:
            guild_room -= 1
            sent.append(_deposit(member, holding, why, GUILD))
            continue
        if len(deposits) >= visit_limit:
            notes.append(
                "%s has more to bank than one visit carries; the "
                "rest waits for the next trip" % member.name
            )
            continue
        if room <= 0:
            notes.append(
                "%s's bank is full, so %s stays in the bags"
                % (member.name, holding.item.name)
            )
            continue
        room -= 1
        deposits.append(_deposit(member, holding, why))
    return deposits, sent, guild_room


def _wanted_back(holding, member, family, totals, storage):
    """Why a banked stack belongs in the bags again, or ''.

    A stack the keeper rule stores is never wanted back, so the two halves
    cannot undo each other. A recipe its holder can now learn is.
    """
    verdict = _verdict(holding, family, member.level, totals)
    if storage is None:
        return verdict.why if verdict.route in WITHDRAW_ROUTES else ""
    if storage_reason(holding, storage):
        return ""
    if disposition.recipe(holding.item) and _learnable(holding, storage):
        return "%s can learn it now" % member.name
    if disposition.recipe(holding.item) and holding.guid in storage.routed:
        return "%s is to go to %s, a designated crafter" % (
            holding.item.name,
            storage.routed[holding.guid],
        )
    return verdict.why if verdict.route in WITHDRAW_ROUTES else ""


def _plan_withdrawals(member, family, totals, storage, space, budget, notes):
    """The withdrawals for one member, within `space` slots and `budget` moves."""
    withdrawals = []
    for holding in member.banked:
        if len(withdrawals) >= budget:
            break
        if holding.container_slots > 0:
            continue
        why = _wanted_back(holding, member, family, totals, storage)
        if not why:
            continue
        if space <= 0:
            notes.append(
                "%s has no room to take %s back out" % (member.name, holding.item.name)
            )
            continue
        space -= 1
        withdrawals.append(
            Move(
                character=member.name,
                verb=WITHDRAW,
                guid=holding.guid,
                item=holding.item.name,
                count=holding.count,
                why="%s is wanted in the bags again - %s" % (holding.item.name, why),
            )
        )
    return withdrawals


def plan(members, family, *, visit_limit=VISIT_LIMIT, storage=None):
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

    `storage` turns on the keeper rule (#233; see the block above
    `Storage`). Without it the plan is disposition's BANK verdict alone,
    which is what this function did before. With it, the keeper rule's stacks
    are deposited first - tradable ones into `Plan.guild` while the guild can
    take them, the rest into `Plan.moves` - and a stack the rule stores is
    never withdrawn, so the two halves cannot undo each other.
    """
    totals = reagent_totals(members)
    moves, notes, guild = [], [], []
    guild_room = storage.guild_free if storage else 0
    for member in sorted(members, key=lambda m: m.name):
        candidates = _deposit_candidates(member, family, totals, storage)
        deposits, sent, guild_room = _plan_deposits(
            member, candidates, storage, guild_room, visit_limit, notes
        )
        # Every deposit hands a bag slot back, so the room to receive a
        # withdrawal is larger than it was measured. A guild deposit does not
        # count: it is written on a different trip, to a different place.
        withdrawals = _plan_withdrawals(
            member,
            family,
            totals,
            storage,
            member.bag_free + len(deposits),
            visit_limit - len(deposits),
            notes,
        )
        moves.extend(deposits)
        moves.extend(withdrawals)
        guild.extend(sent)
    return Plan(
        moves=tuple(moves),
        notes=tuple(dict.fromkeys(notes)),
        guild=tuple(guild),
    )


def command(move):
    """The exact command text mod-overseer's DoBank takes for one move.

    `guid:` and nothing else. The grammar has no `entry:` form on purpose,
    and the guid must be non-zero: zero is what every "not found" path in the
    core returns, so a row asking for it would be answered by whichever item
    that path happened to find.

    A GUILD move is the guild verb's text instead, rendered by the one
    formatter that already knows it (`bank deposit-item guid:<n>`), because
    it goes to DoGuild as a `kind='guild'` row and not to DoBank.
    """
    if move.to == GUILD:
        return guildbank.format_item_deposit(item_guid=move.guid)
    return "%s guid:%d" % (move.verb, move.guid)


# WHAT A BANK ERRAND SHOULD DO NEXT (infra#3728). Three words for the same
# reason towntrip.errand_step and bag_pressure.vendor_errand_step use three:
# "do not aim" and "hand the column back" are opposite intentions that both
# read as "no write this pass", and that is how the missing half stayed
# invisible in all three passes at once.
BANK_ERRAND_AIM = "aim"
BANK_ERRAND_HOLD = "hold"
BANK_ERRAND_RELEASE = "release"


def errand_step(at_counter: bool, rows_outstanding: int, moves_unasked: bool) -> str:
    """What to do with the leader's `banker` aim this pass (infra#3728).

    THE SAME LATCH AS THE SELL PASS'S, IN THE SAME COLUMN. `_bank_once` wrote
    `travel_npc = 'banker'` and nothing ever wrote it back; `banker` is one of
    the four aims `IsMaintenanceErrand` covers, so mod-overseer reaches "errand
    done, releasing" on arrival and then deliberately SKIPS the column write
    (infra#3655), naming the bridge as the half that clears it. The bridge never
    did, in any of the four passes.

    THREE INPUTS NOW, BECAUSE THE PARAGRAPH THAT ARGUED FOR TWO WAS WRONG ON A
    FACT (infra#3815). It said:

        "TWO INPUTS RATHER THAN THE TOWN TRIP'S THREE ... A bank row is written
        from wherever the family happens to be standing and waits `pending`
        until its holder reaches the counter (mod-overseer#209, infra#3311) ...
        so a queue this pass wrote and the world has fully answered is complete
        evidence about this errand's own work, with no 'has not started yet'
        window for an arrival test to close."

    A bank row does not wait. `DoBank` answers it on the next poll from where
    that character stands AT THAT INSTANT - `BankerInReach` searches
    INTERACTION_DISTANCE - and an empty answer goes to `refuse(..., "banker not
    in range")`, which is `describe("refused", reason); return detail;`. The
    second argument is the DETAIL COLUMN'S TEXT, not a retry class; only
    `kind='sell'` has one of those (`SellRefusalRetry`, mod-overseer#230), and
    nothing anywhere puts a bank row back to `pending`. Measured all-time on
    wow-dev: 115 `banker not in range` answered 1.05 SECONDS after the row was
    written, against one delivery in eight days. Nobody walks anywhere in one
    second, so the difference the paragraph called real runs the other way and
    the town trip's third input is the one this needs.

    THE PARAGRAPH AFTER IT WAS TRUE, AND ANSWERING IT IS THE POINT. It said:

        "AND AN ANSWER IS AN ANSWER, INCLUDING A REFUSAL ... counting refusals
        as outstanding would rebuild the latch one table over ... a trip whose
        rows were all refused for range ends this errand, and the pass tries
        again once the retry window lets it re-ask."

    Every sentence of that stands, and the bounded retry was the better of the
    two options ON OFFER - chosen with the measurement in hand and published
    beside it, which is why it was findable at all. What changed is the menu:
    `_bank_once` no longer writes a row into a journey that has not happened,
    so a third option exists that neither counts refusals as outstanding nor
    pays for them, and the refusals that paragraph was pricing stop being
    written at all.

    NOT KNOWING IS A REASON TO HOLD. A negative count is the bridge reporting
    that it could not read the queue at all; reading that as "finished" is the
    fail-open direction and it walks the family away from rows already queued.

    THE FOUR ANSWERS ARE `towntrip.errand_step`'S OWN, IN ITS ORDER, and its
    docstring argues each of them at length rather than twice: unanswered rows
    hold, nothing left to ask for releases, at the counter with work holds
    because the rows are written THIS pass, and away from it with work aims.
    The one that reads differently here is the terminal path - a trip that
    never arrived cannot reach it, because a move `_bank_once` held back for
    the walk is a move this pass has not asked for.

    `at_counter` IS THE LEADER'S OWN ARRIVAL, for the reason infra#3804 records
    one pass over: only the leader is aimed, the other four arrive behind it,
    and WHICH ROWS get written is asked again per mover in `_bank_once`. An
    arrived leader never meant five arrived movers, and this input does not
    claim it does - it decides the column, not the queue.

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

    AND IT IS NOW A MOVE THIS TRIP CAN STILL DO, the one place the gate could
    have built a new latch and did not (infra#3815). A move whose holder never
    arrives is never written, never enters the retry window, and would hold
    this input True for ever - the at-the-counter hold would then keep the
    column on a family that had finished. So `_bank_once` drops a move whose
    holder the world cannot see at all: `_fetch_positions` returns only
    snapshot rows fresher than a minute, and a name missing from it is a name
    nobody can hand anything to. A holder merely FAR AWAY still counts - that
    is the walk this errand exists to make - while one not in the world is not
    this trip's work, and used to be the 17 `target not online` rows.
    """
    if rows_outstanding != 0:
        return BANK_ERRAND_HOLD
    if not moves_unasked:
        return BANK_ERRAND_RELEASE
    return BANK_ERRAND_HOLD if at_counter else BANK_ERRAND_AIM


def lines(moves):
    """One log line per move, for a person reading the pass afterwards.

    Takes the moves rather than the Plan so the caller can log what it
    actually WROTE. A pass that logs its plan and writes half of it, because
    the other half was already queued inside the retry window, is a log that
    lies about what the family did.
    """
    return [
        "%s: %s %d %s (%s) - %s"
        % (move.character, move.verb, move.count, move.item, command(move), move.why)
        for move in moves
    ]
