"""Pure bag-pressure and vendor-sale decisions for the family economy loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


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
