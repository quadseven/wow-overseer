"""Who a /api/v2 read may answer about, and the small helpers they share.

THE SAME CLOSED SET AS /api/armory/member. A read that takes a name answers
only for a member of a family guild, as the database reports the guilds:
anything else is a 404, never a query about an arbitrary character. The name
must also pass the world's own name rule before it reaches SQL at all.
"""

from __future__ import annotations

NOT_A_MEMBER = {"error": "not a guild member"}


def wanted_name(query: dict) -> str:
    """The `name` parameter, or "" when there is none."""
    return (query.get("name") or [""])[0]


def guild_member(ctx, name: str) -> bool:
    """True when `name` is a family member or a member of a family guild."""
    server = ctx.server
    if not server._NAME_RE.fullmatch(name or ""):
        return False
    groups = server._fetch_family_groups()
    names = [n for _key, group in groups for n in group]
    return name in names or server._is_family_guildmate(name, names)


def holes(n: int) -> str:
    """A run of `n` placeholders for an IN list; every value is still bound."""
    return ", ".join(["%s"] * n)
