"""The decree console: what the overseer may order, and what came back.

Pure module, the same seam as core.py, panel.py and agenda.py (infra#2597):
rows go in and a fully decided payload comes out. map_server.py fetches rows
and serves bytes; index.html sets textContent. No SQL, no HTTP, no LLM below
this line, which is what lets every judgement on the only WRITE surface in
the redesign be held by the stdlib suite with no database and no browser.

THREE JUDGEMENTS LIVE HERE AND TWO OF THEM ARE THE REASON THE FILE EXISTS.

ONE: THE UNWIRED JOB. jobs.MODES names twelve modes; jobs.IMPLEMENTED names
the ones that change behaviour. Setting any of the others is not a no-op, and
that is the whole trap: it stands the quest drive DOWN and puts nothing in
its place, so the family stops questing and starts doing nothing at all. A
console that let a person pick a mode and said nothing would have them watch
an empty stream and blame the encoder. The sentence that says so is
jobs.describe, and nothing here keeps a second copy of which modes are wired:
IMPLEMENTED is read, never restated, so wiring a mode in mod-overseer changes
this console in the same commit that changes the module.

TWO: `delivered` IS NOT SUCCESS HERE. core.COMMAND_SUCCESS_STATUSES contains
it, and correctly so for the bridge, where it means "not an error" and every
row has to land in some bucket. On a console it means something far narrower:
the row was HANDED OVER and nothing whatsoever was verified. Two engineers
read it as "applied", in writing, all night, while the same command changed
nothing on the same character twice (overseer_command rows 4049 and 4184; the
whole story is in tests/test_command_outcome.py). So this module draws its own
line and SUCCESS_STATUSES is narrower than core's on purpose: `applied` is the
only status that has ever meant the character changed.

THREE: WHAT THIS CONSOLE MAY ACTUALLY WRITE, which is mostly a refusal. See
SECTIONS. A control that cannot reach the world is drawn disabled with the
reason printed beside it, because a button that silently does nothing is the
exact failure this epic is named after.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import agenda
import bonds
import chat
import core  # noqa: F401 - named by SUCCESS_STATUSES' comment, and by the suite
import jobs
import professions
import travel

# --- what this page can and cannot write -------------------------------------
#
# ONE write path exists from this page to the world: POST /api/chat. It
# persists the operator's words, asks the inner voice, and queues at most one
# allowlisted playerbot command (voice.VOCABULARY) as an overseer_command row.
# That is enough to speak to a character and nothing else.
#
# A job, a travel aim and a campaign cap are all COLUMNS ON overseer_roster.
# No HTTP path writes that table. Routing one of them through the chat box
# would not set the column either: the inner voice would pick some unrelated
# playerbot command, the page would report an order, and the column would be
# untouched. That is a mechanism reporting success while doing nothing, which
# is the failure this whole epic is named after, so those three controls are
# declared unreachable HERE - in the module the suite can hold - and the page
# draws them disabled with the reason beside them.

CHAT = "chat"       # reachable: POST /api/chat
NOWHERE = ""        # no write path from this page

JOB = "job"
CAMPAIGN = "campaign"
TRAVEL = "travel"
WILL = "will"


@dataclass(frozen=True)
class Section:
    """One card on the console, and whether its controls can reach the world."""

    key: str
    title: str
    writes: str
    why_not: str
    instead: str


SECTIONS = (
    Section(
        key=JOB,
        title="Standing job",
        writes=NOWHERE,
        why_not=(
            "This page cannot write overseer_roster.job. The job column is "
            "set by one kind='job' command row per enabled character, written "
            "by the bridge when it hears a job order; no HTTP endpoint writes "
            "it."
        ),
        instead=(
            "Say the mode in the overseer's own channel - the explicit form "
            "is \"job <mode>\" - and jobs.parse_order reads it there."
        ),
    ),
    Section(
        key=CAMPAIGN,
        title="Campaign counter",
        writes=NOWHERE,
        why_not=(
            "This page cannot write overseer_roster.dungeon_runs_wanted. "
            "Nothing writes it but a hand on the database; the run "
            "coordinator only ever reads it."
        ),
        instead=(
            "The count below is live and is the leader's own row, which is "
            "the row the coordinator reads."
        ),
    ),
    Section(
        key=TRAVEL,
        title="Send them somewhere",
        writes=NOWHERE,
        why_not=(
            "This page cannot write overseer_roster.travel_npc, and neither "
            "can any other surface. The column is written in exactly one "
            "place in the bridge, by the profession errand planner, for the "
            "character it decided to send. travel.aim_statements - the "
            "function that would aim a chosen character at a chosen role - "
            "is written and called by nothing."
        ),
        instead=(
            "The roles below are the vocabulary that exists. Where the family "
            "is currently aimed is read live from the roster."
        ),
    ),
    Section(
        key=WILL,
        title="The will",
        writes=CHAT,
        why_not="",
        instead="",
    ),
)

_SECTIONS_BY_KEY = {s.key: s for s in SECTIONS}

# What a card says above its refusal. Kept here rather than in the markup for
# the same reason every other sentence on this view is: a label that softened
# to "coming soon" in a stylesheet edit would be a lie nothing tests.
REFUSAL_TAG = "this cannot be sent from here"


def can_send(key: str) -> bool:
    """Whether this card's controls may reach the world at all.

    The page never decides this for itself. It asks the payload, exactly as
    it asks the payload which job modes are wired, so a control cannot be
    enabled on screen by an edit that nothing in the suite reads.
    """
    return _SECTIONS_BY_KEY[key].writes != NOWHERE


# --- the standing job --------------------------------------------------------

WIRED = "wired"
UNWIRED = "unwired"


def job_chips() -> tuple:
    """Every mode the roster will accept, in the order jobs.py names them.

    `state` is WIRED or UNWIRED rather than a colour: which pigment says
    "this one works" is a decision the stylesheet makes, and a module that
    handed the page a hex would be deciding it twice.

    `says` is jobs.describe verbatim, which is also exactly what the bridge
    answers in the overseer's channel when the same mode is set there. One
    sentence, one author: a console that phrased the stand-down warning in
    its own words would be a second copy free to soften.
    """
    return tuple(
        {
            "mode": mode,
            "what": what,
            "state": WIRED if mode in jobs.IMPLEMENTED else UNWIRED,
            "wired": mode in jobs.IMPLEMENTED,
            "says": jobs.describe(mode),
        }
        for mode, what in jobs.MODES.items()
    )


def job_line(mode: str, leader: str | None) -> str:
    """What the roster is set to right now, said once.

    Names the row it was read off, because that is the fact a person acts on:
    the coordinator reads the leader's row, and the crown moves.
    """
    if leader is None:
        return "Nobody is on the roster, so no job is set."
    return ("Set to %s, read off %s's row - which is the row the run "
            "coordinator reads." % (mode, leader))


def job_choice(mode: str) -> dict | None:
    """What picking `mode` would mean, or None if that is not a mode.

    None rather than an exception for the same reason jobs.resolve returns
    None: "that is not a mode" is an ordinary answer on a surface fed by
    people, not a fault.

    `stands_down` is the whole point of this function. An unwired mode is not
    an order that does nothing - it is an order that turns the quest drive OFF
    with nothing replacing it, and a person who is not told that sets the mode,
    watches five characters stand still, and goes looking for a broken stream.
    """
    resolved = jobs.resolve(mode)
    if resolved is None:
        return None
    wired = resolved in jobs.IMPLEMENTED
    return {
        "mode": resolved,
        "wired": wired,
        "state": WIRED if wired else UNWIRED,
        "stands_down": not wired,
        "says": jobs.describe(resolved),
    }


def unwired_modes() -> tuple:
    """The modes that are a name and nothing else, in MODES order."""
    return tuple(m for m in jobs.MODES if m not in jobs.IMPLEMENTED)


# --- the dungeon campaign ----------------------------------------------------

# The one number that stops a campaign rather than shortening it. Not a
# threshold this module invented: mod_overseer.cpp's idle gate asks whether
# done >= wanted before it starts a run at all, so a wanted of 0 is true on
# the first comparison and no run ever begins. The migration's own column
# comment says the same thing in the same words.
CAMPAIGN_STOP = 0


def campaign_view(counter: dict) -> dict:
    """The campaign counter as a console should read it.

    `counter` is agenda.campaign's answer and every judgement in it stays
    agenda's: the leader's row governs because that is the row LoadCampaignCap
    reads, and a higher count elsewhere on the roster is a DISAGREEMENT rather
    than a better number. This adds only the sentences.

    THE DISAGREEMENT IS NOT DECORATION. Leadership is reassigned in world and
    the counter does not travel with the crown, so a campaign can appear to
    restart the moment somebody else takes the lead. Silently reporting the
    maximum would hide exactly that bug behind a number that looks right,
    which is why agenda reports both and why this says so out loud.
    """
    done = int(counter.get("done") or 0)
    wanted = int(counter.get("wanted") or 0)
    by = counter.get("recorded_by")
    disagrees = counter.get("disagrees") or []
    if by is None:
        line = "Nobody is on the roster, so there is no campaign to count."
    else:
        line = "%d of %d runs done, counted on %s's row." % (done, wanted, by)
    if wanted == CAMPAIGN_STOP:
        means = (
            "Wanted is 0, which stops the campaign outright: the coordinator "
            "asks whether done is at least wanted before it starts a run, so "
            "no run begins at all."
        )
    elif counter.get("over"):
        means = (
            "The campaign is over: done has reached wanted, and the "
            "coordinator will not start another run."
        )
    else:
        left = wanted - done
        means = "%d run%s left before the coordinator stops." % (
            left, "" if left == 1 else "s")
    warning = ""
    if disagrees:
        warning = (
            "The crown has moved. %s carr%s a HIGHER count than the leader's, "
            "and the count does not travel with the crown - the row of "
            "whoever was leading when a run closed is the row that was "
            "incremented. The number above is the one that governs, not the "
            "highest one on the roster."
            % (", ".join(disagrees), "ies" if len(disagrees) == 1 else "y")
        )
    return {
        "done": done,
        "wanted": wanted,
        "recorded_by": by,
        "over": bool(counter.get("over")),
        "stopped": wanted == CAMPAIGN_STOP,
        "disagrees": list(disagrees),
        "line": line,
        "means": means,
        "warning": warning,
    }


# --- sending them somewhere --------------------------------------------------

# Always on screen, never behind a hover. travel.py's own docstring is the
# source and says it in capitals: aiming a character at a trainer makes it
# WALK to the trainer and STAND THERE.
TRAVEL_CAVEAT = (
    "Travel, not transaction. An aimed character walks to the nearest one of "
    "these and stands in front of it. Standing in front of a vendor is not "
    "shopping."
)

# What still has no verb behind it once they have arrived. Training is off
# this list on purpose and with a caveat rather than a claim: mod-overseer
# does buy a trade on arrival, but only for a character the profession errand
# planner sent with a plan of its own. Nobody can aim somebody at a trainer
# and have them learn something.
TRAVEL_UNBUILT = (
    "Buying anything from a vendor.",
    "Repairing at a repair NPC.",
    "Signing a guild charter at a petitioner.",
    "Training on arrival for any reason other than the profession errand's "
    "own plan, which is the one transaction that exists and which nothing on "
    "this page can start.",
)


def travel_chips() -> tuple:
    """Every role a character could be aimed at, as travel.py names them.

    Straight off travel.ROLES, never a second list: the keywords are already
    duplicated in C++ and checked line for line by tests/test_travel_npc.py,
    and a third copy in a web page is the one nobody would think to check.
    """
    return tuple(
        {
            "role": role,
            "flag": flag,
            # A whole sentence, and it says the caveat again in the one place
            # a person is looking when they pick a role. travel.describe
            # supplies the half that names the target.
            "says": ("Aiming somebody here walks them to %s and stands them "
                     "in front of it. It does not make them use it."
                     % travel.describe(role)),
        }
        for role, flag in travel.ROLES.items()
    )


def travel_line(aimed) -> str:
    """Where the family is currently aimed, or that nobody is.

    "Nobody is aimed anywhere" is the common case and has to be SAID: an
    empty list under a heading reads as a panel that failed to load.
    """
    aimed = list(aimed)
    if not aimed:
        return "Nobody is aimed anywhere right now."
    return "; ".join(
        "%s is walking to %s" % (a["name"], a["says"]) for a in aimed
    ) + "."


def travel_now(rows: list) -> tuple:
    """Who is currently aimed somewhere, and where.

    Only the rows that actually carry a target. An entry per character with
    "nowhere" against four of them would bury the one that matters.
    """
    aimed = []
    for row in rows or []:
        target = str(row.get("target") or "")
        if travel.is_target(target):
            aimed.append({
                "name": str(row.get("name") or ""),
                "target": target,
                "says": travel.describe(target),
            })
    return tuple(aimed)


# --- the will ----------------------------------------------------------------

WILL_SUBMIT = "Let the family overhear it"

# Who a decree can be aimed at. Two of these are reachable and two are not,
# and the two that are not are listed anyway: the shape of the thing being
# built is part of what an honest console shows, and a chip that says why it
# is dark is worth more than a chip that is missing.
WILL_FAMILY = "family"
WILL_ONE = "one"
WILL_GUILD = "guild"
WILL_FACTION = "faction"

WILL_TARGETS = (
    {
        "id": WILL_FAMILY,
        "label": "the family",
        "reachable": True,
        "needs_name": False,
        "why_not": "",
        "what": (
            "Every one of them hears it and answers in their own words, "
            "oldest first."
        ),
    },
    {
        "id": WILL_ONE,
        "label": "one of them",
        "reachable": True,
        # The one target that cannot be sent until a character is named. A
        # flag rather than the page comparing against the string "one": the
        # page must not hold a second copy of this module's vocabulary.
        "needs_name": True,
        "why_not": "",
        "what": "One character hears it and answers.",
    },
    {
        "id": WILL_GUILD,
        "label": "the guild",
        "reachable": False,
        "needs_name": False,
        "why_not": (
            "The chat path this page speaks through takes ONE character name. "
            "Widening an order to a guild is fanout.py's job and it runs on "
            "the bridge, not here."
        ),
        "what": "",
    },
    {
        "id": WILL_FACTION,
        "label": "the faction",
        "reachable": False,
        "needs_name": False,
        "why_not": (
            "Same reason as the guild, and louder: a faction order is "
            "hundreds of characters, and the one surface that can widen an "
            "order that far bounds it with its own cap."
        ),
        "what": "",
    },
)

# Every way a decree can be refused before it is sent, written here and
# chosen on the page. The page picks between them on a condition it can see
# for itself (is there text, is a character named); it never composes one,
# because a refusal is a sentence about this system and those are authored in
# Python or they drift.
WILL_REFUSALS = {
    "unchosen": "Pick who is meant to overhear it.",
    "empty": "Say something. An empty decree is not a decree.",
    "unnamed": "Name which one of them is meant to hear it.",
    "nobody": "Nobody is on the roster to overhear it.",
}

# Openers, not orders. Every one of these is a thing to SAY; none of them
# tries to be a command, because what the words become is the inner voice's
# decision and a preset that read like a command line would be pretending
# otherwise.
PRESETS = (
    "Rest here a while. Nobody is chasing you.",
    "Look after each other today.",
    "Sell what you cannot carry before you go anywhere else.",
    "Whoever is hurt, say so now.",
    "Keep together. I do not want to lose anybody.",
)

# The chat box's own limit, taken from the module that enforces it rather
# than typed into an HTML attribute where it could drift.
WILL_MAX_CHARS = chat.MAX_MESSAGE


def will_audience(target: str, roster: list, one: str | None = None) -> tuple:
    """Who this decree is put to, in the order they answer.

    OLDEST FIRST, from bonds.speaking_order, which is the family table's own
    answer to who speaks when they all answer at once. The rows arrive
    leader-first because that is what the roster view is for, and delivering
    in that order would put whoever holds the crown today ahead of the
    mother, which is a different family every time the crown moves.
    """
    names = [str(n) for n in (roster or [])]
    if target == WILL_ONE:
        chosen = (one or "").strip()
        return (chosen,) if chosen in names else ()
    if target == WILL_FAMILY:
        return tuple(bonds.speaking_order(names))
    return ()


# --- what came back ----------------------------------------------------------

# THE ONLY STATUS THIS CONSOLE RENDERS AS SUCCESS.
#
# core.COMMAND_SUCCESS_STATUSES is ("delivered", "applied") and is right to
# be: the bridge has to bucket every finished row into good news or bad, and
# `delivered` is not bad news. A console is not a bucket. Here `delivered`
# means the row was handed to the module and NOTHING was read back, which is
# indistinguishable on the row from a command that changed nothing at all -
# which is precisely how the same command read `delivered` twice while
# changing nothing either time. So this set is deliberately narrower than
# core's, and the test that pins it asserts the difference rather than the
# agreement.
SUCCESS_STATUSES = ("applied",)

# The heading sentence of the card, and the one an operator has to read
# before the rows underneath mean anything.
OUTCOME_LEDE = (
    "Every order this console has sent, newest first, with its OUTCOME rather "
    "than its reply. `delivered` means handed over and nothing verified; "
    "`applied` is the only word here that means the character changed."
)

# Said out loud rather than left as an empty box: a blank list under a
# heading reads as a panel that failed to load.
OUTCOME_EMPTY = "Nothing has been sent from this console yet."

# How many of this console's own orders it looks back over. A decree puts one
# row per character on the queue, so a handful of decrees is already a page;
# past that this is history and the thought timeline is the place for it.
OUTCOME_ROWS = 40

VERIFIED = "verified"       # read back, and it holds
UNVERIFIED = "unverified"   # handed over, nothing checked
INERT = "inert"             # accepted, changed nothing
WAITING = "waiting"         # still in flight
FAILED = "failed"           # refused or errored
UNSEEN = "unseen"           # a status this image has never heard of


@dataclass(frozen=True)
class Outcome:
    word: str
    tone: str
    means: str
    evidence: str


OUTCOMES = {
    "pending": Outcome(
        word="queued",
        tone=WAITING,
        means="Written to the queue. No worldserver has picked it up yet.",
        evidence="Nothing yet. The row is waiting to be claimed.",
    ),
    "claimed": Outcome(
        word="claimed",
        tone=WAITING,
        means=(
            "A worldserver has taken the row and has not handed it to the "
            "character yet."
        ),
        evidence="Nothing yet. `claimed_by` names which worldserver holds it.",
    ),
    "delivered": Outcome(
        word="handed over",
        tone=UNVERIFIED,
        means=(
            "The module accepted the row. NOTHING WAS READ BACK, so this says "
            "the order was handed over and nothing whatsoever about the "
            "character."
        ),
        evidence=(
            "There is none. A row that changed the character and a row that "
            "changed nothing both read exactly this."
        ),
    ),
    "verifying": Outcome(
        word="reading back",
        tone=WAITING,
        means=(
            "In flight between the hand-off and the read-back. Not finished, "
            "so neither good news nor bad yet."
        ),
        evidence="The read-back is running. It resolves on its own.",
    ),
    "applied": Outcome(
        word="applied",
        tone=VERIFIED,
        means=(
            "Read back off the character's own live engines after the "
            "hand-off, and they agreed. The only status that has ever meant "
            "the character changed."
        ),
        evidence="`result` on the row carries the lists it was judged against.",
    ),
    "unchanged": Outcome(
        word="changed nothing",
        tone=INERT,
        means=(
            "Accepted, and the live list is exactly what it was. Nothing "
            "failed and nothing happened."
        ),
        evidence=(
            "`result` on the row carries the live lists the verdict was made "
            "against, so the diagnosis needs no second trip to a probe."
        ),
    ),
    "error": Outcome(
        word="refused",
        tone=FAILED,
        means="It did not happen, and the row says why.",
        evidence="`detail` on the row carries the reason.",
    ),
}


def is_success(status: str) -> bool:
    """Whether this console may draw `status` as a success.

    `delivered` is False here and True in core.COMMAND_SUCCESS_STATUSES. That
    is the point of the function existing at all.
    """
    return status in SUCCESS_STATUSES


def outcome_of(status: str) -> Outcome:
    """How to read one status, including one this image has never heard of.

    The worldserver image and this one deploy separately, so a status from a
    newer module is a normal deploy window rather than a bug. It is NAMED
    rather than swallowed, which is the same rule core.report_outcomes keeps
    at the other end of the same table.
    """
    known = OUTCOMES.get(status)
    if known is not None:
        return known
    return Outcome(
        word="status '%s'" % status,
        tone=UNSEEN,
        means=(
            "This page has never heard of that status. The worldserver may be "
            "newer than the site, which is an ordinary deploy window."
        ),
        evidence="Read the row itself.",
    )


def _when(value) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return None if value is None else str(value)


def outcome(row: dict) -> dict:
    """One overseer_command row as a console line.

    The ROW ID is carried on every one of them, never only on the interesting
    ones: it is the whole handle on the evidence, and an operator who has to
    go and find which row a line was about has already lost the round trip
    this view exists to remove.
    """
    status = str(row.get("status") or "")
    read = outcome_of(status)
    detail = str(row.get("detail") or "")
    return {
        "id": int(row.get("id") or 0),
        "name": str(row.get("target_name") or ""),
        "command": str(row.get("command") or ""),
        "kind": str(row.get("kind") or "bot"),
        "status": status,
        "word": read.word,
        "tone": read.tone,
        "success": is_success(status),
        "means": read.means,
        "evidence": read.evidence,
        "detail": detail,
        "when": _when(row.get("created_at")),
    }


def outcomes(rows: list) -> tuple:
    """The command rows as console lines, newest first."""
    lines = [outcome(row) for row in (rows or [])]
    lines.sort(key=lambda o: -o["id"])
    return tuple(lines)


# --- what is stopping them ---------------------------------------------------

def backlog() -> tuple:
    """The honest list of what the family still cannot do.

    DERIVED WHERE IT CAN BE. "Ten of twelve jobs" is counted off jobs.MODES
    and jobs.IMPLEMENTED, so wiring a mode moves the number without anybody
    remembering to edit a sentence; who is owed the family's first trade is
    read off professions.OPEN_ORDER and the assignment table rather than
    typed. The rest are facts about C++ that does not exist, and they carry
    the module whose own docstring says so, so a reader can go and check.
    """
    unwired = unwired_modes()
    first_trade = professions.OPEN_ORDER[0]
    owed_to = next(
        (n for n in professions.ROSTER if first_trade in professions.assigned(n)),
        "",
    )
    return (
        {
            "what": "Nothing crafts.",
            "why": (
                "mod-overseer has no verb that turns a tradeskill into an "
                "item, so a character can be asked for a bag, can agree, and "
                "no bag can ever appear. craftpleas.py says so in its own "
                "docstring rather than routing around it."
            ),
        },
        {
            "what": "%s does not hold %s." % (owed_to or "The family's crafter",
                                              first_trade),
            "why": (
                "The family assigned it: %s is the first trade in the open "
                "order and it is the family's bag problem. The plan has been "
                "written down since the professions module landed and the "
                "family holds none of its assigned trades yet."
                % first_trade
            ),
        },
        {
            "what": "Travel does not transact.",
            "why": (
                "An aimed character walks to the role and stands in front of "
                "it. Buying, repairing and signing a charter have no verb at "
                "all; the one transaction that exists fires only for a "
                "character the profession errand planner sent with a plan."
            ),
        },
        {
            "what": "%d of %d jobs are a name and nothing else."
                    % (len(unwired), len(jobs.MODES)),
            "why": (
                "Setting one of them stands the quest drive down and puts "
                "nothing in its place: %s." % ", ".join(unwired)
            ),
        },
    )


# --- the whole console -------------------------------------------------------

def build_console(roster_rows: list, command_rows: list,
                  now: datetime | None = None) -> dict:
    """Rows in, the console's JSON out.

    roster_rows    overseer_roster, every column agenda reads
    command_rows   recent overseer_command rows, any status
    now            the clock, injectable so the suite can stand still

    BOTH MAY BE EMPTY. A realm whose worldserver predates a table hands in []
    and gets a thinner console, never an exception - the same contract every
    other endpoint on this page keeps.
    """
    now = now or datetime.now()
    standing = agenda.standing_orders(roster_rows)
    mode = standing["job"]
    split = standing["job_split"]
    aimed = travel_now(standing["travel"])
    return {
        "generated_at": _when(now),
        "sections": [
            {
                "key": s.key,
                "title": s.title,
                "can_send": can_send(s.key),
                "why_not": s.why_not,
                "instead": s.instead,
            }
            for s in SECTIONS
        ],
        "refusal_tag": REFUSAL_TAG,
        "job": {
            "section": JOB,
            "standing": mode,
            "leader": standing["leader"],
            "line": job_line(mode, standing["leader"]),
            "chips": list(job_chips()),
            "choice": job_choice(mode),
            "split": split,
            "split_line": agenda.split_sentence(split) if split else "",
        },
        "campaign": dict(campaign_view(standing["campaign"]), section=CAMPAIGN),
        "travel": {
            "section": TRAVEL,
            "caveat": TRAVEL_CAVEAT,
            "chips": list(travel_chips()),
            "aimed": list(aimed),
            "line": travel_line(aimed),
            "unbuilt": list(TRAVEL_UNBUILT),
        },
        "will": {
            "section": WILL,
            "targets": [dict(t) for t in WILL_TARGETS],
            "presets": list(PRESETS),
            "audience": list(will_audience(WILL_FAMILY, standing["roster"])),
            "refusals": dict(WILL_REFUSALS),
            "max_chars": WILL_MAX_CHARS,
            "submit": WILL_SUBMIT,
        },
        "outcomes": list(outcomes(command_rows)),
        "outcome_lede": OUTCOME_LEDE,
        "outcome_empty": OUTCOME_EMPTY,
        "backlog": list(backlog()),
    }
