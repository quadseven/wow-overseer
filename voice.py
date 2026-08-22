"""The inner voice: natural language in, an allowlisted command + words out.

Pure module - the LLM's reply enters as a string and leaves as a validated
Decision. The one rule that keeps this safe: the model can only pick from a
declared vocabulary (or return a raw command that passes the same charset
gate) - it can never invent a string that reaches the game unchecked. The
LLM supplies voice and intent; the data it speaks about is handed to it,
never asked of it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

MAX_SAY = 400
_COMMAND_RE = re.compile(r"^[a-z0-9 +,@:'!-]{1,120}$")

# The command vocabulary shown to the model, from mod-playerbots' own chat
# grammar (wiki: Playerbot-Commands). Keys are what gets delivered; the
# descriptions exist purely to steer the model's choice.
VOCABULARY = {
    "follow": "walk with and protect the speaker",
    "stay": "stop and hold this position",
    "flee": "run from danger to the master",
    "grind": "hunt and kill nearby monsters continuously (leveling, 'get stronger')",
    "attack": "attack the current target",
    "stats": "report gold, bag space and experience",
    "quests": "list current quests",
    "talents": "report talent build",
    "reset ai": "clear internal state and start fresh",
    "sell junk": "sell grey items at the next vendor",
    "repair": "repair equipment at the next vendor",
    "home": "set hearth at the nearest innkeeper",
    "mount": "get on the mount",
    "summon": "come to the speaker",
    "co +grind": "enable continuous grinding strategy",
    "co -grind": "disable continuous grinding strategy",
    "co +loot": "loot everything",
    "drop quest": "abandon a quest",
    "leave": "leave the current group",
    "los": "list what the character can see",
}

# First tokens that mark an already-raw command - these skip the LLM
# entirely (which is also the outage path's contract), and they bound what
# a model may "parameterize": a returned command must either be a
# vocabulary entry verbatim or start with one of these tokens. The extra
# tokens beyond the vocabulary are the rest of mod-playerbots' common chat
# grammar, so power users typing raw commands keep their pre-#2600
# behavior instead of detouring through the model.
RAW_STARTERS = {v.split()[0] for v in VOCABULARY} | {
    "co", "cast", "castnc", "e", "ue", "equip", "unequip", "talk", "accept",
    "reward", "release", "revive", "emote", "q", "ll", "c", "s", "b", "bank",
    "gb", "rtsc", "rti", "focus", "playerbot", "tank", "heal", "dps", "say",
    "unmount", "formation", "stance", "give", "trainer", "maintenance",
}


@dataclass(frozen=True)
class Decision:
    command: str | None
    say: str


def is_raw_command(text: str) -> bool:
    first = text.split()[0].lower() if text.split() else ""
    return first in RAW_STARTERS


def build_prompt(*, name: str, level: int, race_name: str, class_name: str,
                 zone: str, personality: str | None, text: str) -> str:
    vocab = "\n".join(f"  {cmd} - {what}" for cmd, what in VOCABULARY.items())
    persona = f" Personality: {personality}." if personality else ""
    return (
        f"You are {name}, a level {level} {race_name} {class_name} standing in "
        f"{zone}, a character in World of Warcraft.{persona}\n"
        f"The Overseer commands you: \"{text}\"\n\n"
        "Pick the ONE command from this list that best fulfils the order:\n"
        f"{vocab}\n\n"
        "Answer with ONLY a JSON object, no other text:\n"
        '{"command": "<exactly one command from the list, or none>", '
        '"say": "<your reply, in character, one or two short sentences>"}\n'
        "If no command fits, use \"none\" and refuse in character."
    )


def parse_decision(content: str) -> Decision:
    """Validate whatever the model said into a safe Decision.

    The gate is select-and-parameterize, per infra#2600: a command must be
    a vocabulary entry verbatim, OR start with a known raw token and pass
    the charset (e.g. "co +grind,-loot"). A charset alone is not enough -
    it would let the model invent well-formed strings the vocabulary never
    sanctioned. Everything else degrades to words with no command row.
    """
    # Reasoning models narrate before they answer, and the narration can
    # contain braces. The answer is the LAST well-formed object, so walk the
    # candidates from the end (live-found 2026-08-21: a greedy first-to-last
    # brace match swallowed the think-aloud preamble and parsed nothing).
    data = None
    for candidate in reversed(re.findall(r"\{[^{}]*\}", content)):
        try:
            data = json.loads(candidate)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        return Decision(None, "The voice mumbles something I cannot make out.")
    say = str(data.get("say", "")).strip()[:MAX_SAY] or "..."
    command = str(data.get("command", "none")).strip().lower()
    if command in ("", "none"):
        return Decision(None, say)
    if command in VOCABULARY:
        return Decision(command, say)
    # Parameterized form: a known raw token, then charset-clean arguments.
    if _COMMAND_RE.fullmatch(command) and command.split()[0] in RAW_STARTERS:
        return Decision(command, say)
    return Decision(None, say)
