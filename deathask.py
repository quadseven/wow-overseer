"""A death looper is asked for in guild chat, and a guildmate answers (#2277).

WHY THIS EXISTS. The death-loop pool never drains: the escape step
(guildjobs.death_loop_first) works per member, and a looper who escapes
alone returns to the same content at the same strength and loops again.
The durable exit is help: a group-up with a guildmate in reach. Slice 1 of
the help route named that offer in the escape's log line, and the ask
table learned the deathloop kind; this module is the executed half: the
planner the bridge's social pass runs beside the class quest asks.

THE SAME ROWS AS THE OTHER ASKS. An ask is a guildsocial.Post of kind
"deathloop" (guildsocial.KIND_DEATHLOOP), its target naming the loop
place, its reason naming the mate in reach, one helper wanted, and the
bridge writes it through the same writer as a dungeon or quest ask. The
answers side is the table's ordinary one; nothing here seats a party.

WHO IS ASKED FOR. A member the planning pass already flagged in a death
loop (deathloop.Loop, keyed by name in the pass's death-loop read) whose
best mate guildjobs.loop_mates finds in reach: the same selection the
escape's offer names, so the post and the log line never disagree about
who could come. A looper held for another job is not asked for, and a
held mate is not counted in reach.

BOUNDED, LIKE THE CLASS ASKS. One live ask per looper, MAX_OPEN_PER_GUILD
open in a guild, NEW_PER_PASS new a pass, and ASK_COOLDOWN_MINUTES before
a looper whose last ask came to nothing is asked again (the class asks'
cooldown read over the deathloop kind, guildsocial.ASK_COOLDOWN_MINUTES).

PURE: rows in, a guildsocial.Pass of posts out.
"""

from __future__ import annotations

import os

import guildjobs
import guildsocial
from guildsocial import DPS, LIVE_ASKS, Post

ENV_SWITCH = "DEATH_ASK"
KIND = guildsocial.KIND_DEATHLOOP

ASK_MINUTES = guildsocial.ASK_MINUTES
ASK_COOLDOWN_MINUTES = guildsocial.ASK_COOLDOWN_MINUTES
MAX_OPEN_PER_GUILD = 3
NEW_PER_PASS = 2
# overseer_guild_ask.reason is 160 characters wide (classask.REASON_CHARS).
REASON_CHARS = 160

_ASK_LINE = (
    "Keep dying in {place}, {deaths} times in an hour. "
    "Anyone free to group up and help me out of here?"
)


def enabled(environ=None) -> bool:
    """On unless DEATH_ASK says off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


def target_of(loop) -> str:
    return "deathloop:%d" % int(loop.zone)


def death_asks(asks) -> list:
    return [a for a in asks or () if a.kind == KIND]


def _fit(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _minutes_since(when, now) -> float:
    if when is None or now is None:
        return 1e9
    return (now - when).total_seconds() / 60.0


def _recent_askers(asks, now) -> set:
    """Members whose last deathloop ask came to nothing within
    ASK_COOLDOWN_MINUTES: the class asks' cooldown read, over this kind."""
    return {
        a.asker
        for a in death_asks(asks)
        if a.state not in LIVE_ASKS
        and _minutes_since(a.created_at, now) < ASK_COOLDOWN_MINUTES
    }


def _as_job_member(mate) -> guildjobs.Member:
    """A social-pass Mate as the guildjobs member loop_mates reads: the
    member's own fields, with the position the Mate carries."""
    m = mate.member
    return guildjobs.Member(
        name=m.name,
        guild=m.guild,
        role="",
        level=int(m.level),
        class_id=int(m.class_id),
        race=int(m.race),
        online=bool(m.online),
        in_combat=bool(m.in_combat),
        map_id=m.map_id,
        x=mate.x,
        y=mate.y,
        zone_id=m.zone_id,
        alive=bool(m.alive),
    )


def plan_pass(loops, mates, asks, now, held=frozenset()) -> guildsocial.Pass:
    """One pass of the death-loop asks: a Pass holding only posts.

    loops  name -> deathloop.Loop, the planning pass's death-loop read
    mates  guildsocial.Mate for every member read
    asks   every overseer_guild_ask row; only the deathloop kind is read
    held   name -> why not free (or a set of names): a held looper is not
           asked for, and a held mate is not counted in reach
    """
    held = set(held or ())
    jobs = {}
    for mate in mates or ():
        jobs.setdefault(mate.name, _as_job_member(mate))
    looping = set(loops or ())
    live = {a.asker for a in death_asks(asks) if a.state in LIVE_ASKS}
    recent = _recent_askers(asks, now)
    open_in: dict = {}
    for a in death_asks(asks):
        if a.state in LIVE_ASKS:
            open_in[a.guild] = open_in.get(a.guild, 0) + 1
    free_mates = [m for name, m in jobs.items() if name not in held]
    posts = []
    for name in sorted(looping):
        if len(posts) >= NEW_PER_PASS:
            break
        member = jobs.get(name)
        if member is None or name in held or name in live or name in recent:
            continue
        if open_in.get(member.guild, 0) >= MAX_OPEN_PER_GUILD:
            continue
        found = guildjobs.loop_mates(member, free_mates, looping=looping)
        if not found:
            continue
        mate = found[0]
        loop = loops[name]
        posts.append(
            Post(
                guild=member.guild,
                asker=name,
                kind=KIND,
                target=target_of(loop),
                target_label=loop.place[:96],
                roles_needed=guildsocial.roles_text((DPS,)),
                reason=_fit(
                    "%s is in reach to group up for the way out" % mate.name,
                    REASON_CHARS,
                ),
                said=_ASK_LINE.format(place=loop.place, deaths=loop.deaths),
                minutes=ASK_MINUTES,
            )
        )
        open_in[member.guild] = open_in.get(member.guild, 0) + 1
    return guildsocial.Pass(posts=tuple(posts))
