"""A class quest that needs help is asked for in guild chat, and answered.

WHY THIS EXISTS. The operator made class quests the top-priority job of every
guild member (2026-10-06): every class does every class-specific quest as soon
as it is eligible, and a quest that needs help is ASKED for, never waited on in
silence. classquest.py does the solo steps (take, hunt, hand in). It names a
quest it cannot do alone, and this module is what the member does about that:
a paladin's level-12 elites, a druid's suggested group, a hunt that stalled
through every pack of its objective (classquest.Hunts), and a use the world
refused for good or that changed nothing at every target (classuse.py) say so
in guild chat,
and free guildmates answer.

THE SAME ROWS AS THE DUNGEON ASKS. An ask is a guildsocial.Post of kind
"quest" (the overseer_guild_ask table already has the kind), its yes a
guildsocial.Reply (the overseer_guild_answer table), and the bridge writes
both through the same writer as a dungeon ask. guildsocial.plan_pass reads only
the dungeon kind, so the two never touch each other's rows.

WHO ASKS. A member whose class quests are all blocked on help (guildjobs.
class_helps: a member with a quest it can do goes and does that first) and who
is free. One open ask per member, MAX_OPEN_PER_GUILD in a guild, NEW_PER_PASS a
pass, ASK_COOLDOWN_MINUTES before the same member asks again. A quest no party
could walk to (a use that changed nothing) is never asked for, and one asked
for guildjobs.CLASS_ASK_STREAK_MAX times in a row that did not get it done
(no party, or a party that went and failed, #1028), or whose last three parties
timed out, is not asked for again
until its hold runs out: both yield to levelling meanwhile
(guildjobs.class_asking). While a member asks, the guild jobs give it no other
step (guildjobs.asking_line, #1072): a step in hand holds it "on a guild job",
which cancelled its live ask and kept it from asking again, so its run never
reached the server's tries.

WHO ANSWERS. A free member of the same guild, not already on an ask, within
LEVEL_BAND levels of the asker, on its map (the open world's maps are
continents) and within HELPER_REACH_YARDS of it: the nearest first,
ANSWERS_PER_PASS a pass, as many as the quest wants, and never one barred from
this ask. A player answers "on my way" and travels, and so does an answerer:
it walks to the objective and meets the asker there before the party forms
(classparty.py), because the module seats nobody farther than 100 yards from
the leader.

AN ASK NOBODY ANSWERS GOES TO THE SERVER (#871). On 2026-10-14 four members
had asked the guild 2 to 7 times for Call of Fire or Redemption over 5 to 14
hours and drawn no yes at all: no guildmate stood free in the band and in
reach. From ESCALATE_AFTER_ASKS asks in a row that did not get the quest done
(no party, or a party that failed: Help.tries), the ask reaches farther
(ESCALATED_REACH_YARDS) and the asker calls it in the faction's public channel as well (guildpug's call row and channel), and a
random bot of its side, free, in the band, on its map and in that reach
answers by a whisper, nearest first; the asker tells the guild
(plan_escalation). Its yes is a guildpug answer (stance pug), and its party
forms as any other: the module seats any bot that is not grouped, and walks
any bot that is not on the roster. A family member cannot be offered one: its
family stands in its own group, which party-up refuses, and walk-to-spawn
refuses a roster member. Every ask still short after a pass names each
guildmate that did not come and why, and counts the random bots by reason
(Silence), so the operator reads who saw it and why each said no.

WHERE A PARTY STOPPED IS KEPT (#1001). A yes taken back because its helper
was called away (held for anything but a fight) writes the step on the ask's
reason column (stopped, STOPPED), as classparty's flow does for an invite
refused or a meeting missed, and the members page says that step in place of
"no party formed".

BOUNDED. An ask lives guildsocial.ASK_MINUTES and, filled, FILLED_GRACE_MINUTES
more, unless a party is up for it: then the party's own clock (classparty.py)
bounds it, and so the hold of its members. A quest nobody answers holds nobody.

THE GROUP is classparty.py's: a filled ask has the asker and its answerers walk
to the objective and meet there, then the module seats them in one party
(`party-up`), walks it to the objective (`party-walk`) and ends it
(`party-disband`). A member is held out of the dungeon passes (held_names)
while it travels to the meeting and while the party is up; before that, from
its ask's first yes (below).

A HELP PARTY HOLDS ITS MEMBERS FROM ITS FIRST YES (#1001). On 2026-10-15 an
asker whose Call of Fire had drawn yes answers 20 times asked the guild for
Ragefire Chasm 24 times in 12 hours, and its walks to the objective ended
"character is held by another verb": the ask held nobody until its party was
on the board, so the dungeon asks and the guild jobs took the asker and its
helpers in between. From the pass a yes stands, the asker and its helpers are
held out of the dungeon passes and the guild jobs (gathering), until the ask
ends or the yes is taken back.

PURE: rows in, a guildsocial.Pass out.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import guildpug
import guildrun
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
# The module forms a party only of members within 100 yards of the leader
# (mod-overseer#866): the members meet at the objective until each stands
# within this of the leader (classparty.judge_meeting).
SEAT_RANGE_YARDS = 90.0
# How far an answerer may stand from the asker: it walks to the objective to
# meet it. Measured on 2026-10-12, no member of one guild within LEVEL_BAND of
# an asker stood within 1,700 yards of it, so answerers held to the seat
# range drew no yes at all.
HELPER_REACH_YARDS = 2500.0
# Asks in a row that did not get the quest done before the next is called to
# the server too (guildjobs.CLASS_ASK_STREAK_MAX leaves it two tries before the
# member yields).
ESCALATE_AFTER_ASKS = 2
# How far a helper of an escalated ask may stand: about nine minutes of a
# straight walk, inside classparty.MEET_SECONDS.
ESCALATED_REACH_YARDS = 4000.0

# Why a member or a random bot does not come, as the Silence line says it.
OTHER_MAP = "on another map"
OUT_OF_BAND = "more than %d levels apart" % LEVEL_BAND
TOO_FAR = "too far away"
ANSWERING = "on another ask"
REFUSED = "refused by the world for this ask"
OTHER_SIDE = "the other side"
GUILDMATE = "a guildmate, who answers in guild chat"
UNPICKED = "free, not picked this pass"
NOT_READ = "no longer read in the world"

_NUMBERS = {1: "one", 2: "two", 3: "three", 4: "four"}

# The reason column of an ask whose party a step stopped starts with this
# (stopped), as one whose party went and failed starts with FAILED.
STOPPED = "stopped: "
FAILED = "failed: "
# overseer_guild_ask.reason is 160 characters wide.
REASON_CHARS = 160


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


def held_names(parties) -> set:
    """The members the dungeon passes leave alone: the leader and the helpers of
    each class quest party that is meeting at its objective or up
    (classparty.PartyRun). An ask nobody has answered, one still being answered
    and one whose meeting failed or whose party was refused or ended hold
    nobody."""
    held = set()
    for party in parties or ():
        held.update(party.names())
    return held


def gathering(quest_pass, asks, answers) -> set:
    """The members of each help party still gathering: the asker of every live
    quest ask this pass keeps that has a yes standing after it, the yeses it
    says now among them, and those helpers. The dungeon passes and the guild
    jobs leave them alone, so no other verb holds one when its party walks to
    the objective (#1001). An ask nobody has answered holds nobody."""
    ended = {e[0] for e in quest_pass.expire} | set(quest_pass.cancel)
    live = {
        a.id: a.asker
        for a in quest_asks(asks)
        if a.state in LIVE_ASKS and a.id not in ended
    }
    gone = set(quest_pass.withdraw)
    standing = [
        (y.ask_id, y.member)
        for y in answers or ()
        if y.state == YES and y.id not in gone
    ]
    standing += [(r.ask_id, r.member) for r in quest_pass.replies]
    held = set()
    for ask_id, member in standing:
        if ask_id in live:
            held.update((live[ask_id], member))
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
_ASK_USE = (
    "Stuck on my class quest, {title}. Using its item got me nowhere, anyone free to help?",
    "{title} will not budge for me alone. Anyone free to come and take a look?",
)
_ANSWER = (
    "Count me in for {title}, {asker}.",
    "I can help with {title}, {asker}.",
    "Sure {asker}, I'll come for {title}.",
)
# Said in the faction's public channel, whispered by a random bot, and told
# the guild, as guildpug's lines are.
_CALL = (
    "LF{n}M for my class quest, {title}. Meeting at {creature}, pst",
    "Anyone free for {title}? Class quest, need {n} at {creature}.",
)
_PUG_ANSWER = (
    "I can help with {title}, inv",
    "Saw your LF for {title}, on my way. Inv?",
)
_PUG_TOLD = (
    "Got help from LFG for {title}: {pug}'s coming.",
    "{pug} answered in LFG, coming for {title}.",
)


def _fit(text: str, limit: int = 255) -> str:
    return guildsocial._fit(text, limit)


def ask_line(help_) -> str:
    move = help_.move
    n = _NUMBERS.get(move.want, str(move.want))
    creature = move.spot.name if move.spot and move.spot.name else "its objective"
    if move.blocker == "usestalled":
        template = guildsocial._pick(_ASK_USE, help_.member, move.quest)
    elif move.blocker == "stalled":
        template = guildsocial._pick(_ASK_STUCK, help_.member, move.quest)
    else:
        template = guildsocial._pick(_ASK_GROUP, help_.member, move.quest)
    return _fit(
        template.format(title=move.title, n=n, k=move.want + 1, creature=creature)
    )


def answer_line(member: str, asker: str, title: str, quest: int) -> str:
    template = guildsocial._pick(_ANSWER, member, quest)
    return _fit(template.format(asker=asker, title=title))


def call_line(help_, n: int) -> str:
    """The asker's call in the public channel for `n` helpers."""
    move = help_.move
    creature = move.spot.name if move.spot and move.spot.name else "the objective"
    template = guildsocial._pick(_CALL, help_.member, move.quest)
    return _fit(template.format(title=move.title, n=n, creature=creature))


def pug_answer_line(pug: str, title: str, quest: int) -> str:
    return _fit(guildsocial._pick(_PUG_ANSWER, pug, quest).format(title=title))


def pug_told_line(asker: str, pug: str, title: str) -> str:
    template = guildsocial._pick(_PUG_TOLD, asker, pug)
    return _fit(template.format(pug=pug, title=title))


# --- the pass ---------------------------------------------------------------------


def _distance(a, b) -> float:
    if a.x is None or a.y is None or b.x is None or b.y is None:
        return 1e9
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def escalated(help_) -> bool:
    """Whether this help's ask goes to the server too: ESCALATE_AFTER_ASKS asks
    for it in a row did not get it done."""
    return int(getattr(help_, "tries", 0) or 0) >= ESCALATE_AFTER_ASKS


def reach_of(help_) -> float:
    """How far a helper of this help's ask may stand from the asker."""
    return ESCALATED_REACH_YARDS if escalated(help_) else HELPER_REACH_YARDS


def _out_of_reach(asker, mate, need) -> str:
    """Why `mate` stands where it cannot help the asker with `need`, or ""."""
    if int(mate.member.map_id) != int(need.map_id):
        return OTHER_MAP
    if abs(int(mate.member.level) - int(need.level)) > LEVEL_BAND:
        return OUT_OF_BAND
    if _distance(asker, mate) > reach_of(need):
        return TOO_FAR
    return ""


def _helper_choices(asker, free: dict, taken: set, need, refused=frozenset()) -> list:
    """Free mates of the asker's guild that may answer, nearest first, within
    reach_of(need), and not one barred from this ask."""
    out = []
    for name, mate in free.items():
        if (
            name == asker.name
            or name in taken
            or name in refused
            or mate.member.guild != asker.member.guild
            or _out_of_reach(asker, mate, need)
        ):
            continue
        out.append((_distance(asker, mate), name))
    return [name for _d, name in sorted(out)]


def _ended(ask, need, free, held, now, partied=frozenset()) -> str:
    """ "expire", "cancel" or "" for one live ask. An ask with a party up does
    not run out by its own clock, nor end with its asker's help unread or
    changed: the party's clock and its read of the quest log end it (#1001).
    Its asker gone still ends it."""
    up = ask.id in partied
    if not up and (
        (ask.state == OPEN and _past(ask.expires_at, now))
        or (ask.state == FILLED and not _running(ask, now))
    ):
        return "expire"
    passing = held.get(ask.asker) in guildsocial.PASSING
    if ask.asker not in free and not passing:
        return "cancel"
    if not up and (need is None or need.move.quest != quest_of(ask)):
        return "cancel"
    return ""


def _leaving(yeses, free, held) -> list:
    """The yes rows of members no longer free, who are not just in combat."""
    return [
        y
        for y in yeses
        if y.member not in free and held.get(y.member) not in guildsocial.PASSING
    ]


def stopped(words) -> str:
    """The reason column of an ask whose party a step stopped: STOPPED and the
    step, which the members page says in place of "no party formed"."""
    return (STOPPED + str(words))[:REASON_CHARS]


def _busy_reason(ask, left, held) -> tuple:
    """(ask id, reason) naming the helpers called away from this ask."""
    words = "; ".join(
        "%s was busy: %s" % (y.member, held.get(y.member) or NOT_READ) for y in left
    )
    return ask.id, stopped(words)


def _close(live, by_member, yes_by_ask, free, held, now, partied=frozenset()) -> tuple:
    """(expire, cancel, withdraw, still, reasons): the asks that end now, the
    yeses taken back, the asks still running, and the step that stopped each
    still running ask a helper was called away from."""
    expire, cancel, withdraw, still, reasons = [], [], [], [], []
    for ask in live:
        yeses = yes_by_ask.get(ask.id, [])
        how = _ended(ask, by_member.get(ask.asker), free, held, now, partied)
        if how == "expire":
            expire.append((ask.id, ask.asker, ""))
        elif how == "cancel":
            cancel.append(ask.id)
        else:
            still.append(ask)
            left = _leaving(yeses, free, held)
            withdraw += [y.id for y in left]
            if left:
                reasons.append(_busy_reason(ask, left, held))
            continue
        withdraw += [y.id for y in yeses]
    return expire, cancel, withdraw, still, reasons


def _full_note(ask, need, seats) -> str:
    """The note on a full ask. Whether its party forms is classparty's to say:
    it names every full ask it skips, and why (classparty.plan)."""
    if seats:
        return "%s's %s ask is full" % (ask.asker, need.move.title)
    return (
        "%s's %s ask is full; this worldserver does not seat a party yet, so "
        "the group is not formed" % (ask.asker, need.move.title)
    )


def _replies(ask, need, free, spoken, wanted, refused=frozenset()) -> list:
    """The new yes rows for one ask short of `wanted` helpers."""
    asker = free.get(ask.asker)
    if asker is None:
        return []
    names = _helper_choices(asker, free, spoken, need, refused)
    return [
        Reply(
            ask.id,
            name,
            DPS,
            HELPS,
            answer_line(name, ask.asker, need.move.title, need.move.quest),
        )
        for name in names[: min(wanted, ANSWERS_PER_PASS)]
    ]


def _answers(
    still, by_member, yes_by_ask, withdraw, free, spoken, partied, refused, seats
) -> tuple:
    """(replies, filled, notes) over the asks still running, oldest first."""
    gone = set(withdraw)
    replies, filled, notes = [], [], []
    for ask in sorted(still, key=lambda a: a.id):
        need = by_member.get(ask.asker)
        if need is None:
            # Its party is up and the help went unread (_ended): the party
            # works on, and draws no new yes meanwhile.
            continue
        standing = [y for y in yes_by_ask.get(ask.id, []) if y.id not in gone]
        wanted = max(1, len(ask.roles_needed)) - len(standing)
        if wanted > 0:
            made = _replies(
                ask, need, free, spoken, wanted, (refused or {}).get(ask.id, ())
            )
            replies += made
            spoken.update(r.member for r in made)
            continue
        if ask.state == OPEN:
            filled.append(ask.id)
        if ask.id not in partied:
            notes.append(_full_note(ask, need, seats))
    return replies, filled, notes


def plan_pass(
    helps,
    mates,
    held,
    asks,
    answers,
    now,
    partied=frozenset(),
    refused=None,
    cooling=frozenset(),
    seats=True,
) -> guildsocial.Pass:
    """One pass of the class quest asks.

    helps    classquest.Help rows: the class quests members need help with now
    mates    guildsocial.Mate for every member read; `held` name -> why not free
    asks     every overseer_guild_ask row; only the quest kind is read
    answers  the answer rows
    partied  ids of the asks a party is up for: their own clock does not end them
    refused  ask id -> the members the module refused for it, who do not answer it
    cooling  the members who gave an ask up lately and do not ask again yet
    seats    False while this worldserver is known not to seat a party
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
    expire, cancel, withdraw, still, reasons = _close(
        live, by_member, yes_by_ask, free, held, now, partied
    )
    gone = set(withdraw)
    spoken = {a.asker for a in still} | {
        y.member for a in still for y in yes_by_ask.get(a.id, []) if y.id not in gone
    }
    replies, filled, notes = _answers(
        still, by_member, yes_by_ask, withdraw, free, spoken, partied, refused, seats
    )
    closing = {e[0] for e in expire} | set(cancel)
    posts = _new_posts(
        by_member, free, asks, still, spoken | set(cooling), now, closing
    )
    return guildsocial.Pass(
        expire=tuple(expire),
        cancel=tuple(cancel),
        withdraw=tuple(withdraw),
        filled=tuple(filled),
        posts=tuple(posts),
        replies=tuple(replies),
        notes=tuple(notes),
        reasons=tuple(reasons),
    )


def _recent_askers(asks, now, closing=frozenset()) -> set:
    """Members whose last ask came to nothing within ASK_COOLDOWN_MINUTES. An
    ask this pass closes (`closing`) counts as closed already: read as live,
    its asker posted again in the same pass, a try every ASK_MINUTES rather
    than a quarter of an hour apart, and the ask after a run of
    guildjobs.CLASS_ASK_STREAK_MAX was posted before the run was counted, then
    cancelled on the next pass (#871)."""
    return {
        a.asker
        for a in quest_asks(asks)
        if (a.state not in LIVE_ASKS or a.id in closing)
        and _minutes_since(a.created_at, now) < ASK_COOLDOWN_MINUTES
    }


def _new_posts(by_member, free, asks, still, spoken, now, closing=frozenset()) -> list:
    barred = spoken | _recent_askers(asks, now, closing)
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
                reason=_fit("the class quest %s" % move.title, REASON_CHARS),
                said=ask_line(h),
                minutes=ASK_MINUTES,
            )
        )
        open_in[h.guild] = open_in.get(h.guild, 0) + 1
    return posts


# --- the server -------------------------------------------------------------------


@dataclass(frozen=True)
class Silence:
    """A live ask still short of helpers after a pass, and why: each
    guildmate of the asker that is not coming, by reason, and what the server
    said (the random bots read, by reason, or why it was not asked)."""

    ask_id: int
    asker: str
    title: str
    tries: int
    short: int
    guild: tuple = ()  # ((why, (name, ...)), ...), the commonest first
    server: str = ""

    @property
    def line(self) -> str:
        head = "class ask: %s's %s ask (ask %d, try %d) is %d short" % (
            self.asker,
            self.title,
            self.ask_id,
            self.tries + 1,
            self.short,
        )
        mates = "; ".join("%s: %s" % (why, ", ".join(n)) for why, n in self.guild)
        return "%s; guild: %s; server: %s" % (
            head,
            mates or "nobody else read",
            self.server,
        )


@dataclass(frozen=True)
class Escalation:
    """What the server part of one pass writes and says: guildpug.Call rows,
    guildpug.Join rows, and a Silence for every ask still short."""

    calls: tuple = ()
    joins: tuple = ()
    silences: tuple = ()


def _tally(reasons: dict) -> tuple:
    """why -> names, as ((why, names), ...) the commonest first."""
    return tuple(
        (why, tuple(sorted(names)))
        for why, names in sorted(reasons.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    )


def _guild_reasons(ask, need, asker, mates, held, coming, spoken, refused) -> tuple:
    """Why each guildmate of the asker that is not coming does not."""
    out: dict = {}
    for mate in mates:
        name = mate.name
        if name == ask.asker or name in coming or mate.member.guild != ask.guild:
            continue
        why = (
            held.get(name)
            or (ANSWERING if name in spoken else "")
            or (REFUSED if name in refused else "")
            or _out_of_reach(asker, mate, need)
            or UNPICKED
        )
        out.setdefault(why, []).append(name)
    return _tally(out)


def why_not_pug(asker, pug, need, faction, spoken, refused, busy, family) -> str:
    """Why this random bot cannot answer the asker's escalated ask, or ""."""
    why = guildrun.why_not(pug.member, busy, set(), family)
    if why:
        return why
    if pug.member.guild == asker.member.guild:
        return GUILDMATE
    if not faction or guildrun.faction_of([pug.member]) != faction:
        return OTHER_SIDE
    if pug.name in spoken:
        return ANSWERING
    if pug.name in refused:
        return REFUSED
    return _out_of_reach(asker, pug, need)


def _server(ask, need, asker, ctx, short) -> tuple:
    """(call or None, joins, the server's words) for one escalated ask.

    `short` is the seats still empty once the guild has answered, and the call
    names only those, as guildpug's dungeon call names its short_seats: a seat
    a guildmate holds is not offered to the server."""
    call = ctx["calls"].get(ask.id)
    if call is None:
        said = call_line(need, short)
        return (
            guildpug.Call(ask.id, ask.asker, (DPS,) * short, said),
            (),
            ("called in the public channel this pass"),
        )
    if guildpug._minutes_since(call.created_at, ctx["now"]) < (
        guildpug.ANSWER_AFTER_MINUTES
    ):
        return None, (), "called, answered from the next minute"
    faction = ctx["factions"].get(ask.guild, "")
    barred = ctx["refused"].get(ask.id, frozenset())
    tally: dict = {}
    ready = []
    for pug in ctx["pugs"]:
        why = why_not_pug(
            asker, pug, need, faction, ctx["spoken"], barred, ctx["busy"], ctx["family"]
        )
        if why:
            tally[why] = tally.get(why, 0) + 1
        else:
            ready.append((_distance(asker, pug), pug.name))
    joins = tuple(
        guildpug.Join(
            ask_id=ask.id,
            member=name,
            role=DPS,
            said=pug_answer_line(name, need.move.title, need.move.quest),
            asker=ask.asker,
            told_guild=pug_told_line(ask.asker, name, need.move.title),
        )
        for _d, name in sorted(ready)[: min(short, ANSWERS_PER_PASS)]
    )
    counts = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    words = "%d random bot(s) read%s" % (
        len(ctx["pugs"]),
        "".join(", %d %s" % (n, why) for why, n in counts),
    )
    return None, joins, words


def _reach_server(ask, need, asker, ctx, short) -> tuple:
    """(call or None, joins, the server's words) for one short ask. Only an
    escalated ask goes to the server, and only with pick-up groups on; any
    other ask gets no call and no joins, and the words say why."""
    if not escalated(need):
        return None, (), "not asked before try %d" % (ESCALATE_AFTER_ASKS + 1)
    if not ctx["pugs_on"]:
        return None, (), "pick-up groups are off (guildpug.ENV_SWITCH)"
    return _server(ask, need, asker, ctx, short)


def _live_after(asks, quest_pass) -> list:
    """The quest asks still live once the quest pass has closed its own."""
    ended = {a for a, _who, _line in quest_pass.expire} | set(quest_pass.cancel)
    return [a for a in quest_asks(asks) if a.state in LIVE_ASKS and a.id not in ended]


def _taken(asks, answers, quest_pass) -> tuple:
    """(live quest asks, live yeses, on_quest, spoken) as the pass leaves them.
    A guildmate is on another ask as plan_pass reads it (a quest ask); a
    random bot on any live ask's yes, a dungeon's pug too."""
    current = guildpug._answers_now(list(answers or ()), quest_pass)
    live = _live_after(asks, quest_pass)
    live_ids = {a.id for a in live} | {
        a.id for a in asks if a.kind != KIND and a.state in LIVE_ASKS
    }
    yeses = [a for a in current if a.state == YES and a.ask_id in live_ids]
    quest_ids = {a.id for a in live}
    on_quest = {a.asker for a in live} | {
        a.member for a in yeses if a.ask_id in quest_ids
    }
    return live, yeses, on_quest, on_quest | {a.member for a in yeses}


def _escalate(ask, need, asker, ctx, yeses, mates, held) -> tuple:
    """(call or None, joins, Silence or None) for one live quest ask: what the
    server does for it, then why it is still short, if it is."""
    coming = {a.member for a in yeses if a.ask_id == ask.id}
    short = max(1, len(ask.roles_needed)) - len(coming)
    if short <= 0:
        return None, (), None
    call, made, words = _reach_server(ask, need, asker, ctx, short)
    ctx["spoken"].update(j.member for j in made)
    ctx["on_quest"].update(j.member for j in made)
    short -= len(made)
    if short <= 0:
        return call, made, None
    refused = ctx["refused"].get(ask.id, frozenset())
    mates_why = _guild_reasons(
        ask, need, asker, mates, held, coming, ctx["on_quest"], refused
    )
    silence = Silence(
        ask.id, ask.asker, need.move.title, int(need.tries), short, mates_why, words
    )
    return call, made, silence


def plan_escalation(
    quest_pass,
    helps,
    mates,
    held,
    asks,
    answers,
    now,
    calls=None,
    pugs=(),
    factions=None,
    refused=None,
    busy=frozenset(),
    family=frozenset(),
    pugs_on=True,
) -> Escalation:
    """The server's part of one pass, after plan_pass (`quest_pass`).

    Each live quest ask still short of helpers once the guild has answered:
    an escalated one (escalated) is called in the public channel once, and a
    minute after its call random bots answer it, nearest first; every ask
    still short then carries a Silence.

    mates    guildsocial.Mate for every member read, `held` as plan_pass read it
    answers  every answer row; calls ask id -> guildpug.Call
    pugs     guildsocial.Mate for the random bots read; factions guild -> side
    refused  ask id -> the members the module refused for it
    busy     names in a guild run; family the roster's names
    pugs_on  False with guildpug's switch off: nothing goes to the server
    """
    live, yeses, on_quest, spoken = _taken(asks, answers, quest_pass)
    by_member = {}
    for h in helps:
        by_member.setdefault(h.member, h)
    by_name = {m.name: m for m in mates}
    ctx = {
        "calls": dict(calls or {}),
        "now": now,
        "pugs": list(pugs or ()),
        "factions": dict(factions or {}),
        "refused": dict(refused or {}),
        "spoken": spoken,
        "on_quest": on_quest,
        "busy": set(busy),
        "family": set(family),
        "pugs_on": pugs_on,
    }
    new_calls, joins, silences = [], [], []
    for ask in sorted(live, key=lambda a: a.id):
        need, asker = by_member.get(ask.asker), by_name.get(ask.asker)
        if need is None or asker is None or need.move.quest != quest_of(ask):
            continue
        call, made, silence = _escalate(ask, need, asker, ctx, yeses, mates, held)
        if call is not None:
            new_calls.append(call)
        joins += made
        if silence is not None:
            silences.append(silence)
    return Escalation(tuple(new_calls), tuple(joins), tuple(silences))
