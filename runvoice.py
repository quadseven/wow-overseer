"""Party and guild chat during runs: real talk tied to real events.

The family streams show almost entirely system-shaped chat - guild chat only
carries canned looking-for-group lines, and party chat is effectively silent
during dungeon runs. Humans naturally chat about real events happening in
front of them.

This module generates party and guild chat lines driven by actual run events:
- Party chat: boss kills, member deaths, wipes, notable drops, wings finished, long stalls
- Guild chat: epic drops, first boss kills, dings at round numbers, class quest help

Pure module: rows in, chat lines out. No SQL, no HTTP, no clock of its own.
The bridge reads events, calls in here, and writes chat commands.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Collection, Mapping

import chat

# Rarity colors for item links (WoW quality: 0=poor, 1=common, 2=uncommon, 3=rare, 4=epic, 5=legendary)
QUALITY_COLOR = {
    0: "9d9d9d",  # gray
    1: "ffffff",  # white
    2: "1eff00",  # green
    3: "0070dd",  # blue
    4: "a335ee",  # purple
    5: "ff8000",  # orange
}

# How long a run-scoped intent stays said before it may be said again.
# Same as chat.SAY_ONCE_SECONDS but scoped to the run, not global.
RUN_SAY_ONCE_SECONDS = 1800.0


@dataclass(frozen=True)
class RunEvent:
    """A single event from a dungeon run."""

    kind: str
    run_id: int
    character: str | None = None
    boss_name: str | None = None
    item_name: str | None = None
    item_quality: int | None = None
    item_id: int | None = None
    old_item_name: str | None = None
    wing_name: str | None = None
    detail: str = ""


@dataclass
class RunVoiceState:
    """Per-run memory of what has been said, keyed by intent."""

    said: dict[tuple, float] = field(default_factory=dict)
    run_id: int = 0
    started_at: float = field(default_factory=time.monotonic)


def _run_say_key(
    speaker: str,
    subject: str,
    listener: str = "",
    run_id: int = 0,
    per_speaker: bool = True,
) -> tuple:
    """What a line MEANS for run-scoped deduplication.

    Includes run_id in the key so the same line can be said in different runs.
    If per_speaker=False, the key is shared across all speakers (party-wide deduplication).
    """
    if per_speaker:
        base = chat.say_key(speaker=speaker, subject=subject, listener=listener)
    else:
        # Party-wide: key doesn't include speaker, so any party member saying it blocks others
        base = (subject.strip().casefold(), listener.strip().casefold())
    # Add run_id to scope deduplication to this run
    return base + (str(run_id),)


def should_say_run(
    state: RunVoiceState,
    key: tuple,
    *,
    now: float,
    cooldown: float = RUN_SAY_ONCE_SECONDS,
) -> bool:
    """Has this intent gone quiet long enough to be said again in this run?"""
    last = state.said.get(key)
    if last is None:
        return True
    return (now - last) >= cooldown


def remember_said_run(
    state: RunVoiceState,
    key: tuple,
    *,
    now: float,
    cooldown: float = RUN_SAY_ONCE_SECONDS,
) -> None:
    """Stamp this intent as just said in this run, and forget expired ones."""
    for old, when in list(state.said.items()):
        if (now - when) >= cooldown:
            del state.said[old]
    state.said[key] = now


def _format_item_link(item_name: str, item_id: int, quality: int) -> str:
    """Format an item as a WoW game link: |c<color>|Hitem:<id>|h[name]|h|r"""
    color = QUALITY_COLOR.get(quality, "ffffff")
    return f"|cff{color}|Hitem:{item_id}|h[{item_name}]|h|r"


def _excitement_for_quality(quality: int) -> str:
    """Return an excitement marker based on item rarity."""
    if quality >= 4:  # epic+
        return "!!"
    elif quality == 3:  # rare
        return "!"
    else:
        return ""


def _is_old_gear_for_level(item_level: int | None, character_level: int) -> bool:
    """Whether an item is genuinely old for a character's level.

    An item is 'old' if its level is more than 10 levels below the character's level.
    """
    if item_level is None:
        return False
    return item_level <= character_level - 10


# Party chat templates for different event types
PARTY_BOSS_KILL_LINES = [
    "{speaker}: {boss} down.",
    "{speaker}: {boss} is dead.",
    "{speaker}: that was {boss}.",
    "{speaker}: {boss} didn't stand a chance.",
    "{speaker}: on to the next one.",
]

PARTY_DEATH_LINES = [
    "{speaker}: {victim} went down.",
    "{speaker}: {victim} fell.",
    "{speaker}: get {victim} up.",
    "{speaker}: {victim}... rez when ready.",
]

PARTY_WIPE_LINES = [
    "{speaker}: wipe it.",
    "{speaker}: we're done here.",
    "{speaker}: everyone down.",
    "{speaker}: run back.",
    "{speaker}: that pull didn't work.",
]

PARTY_DROP_LINES = [
    "{speaker}: {item} dropped{exc}.",
    "{speaker}: {item}{exc} {winner} takes it.",
    "{speaker}: nice {item}{exc}.",
    "{speaker}: {winner} got {item}{exc}.",
]

PARTY_UPGRADE_LINES = [
    "{speaker}: {item} replaces {old}{exc}.",
    "{speaker}: {winner} upgrades from {old} to {item}{exc}.",
    "{speaker}: that {item} is a real upgrade for {winner}{exc}.",
]

PARTY_WING_DONE_LINES = [
    "{speaker}: {wing} clear.",
    "{speaker}: {wing} done.",
    "{speaker}: that wing is finished.",
    "{speaker}: moving on.",
]

PARTY_STALL_LINES = [
    "{speaker}: we're stuck here.",
    "{speaker}: nothing's happening.",
    "{speaker}: this is taking too long.",
    "{speaker}: anyone have a plan?",
]

# Guild chat templates
GUILD_EPIC_DROP_LINES = [
    "[Guild] {speaker}: {winner} got {item}{exc} in {place}!",
    "[Guild] {speaker}: {item}{exc} for {winner} in {place}!",
    "[Guild] {speaker}: nice drop - {item}{exc} to {winner} ({place})!",
]

GUILD_FIRST_KILL_LINES = [
    "[Guild] {speaker}: {winner} got {boss}{exc} in {place}!",
    "[Guild] {speaker}: {boss}{exc} for {winner} in {place}!",
    "[Guild] {speaker}: guild first on {boss} - grats {winner} ({place})!",
]

GUILD_DING_LINES = [
    "[Guild] {speaker}: grats {winner} on {level}!",
    "[Guild] {speaker}: {winner} hit {level}!",
    "[Guild] {speaker}: ding {level} for {winner}!",
]

GUILD_CLASS_QUEST_LINES = [
    "[Guild] {speaker}: anyone free to help {winner} with their class quest?",
    "[Guild] {speaker}: {winner} needs a hand for their class quest.",
]


def _pick_speaker(members: Collection[str], exclude: str | None = None) -> str | None:
    """Pick a random party member to speak, optionally excluding one."""
    candidates = [m for m in members if m != exclude]
    if not candidates:
        return None
    return random.choice(candidates)


def _pick_guild_speaker(
    guild_members: Collection[str], exclude: str | None = None
) -> str | None:
    """Pick a random guild member to speak."""
    candidates = [m for m in guild_members if m != exclude]
    if not candidates:
        return None
    return random.choice(candidates)


def generate_party_lines(
    event: RunEvent,
    party_members: Collection[str],
    state: RunVoiceState,
    *,
    now: float,
    character_levels: Mapping[str, int] | None = None,
) -> list[tuple[str, str]]:
    """Generate party chat lines for a run event.

    Returns list of (speaker, line) tuples that pass deduplication.
    """
    lines: list[tuple[str, str]] = []

    if event.kind == "boss_kill" and event.boss_name:
        speaker = _pick_speaker(party_members)
        if not speaker:
            return lines
        key = _run_say_key(
            speaker=speaker,
            subject=f"boss_kill:{event.boss_name}",
            run_id=event.run_id,
            per_speaker=False,
        )
        if should_say_run(state, key, now=now):
            template = random.choice(PARTY_BOSS_KILL_LINES)
            line = template.format(speaker=speaker, boss=event.boss_name)
            remember_said_run(state, key, now=now)
            lines.append((speaker, line))

    elif event.kind == "death" and event.character:
        speaker = _pick_speaker(party_members, exclude=event.character)
        if not speaker:
            return lines
        key = _run_say_key(
            speaker=speaker,
            subject=f"death:{event.character}",
            run_id=event.run_id,
            per_speaker=False,
        )
        if should_say_run(state, key, now=now):
            template = random.choice(PARTY_DEATH_LINES)
            line = template.format(speaker=speaker, victim=event.character)
            remember_said_run(state, key, now=now)
            lines.append((speaker, line))

    elif event.kind == "wipe":
        speaker = _pick_speaker(party_members)
        if not speaker:
            return lines
        key = _run_say_key(
            speaker=speaker, subject="wipe", run_id=event.run_id, per_speaker=False
        )
        if should_say_run(state, key, now=now):
            template = random.choice(PARTY_WIPE_LINES)
            line = template.format(speaker=speaker)
            remember_said_run(state, key, now=now)
            lines.append((speaker, line))

    elif event.kind == "item_loot" and event.item_name and event.item_id is not None:
        winner = event.character or "someone"
        speaker = _pick_speaker(party_members, exclude=winner)
        if not speaker:
            return lines
        item_link = _format_item_link(
            event.item_name, event.item_id, event.item_quality or 2
        )
        excitement = _excitement_for_quality(event.item_quality or 2)

        # Check if it's an upgrade for the winner
        is_upgrade = False
        old_item = event.old_item_name
        if (
            character_levels
            and old_item
            and event.item_quality
            and event.item_quality >= 3
        ):
            # For epic+ drops, mention what it replaces if old
            # We don't have item level here, but we can check if old_item is mentioned
            is_upgrade = bool(old_item)

        key_suffix = "upgrade" if is_upgrade else "drop"
        key = _run_say_key(
            speaker=speaker,
            subject=f"loot:{event.item_name}:{key_suffix}",
            run_id=event.run_id,
            per_speaker=False,
        )
        if should_say_run(state, key, now=now):
            if is_upgrade and old_item:
                template = random.choice(PARTY_UPGRADE_LINES)
                line = template.format(
                    speaker=speaker,
                    item=item_link,
                    old=old_item,
                    winner=winner,
                    exc=excitement,
                )
            else:
                template = random.choice(PARTY_DROP_LINES)
                line = template.format(
                    speaker=speaker, item=item_link, winner=winner, exc=excitement
                )
            remember_said_run(state, key, now=now)
            lines.append((speaker, line))

    elif event.kind == "wing_done" and event.wing_name:
        speaker = _pick_speaker(party_members)
        if not speaker:
            return lines
        key = _run_say_key(
            speaker=speaker,
            subject=f"wing_done:{event.wing_name}",
            run_id=event.run_id,
            per_speaker=False,
        )
        if should_say_run(state, key, now=now):
            template = random.choice(PARTY_WING_DONE_LINES)
            line = template.format(speaker=speaker, wing=event.wing_name)
            remember_said_run(state, key, now=now)
            lines.append((speaker, line))

    elif event.kind == "stall":
        speaker = _pick_speaker(party_members)
        if not speaker:
            return lines
        key = _run_say_key(
            speaker=speaker, subject="stall", run_id=event.run_id, per_speaker=False
        )
        if should_say_run(state, key, now=now):
            template = random.choice(PARTY_STALL_LINES)
            line = template.format(speaker=speaker)
            remember_said_run(state, key, now=now)
            lines.append((speaker, line))

    return lines


def generate_guild_lines(
    event: RunEvent,
    guild_members: Collection[str],
    state: Mapping[tuple, float],  # Global guild say ledger
    *,
    now: float,
    is_guild_first: bool = False,
    is_family_first: bool = False,
    place: str = "a dungeon",
) -> list[tuple[str, str]]:
    """Generate guild chat lines for notable events.

    Uses a global guild say ledger (not per-run) so guild chat doesn't spam.
    Returns list of (speaker, line) tuples that pass deduplication.
    """
    lines: list[tuple[str, str]] = []

    if event.kind == "item_loot" and event.item_name and event.item_id is not None:
        winner = event.character or "someone"
        item_link = _format_item_link(
            event.item_name, event.item_id, event.item_quality or 2
        )
        excitement = _excitement_for_quality(event.item_quality or 2)

        if event.item_quality and event.item_quality >= 4:  # Epic+
            speaker = _pick_guild_speaker(guild_members, exclude=winner)
            if not speaker:
                return lines

            if is_guild_first or is_family_first:
                key = chat.say_key(
                    speaker=speaker, subject=f"guild_first_epic:{event.item_name}"
                )
            else:
                key = chat.say_key(
                    speaker=speaker, subject=f"guild_epic_drop:{event.item_name}"
                )

            if chat.should_say(state, key, now=now):
                if is_guild_first or is_family_first:
                    template = random.choice(GUILD_FIRST_KILL_LINES)
                    line = template.format(
                        speaker=speaker,
                        boss=event.item_name,
                        winner=winner,
                        exc=excitement,
                        place=place,
                    )
                else:
                    template = random.choice(GUILD_EPIC_DROP_LINES)
                    line = template.format(
                        speaker=speaker,
                        item=item_link,
                        winner=winner,
                        exc=excitement,
                        place=place,
                    )
                chat.remember_said(state, key, now=now)
                lines.append((speaker, line))

    elif event.kind == "boss_kill" and event.boss_name and is_guild_first:
        speaker = _pick_guild_speaker(guild_members)
        if not speaker:
            return lines
        key = chat.say_key(
            speaker=speaker, subject=f"guild_first_kill:{event.boss_name}"
        )
        if chat.should_say(state, key, now=now):
            template = random.choice(GUILD_FIRST_KILL_LINES)
            line = template.format(
                speaker=speaker,
                boss=event.boss_name,
                winner=event.character or "us",
                exc="",
                place=place,
            )
            chat.remember_said(state, key, now=now)
            lines.append((speaker, line))

    elif event.kind == "level_up" and event.character:
        # Only announce round numbers (10, 20, 30, 40, 50, 60)
        level = event.detail
        if level and level.isdigit():
            lvl = int(level)
            if lvl % 10 == 0:
                speaker = _pick_guild_speaker(guild_members, exclude=event.character)
                if not speaker:
                    return lines
                key = chat.say_key(
                    speaker=speaker, subject=f"guild_ding:{event.character}:{lvl}"
                )
                if chat.should_say(state, key, now=now):
                    template = random.choice(GUILD_DING_LINES)
                    line = template.format(
                        speaker=speaker, winner=event.character, level=lvl
                    )
                    chat.remember_said(state, key, now=now)
                    lines.append((speaker, line))

    elif event.kind == "class_quest_help" and event.character:
        speaker = _pick_guild_speaker(guild_members, exclude=event.character)
        if not speaker:
            return lines
        key = chat.say_key(
            speaker=speaker, subject=f"guild_class_quest:{event.character}"
        )
        if chat.should_say(state, key, now=now):
            template = random.choice(GUILD_CLASS_QUEST_LINES)
            line = template.format(speaker=speaker, winner=event.character)
            chat.remember_said(state, key, now=now)
            lines.append((speaker, line))

    return lines


def parse_dungeon_run_events(rows: list[dict]) -> list[RunEvent]:
    """Parse overseer_dungeon_run_event rows into RunEvent objects."""
    events: list[RunEvent] = []
    for row in rows:
        kind = row.get("kind", "")
        run_id = int(row.get("run_id", 0))
        detail = row.get("detail", "")

        if kind == "boss":
            # detail like "1 encounter done, 2 of 5 in all"
            events.append(RunEvent(kind="boss_kill", run_id=run_id, detail=detail))
        elif kind == "wipe":
            events.append(RunEvent(kind="wipe", run_id=run_id, detail=detail))
        elif kind == "stalled":
            events.append(RunEvent(kind="stall", run_id=run_id, detail=detail))
        elif kind == "complete" or kind == "cleared":
            events.append(
                RunEvent(
                    kind="wing_done",
                    run_id=run_id,
                    wing_name="final wing",
                    detail=detail,
                )
            )
        elif kind == "phase":
            # Could indicate wing transitions
            if "wing" in detail.lower():
                events.append(
                    RunEvent(
                        kind="wing_done", run_id=run_id, wing_name=detail, detail=detail
                    )
                )

    return events


def parse_overseer_events(rows: list[dict]) -> list[RunEvent]:
    """Parse overseer_event rows into RunEvent objects."""
    events: list[RunEvent] = []
    for row in rows:
        kind = row.get("kind", "")
        character = row.get("character_name", "")
        subject_id = int(row.get("subject_id", 0) or 0)
        subject_name = row.get("subject_name", "")
        detail = row.get("detail", "")

        if kind == "boss_kill":
            events.append(
                RunEvent(
                    kind="boss_kill",
                    run_id=0,
                    character=character,
                    boss_name=subject_name,
                    detail=detail,
                )
            )
        elif kind == "death":
            events.append(
                RunEvent(kind="death", run_id=0, character=character, detail=detail)
            )
        elif kind == "level_up":
            events.append(
                RunEvent(
                    kind="level_up",
                    run_id=0,
                    character=character,
                    detail=str(subject_id),
                )
            )
        elif kind == "item_loot":
            # detail might have quality info
            quality = 2  # default uncommon
            if "epic" in detail.lower():
                quality = 4
            elif "rare" in detail.lower():
                quality = 3
            events.append(
                RunEvent(
                    kind="item_loot",
                    run_id=0,
                    character=character,
                    item_name=subject_name,
                    item_id=subject_id,
                    item_quality=quality,
                    detail=detail,
                )
            )
        elif kind == "class_quest_help":
            events.append(
                RunEvent(
                    kind="class_quest_help",
                    run_id=0,
                    character=character,
                    detail=detail,
                )
            )

    return events


# For testing determinism
def _set_random_seed(seed: int) -> None:
    random.seed(seed)
