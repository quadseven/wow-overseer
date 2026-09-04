"""Pure bag-pressure and vendor-sale decisions for the family economy loop."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemForSale:
    quality: int
    quest_item: bool = False
    reagent: bool = False
    profession_needed: bool = False
    sell_price: int = 0


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
