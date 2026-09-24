"""Which guild raiders respec into a healing tree, and the row that does it.

WHY THIS EXISTS. A classic Molten Core raid of forty wants twelve healers
(raidlineup.HEALERS_PER_TEN). Read against the realm's own talents on
2026-09-24, both guilds placed eight: Cave had three Shadow priests, four
Retribution paladins, five Enhancement or Elemental shamans and three Feral
druids among its damage dealers, and Bonkers had one Protection paladin
outside the family. A raid leader short of healers asks the hybrids who can
heal to change trees, and starts with the ones the raid misses least.

THE ORDER A RAID LEADER ASKS IN, and the one `picks` follows:

  1. A Shadow priest, but never the guild's last one: one Shadow priest's
     Shadow Weaving and Vampiric Embrace are worth a raid slot, and a second
     is a priest who could be healing.
  2. A Retribution paladin, then a Protection paladin the lineup does not
     seat as a tank.
  3. An Enhancement shaman, then a Feral druid.
  4. An Elemental shaman, then a Balance druid.

Within one step an online raider goes before an offline one (the walk needs
the character in the world), then by name. Nobody in the family is asked:
the family's trees are the roster's decision (mod-overseer#626). Nobody the
lineup seats as a tank is asked either.

THE ROW. mod-overseer's `walk-to-trainer talents:<tree>` (kind='cast',
mod-overseer#692) walks the raider to a class trainer of its own class, buys
the reset through the same door as the family's, and spends the points with
mod-playerbots' premade build for the tree. It is judged there by the
family's own reset rules, so a raider already in the tree or short of the
price is refused rather than walked.

PURE: rows in, picks and rows out. No MySQL, no core.
"""

from __future__ import annotations

from dataclasses import dataclass

import guildcorps
import raidlineup
import raidroles

# The pass's own source prefix: "healerspec:respec:<tree>".
SOURCE = "healerspec"
ACTION = "respec"

# The healing tree of each class that has one, as its talent tab (0 to 2),
# the order talents.json and the DBC give the trees in.
HEALING_TAB = {
    raidlineup.PALADIN: 0,  # Holy
    raidlineup.PRIEST: 1,  # Holy
    raidlineup.SHAMAN: 2,  # Restoration
    raidlineup.DRUID: 2,  # Restoration
}
HEALING_TREE = {
    raidlineup.PALADIN: "Holy",
    raidlineup.PRIEST: "Holy",
    raidlineup.SHAMAN: "Restoration",
    raidlineup.DRUID: "Restoration",
}

# The steps above, as (class, tree) -> rank. A tree not listed is not asked.
_ORDER = {
    (raidlineup.PRIEST, "Shadow"): 0,
    (raidlineup.PALADIN, "Retribution"): 1,
    (raidlineup.PALADIN, "Protection"): 2,
    (raidlineup.SHAMAN, "Enhancement"): 3,
    (raidlineup.DRUID, "Feral Combat"): 4,
    (raidlineup.SHAMAN, "Elemental"): 5,
    (raidlineup.DRUID, "Balance"): 6,
}

# A raider must be at the raid's level to be worth a respec.
RAID_LEVEL = 60

# How long after a respec row for a raider the pass leaves that raider alone.
# The walk is followed for up to its far ceiling (half an hour) by the corps
# runner; three hours covers a walk a fight ended and was walked again, and
# stops a refused raider (offline, no trainer on its map) being asked every
# pass.
RETRY_MINUTES = 180

# At most this many respec walks start per guild per pass. The realm allows
# four far walks at once (mod-overseer's FAR_WALKS_AT_ONCE), and the corps and
# the raid supply walk too.
PER_PASS = 2

# The seats a raider keeps its tree for.
_TANK_DUTIES = frozenset({raidlineup.MAIN_TANK, raidlineup.OFF_TANK})


@dataclass(frozen=True)
class Pick:
    """One raider asked to respec into its class's healing tree."""

    name: str
    guild: str
    class_id: int
    tree: str  # the tree it plays now
    tab: int  # the healing tree's talent tab
    online: bool

    @property
    def healing_tree(self) -> str:
        return HEALING_TREE.get(self.class_id, "")

    def said(self) -> str:
        return "%s (%s %s) respecs to %s for the %s raid's healers" % (
            self.name,
            self.tree,
            raidlineup.CLASS_NAMES.get(self.class_id, "hybrid"),
            self.healing_tree,
            self.guild,
        )


def source(tab: int) -> str:
    return "%s:%s:%d" % (SOURCE, ACTION, int(tab))


def command(tab: int, cap: float) -> str:
    """The module's row: walk to a class trainer and respec into `tab`."""
    return "walk-to-trainer talents:%d max:%d" % (int(tab), int(cap))


def lineups_from_rows(rows, family_names) -> dict:
    """guild -> raidlineup.build_lineup over that guild's members.

    `rows` carry guild_name, name, class_id, level and talent_spells
    (raidroles.TALENTS_COLUMN), one per member of every guild the family is
    in: the corps' own member read. The family is guaranteed its places, as on
    the Lineup page.
    """
    family = frozenset(str(n) for n in family_names or ())
    by_guild: dict = {}
    for row in rows or ():
        guild = str(row.get("guild_name") or "")
        name = str(row.get("name") or "")
        if guild and name:
            by_guild.setdefault(guild, []).append(row)
    out = {}
    for guild, members in sorted(by_guild.items()):
        out[guild] = raidlineup.build_lineup(
            [
                {
                    "name": str(r.get("name")),
                    "class_id": r.get("class_id"),
                    "level": r.get("level"),
                    raidroles.KEY: r.get(raidroles.KEY),
                }
                for r in members
            ],
            guaranteed=[
                str(r.get("name")) for r in members if str(r.get("name")) in family
            ],
        )
    return out


def _everyone(lineup: dict) -> list:
    """Every member the lineup read, placed or not, with its seat's duty."""
    out = []
    for group in lineup.get("groups") or ():
        out.extend(group.get("members") or ())
    for key in ("maintenance", "summoners", "surplus"):
        out.extend(lineup.get(key) or ())
    return out


def choose(guild: str, lineup: dict, family_names, online=frozenset()):
    """(chosen, notes): the raiders the guild's healer shortfall asks, in order.

    `lineup` is raidlineup.build_lineup's answer for the guild, and `online`
    holds the names of members in the world. At most the shortfall is chosen;
    a note says when the guild's hybrids cannot cover it.
    """
    family = frozenset(str(n) for n in family_names or ())
    online = frozenset(online or ())
    short = int((lineup.get("shortfall") or {}).get("healers") or 0)
    notes = []
    if short <= 0:
        return [], notes
    members = _everyone(lineup)
    shadow_left = len(
        [
            m
            for m in members
            if m.get("class_id") == raidlineup.PRIEST and m.get("spec") == "Shadow"
        ]
    )
    candidates = []
    for member in members:
        name = str(member.get("name") or "")
        class_id = member.get("class_id")
        tree = str(member.get("spec") or "")
        rank = _ORDER.get((class_id, tree))
        if rank is None or name in family:
            continue
        if int(member.get("level") or 0) < RAID_LEVEL:
            continue
        if member.get("duty") in _TANK_DUTIES:
            continue
        candidates.append((rank, name not in online, name, member))
    candidates.sort(key=lambda c: c[:3])

    chosen = []
    for _rank, _offline, name, member in candidates:
        if len(chosen) >= short:
            break
        tree = str(member.get("spec") or "")
        if tree == "Shadow":
            if shadow_left <= 1:
                notes.append(
                    "%s stays Shadow: the guild keeps one Shadow priest" % name
                )
                continue
            shadow_left -= 1
        class_id = int(member.get("class_id"))
        chosen.append(
            Pick(
                name=name,
                guild=guild,
                class_id=class_id,
                tree=tree,
                tab=HEALING_TAB[class_id],
                online=name in online,
            )
        )
    left = short - len(chosen)
    if left > 0:
        notes.append(
            "%s is %d healer(s) short after these respecs, and no other raider outside "
            "the family can heal: that is a recruit, not a respec" % (guild, left)
        )
    return chosen, notes


def picks(
    guild: str,
    lineup: dict,
    family_names,
    online=frozenset(),
    recent=None,
    busy=frozenset(),
):
    """(picks, notes): the chosen raiders whose walk may start this pass.

    `recent` is guildcorps.recent_from_rows over this pass's own rows (prefix
    SOURCE): a raider with a respec row younger than RETRY_MINUTES is left
    alone. `busy` holds raiders another guild pass has a step running for. A
    raider not in the world waits for the next pass. At most PER_PASS start.
    """
    chosen, notes = choose(guild, lineup, family_names, online)
    recent = recent or {}
    ready = []
    for pick in chosen:
        age = recent.get((pick.name, ACTION, pick.tab))
        if age is not None and age < RETRY_MINUTES:
            notes.append(
                "%s was asked %d minute(s) ago and is left alone for %d"
                % (pick.name, age, RETRY_MINUTES)
            )
        elif pick.name in busy:
            notes.append("%s is on another guild errand" % pick.name)
        elif not pick.online:
            notes.append("%s is not in the world" % pick.name)
        else:
            ready.append(pick)
    return ready[:PER_PASS], notes


def step(pick: Pick, cap: float):
    """The corps runner's step for one pick: one walk row, followed to its end."""
    row = guildcorps.Row(
        kind="cast", command=command(pick.tab, cap), source=source(pick.tab)
    )
    return guildcorps.Step(
        holder=pick.name,
        action=ACTION,
        key=pick.tab,
        said=pick.said(),
        rows=(row,),
    )
