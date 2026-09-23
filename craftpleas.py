"""Turning a need into a name (infra#2829).

Pure module, same seam as kin.py: a chat line goes in, and a typed Ask comes
out naming who the family already decided handles that need. No SQL, no
Discord, no LLM below this line - `_in_character` is what puts a voice on the
answer, exactly as it puts one on every other line this project speaks in
party chat.

WHY THIS EXISTS. The operator rejected #2823 for materialising a bag out of nowhere -
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

WHAT WENT WRONG ON STREAM, AND WHAT IT CHANGED HERE (infra#3197). Three
faults, all of them in this file, all of them visible in one screenful:

    [Party] [Grog]: Grog give Og 20 Linen Cloth. Og need it for tailoring.
    [Party] [Og]:   Grog need cloth? Og know tailoring. Og make it, family
                    just bring the stuff.
    [Party] [Og]:   Og need cloth? Og know tailoring. Og make it, family
                    just bring the stuff.                     ... x58

  1. A HANDOVER IS NOT A REQUEST. materials.py's own line says "give" and
     "need" in one sentence, so `_NEED_RE` matched the announcement of a
     stack ARRIVING and answered it as though somebody had asked for one.
  2. AN ANSWER IS NOT A NEW ASK. Og's reply names cloth and contains "need",
     so it parsed as a fresh ask whose crafter was Og - Og answering Og,
     forever. `parse_ask` now refuses an ask whose crafter is the speaker
     (chat.addressed_to_self), which breaks the loop at its source.
  3. OG DOES NOT KNOW TAILORING. `professions.crafter_for` answers "who is
     ASSIGNED this trade", and this module read it as "who can make this".
     Verified live: `overseer_trade` holds `learn tailoring` at 'planned'
     since 2026-08-26 and `character_skills` gives Og herbalism only. So
     `answer` now takes the live skills and says the true thing or nothing
     at all - see mod-overseer#160, #167 and #168 for why the learn has
     never happened.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import chat
import professions

# What a product word most likely means, matched as a whole word. Grounded in
# the `why` text professions.ROSTER already carries for each assignment - Og's
# row calls tailoring "the family's BAG problem", Ugga's calls alchemy
# "potions and elixirs" - restated here as a lookup rather than invented
# fresh. Deliberately small: a product not listed gets no answer, exactly as
# professions.UNASSIGNED leaves inscription and jewelcrafting unclaimed
# rather than guessed at. "glyph", "gem" and "ring" stay in this table on
# purpose even though nobody is assigned either trade right now: they are
# still real product words, and professions.crafter_for already answers ""
# for them, so parse_ask correctly finds no ask rather than this table
# needing to know who, if anybody, currently holds the trade.
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

# A request, however the family phrases it: The operator's own example is caveman
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

# A HANDOVER IS NOT A REQUEST (infra#3197). materials.py announces a stack
# moving in one sentence that carries both trigger words:
#
#     Grog give Og 20 Linen Cloth. Og need it for tailoring.
#
# and `_NEED_RE` matched it, so the family answered the delivery of cloth as
# though somebody had asked for cloth. Anchored on the SPEAKER's own name so
# it only ever silences a character narrating their own handover: "Og give me
# cloth?" from anybody else is still a request and still gets an answer.
_GIVING_RE = re.compile(
    r"^\s*(?P<who>[A-Za-z]{2,12})\s+(?:give|gives|hand|hands|handing)\b", re.I
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
    handing = _GIVING_RE.match(line)
    if handing and handing.group("who").casefold() == speaker.casefold():
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
    # NOBODY ANSWERS THEMSELVES. This is the loop that put one sentence on
    # screen 58 times: the crafter's own answer names the product and carries
    # "need", so it parsed as a new ask whose crafter was the speaker again.
    # Refusing here rather than in `answer` means the line is never even
    # considered, which is also the honest reading - a character saying it
    # wants cloth is not a character asking itself to make some.
    if chat.addressed_to_self(crafter, speaker):
        return None
    return Ask(asker=speaker, product=product, skill=skill, crafter=crafter)


def ask_key(ask: Ask) -> tuple:
    """What this exchange IS, for the say-it-once ledger.

    The crafter, the trade, and who asked. Not the product and not the
    sentence: "bag", "bags" and "robe" are one conversation about tailoring
    with Grug, and answering each of them separately is the same wall of
    text with three nouns in it.
    """
    return chat.say_key(speaker=ask.crafter, subject=ask.skill, listener=ask.asker)


def state(ask: Ask, held: Mapping) -> str:
    """Does the named crafter actually have the trade they are about to claim?

    `held` is name -> the professions `character_skills` gives them, read at
    the moment of speaking. The PLAN comes from professions.assigned, which
    is what ROSTER means and all `crafter_for` ever knew - keeping the two
    apart here is the whole fix for "Og know tailoring".
    """
    return chat.skill_state(
        ask.crafter,
        ask.skill,
        held=held,
        planned={ask.crafter: professions.assigned(ask.crafter)},
    )


def answer(ask: Ask, *, held: Mapping) -> str:
    """What the crafter says back, or "" when there is nothing true to say.

    `held` IS REQUIRED, and that is the point of the signature. This used to
    be `answer(ask)`, and with no way to ask what a character can actually do
    it had no way to be anything but a boast:

        Og need cloth? Og know tailoring. Og make it, family just bring the
        stuff.

    Og has never had tailoring. So the three states get three answers: the
    trade in hand accepts, a trade the family has only DECIDED on says so
    plainly, and a trade nobody is getting says nothing at all. Silence is a
    real answer here - the alternative is a sentence a viewer cannot tell is
    false, which is worse than a question going unanswered.

    Still never a refusal on the crafter's behalf, and still never followed
    by the thing appearing: see the module docstring for both.
    """
    how = state(ask, held)
    if how == chat.HELD:
        return (
            f"{ask.asker} need {ask.product}? {ask.crafter} know {ask.skill}. "
            f"{ask.crafter} make it, family just bring the stuff."
        )
    if how == chat.LEARNING:
        return (
            f"{ask.asker} need {ask.product}? {ask.crafter} no know "
            f"{ask.skill} yet. {ask.crafter} learning it."
        )
    return ""
