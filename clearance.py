"""Where a gem or a spare recipe goes when it is only filling a bag (#148, #145).

MEASURED ON WOW-DEV 2026-09-22, with both families' dungeon campaigns withheld
for full bags. One member at 0 free slots carried eight gem stacks, three
engineering schematics his skill of 1 cannot learn and a jewelcrafting design
nobody in the family can use. Another at 0 carried eight gem stacks and six
recipes above her skills. The guild (71 members, 59 online) held 26
jewelcrafters and 20 engineers at 260 or more. Nothing routed any of it:
`guildshare` moved only trade goods and three consumables, the auction pass
listed only unwanted bind-on-equip gear, and the vendor half refuses Quality 2.

THE ROUTE, IN ORDER, AND THE FIRST ONE THAT APPLIES WINS.

    KEEP      a recipe its holder can learn now (the recipe pass learns it),
              a recipe another family member is assigned (the family recipe
              hand-off owns it), a gem one of the family's own trades uses
              (`disposition.profession_keeps`), and anything bound that its
              holder can still use.
    FAMILY    a family member other than the holder can use it: a
              jewelcrafter for a gem, the recipe's trade at its rank.
    GUILD     an online guildmate can use it, by the same test.
    WAIT      a guildmate can use it and none of them is online now. Mail
              needs the receiver online (mod-overseer's DoMail), so it waits
              rather than being sold out from under somebody who wants it.
    AUCTION   nobody in the family or guild can use it, the auction house is
              reachable, and the market price beats the vendor price by
              `disposition.AUCTION_BEATS_VENDOR_BY`.
    VENDOR    the rest, when the vendor pays for it.

"CAN LEARN NOW", NOT "COULD REACH AT THIS LEVEL". #145 asked for the second.
The operator's direction was the first: a recipe whose holder's skill is below
its rank is routed, not kept for the day the holder catches up. A level-60
engineer at skill 1 carrying a rank-265 schematic is the case measured.

PURE MODULE: no MySQL. The bridge reads rows and writes commands.
"""

from __future__ import annotations

from dataclasses import dataclass

import disposition

GEM_CLASS = 3
RECIPE_CLASS = disposition.RECIPE_CLASS
JEWELCRAFTING = 755
# `item_instance.flags` bit ITEM_FIELD_FLAG_SOULBOUND.
SOULBOUND_FLAG = 0x1

KEEP = "keep"
FAMILY = "family"
GUILD = "guild"
WAIT = "wait"
AUCTION = "auction"
VENDOR = "vendor"
GIVEN = (FAMILY, GUILD)


@dataclass(frozen=True)
class Stack:
    """One carried gem or recipe stack, as the world rows describe it."""

    holder: str
    guid: int
    entry: int
    name: str
    item_class: int
    count: int = 1
    quality: int = 0
    sell_price: int = 0
    required_skill: int = 0
    required_rank: int = 0
    bound: bool = False

    @property
    def gem(self) -> bool:
        return int(self.item_class) == GEM_CLASS

    @property
    def recipe(self) -> bool:
        return int(self.item_class) == RECIPE_CLASS and int(self.required_skill) > 0


@dataclass(frozen=True)
class Person:
    """One family member or guildmate: skill line id -> value, and presence."""

    name: str
    skills: dict
    family: bool = False
    online: bool = False

    def rank(self, skill: int) -> int:
        return int((self.skills or {}).get(int(skill), 0) or 0)


@dataclass(frozen=True)
class Route:
    """Where one stack goes, who takes it, and why."""

    stack: Stack
    route: str
    taker: str = ""
    why: str = ""


def stacks_from_rows(rows) -> list:
    """Stack values for gems and skill-gated recipes; unreadable rows dropped."""
    out = []
    for row in rows or ():
        try:
            item_class = int(row["item_class"])
            bonding = int(row.get("bonding", 0) or 0)
            flags = int(row.get("instance_flags", 0) or 0)
            stack = Stack(
                holder=str(row["holder"]).strip(),
                guid=int(row["item_guid"]),
                entry=int(row["entry"]),
                name=str(row.get("name", "")),
                item_class=item_class,
                count=int(row.get("count", 1) or 1),
                quality=int(row.get("quality", 0) or 0),
                sell_price=int(row.get("sell_price", 0) or 0),
                required_skill=int(row.get("required_skill", 0) or 0),
                required_rank=int(row.get("required_rank", 0) or 0),
                bound=bonding in (1, 4) or bool(flags & SOULBOUND_FLAG),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not stack.holder or stack.guid <= 0 or stack.count <= 0:
            continue
        if stack.gem or stack.recipe:
            out.append(stack)
    return out


def can_learn_now(stack: Stack, person: Person) -> bool:
    """Has this person the recipe's trade at its rank today (#145)?"""
    return disposition.learnable_now(
        person.rank(stack.required_skill), stack.required_rank
    )


def can_use(stack: Stack, person: Person) -> str:
    """Why this person could use the stack, or ''."""
    if stack.recipe:
        if can_learn_now(stack, person):
            return "%s can learn it now" % person.name
        return ""
    if stack.gem and person.rank(JEWELCRAFTING) > 0:
        return "%s cuts gems" % person.name
    return ""


def _first(stack: Stack, people, *, family=None, online=False, skip=()):
    for person in sorted(people, key=lambda p: p.name):
        if person.name == stack.holder or person.name in skip:
            continue
        if family is not None and bool(person.family) != family:
            continue
        if online and not person.online:
            continue
        need = can_use(stack, person)
        if need:
            return person, need
    return None, ""


def route(
    stack: Stack,
    holder: Person | None,
    people,
    *,
    kept=frozenset(),
    market=None,
    auction_open: bool = False,
    busy=frozenset(),
) -> Route:
    """One stack's route. See the module docstring for the order.

    `kept` are guids another pass owns: the family recipe hand-off, or the
    family's own trade stock. `market` maps an entry to its lowest buyout per
    unit at the house the family reaches; an entry absent from it has no
    known price and is not listed. `busy` are people already handed a stack
    this pass: they take nothing more now, but they still count as somebody
    who can use it, so the stack waits rather than being sold.
    """
    if stack.guid in kept:
        return Route(stack, KEEP, why="another pass owns %s" % stack.name)
    if stack.recipe and holder is not None and can_learn_now(stack, holder):
        return Route(stack, KEEP, why="%s can learn %s now" % (holder.name, stack.name))
    if not stack.bound:
        for family in (True, False):
            person, need = _first(stack, people, family=family, online=True, skip=busy)
            if person is not None:
                return Route(stack, FAMILY if family else GUILD, person.name, need)
        person, need = _first(stack, people)
        if person is not None:
            return Route(
                stack,
                WAIT,
                person.name,
                "%s; nobody free to take it is online this pass, and a letter "
                "needs its receiver online" % need,
            )
        price = (market or {}).get(stack.entry)
        if (
            auction_open
            and price
            and price >= max(1, stack.sell_price) * disposition.AUCTION_BEATS_VENDOR_BY
        ):
            return Route(
                stack,
                AUCTION,
                why="nobody in the family or guild can use %s, and it sells for "
                "%d copper each listed against %d at a vendor"
                % (stack.name, price, stack.sell_price),
            )
    if stack.sell_price > 0:
        return Route(
            stack,
            VENDOR,
            why="nobody who can use %s can be handed it, and a vendor pays %d "
            "copper" % (stack.name, stack.sell_price),
        )
    return Route(stack, KEEP, why="%s has no route and no vendor price" % stack.name)


def plan(stacks, people, *, kept=frozenset(), market=None, auction_open=False) -> tuple:
    """Every stack's Route, holders in name order.

    A guildmate or family member is handed at most one stack per pass, the
    budget `guildshare._best_taker` keeps for the same reason: nobody reads
    their bags, and a receiver is only known to have one free slot.
    """
    people = list(people)
    by_name = {p.name: p for p in people}
    taken: set = set()
    out = []
    for stack in sorted(stacks, key=lambda s: (s.holder, s.name, s.guid)):
        got = route(
            stack,
            by_name.get(stack.holder),
            people,
            kept=kept,
            market=market,
            auction_open=auction_open,
            busy=frozenset(taken),
        )
        if got.route in GIVEN:
            taken.add(got.taker)
        out.append(got)
    return tuple(out)


def counts(routes) -> dict:
    """route -> how many stacks took it, for the pass's log line."""
    out: dict = {}
    for got in routes:
        out[got.route] = out.get(got.route, 0) + 1
    return out
