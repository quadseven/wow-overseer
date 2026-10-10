"""GET /api/v2/social?name=X: a member's family, guild roster and friends list.

The Social panel the live tiles on Now open. Its old read, /api/client/social,
went with the classic page (#717), which left the tiles' Social button with
nothing to draw. This is that read again, under /api/v2 and built by the same
builder (vclient.build_social):

  family    the member's family in roster order, lead first; a name the
            roster holds that the world does not is "not on this realm"
  guild     the member's guild roster, online first, then highest level
  friends   the member's friends list (character_social), the same order;
            the ignore list is names only

Gated like every v2 read that takes a name: a family guild member, or a 404.
A member of a family guild who is in no family reads as a family of one.
Read-only.
"""

from __future__ import annotations

import vclient

from ._scope import NOT_A_MEMBER, guild_member, holes, wanted_name

FAMILY_SQL = "SELECT name, level, class, race, online FROM characters WHERE name IN "
GUILD_SQL = (
    "SELECT g.guildid AS guild_id, g.name AS guild_name "
    "FROM characters c JOIN guild_member gm ON gm.guid = c.guid "
    "JOIN guild g ON g.guildid = gm.guildid WHERE c.name = %s"
)
ROSTER_SQL = (
    "SELECT c.name, c.level, c.class, c.race, c.online, gm.rank, "
    "gr.rname AS rank_name "
    "FROM guild_member gm JOIN characters c ON c.guid = gm.guid "
    "LEFT JOIN guild_rank gr ON gr.guildid = gm.guildid AND gr.rid = gm.rank "
    "WHERE gm.guildid = %s"
)
FRIENDS_SQL = (
    "SELECT f.name, f.level, f.class, f.race, f.online, s.flags, s.note "
    "FROM characters c JOIN character_social s ON s.guid = c.guid "
    "JOIN characters f ON f.guid = s.friend WHERE c.name = %s"
)


def family_of(ctx, name: str) -> tuple[str, list[str]]:
    """(family key, the family's names) for a member, or ("", [name])."""
    for key, names in ctx.server._fetch_family_groups():
        if name in names:
            return key, list(names)
    return "", [name]


def fetch(ctx, name: str, family_names: list[str]) -> dict:
    """The family's rows, the member's guild and its roster, and the friends."""
    rd = ctx.read
    # S608: placeholders only, one per roster name from the database.
    family_sql = FAMILY_SQL + "(" + holes(len(family_names)) + ")"  # noqa: S608
    family_rows = rd.rows(family_sql, tuple(family_names), what="characters")
    guilds = rd.rows(GUILD_SQL, (name,), what="guild_member")
    guild = guilds[0] if guilds else None
    roster = []
    if guild is not None:
        roster = rd.rows(ROSTER_SQL, (guild["guild_id"],), what="guild_member")
    friends = rd.rows(FRIENDS_SQL, (name,), what="character_social")
    return {
        "family_rows": list(family_rows),
        "guild": guild,
        "guild_rows": list(roster),
        "social_rows": list(friends),
    }


def social(query: dict, ctx) -> tuple[int, dict]:
    name = wanted_name(query)
    if not guild_member(ctx, name):
        return 404, dict(NOT_A_MEMBER)
    key, names = family_of(ctx, name)
    payload = vclient.build_social(name, key, names, **fetch(ctx, name, names))
    payload["family_key"] = key
    return 200, payload


ROUTES = {"/api/v2/social": social}
