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


@dataclass(frozen=True)
class BagMove:
    """One move, with the reason it is worth making written into it.

    `slots_gained` is the honest net change in usable slots, counting the slot
    the bag itself gives back when it stops being carried. It is what ranks the
    moves, and it is what a caller reports afterwards to say whether the plan
    did what it said.
    """
    action: str            # "equip" into an empty position, or "swap"
    bag: str               # the carried bag being put on
    position: int          # which bag position it goes into
    replaces: str | None   # the worn bag it displaces, on a swap
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
        moves.append(BagMove(
            action="equip", bag=bag.name, position=position, replaces=None,
            slots_gained=bag.slots + 1,
            why="position %d was empty while this bag was being carried, so it "
                "cost a slot and gave none" % position))
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
            moves.append(BagMove(
                action="swap", bag=candidate.name, position=position,
                replaces=worn_bag.name,
                slots_gained=candidate.slots - worn_bag.slots,
                why="%s holds %d slots where %s holds %d, and there is room to "
                    "land what comes out"
                    % (candidate.name, candidate.slots, worn_bag.name,
                       worn_bag.slots)))
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
