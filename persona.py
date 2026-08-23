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
    "Rules: say your own name instead of \"I\". Drop the words \"a\", "
    "\"an\" and \"the\". Use \"no\" instead of \"do not\" or \"does "
    "not\". Short words only. Never sound clever or modern."
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
        lines.append(
            f"  {other} - {bond.role}, a {bond.char_class}")
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
        f"  \"{plain}\"\n\n"
        "Say the SAME thing in caveman talk, in your own voice. Keep the meaning "
        "exactly - if it names a person, a number or a place, keep them. One "
        "short sentence.\n"
        "Answer with the sentence and nothing else."
    )


_STRIP_QUOTES = re.compile(r'^[\s"\'`*]+|[\s"\'`*]+$')
_STAGE = re.compile(r"^\s*[\(\[*].*?[\)\]*]\s*")


def clean(said: str, plain: str) -> str:
    """Whatever the model returned, made safe to speak - or the plain line.

    Falls back rather than repairing. A line that arrives empty, enormous, or
    wearing narration is a line the model did not really produce, and speaking
    a mangled version of it is worse than speaking the plain one: the plain one
    is at least true to the plan.
    """
    if not said:
        return plain

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

    if not text or len(text) > MAX_SPOKEN:
        return plain
    return text
