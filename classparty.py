"""A filled class quest ask becomes a party that walks to the objective.

THE ROWS (quadseven/mod-overseer#866). classask.py asks guild chat for help with
a class quest and picks the answerers; this module is what the bridge does once
an ask has them:

  party-up      kind='guild', target = the asker, who leads:
                `party-up <helper> [<helper> ...]` (1 to 4 names), source
                `classask`. Answered `applied` with result {"phase":"formed"}, or
                `error` with {"phase":"refused","why":<literal>} (the detail
                column reads "refused: see result").
  party-walk    kind='job', target = the leader: `party-walk creature:<spawn id>
                [max:<yards>]`. The leader walks as `walk-to-spawn` does with the
                party following, and is held at the objective.
  party-disband kind='guild', target = the leader: ends the party and gives back
                every follow and strategy change. `unchanged` when there is no
                party, so a late one is harmless. The module ends a party itself
                after 30 minutes, a death, a member lost or an instance.

THE FLOW, one task per party (the bridge's _run_class_party):

  form      write party-up, read its answer. FORMED goes on. A refusal that names
            a helper (HELPER) takes that helper's yes back, bars the helper from
            this ask and ends the attempt: the ask's next pass picks another.
            A refusal that names the leader (LEADER) waits LEADER_WAIT_SECONDS
            and writes the row again. UNSUPPORTED (a worldserver before the
            verbs, or one with Overseer.PartyWalk.Enable off) keeps today's
            behaviour: the ask runs out unformed and nothing is asked again for
            guildroute.WALK_UNSUPPORTED_SECONDS. After MAX_FAILURES failures of
            one ask the ask is given up and its asker does not ask again for
            GIVE_UP_COOLDOWN_MINUTES.
  walk      write party-walk to the objective spawn (classquest.objective_spot).
  watch     read the asker's quest log every WATCH_SECONDS: complete (or handed
            in, or gone) ends it, so does its ask no longer being live or
            PARTY_SECONDS passing.
  disband   write party-disband and mark the answerers' yes rows seated (or
            withdrawn when no party formed). The members are free again the
            moment the PartyRun leaves the Board.

THE HOLD. A member is held out of the dungeon passes and the guild jobs only
while a PartyRun with its name is on the Board: from the pass that decides to
form the party to its disband, and not a moment after a refusal.

FAMILY MEMBERS are never touched: classask answerers come from the guild
members free of every campaign (guildrun.why_not holds a family member), and the
module refuses a family member of an armed campaign by itself.

PURE: rows in, decisions out. No MySQL, no clock of its own, no sleeping.
"""

from __future__ import annotations

import json
import re
import types
from dataclasses import dataclass, field

import classask
import classquest
import guildroute
import guildrun
from guildsocial import LIVE_ASKS, PASSING, YES

SOURCE = "classask"
UP, WALK, DISBAND = "party-up", "party-walk", "party-disband"
MAX_HELPERS = 4

# Seconds the bridge reads a party-up row's answer before it counts as lost.
UP_FOLLOW_SECONDS = 90.0
# Seconds to wait before writing party-up again after the leader was refused.
LEADER_WAIT_SECONDS = 60.0
# Failures of one ask (a helper refused, the leader refused, no answer) before
# the ask is given up, and how long its asker then does not ask again.
MAX_FAILURES = 3
GIVE_UP_COOLDOWN_MINUTES = 30
# After a party ends with its quest not done, the asker waits this long.
ENDED_COOLDOWN_MINUTES = classask.ASK_COOLDOWN_MINUTES
# A party stands this long at most: the module's own ceiling is 1800 seconds.
PARTY_SECONDS = 1680.0
# Seconds between reads of the quest log while the party works.
WATCH_SECONDS = 30.0
# An ask with some yes but not all waits this long from its post for the rest.
PARTIAL_WAIT_MINUTES = 3.0

# What an older worldserver says to a row it cannot parse, and what the module
# says with the switch off.
OLD_PARSER = "malformed request"
OLD_JOB_MODE = "unknown job mode"
SWITCH_OFF = "Overseer.PartyWalk.Enable is off"

# Verdicts on a party-up row.
FORMED = "formed"
HELPER = "helper"
LEADER = "leader"
UNSUPPORTED = "unsupported"
BAD = "bad"
WAITING = "waiting"

# Where the asker's quest stands.
COMPLETE = "complete"
INCOMPLETE = "incomplete"
GONE = "gone"
# character_queststatus.status of a quest ready to hand in.
STATUS_COMPLETE = 1

_HELPER_REFUSAL = re.compile(r"^'([^']+)'")
_LEADER_REFUSALS = (
    "the leader ",
    "the realm already has",
    "the core would not form a party",
)


# --- the answers --------------------------------------------------------------------


@dataclass(frozen=True)
class UpAnswer:
    """One reading of a party-up row: `state`, the sentence for the log and,
    for a refusal that names a helper, the helper."""

    state: str
    said: str = ""
    name: str = ""


def _body(result) -> dict:
    if isinstance(result, dict):
        return result
    try:
        parsed = json.loads(result or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def unsupported(detail, why="") -> bool:
    """True when an answer says the worldserver does not carry the party verbs:
    the older parser's words, or the switch off."""
    for text in (str(detail or ""), str(why or "")):
        if text.startswith((OLD_PARSER, OLD_JOB_MODE)) or text == SWITCH_OFF:
            return True
    return False


def judge_up(leader, status, detail, result) -> UpAnswer:
    """What one party-up row's status, detail and result say."""
    status = str(status or "").strip().lower()
    detail = str(detail or "").strip()
    body = _body(result)
    why = str(body.get("why") or "").strip()
    if status in ("pending", "claimed", "verifying", ""):
        return UpAnswer(WAITING, "%s's party-up row has not been answered" % leader)
    if status == "applied":
        if str(body.get("phase") or "").lower() == "formed":
            return UpAnswer(FORMED, "%s's party is formed" % leader)
        return UpAnswer(
            BAD, "%s's party-up row read 'applied' without a formed party" % leader
        )
    if unsupported(detail, why):
        return UpAnswer(
            UNSUPPORTED,
            "this worldserver answered the party row as %r, so it cannot seat a "
            "quest party yet" % (why or detail),
        )
    reason = why or detail or "the world refused the party and said nothing about why"
    named = _HELPER_REFUSAL.match(reason)
    if named:
        return UpAnswer(
            HELPER, "%s's party was refused: %s" % (leader, reason), named.group(1)
        )
    if reason.startswith(_LEADER_REFUSALS):
        return UpAnswer(LEADER, "%s's party was refused: %s" % (leader, reason))
    return UpAnswer(BAD, "%s's party was refused: %s" % (leader, reason))


def walk_unsupported(said) -> bool:
    """True when a walk's sentence carries the older worldserver's answer."""
    return OLD_PARSER in str(said or "") or OLD_JOB_MODE in str(said or "")


def quest_state(status) -> str:
    """Where a quest stands from its character_queststatus status: None (no row:
    handed in, abandoned or never taken), 1 complete, anything else under way."""
    if status is None:
        return GONE
    return COMPLETE if int(status) == STATUS_COMPLETE else INCOMPLETE


def objective_done(state) -> bool:
    return state in (COMPLETE, GONE)


# --- the commands -------------------------------------------------------------------


def up_command(helpers) -> str:
    return "%s %s" % (UP, " ".join(helpers))


def walk_command(spot, cap) -> str:
    return "%s creature:%d%s" % (WALK, int(spot.guid), guildroute.errand_cap_word(cap))


# --- one party ------------------------------------------------------------------------


@dataclass
class PartyRun:
    """One class quest party from the pass that decided it to its disband.

    `answers` is member name -> the id of its yes row. `formed_at` and
    `deadline` are on the bridge's monotonic clock, set when the module said
    formed."""

    ask_id: int
    leader: str
    helpers: tuple
    quest: int
    title: str
    spot: object
    answers: dict = field(default_factory=dict)
    formed_at: float | None = None
    deadline: float | None = None

    def names(self) -> tuple:
        return (self.leader,) + tuple(self.helpers)

    def helper_named(self, name) -> str:
        """The helper of this party whose name is `name` in any case, "" when
        none is (the module names a helper as the row wrote it)."""
        low = str(name).lower()
        return next((h for h in self.helpers if h.lower() == low), "")

    def form(self, now) -> None:
        self.formed_at = now
        self.deadline = now + PARTY_SECONDS

    def left(self, now) -> float:
        """Seconds before the party's clock runs out."""
        return PARTY_SECONDS if self.deadline is None else self.deadline - now


class Board:
    """What the class quest parties have done, kept in memory by the bridge.

    A restart forgets it: the module's own parties end by themselves within 30
    minutes, and the ask rows run out. Times are seconds on one monotonic
    clock."""

    def __init__(self):
        self.parties: dict = {}
        self._refused: dict = {}
        self._failures: dict = {}
        self._cooling: dict = {}
        self._unsupported_until = 0.0

    def runs(self) -> list:
        return list(self.parties.values())

    def names(self) -> set:
        return classask.held_names(self.parties.values())

    def partied_asks(self) -> set:
        return {p.ask_id for p in self.parties.values()}

    def begin(self, run: PartyRun) -> None:
        self.parties[run.leader] = run

    def end(self, run: PartyRun, now, done) -> None:
        """The party is over: its members are free at once. A party that formed
        and did not finish its quest keeps its asker from asking again for
        ENDED_COOLDOWN_MINUTES."""
        self.parties.pop(run.leader, None)
        if run.formed_at is not None and not done:
            self.cool(run.leader, now, ENDED_COOLDOWN_MINUTES)

    def refuse(self, ask_id, name) -> None:
        self._refused.setdefault(int(ask_id), set()).add(str(name))

    def refused(self) -> dict:
        return {k: frozenset(v) for k, v in self._refused.items()}

    def fail(self, ask_id) -> int:
        """One more failure for this ask; the count so far."""
        self._failures[int(ask_id)] = self._failures.get(int(ask_id), 0) + 1
        return self._failures[int(ask_id)]

    def failures(self, ask_id) -> int:
        return self._failures.get(int(ask_id), 0)

    def exhausted(self, ask_id) -> bool:
        return self.failures(ask_id) >= MAX_FAILURES

    def cool(self, name, now, minutes) -> None:
        self._cooling[str(name)] = now + float(minutes) * 60.0

    def cooling(self, now) -> set:
        self._cooling = {n: t for n, t in self._cooling.items() if t > now}
        return set(self._cooling)

    def seats(self, now) -> bool:
        """False while this worldserver is known not to carry the party verbs."""
        return now >= self._unsupported_until

    def mark_unsupported(self, now) -> None:
        self._unsupported_until = now + guildroute.WALK_UNSUPPORTED_SECONDS

    def prune(self, live_ids) -> None:
        """Forget what was kept for asks that are over."""
        keep = {int(i) for i in live_ids} | self.partied_asks()
        for table in (self._refused, self._failures):
            for ask_id in [i for i in table if i not in keep]:
                del table[ask_id]


# --- who forms a party now --------------------------------------------------------------


def _minutes_since(when, now) -> float:
    if when is None or now is None:
        return 1e9
    return (now - when).total_seconds() / 60.0


def _at(mate):
    """What classquest.objective_spot reads of a member: where it stands."""
    return types.SimpleNamespace(
        map_id=mate.member.map_id,
        x=0.0 if mate.x is None else mate.x,
        y=0.0 if mate.y is None else mate.y,
    )


def _standing(ask, yes_by_ask, gone, free, taken) -> list:
    """The yes rows of one ask that stand: the member is free, its yes was not
    taken back this pass and it is on no other party."""
    return [
        y
        for y in yes_by_ask.get(ask.id, [])
        if y.id not in gone and y.member in free and y.member not in taken
    ]


def _ready(ask, standing, now) -> bool:
    wanted = max(1, len(ask.roles_needed))
    if len(standing) >= wanted:
        return True
    return (
        bool(standing) and _minutes_since(ask.created_at, now) >= PARTIAL_WAIT_MINUTES
    )


def plan_starts(asks, answers, quest_pass, helps, free, board, now, clock, book=None):
    """The parties to form now: one PartyRun per quest ask that has its answers
    (all it asked for, or some of them once PARTIAL_WAIT_MINUTES have passed),
    a leader and helpers free to it, and an objective spawn to walk to.

    asks         every overseer_guild_ask row; answers the answer rows
    quest_pass   the guildsocial.Pass classask.plan_pass made: asks it ends and
                 yeses it takes back are left alone
    helps        classquest.Help rows; free  name -> guildsocial.Mate
    board        the Board; clock  its monotonic now; now  the database's clock
    """
    if not board.seats(clock):
        return ()
    ended = {a for a, _who, _line in quest_pass.expire} | set(quest_pass.cancel)
    gone = set(quest_pass.withdraw)
    by_member = {}
    for h in helps:
        by_member.setdefault(h.member, h)
    yes_by_ask: dict = {}
    for a in answers or ():
        if a.state == YES:
            yes_by_ask.setdefault(a.ask_id, []).append(a)
    taken = set(board.names())
    starts = []
    for ask in sorted(classask.quest_asks(asks), key=lambda a: a.id):
        if (
            ask.state not in LIVE_ASKS
            or ask.id in ended
            or ask.asker in board.parties
            or ask.asker in taken
            or ask.asker not in free
            or board.exhausted(ask.id)
        ):
            continue
        need = by_member.get(ask.asker)
        if need is None or need.move.quest != classask.quest_of(ask):
            continue
        standing = _standing(ask, yes_by_ask, gone, free, taken)
        if not _ready(ask, standing, now):
            continue
        spot = classquest.objective_spot(book, need.move, _at(free[ask.asker]))
        if spot is None:
            continue
        chosen = standing[:MAX_HELPERS]
        run = PartyRun(
            ask.id,
            ask.asker,
            tuple(y.member for y in chosen),
            need.move.quest,
            need.move.title,
            spot,
            {y.member: y.id for y in chosen},
        )
        taken.update(run.names())
        starts.append(run)
    return tuple(starts)


def ask_held(held, board) -> dict:
    """`held` as classask.plan_pass should read it: a member of a party that is
    up is free to its ask though the core now reads it as grouped (or fighting).
    Any other reason (offline, dead, in an instance) still holds it, and the ask
    is then cancelled, which ends the party."""
    mine = board.names()
    return {
        n: why
        for n, why in held.items()
        if not (n in mine and (why == guildrun.GROUPED or why in PASSING))
    }
