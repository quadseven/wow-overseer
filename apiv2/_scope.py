"""Who a /api/v2 read may answer about, and the small helpers they share.

ONE CLOSED SET, families.Families.may_answer (the map server's FAMILIES): a
read that takes a name answers only for a family member or a member of a
family guild, as the database reports the guilds; anything else is a 404,
never a query about an arbitrary character. The name must also pass the
world's own name rule before it reaches SQL at all. A read that takes a guild
answers only for a family guild (`guild`), matched without case, and refuses
anything else before it opens a connection of its own.
"""

from __future__ import annotations

NOT_A_MEMBER = {"error": "not a guild member"}
NAME_MAX = 12


def wanted_name(query: dict) -> str:
    """The `name` parameter, or "" when there is none."""
    return (query.get("name") or [""])[0]


def name_shaped(value: str) -> bool:
    """Letters only, at most twelve: the shape of a character name, checked
    before a value is looked up at all."""
    value = (value or "").strip()
    return bool(value) and len(value) <= NAME_MAX and value.isalpha()


def may_answer(ctx, name: str) -> bool:
    """True when `name` is a family member or a member of a family guild."""
    return ctx.server.FAMILIES.may_answer(name)


def guilds(ctx) -> dict:
    """{lower-case name: name} for every family guild."""
    return {g["name"].lower(): g["name"] for g in ctx.server.FAMILIES.guilds()}


def guild(ctx, value: str) -> str | None:
    """The family guild's own name for `value`, any case, or None."""
    return guilds(ctx).get((value or "").strip().lower())


def no_such_guild(ctx) -> dict:
    """The refusal for a guild outside the set, naming the ones inside it."""
    return {"error": "no such guild", "guilds": sorted(guilds(ctx))}


def holes(n: int) -> str:
    """A run of `n` placeholders for an IN list; every value is still bound."""
    return ", ".join(["%s"] * n)


def guarded(ctx, cur, sql: str, params: tuple = (), what: str = "") -> list:
    """The map server's own degraded-schema guard: a missing table or column
    is an empty read, anything else still fails the request."""
    return ctx.server._wide_guarded(cur, sql, params, "", what)
