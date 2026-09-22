"""Say the line in character. Never decide anything.

The family's plans are made by rules - council.py picks what the day is for,
bonds.py decides who turns out for whom - and those rules run to completion
before this module is asked anything. That ordering is the whole design: a
model that is offline, slow, or having a bad day costs the family its VOICE
and never its plan. There is always a line to fall back on, because the plain
line is what was going to be said anyway.

WHY THE PERSONAS MATTER MECHANICALLY. bonds.py already had Grug refuse to
answer Ugga once Og had answered her too often. The sulk was in the rules
before it had a reason. The reason is now written down (bonds.SUSPICION), and
grounding the voice on it is what turns a threshold into a scene: the father
counts, and cannot say why he is counting.

WHAT THE MODEL IS NEVER TOLD. That the affair is real. Grug SUSPECTS. A
suspicion nobody can prove is a better engine than a confirmed fact, and it
keeps the model from writing the confrontation the rules cannot deliver.
"""

from __future__ import annotations

import json
import re

import bonds

# Long enough to have a voice, short enough to read as speech in a chat window
# rather than as prose. WoW itself will not carry much more than this in one
# line anyway.
MAX_SPOKEN = 180

# The house voice, taken from Evan's grug project rather than invented. All
# five talk this way - that is WHY they are human cavemen, and the two boys are
# a dwarf and a gnome only because those models are short enough to read as
# children.
#
# It also does real work: the personas differed only by role at first, and five
# characters produced five near-identical sentences. A shared register plus
# distinct personalities separates them far better than five polite
# descriptions of a family did.
GRUG_VOICE = (
    "HOW YOU TALK. You are a caveman. Speak like this:\n"
    "  Grug know fire good.\n"
    "  Grug no like.\n"
    "  Grug club wolf into next cave!\n"
    "  Grug no understand.\n"
    'Rules: say your own name instead of "I". Drop the words "a", '
    '"an" and "the". Use "no" instead of "do not" or "does '
    'not". Short words only. Never sound clever or modern.'
)


def _relationships(speaker: str) -> str:
    """How the speaker stands to everyone else, in their own terms."""
    me = bonds.member(speaker)
    if me is None:
        return ""
    lines = []
    for other, bond in bonds.FAMILY.items():
        if other == speaker:
            continue
        lines.append(f"  {other} - {bond.role}, a {bond.char_class}")
    return "\n".join(lines)


def build_prompt(speaker: str, plain: str, *, context: str = "") -> str | None:
    """The prompt that turns a decided line into that character saying it.

    Returns None for anyone outside the family: this module has personas for
    five characters and no business putting words in anyone else's mouth.

    The plain line is given as the MEANING, not as a draft to improve. The
    model's only job is to say that meaning as this character would - so a
    model that ignores the instruction and rewrites the sense is caught by
    the caller keeping the plan, not the words.
    """
    bond = bonds.member(speaker)
    if bond is None:
        return None

    canonical = bonds.canon(speaker)
    suspicion = ""
    if canonical == bonds.SUSPICION["who"]:
        suspicion = "\nSomething you carry: " + bonds.SUSPICION["note"] + "\n"

    return (
        f"You are {canonical}, a {bond.gender} {bond.char_class} in World of "
        f"Warcraft. You are a CAVEMAN.\n"
        f"You are the {bond.role} of a family of cavemen who travel together.\n"
        f"{bond.persona}\n"
        f"\nThe others:\n{_relationships(canonical)}\n"
        f"{suspicion}"
        f"{chr(10) + 'What is happening: ' + context + chr(10) if context else ''}"
        f"\n{GRUG_VOICE}\n"
        f"\nYou are about to say this to your family:\n"
        f'  "{plain}"\n\n'
        "Say the SAME thing in caveman talk, in your own voice. Keep the meaning "
        "exactly - if it names a person, a number or a place, keep them. One "
        "short sentence.\n"
        "Answer with the sentence and nothing else."
    )


# A model asked for a sentence sometimes answers with an object anyway. These
# are the keys it actually reached for, live, before this was caught.
_SPOKEN_KEYS = ("response", "sentence", "say", "text", "line", "answer")


def _from_json(text: str) -> str | None:
    """The sentence inside an object, if that is what arrived.

    Live, in Evan's Discord, spoken aloud in game:

        [Party] Bork: {"response": "Bork no need do thing. Bork go fish!"}
        [Party] Og:   {"sentence": "Og help Grug."}
        [Party] Grug: }

    The last one is the worst: a pretty-printed object whose final line is a
    lone brace, taken by a cleaner that reads the last line. Answering in JSON
    is not the failure - failing to notice is.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    for key in _SPOKEN_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # An object with no sentence in it. Whatever it is, it is not speech.
    return ""


_STRIP_QUOTES = re.compile(r'^[\s"\'`*]+|[\s"\'`*]+$')
_STAGE = re.compile(r"^\s*[\(\[*].*?[\)\]*]\s*")
# A line that is only punctuation is a fragment of something, never a sentence.
_ALL_PUNCTUATION = re.compile(r"^[^\w]*$")


def clean(said: str, plain: str) -> str:
    """Whatever the model returned, made safe to speak - or the plain line.

    Falls back rather than repairing. A line that arrives empty, enormous, or
    wearing narration is a line the model did not really produce, and speaking
    a mangled version of it is worse than speaking the plain one: the plain one
    is at least true to the plan.
    """
    if not said:
        return plain

    # JSON FIRST. Everything below reads line by line, and an object spread
    # over several lines defeats all of it - which is exactly how a lone "}"
    # ended up being said out loud in party chat.
    from_json = _from_json(said)
    if from_json is not None:
        return from_json or plain

    text = said.strip()
    # Reasoning models narrate first and answer last; take the final non-empty
    # line rather than the whole monologue.
    parts = [p.strip() for p in text.splitlines() if p.strip()]
    if not parts:
        return plain
    text = parts[-1]

    text = _STAGE.sub("", text)
    text = _STRIP_QUOTES.sub("", text)
    text = " ".join(text.split())

    if not text or len(text) > MAX_SPOKEN or _ALL_PUNCTUATION.match(text):
        return plain
    return text


def characterisation(name: str) -> str | None:
    """Who this character is, for a prompt this module does not build itself.

    Returns None for anyone outside the family, so a caller can keep whatever
    it had - this module has personas for five characters and no business
    describing anyone else.

    WHY THIS EXISTS. voice.build_prompt was grounded on
    `mod_ollama_chat_personality` instead, which is the table mod-ollama-chat
    fills in for the five hundred random bots. Read live, it holds two rows
    for this family and both are wrong:

        name | ollama_personality
        -----+-------------------
        Bork | ANCIENT_WISE_ONE
        Og   | ANCIENT_WISE_ONE

    and NO row at all for Grug, Ugga or Grog, who were therefore prompted with
    no character whatsoever. So when Evan said "lets go sell junk in town", the
    little brother who is in trouble constantly answered

        "The cycle of commerce must flow. Let us trade these dull relics for
         coin, as the ancients did."

    Bork was not out of character. He was flagged ANCIENT_WISE_ONE and played
    it perfectly. The family's real characterisation is the `persona` Evan
    wrote on each Bond, which build_prompt above has grounded the council on
    since it was written, and which reached the inner voice through nothing.

    GRUG_VOICE comes with it deliberately. The persona is what separates the
    five; the register is what makes them one family, and a persona without it
    is what produced five polite strangers the first time round.
    """
    bond = bonds.member(name)
    if bond is None:
        return None
    return (
        f"You are the {bond.role} of a family of cavemen who travel together.\n"
        f"{bond.persona}\n\n{GRUG_VOICE}"
    )
