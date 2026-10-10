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

A CRAFTING MATERIAL PAST ITS KEEP CAP TAKES THE SAME ROAD, WITH ONE STOP MORE.
The family keeps `disposition.MATERIAL_KEEP` of each material a holder carries
and the surplus used to be vendor goods, so a crafter's fifty-five stacks of
cloth went to a vendor for copper while guildmates raised trades on nothing.
The order for a surplus material stack is now

    GUILD     an online guildmate outside the family who holds a trade that
              consumes it (`guildshare.FEEDS`), by give or by letter.
    BANK      the guild vault, when the guild has a tab, the holder's rank may
              deposit and the tab has room. bank.py's keeper rule makes the
              deposit; this route only keeps the stack away from the vendor.
    AUCTION   the house pays `disposition.AUCTION_BEATS_VENDOR_BY` times the
              vendor price.
    VENDOR    the last resort, when nobody can use it and nothing else takes it.

PAST THE GUILD'S TARGET (bankforecast, 2026-10-10) a material takes a shorter
road. The guild already holds more of it than it will eat over the forecast's
horizon, so the vault is skipped, a guildmate takes it only when its current
rung is short of it (`short`), and the house is asked at the fair price read
from its own history (`fair`) when no live listing names one.

A material never WAITs for an offline guildmate: cloth is not scarce enough to
hold a full bag for, and the next pass asks again. The family is not a taker
for a material either; `materials.py` owns hand-offs inside the family.

A RECIPE THE DESIGNATED-CRAFTERS REGISTER PLACES (#248) skips the by-name
search: `crafters.choose` has already picked the family member or designated
guild crafter who learns it, skipping anyone who already knows it. A recipe
it places with nobody goes on to KEEP, AUCTION or VENDOR as before.

"CAN LEARN NOW", NOT "COULD REACH AT THIS LEVEL". #145 asked for the second.
The operator's direction was the first: a recipe whose holder's skill is below
its rank is routed, not kept for the day the holder catches up. A level-60
engineer at skill 1 carrying a rank-265 schematic is the case measured.

PURE MODULE: no MySQL. The bridge reads rows and writes commands.
"""

from __future__ import annotations

from dataclasses import dataclass

import disposition
import guildshare

GEM_CLASS = 3
RECIPE_CLASS = disposition.RECIPE_CLASS
JEWELCRAFTING = 755
# `item_instance.flags` bit ITEM_FIELD_FLAG_SOULBOUND.
SOULBOUND_FLAG = 0x1

KEEP = "keep"
BANK = "bank"
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
    subclass: int = 0
    # A crafting material past its holder's keep cap (`disposition.MATERIAL_KEEP`).
    # The caller sets it; the stack is otherwise a trade good this module ignores.
    material: bool = False

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


def _stack_from_row(row) -> Stack:
    """One Stack from one world row; raises on a row that cannot be read."""
    bonding = int(row.get("bonding", 0) or 0)
    flags = int(row.get("instance_flags", 0) or 0)
    return Stack(
        holder=str(row["holder"]).strip(),
        guid=int(row["item_guid"]),
        entry=int(row["entry"]),
        name=str(row.get("name", "")),
        item_class=int(row["item_class"]),
        count=int(row.get("count", 1) or 1),
        quality=int(row.get("quality", 0) or 0),
        sell_price=int(row.get("sell_price", 0) or 0),
        required_skill=int(row.get("required_skill", 0) or 0),
        required_rank=int(row.get("required_rank", 0) or 0),
        bound=bonding in (1, 4) or bool(flags & SOULBOUND_FLAG),
        subclass=int(row.get("subclass", 0) or 0),
        material=bool(row.get("material_surplus", False)),
    )


def stacks_from_rows(rows) -> list:
    """Stack values for gems and skill-gated recipes; unreadable rows dropped."""
    out = []
    for row in rows or ():
        try:
            stack = _stack_from_row(row)
        except (KeyError, TypeError, ValueError):
            continue
        if stack.holder and stack.guid > 0 and stack.count > 0:
            if stack.gem or stack.recipe or stack.material:
                out.append(stack)
    return out


def can_learn_now(stack: Stack, person: Person) -> bool:
    """Has this person the recipe's trade at its rank today (#145)?"""
    return disposition.learnable_now(
        person.rank(stack.required_skill), stack.required_rank
    )


def can_use(stack: Stack, person: Person) -> str:
    """Why this person could use the stack, or ''."""
    if stack.material:
        return _material_use(stack, person)
    if stack.recipe:
        if can_learn_now(stack, person):
            return "%s can learn it now" % person.name
        return ""
    if stack.gem and person.rank(JEWELCRAFTING) > 0:
        return "%s cuts gems" % person.name
    return ""


def _material_use(stack: Stack, person: Person) -> str:
    """The trade this person holds that consumes the material, or ''.

    The trade is read off the item's own subclass, `guildshare.FEEDS`, and the
    skill line off `character_skills`: the same two facts guildshare asks.
    """
    for trade in guildshare.FEEDS.get(int(stack.subclass), ()):
        if person.rank(guildshare.SKILL_LINES.get(trade, 0)) > 0:
            return "%s has %s" % (person.name, trade)
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
    picks=None,
    vault=frozenset(),
    over_target=None,
    fair=None,
    short=None,
) -> Route:
    """One stack's route. See the module docstring for the order.

    `kept` are guids another pass owns: the family recipe hand-off, or the
    family's own trade stock. `market` maps an entry to its lowest buyout per
    unit at the house the family reaches; an entry absent from it has no
    known price and is not listed. `busy` are people already handed a stack
    this pass: they take nothing more now, but they still count as somebody
    who can use it, so the stack waits rather than being sold.

    `picks` maps a recipe's guid to `crafters.Pick` (#248). When a recipe has
    one, the designated-crafters register decides who takes it, and the
    by-name search below is not asked.

    `vault` names the holders whose surplus the guild bank will take now: the
    guild has a tab with room and the holder's rank may deposit into it.

    `over_target` maps an entry the guild holds past its reserve target to
    why (bankforecast); `fair` an entry to a fair price per unit from the
    house's history; `short` an entry to the members whose current rung is
    short of it.
    """
    if stack.material and stack.entry in (over_target or {}):
        return _past_target_route(
            stack,
            people,
            kept,
            market,
            auction_open,
            busy,
            over_target[stack.entry],
            (fair or {}).get(stack.entry, 0),
            frozenset((short or {}).get(stack.entry, ())),
        )
    if stack.material:
        return _material_route(stack, people, kept, market, auction_open, busy, vault)
    pick = (picks or {}).get(stack.guid) if stack.recipe else None
    if pick is not None and pick.taker:
        return _picked(stack, pick, busy)
    if stack.guid in kept:
        return Route(stack, KEEP, why="another pass owns %s" % stack.name)
    if stack.recipe and holder is not None and can_learn_now(stack, holder):
        return Route(stack, KEEP, why="%s can learn %s now" % (holder.name, stack.name))
    if not stack.bound:
        # A recipe the register placed with nobody is not searched again.
        handed = _handed(stack, people, busy) if pick is None else None
        if handed is not None:
            return handed
        listed = _listed(stack, market, auction_open)
        if listed is not None:
            return listed
    if stack.sell_price > 0:
        return Route(
            stack,
            VENDOR,
            why="nobody who can use %s can be handed it, and a vendor pays %d "
            "copper" % (stack.name, stack.sell_price),
        )
    return Route(stack, KEEP, why="%s has no route and no vendor price" % stack.name)


def _material_route(stack, people, kept, market, auction_open, busy, vault) -> Route:
    """GUILD, BANK, AUCTION, then VENDOR for a material past its keep cap."""
    if stack.guid in kept:
        return Route(stack, KEEP, why="another pass owns %s" % stack.name)
    person, need = _first(stack, people, family=False, online=True, skip=busy)
    if person is not None:
        return Route(stack, GUILD, person.name, need)
    if stack.holder in vault:
        return Route(
            stack,
            BANK,
            why="nobody outside the family can use %s now, and the guild bank "
            "has a tab with room for it" % stack.name,
        )
    listed = _listed(stack, market, auction_open)
    if listed is not None:
        return listed
    if stack.sell_price > 0:
        return Route(
            stack,
            VENDOR,
            why="nobody can use %s, the guild bank has no room for it and the "
            "house does not pay enough; a vendor pays %d copper each"
            % (stack.name, stack.sell_price),
        )
    return Route(stack, KEEP, why="%s has no route and no vendor price" % stack.name)


def _past_target_route(
    stack, people, kept, market, auction_open, busy, over, fair, short
) -> Route:
    """GUILD to a short member, AUCTION at the live or fair price, then VENDOR,
    for a material the guild holds past its reserve target. Never the vault."""
    if stack.guid in kept:
        return Route(stack, KEEP, why="another pass owns %s" % stack.name)
    takers = [p for p in people if p.name in short and not p.family]
    person, need = _first(stack, takers, family=False, online=True, skip=busy)
    if person is not None:
        return Route(
            stack, GUILD, person.name, "%s, and its current rung is short of it" % need
        )
    price = (market or {}).get(stack.entry) or fair
    listed = _listed(stack, {stack.entry: price} if price else {}, auction_open)
    if listed is not None:
        return Route(stack, AUCTION, why="%s; %s" % (listed.why, over))
    if stack.sell_price > 0:
        return Route(
            stack,
            VENDOR,
            why="%s; nobody short of it can take it and the house does not pay "
            "enough; a vendor pays %d copper each" % (over, stack.sell_price),
        )
    return Route(stack, KEEP, why="%s has no route and no vendor price" % stack.name)


def _handed(stack: Stack, people, busy) -> Route | None:
    """FAMILY, GUILD or WAIT for the first person by name who can use it."""
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
    return None


def _listed(stack: Stack, market, auction_open: bool) -> Route | None:
    """AUCTION when the house is open and pays enough more than a vendor."""
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
    return None


def _picked(stack: Stack, pick, busy) -> Route:
    """The route for a recipe the designated-crafters register placed (#248).

    The holder keeps what the holder learns. A family taker is handed it; a
    guild taker is handed it when online, and otherwise it waits, because a
    letter needs its receiver online. A taker already handed a stack this
    pass waits for the next one.
    """
    if pick.kept:
        return Route(stack, KEEP, why=pick.why)
    if stack.bound:
        return Route(stack, KEEP, why="%s is bound to %s" % (stack.name, stack.holder))
    if pick.taker in busy:
        return Route(
            stack,
            WAIT,
            pick.taker,
            "%s; %s is already handed a stack this pass" % (pick.why, pick.taker),
        )
    if pick.seat == "family":
        return Route(stack, FAMILY, pick.taker, pick.why)
    if pick.online:
        return Route(stack, GUILD, pick.taker, pick.why)
    return Route(
        stack,
        WAIT,
        pick.taker,
        "%s; offline this pass, and a letter needs its receiver online" % pick.why,
    )


def plan(
    stacks,
    people,
    *,
    kept=frozenset(),
    market=None,
    auction_open=False,
    picks=None,
    vault=frozenset(),
    vault_room=0,
    over_target=None,
    fair=None,
    short=None,
) -> tuple:
    """Every stack's Route, holders in name order.

    A guildmate or family member is handed at most one stack per pass, the
    budget `guildshare._best_taker` keeps for the same reason: nobody reads
    their bags, and a receiver is only known to have one free slot.

    `vault_room` is tab 0's free slots: each BANK route takes one, and a
    material past the room goes on to the auction house or the vendor.
    `over_target`, `fair` and `short` are `route`'s.
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
            picks=picks,
            vault=vault if vault_room > 0 else frozenset(),
            over_target=over_target,
            fair=fair,
            short=short,
        )
        if got.route in GIVEN:
            taken.add(got.taker)
        if got.route == BANK:
            vault_room -= 1
        out.append(got)
    return tuple(out)


def counts(routes) -> dict:
    """route -> how many stacks took it, for the pass's log line."""
    out: dict = {}
    for got in routes:
        out[got.route] = out.get(got.route, 0) + 1
    return out
