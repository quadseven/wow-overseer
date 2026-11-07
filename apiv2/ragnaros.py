"""GET /api/v2/ragnaros?guild=<cave|bonkers>: the road to a Ragnaros attempt.

One total per guild, the eight goal checkpoints A to H as rows of seats
passing, every blocker with how many of the 40 seats it holds back, and the
Molten Core attempt count. It composes reads that exist: the goal read
(cached, apiv2/goal.py), the raidteams read and the guild's Molten Core runs.
A milestone with no small, correct read says `measured: false` and why.
roadtoragnaros.py holds the rules and the arithmetic.
"""

from __future__ import annotations

import guildrun
import raidrun
import raidteams
import readcache
import realmread
import roadtoragnaros

from . import _scope
from . import goal as goal_read
from . import raidteams as teams_read

CACHE_SECONDS = 60.0
_MAX_RUNS = 500

_CACHE = readcache.ReadCache(CACHE_SECONDS)


def build(ctx, guild: str) -> dict:
    teams = None
    if guild in raidteams.GROUPS:
        teams = teams_read.build(guild, teams_read.fetch(ctx.read, guild))
    _, goal = goal_read.goal({"guild": [guild]}, ctx)
    try:
        runs = guildrun.keyword_runs(ctx.read, guild, raidrun.MOLTEN_CORE, _MAX_RUNS)
    except realmread.Gap:
        runs = None
    return roadtoragnaros.build(guild, teams, goal, runs)


def ragnaros(query: dict, ctx) -> tuple[int, dict]:
    asked = (query.get("guild") or [""])[0].strip()
    if not asked:
        return 400, {"error": "say guild="}
    guild = _scope.guild(ctx, asked)
    if guild is None:
        return 404, _scope.no_such_guild(ctx)
    return 200, _CACHE.get("ragnaros:%s" % guild, lambda: build(ctx, guild))


ROUTES = {"/api/v2/ragnaros": ragnaros}
