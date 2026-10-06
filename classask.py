"""A class quest that needs help is asked for in guild chat, and answered.

WHY THIS EXISTS. The operator made class quests the top-priority job of every
guild member (2026-10-06): every class does every class-specific quest as soon
as it is eligible, and a quest that needs help is ASKED for, never waited on in
silence. classquest.py does the solo steps (take, hunt, hand in). It names a
quest it cannot do alone, and this module is what the member does about that:
a paladin's level-12 elites, a druid's suggested group, a hunt that stalled
through every pack of its objective (classquest.Hunts) say so in guild chat,
and free guildmates answer.

THE SAME ROWS AS THE DUNGEON ASKS. An ask is a guildsocial.Post of kind
"quest" (the overseer_guild_ask table already has the kind), its yes a
guildsocial.Reply (the overseer_guild_answer table), and the bridge writes
both through the same writer as a dungeon ask. guildsocial.plan_pass reads only
the dungeon kind, so the two never touch each other's rows.

WHO ASKS. A member whose class quests are all blocked on help (guildjobs.
class_helps: a member with a quest it can do goes and does that first) and who
is free. One open ask per member, MAX_OPEN_PER_GUILD in a guild, NEW_PER_PASS a
pass, ASK_COOLDOWN_MINUTES before the same member asks again.

WHO ANSWERS. A free member of the same guild, not already on an ask, within
LEVEL_BAND levels of the asker and on its map (the open world's maps are
continents): the nearest first, ANSWERS_PER_PASS a pass, as many as the quest
wants.

BOUNDED. An ask lives guildsocial.ASK_MINUTES and, filled, FILLED_GRACE_MINUTES
more; a member is held out of the dungeon passes (held_names) only while its
ask has a yes and has not run out, then not again for the cooldown. A quest
nobody answers never holds a member at all.

WHAT IS NOT HERE: the group. Forming it needs a module verb that does not
exist: one that seats the named members in one party and walks the party to a
creature spawn (finder-run is the dungeon door's, and walk-to-spawn walks one
bot). Until it does, a filled ask runs out unformed, and the pass says so in its
notes.

PURE: rows in, a guildsocial.Pass out.
"""

from __future__ import annotations

import os

import guildsocial
from guildsocial import (
    DPS,
    FILLED,
    HELPS,
    LIVE_ASKS,
    OPEN,
    YES,
    Post,
    Reply,
)

ENV_SWITCH = "CLASS_ASK"
KIND = "quest"

ASK_MINUTES = guildsocial.ASK_MINUTES
FILLED_GRACE_MINUTES = guildsocial.FILLED_GRACE_MINUTES
ASK_COOLDOWN_MINUTES = guildsocial.ASK_COOLDOWN_MINUTES
ANSWERS_PER_PASS = guildsocial.ANSWERS_PER_PASS
MAX_OPEN_PER_GUILD = 3
NEW_PER_PASS = 2
LEVEL_BAND = 5

_NUMBERS = {1: "one", 2: "two", 3: "three", 4: "four"}


def enabled(environ=None) -> bool:
    """On unless CLASS_ASK says off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


def target_of(quest_id) -> str:
    return "quest:%d" % int(quest_id)


def quest_of(ask) -> int:
    """The quest id an ask is for, 0 when its target is not a quest's."""
    head, _, tail = str(ask.target).partition(":")
    return int(tail) if head == "quest" and tail.isdigit() else 0


def quest_asks(asks) -> list:
    return [a for a in asks if a.kind == KIND]


def _past(when, now) -> bool:
    return when is not None and now is not None and when <= now


def _minutes_since(when, now) -> float:
    if when is None or now is None:
        return 1e9
    return (now - when).total_seconds() / 60.0


def _running(ask, now) -> bool:
    """Whether a live ask has not run out: an open one before its expiry, a
    filled one within the grace after it."""
    if ask.state == OPEN:
        return not _past(ask.expires_at, now)
    return (
        ask.state == FILLED
        and _minutes_since(ask.expires_at, now) <= FILLED_GRACE_MINUTES
    )


def held_names(asks, answers, now) -> set:
    """The members the dungeon passes leave alone: the asker of a running quest
    ask that has a yes, and each member whose yes stands on one. An ask nobody
    has answered holds nobody, and one that ran out holds nobody."""
    yes_by_ask: dict = {}
    for a in answers or ():
        if a.state == YES:
            yes_by_ask.setdefault(a.ask_id, []).append(a.member)
    held = set()
    for ask in quest_asks(asks):
        if ask.state not in LIVE_ASKS or not _running(ask, now):
            continue
        yes = yes_by_ask.get(ask.id, [])
        if yes:
            held.add(ask.asker)
            held.update(yes)
    return held


# --- the words --------------------------------------------------------------------

_ASK_GROUP = (
    "Anyone free to help with {title}? Need {n} to take down {creature}, it wants a group.",
    "LF{k}M for my class quest, {title}. {creature} is too much alone, need {n}.",
    "Class quest {title} needs a group. Could use {n} to go after {creature}.",
)
_ASK_STUCK = (
    "Stuck on my class quest, {title}. Nothing to show for it after a long hunt, anyone want to come along?",
    "{title} is not going anywhere for me alone. Anyone free to help?",
)
_ANSWER = (
    "Count me in for {title}, {asker}.",
    "I can help with {title}, {asker}.",
    "Sure {asker}, I'll come for {title}.",
)


def _fit(text: str, limit: int = 255) -> str:
    return guildsocial._fit(text, limit)


def ask_line(help_) -> str:
    move = help_.move
    n = _NUMBERS.get(move.want, str(move.want))
    creature = move.spot.name if move.spot and move.spot.name else "its objective"
    if move.blocker == "stalled":
        template = guildsocial._pick(_ASK_STUCK, help_.member, move.quest)
    else:
        template = guildsocial._pick(_ASK_GROUP, help_.member, move.quest)
    return _fit(
        template.format(title=move.title, n=n, k=move.want + 1, creature=creature)
    )


def answer_line(member: str, asker: str, title: str, quest: int) -> str:
    template = guildsocial._pick(_ANSWER, member, quest)
    return _fit(template.format(asker=asker, title=title))


# --- the pass ---------------------------------------------------------------------


def _distance(a, b) -> float:
    if a.x is None or a.y is None or b.x is None or b.y is None:
        return 1e9
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _helper_choices(asker, free: dict, taken: set, level: int, map_id: int) -> list:
    """Free mates of the asker's guild that may answer, nearest first."""
    out = []
    for name, mate in free.items():
        if (
            name == asker.name
            or name in taken
            or mate.member.guild != asker.member.guild
        ):
            continue
        if int(mate.member.map_id) != int(map_id):
            continue
        if abs(int(mate.member.level) - int(level)) > LEVEL_BAND:
            continue
        out.append((_distance(asker, mate), name))
    return [name for _d, name in sorted(out)]


def plan_pass(helps, mates, held, asks, answers, now) -> guildsocial.Pass:
    """One pass of the class quest asks.

    helps    classquest.Help rows: the class quests members need help with now
    mates    guildsocial.Mate for every member read; `held` name -> why not free
    asks     every overseer_guild_ask row; only the quest kind is read
    answers  the answer rows
    """
    free = {m.name: m for m in mates if m.name not in held}
    by_member = {}
    for h in helps:
        by_member.setdefault(h.member, h)
    live = [a for a in quest_asks(asks) if a.state in LIVE_ASKS]
    yes_by_ask: dict = {}
    for a in answers or ():
        if a.state == YES:
            yes_by_ask.setdefault(a.ask_id, []).append(a)
    expire, cancel, withdraw, filled, still = [], [], [], [], []
    for ask in live:
        yeses = yes_by_ask.get(ask.id, [])
        need = by_member.get(ask.asker)
        passing = held.get(ask.asker) in guildsocial.PASSING
        if (
            ask.state == OPEN
            and _past(ask.expires_at, now)
            or (ask.state == FILLED and not _running(ask, now))
        ):
            expire.append((ask.id, ask.asker, ""))
        elif (
            (ask.asker not in free and not passing)
            or need is None
            or (need.move.quest != quest_of(ask))
        ):
            cancel.append(ask.id)
        else:
            still.append(ask)
            withdraw += [
                y.id
                for y in yeses
                if y.member not in free
                and held.get(y.member) not in guildsocial.PASSING
            ]
            continue
        withdraw += [y.id for y in yeses]
    spoken = {a.asker for a in still} | {
        y.member
        for a in still
        for y in yes_by_ask.get(a.id, [])
        if y.id not in set(withdraw)
    }
    replies, notes = [], []
    for ask in sorted(still, key=lambda a: a.id):
        need = by_member[ask.asker]
        standing = [y for y in yes_by_ask.get(ask.id, []) if y.id not in set(withdraw)]
        wanted = max(1, len(ask.roles_needed)) - len(standing)
        if wanted <= 0:
            if ask.state == OPEN:
                filled.append(ask.id)
            notes.append(
                "%s's %s ask is full; the module has no verb that seats a party and "
                "walks it to a spawn, so the group is not formed"
                % (ask.asker, need.move.title)
            )
            continue
        asker = free.get(ask.asker)
        if asker is None:
            continue
        for name in _helper_choices(asker, free, spoken, need.level, need.map_id)[
            : min(wanted, ANSWERS_PER_PASS)
        ]:
            replies.append(
                Reply(
                    ask.id,
                    name,
                    DPS,
                    HELPS,
                    answer_line(name, ask.asker, need.move.title, need.move.quest),
                )
            )
            spoken.add(name)
    posts = _new_posts(by_member, free, asks, still, spoken, now)
    return guildsocial.Pass(
        expire=tuple(expire),
        cancel=tuple(cancel),
        withdraw=tuple(withdraw),
        filled=tuple(filled),
        posts=tuple(posts),
        replies=tuple(replies),
        notes=tuple(notes),
    )


def _recent_askers(asks, now) -> set:
    return {
        a.asker
        for a in quest_asks(asks)
        if a.state not in LIVE_ASKS
        and _minutes_since(a.created_at, now) < ASK_COOLDOWN_MINUTES
    }


def _new_posts(by_member, free, asks, still, spoken, now) -> list:
    barred = spoken | _recent_askers(asks, now)
    open_in: dict = {}
    for a in still:
        open_in[a.guild] = open_in.get(a.guild, 0) + 1
    posts = []
    for name in sorted(by_member, key=lambda n: (by_member[n].level, n)):
        if len(posts) >= NEW_PER_PASS:
            break
        h = by_member[name]
        if (
            name not in free
            or name in barred
            or open_in.get(h.guild, 0) >= MAX_OPEN_PER_GUILD
        ):
            continue
        move = h.move
        posts.append(
            Post(
                guild=h.guild,
                asker=name,
                kind=KIND,
                target=target_of(move.quest),
                target_label=move.title[:96],
                roles_needed=guildsocial.roles_text((DPS,) * move.want),
                reason=_fit("the class quest %s" % move.title, 160),
                said=ask_line(h),
                minutes=ASK_MINUTES,
            )
        )
        open_in[h.guild] = open_in.get(h.guild, 0) + 1
    return posts
