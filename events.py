"""The world narrates itself: snapshot deltas in, in-character thoughts out.

Pure module (infra#2602). Event detection is nothing but delta logic over
two consecutive snapshot polls - the LLM never decides WHAT happened, it
only voices it, and every voicing helper here (prompt building, response
parsing, templated fallback) is a pure function so the whole pipeline is
testable with canned data. Two invariants the bridge relies on:

- An event thought is NEVER dropped because the LLM failed or the voice cap
  was hit - overflow and outages degrade to template_line(), which always
  produces a usable sentence.
- Appearance/disappearance of a character between polls is churn (logins,
  snapshot staleness), never story: only characters present in BOTH polls
  can emit events, which also makes the first poll (empty prev) silent -
  a bridge restart must not narrate 500 "arrivals".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from voice import MAX_SAY

# Lower number wins the bounded LLM voice budget. Level ups are the rarest
# and most story-shaped, so they outrank everything; combat toggles are the
# noisiest (500 grinding bots flip in_combat constantly), so they lose the
# budget first and land as templated lines instead.
PRIORITY = {
    "level_up": 0,
    "death": 1,
    "zone_change": 2,
    "combat_survived": 3,
    "combat_entered": 4,
}


@dataclass(frozen=True)
class Event:
    kind: str
    name: str
    data: dict = field(default_factory=dict)


def _sort_key(event: Event) -> tuple[int, str, str]:
    # Name then kind as tie-breakers: the cap split must be deterministic
    # so a test (and an operator reading logs) can predict who got voiced.
    return (PRIORITY[event.kind], event.name, event.kind)


def detect_events(prev: dict[str, dict], curr: dict[str, dict], geo) -> list[Event]:
    """Diff two name-keyed snapshot polls into a priority-sorted event list.

    `geo` is anything with transform.Geometry's zone_name(map_id, x, y) -
    zone CHANGE is detected on the zone_id column (the database's truth),
    but the story wants zone NAMES, which only geometry can supply.
    """
    events: list[Event] = []
    for name, row in curr.items():
        before = prev.get(name)
        if before is None:
            continue
        if row["level"] > before["level"]:
            events.append(Event("level_up", name, {"level": row["level"]}))
        if row["zone_id"] != before["zone_id"]:
            from_zone = geo.zone_name(
                before["map_id"], before["pos_x"], before["pos_y"]
            )
            to_zone = geo.zone_name(row["map_id"], row["pos_x"], row["pos_y"])
            # zones.json rectangles are coarser than zone_id; a transition
            # that resolves to the same name would narrate "left X for X",
            # which reads as a glitch rather than a journey. Skip those.
            if from_zone != to_zone:
                events.append(
                    Event(
                        "zone_change",
                        name,
                        {"from_zone": from_zone, "to_zone": to_zone},
                    )
                )
        died = before["health"] > 0 and row["health"] <= 0
        if died:
            events.append(Event("death", name))
        if not before["in_combat"] and row["in_combat"]:
            events.append(Event("combat_entered", name))
        # Leaving combat at zero health is the death above, not a survival.
        if before["in_combat"] and not row["in_combat"] and row["health"] > 0:
            events.append(Event("combat_survived", name))
    return sorted(events, key=_sort_key)


# Kinds that are always story: they mark a character's arc. Combat is the
# world's heartbeat - it fires constantly for 500 bots and buries the arc
# (live, one hour after #2602 shipped: 508 of 727 event thoughts were
# combat, against 20 level ups). Death stays for everyone; dying is a story
# whoever you are.
STORY_ALWAYS = frozenset({"level_up", "zone_change", "death"})


def filter_for_story(events: list, notable: frozenset) -> list:
    """Drop the heartbeat for characters nobody is following.

    `notable` is the set of names the overseer cares about - mortals, the
    reserved characters, and anyone under an active goal. Order is
    preserved so downstream priority sorting is unaffected.
    """
    lowered = {n.lower() for n in notable}
    return [e for e in events if e.kind in STORY_ALWAYS or e.name.lower() in lowered]


def split_for_voicing(events: list[Event], cap: int) -> tuple[list[Event], list[Event]]:
    """(voiced, overflow): the first `cap` events by priority get LLM voice.

    This is the per-cycle bound that keeps 500 bots from flooding the
    gateway - overflow events still become thoughts, just templated ones.
    """
    cap = max(cap, 0)
    return events[:cap], events[cap:]


def describe(event: Event) -> str:
    """Third-person clause handed to the model - data given, never asked."""
    if event.kind == "level_up":
        return f"reached level {event.data['level']}"
    if event.kind == "zone_change":
        return f"crossed from {event.data['from_zone']} into {event.data['to_zone']}"
    if event.kind == "death":
        return "collapsed, beaten down to nothing"
    if event.kind == "combat_entered":
        return "was drawn into combat"
    return "survived a fight"


def template_line(event: Event) -> str:
    """The plain narration an event falls back to. Always usable, never fails."""
    if event.kind == "level_up":
        return f"{event.name} reached level {event.data['level']}."
    if event.kind == "zone_change":
        return f"{event.name} crossed into {event.data['to_zone']}."
    if event.kind == "death":
        return f"{event.name} fell in battle."
    if event.kind == "combat_entered":
        return f"{event.name} entered combat."
    return f"{event.name} survived the fight."


def build_batch_prompt(events: list[Event]) -> str:
    """One prompt for the whole batch - one LLM call per cycle, not per event."""
    payload = json.dumps([{"name": e.name, "event": describe(e)} for e in events])
    return (
        "You narrate the inner lives of World of Warcraft characters. "
        "These things just happened, one entry per event:\n"
        f"{payload}\n\n"
        "For EACH event, write that character's own thought about it: first "
        "person, in character, one short sentence.\n"
        "Answer with ONLY a JSON array in the same order, no other text:\n"
        '[{"name": "<character name exactly as given>", "say": "<the thought>"}]'
    )


def _final_json_value(content: str):
    """The LAST top-level JSON value in the text, or None.

    Reasoning models narrate before they answer (same live finding that
    shaped voice.parse_decision), and the narration can contain braces or
    even small well-formed JSON. Decoding forward and skipping each decoded
    span keeps nested values from shadowing the real answer: the final
    top-level value is the model's answer.
    """
    decoder = json.JSONDecoder()
    value = None
    i = 0
    while i < len(content):
        if content[i] in "[{":
            try:
                value, end = decoder.raw_decode(content, i)
                i = end
                continue
            except ValueError:
                pass
        i += 1
    return value


def voice_events(events: list[Event], content: str) -> list[str]:
    """Model output -> one thought per event, aligned with `events`.

    Defensive by contract: any event the model skipped, garbled, or that the
    parse could not recover degrades to template_line() - the thought still
    lands. A character with several events in one batch consumes the model's
    lines for that name in order.
    """
    data = _final_json_value(content)
    if isinstance(data, dict):
        data = [data]
    sayings: dict[str, list[str]] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            say = str(item.get("say", "")).strip()[:MAX_SAY]
            if name and say:
                sayings.setdefault(name, []).append(say)
    out = []
    for event in events:
        queue = sayings.get(event.name)
        out.append(queue.pop(0) if queue else template_line(event))
    return out
