"""What the Guilds reads answer for, decided before any query runs.

The site is public-facing and takes no auth, so a read must not become a way
to look up any guild or character the realm holds. These reads answer for the
guilds the overseer manages (guildrun.DEFAULT_GUILDS) and for nothing else:

  guild=   one of those guilds, by name, any case. Anything else is refused
           by the handler before it opens a connection.
  name=    a character name of the realm's shape (letters only, at most 12),
           checked here; whether it belongs to a managed guild is part of the
           one query that reads it, so a name outside them reads as unknown.

Every value that reaches SQL is bound by the driver; nothing from a query
string is ever formatted into a statement.
"""

from __future__ import annotations

import guildrun

GUILDS = {g.lower(): g for g in guildrun.DEFAULT_GUILDS}
NAME_MAX = 12


def guild(value: str) -> str | None:
    """The managed guild's own name for `value`, or None."""
    return GUILDS.get((value or "").strip().lower())


def name(value: str) -> str | None:
    """`value` when it has the shape of a character name, else None."""
    value = (value or "").strip()
    if not value or len(value) > NAME_MAX or not value.isalpha():
        return None
    return value


def guild_holes() -> str:
    return ", ".join(["%s"] * len(GUILDS))


def guild_args() -> tuple:
    return tuple(GUILDS.values())
