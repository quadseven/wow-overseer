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

CLOSED BY THIS PASS (#2344). A deathloop ask is also closed here: the
dungeon and quest passes close only their own kinds, so without this a
deathloop ask stayed open forever, its asker was skipped for good by the
live-ask check, and three stuck asks filled a guild's MAX_OPEN_PER_GUILD
for ever. plan_pass emits a silent expire (the #1636 shape: the row
closes, no line is said) for every live deathloop ask past its
expires_at, and for every live ask whose asker is no longer in the loop
set (the recovered case). Expired asks stop counting toward the guild's
open cap in the same pass; an asker whose ask expires this pass is not
re-asked this pass, and the ordinary cooldown governs the next one.

THE SWITCH IS OFF UNTIL THE ANSWER SIDE EXISTS (#2344). Nothing yet
seats a party from a deathloop yes, so the guild chat line may not speak
yet: DEATH_ASK defaults off, and only an explicit on value enables new
posts. Expiry is not gated by the switch: asks already open keep closing
while the switch is off (the bridge's death-ask pass runs the expiry
half either way).

SEATED THIS PASS (#2277, piece 2 seating step). A member seated in a run
formed this same pass (a class quest party the bridge just planned) is
not free to this pass either, though it neither said a yes in the social
replies nor stands as a yes on any ask: the asker of such a run could
otherwise be counted in reach, named in a new post's reason, or drawn as
the yes for a deathloop ask in the very pass its own run forms. The
bridge passes those names in as `seated`; they are read exactly like the
names that already spoke.

THE ANSWER SIDE, PIECE 1 (#2277). A live deathloop ask draws one yes:
the first mate guildjobs.loop_mates finds in reach for its asker, the
same selection the post's reason names, answers as a helper in a damage
seat (the seat the ask wants). One yes per ask (the ask wants one
helper), one ask answered per member per pass, and at most
REPLIES_PER_PASS new yeses a pass, so yeses trickle the way the other
asks' do. A member already standing as a yes on any ask is not counted
again, a held mate does not answer, and an ask this pass expires draws
no yes. Nothing here seats a party: that is piece 2, and the switch
stays off until it lands.

FILLED, NOT SEATED (#2277, piece 2 bridge). A live ask holding a yes
(a standing yes on the answer rows, or the yes this pass draws in its
replies) whose asker and helper are both free and not held or seated
is emitted in the Pass's filled ids, and the bridge merges those ids
into the social pass, whose writer marks the ask filled through the
same generic path as the quest asks. Filled is a state, not a party:
no party is started here, and the switch stays off until a party
runner lands.

PURE: rows in, a guildsocial.Pass of posts, replies and expires out.
"""

from __future__ import annotations

import os

import guildjobs
import guildsocial
from guildsocial import DPS, HELPS, LIVE_ASKS, YES, Post, Reply

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

_ANSWER_LINES = (
    "Count me in, {asker}. On my way to {place}.",
    "I'll come help you out of {place}, {asker}.",
    "Sure {asker}, I'll group up for {place}.",
)

REPLIES_PER_PASS = 4
ANSWERS_PER_PASS = REPLIES_PER_PASS  # legacy alias; the cap below is this module's own


def answer_line(member: str, asker: str, place: str) -> str:
    template = guildsocial._pick(_ANSWER_LINES, member, asker, place)
    return template.format(asker=asker, place=place)


def enabled(environ=None) -> bool:
    """Off unless DEATH_ASK says on: no new deathloop ask is posted until
    the answer side exists (#2344). Expiry never consults this switch."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


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


def _past(when, now) -> bool:
    return when is not None and now is not None and when <= now


def expires(asks, looping, now) -> tuple:
    """The expire half of a pass: (ask id, asker, "") for every live
    deathloop ask past its expires_at, and for every live ask whose asker
    is no longer in the loop set. Silent, in ask-id order."""
    looping = set(looping or ())
    ending = [
        a
        for a in death_asks(asks)
        if a.state in LIVE_ASKS and (_past(a.expires_at, now) or a.asker not in looping)
    ]
    return tuple((a.id, a.asker, "") for a in sorted(ending, key=lambda a: a.id))


def expire_pass(asks, loops, now) -> guildsocial.Pass:
    """A Pass holding only expires: the half that runs while the switch
    is off, so asks already open keep closing (#2344)."""
    return guildsocial.Pass(expire=expires(asks, set(loops or ()), now))


def _replies(live_asks, ending_ids, jobs, looping, answers, held, spoken=()) -> tuple:
    """One yes per live deathloop ask that has none: the first mate
    loop_mates finds in reach for the asker, as a helper. A member
    answers at most one ask a pass, a member already standing as a yes
    on any ask is not counted again, and an ask ending this pass draws
    no yes."""
    standing = {a.member for a in answers or () if a.state == YES}
    answered = {a.ask_id for a in answers or () if a.state == YES}
    free_mates = [m for name, m in jobs.items() if name not in held]
    spoken = set(standing) | set(spoken or ())
    out = []
    for ask in sorted(live_asks, key=lambda a: a.id):
        if len(out) >= REPLIES_PER_PASS:
            break
        if ask.id in ending_ids or ask.id in answered:
            continue
        asker = jobs.get(ask.asker)
        if asker is None or ask.asker in held:
            continue
        found = guildjobs.loop_mates(asker, free_mates, looping=looping)
        mate = next((m for m in found if m.name not in spoken), None)
        if mate is None:
            continue
        out.append(
            Reply(
                ask_id=ask.id,
                member=mate.name,
                role=DPS,
                stance=HELPS,
                said=answer_line(mate.name, ask.asker, ask.target_label),
            )
        )
        spoken.add(mate.name)
    return tuple(out)


def plan_pass(
    loops,
    mates,
    asks,
    now,
    held=frozenset(),
    answers=(),
    spoken=frozenset(),
    seated=frozenset(),
) -> guildsocial.Pass:
    """One pass of the death-loop asks: posts for loopers with a mate in
    reach, expires for the live asks that end now, and one yes per live
    ask that has none yet.

    loops    name -> deathloop.Loop, the planning pass's death-loop read
    mates    guildsocial.Mate for every member read
    asks     every overseer_guild_ask row; only the deathloop kind is read
    held     name -> why not free (or a set of names): a held looper is not
             asked for, and a held mate is not counted in reach
    answers  the overseer_guild_answer rows; only standing yeses are read
    spoken   names that already said a yes in this same pass (in the
             social pass's replies, which this planner cannot see from
             the recorded rows): such a mate is not counted again
    seated   names seated in a run formed this same pass (the class
             quest parties the bridge just planned): such a mate is not
             counted in reach, named in a post, or drawn as a yes
    """
    held = set(held or ()) | set(seated or ())
    jobs = {}
    for mate in mates or ():
        jobs.setdefault(mate.name, _as_job_member(mate))
    looping = set(loops or ())
    expire = expires(asks, looping, now)
    ending_ids = {ask_id for ask_id, _asker, _line in expire}
    live = {a.asker for a in death_asks(asks) if a.state in LIVE_ASKS}
    recent = _recent_askers(asks, now)
    open_in: dict = {}
    for a in death_asks(asks):
        if a.state in LIVE_ASKS and a.id not in ending_ids:
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
    live_asks = [
        a for a in death_asks(asks) if a.state in LIVE_ASKS and a.id not in ending_ids
    ]
    replies = _replies(live_asks, ending_ids, jobs, looping, answers, held, spoken)
    yes_by_ask = {a.ask_id: a.member for a in answers or () if a.state == YES}
    for reply in replies:
        yes_by_ask[reply.ask_id] = reply.member
    filled = tuple(
        a.id
        for a in sorted(live_asks, key=lambda a: a.id)
        if a.id in yes_by_ask
        and a.asker not in held
        and yes_by_ask[a.id] not in held
    )
    return guildsocial.Pass(
        posts=tuple(posts), expire=expire, replies=replies, filled=filled
    )
