"""Pure bag-pressure and vendor-sale decisions for the family economy loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import disposition

# The two item classes that are worn: weapons and armour. A bag is class 1 and
# is deliberately not here, because an empty bag is still slots.
EQUIPMENT_CLASSES = frozenset({2, 4})

# `item_template.bonding` as the core writes it. 3 is bind-on-use, which is
# still tradable while it sits in the bag, and 4 is a quest binding that the
# quest_item gate refuses long before binding is consulted. A value outside
# this map is a fact we do not have, and a row we cannot read the binding of
# is dropped rather than guessed at.
_BONDING = {
    0: disposition.BIND_NONE,
    1: disposition.BIND_ON_PICKUP,
    2: disposition.BIND_ON_EQUIP,
    3: disposition.BIND_NONE,
}

# item_instance.flags bit 1: ITEM_FIELD_FLAG_SOULBOUND.
_INSTANCE_SOULBOUND = 0x1


@dataclass(frozen=True)
class ItemForSale:
    quality: int
    quest_item: bool = False
    reagent: bool = False
    profession_needed: bool = False
    sell_price: int = 0


@dataclass(frozen=True)
class SellCandidate:
    """A carried stack the world executor may offer to a vendor."""
    holder: str
    item_guid: int
    count: int
    item: ItemForSale


def vendor_candidates(rows: Iterable[dict]) -> tuple[SellCandidate, ...]:
    """Select only explicitly classified, safe carried vendor goods.

    The adapter supplies flags from world data. Missing flags are dangerous
    and therefore become False only for positive facts such as ``quest_item``;
    unknown identity, price, or count keeps the row out of the action queue.
    """
    out = []
    for row in rows:
        try:
            item = ItemForSale(
                quality=int(row["quality"]),
                quest_item=bool(row.get("quest_item", True)),
                reagent=bool(row.get("reagent", True)),
                profession_needed=bool(row.get("profession_needed", True)),
                sell_price=int(row["sell_price"]),
            )
            candidate = SellCandidate(
                holder=str(row["holder"]), item_guid=int(row["item_guid"]),
                count=int(row.get("count", 0)), item=item,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if candidate.item_guid > 0 and candidate.count > 0 and sellable(item):
            out.append(candidate)
    return tuple(out)


def vendor_batch(candidates: Iterable[SellCandidate]) -> tuple[str, tuple[SellCandidate, ...]]:
    """Choose one holder's safe stacks for a single vendor errand.

    The world executor sells items carried by the character named on each
    command. Sending every holder to one leader's vendor position makes all
    but the leader fail the core's interaction-range check, so one pass must
    be scoped to one travelling holder.
    """
    grouped: dict[str, list[SellCandidate]] = {}
    for candidate in candidates:
        if not isinstance(candidate, SellCandidate) or not candidate.holder:
            continue
        grouped.setdefault(candidate.holder, []).append(candidate)
    if not grouped:
        return "", ()
    holder = sorted(grouped)[0]
    return holder, tuple(grouped[holder])


def town_run_needed(used: int, slots: int, minimum_free: int = 2,
                    pressure_percent: int = 90) -> bool:
    """Return whether bag pressure warrants a vendor run."""
    if slots <= 0 or used < 0 or used > slots:
        return False
    free = slots - used
    return free <= minimum_free or used * 100 >= slots * pressure_percent


def sellable(item: ItemForSale) -> bool:
    """Sell only safe vendor goods: never rare, quest, reagent, or needed."""
    return (item.quality <= 1 and not item.quest_item and not item.reagent
            and not item.profession_needed and item.sell_price > 0)


def bag_purchase_allowed(money: int, price: int, empty_position: bool,
                         reserve: int = 10000) -> bool:
    """Buy a bag only when a real slot exists and the reserve remains."""
    return empty_position and price > 0 and money >= price + reserve


def item_binding(row) -> str:
    """How this particular copy is bound, which is not what the template says.

    SOULBOUND IS A FACT ABOUT THE INSTANCE. A bind-on-equip green somebody
    wore once is bound forever and its template still reads `bonding = 2`.
    Measured 2026-09-05: of the 111 bind-on-equip greens the family carries,
    38 are already soulbound in `item_instance.flags`. Reading the template
    alone calls those 38 tradable and holds them for an auction house that can
    never list them, which is exactly the bag that never empties.
    """
    flags = int(row.get("instance_flags", 0) or 0)
    if flags & _INSTANCE_SOULBOUND:
        return disposition.BIND_ON_PICKUP
    return _BONDING.get(int(row.get("bonding", -1) or 0), "")


def gear_candidates(rows: Iterable[dict], family, available=None
                    ) -> tuple[SellCandidate, ...]:
    """Carried equipment whose only honest route is a vendor (infra#3330).

    `disposition.decide` makes every judgement; this is the adapter that turns
    world rows into the items it wants and drops the rows it cannot describe.
    Only a VENDOR verdict becomes a candidate, because a sale is the only
    thing the caller can write today; a KEEP, or an AUCTION or BANK verdict
    withheld for want of an executor, produces nothing and the item stays put.

    THE SIBLING-UPGRADE QUESTION IS NOT ANSWERED HERE and must not be. Whether
    a carried green would be an upgrade for somebody else is mod-overseer#189's
    job; until it exists, `disposition` keeps every tradable piece and only
    soulbound gear the wearer has outgrown by the `outgrown` margin is offered
    to a vendor. Nobody can trade, list or wear those, so no route loses out.
    """
    if available is None:
        available = disposition.EXECUTABLE_TODAY
    out = []
    for row in rows:
        try:
            binding = item_binding(row)
            if not binding:
                continue
            item_class = int(row["item_class"])
            item = disposition.Item(
                name=str(row["name"]),
                quality=int(row["quality"]),
                known=True,
                binding=binding,
                quest_item=item_class == 12,
                equipment=item_class in EQUIPMENT_CLASSES,
                required_level=int(row["required_level"]),
                sell_price=int(row["sell_price"]),
            )
            holder = str(row["holder"])
            guid = int(row["item_guid"])
            count = int(row.get("count", 0))
            level = int(row["level"])
        except (KeyError, TypeError, ValueError):
            continue
        if guid <= 0 or count <= 0 or not holder:
            continue
        verdict = disposition.decide(item, family, character_level=level,
                                     available=available)
        if verdict.route != disposition.VENDOR:
            continue
        out.append(SellCandidate(
            holder=holder, item_guid=guid, count=count,
            # Carried only so the insert path has one shape to write. The
            # decision above is disposition's, not `sellable`'s, which refuses
            # every uncommon on purpose and would refuse these too.
            item=ItemForSale(quality=item.quality, sell_price=item.sell_price),
        ))
    return tuple(out)
