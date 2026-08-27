"""Turning a need into a name (infra#2829).

Pure module, same seam as kin.py: a chat line goes in, and a typed Ask comes
out naming who the family already decided handles that need. No SQL, no
Discord, no LLM below this line - `_in_character` is what puts a voice on the
answer, exactly as it puts one on every other line this project speaks in
party chat.

WHY THIS EXISTS. Evan rejected #2823 for materialising a bag out of nowhere -
"they should know each others skills and professions and be able to ask Ugga
or Og whoever gets tailoring to make a bag." The knowledge already existed:
professions.ROSTER assigns Og tailoring for exactly this reason (its own
`why` calls tailoring "the family's BAG problem"). What was missing was not
the decision, it was somebody SAYING it when somebody else asked - the family
could not answer a question it was never asked, and nothing outside the
Python process could put that question to professions.ROSTER at all.

WHAT THIS DOES NOT DO, AND WHY IT IS HONEST ABOUT THAT. It never crafts
anything - mod-overseer has no verb that turns a tradeskill into an item, so
an "accept" here can never be followed by a bag actually appearing. That is
new C++ work (a real TradeSkill cast, the same "no magic" bar #2597's DoGive
and #2757's TrainOnArrival were held to), and it is out of scope for this
module. It also never REFUSES on the crafter's behalf: this module has no
visibility into what the crafter is currently carrying - materials.py knows
that, one process boundary away, on its own cycle - and a false "I have
nothing" is a worse failure than an accept the crafter cannot yet honour.
Both gaps are said here rather than routed around, the same way
professions.BLOCKERS says what its own module still needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import professions

# What a product word most likely means, matched as a whole word. Grounded in
# the `why` text professions.ROSTER already carries for each assignment - Og's
# row calls tailoring "the family's BAG problem", Ugga's calls alchemy
# "potions and elixirs", Grog's calls inscription "glyphs" - restated here as
# a lookup rather than invented fresh. Deliberately small: a product not
# listed gets no answer, exactly as professions.UNASSIGNED leaves engineering
# unclaimed rather than guessed at.
PRODUCTS = {
    "bag": "tailoring",
    "bags": "tailoring",
    "robe": "tailoring",
    "cloth": "tailoring",
    "potion": "alchemy",
    "potions": "alchemy",
    "elixir": "alchemy",
    "elixirs": "alchemy",
    "flask": "alchemy",
    "armor": "blacksmithing",
    "armour": "blacksmithing",
    "plate": "blacksmithing",
    "sword": "blacksmithing",
    "weapon": "blacksmithing",
    "leather armor": "leatherworking",
    "leathers": "leatherworking",
    "enchant": "enchanting",
    "enchantment": "enchanting",
    "glyph": "inscription",
    "glyphs": "inscription",
    "gem": "jewelcrafting",
    "gems": "jewelcrafting",
    "ring": "jewelcrafting",
}

# A request, however the family phrases it: Evan's own example is caveman
# grammar ("Ugga make bag?"), and so is professions.py's own `said` text
# ("Family need tailoring"). "make" alone is included, not only "need" and
# "want", because that caveman form has no "need" in it at all.
# `s?` on every trigger word: "Grug need bag" is the caveman form and
# "Grug needs a bag" is the same request in a third person's mouth, and
# neither should be missed for want of a plural.
_NEED_RE = re.compile(
    r"""\b(?:
        needs? | wants?
      | who \s+ (?: can \s+ )? makes?
      | can \s+ (?: you | someone | anyone | somebody ) \s+ make
      | makes?
    )\b""",
    re.I | re.X,
)

# The same negation shape kin._NEGATIVE_RE guards with, aimed at this
# module's own trigger words instead of "help".
_NEGATIVE_RE = re.compile(
    r"""\b(?:
        no | not | never | nobody | noone | none
      | don'?t | doesn'?t | didn'?t
      | can'?t | cannot | won'?t | wouldn'?t | couldn'?t | shouldn'?t
    )\b (?:\W+\w+){0,3}? \W+ (?:needs?|wants?|makes?)\b""",
    re.I | re.X,
)


@dataclass(frozen=True)
class Ask:
    asker: str
    product: str
    skill: str
    crafter: str


def _find_product(text: str) -> str:
    """The first PRODUCTS word this line names.

    Longest key first, so "leather armor" is matched whole rather than being
    shadowed by the bare "armor" sitting inside it.
    """
    lowered = text.lower()
    for word in sorted(PRODUCTS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return word
    return ""


def parse_ask(speaker: str, text: str) -> Ask | None:
    """Is this line someone asking the family for a crafted thing?

    Returns None for anything ambiguous, or for a product this module has no
    opinion about - the same bar kin.parse_plea sets for a plea: a false
    positive here is a fabricated voice line in party chat, so silence is the
    safe failure and not a guess.
    """
    speaker = (speaker or "").strip()
    line = (text or "").strip()
    if not speaker or not line:
        return None
    if _NEGATIVE_RE.search(line):
        return None
    if not _NEED_RE.search(line):
        return None
    product = _find_product(line)
    if not product:
        return None
    skill = PRODUCTS[product]
    crafter = professions.crafter_for(skill)
    if not crafter:
        return None
    return Ask(asker=speaker, product=product, skill=skill, crafter=crafter)


def answer(ask: Ask) -> str:
    """What the crafter says back.

    Always an accept - see the module docstring for why this cannot yet be a
    refusal or a "bring me more X", and cannot yet be followed by the thing
    actually appearing.
    """
    return (
        f"{ask.asker} need {ask.product}? {ask.crafter} know {ask.skill}. "
        f"{ask.crafter} make it, family just bring the stuff."
    )
