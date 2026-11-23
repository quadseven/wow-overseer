"""Decision core for the wow-overseer bridge.

The bridge's whole intelligence lives here as pure functions: a Discord
message or a table poll comes in, and decisions come out - rows to write,
replies to send. Nothing in this module touches Discord, MySQL, or an LLM;
the adapters around it do IO and nothing else. That split is the test seam:
the suite runs stdlib-only in the python-units matrix, and the adapters stay
too thin to hide logic in.

Epic: infra#2597, ticket infra#2598.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import director
from relay import GmCommand, GmRefused, SpeakCommand, parse_speak

# WoW enforces 2-12 letters for character names; anything else is not a
# character and never reaches SQL.
_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

# Matches the module's overseer_command.command column.
MAX_COMMAND_LEN = 255

# One Discord message must not flood the delivery queue.
MAX_COMMANDS_PER_MESSAGE = 5

USAGE = "Speak like this: @CharacterName <playerbot command>  (one per line)"

# WHAT A FINISHED ROW CLAIMS (infra#2819).
#
# `delivered` used to be the only success, and it was written the instant
# PlayerbotAI::HandleCommand ACCEPTED the row. A whispered command does not act
# when it is accepted - it lands in PlayerbotAI::chatCommands and is drained on
# the bot's next AI tick (mod_overseer.cpp:2054-2057) - so `delivered` says the
# row was handed over and nothing more. `nc -new rpg` was sent to Ugga twice,
# read `delivered` twice, and removed nothing either time; the three characters
# it worked for produced rows that looked exactly the same.
#
# So the module now READS THE STRATEGY LIST BACK off the live engines and the
# statuses split three ways:
#
#   delivered  - carried out. Unverifiable by construction, or nothing to
#                verify: chat, gm, probe, give, share, and any bot command
#                with no checkable post-condition. UNCHANGED IN MEANING, so
#                every row already in the table still reads correctly and the
#                two images can deploy in either order.
#   applied    - a strategy command whose effect was READ BACK off the bot's
#                own engine and holds. This is the only status that has ever
#                meant "the bot changed".
#   unchanged  - the bot accepted it and its live strategy list did not
#                change. Not an error: nothing failed, nothing happened. The
#                row's `result` carries the lists it was judged against.
#
# `verifying` is deliberately absent: it is the in-flight state between the
# hand-off and the read-back, and reporting it would call a command that has
# not finished yet a failure - the same reason `claimed` is absent.
COMMAND_TERMINAL_STATUSES = ("delivered", "applied", "unchanged", "error")
COMMAND_SUCCESS_STATUSES = ("delivered", "applied")

# A ROW A WORLDSERVER ROLL ENDED SAYS SO (#789). The module holds its
# read-backs (strategy, hearth, summon, conjure, cast, learn, quest use,
# retire, hunt) in memory, so a roll loses them and the next worldserver ends
# their rows as errors (mod-overseer ExpireAbandonedClaims); the bridge's own
# stale sweep ends the ones it reaches first. Both write a detail that starts
# with this word. Nothing refused the command: the world restarted. A pass
# that backs off a refusal asks again instead.
RESTART_DETAIL_PREFIX = "restart: "


def ended_by_restart(status, detail) -> bool:
    """True when an overseer_command row is an error a worldserver roll wrote,
    not a refusal."""
    return str(status or "") == "error" and str(detail or "").startswith(
        RESTART_DETAIL_PREFIX
    )


@dataclass(frozen=True)
class InsertCommand:
    """A row for overseer_command; mod-overseer whispers it to the bot."""

    target_name: str
    command: str
    source: str


@dataclass(frozen=True)
class Reply:
    """Text to send back to the channel the directive came from."""

    text: str


@dataclass(frozen=True)
class RosterQuery:
    """The overseer itself is being asked who is in the world."""


@dataclass(frozen=True)
class DigestQuery:
    """Somebody has come back and is asking after the family.

    "how are they?", "what did they do all night?", "catch me up on the last 6
    hours". A question for the OVERSEER about five characters, not an order to
    any of them - which is why it is its own decision beside RosterQuery and
    never a voice.VOCABULARY entry. Vocabulary entries are mod-playerbots chat
    commands delivered verbatim to a bot; a reporting verb put there is
    whispered into a grammar that has no such command, and mod-playerbots
    reports success anyway (see the `sell junk` note in voice.py).

    `hours` is the window asked for, already parsed and bounded by
    digest.parse_ask.
    """

    hours: float


@dataclass(frozen=True)
class NLDirective:
    """A natural-language order for a character - the inner voice decides
    what playerbot command it becomes (voice.py), outside this module."""

    target_name: str
    text: str
    source: str


@dataclass(frozen=True)
class JobDirective:
    """A family-wide job-schedule order (infra#2834) - "it's farming time".

    NO target_name, unlike NLDirective: a job is a property of the FAMILY, not
    of one character. mod-overseer gates `new rpg` to the leader alone (the
    "ONLY THE TRAVELLER" rule), so a mode that could differ per character
    would reintroduce independent aims and the 937-yard scatter of infra#2812
    one layer up from where it was fixed. jobs.py's own docstring explains
    this at length; it is no longer a stray attribute.
    """

    job_name: str
    source: str


Decision = InsertCommand | Reply | RosterQuery | DigestQuery | NLDirective | JobDirective


def decide(text: str, source: str) -> list[Decision]:
    """Pure decision function: maps incoming text and a source identifier
    to a list of decisions (commands, replies, queries).
    """
    cleaned = text.strip()
    if not cleaned:
        return [Reply(USAGE)]

    if cleaned.lower() in ("roster", "!roster"):
        return [RosterQuery()]

    if cleaned.lower().startswith("digest"):
        parts = cleaned.split()
        hours = 6.0
        if len(parts) > 1:
            try:
                hours = float(parts[1])
            except ValueError:
                pass
        return [DigestQuery(hours=hours)]

    # Parse speak / direct commands using relay module
    try:
        parsed = parse_speak(cleaned)
    except Exception:
        parsed = None

    if parsed is not None:
        if isinstance(parsed, SpeakCommand):
            if not _NAME_RE.match(parsed.target):
                return [Reply(f"Invalid character name: {parsed.target}. Must be 2-12 alphabetic characters.")]
            if len(parsed.command) > MAX_COMMAND_LEN:
                return [Reply(f"Command exceeds maximum length of {MAX_COMMAND_LEN} characters.")]
            return [InsertCommand(target_name=parsed.target, command=parsed.command, source=source)]
        elif isinstance(parsed, GmCommand):
            # GM commands are handled via director / relay integration
            return [Reply(f"GM command accepted: {parsed.command}")]
        elif isinstance(parsed, GmRefused):
            return [Reply(f"GM command refused: {parsed.reason}")]

    # Fallback line-by-line parsing for multi-line messages
    decisions: list[Decision] = []
    lines = cleaned.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            p = parse_speak(line)
            if isinstance(p, SpeakCommand):
                if not _NAME_RE.match(p.target):
                    continue
                if len(p.command) > MAX_COMMAND_LEN:
                    continue
                decisions.append(InsertCommand(target_name=p.target, command=p.command, source=source))
                if len(decisions) >= MAX_COMMANDS_PER_MESSAGE:
                    break
        except Exception:
            continue

    if not decisions:
        return [Reply(USAGE)]

    return decisions