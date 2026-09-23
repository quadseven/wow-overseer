"""Pure logic for the two-way chat bridge between Discord and the world.

Two directions, both decided here and executed by bridge.py:

  OUT (world -> Discord)  rows from overseer_chat become Discord lines.
  IN  (Discord -> world)  a message becomes a SpeakCommand or GmCommand row
                          in overseer_command, which mod-overseer carries out.

The inbound syntax is deliberately not invented: it is WoW's own. `/say`,
`/y`, `/g`, `/p`, `/w Name`, `/e` and a leading `.` for a dot-command all mean
in Discord exactly what they mean in the client, so there is no second
vocabulary to remember. Anything that is NOT one of those stays a natural
language order and flows to voice.py as before.

Same seam rule as core/map_core/panel (infra#2597): no SQL, no HTTP and no
Discord objects below this line, which is what lets the stdlib suite test the
whole feature.

Ticket: infra#2597.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# overseer_command.command is VARCHAR(255), and 255 is WoW's own chat limit.
MAX_SPEAK_LEN = 255
# Discord hard-caps a message at 2000 of ITS units, which are UTF-16 code
# units, not code points: an astral character (most emoji) counts as two.
# Sizing with len() undercounts them by half, which is how twenty emoji-heavy
# lines can measure 1379 here and be rejected as 2639 by Discord. Leave room
# below the cap regardless.
MAX_DISCORD_UNITS = 1900


def discord_len(text: str) -> int:
    """Length as Discord counts it: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def fit_spoken(text: str, limit: int = MAX_SPEAK_LEN) -> str:
    """`text` cut to fit the command column, at a word boundary.

    A spoken row carries its words in overseer_command.command, and MySQL
    refuses a row longer than the column whole (1406). So an over-long line
    was never said at all, and the council that produced it failed every
    cycle (#217). The cut ends on a whole word and marks itself with "...";
    a single word longer than the column is cut where the column ends.
    """
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[: max(limit, 0)]
    head = text[: limit - 3]
    space = head.rfind(" ")
    if space > 0:
        head = head[:space]
    return head.rstrip(" ,;:.-") + "..."


# One relay post must not become a wall. Older lines are still in the table.
MAX_LINES_PER_POST = 20

_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

# WoW's slash commands -> the channel names mod_overseer.cpp dispatches on.
# The long and short forms a player actually types both map to one channel.
SLASH_CHANNELS = {
    "s": "say",
    "say": "say",
    "y": "yell",
    "yell": "yell",
    "shout": "yell",
    "e": "emote",
    "em": "emote",
    "emote": "emote",
    "me": "emote",
    "w": "whisper",
    "whisper": "whisper",
    "t": "whisper",
    "tell": "whisper",
    "p": "party",
    "party": "party",
    "raid": "raid",
    "ra": "raid",
    "g": "guild",
    "guild": "guild",
    "o": "officer",
    "officer": "officer",
}

# How each channel is labelled when it reaches Discord. Mirrors the client's
# own bracket convention so the log reads like the chat frame it came from.
CHANNEL_LABELS = {
    "say": "",
    "yell": "yell",
    "emote": "",
    "whisper": "whisper",
    "party": "Party",
    "raid": "Raid",
    "guild": "Guild",
    "officer": "Officer",
    "channel": "",
}


@dataclass(frozen=True)
class SpeakCommand:
    """The character says something out loud, in the world."""

    target_name: str
    channel: str
    text: str
    whisper_to: str
    source: str


# Dot-commands run at the target character's REAL security level, which stops
# escalation above that character - but it does not by itself constrain what a
# Discord caller may reach through a character that is already a GM (Grug is
# gmlevel 3). This repo's standing rule for any GM surface is an allowlist
# rather than arbitrary strings on a console, so that is what this is, and it
# is the difference between "a compromised Discord account can move my orc"
# and "a compromised Discord account owns the realm".
#
# Deliberately generous: it covers the whole point of the feature - move a
# character, hand it to the bot AI, look at and poke its state. What it leaves
# out is the surface you cannot undo: accounts and bans (identity), server
# shutdown and restart (availability), character deletion and reload (state
# that does not come back).
GM_ALLOWED_PREFIXES = frozenset(
    {
        # Getting a character somewhere, which is most of the point.
        "appear",
        "summon",
        "revive",
        "recall",
        "unstuck",
        "go",
        "tele",
        # Handing a character to the bot AI, and grouping it up.
        "playerbots",
        "group",
        # Its own state. None of these destroy anything persistent.
        "gm",
        "modify",
        "learn",
        "unlearn",
        "cast",
        "aura",
        "unaura",
        "maxskill",
        "levelup",
        "die",
        "damage",
        "freeze",
        "unfreeze",
        "additem",
        # Read-only. `npc` and `gobject` are NOT here as whole trees on
        # purpose: `.npc delete` and `.gobject delete` permanently remove
        # world objects, so only their info leaves are admitted.
        "npc info",
        "gobject info",
        "server info",
        "pinfo",
        "lookup",
        "list",
        "gps",
        "distance",
        "cooldown",
        "help",
    }
)

# Destructive leaves that live INSIDE a tree worth keeping whole.
#
# `.tele` is the clearest case and the reason this exists: `.tele Orgrimmar`
# is the entire point of the command, so the tree has to stay - but
# `.tele del <name>` permanently removes a stored location from game_tele.
# Dropping the whole tree would lose the feature; keeping it whole would keep
# the delete. So the model is: allow the tree, then deny the leaf.
#
# Entries for trees that are not on the allowlist anyway are kept as belt and
# braces, so that widening GM_ALLOWED_PREFIXES later cannot quietly re-admit
# a delete along with it.
GM_DENIED_LEAVES = frozenset(
    {
        "tele del",
        "tele delete",
        "npc delete",
        "npc del",
        "gobject delete",
        "gobject del",
        "character delete",
        "character erase",
        "account delete",
        "guild delete",
        "server exit",
        "server shutdown",
        "server restart",
        "server idlerestart",
        "reload",
        "titles reset",
    }
)


def _abbreviations(leaf: str) -> set:
    """Every spelling AzerothCore would resolve to this denied leaf.

    The core matches a subcommand token by PREFIX, case-insensitively -
    `StringStartsWithI(registered, typed)` in
    ChatCommands/ChatCommand.cpp - so typing `.tele d` reaches `.tele del`.
    A denylist that knows only the full spelling is therefore bypassed by
    abbreviation, which is exactly how `.tele d Orgrimmar` slipped past the
    first version of this. Every prefix of the denied subcommand is denied.

    The PARENT token needs no expansion: the allowlist demands its canonical
    spelling, so `.tel d` is already refused for not being an allowed command
    at all. Widening the allowlist to abbreviations would reopen this.
    """
    head, _, sub = leaf.partition(" ")
    if not sub:
        return {leaf}
    return {head + " " + sub[:i] for i in range(1, len(sub) + 1)}


_DENIED_EXPANDED = frozenset(
    form for leaf in GM_DENIED_LEAVES for form in _abbreviations(leaf)
)

_WHITESPACE = re.compile(r"\s+")


def _normalize(command: str) -> str:
    return _WHITESPACE.sub(" ", command.lstrip(".").strip()).lower()


def gm_is_allowed(command: str) -> bool:
    """Is this dot-command permitted?

    Denied leaves are checked FIRST, so a tree can be admitted whole without
    admitting the one subcommand inside it that cannot be undone. Both sides
    match on whole words, so `server info` is allowed without `server
    shutdown` riding in behind it, and `gm` does not admit `gmail`.

    Denials are matched against every ABBREVIATION the worldserver would
    resolve to them, because it matches subcommands by prefix - see
    _abbreviations. Refusing `.tele del` while passing `.tele d` would have
    been a guarantee in name only.
    """
    body = _normalize(command)
    if not body:
        return False
    if any(body == d or body.startswith(d + " ") for d in _DENIED_EXPANDED):
        return False
    return any(body == p or body.startswith(p + " ") for p in GM_ALLOWED_PREFIXES)


@dataclass(frozen=True)
class GmRefused:
    """A dot-command that is not on the allowlist.

    Refused loudly rather than passed through: falling back to the natural
    language path would hand `.account set gmlevel` to an LLM to interpret.
    """

    command: str


@dataclass(frozen=True)
class GmCommand:
    """A dot-command run through the character's own session.

    Carries no privilege of its own: the worldserver runs it at the target
    account's real security level, so a non-GM account is refused exactly as
    it would be in the client.
    """

    target_name: str
    command: str
    source: str


def parse_speak(target: str, command: str, source: str):
    """Recognise a chat or dot-command line. Returns None if it is neither.

    None is the signal to fall through to the existing playerbot-command and
    natural-language paths, so adding this bridge takes nothing away.
    """
    command = command.strip()
    if not command:
        return None

    if command.startswith("."):
        if len(command) < 2:
            return None
        if not gm_is_allowed(command):
            return GmRefused(command[:MAX_SPEAK_LEN])
        return GmCommand(target, command[:MAX_SPEAK_LEN], source)

    if not command.startswith("/"):
        return None

    verb, _, rest = command[1:].partition(" ")
    channel = SLASH_CHANNELS.get(verb.lower())
    if channel is None:
        return None

    rest = rest.strip()
    whisper_to = ""
    if channel == "whisper":
        # "/w Thrall hello" - the first word is who, the rest is what.
        whisper_to, _, rest = rest.partition(" ")
        rest = rest.strip()
        if not _NAME_RE.fullmatch(whisper_to):
            return None
    if not rest:
        return None

    return SpeakCommand(target, channel, rest[:MAX_SPEAK_LEN], whisper_to, source)


# Discord turns these into pings for real people. World chat is UNTRUSTED in
# both directions: bot lines are LLM-generated (mod-ollama-chat), and any of
# 500 characters can type anything at all. There are two independent defenses,
# because a regex is a poor thing to bet a notification storm on:
#
#   1. The client is constructed with AllowedMentions.none() (bridge.py), so
#      Discord itself refuses to resolve ANY mention in anything the bridge
#      sends, whatever the text turns out to contain. That is the real fix.
#   2. The text is defanged here as well, so a relayed line also READS as
#      inert instead of looking like a live ping that merely failed to fire.
#
# The separator is written as an escape, not pasted: an invisible character
# sitting literally in source is unreadable in a diff and unsearchable.
ZERO_WIDTH = "\u200b"

_MASS_MENTION = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
# <@123> and <@!123> are users, <@&123> is a ROLE, <#123> is a channel. The
# role form is exactly what an @everyone-only filter misses.
_ID_MENTION = re.compile(r"<(@[!&]?|#)(\d+)>")


def sanitize(text: str) -> str:
    """Make world text safe to post, without changing what it says."""
    text = _MASS_MENTION.sub(lambda m: "@" + ZERO_WIDTH + m.group(1), text)
    text = _ID_MENTION.sub(
        lambda m: "<" + ZERO_WIDTH + m.group(1) + m.group(2) + ">", text
    )
    # Backticks would break out of the code fence the relay posts inside.
    return text.replace("`", "'")


def format_line(row: dict) -> str:
    """One overseer_chat row -> one line of Discord text."""
    sender = row.get("sender_name", "?")
    channel = row.get("channel", "say")
    text = sanitize(str(row.get("text", "")))

    if channel == "emote":
        return f"* {sender} {text}"

    label = CHANNEL_LABELS.get(channel, channel)
    if channel == "channel":
        label = str(row.get("channel_name", "") or "channel")

    if channel == "whisper":
        return f"[whisper] {sender}: {text}"
    if channel == "yell":
        return f"{sender} yells: {text}"
    if label:
        return f"[{label}] {sender}: {text}"
    return f"{sender}: {text}"


# Addon traffic carries a literal control byte as its field separator; the
# MBOT payloads seen live are "MBOT\x09GET~ROSTER". A player cannot type one -
# the WoW client will not transmit a tab or any other C0 byte in chat - so a
# control character is a reliable signature for machine traffic and never
# catches speech.
# All C0 bytes except newline. The first cut of this skipped 0x09 - the one
# byte the whole filter exists for - and its own test caught it.
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f]")


def is_addon_traffic(text: str) -> bool:
    """Addon protocol riding the chat channels, not something anyone said.

    Multiboxing and unit-frame addons whisper structured payloads between
    clients constantly. They are chat rows by every measure the module can
    see, and relaying them fills the Discord channel with "MBOT PING~18265384"
    and the thought store with sentences no character ever spoke.
    """
    return bool(_CONTROL.search(text or ""))


def collapse_hearers(rows: list[dict]) -> tuple[list[dict], list[int]]:
    """(one row per utterance, ids of the copies to retire).

    overseer_chat stores a row per LISTENER, because who heard a line is the
    only way to tell speech that carried from speech shouted into an empty
    field - that is how the first council was caught talking to itself.
    Useful for diagnosis, ruinous for a relay: a party line with five
    characters in the party is five identical rows, so every council reached
    Discord five times over. Thirty rows for six councils.

    Keyed on (speaker, channel, text, moment). Two genuinely identical lines
    from one speaker in the same second collapse too, which is right: nobody
    says the same sentence twice in a second, and if they did, once is the
    honest rendering.
    """
    seen: set = set()
    keep, drop = [], []
    for row in rows:
        key = (
            row.get("sender_name"),
            row.get("channel"),
            row.get("text"),
            str(row.get("created_at")),
        )
        if key in seen:
            drop.append(int(row["id"]))
        else:
            seen.add(key)
            keep.append(row)
    return keep, drop


def partition_addon(rows: list[dict]) -> tuple[list[dict], list[int]]:
    """(rows worth posting, ids to acknowledge without posting).

    Addon rows must be marked relayed even though nothing is sent. Dropping
    them silently would leave them unrelayed forever, re-read every tick, and
    - because the relay only takes the oldest MAX_LINES_PER_POST rows - a
    steady trickle of addon traffic would push real speech out of the window
    permanently. The relay would look dead while working perfectly.
    """
    keep, drop = [], []
    for row in rows:
        if is_addon_traffic(str(row.get("text", ""))):
            drop.append(int(row["id"]))
        else:
            keep.append(row)
    return keep, drop


def format_batch(rows: list[dict]) -> list[tuple[str, list[int]]]:
    """Rows -> [(post text, the ids that post carries)].

    Each post is paired with ITS OWN rows, which is what lets the caller
    acknowledge exactly what Discord accepted. Returning one flat id list for
    the whole batch was wrong: when an early post succeeded and a later one
    failed, marking the lot relayed silently skipped lines that never went
    out, while re-sending the ones that had.

    Anything trimmed by the line cap appears in no post, so it stays unrelayed
    and goes out next tick rather than being lost.
    """
    posts: list[tuple[str, list[int]]] = []
    if not rows:
        return posts

    chunk: list[str] = []
    chunk_ids: list[int] = []
    size = 0
    for row in rows[:MAX_LINES_PER_POST]:
        line = format_line(row)
        # A single line can exceed the cap on its own once emoji double up;
        # hard-cut it rather than emitting a post Discord will refuse, which
        # would block every later line behind it.
        if discord_len(line) > MAX_DISCORD_UNITS:
            line = _clip_to_units(line, MAX_DISCORD_UNITS)
        length = discord_len(line)
        # +1 for the newline joining it to the previous line.
        if chunk and size + length + 1 > MAX_DISCORD_UNITS:
            posts.append(("\n".join(chunk), chunk_ids))
            chunk, chunk_ids, size = [], [], 0
        chunk.append(line)
        chunk_ids.append(int(row["id"]))
        size += length + 1
    if chunk:
        posts.append(("\n".join(chunk), chunk_ids))
    return posts


def _clip_to_units(text: str, limit: int) -> str:
    """Cut to `limit` UTF-16 units without splitting a surrogate pair.

    Splitting one would produce a lone surrogate, which is not encodable and
    would fail on the way out - trading a too-long post for an unsendable one.
    """
    if discord_len(text) <= limit:
        return text
    out = []
    used = 0
    for ch in text:
        cost = 2 if ord(ch) > 0xFFFF else 1
        if used + cost > limit:
            break
        out.append(ch)
        used += cost
    return "".join(out)
