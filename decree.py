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

THREE: WHAT THIS CONSOLE MAY ACTUALLY WRITE, and exactly what each order
becomes. See SECTIONS for the four cards and `plan_order` for the rows and
columns any one of them turns into. Three of them wrote nothing at all until
infra#3345 and said so; they write now, and the same rule holds either way: a
control either reaches the world or is drawn disabled with the reason printed
beside it, because a button that silently does nothing is the exact failure
this epic is named after.
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
# TWO write paths exist from this page to the world.
#
# POST /api/chat persists the operator's words, asks the inner voice, and
# queues at most one allowlisted playerbot command (voice.VOCABULARY) as an
# overseer_command row. That is how the will is spoken and it is the only
# thing it can do.
#
# POST /api/decree carries the other three cards. A job, a travel aim and a
# campaign cap were all declared unreachable here for the whole of infra#2597,
# because nothing but a hand on the database wrote them - the mechanism was
# proved by an operator hand-writing those rows on a live realm, which is what
# infra#3345 wired a button to. Routing any of them through the chat box would still
# be wrong and the old comment was right about why: the inner voice would pick
# some unrelated playerbot command, the page would report an order, and the
# column would be untouched. So they get their own endpoint, with every
# judgement about what an order becomes held HERE, in the module the suite can
# hold with no database and no browser.
#
# `writes` NAMES THE ROAD, NOT THE PERMISSION. can_send is derived from it, so
# a card cannot become sendable on screen without naming what it writes.

CHAT = "chat"        # POST /api/chat, one character at a time
COMMAND = "command"  # POST /api/decree, one overseer_command row per character
ROSTER = "roster"    # POST /api/decree, one overseer_roster column
NOWHERE = ""         # no write path from this page

JOB = "job"
CAMPAIGN = "campaign"
TRAVEL = "travel"
WILL = "will"


@dataclass(frozen=True)
class Section:
    """One card on the console, and whether its controls can reach the world.

    `does` is the sentence that replaced three refusals. A card that CAN
    reach the world owes the reader the same candour the refusal used to
    give: which table, which column, on whose rows, and what it does not do.
    An operator who has to press a button to find out what it writes is being
    asked to experiment on a live realm.
    """

    key: str
    title: str
    writes: str
    why_not: str
    instead: str
    does: str


SECTIONS = (
    Section(
        key=JOB,
        title="Standing job",
        writes=COMMAND,
        why_not="",
        instead="",
        does=(
            "Writes one kind='job' overseer_command row per ENABLED "
            "character of the family picked above - the same table, row shape and worldserver poller the "
            "bridge uses when it hears a job order in Discord "
            "(bridge._insert_job). No column is set from here: "
            "mod_overseer.cpp's DoJob is what moves overseer_roster.job, and "
            "it needs the character in the world to act on the row. What "
            "came back reads that column afterwards and says whether the "
            "order is in effect."
        ),
    ),
    Section(
        key=CAMPAIGN,
        title="Campaign counter",
        writes=ROSTER,
        why_not="",
        instead="",
        does=(
            "Writes overseer_roster.dungeon_runs_wanted and "
            "dungeon_runs_done on EVERY enabled row of the family picked "
            "above, not only the leader's. "
            "The coordinator reads the leader's row and the count does not "
            "travel with the crown, so a cap set on one row is a campaign "
            "that appears to restart the moment somebody else takes the "
            "lead - which is the disagreement this card already reports."
        ),
    ),
    Section(
        key=TRAVEL,
        title="Send them somewhere",
        writes=ROSTER,
        why_not="",
        instead="",
        does=(
            "Writes overseer_roster.travel_npc for ONE named character, and "
            "only while that column is free - the same WHERE clause the "
            "bridge guards its vendor pass with, widened here to every role, "
            "because a console aim must not erase an errand the profession "
            "planner wrote. Standing somebody down clears the column "
            "outright, which is the one write on this page that removes an "
            "intent rather than replacing one."
        ),
    ),
    Section(
        key=WILL,
        title="The will",
        writes=CHAT,
        why_not="",
        instead="",
        does=(
            "Persists the words, then asks the inner voice once per "
            "character. At most one allowlisted playerbot command is queued "
            "per answer and WHICH one is the voice's decision, not the "
            "operator's - so this is the one card whose order is a "
            "conversation rather than a column."
        ),
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

    `sendable` is the same fact as `wired` said in the vocabulary the send
    button uses, and it is here so the page never compares a mode against a
    list. Its refusal travels with it: a chip a person has picked prints why
    it will not go rather than leaving a dead button to be discovered.
    """
    return tuple(
        {
            "mode": mode,
            "what": what,
            "state": WIRED if mode in jobs.IMPLEMENTED else UNWIRED,
            "wired": mode in jobs.IMPLEMENTED,
            "sendable": mode in jobs.IMPLEMENTED,
            "why_not": "" if mode in jobs.IMPLEMENTED else unwired_refusal(mode),
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
    "Every order this console has sent, newest first, one line per order. "
    "In effect and applied mean the change was read back afterwards: a job order is checked "
    "against the job column it writes, and a bot order against the "
    "character's live strategies. Handed over means the module took the row "
    "and nothing was checked."
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


def ago(then, now: datetime | None) -> str:
    """How long ago, coarse, in words: "just now", "4 hours ago", "11 days ago".

    Written here rather than in the page because a line that says WHEN an
    order was sent is part of the verdict: "handed over" on an order from
    eleven days ago and on one from a minute ago are different findings, and
    the list used to print neither.
    """
    if not isinstance(then, datetime) or not isinstance(now, datetime):
        return "at an unknown time"
    seconds = int((now - then).total_seconds())
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return "%d %s%s ago" % (count, unit, "" if count == 1 else "s")
    return "just now"


# --- reading a job order back ------------------------------------------------
#
# A STOPGAP UNTIL quadseven/mod-overseer#564 lands the read-back in DoJob.
#
# WHY THE SITE READS IT BACK AND NOT THE MODULE. mod_overseer.cpp's DoJob is a
# plain `UPDATE overseer_roster SET job` followed by status `delivered`, so a
# job row is never `applied` and never `unchanged`, whatever it did. Every
# job order this console had ever sent therefore read "NOTHING WAS READ BACK",
# which is true of the row and useless to the operator: the column it writes
# is sitting in overseer_roster, and this console already reads that table.
#
# So a delivered job row is judged against two things the adapter hands in:
# what the target's roster row says NOW, and the newest job row for that
# target from ANY source. The second is what separates "a later order
# replaced it" from "it never took", because the goal loop and the Discord
# bridge write job rows too and this console only lists its own.
HOLDS = "holds"
REPLACED = "replaced"
DID_NOT_TAKE = "did not take"
NO_ROW = "no roster row"

READBACK = {
    HOLDS: Outcome(
        word="in effect",
        tone=VERIFIED,
        means="%(name)s's job column reads %(now)s now, which is what this order set.",
        evidence=(
            "Read off overseer_roster.job for %(name)s just now. The module "
            "itself reports only that it accepted the row."
        ),
    ),
    REPLACED: Outcome(
        word="replaced",
        tone=INERT,
        means=(
            "%(name)s's job reads %(now)s now: a later order (row %(newest)d) "
            "set something else after this one."
        ),
        evidence="Read off overseer_roster.job and the newest job row for %(name)s.",
    ),
    DID_NOT_TAKE: Outcome(
        word="did not take",
        tone=FAILED,
        means=(
            "This is the newest job order for %(name)s, and their job reads "
            "%(now)s rather than %(asked)s. The module accepted the row and the "
            "column did not change."
        ),
        evidence="Read off overseer_roster.job for %(name)s just now.",
    ),
    NO_ROW: Outcome(
        word="changed nothing",
        tone=FAILED,
        means=(
            "%(name)s has no overseer_roster row, so the module's column write "
            "matched nothing even though it reported the row delivered."
        ),
        evidence="No overseer_roster row carries that name.",
    ),
}

# THE ONE REFUSAL EVERY OPERATOR SEES, said in plain words. It is written by
# the worldserver when the target is not logged in at the moment the queue is
# read, which on this realm means a restart or a relog was in progress.
NOT_ONLINE = "target not online"


def _readback(row: dict, roster_jobs: dict, newest_job: dict) -> str | None:
    """Which READBACK verdict a delivered job row earns, or None to leave it.

    None for everything that is not a delivered job row, and for a delivered
    one when the adapter handed in no roster at all: an absent read is not
    evidence, and a thinner console says "handed over" exactly as before.
    """
    if str(row.get("kind") or "") != JOB_KIND:
        return None
    if str(row.get("status") or "") != "delivered" or not roster_jobs:
        return None
    name = str(row.get("target_name") or "")
    if name not in roster_jobs:
        return NO_ROW
    asked = jobs.resolve(str(row.get("command") or "")) or str(row.get("command") or "")
    if roster_jobs[name] == asked:
        return HOLDS
    latest = int(newest_job.get(name) or 0)
    if latest > int(row.get("id") or 0):
        return REPLACED
    return DID_NOT_TAKE


def _verdict(row: dict, read: Outcome, check: str | None, facts: dict) -> str:
    """One plain sentence: did this order work, for this character."""
    name = facts["name"]
    status = str(row.get("status") or "")
    detail = str(row.get("detail") or "")
    if check == HOLDS:
        return "In effect: %s's job reads %s now." % (name, facts["now"])
    if check == REPLACED:
        return "Replaced: a later order set %s to %s." % (name, facts["now"])
    if check == DID_NOT_TAKE:
        return "Did not take: %s's job still reads %s." % (name, facts["now"])
    if check == NO_ROW:
        return "Nothing changed: %s has no roster row." % name
    if status == "error":
        if detail == NOT_ONLINE:
            return ("Did not happen: %s was not logged in when the worldserver "
                    "read the order." % name)
        return "Did not happen for %s: %s." % (name, detail or "no reason given")
    if status == "applied":
        return "Applied: %s changed, read back off the character." % name
    if status == "unchanged":
        return "Nothing changed for %s." % name
    if read.tone == WAITING:
        return "Not picked up yet for %s." % name
    return "Handed over to %s; nothing was checked." % name


def outcome(row: dict, roster_jobs: dict | None = None,
            newest_job: dict | None = None,
            now: datetime | None = None) -> dict:
    """One overseer_command row as a console line.

    The ROW ID is carried on every one of them, never only on the interesting
    ones: it is the whole handle on the evidence, and an operator who has to
    go and find which row a line was about has already lost the round trip
    this view exists to remove.

    `roster_jobs` is {name: job} off overseer_roster and `newest_job` is
    {name: newest job row id, any source}. Both default to empty, and empty
    means "not read", which leaves a delivered job row saying "handed over".
    """
    roster_jobs = roster_jobs or {}
    status = str(row.get("status") or "")
    read = outcome_of(status)
    check = _readback(row, roster_jobs, newest_job or {})
    name = str(row.get("target_name") or "")
    facts = {
        "name": name,
        "now": roster_jobs.get(name, ""),
        "asked": str(row.get("command") or ""),
        "newest": int((newest_job or {}).get(name) or 0),
    }
    if check is not None:
        template = READBACK[check]
        read = Outcome(word=template.word, tone=template.tone,
                       means=template.means % facts,
                       evidence=template.evidence % facts)
    detail = str(row.get("detail") or "")
    return {
        "id": int(row.get("id") or 0),
        "name": name,
        "command": str(row.get("command") or ""),
        "kind": str(row.get("kind") or "bot"),
        "status": status,
        "word": read.word,
        "tone": read.tone,
        # A read-back that holds is the one other thing allowed the success
        # weight: it is the column this order wrote, read off the table after.
        "success": is_success(status) or check == HOLDS,
        "means": read.means,
        "evidence": read.evidence,
        "detail": detail,
        "verdict": _verdict(row, read, check, facts),
        "when": _when(row.get("created_at")),
        "ago": ago(row.get("created_at"), now),
    }


def outcomes(rows: list, roster_jobs: dict | None = None,
             newest_job: dict | None = None,
             now: datetime | None = None) -> tuple:
    """The command rows as console lines, newest first."""
    lines = [outcome(row, roster_jobs, newest_job, now) for row in (rows or [])]
    lines.sort(key=lambda o: -o["id"])
    return tuple(lines)


# --- one decree, one line ----------------------------------------------------
#
# A job order is one row PER CHARACTER, so a single press of the button used
# to fill the list with five identical cards. The operator's question is
# "did the order I gave work", and that is one line with the exceptions named.
_TONE_RANK = (FAILED, INERT, UNSEEN, UNVERIFIED, WAITING, VERIFIED)


def _batch_key(line: dict, row: dict) -> tuple:
    return (line["kind"], line["command"], line["when"],
            str(row.get("source") or ""))


def _batch_verdict(lines: list, command: str, who: str) -> str:
    """The whole order in one sentence, with the exceptions named.

    One exception is said in its own full sentence. Several are grouped by
    what happened to them, so five characters handed the same thing read as
    one clause rather than five copies of it.
    """
    worked = [o for o in lines if o["success"]]
    rest = [o for o in lines if not o["success"]]
    head = "%s for %s" % (command, who)
    if not rest:
        if len(lines) == 1:
            return "%s: %s" % (head, lines[0]["verdict"])
        return "%s: in effect for all %d." % (head, len(lines))
    if len(rest) == 1:
        said = rest[0]["verdict"]
    else:
        groups: dict = {}
        for o in rest:
            label = o["word"] + (" (%s)" % o["detail"] if o["detail"] else "")
            groups.setdefault(label, []).append(o["name"])
        said = "; ".join("%s: %s" % (label, ", ".join(names))
                         for label, names in groups.items()) + "."
    if worked:
        return "%s: in effect for %d of %d. %s" % (
            head, len(worked), len(lines), said)
    return "%s: %s" % (head, said)


def batches(rows: list, lines: tuple, family_of: dict | None = None) -> tuple:
    """The console lines grouped into the orders that were actually given.

    One decree is one group: the same kind and command, written in the same
    second. `family_of` names whose family each character is in, so a batch
    says "for Grug's family" instead of listing five names.
    """
    family_of = family_of or {}
    by_id = {int(r.get("id") or 0): r for r in (rows or [])}
    groups: dict = {}
    for line in lines:
        key = _batch_key(line, by_id.get(line["id"], {}))
        groups.setdefault(key, []).append(line)
    out = []
    for members in groups.values():
        names = [o["name"] for o in members]
        fams = {family_of.get(n, "") for n in names}
        if len(names) > 1 and len(fams) == 1 and "" not in fams:
            who = family_label(fams.pop())
        else:
            who = ", ".join(names)
        tone = min((o["tone"] for o in members),
                   key=lambda t: _TONE_RANK.index(t) if t in _TONE_RANK else 0)
        out.append({
            "id": max(o["id"] for o in members),
            "command": members[0]["command"],
            "kind": members[0]["kind"],
            "who": who,
            "tone": tone,
            "success": all(o["success"] for o in members),
            "ago": members[0]["ago"],
            "when": members[0]["when"],
            "verdict": _batch_verdict(members, members[0]["command"], who),
            "lines": members,
        })
    out.sort(key=lambda b: -b["id"])
    return tuple(out)


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


# --- giving an order ---------------------------------------------------------
#
# THE HALF THAT WAS MISSING. Everything above reads. This decides what an
# order BECOMES, and holds every judgement on the write path: whether a mode
# is a mode, who an order fans out over, whether a campaign number is one the
# column can hold, and the exact rows and column writes it turns into.
# map_server.py reads a body, calls plan_order, and either serialises the
# refusal or runs the writes it was handed. It decides nothing, which is why
# all of this is held by a stdlib suite with no database and no browser.
#
# TWO OF THESE ARE JUDGEMENTS RATHER THAN VALIDATION, and each is argued at
# the function that makes it: an unwired mode is REFUSED here where Discord
# only warns (unwired_refusal), and a travel aim never overwrites a travel aim
# (_plan_travel). Read those before widening either.

# The command kind, matching bridge._insert_job. NOT 'bot': "quest" is not a
# mod-playerbots chat command, so a row handed to PlayerbotAI::HandleCommand
# would be accepted and do nothing.
JOB_KIND = "job"

CAMPAIGN_WANTED = "dungeon_runs_wanted"
CAMPAIGN_DONE = "dungeon_runs_done"
TRAVEL_COLUMN = "travel_npc"

# The column's own ceiling and not a number this module invented: both
# campaign columns are SMALLINT UNSIGNED in mod-overseer's
# 2026_09_02_01_overseer_roster_dungeon_runs.sql. A cap above it is not an
# ambitious campaign, it is an out-of-range error the operator would read as
# the console being broken.
CAMPAIGN_CEILING = 65535

# A restart is to zero and to nothing else. dungeon_runs_done is the
# coordinator's own record of runs that closed, and the migration's comment
# says how a campaign is started again: set it back to 0. A console that let a
# person type any number into it would be offering to forge that record.
CAMPAIGN_RESTART = 0

# What the buttons say. Here rather than in the markup for the same reason
# every other sentence on this view is: a label that drifted to "apply" in a
# markup edit would be a claim nothing tests.
JOB_SUBMIT = "Set the family's job"
CAMPAIGN_SUBMIT = "Set the run cap"
CAMPAIGN_RESTART_LABEL = "Start the count again"
TRAVEL_SUBMIT = "Send them"
TRAVEL_STAND_DOWN = "Stand them down"

# Said on the travel card, because it is the fact that makes a stand-down look
# broken to somebody who does not know it.
TRAVEL_REASSERT = (
    "A profession errand is re-asserted by the bridge on every trade cycle, "
    "so standing down a character who is on one clears the column until the "
    "next pass writes it back. Standing down an aim given from here is final."
)


def unwired_refusal(mode: str) -> str:
    """Why a named but unimplemented mode will not be sent from this page.

    Opens with jobs.describe rather than restating it: the stand-down warning
    has one author, and a second copy here would be free to soften.
    """
    return (
        "%s That is a name and nothing else, so this console will not send "
        "it - one tap is too cheap for an order that stands the family down. "
        "Say \"job %s\" in the overseer's own channel if you mean it anyway."
        % (jobs.describe(mode), mode)
    )


# Every way an order can be refused, authored here and printed verbatim by the
# page. The page never composes one, for the same reason WILL_REFUSALS exists:
# a refusal is a claim about this system, and those are written in Python or
# they drift.
ORDER_REFUSALS = {
    "section": "That is not a card that gives orders on this console.",
    "will": (
        "The will is not sent from here. It goes through the chat path, once "
        "per character, so each of them answers in their own words."
    ),
    "roster": "Nobody is on the roster, so there is nobody to order.",
    "family": (
        "Pick which family this is for. Each family has its own leader, job "
        "and run count, so one order cannot set both."
    ),
    "mode": "That is not a job mode. The modes are: %s." % ", ".join(jobs.MODES),
    "campaign": (
        "Say what the campaign should be: a new cap, a restart, or both."
    ),
    "wanted": "The run cap has to be a whole number of runs.",
    "ceiling": (
        "The run cap has to be between %d and %d. That ceiling is the "
        "column's own - it is SMALLINT UNSIGNED - so anything above it is "
        "refused by the database rather than by this page."
        % (CAMPAIGN_STOP, CAMPAIGN_CEILING)
    ),
    "name": (
        "That is not one of the enabled characters, and only an enabled row "
        "is one the worldserver drives."
    ),
    "role": (
        "That is not somewhere the family can be sent. The roles are: %s - "
        "or a creature entry." % ", ".join(travel.ROLES)
    ),
}


@dataclass(frozen=True)
class Row:
    """One overseer_command row to insert.

    `source` is deliberately not a field: every row this console writes is
    map_server.WEB_SOURCE, and a field would be a second place to spell it.
    """

    target_name: str
    command: str
    kind: str


@dataclass(frozen=True)
class Update:
    """One overseer_roster column write, on one named row.

    `if_free` picks between the two statements the adapter holds: the plain
    one, and the guarded one that declines to overwrite a column already
    carrying something else. A boolean rather than a WHERE clause, because SQL
    is the adapter's half.
    """

    name: str
    column: str
    value: object
    if_free: bool


@dataclass(frozen=True)
class Order:
    """A refusal, or exactly what to write. Never both, and never neither."""

    section: str
    refusal: str
    rows: tuple
    updates: tuple
    says: str

    @property
    def asked(self) -> int:
        """How many writes this is, which is what `changed` is read against."""
        return len(self.rows) + len(self.updates)


def _refuse(section: str, why: str) -> Order:
    return Order(section=section, refusal=why, rows=(), updates=(), says="")


def _plan_job(request: dict, standing: dict) -> Order:
    """One kind='job' row per enabled character, or why not.

    FAMILY-WIDE BY CONSTRUCTION, over the enabled roster in full rather than
    who happens to be online - jobs.py explains why a job cannot differ per
    character and bridge._fetch_enabled_names picks the same set. An offline
    member's row comes back "target not online" on the queue, which is
    visible, rather than being left out of an order meant for everybody.
    """
    raw = request.get("mode")
    mode = jobs.resolve(raw if isinstance(raw, str) else None)
    if mode is None:
        return _refuse(JOB, ORDER_REFUSALS["mode"])
    base_mode = mode.split(":", 1)[0] if mode.startswith("dungeon:") else mode
    if base_mode not in jobs.IMPLEMENTED:
        return _refuse(JOB, unwired_refusal(mode))
    names = list(standing["roster"])
    if not names:
        return _refuse(JOB, ORDER_REFUSALS["roster"])
    return Order(
        section=JOB,
        refusal="",
        rows=tuple(Row(name, mode, JOB_KIND) for name in names),
        updates=(),
        says=jobs.describe(mode),
    )


def _plan_campaign(request: dict, standing: dict) -> Order:
    """The cap, the restart, or both - on every enabled row.

    EVERY ENABLED ROW, not the leader's alone, and campaign_view above is the
    argument for it: the coordinator reads the leader's row, the crown moves
    in world, and the count does not travel with it. Writing all of them is
    the only write that makes the number mean the same thing whoever leads.
    """
    names = list(standing["roster"])
    if not names:
        return _refuse(CAMPAIGN, ORDER_REFUSALS["roster"])
    wanted = request.get("wanted")
    restart = bool(request.get("restart"))
    updates = []
    said = []
    if wanted is not None:
        # bool is an int in Python, so JSON `true` would arrive as a cap of 1
        # and pass every range check. A cap of True is not a cap.
        if isinstance(wanted, bool) or not isinstance(wanted, int):
            return _refuse(CAMPAIGN, ORDER_REFUSALS["wanted"])
        if not CAMPAIGN_STOP <= wanted <= CAMPAIGN_CEILING:
            return _refuse(CAMPAIGN, ORDER_REFUSALS["ceiling"])
        updates.extend(
            Update(name, CAMPAIGN_WANTED, wanted, False) for name in names
        )
        # A cap of 0 is legal and is not a small campaign. campaign_view
        # already owns that sentence; this is the same fact said forwards.
        said.append(
            "the campaign is stopped outright - wanted is 0, and the "
            "coordinator asks whether done is at least wanted before it "
            "starts a run at all"
            if wanted == CAMPAIGN_STOP
            else "the campaign wants %d run%s" % (wanted, "" if wanted == 1 else "s")
        )
    if restart:
        updates.extend(
            Update(name, CAMPAIGN_DONE, CAMPAIGN_RESTART, False) for name in names
        )
        said.append("the count starts again from %d" % CAMPAIGN_RESTART)
    if not updates:
        return _refuse(CAMPAIGN, ORDER_REFUSALS["campaign"])
    return Order(
        section=CAMPAIGN,
        refusal="",
        rows=(),
        updates=tuple(updates),
        says="On every enabled row, %s." % " and ".join(said),
    )


def _plan_travel(request: dict, standing: dict) -> Order:
    """One character aimed at one role, or stood down.

    NOT travel.aim_statements: its second statement clears everybody who was
    not named, which is right for a council that decides where the whole
    family stands and wrong for a console aiming one person. Standing the
    others down is an order in its own right here, and it is given one
    character at a time.

    That function IS called - `trainjob.statements` (trainjob.py) delegates to
    it whole. This comment used to say it "is still called by nothing and
    still should be", which was true when written and stopped being true when
    the trainjob caller landed. A writer of `travel_npc` documented as uncalled
    is a writer nobody audits, and that is exactly what happened: it kept the
    function off the list while its no-target branch cleared the column for
    the entire roster with no `WHERE name` clause (infra#4195).
    """
    names = list(standing["roster"])
    if not names:
        return _refuse(TRAVEL, ORDER_REFUSALS["roster"])
    raw_name = request.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if name not in names:
        return _refuse(TRAVEL, ORDER_REFUSALS["name"])
    raw_role = request.get("role")
    if not isinstance(raw_role, str):
        return _refuse(TRAVEL, ORDER_REFUSALS["role"])
    role = raw_role.strip()
    if role == travel.NONE:
        return Order(
            section=TRAVEL,
            refusal="",
            rows=(),
            updates=(Update(name, TRAVEL_COLUMN, travel.NONE, False),),
            says=(
                "%s stops walking anywhere. Clearing the column does not "
                "fetch them back from wherever they already are." % name
            ),
        )
    target = travel.resolve(role)
    # The width check is travel.py's own and is made here rather than
    # discovered as a silently truncated row - the same discipline
    # travel.aim_statements keeps for the same column.
    if target is None or len(target) > travel.COLUMN_WIDTH:
        return _refuse(TRAVEL, ORDER_REFUSALS["role"])
    return Order(
        section=TRAVEL,
        refusal="",
        rows=(),
        updates=(Update(name, TRAVEL_COLUMN, target, True),),
        says=(
            "%s walks to %s and stands in front of it. Standing in front of "
            "it is not using it." % (name, travel.describe(target))
        ),
    )


# Which card plans which order. A table rather than a chain for the same
# reason map_server's routes are one: an unknown section is a miss, not
# another branch.
PLANNERS = {JOB: _plan_job, CAMPAIGN: _plan_campaign, TRAVEL: _plan_travel}

# The cards whose order fans out over a family and is read off its leader.
# Travel is not one: it names one character, and the name picks the family.
FAMILY_WIDE = (JOB, CAMPAIGN)


def plan_order(request: dict, roster_rows: list) -> Order:
    """One order from the console: a refusal with a reason, or what to write.

    request       the POST body, entirely untrusted
    roster_rows   overseer_roster, the same rows build_console is handed

    THE ROSTER IS READ, NEVER TAKEN FROM THE REQUEST: a stale page carrying
    its own idea of the family would fan an order out over characters the
    worldserver no longer drives.
    """
    section = request.get("section") if isinstance(request.get("section"), str) else ""
    if section == WILL:
        return _refuse(WILL, ORDER_REFUSALS["will"])
    planner = PLANNERS.get(section)
    if planner is None:
        return _refuse(section, ORDER_REFUSALS["section"])
    if section in FAMILY_WIDE:
        # WHICH FAMILY, and never both by default. A job or a campaign cap is
        # read off one leader's row, so an order that fanned out over every
        # enabled row set the Horde's job from a card that described the
        # Alliance's. With more than one family the request has to name one,
        # and the name is matched against the roster, never trusted.
        keys = family_keys(roster_rows)
        asked = request.get("family")
        if isinstance(asked, str) and asked in keys:
            roster_rows = _rows_of(roster_rows, asked)
        elif len(keys) > 1:
            return _refuse(section, ORDER_REFUSALS["family"])
    return planner(request, agenda.standing_orders(roster_rows))


# What came of it, in this module's words. `changed` is rows CHANGED and not
# rows matched: pymysql does not set CLIENT_FOUND_ROWS, so re-asserting a
# value a row already holds reports zero. That is the ordinary shape of the
# same order pressed twice, so it gets a sentence of its own rather than being
# reported as a failure.
ORDER_ALL = "%d of %d writes landed."
ORDER_SOME = (
    "%d of %d writes landed. The rest changed nothing, which on these columns "
    "means the row already carried the value."
)
ORDER_NOTHING = {
    JOB: (
        "No row was written. overseer_command.kind has no 'job' value on this "
        "realm, which needs the worldserver image carrying mod-overseer's SQL."
    ),
    CAMPAIGN: (
        "Nothing changed. Either every enabled row already carried those "
        "numbers, or this realm's overseer_roster predates the campaign "
        "columns."
    ),
    TRAVEL: (
        "Nothing changed. Either they are already walking there, or the "
        "column carries an errand and this console will not erase one. The "
        "live line above says which."
    ),
}


def order_result(order: Order, changed: int) -> dict:
    """What actually landed, said rather than counted at the reader.

    `ok` is deliberately false for an order that changed nothing, including
    the harmless re-assert, and the note is what explains which it was. The
    alternative is a console that reports success for a write the database
    declined, which is the failure this whole view is named after.
    """
    asked = order.asked
    if changed >= asked:
        note = ORDER_ALL % (changed, asked)
    elif changed == 0:
        note = ORDER_NOTHING[order.section]
    else:
        note = ORDER_SOME % (changed, asked)
    return {
        "section": order.section,
        "ok": changed > 0,
        "changed": changed,
        "asked": asked,
        "says": order.says,
        "note": note,
    }


# --- two families --------------------------------------------------------------
#
# overseer_roster carries a `family` column, and the realm now drives two: an
# Alliance five and a Horde five, each with its own leader, its own job and
# its own campaign counter (mod_overseer.cpp reads the LEADER's row, and each
# family has one). Reading the roster as one family picked one of the two
# leaders and printed "read off Grug's row" over ten characters, half of
# whom that row does not govern. So the job and the campaign are read and
# ordered per family, and an order that fans out names the family it is for.

def family_label(key: str) -> str:
    """How a family is named on the page: after the head it is keyed by."""
    return "%s's family" % key if key else "the family"


def _family_key(row: dict) -> str:
    return str(row.get("family") or "")


def family_keys(roster_rows: list) -> list:
    """Every family with at least one enabled row, bonds' own first.

    The family this process was configured for opens first, which is the
    rule /api/family keeps; the rest follow by name so the order is stable.
    """
    keys = {_family_key(r) for r in roster_rows if int(r.get("enabled") or 0)}
    head = bonds.head_of_family()
    own = {_family_key(r) for r in roster_rows if str(r.get("name")) == head}
    return sorted(keys, key=lambda k: (k not in own, k))


def _rows_of(roster_rows: list, key: str) -> list:
    return [r for r in roster_rows if _family_key(r) == key]


def family_views(roster_rows: list) -> list:
    """One standing job and one campaign counter per family."""
    out = []
    for key in family_keys(roster_rows):
        standing = agenda.standing_orders(_rows_of(roster_rows, key))
        split = standing["job_split"]
        out.append({
            "key": key,
            "label": family_label(key),
            "leader": standing["leader"],
            "roster": list(standing["roster"]),
            "job": {
                "standing": standing["job"],
                "line": "%s: %s" % (family_label(key),
                                    job_line(standing["job"], standing["leader"])),
                "split_line": agenda.split_sentence(split) if split else "",
            },
            "campaign": dict(
                campaign_view(standing["campaign"]),
                line="%s: %s" % (family_label(key),
                                 campaign_view(standing["campaign"])["line"]),
            ),
        })
    return out


# --- the whole console -------------------------------------------------------

def build_console(roster_rows: list, command_rows: list,
                  now: datetime | None = None,
                  newest_job_rows: list | None = None) -> dict:
    """Rows in, the console's JSON out.

    roster_rows    overseer_roster, every column agenda reads
    command_rows   recent overseer_command rows, any status
    now            the clock, injectable so the suite can stand still
    newest_job_rows  {target_name, id} for the newest kind='job' row per
                   character from any source, which is what tells "a later
                   order replaced it" apart from "it never took"

    ALL MAY BE EMPTY. A realm whose worldserver predates a table hands in []
    and gets a thinner console, never an exception - the same contract every
    other endpoint on this page keeps.
    """
    now = now or datetime.now()
    standing = agenda.standing_orders(roster_rows)
    mode = standing["job"]
    split = standing["job_split"]
    aimed = travel_now(standing["travel"])
    # THE READ-BACK NEEDS THE JOB COLUMN. A thin roster read (no `job`) hands
    # in no jobs at all, and no jobs means "not read", never "blank".
    roster_jobs = {str(r["name"]): agenda._mode(r) for r in roster_rows
                   if "job" in r}
    newest_job = {str(r.get("target_name")): int(r.get("id") or 0)
                  for r in (newest_job_rows or [])}
    lines = outcomes(command_rows, roster_jobs, newest_job, now)
    family_of = {str(r["name"]): _family_key(r) for r in roster_rows}
    return {
        "generated_at": _when(now),
        "sections": [
            {
                "key": s.key,
                "title": s.title,
                "can_send": can_send(s.key),
                "why_not": s.why_not,
                "instead": s.instead,
                "does": s.does,
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
            "submit": JOB_SUBMIT,
        },
        "campaign": dict(
            campaign_view(standing["campaign"]),
            section=CAMPAIGN,
            submit=CAMPAIGN_SUBMIT,
            restart_label=CAMPAIGN_RESTART_LABEL,
            floor=CAMPAIGN_STOP,
            ceiling=CAMPAIGN_CEILING,
        ),
        "travel": {
            "section": TRAVEL,
            "caveat": TRAVEL_CAVEAT,
            "chips": list(travel_chips()),
            "aimed": list(aimed),
            "line": travel_line(aimed),
            "unbuilt": list(TRAVEL_UNBUILT),
            # WHO CAN BE AIMED, off the roster and never off the request.
            "who": list(standing["roster"]),
            "submit": TRAVEL_SUBMIT,
            "stand_down": TRAVEL_STAND_DOWN,
            # The value that means nowhere, so the page sends travel.NONE
            # rather than holding its own idea of what an empty aim is.
            "clear": travel.NONE,
            "reassert": TRAVEL_REASSERT,
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
        "families": family_views(roster_rows),
        "outcomes": list(lines),
        "orders": list(batches(command_rows, lines, family_of)),
        "outcome_lede": OUTCOME_LEDE,
        "outcome_empty": OUTCOME_EMPTY,
        "backlog": list(backlog()),
    }
