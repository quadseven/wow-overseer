"""One purchase order per guild member, read from one purse (#771).

WHY THIS EXISTS. Read on the dev realm on 2026-10-10 between 14:00 and 15:10
America/New_York: the 132 members of the two family guilds off the roster owed
478 gold of class spells their trainers would sell them now (348 gold of them
spells their own AI casts) and held 36 gold between them. Only 2 of the 87 at
level 20 or above knew Apprentice Riding. Purchases ran first come, first
served: food and drink could take half the purse (restsupply.PURSE_SHARE) and
vendor gear 60% of what was left (gearup), so the class spells came last or
not at all, and nothing bought riding.

THE ORDER. What the member buys first is what it saves for first:

  1. CLASS SPELLS IT CASTS: the class spells trainable now whose names its own
     class AI casts, or that are passive (classtrain.cast_due). Bought by the
     class trainer walk (classtrain.py).
  2. RIDING: Apprentice Riding at level 20, Journeyman Riding at 40, at the
     world's riding trainer (RIDING). Bought by the riding walk
     (guildjobs.riding_step).
  3. FOOD AND DRINK (restsupply), from what is left after riding.
  4. GEAR: vendor gear for empty or weak slots (gearup), from what is left.

A purchase spends only the purse ABOVE everything ahead of it (`spendable`).
So a member holding 4 silver and owing 3 gold of spells buys no gear: it saves.

ONE EXCEPTION, AND IT IS NAMED. A member that carries nothing to eat, or
nothing to drink, buys food and drink from its whole purse as before
(`survival`): a member that cannot rest between pulls dies in them, and the
deaths cost more than the food (restsupply.py, Femur's 57 deaths in a day).

WHAT IS NOT IN THE ORDER. A mount. On this world a racial mount costs 1 gold at
level 20 with Apprentice Riding. The mount walk (guildjobs.mount_step,
mountbuy.py, #779) buys it from the purse above the class spells, the reserve
riding spends above, and uses the item (the module's `use entry:` learn row).
It is not a want here, so gear and food do not save for it.

NATURAL ONLY. Nothing here grants anything: it decides what the member's own
gold is kept for.

PURE MODULE: facts in, an order and a sentence out. No MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

SPELLS = "class spells"
RIDING = "riding"
GEAR = "gear"
FOOD = "food and drink"
ORDER = (SPELLS, RIDING, FOOD, GEAR)

RIDING_SKILL = 762


@dataclass(frozen=True)
class Rank:
    """One riding rank at the riding trainer: trainer_spell on the dev world,
    2026-10-10 (every riding trainer teaches both, for any race)."""

    spell: int
    name: str
    level: int
    cost: int
    # The skill ceiling the rank brings; a member already at it has the rank.
    ceiling: int


APPRENTICE = Rank(33388, "Apprentice Riding", 20, 40000, 75)
JOURNEYMAN = Rank(33391, "Journeyman Riding", 40, 500000, 150)
RIDING_RANKS = (APPRENTICE, JOURNEYMAN)

LOG_PREFIX = "purse:"


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def money(copper) -> str:
    """`3g 76s`, `4s 39c`, `0c`."""
    copper = max(0, _int(copper))
    gold, rest = divmod(copper, 10_000)
    silver, copper = divmod(rest, 100)
    parts = [
        "%d%s" % (n, unit)
        for n, unit in ((gold, "g"), (silver, "s"), (copper, "c"))
        if n
    ]
    return " ".join(parts[:2]) or "0c"


def riding_due(level, riding_max) -> Rank | None:
    """The riding rank the member may buy now and lacks, None when none.

    `riding_max` is the member's Riding skill ceiling (character_skills.max,
    0 when it has no Riding): 75 after Apprentice, 150 after Journeyman.
    """
    level, ceiling = _int(level), _int(riding_max)
    for rank in RIDING_RANKS:
        if level >= rank.level and ceiling < rank.ceiling:
            return rank
    return None


@dataclass(frozen=True)
class Want:
    """One line of the order: what it is, and the copper it is saved for."""

    kind: str
    copper: int
    what: str
    # The trainer spell bought, for a riding rank; 0 for the rest.
    spell: int = 0


@dataclass(frozen=True)
class Order:
    """One member's purchase order over its purse."""

    name: str
    level: int
    money: int
    wants: tuple = ()
    # The member carries nothing to eat or nothing to drink (see survival).
    hungry: bool = False

    def held_before(self, kind) -> int:
        """Copper kept for everything ahead of `kind` in ORDER."""
        if kind not in ORDER:
            return 0
        ahead = ORDER[: ORDER.index(kind)]
        return sum(w.copper for w in self.wants if w.kind in ahead)

    def spendable(self, kind) -> int:
        """Copper `kind` may spend: the purse above what is kept ahead of it."""
        if kind == FOOD and self.hungry:
            return max(0, self.money)
        return max(0, self.money - self.held_before(kind))

    def want(self, kind) -> Want | None:
        return next((w for w in self.wants if w.kind == kind), None)

    def affords(self, kind) -> bool:
        """Whether the purse covers `kind` after everything ahead of it."""
        want = self.want(kind)
        return want is not None and self.spendable(kind) >= want.copper

    def skipped(self) -> tuple:
        """The priced wants the purse cannot cover yet, in order."""
        return tuple(
            w for w in self.wants if w.copper and self.spendable(w.kind) < w.copper
        )

    @property
    def signature(self) -> tuple:
        """What the order is, without the purse: the wants, what it is short
        for and hunger. A log says the line again only when this changes."""
        return (
            tuple((w.kind, w.copper) for w in self.wants),
            tuple(w.kind for w in self.skipped()),
            self.hungry,
        )

    @property
    def line(self) -> str:
        """`purse: Bonk (25) holds 4s 39c; order: class spells 3g 76s (9 it
        casts), Apprentice Riding 4g, gear, food and drink; short for: class
        spells 3g 76s, Apprentice Riding 4g`."""
        order = ", ".join(
            ("%s %s" % (w.what, money(w.copper))) if w.copper else w.what
            for w in self.wants
        )
        skipped = self.skipped()
        tail = (
            "; short for: "
            + ", ".join("%s %s" % (w.what, money(w.copper)) for w in skipped)
            if skipped
            else "; covers every priced want"
        )
        if self.hungry:
            tail += (
                "; carries nothing to eat or drink, so food comes from the whole purse"
            )
        return "%s %s (%d) holds %s; order: %s%s" % (
            LOG_PREFIX,
            self.name,
            self.level,
            money(self.money),
            order,
            tail,
        )


def order(
    name, level, purse, spells_copper=0, spells_count=0, riding_max=0, hungry=False
) -> Order:
    """The member's purchase order.

    `spells_copper` and `spells_count` are the class spells it casts that its
    trainer would sell it now (classtrain.cast_due); `riding_max` its Riding
    ceiling; `hungry` that it carries nothing to eat or nothing to drink.
    """
    wants = []
    if _int(spells_copper) > 0:
        wants.append(
            Want(
                SPELLS,
                _int(spells_copper),
                "class spells (%d it casts)" % _int(spells_count),
            )
        )
    rank = riding_due(level, riding_max)
    if rank is not None:
        wants.append(Want(RIDING, rank.cost, rank.name, rank.spell))
    wants.append(Want(FOOD, 0, FOOD))
    wants.append(Want(GEAR, 0, GEAR))
    return Order(
        str(name), _int(level), max(0, _int(purse)), tuple(wants), bool(hungry)
    )
