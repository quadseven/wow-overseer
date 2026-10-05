"""PvP for upgrades: a member whose next upgrade is PvP gear earns it (#589).

THE DECISION (#530, binding). PvP is for gear. A member whose next upgrade by
the gear scorer is a PvP item queues battlegrounds with anyone of its faction,
grinds honor until it can pay, and buys the item at the vendor. Mostly at 60;
below 60 only for a strong upgrade. On this 3.3.5 server every level 60 PvP
reward is sold for honor alone, with no rank and no reputation gate (#520).

THE NEXT UPGRADE (`next_upgrade`). gearscore's own order: the pre-raid list
first, then the raid list once nothing pre-raid beats what is worn. The PvP
stock the member's side can buy competes in the pre-raid round, because it is
bought now, not raided for. Every candidate is scored by guildsocial.drop_gain,
which is gearscore's score gated by recap.verdict (class, proficiency, armor
grade, required level) and asks for MIN_GAIN_SHARE over the worn piece. Across
slots the largest gain is the next upgrade. When that item is a PvP item the
member's activity becomes "PvP for <item>".

STRONG ENOUGH (`wants`). At LEVEL_CAP any such upgrade counts. Below it the
member must gain at least STRONG_BELOW_CAP of the worn piece's score (an empty
slot always does), because a member still levelling outgrows a blue in a few
levels and its time is better spent levelling.

WHICH BATTLEGROUND (`battleground_for`). The vendor names the currency. A
battleground's own supply officer (Stormpike or Frostwolf, Silverwing or
Warsong, Arathor or Defilers) sells for honor, and the member earns it in that
battleground, the way a player grinds its reputation there. A legacy rank
quartermaster takes honor from any battleground: the member follows a
guildmate already queued for one this pass, so they go in together, else the
first of HONOR_ORDER its level fits. Brackets are this realm's own (#520):
Alterac Valley 51-60, Warsong Gulch from 10, Arathi Basin from 20.

WHAT IT DOES NEXT (`next_move`):
  inside    standing in a battleground (the snapshot's map): it plays; nothing
            else is asked of it.
  carried   the bought item sits in its bags; the module's equip drive wears
            it, so nothing is bought or queued again.
  buy       its honor covers the price: walk to the vendor that stocks the
            item and buy it with an `honor:` ceiling at the price.
  waiting   it queued less than QUEUE_MINUTES ago and the row did not fail:
            it waits in the queue, the way a player waits for the call.
  queue     otherwise: `bg-queue <key>` (quadseven/mod-overseer, kind
            'guild'). A member that leads a group queues the group.

GUILD CHAT (`chat_lines`). A member starting a PvP session (no PvP row for
CHAT_QUIET_MINUTES) says so in guild chat through the social layer's path
("Queueing AV for honor, anyone?"); a guildmate starting one for the same
battleground in the same pass answers that it is in. A member off to buy says
so once. Nothing here assigns anybody: each member queues for its own item.

PURE: rows in, decisions out. The bridge reads the rows and writes the steps.
"""

from __future__ import annotations

import math
import os
import zlib
from dataclasses import dataclass

import gearscore
import guildrun
import guildsocial

ENV_SWITCH = "PVP_FOR_UPGRADES"
LEVEL_CAP = 60
# Below the cap, a PvP upgrade must add this share of the worn piece's score.
STRONG_BELOW_CAP = 0.3
# A queue row younger than this, that did not fail, is a member still waiting
# for its battleground; it is not queued again and given no other job.
QUEUE_MINUTES = 15
# A member with no PvP row this long starts a new session, and says so.
CHAT_QUIET_MINUTES = 60
ACTION = "pvp"


@dataclass(frozen=True)
class Battleground:
    key: str
    name: str
    short: str
    map_id: int
    min_level: int


AV = Battleground("av", "Alterac Valley", "AV", 30, 51)
WSG = Battleground("wsg", "Warsong Gulch", "WSG", 489, 10)
AB = Battleground("ab", "Arathi Basin", "AB", 529, 20)
BATTLEGROUNDS = {bg.key: bg for bg in (AV, WSG, AB)}
BATTLEGROUND_MAPS = frozenset(bg.map_id for bg in BATTLEGROUNDS.values())
# Where honor comes from when any battleground pays it: Alterac Valley first,
# forty a side with the most bonus honor a win, then Arathi Basin, then
# Warsong Gulch, whose flag games run longest.
HONOR_ORDER = ("av", "ab", "wsg")

ALLIANCE, HORDE = "Alliance", "Horde"
# The PvP vendors of the 3.3.5 world data (#520): npc -> (the battleground
# whose supply officer it is, or "" for a legacy rank quartermaster, side).
PVP_VENDORS = {
    13216: ("av", ALLIANCE),
    13217: ("av", ALLIANCE),
    13218: ("av", HORDE),
    13219: ("av", HORDE),
    14753: ("wsg", ALLIANCE),
    14754: ("wsg", HORDE),
    15127: ("ab", ALLIANCE),
    15126: ("ab", HORDE),
    12781: ("", ALLIANCE),
    12784: ("", ALLIANCE),
    12785: ("", ALLIANCE),
    12805: ("", ALLIANCE),
    12793: ("", HORDE),
    12794: ("", HORDE),
    12795: ("", HORDE),
    12799: ("", HORDE),
}

# The PvP stock: every weapon and armor line the vendors above sell through
# an ExtendedCost, with the columns guildsocial.drop_gain reads.
STOCK_SQL = (
    # S608: _ITEM_COLUMNS is a constant column list; every value is bound.
    "SELECT nv.entry AS vendor, nv.ExtendedCost AS extended_cost, "  # noqa: S608
    "it.entry AS Item, " + guildsocial._ITEM_COLUMNS + " "
    "FROM acore_world.npc_vendor nv "
    "JOIN acore_world.item_template it ON it.entry = nv.item "
    "WHERE nv.entry IN ({holes}) AND nv.ExtendedCost > 0 AND it.class IN (2, 4) "
    "AND it.RequiredLevel <= %s"
)


def enabled(environ=None) -> bool:
    """On only when PVP_FOR_UPGRADES says so: members queue nothing until the
    realm's playerbots run level 60 battlegrounds (see the pull request)."""
    env = os.environ if environ is None else environ
    return str(env.get(ENV_SWITCH, "")).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Offer:
    """One PvP item a vendor sells for honor alone."""

    entry: int
    vendor: int
    honor: int
    row: dict

    @property
    def battleground(self) -> str:
        return PVP_VENDORS.get(self.vendor, ("", ""))[0]

    @property
    def side(self) -> str:
        return PVP_VENDORS.get(self.vendor, ("", ""))[1]

    @property
    def name(self) -> str:
        return str(self.row.get("item_name") or "item %d" % self.entry)

    @property
    def required_level(self) -> int:
        return int(self.row.get("required_level") or 0)


def offers_from_rows(rows, costs: dict) -> list:
    """Offers from STOCK_SQL rows. `costs` is itemsource.load_costs: a line
    whose cost asks for arena points or a token, or no honor, is left out."""
    out = []
    for row in rows or ():
        try:
            vendor = int(row["vendor"])
            entry = int(row["Item"])
            cost = costs.get(int(row["extended_cost"])) or {}
        except (KeyError, TypeError, ValueError):
            continue
        if vendor not in PVP_VENDORS:
            continue
        honor = int(cost.get("honor") or 0)
        if honor <= 0 or cost.get("arena") or cost.get("items"):
            continue
        out.append(Offer(entry, vendor, honor, dict(row)))
    return out


def offers_for(side: str, offers) -> list:
    """The offers a member of `side` can buy: its own side's vendors."""
    return [o for o in offers if o.side == side]


def list_ids(spec: str, phase: str) -> frozenset:
    """Every item id one of the spec's lists names (gearscore.PREFER_PHASES)."""
    lists = gearscore.load_spec(spec)["lists"].get(phase, {}).get("slots", {})
    return frozenset(int(i) for entries in lists.values() for i in entries)


@dataclass(frozen=True)
class Upgrade:
    """The member's next upgrade: the item, what it adds, and its share of the
    worn piece's score (math.inf over an empty slot)."""

    entry: int
    name: str
    gain: float
    share: float
    offer: Offer | None = None

    @property
    def pvp(self) -> bool:
        return self.offer is not None


def _best(candidates, gear: dict, spec: str, level: int, offers: dict):
    best = None
    for row in candidates:
        gain, index = guildsocial.drop_gain(row, gear, spec, level)
        if index is None or gain <= 0:
            continue
        entry = int(row.get("Item") or row.get("entry") or 0)
        new = gearscore.score(
            gearscore.stats_from_row(row),
            spec,
            level,
            guildsocial._WEAPON_SLOT.get(int(row.get("inventory_type") or 0), ""),
        )
        old = new - gain
        share = gain / old if old > 0 else math.inf
        name = str(row.get("item_name") or "item %d" % entry)
        found = Upgrade(entry, name, round(gain, 1), share, offers.get(entry))
        key = (found.gain, found.pvp, -entry)
        if best is None or key > best[0]:
            best = (key, found)
    return best[1] if best else None


def next_upgrade(
    gear: dict, spec: str, level: int, list_rows: dict, offers
) -> Upgrade | None:
    """The member's next upgrade, by gearscore, or None when nothing beats
    what it wears.

    `gear` is recap's member dict (guildsocial.gear_by_name), `list_rows`
    item id -> item_template row (guildsocial's columns, `Item` or `entry` the
    id) for every id the spec's lists name, `offers` the Offers its side can
    buy. The pre-raid list and the PvP stock first, then the raid list.
    """
    by_entry = {o.entry: o for o in offers or ()}
    stock = {o.entry: o.row for o in offers or ()}
    for phase in gearscore.PREFER_PHASES:
        ids = list_ids(spec, phase)
        pool = {i: r for i, r in list_rows.items() if int(i) in ids}
        if phase == gearscore.PREFER_PHASES[0]:
            pool.update(stock)
        found = _best(pool.values(), gear, spec, level, by_entry)
        if found is not None:
            return found
    return None


def wants(level: int, upgrade: Upgrade | None) -> bool:
    """Whether this upgrade sends the member to PvP: a PvP item, and at the
    cap any gain, below it at least STRONG_BELOW_CAP, and a battleground its
    level may enter."""
    if upgrade is None or not upgrade.pvp:
        return False
    if battleground_for(upgrade.offer, level) is None:
        return False
    return int(level) >= LEVEL_CAP or upgrade.share >= STRONG_BELOW_CAP


def battleground_for(offer: Offer, level: int, follow: str = "") -> Battleground | None:
    """The battleground that earns this offer's honor at this level: its own
    supply officer's battleground, else `follow` (a guildmate's), else the
    first of HONOR_ORDER the level fits."""
    if offer.battleground:
        bg = BATTLEGROUNDS[offer.battleground]
        return bg if int(level) >= bg.min_level else None
    for key in ((follow,) if follow else ()) + HONOR_ORDER:
        bg = BATTLEGROUNDS.get(key)
        if bg is not None and int(level) >= bg.min_level:
            return bg
    return None


@dataclass(frozen=True)
class Aim:
    """A member playing PvP for one item."""

    name: str
    guild: str
    level: int
    entry: int
    item: str
    honor: int
    held: int
    battleground: Battleground

    @property
    def short(self) -> int:
        return max(0, self.honor - self.held)

    @property
    def line(self) -> str:
        return "PvP for %s: %s for honor, %d of %d" % (
            self.item,
            self.battleground.short,
            min(self.held, self.honor),
            self.honor,
        )


@dataclass(frozen=True)
class Seeker:
    """One member's facts for `plan_aims`."""

    name: str
    guild: str
    level: int
    honor: int
    upgrade: Upgrade | None


def plan_aims(seekers) -> dict:
    """name -> Aim for every member `wants` sends to PvP.

    A member whose honor any battleground pays follows the battleground a
    guildmate before it chose, so members of one guild queue together. The
    order is by guild, the member closest to its item first, then name.
    """
    out = {}
    chosen: dict = {}
    wanting = [s for s in seekers or () if wants(s.level, s.upgrade)]
    wanting.sort(key=lambda s: (s.guild, s.upgrade.offer.honor - s.honor, s.name))
    for s in wanting:
        offer = s.upgrade.offer
        bg = battleground_for(offer, s.level, chosen.get(s.guild, ""))
        if bg is None:
            continue
        chosen.setdefault(s.guild, bg.key)
        out[s.name] = Aim(
            s.name, s.guild, s.level, offer.entry, offer.name, offer.honor,
            int(s.honor), bg,
        )  # fmt: skip
    return out


INSIDE, CARRIED, BUY, WAITING, QUEUE = "inside", "carried", "buy", "waiting", "queue"
FAILED = frozenset({"error", "unchanged"})


@dataclass(frozen=True)
class Move:
    kind: str
    said: str


def _pvp_rows(name: str, recent):
    return [r for r in recent or () if r.name == name and r.action == ACTION]


def last_pvp_age(name: str, recent) -> int | None:
    """Minutes since this member's newest PvP row, None when it has none."""
    rows = _pvp_rows(name, recent)
    return min(int(r.age_minutes) for r in rows) if rows else None


def next_move(aim: Aim, map_id, carried: bool, recent) -> Move:
    """What the member does about its aim this pass (see the module notes).
    `recent` is guildjobs.Recent rows."""
    bg = aim.battleground
    if map_id is not None and int(map_id) in BATTLEGROUND_MAPS:
        return Move(
            INSIDE, "%s plays a battleground for honor toward %s" % (aim.name, aim.item)
        )
    if carried:
        return Move(CARRIED, "%s carries %s and puts it on" % (aim.name, aim.item))
    if aim.held >= aim.honor:
        return Move(
            BUY,
            "%s has the %d honor for %s and walks to the vendor"
            % (aim.name, aim.honor, aim.item),
        )
    rows = _pvp_rows(aim.name, recent)
    if rows:
        newest = min(rows, key=lambda r: int(r.age_minutes))
        if int(newest.age_minutes) < QUEUE_MINUTES and newest.status not in FAILED:
            return Move(
                WAITING,
                "%s waits in the %s queue, %d honor short of %s"
                % (aim.name, bg.name, aim.short, aim.item),
            )
    return Move(
        QUEUE,
        "%s queues %s for honor toward %s (%d of %d)"
        % (aim.name, bg.name, aim.item, min(aim.held, aim.honor), aim.honor),
    )


def queue_command(aim: Aim) -> str:
    return "bg-queue %s" % aim.battleground.key


def buy_command(aim: Aim) -> str:
    """The kind='buy' row: one piece, capped at its honor price."""
    return "entry:%d count:1 honor:%d" % (int(aim.entry), int(aim.honor))


_ASK = (
    "Queueing {bg} for honor, anyone? Saving up for {item}.",
    "Anyone up for {bg}? Grinding honor for {item}.",
    "Heading into {bg} for honor, come along if you need gear.",
)
_JOIN = (
    "I'm in, queueing {bg} too. Need honor for {item}.",
    "Same here, {bg} it is. Still short on honor for {item}.",
    "Count me in for {bg}, I'm after {item}.",
)
_BOUGHT = (
    "Finally have the honor for {item}, off to the quartermaster.",
    "Enough honor for {item} at last. Buying it now.",
)


def _pick(options: tuple, *keys) -> str:
    seed = zlib.crc32("|".join(str(k) for k in keys).encode("utf-8"))
    return options[seed % len(options)]


def chat_lines(moves: dict, aims: dict, recent) -> list:
    """[(speaker, line)] for guild chat this pass.

    `moves` name -> Move, `aims` name -> Aim. A queuing member starting a
    session (no PvP row for CHAT_QUIET_MINUTES) asks; the next ones of its
    guild for the same battleground in this pass answer that they are in. A
    member off to buy says so as it sets out.
    """
    out = []
    asked: set = set()
    for name in sorted(moves):
        move, aim = moves[name], aims.get(name)
        if aim is None:
            continue
        age = last_pvp_age(name, recent)
        fresh = age is None or age >= CHAT_QUIET_MINUTES
        bg = aim.battleground
        if move.kind == BUY:
            out.append((name, _pick(_BOUGHT, name, aim.entry).format(item=aim.item)))
        elif move.kind == QUEUE and fresh:
            key = (aim.guild, bg.key)
            options = _JOIN if key in asked else _ASK
            asked.add(key)
            out.append(
                (
                    name,
                    _pick(options, name, aim.entry).format(bg=bg.short, item=aim.item),
                )
            )
    return out


# --- from the bridge's rows -------------------------------------------------


def specs_list_ids(specs) -> list:
    """Every item id the given specs' pre-raid and raid lists name, sorted."""
    ids: set = set()
    for spec in {s for s in specs if s}:
        for phase in gearscore.PREFER_PHASES:
            ids |= list_ids(spec, phase)
    return sorted(ids)


def spec_of_row(row: dict) -> str | None:
    """The gear spec of one member row (name, level, class_id, talent_spells)."""
    member = guildrun.member_from_row(row)
    return guildsocial.spec_of(member) if member is not None else None


def seekers_from_rows(member_rows, gear_by_name: dict, list_rows: dict, offers) -> list:
    """A Seeker per member row whose level could use any offer.

    `member_rows` carry name, guild_name, level, class_id, race, honor and
    talent_spells; `gear_by_name` is guildsocial.gear_by_name over them;
    `list_rows` item id -> item_template row for every list id their specs
    name; `offers` every Offer, both sides (each member sees its own side's).
    """
    floor = min((o.required_level for o in offers or ()), default=LEVEL_CAP + 1)
    out = []
    for row in member_rows or ():
        member = guildrun.member_from_row(row)
        if member is None or member.level < floor:
            continue
        gear = gear_by_name.get(member.name)
        spec = guildsocial.spec_of(member)
        if not gear or not spec:
            continue
        mine = offers_for(guildrun.faction_of([member]), offers)
        upgrade = next_upgrade(gear, spec, member.level, list_rows, mine)
        honor = int(row.get("honor") or 0)
        out.append(Seeker(member.name, member.guild, member.level, honor, upgrade))
    return out
