"""What each family member is doing, said beside their name in the game.

infra#3334. Five clients each stream one member, and on every one of them the
party frames name the other four and say nothing about what they are doing.
The Family tab and the Watch wall answer that on a web page; nobody watching a
stream is looking at a web page.

TWO SOURCES, AND THE SPLIT IS THE WHOLE DESIGN. Five of these states are
already sitting in the client: UnitIsConnected, UnitIsDeadOrGhost,
UnitIsVisible (the client is not tracking the unit at all, so it is a zone away
or far outside sight), UnitAffectingCombat, and UnitInRange - the ~40 yard
check Blizzard_RaidUI uses. They are observed rather than reported, true within
a frame of being true, and they keep working when every process behind this one
is down. PRECEDENCE below is that list, in the order it is asked.

The rest is only knowable here. Whether a character is ON TASK, walking an
errand, inside a run, or being driven by nothing lives in `overseer_roster` and
`overseer_dungeon_run`, and no client can see a database. That half is composed
here into one short line and pushed to the clients; the addon splits it and
renders it.

THE MODULE OWNS THE WORDS, THE ADDON OWNS THE COLOURS. Same seam as
watchwall.py (infra#2597): a module that returns "#ff4d2e" has decided what the
palette is, and a Lua file that decides what "on task" means has put judgement
somewhere no test can reach.

WHAT THE ADDON MUST MIRROR, and why that is safe. The precedence between the
five local facts has to run inside the client, because the facts do, and there
is no way to move it here. So it is written here as PRECEDENCE, written there
as LOCAL_RULES, and tests/test_partystatus.py reads the Lua as text and fails
if the two orders differ - the guard test_jobs.py puts on mod_overseer.cpp and
test_frames.py puts on map_server.py.

DEGRADING IS THE NORMAL CASE, not the failure case. Nothing runs the sender by
default, so an addon installed on its own shows the five local states and says
nothing else. It must never fill that silence with a guess: a member standing
quietly with the party and a member nobody is driving look identical from
inside the client, and only one of them is a problem.

THREE THINGS THIS DELIBERATELY DOES NOT SAY:

1. Health. The party frame draws a health bar six pixels away, and a second
   opinion about it would disagree the moment one of them rounded.
2. The dungeon PHASE. DungeonRunPhase (Gathering, Barrier, Enter, Clearing,
   ...) lives in world-thread memory in mod_overseer.cpp, is not persisted and
   is not queryable. `overseer_dungeon_run.state` is active or ended, so that
   is what DUNGEON means here and no more.
3. Held on the spot. The module logs a refusal when it will not walk a
   character off a drop, guarded by an in-process bool no table records. There
   is nothing to read, so there is no code for it: a state that can never
   arrive teaches a viewer to expect a warning that will not come.

HOW IT IS CARRIED. `overseer_command` already has `kind='chat'` and
`channel='party'`, and mod_overseer.cpp's DoChat broadcasts that to the group
as a packet it builds itself, so `build_push` emits ready-made rows and nothing
new is needed server-side. Two properties make party chat survivable for
machine traffic: the payload is TAB separated, which relay.is_addon_traffic
already recognises so it never reaches Discord, and the addon filters its own
lines out of the chat frames so nothing appears on the stream. The better route
is the same packet sent with LANG_ADDON, which no chat frame renders at all -
a few lines in DoChat, in quadseven/mod-overseer, and not this change. The
addon accepts both.

PURE MODULE: rows in, lines out. No MySQL, no client, and no clock of its own
unless one is not handed to it.
"""
from __future__ import annotations

from datetime import datetime

import agenda
import jobs

# --- the vocabulary ----------------------------------------------------------

# What the client can see for itself, in the order it is asked. First true one
# wins.
#
# AWAY OUTRANKS FIGHTING, the one place this disagrees with watchwall.py. That
# is a health-and-danger view, so a fight is the most urgent thing on it. This
# is a has-anyone-drifted-off view: a member the client cannot even see is the
# exact failure it exists to catch, and a drifted member is nearly always
# fighting something, so combat first would hide it behind the most ordinary
# word in the game. APART sits BELOW fighting for the opposite reason - forty
# yards during a fight is a caster standing where a caster stands, and a label
# that lit up on every pull would be ignored inside a day.
OFFLINE = "offline"
DEAD = "dead"
AWAY = "away"
FIGHTING = "fighting"
APART = "apart"
PRECEDENCE = (OFFLINE, DEAD, AWAY, FIGHTING, APART)

# The words the addon shows for those five. Here rather than in the Lua so
# every sentence a viewer reads is written in one file, and so the suite can
# hold the Lua to them.
LOCAL_LABELS = {
    OFFLINE: "offline",
    DEAD: "dead",
    AWAY: "away",
    FIGHTING: "fighting",
    APART: "apart",
}

# What only this side knows. TASK is the operator's "on task": something is
# driving this character and it is not one of the more specific cases below.
TASK = "task"
TRAVEL = "travel"
DUNGEON = "dungeon"
STALLED = "stalled"
IDLE = "idle"
PUSHED = (TASK, TRAVEL, DUNGEON, STALLED, IDLE)

CODES = PRECEDENCE + PUSHED

# --- the wire ----------------------------------------------------------------

# The prefix, which is also the addon-message prefix, matching the "DC"
# convention mod-dungeon-clear already uses in this worldserver. Nothing in
# OllamaChat.BlacklistCommands starts with it, and that list is prefix-matched
# on a word boundary, so it cannot be caught by accident.
PREFIX = "OVSR"

# Carried in the line rather than assumed. The addon and the server are
# deployed by completely different means - a file copied onto a Windows box
# against a container roll - so they will be out of step routinely, and an
# addon reading a version it does not know must fall back to the local states.
VERSION = "1"

# TAB, load-bearing twice over. relay.is_addon_traffic already treats any C0
# byte as machine traffic and keeps the row out of Discord and the thought
# store, so this needs no change there; and the client will not transmit a tab
# in chat, so no player can forge one of these lines by typing.
SEP = "\t"

# Two caps for one column: overseer_command.command is VARCHAR(255), and MySQL
# truncates rather than refusing. A line trimmed by the database arrives with
# its last field cut in half.
MAX_LABEL_CHARS = 14
MAX_LINE_CHARS = 240

# How long a pushed state may go unrefreshed before the addon drops back to the
# local states alone.
#
# NINETY SECONDS, from the sender's poll budget rather than taste.
# mod_overseer.cpp drains overseer_command every two seconds, so a sender
# running every thirty gets three attempts inside this window. Shorter and an
# ordinary worldserver hiccup blanks every label; longer and a dead sender
# leaves "on task" under a character who stopped an hour ago.
PUSH_STALE_SECONDS = 90


def _short(text) -> str:
    """A label trimmed to what fits beside a name, with no ellipsis.

    An ellipsis costs three of the fourteen characters to say something was
    cut: "guild busine" is read correctly and "guild bus..." is not read at all.
    """
    return str(text or "").strip()[:MAX_LABEL_CHARS]


def _clean(text) -> str:
    """A field with the separator taken out of it.

    A label carrying a tab would silently become two fields and shift every
    later member onto the wrong name. Replaced rather than refused: a label is
    cosmetic and a shifted line is a lie.
    """
    return str(text or "").replace(SEP, " ").replace("\n", " ").strip()


def line(members: list[dict]) -> str:
    """One line carrying the whole family's pushed state.

    ONE LINE FOR FIVE MEMBERS, not five lines. Five rows is five packets, five
    chat-frame filters and five chances for a partial update to render a family
    half in one state and half in another. At roughly twenty-five bytes a
    member the whole roster fits inside one 255-byte command with room to
    spare, and a viewer either sees the new picture or the old one.

    Members that would push the line past MAX_LINE_CHARS are dropped from the
    end rather than shortened further. A truncated line is not parseable; a
    short one is.
    """
    out = [PREFIX, VERSION]
    for member in members:
        fields = [_clean(member.get("name")), _clean(member.get("code")),
                  _short(_clean(member.get("label")))]
        if len(SEP.join(out + fields)) > MAX_LINE_CHARS:
            break
        out.extend(fields)
    return SEP.join(out)


def parse(text) -> list[dict] | None:
    """A line back into members, or None if it is not one of ours.

    None and [] are different answers and both are real. None means "not our
    traffic" - somebody else's addon, a person talking, a version this build
    does not know - and the caller must leave whatever it is showing alone. []
    means "ours, and it says nobody", which should blank the labels.

    A trailing partial triple is dropped rather than guessed at. It only
    happens when something truncated the line, and the fields that did arrive
    are still correctly paired with their names.
    """
    raw = str(text or "")
    if SEP not in raw:
        return None
    fields = raw.split(SEP)
    if len(fields) < 2 or fields[0] != PREFIX or fields[1] != VERSION:
        return None
    body = fields[2:]
    members = []
    for i in range(0, len(body) - 2, 3):
        name, code, label = body[i], body[i + 1], body[i + 2]
        if not name or code not in CODES:
            continue
        members.append({"name": name, "code": code, "label": label})
    return members


# --- the decision ------------------------------------------------------------

def decide(facts: dict, pushed: dict | None = None) -> dict:
    """What one character's label says, given what is known about them.

    THIS IS THE FUNCTION THE ADDON MIRRORS, and the only one it does. `facts`
    is what the client observed; `pushed` is the last line that arrived for
    this character, or None when none has or the last one went stale.

    Local first, always. A pushed state is at best seconds old and was composed
    from a snapshot; "he is dead" observed in this frame outranks "he is
    questing" recorded a minute ago, and a character who is offline is not
    doing any of the things the roster says.

    An unknown fact is a fact that is NOT true. The defaults are all the
    reassuring direction on purpose: a caller that hands in nothing gets the
    pushed state or silence, never five alarms about a member it failed to ask
    about.
    """
    if not facts.get("connected", True):
        return {"code": OFFLINE, "label": LOCAL_LABELS[OFFLINE]}
    if facts.get("dead"):
        return {"code": DEAD, "label": LOCAL_LABELS[DEAD]}
    if not facts.get("visible", True):
        return {"code": AWAY, "label": LOCAL_LABELS[AWAY]}
    if facts.get("combat"):
        return {"code": FIGHTING, "label": LOCAL_LABELS[FIGHTING]}
    if not facts.get("in_range", True):
        return {"code": APART, "label": LOCAL_LABELS[APART]}
    if pushed and pushed.get("code") in PUSHED:
        return {"code": pushed["code"], "label": _short(pushed.get("label"))}
    return {"code": "", "label": ""}


# --- composing the pushed half -----------------------------------------------

def _job_label(job: str) -> str:
    """The job column said in the space beside a name.

    jobs.MODES are already phrases a person says out loud, so they are printed
    as stored rather than translated into a second vocabulary.

    THE QUALIFIED DUNGEON JOB IS STRIPPED. mod_overseer.cpp's IsDungeonJob
    accepts `dungeon:deadmines` as well as bare `dungeon`, and jobs.py has no
    vocabulary for the qualified form at all. Printing it raw would spend the
    whole label on a keyword nobody needs beside a name.
    """
    text = str(job or "").strip() or jobs.DEFAULT
    return _short(text.split(":", 1)[0])


def _in_run(run: dict | None, roster: list[str]) -> set:
    """Who the active run counts as being in it.

    `members` is stamped at the moment the party is all inside, so it is empty
    for the whole approach - the reset, the walk to the staging point, the
    gather at the door. An empty column during an active run means "not stamped
    yet", not "nobody", and reading it the other way would say IDLE at five
    characters walking to a dungeon together.
    """
    if run is None:
        return set()
    stamped = [n.strip() for n in str(run.get("members") or "").split(",")
               if n.strip()]
    return set(stamped) if stamped else set(roster)


def build_push(roster_rows: list[dict], run_rows: list[dict],
               event_rows: list[dict], now: datetime | None = None) -> dict:
    """The pushed half of every label, plus the command rows that carry it.

    Reads what the agenda banner already reads, through agenda's own functions,
    so the party frames and the web page cannot come to different conclusions
    about the same family. Nothing new is queried and no table is added.

    THE ORDER OF THESE BRANCHES IS THE DESIGN:

    1. Not on the enabled roster - nothing is driving this character, and a
       disabled row is not a member for this purpose. IDLE, which is the
       operator's "not doing anything".
    2. The family is stalled  - nothing has happened anywhere in twenty
       minutes. It outranks every busy-looking state below BECAUSE they look
       busy: a run whose row still reads active and a job that is still set are
       exactly what a stuck family looks like from the tables, and
       quadseven/mod-overseer#171 is that state going unnoticed.
    3. Inside a run           - the most specific and most time-bound thing the
       family can be doing.
    4. Walking an errand      - a travel aim is per-character by design, and
       the column IS the status: the module clears it on arrival and on giving
       up, so non-empty means still walking.
    5. On task                - the ordinary case, named by the job.

    Stalled is family-wide and is therefore said about everyone, including a
    character standing somewhere blameless. The stall is a fact about the
    party, the operator is looking at five streams, and telling only one of
    them would make it look like one member's problem.
    """
    now = now or datetime.utcnow()
    orders = agenda.standing_orders(roster_rows)
    roster = orders["roster"]
    run = agenda.active_run(run_rows)
    is_stalled = agenda.stalled(agenda.last_movement(event_rows), now)
    inside = _in_run(run, roster)
    aims = {t["name"]: str(t.get("target") or "").strip()
            for t in orders["travel"]}
    job = _job_label(orders["job"])

    members = []
    for name in roster:
        if is_stalled:
            code, label = STALLED, "stalled"
        elif name in inside:
            code, label = DUNGEON, "dungeon"
        elif aims.get(name):
            code, label = TRAVEL, "walking"
        else:
            code, label = TASK, job
        members.append({"name": name, "code": code, "label": _short(label)})

    text = line(members)
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "stale_after_seconds": PUSH_STALE_SECONDS,
        "members": members,
        "line": text,
        "commands": commands(text, orders["leader"]),
    }


def commands(text: str, speaker: str | None) -> list[dict]:
    """The overseer_command rows that put one line in front of five clients.

    Party chat, spoken by the leader, because DoChat builds that packet itself
    and broadcasts it to the whole group: one row reaches all five sessions and
    none of them has to be picked as a special case.

    NO SPEAKER, NO ROWS. DoChat answers "not in a group" and marks the row an
    error, so enqueueing anyway would fill the queue with failures rather than
    reporting the honest fact that there is nobody to speak.

    Returned as rows rather than inserted: this module holds no connection and
    never will, and whoever inserts them owns the schedule and the retry.
    """
    if not speaker or not text:
        return []
    return [{
        "target_name": speaker,
        "command": text,
        "kind": "chat",
        "channel": "party",
    }]
