"""What each streamed character is doing, and what it is waiting for.

WHY THIS EXISTS. The Watch tab showed "in Stormwind" or "inside an instance"
under a live picture. A character standing still for eight minutes looked
exactly like a character that was working, and nobody could tell a hold from a
fault. This module turns facts that already exist into one plain sentence,
"Doing: <what>. Waiting for: <what> (for 4 min).", and into the last few
steps behind it.

TWO KINDS OF SOURCE, CHOSEN BY WHERE THE FACT LIVES.

  tables the site already reads    the roster's job and aim, the module's intent
                                   book (`overseer_family_intent`: who holds the
                                   leader's walk, to where, since when, and the
                                   state of each member). Composed on the site,
                                   every request, with nothing stored.

  reasons that live only in logs   "waits for bag room", "withheld: bags are
                                   near full", "no guest at ...". The bridge
                                   writes these itself, as INFO lines, and
                                   nothing else records them. A `NowTap` on the
                                   bridge's logger classifies those lines and a
                                   bridge loop stores them as steps in
                                   `overseer_now_step`.

THE WORLDSERVER MODULE'S OWN LOG LINES ARE NOT IN THE SECOND KIND. The bridge
cannot read another process's log, so a refused walk or a post-revival hold is
visible here only through what the module publishes in its intent book (the
owner, the aim and how long it has held). A walk that keeps ending and starting
again shows as a count of restarts, which is a fact, instead of a reason, which
would be a guess.

NO REASON IS A VISIBLE ANSWER. When nothing explains a still character the
sentence says "Idle: no errand and no hold found". A blank would read as a
healthy character; a sentence that names the gap makes the gap a bug report.

PURE: strings and numbers in, strings and numbers out. The suite calls it with
no database, no clock and no browser.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import deque
from dataclasses import dataclass

import places

# --------------------------------------------------------------------- storage --

CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_now_step ("
    " id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " subject VARCHAR(24) NOT NULL,"
    " scope ENUM('character','family') NOT NULL,"
    " kind VARCHAR(24) NOT NULL,"
    " doing VARCHAR(200) NOT NULL,"
    " waiting VARCHAR(200) NOT NULL DEFAULT '',"
    " occurrences INT UNSIGNED NOT NULL DEFAULT 1,"
    " first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " PRIMARY KEY (id),"
    " KEY idx_subject (subject, last_seen),"
    " KEY idx_last (last_seen)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)
INSERT_SQL = (
    "INSERT INTO overseer_now_step (subject, scope, kind, doing, waiting) "
    "VALUES (%s, %s, %s, %s, %s)"
)
BUMP_SQL = (
    "UPDATE overseer_now_step SET occurrences = occurrences + 1, last_seen = NOW() "
    "WHERE id = %s"
)
PRUNE_SQL = "DELETE FROM overseer_now_step WHERE last_seen < NOW() - INTERVAL %s HOUR"
READ_SQL = (
    "SELECT subject, scope, kind, doing, waiting, occurrences, "
    "UNIX_TIMESTAMP(first_seen) AS first_at, UNIX_TIMESTAMP(last_seen) AS last_at, "
    "UNIX_TIMESTAMP() AS now_at FROM overseer_now_step "
    "WHERE last_seen > NOW() - INTERVAL %s HOUR ORDER BY last_seen DESC, id DESC "
    "LIMIT 600"
)
KEEP_HOURS = 6
# An identical step seen again inside this window is the same step, bumped.
SAME_STEP_SECONDS = 900
# A step older than this no longer describes what the character is doing now.
FRESH_SECONDS = 600
SHEET_STEPS = 5

# ----------------------------------------------------------------- the log tap --


@dataclass(frozen=True)
class Step:
    subject: str
    scope: str  # "character" or "family"
    kind: str
    doing: str
    waiting: str = ""


# Each rule: pattern over the bridge's INFO message, then how to say it. The
# patterns are anchored on the start of the message so another line that merely
# mentions a name never matches. Every message here is one the bridge writes
# itself (the tests carry a real example of each).
_RULES = (
    (
        re.compile(
            r"^dungeon quests: (?P<s>\w+)'s family waits for bag room; (?P<why>.+)$"
        ),
        "family",
        "bag_room",
        lambda m: (
            "Clearing bag space before the dungeon quests",
            "bag room (" + m["why"] + ")",
        ),
    ),
    (
        re.compile(r"^queue: (?P<s>\w+)'s family: withheld: (?P<why>.+)$"),
        "family",
        "queue_held",
        lambda m: ("Holding the next dungeon run back", m["why"]),
    ),
    (
        re.compile(
            r"^queue: (?P<s>\w+)'s family holds (?P<kw>\S+) while the family's "
            r"sell interlude runs"
        ),
        "family",
        "queue_held",
        lambda m: (
            "Selling before the " + m["kw"] + " run",
            "the sell interlude to finish",
        ),
    ),
    (
        # The record line holds its own "(0%)", and the bridge appends the
        # notes in a second pair: "holds (5 fought, 0 wiped (0%), ...) (six or
        # more empty slots: Zork 6)". A greedy match split them mid-way.
        re.compile(
            r"^pace: (?P<s>\w+)'s family: (?P<dg>.+?) holds "
            r"\((?P<why>[^()]*(?:\([^()]*\)[^()]*)*)\)(?: \((?P<note>.+)\))?$"
        ),
        "family",
        "pace_hold",
        lambda m: (
            "Holding the " + m["dg"] + " run",
            m["why"] + ("; " + m["note"] if m["note"] else ""),
        ),
    ),
    (
        re.compile(r"^standin: (?P<s>\w+)'s family: (?P<why>.+)$"),
        "family",
        "standin",
        lambda m: ("Running short-handed: " + m["why"], ""),
    ),
    (
        re.compile(r"^activity: (?P<s>\w+)'s family waits in town for its campaign"),
        "family",
        "town_wait",
        lambda m: ("Selling in town", "the family's dungeon campaign"),
    ),
    (
        re.compile(
            r"^town slot: (?P<s>\w+)'s campaign waits in town for bag room "
            r"\((?P<short>.+?) short of"
        ),
        "family",
        "town_wait",
        lambda m: (
            "Waiting in town",
            "bag room (" + m["short"] + " short of free slots)",
        ),
    ),
    (
        re.compile(
            r"^town slot: (?P<f>\w+)'s campaign owns the traveller (?P<s>\w+) "
            r"\((?P<what>.+?)\) - town errands wait"
        ),
        "character",
        "town_wait",
        lambda m: ("Held for the campaign", "the campaign to release the traveller"),
    ),
    (
        re.compile(
            r"^town slot: town errand takes the traveller (?P<s>\w+) for '(?P<aim>[^']*)'"
        ),
        "character",
        "town_errand",
        lambda m: ("Walking " + places.walk_words(m["aim"]) + " on a town errand", ""),
    ),
    (
        re.compile(
            r"^equip: (?P<s>\w+) still carries (?P<item>.+?) after (?P<n>\d+) "
            r"equip command\(s\); held until"
        ),
        "character",
        "equip_held",
        lambda m: (
            "Trying to wear " + m["item"],
            "the game to accept it (" + m["n"] + " tries)",
        ),
    ),
    (
        re.compile(
            r"^economy: (?P<n>\d+) carried candidate\(s\) for (?P<s>\w+) but no "
            r"vendor within reach"
        ),
        "character",
        "no_vendor",
        lambda m: ("Carrying things to sell", "a vendor within reach"),
    ),
    (
        re.compile(
            r"^bank bags: (?P<s>\w+) buys bank bag slot .* it waits for a banker"
        ),
        "character",
        "bank_wait",
        lambda m: ("Buying a bank bag slot", "a banker"),
    ),
    (
        re.compile(
            r"^guild social: (?P<s>\w+)'s group waits: (?P<who>.+?) still in combat"
        ),
        "character",
        "group_wait",
        lambda m: ("Forming a dungeon group", m["who"] + " to leave combat"),
    ),
)


def classify(message: str) -> list[Step]:
    """The steps one bridge log line carries, or none."""
    text = str(message or "").strip()
    for pattern, scope, kind, say in _RULES:
        m = pattern.match(text)
        if m:
            doing, waiting = say(m)
            return [Step(m["s"], scope, kind, doing[:200], waiting[:200])]
    return []


class NowTap(logging.Handler):
    """Collects classified steps from the bridge's logger, without I/O.

    A handler that wrote to the database would put a query inside every log
    call on whatever thread logged; this only appends to a bounded deque, and
    the bridge's own loop drains it.
    """

    def __init__(self, maxlen: int = 400):
        super().__init__(level=logging.INFO)
        self._steps: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            steps = classify(record.getMessage())
        except Exception:  # a tap must never break the log call it listens to
            self.handleError(record)
            return
        if steps:
            with self._lock:
                self._steps.extend(steps)

    def drain(self) -> list[Step]:
        with self._lock:
            out = list(self._steps)
            self._steps.clear()
        return out


def intent_steps(prev: dict | None, row: dict) -> list[Step]:
    """The steps a change in the module's intent book represents.

    `prev` and `row` are rows of `overseer_family_intent` as the bridge reads
    them (`current_for` is the seconds the present intent has held). A change
    records what ended and what took over: the second sentence is what the
    world answered to the first. Neither carries a duration, so a loop of the
    same two sentences is one pair of steps with a count, not a stream of rows. The first sighting of a
    row records only what holds now.
    """
    who = str(row.get("leader_name") or "")
    if not who:
        return []
    key = _intent_key(row)
    held = key[0] not in ("", "none")
    if prev is None:
        return [_took(who, row)] if held else []
    # The same walk begun again shows as a shorter age than the last look.
    restarted = key == _intent_key(prev) and _age(row) + 2 < _age(prev)
    if key == _intent_key(prev) and not restarted:
        return []
    out = []
    if _intent_key(prev)[0] not in ("", "none"):
        out.append(
            Step(
                who,
                "character",
                "intent",
                "%s ended %s" % (_owner(prev), _walk_words(prev)),
            )
        )
    if held:
        out.append(_took(who, row))
    return out


def _took(who: str, row: dict) -> Step:
    return Step(
        who, "character", "intent", "%s took over: %s" % (_owner(row), _walk_words(row))
    )


def _age(row: dict) -> int:
    try:
        return int(row.get("current_for") or 0)
    except (TypeError, ValueError):
        return 0


def _intent_key(row: dict) -> tuple:
    return (
        str(row.get("current_kind") or ""),
        str(row.get("current_owner") or ""),
        str(row.get("current_target") or ""),
    )


def _owner(row: dict) -> str:
    owner = str(row.get("current_owner") or "")
    return _OWNER_WORDS.get(owner, owner or "the module")


# --------------------------------------------------------------------- wording --


def aim_words(target: str) -> str:
    """A module aim in words: `trigger:194` is "the way out of Shadowfang
    Keep", `at:0:-3898,-597,5` "the Menethil Harbor docks (Wetlands)"
    (places.aim_place)."""
    return places.aim_place(target)


# Words the module and the bridge use for their own parts, as a reader says
# them: the travel column is the roster column that holds a walk's aim.
_OWNER_WORDS = {
    "travel column": "the errand walk",
    "quest drive": "the quest drive",
    "town trip": "the town trip",
    "dungeon run": "the dungeon run",
}
_REWORD = (
    (
        re.compile(r"walking to trigger (\d+)", re.I),
        lambda m: _cap(m[0], "walking " + places.walk_words("trigger:" + m[1])),
    ),
    (
        re.compile(r"the vendor trip keeps the travel column"),
        lambda m: "the vendor trip goes first and holds the leader's walk",
    ),
    (
        re.compile(r"^(travel column|quest drive|town trip|dungeon run)\b"),
        lambda m: _cap("A", _OWNER_WORDS[m[1]]),
    ),
)


def _cap(like: str, text: str) -> str:
    return text[:1].upper() + text[1:] if like[:1].isupper() else text


def reword(text: str) -> str:
    """A stored step's text with the module's ids and part names said in
    words. Steps are kept KEEP_HOURS and were written by older bridges too,
    so "walking to trigger 194" is named as it is read, not only as new rows
    are written."""
    out = str(text or "")
    for pattern, say in _REWORD:
        out = pattern.sub(say, out)
    return out


def duration_words(seconds) -> str:
    """4 min, 40 s, 2 h 5 min: short, and never a negative."""
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        return "an unknown time"
    if s < 90:
        return "%d s" % s
    if s < 3600:
        return "%d min" % round(s / 60)
    return "%d h %d min" % (s // 3600, (s % 3600) // 60)


_KIND_WORDS = {
    "quest": "working its quests",
    "economy": "walking to {aim} for upkeep",
    "errand": "walking to {aim} on a town errand",
    "respec": "walking to its class trainer to reset talents",
    "training": "walking to {aim} so a member can train",
    "regroup": "holding still for a member walking back",
    "fetch": "walking back for a member held far away",
    "hearth": "heading home to its inn",
    "dungeon": "walking to {aim} for the dungeon run",
    "operator": "following an operator's order to {aim}",
}


def _walk_words(row: dict) -> str:
    kind = str(row.get("current_kind") or "")
    pattern = _KIND_WORDS.get(kind, kind or "nothing")
    walk = places.walk_words(row.get("current_target"))
    return pattern.replace("walking to {aim}", "walking " + walk).format(
        aim=aim_words(row.get("current_target"))
    )


_MEMBER_STATES = {
    "following": ("Following {leader}", "{leader} to move on"),
    "on an errand of its own": ("On an errand of its own", "the errand to finish"),
    "walking back": ("Walking back to {leader}", "to catch up with {leader}"),
    "held too far to walk": (
        "Held where it stands, too far to walk back",
        "{leader} to come back for it",
    ),
    "held off a deadly walk": (
        "Held back from a deadly walk",
        "{leader} to find a safer way",
    ),
}


# ------------------------------------------------------------------- composing --


def member_states(rows) -> dict:
    """name -> (leader, state, detail) from every `members_state` column."""
    out = {}
    for r in rows or ():
        leader = str(r.get("leader_name") or "")
        for line in str(r.get("members_state") or "").splitlines():
            parts = line.split("|", 2)
            if len(parts) >= 2 and parts[0].strip():
                out[parts[0].strip()] = (
                    leader,
                    parts[1].strip(),
                    (parts[2] if len(parts) > 2 else "").strip(),
                )
    return out


def build_facts(names, roster, intents, steps, now_at=None) -> dict:
    """name -> the facts `compose` reads, from the three table reads.

    `roster` is a list of overseer_roster rows, `intents` the intent-book rows,
    `steps` the stored steps (READ_SQL rows) and `now_at` the database clock in
    epoch seconds, the same clock the steps' times are read on. Each step is offered to the
    character it names and to every character of the family it names.
    """
    by_name = {str(r.get("name")): r for r in roster or ()}
    families = {}
    for n, r in by_name.items():
        families.setdefault(str(r.get("family") or n), []).append(n)
    leaders = {str(r.get("leader_name")): r for r in intents or ()}
    members = member_states(intents)
    facts = {}
    for n in names:
        facts[n] = {
            "roster": by_name.get(n),
            "intent": leaders.get(n),
            "member": members.get(n),
            "steps": [],
            "now_at": now_at,
        }
    for s in steps or ():
        subject = str(s.get("subject"))
        targets = (
            [subject] if s.get("scope") == "character" else families.get(subject, [])
        )
        for n in targets:
            if n in facts:
                facts[n]["steps"].append(s)
    return facts


def _fresh(steps, now_at):
    return [s for s in steps if now_at - int(s.get("last_at") or 0) <= FRESH_SECONDS]


def _clock(f: dict, steps: list, now_at):
    """The database clock: the argument, else the facts', else a step's."""
    if now_at is None:
        now_at = int(f.get("now_at") or 0)
    if not now_at and steps and steps[0].get("now_at"):
        now_at = int(steps[0]["now_at"])
    return now_at


def _out_of_play(member: dict, f: dict):
    """Doing and waiting for a character who is gone, dead or fighting, else None."""
    if not member.get("present"):
        on = (f.get("roster") or {}).get("enabled", 1)
        return "Logged out", "a login" if on else "being switched on in the roster"
    if member.get("condition") == "dead":
        return "Dead", "a release or a resurrection"
    if member.get("combat"):
        return "Fighting", "the fight to end"
    return None


def _stored_reason(fresh: list, doing: str, waiting: str, since):
    """A reason from a stored step beats a guess from the intent book, when it
    is still being repeated: the bridge writes the step again on every pass."""
    held = [s for s in fresh if s.get("waiting")]
    if not held:
        return doing, waiting, since
    top = held[0]
    return (doing or reword(top["doing"])), reword(top["waiting"]), int(top["first_at"])


def compose(member: dict, facts: dict | None, now_at: int | None = None) -> dict:
    """The sentence and the sheet for one character.

    Returns {"doing", "waiting", "for_s", "line", "steps"}; `for_s` is None
    when there is no clock to quote. Precedence for DOING: logged out, dead,
    fighting, a fresh step the bridge recorded for this character, the module's
    intent (leader) or member state, a fresh family step, the roster's job, and
    last the visible "Idle" answer.
    """
    f = facts or {}
    steps = list(f.get("steps") or ())
    now_at = _clock(f, steps, now_at)
    fresh = _fresh(steps, now_at) if now_at else []
    since = None
    stopped = _out_of_play(member, f)
    if stopped:
        doing, waiting = stopped
    else:
        doing, waiting, since = _live(member, f, fresh, now_at)
        doing, waiting, since = _stored_reason(fresh, doing, waiting, since)
    if not doing:
        doing, waiting, since = "Idle", "no errand and no hold found", None
    elapsed = max(0, now_at - since) if (since is not None and now_at) else None
    return {
        "doing": doing,
        "waiting": waiting,
        "for_s": elapsed,
        "line": _sentence(doing, waiting, elapsed),
        "known": doing != "Idle",
        "steps": sheet(steps, now_at),
    }


def _from_intent(intent: dict, steps, now_at):
    doing = _walk_words(intent)
    doing = doing[:1].upper() + doing[1:]
    age = intent.get("current_for")
    since = (now_at - int(age)) if (age is not None and now_at) else None
    restarts = _restarts(steps, now_at)
    if restarts >= 3:
        why = "a way there; the walk has ended and restarted %d times" % restarts
        return doing, why, _first_restart(steps, now_at) or since
    return doing, "to get there", since


def _from_step(step: dict):
    return reword(step["doing"]), reword(step.get("waiting")), int(step["first_at"])


def _from_member_state(state):
    leader, st, detail = state
    said = _MEMBER_STATES.get(st)
    if not said:
        return "In state '%s' with %s" % (st, leader), "", None
    doing = said[0].format(leader=leader)
    if detail:
        doing += " (" + _detail_words(detail) + ")"
    return doing, said[1].format(leader=leader), None


def _from_job(roster: dict):
    job = str(roster.get("job") or "")
    if job.startswith("dungeon:"):
        done = roster.get("dungeon_runs_done")
        wanted = roster.get("dungeon_runs_wanted")
        run = " (run %d of %d)" % (int(done) + 1, int(wanted)) if wanted else ""
        return "On the " + job.split(":", 1)[1] + " dungeon job" + run, "", None
    if job and job != "quest":
        return "On the '" + job + "' job", "", None
    return "", "", None


def _live(member, f, fresh, now_at):
    """Doing, waiting, since for a character in the world and not fighting."""
    intent = f.get("intent")
    if intent and str(intent.get("current_kind") or "") not in ("", "none"):
        return _from_intent(intent, f.get("steps") or (), now_at)
    for scope in ("character", None, "family"):
        if scope is None:
            if f.get("member"):
                return _from_member_state(f["member"])
            continue
        mine = [s for s in fresh if s.get("scope") == scope]
        if mine:
            return _from_step(mine[0])
    return _from_job(f.get("roster") or {})


def _detail_words(detail: str) -> str:
    d = str(detail).strip()
    return d + " yards behind" if d.isdigit() else d


def _restarts(steps, now_at, window=900) -> int:
    n = 0
    for s in steps:
        if s.get("kind") == "intent" and " took over: " in str(s.get("doing")):
            if not now_at or now_at - int(s.get("last_at") or 0) <= window:
                n += int(s.get("occurrences") or 1)
    return n


def _first_restart(steps, now_at, window=900):
    firsts = [
        int(s["first_at"])
        for s in steps
        if s.get("kind") == "intent"
        and " took over: " in str(s.get("doing"))
        and (not now_at or now_at - int(s.get("last_at") or 0) <= window)
    ]
    return min(firsts) if firsts else None


def _sentence(doing: str, waiting: str, elapsed) -> str:
    if doing == "Idle":
        return "Idle: " + waiting + "."
    if not waiting:
        return "Doing: %s. Waiting for: nothing it reports." % doing
    tail = "" if elapsed is None else " (for %s)" % duration_words(elapsed)
    return "Doing: %s. Waiting for: %s%s." % (doing, waiting, tail)


def sheet(steps, now_at: int) -> list[dict]:
    """The last few steps, newest first, each with a clock and how long ago."""
    out = []
    for s in steps[:SHEET_STEPS]:
        text = reword(s.get("doing"))
        if s.get("waiting"):
            text += ": waiting for " + reword(s["waiting"])
        last = int(s.get("last_at") or 0)
        out.append(
            {
                "at": last,
                "ago_s": max(0, now_at - last) if now_at else None,
                "times": int(s.get("occurrences") or 1),
                "text": text,
            }
        )
    return out


def unavailable() -> dict:
    """What a tile says when the step feed could not be read at all."""
    return {
        "doing": "Unknown",
        "waiting": "the status feed, which did not answer",
        "for_s": None,
        "line": "Doing: unknown. Waiting for: the status feed, which did not answer.",
        "known": False,
        "steps": [],
    }
