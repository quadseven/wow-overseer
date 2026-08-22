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

from relay import GmCommand, GmRefused, SpeakCommand, parse_speak

# WoW enforces 2-12 letters for character names; anything else is not a
# character and never reaches SQL.
_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

# Matches the module's overseer_command.command column.
MAX_COMMAND_LEN = 255

# One Discord message must not flood the delivery queue.
MAX_COMMANDS_PER_MESSAGE = 5

USAGE = "Speak like this: @CharacterName <playerbot command>  (one per line)"


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
class NLDirective:
    """A natural-language order for a character - the inner voice decides
    what playerbot command it becomes (voice.py), outside this module."""

    target_name: str
    text: str
    source: str


@dataclass(frozen=True)
class FanoutCommand:
    """A group order that is already a playerbot command.

    One expression ("horde", "guild Argentum") becomes many InsertCommand
    rows at insert time - the fan-out is the bridge's job, so mod-overseer's
    delivery loop stays one row, one character (infra#2605).
    """

    expression: str
    command: str
    source: str


@dataclass(frozen=True)
class FanoutDirective:
    """A conjured event: natural language aimed at a group.

    Mirrors NLDirective, one rung wider - the inner voice picks a single
    allowlisted command for the whole band (voice.py, outside this module)
    and that one command is what fans out.
    """

    expression: str
    text: str
    source: str


def _voice_is_raw(command: str) -> bool:
    # Late import: core must stay importable without voice's vocabulary in
    # contexts that only need parsing (and the map server imports core).
    from voice import is_raw_command

    return is_raw_command(command)


def _group_split(head: str, rest: str) -> tuple[str, str] | None:
    # Late import for the same reason, plus one more: fanout imports core
    # for the faction race sets, so a module-level import here would be a
    # cycle.
    from fanout import split_group_order

    return split_group_order(head, rest)


def _spoken_directive(target: str, command: str, source: str):
    """A chat or dot-command line -> its directive, the Reply that refuses it,
    or None to let the older paths have it."""
    spoken = parse_speak(target, command, source)
    if isinstance(spoken, GmRefused):
        return Reply(
            f"'{spoken.command}' is not on the GM allowlist. That list is "
            "GM_ALLOWED_PREFIXES in relay.py; it leaves out accounts, bans, "
            "server shutdown, character deletion and reload on purpose."
        )
    return spoken


_ROSTER_RE = re.compile(r"\b(list|who|online|souls|playing|roster|players)\b", re.IGNORECASE)


def parse_directive(
    text: str, author_id: str, allowed_ids: frozenset[str], dedicated: bool = False
) -> list:
    """Turn one Discord message into decisions.

    In a shared channel, silence (empty list) for anyone not allowed and for
    messages that do not address a character - the bridge must not answer
    every message. In the DEDICATED overseer channel (`dedicated=True`), an
    allowed user talking to the overseer itself always gets an answer: a
    roster when they ask who is in the world, and help otherwise - dead air
    in the overseer's own hall reads as breakage, because it is.
    """
    if author_id not in allowed_ids:
        return []

    directives = []
    addressed = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("@"):
            continue
        addressed = True
        target, _, command = line[1:].partition(" ")
        command = command.strip()
        group = _group_split(target, command)
        if group is not None:
            directives.append(_group_directive(group, author_id))
            continue
        if not _NAME_RE.fullmatch(target):
            directives.append(Reply(f"'{target}' is not a character name. {USAGE}"))
            continue
        if not command:
            directives.append(Reply(f"Tell {target} what to do. {USAGE}"))
            continue
        if len(command) > MAX_COMMAND_LEN:
            directives.append(
                Reply(f"That order for {target} is too long ({len(command)} chars, max {MAX_COMMAND_LEN}).")
            )
            continue
        # WoW's own chat syntax ("/say hi", "/w Thrall hi") and dot-commands
        # (".appear Thrall") are taken literally. Everything else falls
        # through to the playerbot-command and inner-voice paths untouched.
        spoken = _spoken_directive(target, command, f"discord:{author_id}")
        if spoken is not None:
            directives.append(spoken)
            continue
        if _voice_is_raw(command):
            directives.append(InsertCommand(target, command, f"discord:{author_id}"))
        else:
            directives.append(NLDirective(target, command, f"discord:{author_id}"))

    if not addressed:
        if not dedicated:
            return []
        if _ROSTER_RE.search(text):
            return [RosterQuery()]
        return [Reply(f"I command the world, not the conversation - yet. {USAGE}")]
    # A fan-out line counts as one order here: the flood cap bounds how many
    # things one message may ask for, and MAX_FANOUT_TARGETS bounds how wide
    # each of those things may get.
    orders = [
        d
        for d in directives
        if isinstance(
            d, (InsertCommand, NLDirective, FanoutCommand, FanoutDirective, SpeakCommand, GmCommand)
        )
    ]
    if len(orders) > MAX_COMMANDS_PER_MESSAGE:
        return [Reply(f"That is {len(orders)} orders in one breath; the cap is {MAX_COMMANDS_PER_MESSAGE}.")]
    return directives


def _group_directive(
    group: tuple[str, str], author_id: str
) -> Reply | FanoutCommand | FanoutDirective:
    """One group line -> one decision, or the Reply that explains itself.

    Kept beside parse_directive rather than inside it so the group grammar
    reads as one thing; the widening lives in fanout.py, and this is only
    the same command validation the single-character path applies.
    """
    from fanout import GROUP_USAGE, describe_expression

    expression, command = group
    if expression == "guild":
        return Reply(f"Name the guild. {GROUP_USAGE}")
    if not command:
        return Reply(f"Tell {describe_expression(expression)} what to do. {GROUP_USAGE}")
    if len(command) > MAX_COMMAND_LEN:
        return Reply(
            f"That order for {describe_expression(expression)} is too long "
            f"({len(command)} chars, max {MAX_COMMAND_LEN})."
        )
    source = f"discord:{author_id}"
    if _voice_is_raw(command):
        return FanoutCommand(expression, command, source)
    return FanoutDirective(expression, command, source)


def report_outcomes(
    rows: list[dict], seen_ids: set[int]
) -> tuple[list[tuple[int, Reply | None]], set[int]]:
    """Turn polled overseer_command rows into delivery reports, exactly once.

    `rows` are non-pending rows from the store. `seen_ids` is what has already
    been reported; the returned set replaces it. Each reply is paired with its
    row id so the caller can route it back to wherever the directive came from.
    A reply of None means "this one is finished, say nothing" - the caller
    still clears the id, which is what keeps its pending map from growing.
    On bridge restart the caller seeds seen_ids with every known row id, so
    history is never re-announced.
    """
    replies = []
    new_seen = set(seen_ids)
    for row in rows:
        row_id = row["id"]
        if row_id in new_seen:
            continue
        new_seen.add(row_id)
        # Rows written before the chat bridge existed carry no kind.
        kind = row.get("kind") or "bot"
        if row["status"] == "delivered":
            if kind == "chat":
                # A spoken line confirms itself: it comes straight back
                # through the chat relay, exactly as it would appear in the
                # player's own chat frame. A "delivered" note would be an echo.
                # Still reported, with no text: the caller needs the id back
                # to clear the row from its pending map.
                replies.append((row_id, None))
                continue
            if kind == "gm":
                reply = Reply(f"{row['target_name']}: {row['command']} - done.")
            else:
                reply = Reply(f"{row['target_name']} heard the order: {row['command']}")
        else:
            detail = row.get("detail") or "unknown error"
            if kind == "chat":
                reply = Reply(f"{row['target_name']} could not say that ({detail}).")
            elif kind == "gm":
                reply = Reply(f"{row['target_name']}: {row['command']} - refused ({detail}).")
            else:
                reply = Reply(f"{row['target_name']} did not get the order ({detail}).")
        replies.append((row_id, reply))
    return replies, new_seen


# Race -> faction, 3.3.5a. Missing/unknown races count as neither.
_ALLIANCE_RACES = {1, 3, 4, 7, 11}
_HORDE_RACES = {2, 5, 6, 8, 10}
_CONTINENTS = {0: "Eastern Kingdoms", 1: "Kalimdor", 530: "Outland", 571: "Northrend"}

ROSTER_SAMPLE = 15


def format_roster(rows: list[dict]) -> Reply:
    """One readable message summarizing overseer_snapshot rows.

    500 names do not fit a Discord message (2000 chars), so the roster is a
    census plus a sample; the full living map is the #2599 ticket's job.
    """
    if not rows:
        return Reply("The world is empty. Either the realm is down or nobody is logged in.")

    total = len(rows)
    alliance = sum(1 for r in rows if r["race"] in _ALLIANCE_RACES)
    horde = sum(1 for r in rows if r["race"] in _HORDE_RACES)
    fighting = sum(1 for r in rows if r.get("in_combat"))
    humans = [r["name"] for r in rows if not r.get("is_bot")]

    by_continent: dict[str, int] = {}
    for r in rows:
        key = _CONTINENTS.get(r["map_id"], "elsewhere")
        by_continent[key] = by_continent.get(key, 0) + 1

    levels = sorted(r["level"] for r in rows)
    highest = sorted(rows, key=lambda r: (-r["level"], r["name"]))[:ROSTER_SAMPLE]

    lines = [
        f"{total} souls in the world - {alliance} Alliance, {horde} Horde, {fighting} in combat right now.",
        "By continent: " + ", ".join(f"{name} {n}" for name, n in sorted(by_continent.items(), key=lambda kv: -kv[1])) + ".",
        f"Levels {levels[0]} to {levels[-1]}, median {levels[len(levels) // 2]}.",
        "Highest: " + ", ".join(f"{r['name']} ({r['level']})" for r in highest) + ".",
    ]
    if humans:
        lines.append("Mortals present: " + ", ".join(sorted(humans)) + ".")
    return Reply("\n".join(lines))
