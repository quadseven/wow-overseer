"""The guild bankers' own loop (#2660, slice 4): where a banker stands and what
it may sell.

A banker is a guild member in a seat of its own (`raidteams.BANKERS`). It never
raids, levels, quests, gathers or joins a group. It stays in its guild's vault
city and does only a few steps there, each through a verb that already exists:

  * HOME: a banker away from the vault city walks back to the guild vault, or
    hearths when it is on another continent. It is not left to the random-bot
    AI, which wanders.
  * MAIL: it opens its post (the same takes the guild members' collect step
    writes), which is how what members send reaches it.
  * BANK: when its bags run short it deposits what the item plan banks into its
    own personal bank (the seat loop's deposit).
  * VENDOR: it sells true junk only, grey stacks. Never a white, never a
    destroy.

Bankers sit in none of the lineup's groups (slice 2), so the bridge gives them
this role by name. The steps are built in guildjobs (`_banker_step`), which owns
the rows; this module holds the facts that need no step: the city, the reach
and the junk rule.

Not in this slice: vault deposit and withdraw moves, the trade hand-over, a
send to a member, and auction listings. Each is its own step kind on the same
loop and lands on top of it.

PURE: members in, members out. No database, no clock.
"""

from __future__ import annotations

import math
from dataclasses import replace

BANKER = "banker"

# The zone id of each guild's vault city: Ironforge for Cave, Thunder Bluff for
# Bonkers (the two cities the issue's table sends them to).
VAULT_CITY_ZONE = {"Cave": 1537, "Bonkers": 1638}
# The vault city's map, for the hearth fallback and the vault read.
VAULT_CITY_MAP = {"Cave": 0, "Bonkers": 1}
# A banker within this many yards of the vault stays where it is.
STAY_YARDS = 250.0
# Grey: the only quality a banker sells.
JUNK_QUALITY = 0
ACTION = "bankhome"
HOME_COOLDOWN_MINUTES = 10


def is_banker(member) -> bool:
    return getattr(member, "role", "") == BANKER


def city_zone(guild) -> int:
    return int(VAULT_CITY_ZONE.get(str(guild), 0))


def vault_map(guild) -> int | None:
    return VAULT_CITY_MAP.get(str(guild))


def _yards(member, spot) -> float:
    return math.hypot(float(member.x) - spot.x, float(member.y) - spot.y)


def at_home(member) -> bool:
    """Whether the banker stands in its vault city, beside the vault when the
    vault's place is known. An unread position is never home."""
    zone = city_zone(member.guild)
    if not zone or member.zone_id is None or int(member.zone_id) != zone:
        return False
    if member.x is None or member.y is None:
        return False
    vault = getattr(member, "vault", None)
    if vault is None:
        return True
    if member.map_id is None or int(vault.map_id) != int(member.map_id):
        return False
    return _yards(member, vault) <= STAY_YARDS


def junk_only(stacks) -> tuple:
    """The grey stacks of what the plan would sell: a banker sells nothing else."""
    return tuple(s for s in stacks or () if int(s.quality) == JUNK_QUALITY)


def nearest_vault(member, spots):
    """The guild vault spawn in the member's vault city nearest it, or None."""
    wanted = vault_map(member.guild)
    if wanted is None:
        return None
    best, best_yards = None, None
    here = (member.x, member.y)
    for spot in spots or ():
        if int(spot.map_id) != wanted:
            continue
        yards = (
            math.hypot(float(here[0]) - spot.x, float(here[1]) - spot.y)
            if None not in here
            and member.map_id is not None
            and int(member.map_id) == wanted
            else 0.0
        )
        if best_yards is None or yards < best_yards:
            best, best_yards = spot, yards
    return best


def attach_vaults(members, spots) -> list:
    """The bankers, each carrying its guild's vault spawn; everyone else as is."""
    out = []
    for m in members:
        if not is_banker(m):
            out.append(m)
            continue
        vault = nearest_vault(m, spots)
        out.append(replace(m, vault=vault) if vault is not None else m)
    return out
