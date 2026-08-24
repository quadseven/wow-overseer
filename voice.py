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
    # "sell junk" IS NOT A COMMAND. mod-playerbots' SellAction accepts
    # gray/*/vendor/[item link] and nothing else - "junk" fell through to the
    # item-name branch, matched no item, sold nothing, and RETURNED TRUE. So it
    # reported delivered, the character announced it was on its way, and not one
    # grey item ever left a bag. Evan watched this twice.
    "sell gray": "sell grey items at the next vendor",
    "sell vendor": "sell everything worth vendoring, not only greys",
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
# Multi-word vocabulary entries must be matched WHOLE. Deriving starters by
# splitting them - which this did - reduces "sell gray" to the bare token
# "sell", and the parameterize branch below then happily accepts "sell junk":
# the exact string documented twenty lines above as NOT A COMMAND, which sells
# nothing and returns TRUE. The guard's own allowlist was re-admitting the
# footgun the comment warns about. Live-found 2026-08-24: rows 856-859 sent
# "sell junk" to four characters, all status `delivered`, nothing sold.
MULTIWORD = frozenset(v for v in VOCABULARY if " " in v)

# Only genuinely single-word entries may start a raw command on their own. The
# extra tokens are the rest of mod-playerbots' common chat grammar, so power
# users typing raw commands keep their pre-#2600 behavior.
RAW_STARTERS = {v for v in VOCABULARY if " " not in v} | {
    "co", "cast", "castnc", "e", "ue", "equip", "unequip", "talk", "accept",
    "reward", "release", "revive", "emote", "q", "ll", "c", "s", "b", "bank",
    "gb", "rtsc", "rti", "focus", "playerbot", "tank", "heal", "dps", "say",
    "unmount", "formation", "stance", "give", "trainer", "maintenance",
}


def _starts_with_multiword(command: str) -> bool:
    """Is this a whole multi-word entry, optionally with arguments after it?

    "drop quest Foo" yes, "sell gray" yes, "sell junk" NO - because "sell"
    alone was never a command and must not behave like one.
    """
    return any(command == m or command.startswith(m + " ") for m in MULTIWORD)


@dataclass(frozen=True)
class Decision:
    command: str | None
    say: str


def is_raw_command(text: str) -> bool:
    normalised = " ".join(text.split()).lower()
    if not normalised:
        return False
    if _starts_with_multiword(normalised):
        return True
    return normalised.split()[0] in RAW_STARTERS


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
    if _COMMAND_RE.fullmatch(command) and (
            command.split()[0] in RAW_STARTERS or _starts_with_multiword(command)):
        return Decision(command, say)
    return Decision(None, say)
