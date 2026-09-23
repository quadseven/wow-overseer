"""Where a lockbox goes: to a family rogue who can pick it, or to a vendor (#88).

MEASURED ON WOW-DEV 2026-09-22. Grog (0 free slots) carried a Reinforced
Steel Lockbox and Ugga (0 free slots) carried another plus two Mithril
Lockboxes. No pass routed them: the vendor half sells only Quality 1 and
below, and a lockbox is Quality 2. Bork, the family rogue, has Lockpicking at
300 and six free slots.

THE ROUTE, IN ORDER.

    1. The holder can pick it: the holder unlocks it and opens it, through
       mod-playerbots' own chat commands `unlock items` (Pick Lock, spell
       1804, on the first locked item in the bags) and `open items`.
    2. A family rogue can pick it: it goes to that rogue, by a give when the
       two stand within trade range or by post from a mailbox, never a give
       across a distance (#193). The rogue then does step 1.
    3. Nobody in the family can: it is sold to a vendor.

A ROGUE IS NOT FILLED TO THE TRIGGER. A box handed over costs the rogue a
slot until it is opened, and a rogue at `bag_pressure.TOWN_RUN_FREE_SLOTS`
would itself withhold the family's dungeon campaign. So a rogue is handed a
box only while its free slots stay above that line after every box already
planned for it this pass.

THE LOCK SKILL. `acore_world.lock_dbc` holds no rows on this realm, so the
skill a lock needs cannot be read from the database. `LOCK_SKILL` carries the
3.3.5 Lock.dbc values for the classic lockboxes this family loots, keyed by
`item_template.lockid`. A lock not in it needs `UNKNOWN_LOCK_SKILL`, the
skill cap, so an unknown lock is only ever tried by a rogue at the top of the
trade. The world refuses a pick below the real value, and the box stays put.

PURE MODULE: no MySQL. The bridge reads the rows and writes the commands.
"""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure

ROGUE = 4
LOCKPICKING = 633
LOCKBOX_CLASS = 15
# `item_instance.flags` bit ITEM_FIELD_FLAG_UNLOCKED: Pick Lock has opened it.
UNLOCKED_FLAG = 0x4

# item_template.lockid -> the Lockpicking skill Lock.dbc asks for.
LOCK_SKILL = {5: 1, 23: 25, 24: 70, 60: 125, 61: 175, 62: 225}
UNKNOWN_LOCK_SKILL = 300

UNLOCK_COMMAND = "unlock items"
OPEN_COMMAND = "open items"


@dataclass(frozen=True)
class Box:
    """One carried lockbox, as the world rows describe it."""

    holder: str
    guid: int
    entry: int
    name: str
    lock_id: int
    unlocked: bool = False
    quality: int = 0
    sell_price: int = 0

    @property
    def skill_needed(self) -> int:
        return LOCK_SKILL.get(int(self.lock_id), UNKNOWN_LOCK_SKILL)


@dataclass(frozen=True)
class Picker:
    """One family member: class, Lockpicking skill and free slots."""

    name: str
    class_id: int
    lockpicking: int = 0
    free_slots: int = 0

    def can_pick(self, box: Box) -> bool:
        return int(self.class_id) == ROGUE and int(self.lockpicking) >= box.skill_needed


@dataclass(frozen=True)
class Hand:
    """One box moving from its holder to the rogue who will pick it."""

    holder: str
    taker: str
    box: Box
    why: str

    @property
    def command(self) -> str:
        """What mod-overseer's DoGive parses."""
        return "guid:%d" % int(self.box.guid)

    @property
    def post_command(self) -> str:
        """The kind='mail' send of the same box from a mailbox."""
        return "send item:%d subject:%s" % (int(self.box.guid), self.box.name)


@dataclass(frozen=True)
class Plan:
    """What happens to every carried lockbox this pass."""

    unlock: tuple = ()  # holders who carry a box that is still locked
    open: tuple = ()  # holders who carry a box that is already unlocked
    hands: tuple = ()  # Hand values
    sell: tuple = ()  # Box values nobody in the family can pick
    notes: tuple = ()


def boxes_from_rows(rows) -> list:
    """Box values from world rows; a row that cannot be read is dropped.

    A lockbox is `item_template.class` 15 with a `lockid`. The rows carry
    holder, item_guid, entry, name, item_class, lock_id and instance_flags.
    """
    out = []
    for row in rows or ():
        try:
            if int(row["item_class"]) != LOCKBOX_CLASS:
                continue
            lock_id = int(row.get("lock_id", 0) or 0)
            box = Box(
                holder=str(row["holder"]).strip(),
                guid=int(row["item_guid"]),
                entry=int(row["entry"]),
                name=str(row.get("name", "")),
                lock_id=lock_id,
                unlocked=bool(int(row.get("instance_flags", 0) or 0) & UNLOCKED_FLAG),
                quality=int(row.get("quality", 0) or 0),
                sell_price=int(row.get("sell_price", 0) or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if box.holder and box.guid > 0 and lock_id > 0:
            out.append(box)
    return out


def plan(boxes, pickers, trigger: int) -> Plan:
    """Route every box. `trigger` is `bag_pressure.TOWN_RUN_FREE_SLOTS`."""
    by_name = {p.name: p for p in pickers}
    incoming: dict = {}
    unlock, opens, hands, sell, notes = set(), set(), [], [], []
    for box in sorted(boxes, key=lambda b: (b.holder, b.guid)):
        holder = by_name.get(box.holder)
        if holder is not None and holder.can_pick(box):
            (opens if box.unlocked else unlock).add(box.holder)
            continue
        able = [p for p in pickers if p.name != box.holder and p.can_pick(box)]
        if not able:
            sell.append(box)
            continue
        room = [
            p
            for p in able
            if int(p.free_slots) - incoming.get(p.name, 0) - 1 > int(trigger)
        ]
        if not room:
            notes.append(
                "%s stays with %s: %s would drop to %d free slots or fewer"
                % (box.name, box.holder, " or ".join(p.name for p in able), trigger)
            )
            continue
        taker = max(
            room, key=lambda p: (int(p.free_slots) - incoming.get(p.name, 0), p.name)
        )
        incoming[taker.name] = incoming.get(taker.name, 0) + 1
        hands.append(
            Hand(
                holder=box.holder,
                taker=taker.name,
                box=box,
                why="%s has Lockpicking %d and %s needs %d"
                % (taker.name, taker.lockpicking, box.name, box.skill_needed),
            )
        )
    return Plan(
        unlock=tuple(sorted(unlock)),
        open=tuple(sorted(opens)),
        hands=tuple(hands),
        sell=tuple(sell),
        notes=tuple(notes),
    )


def sale_candidates(boxes) -> tuple:
    """The vendor pass's SellCandidate for each box nobody can pick.

    A lockbox is Quality 2, which `bag_pressure.sellable` refuses on purpose
    for gear. This is the one route that sells one, and only after `plan`
    found no rogue in the family who can open it. A box with no vendor price
    is kept.
    """
    return tuple(
        bag_pressure.SellCandidate(
            holder=box.holder,
            item_guid=box.guid,
            count=1,
            item=bag_pressure.ItemForSale(
                quality=box.quality, sell_price=box.sell_price
            ),
        )
        for box in boxes
        if box.sell_price > 0
    )
