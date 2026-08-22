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

Ticket: infra#2604.
"""
from __future__ import annotations

import json
import re
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
