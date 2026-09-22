"""How high the auction house may reach for a roster at these levels (infra).

Pure module, same seam as materials.py and professions.py: facts in, a decision
out. Nothing here opens a socket or reads the world database. It lives in
tools/ rather than at the top level because the bridge never imports it and
the top level is what gets packed into the build's shared tarball, which is
measured against a ConfigMap size budget (infra#3139). What it decides is
the two ceilings in
production/oke/manifests/wow-dev/config/ahbot.overrides.conf, and
tests/test_ahbot_ceiling.py asserts that file agrees with this one, so the
numbers cannot be edited there in isolation.

WHY THIS IS A MODULE AND NOT TWO NUMBERS IN A CONF FILE. Two numbers in a conf
file are a snapshot of a roster that levels. The roster is what moves: the
ceiling that is right at level 29 is wrong at level 40 and nothing would say so,
because an auction house that has quietly stopped stocking anything useful looks
exactly like one that is working. Keeping the derivation here means the input is
the roster's top level, the output is the conf, and `drift()` can answer "is the
deployed ceiling still the right one" from the levels alone.

WHAT WAS WRONG, WHICH IS WHAT THE SHAPE OF THIS IS ANSWERING. Measured on the
dev realm: 14988 live auction listings, all owned by the seller bot, and among
them Netherweave Bag - item 21841, ITEM LEVEL 63, a Burning Crusade container
woven from Outland cloth - being sold to a party questing at levels 23 to 29.
Three of the five were carrying two each. The house was cheaper than the
profession, so the profession had no point.

THE ONE NON-OBVIOUS FACT, and the reason `would_list()` exists rather than a
comment. mod-ah-bot-plus has TWO independent ceilings, and they are not
symmetrical about zero. Read at the SHA this realm pins (AC_AH_BOT_SHA in
production/docker/azerothcore-playerbots/UPSTREAM-PINS.env),
src/AuctionHouseBot.cpp, PopulateItemCandidatesAndProportions():

    if (useOrEquipLevelCompare > 0 && useOrEquipLevelCompare > ...MaxLevel)

The required-level filter SKIPS every item whose RequiredLevel is zero, which is
every container, every trade good and most consumables. The item-level filter
carries no such guard. So a required-level ceiling alone would have let the
Netherweave Bag straight through while looking like it was working, and an
item-level floor above zero would delete the entire zero-item-level tail of the
item table. Both facts are encoded below and pinned by tests, because both are
the kind of thing that reads as a detail and behaves as an outage.

WHAT THIS DOES NOT DECIDE. Whether an item is worth buying, what it should cost,
or what the family already owns. It answers only "would the bot be allowed to
list this", and it answers it the way the C++ does.
"""

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence, Tuple

# ---------------------------------------------------------------------------
# MEASURED INPUT. The roster's level span on the dev realm, 2026-09-05: five
# characters questing together in a starting zone. Only the TOP of the span is
# an input to anything - the ceiling has to serve the character most likely to
# outgrow it - but the bottom is recorded because it is what makes the answer
# "restrict to their levels" a narrow band rather than a wide one.
ROSTER_LEVELS_MEASURED: Tuple[int, int] = (23, 29)
ROSTER_MEASURED_ON = "2026-09-05"

# FIVE LEVELS OF HEADROOM. A ceiling set at exactly the top character's level is
# wrong the moment anybody dings, and it also removes the reason to shop: gear
# you can only just equip is gear you are about to replace. Five is about two
# evenings of questing at this level, so the house always has something to grow
# into and never has anything from another expansion.
HEADROOM_LEVELS = 5

# ITEM LEVEL RUNS AHEAD OF REQUIRED LEVEL, and the item-level ceiling has to
# clear that gap or it silently re-filters gear the required-level ceiling has
# already allowed. Measured against this realm's own item table: Twisted Sabre
# (item 2011) is item level 26 at required level 21, and the +5 relationship
# holds broadly for world-drop gear in this band.
OBSERVED_GEAR_OFFSET = 5

# The margin actually applied, which is the offset plus slack. Slack matters
# because the offset is a tendency, not a rule, and the cost of being a little
# generous here is one or two items a few levels above the band, while the cost
# of being tight is gear vanishing for no visible reason.
ITEM_LEVEL_MARGIN = 10

# THE FLOORS. Both stay at zero and neither is an oversight - see the module
# docstring. Raising MIN_ITEM_LEVEL above zero would drop every item whose
# ItemLevel is 0, which is a large part of the quest, key and miscellaneous
# tables, and there is nothing to gain: a low-level party has no reason to be
# protected from cheap goods.
MIN_ITEM_LEVEL = 0
MIN_REQUIRED_LEVEL = 0

# HOW BIG THE MARKET IS. Per auction house; the module lists into three
# (Alliance, Horde, Neutral), so the realm total is three times this.
#
# 750 rather than the 5000 this realm ran before, and the ceiling above is what
# pays for the cut. 15000 listings drawn from the whole item table was depth
# used as a substitute for relevance: it took that many to contain a few hundred
# a character in the twenties could use. With the ceiling doing that job
# directly, an equally useful market is roughly an order of magnitude smaller -
# and a market that small is one where the family's own handful of listings is
# findable by a person browsing it, instead of one row in fifteen thousand.
LISTINGS_PER_HOUSE = 750
AUCTION_HOUSE_COUNT = 3


@dataclass(frozen=True)
class Ceilings:
    """What the seller bot is allowed to reach for."""

    max_required_level: int
    max_item_level: int
    listings_per_house: int

    @property
    def total_listings(self) -> int:
        return self.listings_per_house * AUCTION_HOUSE_COUNT


def top_level(levels: Iterable[int]) -> int:
    """The character the ceiling has to serve.

    Raises on an empty roster rather than inventing a level: a ceiling derived
    from no characters is a number nobody chose.
    """
    ordered = sorted(levels)
    if not ordered:
        raise ValueError("no roster levels given, so there is no ceiling to derive")
    return ordered[-1]


def ceilings(
    roster_top_level: int,
    headroom: int = HEADROOM_LEVELS,
    margin: int = ITEM_LEVEL_MARGIN,
    listings_per_house: int = LISTINGS_PER_HOUSE,
) -> Ceilings:
    """Both ceilings, from the one input that moves."""
    if roster_top_level < 1:
        raise ValueError("a roster top level below 1 is not a level")
    if margin < OBSERVED_GEAR_OFFSET:
        raise ValueError(
            "an item level margin below the observed gear offset would strip "
            "gear the required level ceiling already allows"
        )
    max_required = roster_top_level + headroom
    return Ceilings(
        max_required_level=max_required,
        max_item_level=max_required + margin,
        listings_per_house=listings_per_house,
    )


def would_list(item_level: int, required_level: int, limits: Ceilings) -> bool:
    """Would the seller bot be allowed to list this item.

    Mirrors PopulateItemCandidatesAndProportions() at the pinned SHA, in its
    order and with its asymmetry: the item level test has no zero guard, the
    required level test has one on both comparisons. Exception lists are
    deliberately not modelled - this realm keeps both of them empty, and a
    model of a list that is empty is a model of nothing.
    """
    if item_level < MIN_ITEM_LEVEL:
        return False
    if item_level > limits.max_item_level:
        return False
    if required_level > 0 and required_level < MIN_REQUIRED_LEVEL:
        return False
    if required_level > 0 and required_level > limits.max_required_level:
        return False
    return True


def overrides(limits: Ceilings) -> Tuple[Tuple[str, str], ...]:
    """The conf keys this decision owns, as they must appear in the overrides.

    EVERY KEY HERE EXISTS IN mod_ahbot.conf.dist AT THE PINNED SHA. That is not
    a style note: the seeder in production/oke/manifests/wow-dev/ahbot.yaml
    refuses to start the worldserver on a key the dist does not declare, because
    AzerothCore's parser accepts an unknown key silently and never reads it. A
    key invented here is a realm that will not boot, which is the good outcome;
    the bad one is the parser's.
    """
    return (
        ("AuctionHouseBot.Alliance.MinItems", str(limits.listings_per_house)),
        ("AuctionHouseBot.Alliance.MaxItems", str(limits.listings_per_house)),
        ("AuctionHouseBot.Horde.MinItems", str(limits.listings_per_house)),
        ("AuctionHouseBot.Horde.MaxItems", str(limits.listings_per_house)),
        ("AuctionHouseBot.Neutral.MinItems", str(limits.listings_per_house)),
        ("AuctionHouseBot.Neutral.MaxItems", str(limits.listings_per_house)),
        ("AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.Enabled", "true"),
        (
            "AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MinLevel",
            str(MIN_REQUIRED_LEVEL),
        ),
        (
            "AuctionHouseBot.EquipItemUseOrEquipLevelRestrict.MaxLevel",
            str(limits.max_required_level),
        ),
        ("AuctionHouseBot.ListedItemLevelRestrict.Enabled", "true"),
        (
            "AuctionHouseBot.ListedItemLevelRestrict.UseCraftedItemForCalculation",
            "true",
        ),
        ("AuctionHouseBot.ListedItemLevelRestrict.MinItemLevel", str(MIN_ITEM_LEVEL)),
        (
            "AuctionHouseBot.ListedItemLevelRestrict.MaxItemLevel",
            str(limits.max_item_level),
        ),
    )


def parse_conf(text: str) -> "dict[str, str]":
    r"""The `AuctionHouseBot.*` settings an overrides file actually sets.

    Only lines that START with the prefix count, which is exactly what the
    seeder's own `grep -oE '^AuctionHouseBot\.[A-Za-z0-9_.]+'` sees. A commented
    out key is not a setting, here or there.
    """
    settings = {}
    for line in text.splitlines():
        if not line.startswith("AuctionHouseBot.") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip()
    return settings


def drift(
    conf_text: str,
    levels: Sequence[int],
    settings: "Mapping[str, str] | None" = None,
) -> Tuple[str, ...]:
    """Why the deployed ceiling is no longer the one this roster needs.

    Empty means the conf and the roster agree. Each string names one key and
    both values, because "the ceiling is stale" is not actionable and "MaxLevel
    is 34, the roster wants 45" is.
    """
    actual = dict(parse_conf(conf_text)) if settings is None else dict(settings)
    wanted = overrides(ceilings(top_level(levels)))
    reasons = []
    for key, value in wanted:
        if key not in actual:
            reasons.append(
                "{} is not set at all, so the dist default stands".format(key)
            )
        elif actual[key] != value:
            reasons.append(
                "{} is {}, this roster wants {}".format(key, actual[key], value)
            )
    return tuple(reasons)


def _main(argv: "Sequence[str] | None" = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Print the auction house bot override lines for a roster, so the "
            "conf can be updated from the levels rather than by hand."
        )
    )
    parser.add_argument(
        "--levels",
        default=",".join(str(n) for n in ROSTER_LEVELS_MEASURED),
        help=(
            "comma separated character levels (default: the span measured on "
            + ROSTER_MEASURED_ON
            + ")"
        ),
    )
    args = parser.parse_args(argv)
    levels = [int(n) for n in args.levels.split(",") if n.strip()]
    limits = ceilings(top_level(levels))
    for key, value in overrides(limits):
        print("{} = {}".format(key, value))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
