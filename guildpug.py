"""Pick-up groups: a guild group short a tank or healer recruits one (#591).

WHY THIS EXISTS. The guilds' raid plan stands (no respeccing): their planned
tanks and healers are not at every level band yet, so an ask in guild chat
(guildsocial, #568) can draw a full set of damage dealers and still have no
real tank or healer. A player in that spot asks the server. So does the
asker here: after LOOK_AFTER_MINUTES it says "LF healer for Deadmines, 4/5" in
the faction's public channel (mod-overseer's `lfg` chat channel:
LookingForGroup, else its zone's General), and a random bot of the same side
that plays the seat answers.

WHEN TO LOOK. An open dungeon ask whose asker is free, at least
LOOK_AFTER_MINUTES old, whose yeses fill every seat but a real tank and/or a
real healer (guildsocial.seats_so_far: the same seating `seat` does). One call
per ask (the call table's unique ask id).

WHO ANSWERS. A random bot (the bridge reads overseer_snapshot, is_bot = 1, in
no guild or another guild) that is:

  free     guildrun.why_not: online, out of an instance, alive, out of combat,
           not grouped, not a family member, not in a guild run;
  real     its spent talents play the seat, and it is dressed for it
           (guildsocial.can_take: Member.plays plus tank_ready or covered);
  on side  the race of the guild's side (guildrun.faction_of);
  in band  the door fits its level (guildrun.fitting_doors) and it is within
           guildrun.BAND_SPREAD of the asker;
  near     on the door's continent, and the run is worth more than what it is
           doing: guildsocial.XP_BAND less its activity and the walk, as the
           social layer weighs a guildmate.

The best answers first: the most worth, then the level nearest the asker's,
then the name.

WHEN NOBODY ANSWERS (`silence`). On wow-dev on 2026-10-05 Bonkers called for
a healer for Ragefire Chasm and a tank and healer for Wailing Caverns ten
times from 06:14 to 08:04 UTC, and no pug ever answered. The bridge read no
random bot at all: of the realm's 2,069 random bot characters none stood
between level 8 and 49, online or not. The 880 made that day level from 1
(the realm's natural start) and had reached level 7 in at most five hours of
play; the rest are 50 to 60. The qualification itself works: on the same
pass's live read, 8 Horde random bots qualified to tank Blackrock Depths and
5 to heal it. Nothing said so, because a pass with no call and no join logs
nothing. So each called ask nobody answers carries a Silence: how many random
bots were read and the commonest reasons each could not answer, and the
bridge logs it whenever the reasons change. It answers at least ANSWER_AFTER_MINUTES after the call, by a
whisper to the asker ("I can heal Deadmines, inv"), one pug an ask a pass, and
the asker tells the guild ("Got a healer from LFG, Thrall's coming."). The
answer is an overseer_guild_answer row with stance `pug`, so the social layer
seats it, withdraws it when the pug is no longer free, and forms the run as
it forms any other: the tank leads, and the finder row names the pug
(`pug <name>`), which mod-overseer's finder-run takes outside the guild.

Off (GUILD_PUGS off): nothing here runs and the social layer is unchanged.

PURE: rows in, a PugPass out. The bridge reads, writes and says the lines.
"""

from __future__ import annotations

import os
import zlib
from dataclasses import dataclass

import guildrun
import guildsocial

ENV_SWITCH = "GUILD_PUGS"
SOURCE = "overseer:guildpug"
# mod-overseer's chat channel for the faction's public channel.
CHANNEL = "lfg"

LOOK_AFTER_MINUTES = 5
ANSWER_AFTER_MINUTES = 1
PUGS_PER_ASK_PER_PASS = 1

TANK, HEALER = guildsocial.TANK, guildsocial.HEALER
# The seats a pug is called for, in the order they are filled.
PUG_SEATS = (TANK, HEALER)

CALL_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_guild_pug_call ("
    " id INT NOT NULL AUTO_INCREMENT,"
    " ask_id INT NOT NULL,"
    " asker VARCHAR(12) NOT NULL,"
    " seats VARCHAR(32) NOT NULL DEFAULT '',"
    " channel VARCHAR(16) NOT NULL DEFAULT 'lfg',"
    " said VARCHAR(255) NOT NULL DEFAULT '',"
    " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " PRIMARY KEY (id), UNIQUE KEY uq_ask (ask_id)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)
# The answer table learns the pug stance; the run table, who was a pug.
ANSWER_STANCE_SQL = (
    "ALTER TABLE overseer_guild_answer "
    "MODIFY COLUMN stance ENUM('need','help','pug') NOT NULL"
)
RUN_PUGS_COLUMN_SQL = (
    "ALTER TABLE overseer_guild_run "
    "ADD COLUMN pugs VARCHAR(40) NOT NULL DEFAULT '' AFTER proposer"
)
RUN_PUGS_SQL = "UPDATE overseer_guild_run SET pugs = %s WHERE id = %s"
# The calls of the asks still in play.
CALLS_SQL = (
    "SELECT c.ask_id, c.asker, c.seats, c.said, c.created_at "
    "FROM overseer_guild_pug_call c "
    "JOIN overseer_guild_ask a ON a.id = c.ask_id "
    "WHERE a.state IN ('open', 'filled')"
)
# One call per ask: a second pass that read an older table writes nothing.
INSERT_CALL_SQL = (
    "INSERT IGNORE INTO overseer_guild_pug_call (ask_id, asker, seats, channel, "
    "said, created_at) VALUES (%s, %s, %s, %s, %s, NOW())"
)


def enabled(environ=None) -> bool:
    """On unless GUILD_PUGS says off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


# --- the rows -----------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    """An asker's call for a pug: written once, said in the public channel."""

    ask_id: int
    asker: str
    seats: tuple
    said: str
    created_at: object = None


@dataclass(frozen=True)
class Join:
    """A pug's yes: an answer row (stance pug), the pug's whisper to the
    asker, and the asker's line in guild chat."""

    ask_id: int
    member: str
    role: str
    said: str
    asker: str
    told_guild: str


@dataclass(frozen=True)
class Silence:
    """A called ask whose seat no random bot answered this pass, and why:
    how many random bots were read and the commonest reasons each could not."""

    ask_id: int
    asker: str
    seat: str
    place: str
    read: int
    reasons: tuple = ()  # ((why, count), ...), commonest first

    @property
    def line(self) -> str:
        head = "nobody answers %s's call for a %s for %s (ask %d)" % (
            self.asker,
            self.seat,
            self.place,
            self.ask_id,
        )
        if not self.read:
            return head + ": no random bot is online in its level range"
        return "%s: %d random bot(s) read, %s" % (
            head,
            self.read,
            ", ".join("%d %s" % (n, why) for why, n in self.reasons),
        )


@dataclass(frozen=True)
class PugPass:
    calls: tuple = ()
    joins: tuple = ()
    silences: tuple = ()


def call_from_row(row: dict) -> Call:
    return Call(
        ask_id=int(row["ask_id"]),
        asker=str(row.get("asker") or ""),
        seats=guildsocial.roles_of(row.get("seats")),
        said=str(row.get("said") or ""),
        created_at=row.get("created_at"),
    )


def _minutes_since(when, now) -> float:
    if when is None or now is None:
        return -1.0
    return (now - when).total_seconds() / 60.0


# --- when to look --------------------------------------------------------------


def short_seats(ask, answers: list, free: dict) -> tuple:
    """The tank and healer seats still empty when every other seat is filled
    by the asker and its yeses, tank first; () when anything else is short
    (a guild group fills its damage seats first) or nothing is."""
    sofar = guildsocial.seats_so_far(ask, answers, free)
    if sofar is None:
        return ()
    seats, damage = sofar
    if len(damage) < 3:
        return ()
    return tuple(seat for seat in PUG_SEATS if seats[seat] is None)


def _live(ask) -> bool:
    return ask.state == guildsocial.OPEN and ask.kind == guildsocial.KIND_DUNGEON


def watching(asks: list, calls: dict, answers: list, now) -> list:
    """The live asks a pug may be read for: open and old enough to call,
    already called, or holding a pug's yes (a filled ask too, so its pug is
    not withdrawn while the run waits for the realm's spacing). The bridge reads random bots only when
    this is not empty, in the level range of their doors."""
    pugged = {
        a.ask_id
        for a in answers
        if a.stance == guildsocial.PUG and a.state == guildsocial.YES
    }
    return [
        a
        for a in asks
        if a.state in guildsocial.LIVE_ASKS
        and a.kind == guildsocial.KIND_DUNGEON
        and (
            a.id in calls
            or a.id in pugged
            or (_live(a) and _minutes_since(a.created_at, now) >= LOOK_AFTER_MINUTES)
        )
    ]


def levels_to_read(asks: list, doors: dict) -> tuple | None:
    """(lowest, highest) level a pug for these asks could be, or None."""
    spans = [
        (min(d.finder_floor, d.floor), d.ceiling)
        for d in (doors.get(a.target) for a in asks)
        if d is not None
    ]
    if not spans:
        return None
    return min(s[0] for s in spans), max(s[1] for s in spans)


# --- who qualifies --------------------------------------------------------------


def why_not_pug(
    mate,
    seat: str,
    door,
    asker_level: int,
    faction: str,
    guild: str,
    entrances: dict,
    busy=frozenset(),
    family=frozenset(),
) -> str:
    """Why this random bot cannot answer for the seat, or ""."""
    member = mate.member
    why = guildrun.why_not(member, set(busy), set(), set(family))
    if why:
        return why
    if member.guild == guild:
        return "a guildmate, who answers in guild chat"
    if not faction or guildrun.faction_of([member]) != faction:
        return "the other side"
    if not guildsocial.can_take(member, seat):
        return "does not play the %s seat" % seat
    if not guildrun.fitting_doors([member.level], [door], faction):
        return "outside the door's band"
    if abs(int(member.level) - int(asker_level)) > guildrun.BAND_SPREAD:
        return "too far from the asker's level"
    spot = (entrances or {}).get(str(door.map_id))
    if spot and int(spot.get("map", -1)) != int(member.map_id):
        return "on another continent"
    if worth(mate, door, entrances) <= 0:
        return "too far to walk for it"
    return ""


def worth(mate, door, entrances: dict) -> float:
    """What the run is worth to a pug: its level's experience, less what it
    is doing and the walk (guildsocial.worth with XP_BAND)."""
    return guildsocial.worth(mate, door, guildsocial.XP_BAND, entrances)


# How many reasons a Silence names.
SILENCE_REASONS = 3


def silence(
    ask,
    seat: str,
    door,
    pugs: list,
    asker_level: int,
    faction: str,
    entrances: dict,
    busy=frozenset(),
    family=frozenset(),
) -> Silence:
    """Why no random bot of `pugs` answers this ask's seat: each one's
    why_not_pug, counted, the commonest first."""
    tally: dict = {}
    for m in pugs:
        why = why_not_pug(
            m, seat, door, asker_level, faction, ask.guild, entrances, busy, family
        )
        if why:
            tally[why] = tally.get(why, 0) + 1
    reasons = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    return Silence(
        ask.id,
        ask.asker,
        seat,
        guildsocial.short_place(door.place),
        len(pugs),
        tuple(reasons[:SILENCE_REASONS]),
    )


def best_pug(
    pugs: list,
    seat: str,
    door,
    asker_level: int,
    faction: str,
    guild: str,
    entrances: dict,
    busy=frozenset(),
    family=frozenset(),
):
    """The random bot that answers for the seat, or None: the most worth,
    then the level nearest the asker's, then the name."""
    ranked = sorted(
        (
            (
                -worth(m, door, entrances),
                abs(int(m.member.level) - int(asker_level)),
                m.name,
                m,
            )
            for m in pugs
            if not why_not_pug(
                m, seat, door, asker_level, faction, guild, entrances, busy, family
            )
        ),
        key=lambda r: r[:3],
    )
    return ranked[0][3] if ranked else None


# --- the words ------------------------------------------------------------------


def _pick(options: tuple, *keys) -> str:
    seed = zlib.crc32("|".join(str(k) for k in keys).encode("utf-8"))
    return options[seed % len(options)]


def seats_words(seats) -> str:
    """("tank", "healer") -> "tank and healer"."""
    return " and ".join(seats)


_CALL = (
    "LF {seats} for {place}, {have}/5",
    "LF{n}M {place}, need {seats}. {have}/5",
    "{place}: LF {seats}, {have}/5 and ready to go",
    "Need {seats} for {place}, {have}/5, pst",
)
_ANSWER = {
    TANK: (
        "I can tank {place}, inv",
        "Tank here, inv me for {place}",
        "Saw your LF, I'll tank. Inv?",
    ),
    HEALER: (
        "I can heal {place}, inv",
        "Healer here, inv me for {place}",
        "Saw your LF, I'll heal. Inv?",
    ),
}
_TOLD = (
    "Got a {seat} from LFG, {pug}'s coming along.",
    "Found a {seat} in LFG: {pug}.",
    "{pug} answered in LFG, they'll {verb} for us.",
)
_VERB = {TANK: "tank", HEALER: "heal"}


def call_line(asker: str, door, seats: tuple) -> str:
    have = 5 - len(seats)
    template = _pick(_CALL, asker, door.keyword, ",".join(seats))
    return guildsocial._fit(
        template.format(
            seats=seats_words(seats),
            place=guildsocial.short_place(door.place),
            have=have,
            n=len(seats),
        ),
        255,
    )


def answer_line(pug: str, seat: str, door) -> str:
    template = _pick(_ANSWER[seat], pug, door.keyword)
    return guildsocial._fit(
        template.format(place=guildsocial.short_place(door.place)), 255
    )


def told_line(asker: str, pug: str, seat: str) -> str:
    template = _pick(_TOLD, asker, pug, seat)
    return guildsocial._fit(
        template.format(seat=seat, pug=pug, verb=_VERB.get(seat, seat)), 255
    )


# --- one pass ---------------------------------------------------------------------


def _answers_now(answers: list, social) -> list:
    """The answers as they stand after the social pass: its withdrawals out,
    its new yeses in (ids below zero, never written)."""
    gone = set(social.withdraw)
    out = [a for a in answers if a.id not in gone]
    for n, reply in enumerate(social.replies, start=1):
        out.append(
            guildsocial.Answer(
                id=-n,
                ask_id=reply.ask_id,
                member=reply.member,
                role=reply.role,
                stance=reply.stance,
                said=reply.said,
                state=guildsocial.YES,
            )
        )
    return out


def _closing(social) -> set:
    """Asks the social pass ends, fills or forms this pass."""
    out = {ask_id for ask_id, _a, _l in social.expire}
    out |= set(social.cancel) | set(social.filled)
    if social.form is not None:
        out.add(social.form.ask.id)
    return out


def _spoken(answers: list) -> set:
    return {
        a.member
        for a in answers
        if a.stance == guildsocial.PUG and a.state == guildsocial.YES
    }


def plan(
    social,
    asks: list,
    answers: list,
    calls: dict,
    free: dict,
    pugs: list,
    doors: dict,
    factions: dict,
    entrances: dict,
    now,
    busy=frozenset(),
    family=frozenset(),
) -> PugPass:
    """One pass, after the social layer's (`social`, a guildsocial.Pass).

    asks      Ask rows (the live ones); calls: ask id -> Call
    answers   Answer rows for them, the pugs' included
    free      name -> guildrun.Member for every member free now, the pug
              answerers included (the social pass's `free`)
    pugs      Mates for the random bots read this pass
    factions  guild -> its side
    """
    closing = _closing(social)
    current = _answers_now(answers, social)
    spoken = _spoken(current)
    by_ask: dict = {}
    for answer in current:
        by_ask.setdefault(answer.ask_id, []).append(answer)
    new_calls, joins, silences = [], [], []
    for ask in sorted(asks, key=lambda a: a.id):
        if not _live(ask) or ask.id in closing:
            continue
        door = doors.get(ask.target)
        asker = free.get(ask.asker)
        if door is None or asker is None:
            continue
        short = short_seats(ask, by_ask.get(ask.id, []), free)
        if not short:
            continue
        call = calls.get(ask.id)
        if call is None:
            if _minutes_since(ask.created_at, now) >= LOOK_AFTER_MINUTES:
                new_calls.append(
                    Call(ask.id, ask.asker, short, call_line(ask.asker, door, short))
                )
            continue
        if _minutes_since(call.created_at, now) < ANSWER_AFTER_MINUTES:
            continue
        for seat in short[:PUGS_PER_ASK_PER_PASS]:
            open_pugs = [m for m in pugs if m.name not in spoken]
            faction = factions.get(ask.guild, "")
            pug = best_pug(
                open_pugs,
                seat,
                door,
                asker.level,
                faction,
                ask.guild,
                entrances,
                busy,
                family,
            )
            if pug is None:
                silences.append(
                    silence(
                        ask,
                        seat,
                        door,
                        open_pugs,
                        asker.level,
                        faction,
                        entrances,
                        busy,
                        family,
                    )
                )
                continue
            spoken.add(pug.name)
            joins.append(
                Join(
                    ask_id=ask.id,
                    member=pug.name,
                    role=seat,
                    said=answer_line(pug.name, seat, door),
                    asker=ask.asker,
                    told_guild=told_line(ask.asker, pug.name, seat),
                )
            )
    return PugPass(calls=tuple(new_calls), joins=tuple(joins), silences=tuple(silences))


def pug_tail(pugs) -> str:
    """What the finder row adds for a run's pugs (mod-overseer's
    `finder-run ... pug <name>`): nothing when it has none."""
    return "".join(" pug %s" % name for name in pugs)


def factions(mates: list, guilds) -> dict:
    """guild -> its side, from its own members only (a pug's guild, if any,
    is not one of these)."""
    return {
        g: guildrun.faction_of([m.member for m in mates if m.member.guild == g])
        for g in guilds
    }


def pug_mates(rows: list, answers: list, busy, family) -> tuple:
    """(every random bot read as a Mate, the free ones holding a pug's yes,
    held name -> why for the others holding one). A pug in combat is waited
    out as a guildmate is (guildsocial.PASSING)."""
    holding = {
        a.member
        for a in answers
        if a.stance == guildsocial.PUG and a.state == guildsocial.YES
    }
    everyone, answered, held = [], [], {}
    for row in rows:
        mate = guildsocial.mate_from_row(row)
        if mate is None:
            continue
        everyone.append(mate)
        if mate.name not in holding:
            continue
        answered.append(mate)
        why = guildrun.why_not(mate.member, set(busy), set(), set(family))
        if why:
            held[mate.name] = why
    return everyone, answered, held
