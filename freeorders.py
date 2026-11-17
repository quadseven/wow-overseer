"""Free-phrased Discord orders, through the local model (#1501).

quadseven/mod-overseer#150 asks that an operator can type a sentence ("run
Deadmines until the Red Defias Mask drops", "go level Grug to 40") and have it
become the right rows. The bridge's fixed forms ("queue ...", "@Name reach
level N") stay the only way a row is written. This module only TRANSLATES: the
model answers with one small JSON tool call, and a tool call becomes the SAME
directive a typed fixed form would have produced, so the existing writer
(`_set_queue`, the goal path) validates it with its own rules and a tool call
can never write a row a typed form could not.

THREE TOOLS, AND NO FARM TOOL. There is no family-scoped farm writer
(jobs.py leaves `farm` out of IMPLEMENTED), so a model tool cannot honestly map
onto one. A farm phrasing is answered with a sentence saying so and writes
nothing, whether the model names the tool or the operator's own words say it.

- campaign: a family runs a dungeon N times, or until an item drops. Becomes a
  QueueDirective, the text `campaignqueue.parse_entries` already reads.
- level: a member is taken to a level. Becomes the NLDirective
  "reach level N", which the goal path already reads.
- ask: the model needs one more fact. Becomes a Reply and writes nothing.

AN UNKNOWN MEMBER OR FAMILY WRITES NOTHING AND ASKS. The model is never trusted
to spell a name: every name is matched against the roster here, and an item is
resolved by `_set_queue` against the item catalog, which refuses an unknown or
ambiguous one before anything is written.

PURE MODULE: no MySQL, no Discord, no model call. The bridge asks the model
and hands the raw reply here.
"""

from __future__ import annotations

import json
import re

import campaignqueue
import core
import goals

# A message is only worth a model call when it reads like an order. Chatter in
# the overseer's channel keeps the help reply it always had.
_ORDER_WORDS = re.compile(
    r"\b(?:run|runs|farm|farming|go|clear|level|until|drop|drops|grind)\b",
    re.IGNORECASE,
)
_FARM = re.compile(r"\bfarm(?:ing)?\b", re.IGNORECASE)

MAX_TEXT = 400
_FAMILY = re.compile(r"^[A-Za-z]{2,32}$")
_DUNGEON = re.compile(r"^[A-Za-z' ]{2,40}$")
_ITEM = re.compile(r"^[A-Za-z0-9' ,:\-]{2,80}$")

FARM_REFUSAL = (
    "Farming orders are not supported yet, so nothing was written. "
    'You can ask for a dungeon: "run Deadmines 5 times", or a level: '
    '"level Grug to 40".'
)
NOT_UNDERSTOOD = (
    "I did not understand that as an order, so nothing was written. "
    'Use a fixed form: "queue <family>: ragefire 5" or '
    '"@Name reach level 40". ' + core.USAGE
)

SYSTEM = "Answer with one JSON object only. No reasoning, no preamble."


def looks_like_an_order(text: str) -> bool:
    """Whether a message that matched no fixed form is worth asking the model."""
    text = str(text or "")
    return 0 < len(text) <= MAX_TEXT and _ORDER_WORDS.search(text) is not None


def is_farm(text: str) -> bool:
    return _FARM.search(str(text or "")) is not None


def build_prompt(text: str, families: dict) -> str:
    """The prompt: the sentence, the tools, and the names the model may use."""
    family_lines = (
        "; ".join(
            "%s (members: %s)" % (key or "(unnamed)", ", ".join(info["names"]))
            for key, info in sorted(families.items())
        )
        or "none"
    )
    return (
        "An operator gave this order to a family of game characters:\n"
        "%s\n\n"
        "Families: %s\n\n"
        "Answer with ONE JSON object naming a tool:\n"
        '{"tool":"campaign","family":"<family or empty>","dungeon":"<dungeon name>",'
        '"runs":<number of runs, or 0 when waiting for an item>,'
        '"item":"<item name, or empty>"}\n'
        '{"tool":"level","member":"<character name>","level":<target level>}\n'
        '{"tool":"ask","question":"<one short question when a fact is missing>"}\n'
        "Use only the family and character names listed. If the order is "
        "about farming, or a name or number is missing, use the ask tool."
        % (str(text).strip()[:MAX_TEXT], family_lines)
    )


def parse_reply(raw: str) -> dict | None:
    """The LAST JSON object in a reply, or None. A reasoning model may think
    aloud first and answer last, so the last object is the answer."""
    decoder = json.JSONDecoder()
    found = None
    text = str(raw or "")
    index = text.find("{")
    while index != -1:
        try:
            obj, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(obj, dict):
            found = obj
        index = text.find("{", end)
    return found


def _match(asked: str, names) -> str:
    for name in names:
        if name.casefold() == asked.casefold():
            return name
    return ""


def _campaign(call: dict, source: str, families: dict) -> tuple:
    family = str(call.get("family") or "").strip()
    dungeon = str(call.get("dungeon") or "").strip()
    item = str(call.get("item") or "").strip()
    try:
        runs = int(call.get("runs") or 0)
    except (TypeError, ValueError):
        return [core.Reply("How many runs? Nothing was written.")], ""
    if family and not _FAMILY.match(family):
        return [core.Reply("Which family? Nothing was written.")], ""
    if family:
        key = _match(family, families)
        if not key:
            return [
                core.Reply(
                    "%s is not a family on the roster. The families are: %s. "
                    "Nothing was written."
                    % (family, ", ".join(sorted(families)) or "none")
                )
            ], ""
        family = key
    if not _DUNGEON.match(dungeon):
        return [core.Reply("Which dungeon? Nothing was written.")], ""
    if item:
        if not _ITEM.match(item):
            return [core.Reply("Which item? Nothing was written.")], ""
        count = " %d" % runs if runs > 0 else ""
        text = "%s%s until %s drops" % (dungeon, count, item)
    else:
        if not 0 < runs <= campaignqueue.RUNS_CEILING:
            return [
                core.Reply("How many runs of %s? Nothing was written." % dungeon)
            ], ""
        text = "%s %d" % (dungeon, runs)
    # The directive is built exactly as core._unaddressed builds it from a
    # typed "queue <family>: <text>", so the same writer validates it.
    directive = core.QueueDirective(family=family, text=text, source=source)
    heard = "queue %s: %s" % (family, text) if family else "queue %s" % text
    return [directive], heard


def _level(call: dict, source: str, families: dict) -> tuple:
    member = str(call.get("member") or "").strip()
    try:
        level = int(call.get("level"))
    except (TypeError, ValueError):
        return [core.Reply("To which level? Nothing was written.")], ""
    names = sorted({n for info in families.values() for n in info["names"]})
    key = _match(member, names) if core._NAME_RE.match(member) else ""
    if not key:
        return [
            core.Reply(
                "I do not know a character called %s. Nothing was written. "
                "Members: %s." % (member or "(none)", ", ".join(names) or "none")
            )
        ], ""
    if not 2 <= level <= goals.MAX_LEVEL:
        return [
            core.Reply(
                "A level target is 2 to %d. Nothing was written." % goals.MAX_LEVEL
            )
        ], ""
    directive = core.NLDirective(key, "reach level %d" % level, source)
    return [directive], "@%s reach level %d" % (key, level)


def decisions(raw: str, original: str, source: str, families: dict) -> tuple:
    """(decisions, heard) for one model reply.

    `heard` is the fixed form the reply was turned into, for the bridge to
    echo before the writer's own answer; "" when no row can follow. A farm
    phrasing, an unreadable reply, an unknown tool and a tool naming something
    that is not on the roster all end in a Reply and no directive.
    """
    if is_farm(original):
        return [core.Reply(FARM_REFUSAL)], ""
    call = parse_reply(raw)
    if call is None:
        return [core.Reply(NOT_UNDERSTOOD)], ""
    tool = str(call.get("tool") or "").strip().lower()
    if tool == "campaign":
        return _campaign(call, source, families)
    if tool == "level":
        return _level(call, source, families)
    if tool == "farm":
        return [core.Reply(FARM_REFUSAL)], ""
    if tool == "ask":
        question = " ".join(str(call.get("question") or "").split())[:300]
        return [
            core.Reply(
                (question or "Which dungeon, or which character?")
                + " Nothing was written."
            )
        ], ""
    return [core.Reply(NOT_UNDERSTOOD)], ""
