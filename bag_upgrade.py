"""The bags a character needs are often already in its pockets.

MEASURED ON THE DEV FAMILY, 2026-09-04, while every other economy decision was
still a draft. All five were wedged: 273 of 274 slots used, four of the five at
zero free, material transfers failing with "receiver bags are full - GAVE UP
AFTER 3", and the quest drive stopped because a character with no room cannot
finish a loot. They were carrying 806 gold at the time.

What the inventories actually held:

    Grug   4 bags worn   carrying Small Red Pouch, Small Black Pouch x2
    Ugga   4 bags worn   carrying nothing
    Og     4 bags worn   carrying Small Black Pouch
    Grog   4 bags worn   carrying Red Leather Bag, Green Leather Bag
    Bork   3 bags worn   carrying nothing, AND ONE EMPTY BAG POSITION

Six unequipped bags, and an empty position to put one in. Those bags were
costing a slot each AND providing none, which is the worst of both. The family
did not need a vendor, money, a walk into town or a merchant transaction to get
room. It needed to put its own bags on.

WHY THIS IS A SEPARATE DECISION FROM SELLING. A vendor run is the expensive
answer: it needs travel, a live merchant, a transaction, and a sale rule good
enough not to sell the family's tailoring cloth. This needs none of those, so
it must be decided and applied FIRST - and, more sharply, a sale rule that ran
first would happily sell these bags, because a Small Black Pouch is a common
item with a vendor price like any other. `bags_in_plan` exists so the sale side
can be told what not to touch. That interaction is the whole reason these two
live next to each other.

PURE MODULE, same seam as the rest: no MySQL, no core, no browser. Everything
here is arithmetic over what the caller measured.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bag:
    """One bag, either worn in a position or carried loose in the inventory.

    `used` is meaningful only for a worn bag, and it is the reason a swap can
    be refused: emptying a bag that is holding things requires somewhere to put
    them.
    """

    name: str
    slots: int
    used: int = 0
    # The item_instance guid. A move is executed by naming the exact
    # item, not its kind: the family carries several identical pouches
    # and an entry id would name any of them.
    guid: int = 0
    # The item_template entry, which is what the playerbot equip verb names
    # (`self_equips`). 0 when the caller did not read it, and a bag with no
    # entry is never put on by its own holder.
    entry: int = 0
    # A general bag (item_template.subclass 0) holds anything. A herb bag or
    # a soul bag does not, so the core refuses to empty a worn bag into one;
    # only general bags are put on by their own holder.
    general: bool = True
    # The guid of the worn bag a carried bag sits in, 0 in the backpack. A
    # swap may not empty a worn bag into a spare that is inside it.
    inside: int = 0


@dataclass(frozen=True)
class BagMove:
    """One move, with the reason it is worth making written into it.

    `slots_gained` is the honest net change in usable slots, counting the slot
    the bag itself gives back when it stops being carried. It is what ranks the
    moves, and it is what a caller reports afterwards to say whether the plan
    did what it said.
    """

    action: str  # "equip" into an empty position, or "swap"
    bag: str  # the carried bag being put on
    position: int  # which bag position it goes into
    replaces: str | None  # the worn bag it displaces, on a swap
    slots_gained: int
    why: str


def _biggest_first(bags):
    """Deterministic order: largest first, then by name.

    The name tiebreak is not cosmetic. Two Small Black Pouches are
    indistinguishable by size, and a plan that reordered them between runs
    would make the tests flap and the logs unreadable.
    """
    return sorted(bags, key=lambda b: (-b.slots, b.name))


def fill_empty_positions(positions, worn, carried):
    """Put the largest carried bags into positions that hold nothing.

    This is the move with no downside at all, which is why it is separate and
    why it goes first. An empty position holds no items, so nothing has to be
    relocated and nothing can be orphaned; the bag stops costing a slot and
    starts providing several. The gain is its own slots PLUS the one it hands
    back by no longer being carried.
    """
    empty = [p for p in range(positions) if p >= len(worn)]
    moves = []
    for position, bag in zip(empty, _biggest_first(carried)):
        moves.append(
            BagMove(
                action="equip",
                bag=bag.name,
                position=position,
                replaces=None,
                slots_gained=bag.slots + 1,
                why="position %d was empty while this bag was being carried, so it "
                "cost a slot and gave none" % position,
            )
        )
    return moves


def _swap_is_safe(worn_bag, new_bag, free_slots):
    """May we take a bag off that still has things in it?

    Only when what comes out has somewhere to go. Taking a bag off does not
    delete what is inside it in a running world, but a swap planned without the
    room to land is a swap that half-completes, and the failure mode of a
    half-completed swap is items on the floor. So the test is conservative and
    counts the space that will exist AFTER the size change, not before.
    """
    if new_bag.slots <= worn_bag.slots:
        return False
    room_after = free_slots + (new_bag.slots - worn_bag.slots)
    return worn_bag.used <= room_after


def upgrade_swaps(worn, carried, free_slots, already_used=()):
    """Replace a small worn bag with a strictly larger carried one.

    Strictly larger, because an equal swap moves items for no gain and a
    smaller one is a loss dressed up as a decision. Each carried bag is used at
    most once, and each position is touched at most once, or the plan would
    describe the same bag being in two places.
    """
    spent = set(already_used)
    moves = []
    pool = _biggest_first([b for b in carried if b.name not in spent])
    # Smallest worn bag first: it is the one an upgrade helps most, and taking
    # them in a fixed order keeps the plan reproducible.
    for position, worn_bag in sorted(enumerate(worn), key=lambda p: (p[1].slots, p[0])):
        for candidate in pool:
            if candidate.name in spent:
                continue
            if not _swap_is_safe(worn_bag, candidate, free_slots):
                continue
            spent.add(candidate.name)
            moves.append(
                BagMove(
                    action="swap",
                    bag=candidate.name,
                    position=position,
                    replaces=worn_bag.name,
                    slots_gained=candidate.slots - worn_bag.slots,
                    why="%s holds %d slots where %s holds %d, and there is room to "
                    "land what comes out"
                    % (candidate.name, candidate.slots, worn_bag.name, worn_bag.slots),
                )
            )
            break
    return moves


def plan_bag_moves(positions, worn, carried, free_slots):
    """Every bag move worth making, best first, empty positions before swaps.

    Empty positions come first because they are unconditional gains and because
    filling one frees a slot that can then make a swap safe. Running them in
    the other order would refuse swaps this order allows.
    """
    filling = fill_empty_positions(positions, worn, carried)
    taken = {m.bag for m in filling}
    # Each filled position hands back the slot its bag was occupying, so the
    # room available to land a swap is larger than it was before filling.
    room = free_slots + sum(m.slots_gained for m in filling)
    return filling + upgrade_swaps(worn, carried, room, already_used=taken)


def bags_in_plan(moves):
    """The bags a sale rule must not sell.

    A Small Black Pouch is a common item with a vendor price, so nothing in the
    sale rule would spare it on its own. This is the list that does.
    """
    return {m.bag for m in moves}


def slots_gained(moves):
    """What the plan claims it will free, for reporting against reality."""
    return sum(m.slots_gained for m in moves)


# ---------------------------------------------------------------------------
# THE FAMILY, NOT THE CHARACTER
#
# Everything above reasons about one character's own bags, and on the measured
# family that decides nothing at all: the four who carry spare bags have no
# empty position, and the one with an empty position carries no spare.
#
#     Grug   4 worn   carrying Small Red Pouch, Small Black Pouch x2
#     Ugga   4 worn   carrying nothing
#     Og     4 worn   carrying Small Black Pouch
#     Grog   4 worn   carrying Red Leather Bag, Green Leather Bag
#     Bork   3 worn   carrying nothing, AND ONE EMPTY BAG POSITION
#
# Every useful move is therefore a transfer between two characters, and that is
# also the only move the world can actually perform: mod-overseer's DoGive
# equips a container straight into the receiver's bag slot, using the same core
# call a player makes dragging a bag onto a bag position, and because it equips
# rather than stores it needs NO free inventory slot on the receiver. That last
# property is what dissolves the deadlock - Bork has no room to receive the bag
# that would give him room, and does not need any.
#
# WHY THE MODULE HAS TO DO THIS AND THE WORLD CANNOT. mod-overseer already
# looks for a spare bag when a give is refused for want of room, but
# `SpareContainerFor(giver, receiver)` is scoped to the PAIR of the blocked
# give. On the measured family the blocked give is Grog -> Og, and Og has four
# of four positions filled, so no container can be offered and the rescue
# correctly fails. Bork, who has the empty position, is not party to that
# transfer and never will be. The family-wide match is the missing half, and it
# can only be made somewhere that can see all five at once.
#
# SAME-CHARACTER EQUIPS ARE `self_equips` BELOW, and they are a different verb.
# Putting on a bag you already carry is not a give. When this was first
# written `give` was the only mechanism, and nothing on the measured family
# needed more. The bag purchase (#150) has since used the playerbot equip verb
# (`e`) for a bag its own buyer carries, and measured on wow-dev 2026-09-22
# Grog carried a spare Red Leather Bag (8 slots) at 0 free slots while wearing
# a Small Green Pouch (6). That swap is the same verb.


@dataclass(frozen=True)
class Member:
    """One character's bag situation, as the caller measured it."""

    name: str
    positions: int
    worn: tuple = ()
    carried: tuple = ()


@dataclass(frozen=True)
class Handover:
    """One bag moving from somebody who cannot use it to somebody who can.

    `guid` is the item_instance guid, because that is what the give command
    names. A move without one cannot be executed, so it is not optional.
    """

    giver: str
    receiver: str
    bag: str
    guid: int
    slots_gained: int
    why: str


def _spares(members):
    """Every carried bag in the family, largest first, as (member, bag).

    Sorted so the biggest bag reaches the first empty position rather than
    whichever member happens to sort first, and tie-broken by holder name so
    two identical pouches are chosen in a stable order.
    """
    # The core refuses to trade a non-empty container.  Treating one as a
    # spare would enqueue a command that can never free space, then make the
    # real recovery look like another receiver-full loop.  `used` comes from
    # the bridge's fill count and is deliberately part of this pure seam.
    held = [(m, b) for m in members for b in m.carried if b.used == 0]
    return sorted(
        held,
        key=lambda pair: (-pair[1].slots, pair[0].name, pair[1].name, pair[1].guid),
    )


def plan_family_bags(members):
    """Hand the family's idle bags to whoever has somewhere to put them.

    Each empty position is filled once and each spare bag is given once. The
    gain is the bag's own capacity PLUS the slot it stops occupying in the
    giver's bags, which is why a transfer helps BOTH characters and why doing
    this before any vendor run is worth the ordering.
    """
    spares = _spares(members)
    taken = set()
    moves = []
    for member in sorted(members, key=lambda m: m.name):
        empty = member.positions - len(member.worn)
        for _ in range(max(0, empty)):
            choice = next(
                (
                    (holder, bag)
                    for holder, bag in spares
                    if bag.guid not in taken and holder.name != member.name
                ),
                None,
            )
            if choice is None:
                break
            holder, bag = choice
            taken.add(bag.guid)
            moves.append(
                Handover(
                    giver=holder.name,
                    receiver=member.name,
                    bag=bag.name,
                    guid=bag.guid,
                    slots_gained=bag.slots + 1,
                    why="%s has an empty bag position and %s is carrying %s as "
                    "cargo, where it costs a slot and gives none"
                    % (member.name, holder.name, bag.name),
                )
            )
    return moves


@dataclass(frozen=True)
class SelfEquip:
    """One carried bag its own holder puts on (#88).

    `replaces` names the worn bag it displaces on a swap, None when it goes
    into an empty position. `command` is the playerbot equip verb.
    """

    holder: str
    bag: str
    entry: int
    guid: int
    replaces: str | None
    slots_gained: int
    why: str

    @property
    def command(self) -> str:
        """`e` with an item link. mod-playerbots' EquipAction puts a container
        into the first empty bag position, else in place of the smallest worn
        bag (EquipAction::GetSmallestBagSlot, the last of equal sizes)."""
        return "e Hitem:%d:0" % int(self.entry)


def _smallest_worn(worn):
    """The worn bags the equip verb may pick, and their size.

    GetSmallestBagSlot takes the last of several equal smallest bags, and
    which one that is depends on bag positions this planner does not read.
    So every worn bag of the smallest size is a candidate, and a swap must be
    safe against each of them.
    """
    size = min(bag.slots for bag in worn)
    return size, [bag for bag in worn if bag.slots == size]


def self_equips(members):
    """The carried bags their own holders should put on, one per holder.

    AN EMPTY POSITION FIRST. The equip verb fills one before it swaps
    anything, and a bag there gains its own slots plus the slot it stops
    occupying.

    OTHERWISE A SWAP, ONLY WHEN THE CORE CAN DO IT. With every position full
    the verb swaps the spare for the smallest worn bag. The core then moves
    that bag's items into the spare (Player::SwapItem's bag exchange), so the
    swap needs a general spare that is strictly larger, empty, holds every
    item of each smallest worn bag, and is not inside one of them. The free
    slots elsewhere do not matter, which is why `_swap_is_safe` above is not
    the test here. The displaced bag is carried afterwards, where
    `plan_family_bags` hands it on or `bag_pressure.bag_candidates` sells it.
    """
    moves = []
    for member in sorted(members, key=lambda m: m.name):
        spares = [
            bag
            for bag in member.carried
            if bag.used == 0 and bag.general and bag.entry > 0 and bag.guid > 0
        ]
        if not spares:
            continue
        best = _biggest_first(spares)[0]
        if member.positions - len(member.worn) > 0:
            moves.append(
                SelfEquip(
                    holder=member.name,
                    bag=best.name,
                    entry=best.entry,
                    guid=best.guid,
                    replaces=None,
                    slots_gained=best.slots + 1,
                    why="%s has an empty bag position and carries %s as cargo"
                    % (member.name, best.name),
                )
            )
            continue
        if not member.worn:
            continue
        size, smallest = _smallest_worn(member.worn)
        if best.slots <= size:
            continue
        if any(bag.used > best.slots for bag in smallest):
            continue
        if best.inside and best.inside in {bag.guid for bag in smallest}:
            continue
        moves.append(
            SelfEquip(
                holder=member.name,
                bag=best.name,
                entry=best.entry,
                guid=best.guid,
                replaces=smallest[-1].name,
                slots_gained=best.slots - size,
                why="%s holds %d slots where the smallest worn bag holds %d"
                % (best.name, best.slots, size),
            )
        )
    return moves


def without_bags(members, guids):
    """The members with the given carried bags removed from their cargo.

    Used so a bag its holder is putting on is not also handed to a sibling
    by `plan_family_bags` in the same pass.
    """
    gone = set(guids)
    return [
        Member(
            m.name,
            m.positions,
            worn=m.worn,
            carried=tuple(b for b in m.carried if b.guid not in gone),
        )
        for m in members
    ]


def give_command(move):
    """The command text mod-overseer's DoGive takes for one handover.

    `guid:` rather than `entry:` because the family carries several identical
    pouches and an entry would name any of them. The guid names the one that
    was actually weighed and chosen.
    """
    return "guid:%d" % move.guid


# ---------------------------------------------------------------------------
# FROM ROWS TO MEMBERS
#
# The bridge fetches one row per container the family owns and nothing else;
# which of those rows is a WORN bag, which is CARGO, and which is out of reach
# in the bank is decided here, where it can be tested against rows written by
# hand rather than against a live character_inventory.
#
# Inventory geography is the core's own (Player.h, the 3.3.5 slot enums), the
# same ranges panel.py draws from:
#
#     bag 0, slot 19..22   the four bag positions            -> worn
#     bag 0, slot 23..38   the built-in backpack             -> carried
#     bag = a worn bag     inside one of the four            -> carried
#     bag 0, slot 39..66   bank item slots                   -> ignored
#     bag 0, slot 67..73   bank bag positions                -> ignored
#     bag = a bank bag     inside the bank                   -> ignored
#
# A bag in the bank is not "spare" for this planner: DoGive moves what the
# giver is CARRYING, and a bag sitting in the bank is exactly as unreachable
# as one on the auction house until somebody walks to a banker. Counting it
# would plan a give the world refuses, which is the failure mode this whole
# file exists to stop.

BAG_POSITIONS = range(19, 23)
BACKPACK_POSITIONS = range(23, 39)


def members_from_rows(rows, names, positions=len(BAG_POSITIONS)):
    """One Member per name, whether or not any row mentions them.

    A character with no container rows at all still has `positions` empty
    bag positions, and a name missing from the result would make the planner
    forget the one member who most needs a bag. `rows` carry holder, guid,
    name, slots, bag, slot and used, as the bridge's SQL names them.
    """
    by_name = {name: {"worn": [], "carried": []} for name in names}
    worn_guids = {}
    for row in rows:
        if row["holder"] not in by_name:
            continue
        if int(row["bag"]) == 0 and int(row["slot"]) in BAG_POSITIONS:
            worn_guids.setdefault(row["holder"], set()).add(int(row["guid"]))
    for row in rows:
        holder = row["holder"]
        if holder not in by_name:
            continue
        container, slot = int(row["bag"]), int(row["slot"])
        bag = Bag(
            row["name"],
            int(row["slots"]),
            used=int(row.get("used", 0)),
            guid=int(row["guid"]),
            entry=int(row.get("entry", 0) or 0),
            general=int(row.get("subclass", 0) or 0) == 0,
            inside=container,
        )
        if container == 0 and slot in BAG_POSITIONS:
            by_name[holder]["worn"].append(bag)
        elif (
            container == 0 and slot in BACKPACK_POSITIONS
        ) or container in worn_guids.get(holder, ()):
            by_name[holder]["carried"].append(bag)
    return [
        Member(
            name,
            positions,
            worn=tuple(sorted(by_name[name]["worn"], key=lambda b: b.guid)),
            carried=tuple(sorted(by_name[name]["carried"], key=lambda b: b.guid)),
        )
        for name in sorted(by_name)
    ]
