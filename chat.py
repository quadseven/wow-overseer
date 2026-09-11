"""Pure builders for the thought timeline and the web chat box.

The overseer's memory (overseer_thought) is written by the Discord bridge
and read by the map page; this module is everything that happens between
the rows and the screen - how a page of history ends, what "3m ago" means,
who spoke a line, exactly what the inner voice is asked, and what a garbled
or absent model reply degrades to.

Same seam rule as map_core/panel (infra#2597): map_server.py fetches rows,
calls in here, and writes bytes. No SQL, no HTTP, no LLM below this line,
which is what lets the stdlib suite test the whole feature.

One mind across surfaces: a line said on Discord and a line typed on the
web page land in the same table with the same shape, so each surface shows
the other's half of the conversation.

THE SECOND HALF OF THIS MODULE IS THE RULES FOR SAYING A THING AT ALL
(infra#3197), and it is here rather than in a module of its own because it
is the same subject seen from the other end: everything below decides what
reaches a chat window, and the four rules are shared by every module that
puts words in a character's mouth. They are pure predicates over facts the
caller supplies - no roster, no SQL, no clock of their own - so each one is
a function a test can hold, which is the point. What Evan watched on stream
is what named them:

    [Party] [Grog]: Grog give Og 20 Linen Cloth. Og need it for tailoring.
    [Party] [Grug]: Grug give Og 19 Linen Cloth. Og need it for tailoring.
    [Party] [Og]:   Og need cloth? Og know tailoring. Og make it, family
                    just bring the stuff.          (x58 in three minutes)

  SAY IT ONCE          keyed on the INTENT (speaker, subject, listener), so
                       a count drifting from 20 to 19, or the voice layer
                       rewording the same meaning, cannot defeat it.
  NEVER ADDRESS        a plea excludes its own speaker and a response
  YOURSELF             excludes whoever raised it. "Og need cloth? Og know
                       tailoring" is Og answering Og, which is also the
                       feedback loop that produced the 58.
  NEVER CLAIM A SKILL  checked against `character_skills` AT THE MOMENT OF
  YOU DO NOT HAVE      SPEAKING, never against a plan or a queued trade. Og
                       does not know tailoring: `overseer_trade` has held
                       `learn tailoring` at 'planned' since 2026-08-26 and
                       `character_skills` gives him Herbalism and nothing
                       else. A viewer cannot tell that line is wrong, which
                       is what makes it the worst of the three.
  READ THE ROOM        crafting chatter stands down while a dungeon run is
                       active. Evan, watching a Deadmines pull stop for a
                       cloth handover: "Why the fuck is the whole game
                       pausing to give Og cloth? They should say shut up we
                       are in a dungeon just wait."

Tickets: infra#2604, infra#3197; mod-overseer#169.
"""
from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, MutableMapping
from datetime import datetime

import voice

# overseer_thought.text is VARCHAR(2000); every string this module hands to
# the adapter is already short enough for the column.
MAX_TEXT = 2000

# One page must never be a whole-table scan serialized into one response:
# a busy character accumulates event thoughts every 30s forever.
DEFAULT_PAGE = 50
MAX_PAGE = 100

# What the human may type in one go. Longer than a playerbot command
# (core.MAX_COMMAND_LEN) because this is conversation, not a command line.
MAX_MESSAGE = 500

# How much history the model is shown. Bounded because the prompt is built
# per message and a character's history only grows.
RECENT_FOR_PROMPT = 8
# One history line in the prompt; a 2000-char event narration must not
# crowd out the seven other thoughts.
MAX_HISTORY_LINE = 200

# Both halves of a web exchange persist as source 'chat' - the enum has one
# value for conversation, and adding one is a schema change the worldserver
# image would have to agree with. This marker is what tells both surfaces
# (and the model, which sees the history verbatim) who spoke a line.
OVERSEER_PREFIX = "Overseer: "

# What gets persisted when the model says nothing usable. An honest line in
# the stream beats an invented in-character reply, and beats a lost message.
SILENT_LINE = "(the voice is silent - nothing came back)"

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}")


def page_size(raw: str | None) -> int:
    """Clamp a caller-supplied page size into the bounded range."""
    try:
        asked = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_PAGE
    if asked < 1:
        return DEFAULT_PAGE
    return min(asked, MAX_PAGE)


def clean_message(raw: str) -> str:
    """The human's typed line, trimmed and bounded. Empty means no message."""
    return raw.strip()[:MAX_MESSAGE]


def overseer_line(text: str) -> str:
    """The human's words as they persist into the character's stream."""
    return (OVERSEER_PREFIX + text)[:MAX_TEXT]


def outage_line(name: str) -> str:
    """The reply row written when the inner voice cannot be reached.

    The human's message is already in the stream by this point; leaving the
    exchange half-written would read as the character ignoring them.
    """
    return f"{name} hears you, but the voice that speaks for them is silent right now."[:MAX_TEXT]


def relative_when(created_at: datetime, now: datetime) -> str:
    """A "3m ago"-style label, from a caller-supplied now (so it is testable).

    The caller passes the DATABASE clock, not the pod clock: created_at is
    stamped by MySQL, and a few seconds of drift between the two machines
    would otherwise render fresh thoughts as happening in the future.
    """
    seconds = int((now - created_at).total_seconds())
    if seconds < 10:
        # Includes rows stamped "ahead" of now - a row written between the
        # SELECT and the NOW() read is legitimately newer than now.
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _speaker_and_text(source: str, text: str) -> tuple[str, str]:
    """Who said this line, and the line without its bookkeeping marker."""
    if text.startswith(OVERSEER_PREFIX):
        return "overseer", text[len(OVERSEER_PREFIX):]
    # A Discord directive persists as source 'command' with the raw order
    # as its text - that is the Overseer speaking too, on the other surface.
    if source == "command":
        return "overseer", text
    return "character", text


def build_timeline(name: str, rows: list[dict], now: datetime, limit: int) -> dict:
    """One page of a character's thought history, newest first.

    `rows` are newest-first overseer_thought rows (id, source, text,
    created_at). The page ends with a cursor the caller passes back as
    `before` to walk further into the past; a short page means there is no
    more history, which is how the page knows to stop asking.
    """
    thoughts = []
    for row in rows:
        speaker, text = _speaker_and_text(row["source"], row["text"])
        thoughts.append({
            "id": row["id"],
            "source": row["source"],
            "speaker": speaker,
            "text": text,
            "created_at": row["created_at"].isoformat(),
            "when": relative_when(row["created_at"], now),
        })
    # A full page might be the exact end of history; the next request
    # returning nothing is cheaper than counting the whole table here.
    full = len(rows) == limit and limit > 0
    next_before = min(t["id"] for t in thoughts) if (full and thoughts) else None
    return {
        "name": name,
        "thoughts": thoughts,
        "next_before": next_before,
        "has_more": next_before is not None,
    }


def build_chat_prompt(*, name: str, level: int, race_name: str, class_name: str,
                      zone: str, personality: str | None, health: int,
                      max_health: int, in_combat: bool, recent: list[dict],
                      text: str) -> str:
    """Everything the inner voice needs to answer as this character.

    Grounding, not invention: identity, body, place, and the character's own
    recent thoughts are handed to the model. It supplies voice and intent
    only - and its command choice is gated by voice.parse_decision, so the
    web surface can never deliver a string the vocabulary never sanctioned.
    """
    persona = f" Personality: {personality}." if personality else ""
    body = f"Your body: {health}/{max_health} health"
    body += ", and you are fighting right now." if in_combat else "."
    # Oldest first: the model reads history like a transcript, and the most
    # recent thought sits closest to the question being asked.
    lines = [
        f"  [{row['source']}] {row['text'][:MAX_HISTORY_LINE]}"
        for row in reversed(recent[:RECENT_FOR_PROMPT])
    ]
    history = "\n".join(lines) if lines else "  (nothing recent comes to mind)"
    vocab = "\n".join(f"  {cmd} - {what}" for cmd, what in voice.VOCABULARY.items())
    return (
        f"You are {name}, a level {level} {race_name} {class_name} standing in "
        f"{zone}, a character in World of Warcraft.{persona}\n"
        f"{body}\n"
        "Your recent thoughts, oldest first:\n"
        f"{history}\n\n"
        f"The Overseer speaks to you: \"{text}\"\n\n"
        "Answer them in character - one or two short sentences, your own voice, "
        "grounded in where you are and what just happened to you.\n"
        "If they asked you to DO something, also pick the ONE command from this "
        "list that carries it out:\n"
        f"{vocab}\n\n"
        "Answer with ONLY a JSON object, no other text:\n"
        '{"command": "<exactly one command from the list, or none>", '
        '"say": "<what you say back, in character>"}\n'
        "If they are only talking, use \"none\" for the command."
    )


def _strip_reasoning(content: str) -> str:
    """Drop think-aloud blocks, including one the model never closed."""
    body = _THINK_TAG_RE.sub(" ", content)
    opened = body.lower().find("<think>")
    if opened != -1:
        # Unclosed: the model spent its whole budget thinking and never
        # answered. Everything from here on is private reasoning.
        body = body[:opened]
    return body


def _last_prose(body: str) -> str:
    """The last paragraph that reads like an answer rather than JSON debris."""
    for block in reversed(re.split(r"\n\s*\n", body)):
        lines = [
            line.strip() for line in block.splitlines()
            # A truncated object ('{"say": ') is debris, not something to
            # put in a character's mouth.
            if line.strip() and not line.strip().startswith(("{", "}", '"'))
        ]
        if lines:
            return " ".join(lines)
    return ""


def parse_reply(content: str) -> voice.Decision:
    """Whatever the model said, turned into something safe to persist.

    Defensive on purpose, and in this order (learned live on 2026-08-21):
    reasoning models narrate before they answer, so the answer is the LAST
    well-formed JSON object, not the first. A model that ignores the JSON
    ask and simply talks is still a perfectly good chat reply, so prose
    falls back to prose. Only when there is nothing usable at all does the
    exchange degrade to an admitted silence.

    Command validation is deliberately NOT re-implemented here:
    voice.parse_decision owns the select-and-parameterize gate, so there is
    exactly one place in the service that decides what may reach the game.
    """
    body = _strip_reasoning(content)
    data = None
    for candidate in reversed(_JSON_OBJECT_RE.findall(body)):
        try:
            data = json.loads(candidate)
            break
        except ValueError:
            continue
    if isinstance(data, dict) and str(data.get("say", "")).strip():
        return voice.parse_decision(body)
    prose = _last_prose(body)
    if prose:
        return voice.Decision(None, prose[:voice.MAX_SAY])
    if isinstance(data, dict):
        # A well-formed answer with no words in it: keep the command gate's
        # verdict, but say something rather than showing an empty bubble.
        return voice.Decision(voice.parse_decision(body).command, SILENT_LINE)
    return voice.Decision(None, SILENT_LINE)


# ---------------------------------------------------------------------------
# The rules for saying a thing out loud (infra#3197).
#
# Pure predicates over facts the caller supplies. Nothing below reads a
# roster, a database or a clock: `now` and `held` and `run` are arguments
# precisely so that the rule is the part a test can hold, and so that the
# same rule serves craftpleas.py, materials.py and bridge.py without any of
# them growing a private copy that drifts.
# ---------------------------------------------------------------------------

# How long one INTENT stays said before it may be said again.
#
# Thirty minutes, and the number is a viewing decision rather than an
# engineering one: the bar Evan set is that he never sees the same sentence
# twice in a screenful of party chat, and a screenful is a couple of minutes
# of a busy fight. kin.COOLDOWN_SECONDS is 90s for the opposite reason - a
# second real emergency in the same fight still deserves an answer, while a
# second announcement of the same handover never does.
SAY_ONCE_SECONDS = 1800.0


def say_key(*, speaker: str, subject: str, listener: str = "") -> tuple:
    """What a line MEANS, as the thing that gets remembered.

    THE KEY IS THE INTENT AND NEVER THE RENDERED SENTENCE. Two things defeat
    a key made of words, and both were on screen: the count in a handover
    drifts (20 Linen Cloth, then 19, because the stack is a different one),
    and the voice layer turns one meaning into two wordings ("Og make it,
    family just bring the stuff" and "Og make cloth. Family bring stuff.").
    Speaker, subject and listener are what is actually the same about those
    lines.

    Casefolded, because bots and people spell each other's names either way
    and "og" must not be a second Og.
    """
    return (
        (speaker or "").strip().casefold(),
        (subject or "").strip().casefold(),
        (listener or "").strip().casefold(),
    )


def should_say(said: Mapping, key: tuple, *, now: float,
               cooldown: float = SAY_ONCE_SECONDS) -> bool:
    """Has this intent gone quiet long enough to be said again?

    `said` is the caller's ledger of key -> the monotonic moment it was last
    spoken, held for the life of the process the same way bridge.py holds
    `_last_muster_at` for kin and `_last_overheard_at` for overhear. A
    restart forgets, deliberately: the ledger is about a viewer's screen, and
    a process that has just come back has not filled anybody's screen.
    """
    last = said.get(key)
    if last is None:
        return True
    return (now - last) >= cooldown


def remember_said(said: MutableMapping, key: tuple, *, now: float,
                  cooldown: float = SAY_ONCE_SECONDS) -> None:
    """Stamp this intent as just said, and forget the ones that have expired.

    Pruning here rather than in a sweep keeps the ledger bounded by what is
    actually being repeated, which is the only thing it is ever asked about.
    """
    for old, when in list(said.items()):
        if (now - when) >= cooldown:
            del said[old]
    said[key] = now


def addressed_to_self(speaker: str, listener: str) -> bool:
    """Is this character about to talk to itself?

    The whole of "Og need cloth? Og know tailoring" is this predicate being
    absent: craftpleas answered a line without checking that the crafter it
    named was the character that asked, so Og answered Og, and his own answer
    then parsed as a fresh ask and answered itself 58 times.

    An empty listener is nobody, which is not the same as being yourself.
    """
    them = (listener or "").strip().casefold()
    if not them:
        return False
    return them == (speaker or "").strip().casefold()


# What a character's relationship to a trade can be. Three states and not a
# boolean, because "planned" is the case the family is actually in and the
# honest line for it is neither the claim nor silence.
HELD = "has"
LEARNING = "learning"
UNSKILLED = "neither"


def _for(table: Mapping, who: str) -> Collection:
    """One character's row from a name-keyed table, however it is spelled."""
    for name, skills in (table or {}).items():
        if str(name).strip().casefold() == who:
            return skills or ()
    return ()


def skill_state(name: str, skill: str, *, held: Mapping,
                planned: Mapping) -> str:
    """Does this character HAVE this trade, is it only planned, or neither?

    `held` is name -> the professions `character_skills` actually gives them,
    read at the moment of speaking. `planned` is name -> the professions the
    family has DECIDED they will end up with (professions.assigned, or the
    'planned' rows of overseer_trade). The two are separate arguments because
    conflating them is the bug: `professions.crafter_for` answers "who is
    assigned tailoring" and every caller read it as "who can make cloth".

    Order matters. HELD is checked first, so a trade that is both held and
    still queued reads as held - the world is the authority, never the queue.
    """
    who = (name or "").strip().casefold()
    what = (skill or "").strip().casefold()
    if not who or not what:
        return UNSKILLED
    if what in {str(s).strip().casefold() for s in _for(held, who)}:
        return HELD
    if what in {str(s).strip().casefold() for s in _for(planned, who)}:
        return LEARNING
    return UNSKILLED


# Words that turn a mention of a trade into an admission rather than a claim.
# "Og learning tailoring" names the trade and claims nothing; "Og know
# tailoring" names it and claims everything.
_HEDGE_RE = re.compile(
    r"\b(?:learn|learns|learning|learned|soon|some\s?day|going\s+to|will|"
    r"not\s+yet|no\s+yet|no\s+know|not\s+know|no\s+can)\b",
    re.I,
)


def honest_claim(text: str, *, skill: str, state: str) -> bool:
    """Is this sentence still true once the voice layer has reworded it?

    The last gate, and it exists because the plain line goes through an LLM
    between the decision and the chat window. A hedged line can come back
    unhedged ("Og learning tailoring" -> "Og know tailoring") and it would be
    a lie in the family's mouth with nothing between it and the stream. The
    caller falls back to the plain line when this says no.

    HELD claims are always honest, whatever the wording: the character really
    does have the trade. LEARNING may name the trade only with a hedge.
    UNSKILLED may not name it at all - there is nothing true to say.
    """
    body = text or ""
    what = (skill or "").strip()
    if state == HELD or not what:
        return True
    if not re.search(rf"\b{re.escape(what)}\b", body, re.I):
        return True
    if state == LEARNING:
        return bool(_HEDGE_RE.search(body))
    return False


# The jobs during which the family has something better to do than talk about
# reagents. From jobs.MODES, named here rather than imported so this module
# keeps its no-dependency shape; test_chat.py asserts the two agree.
BUSY_JOBS = frozenset({"dungeon"})


def mid_run(name: str, *, run: Mapping | None, jobs: Mapping) -> bool:
    """Is this character in the middle of a dungeon run right now?

    `run` is the `overseer_dungeon_run` row whose state is 'active', or None
    when there is no run. `jobs` is name -> `overseer_roster.job`.

    THE MEMBER LIST IS PREFERRED AND THE JOB IS THE FALLBACK. A run row
    carries the names that were on the instance map, which is the precise
    answer; rows written before that column was filled carry an empty string,
    and for those the roster's job='dungeon' is what is left to go on. Asking
    the job alone would be wrong on its own - all five sit at job='dungeon'
    between runs as well, and that is not a reason to go quiet forever.
    """
    if not run or str(run.get("state") or "").strip().lower() != "active":
        return False
    who = (name or "").strip().casefold()
    if not who:
        return False
    members = run.get("members") or ()
    if isinstance(members, str):
        members = members.replace(";", ",").split(",")
    named = {str(m).strip().casefold() for m in members if str(m).strip()}
    if named:
        return who in named
    for roster_name, job in (jobs or {}).items():
        if str(roster_name).strip().casefold() == who:
            return str(job or "").strip().lower() in BUSY_JOBS
    return False


def run_has_present_member(run: Mapping | None, live_maps: Mapping[str, int] | None) -> bool:
    """Whether an active run still contains a member in its instance.

    The durable run row can outlive the party after a crash or an incomplete
    exit. When fresh snapshot rows are available, they are the authority for
    whether the family is still on that run's map. ``None`` means the snapshot
    read failed, so callers must fail closed and retain the busy state.
    """
    if not run or str(run.get("state") or "").strip().lower() != "active":
        return False
    if live_maps is None:
        return True
    try:
        map_id = int(run["map_id"])
    except (KeyError, TypeError, ValueError):
        return True
    members = run.get("members") or ()
    if isinstance(members, str):
        members = members.replace(";", ",").split(",")
    names = {str(member).strip().casefold() for member in members if str(member).strip()}
    if not names:
        return bool(live_maps)
    return any(
        str(name).strip().casefold() in names and int(member_map) == map_id
        for name, member_map in live_maps.items()
    )


def stand_down(speaker: str, *, subject: str = "", place: str = "") -> str:
    """What a character says instead, when it is asked mid-run.

    Evan's own words for the line he wanted: "They should say shut up we are
    in a dungeon just wait." Said ONCE, keyed like every other intent - the
    fault being fixed is a loop that cannot read the room, and a stand-down
    repeated every tick would be the same loop wearing better manners.
    """
    where = (place or "").strip() or "the deep place"
    thing = (subject or "").strip()
    # Capitalised because it opens its own sentence: "... in The Deadmines.
    # cloth wait." reads as a typo rather than as caveman grammar, and the
    # register is deliberate.
    tail = f" {thing[:1].upper()}{thing[1:]} wait." if thing else ""
    return f"{speaker} say not now. Family fight in {where}.{tail}"
