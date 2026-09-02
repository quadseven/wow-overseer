"""Pure builder for the Family tab: snapshot rows -> the five that matter.

WHY THIS EXISTS AS AN ENDPOINT AT ALL. Everything here can be read today:
/api/map carries zone and combat, /api/character carries health. But the
Family tab wants BOTH for five characters at a phone-friendly cadence, and
the only way to get health without this is five /api/character calls - five
connections, thirty-odd queries, and about 12KB of hotbars, bags and
equipment nobody asked for, every poll. This is that same state, projected
to what a card actually draws.

Same seam rule as map_core and panel (infra#2597): the HTTP adapter fetches
rows and does nothing else. Which member is "hurt", who is missing, and what
a dead character reads as are decisions, so they live here where the stdlib
suite can reach them.

Ticket: infra#2892.
"""
from __future__ import annotations

import os
import re

import bonds
import stream
from core import _ALLIANCE_RACES, _HORDE_RACES
from panel import _CLASS_NAMES, _RACE_NAMES, CLASS_COLOURS

# Below this fraction of their health a character is in trouble, and the card
# says so in colour rather than making a person read two numbers and divide.
#
# A THIRD, not a tenth. The incident that produced this tab was the family
# dying on a loop in a zone thirty levels above them (infra#2891 territory):
# by the time anyone was under 10% the fight was already lost, so the useful
# warning is the one that fires while there is still something to be done.
HURT_BELOW = 0.35

# What a card can be, in the order a person cares about them. The page maps
# these straight to a colour and a word; deciding it here is what makes it
# testable, and what stops "dead" and "logged out" ever rendering the same.
DEAD = "dead"
HURT = "hurt"
OK = "ok"
GONE = "gone"

# --- the always-on broadcast grid (infra#2892 Twitch view) -----------------
#
# The five family members already stream continuously to MediaMTX - five
# ffmpeg encoders running on the gaming box independently of the on-demand
# POV watch above. That watch flow (stream.py, MAX_CHANNELS=2, a 45-60s
# client bring-up) governs LOGGING IN AS somebody; this is a passive VIEWER
# path onto a broadcast that is already running, and the two are unrelated -
# nothing here ever asks the stream agent for a client, so it never competes
# for a GPU channel.
#
# WHY THE PATH IS BUILT HERE AND NOT BORROWED FROM wow-stream-agent/video.py.
# That module's stream_path() is the correct, current answer for anything the
# stream agent itself starts - but it is a separate codebase on a separate
# machine, imported nowhere near this one, and as of this feature landing its
# formula (f"{prefix}-{name}", HYPHENATED) does not match what is actually
# live: querying http://127.0.0.1:9997/v3/paths/list on the gaming box right
# now returns devgrug, devbork, devgrog, devog, devugga - prefix and name
# CONCATENATED, no separator. The encoders publishing those paths were
# started before video.py grew the hyphen (infra#2994) and were not
# restarted to pick it up - restarting them is exactly the "kill a live
# demo" this feature must not do. So this mirrors the convention that is
# actually running, not the one in the newer source file, and says so here
# rather than silently disagreeing with a file three directories away.
_STREAM_PREFIX = os.environ.get("WOW_STREAM_PREFIX", "dev").strip().lower()
_STREAM_BASE = os.environ.get(
    "WOW_STREAM_BASE", "https://wow.stream.ts.ehumps.me").rstrip("/")
# Same shape restriction as the stream agent's own _NAME_RE (video.py): a
# name that lands in a URL gets the same treatment frames._NAME_RE gives it.
_BROADCAST_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")
_BROADCAST_PREFIX_RE = re.compile(r"^[a-z]{0,8}$")


def broadcast_path(character: str, prefix: str | None = None) -> str:
    """The MediaMTX path a family member's continuous broadcast lives on.

    Concatenated, not hyphenated - see the module docstring above for why
    this deliberately does not match video.py's stream_path(). An unusable
    name or prefix returns "" rather than raising: a broadcast tile that
    cannot resolve a path is drawn offline, not a 500 that takes the whole
    Family tab down with it.
    """
    name = (character or "").strip()
    if not _BROADCAST_NAME_RE.match(name):
        return ""
    label = (_STREAM_PREFIX if prefix is None else prefix).strip().lower()
    if label and not _BROADCAST_PREFIX_RE.match(label):
        return ""
    return f"{label}{name.lower()}"


def broadcast_url(character: str, base: str | None = None,
                   prefix: str | None = None) -> str | None:
    """Where a browser opens a WHEP connection for this member's broadcast.

    None when the path cannot be built, so the page can tell "nobody to
    watch" (no URL) apart from "asked and got refused" (a URL that 404s).
    """
    path = broadcast_path(character, prefix)
    if not path:
        return None
    return f"{(_STREAM_BASE if base is None else base).rstrip('/')}/{path}"


def roster() -> list[str]:
    """The five, oldest first.

    bonds.speaking_order is the family table's own answer to who comes first,
    and it is already what decides who speaks first when they all answer at
    once. Sorting these cards by a second rule would be a second opinion about
    the same family that could disagree with it.
    """
    return bonds.speaking_order(bonds.FAMILY)


def _condition(health: int, max_health: int) -> str:
    # max_health of 0 is a snapshot mid-write, not a corpse. Calling that
    # "dead" would put a red card on screen for a character running about
    # perfectly well, which is the one lie this tab cannot afford.
    if max_health <= 0:
        return OK if health > 0 else DEAD
    if health <= 0:
        return DEAD
    return HURT if health / max_health < HURT_BELOW else OK


def _member(name: str, row: dict | None, geo, leader_name: str | None) -> dict:
    bond = bonds.FAMILY[name]
    if row is None:
        # Logged out, or the worldserver dropped them. NOT an error and NOT a
        # dead character: the snapshot sweep removes rows for anyone who is
        # not there, so an absent row is the ordinary way to be offline.
        return {
            "name": name,
            "role": bond.role,
            "class": bond.char_class.title(),
            "class_colour": class_colour_by_name(bond.char_class),
            "present": False,
            "condition": GONE,
            # A logged-out character can still be mid-broadcast for a beat -
            # the snapshot sweep and the encoder are not the same clock - so
            # the tile is offered a URL here too. The tile itself learns the
            # truth from the WHEP handshake, the same way the on-demand
            # player does; this module does not guess "offline" from absence.
            "broadcast_url": broadcast_url(name),
        }
    race, class_id = row["race"], row["class"]
    health, max_health = int(row["health"]), int(row["max_health"])
    placed = geo.place(row["map_id"], row["pos_x"], row["pos_y"])
    in_instance = placed is not None and str(row["map_id"]) != placed[0]
    return {
        "name": row["name"],
        "role": bond.role,
        "present": True,
        "level": row["level"],
        "class": _CLASS_NAMES.get(class_id, f"class {class_id}"),
        # The feed's name is drawn in it (infra#88), the same colour the
        # Armory and the quest board's portraits use for the same person.
        "class_colour": CLASS_COLOURS.get(class_id, "#ffffff"),
        "race": _RACE_NAMES.get(race, f"race {race}"),
        "faction": "alliance" if race in _ALLIANCE_RACES
                   else "horde" if race in _HORDE_RACES else "neutral",
        "condition": _condition(health, max_health),
        "health": health,
        "max_health": max_health,
        # Rounded here so five cards cannot each round it differently, and so
        # a character on 1hp of 583 reads as 1% rather than 0% - "0%" next to
        # a living character is a card arguing with itself.
        "health_pct": _health_pct(health, max_health),
        "zone": "inside an instance" if in_instance
                else geo.zone_name(row["map_id"], row["pos_x"], row["pos_y"]),
        "broadcast_url": broadcast_url(row["name"]),
        "instance": in_instance,
        "combat": bool(row["in_combat"]),
        "leader": bool(leader_name) and row["name"] == leader_name,
        # Surfaced because stream.pov_changes_the_family says in as many words
        # that the UI must not hide it: watching the leader in POV hands the
        # other four a master and they start following. Best thing about
        # watching Grug, and a surprise if nobody says it.
        "pov_changes_the_family": stream.pov_changes_the_family(
            row["name"], leader_name or ""),
        "age_seconds": int(row["age_seconds"]),
    }


def class_colour_by_name(class_name: str) -> str:
    """The colour for a class the family table spells by name.

    A logged-out member has no snapshot row and so no class id, but the card
    still carries their name and the name should still be their colour.
    """
    wanted = (class_name or "").strip().lower()
    for cid, spelled in _CLASS_NAMES.items():
        if spelled.lower() == wanted:
            return CLASS_COLOURS.get(cid, "#ffffff")
    return "#ffffff"


def _health_pct(health: int, max_health: int) -> int:
    if max_health <= 0:
        return 0
    pct = round(100 * health / max_health)
    # A living character never rounds down to nothing, and a dead one never
    # rounds up to something.
    if pct == 0 and health > 0:
        return 1
    if pct == 100 and health < max_health:
        return 99
    return pct


def build_family(rows: list[dict], geo) -> dict:
    """The five family cards, oldest first, from whatever the snapshot has.

    `rows` is every fresh snapshot row for a family name; anyone missing is
    rendered as GONE rather than dropped, because a card that vanishes is how
    a logged-out character stops being noticed - which is the whole complaint
    this tab answers.
    """
    by_name = {r["name"]: r for r in rows}
    by_guid = {r["guid"]: r for r in rows}
    # The leader as the WORLD has it, not as the family table remembers it:
    # group_leader is a live guid, and the party can be led by someone the
    # snapshot has not got, in which case nobody here is marked leader.
    leader_name = None
    for r in rows:
        holder = by_guid.get(r["group_leader"])
        if holder is not None:
            leader_name = holder["name"]
            break
    members = [_member(n, by_name.get(n), geo, leader_name) for n in roster()]
    present = [m for m in members if m["present"]]
    return {
        "members": members,
        "here": len(present),
        "expected": len(members),
        "dead": sum(1 for m in present if m["condition"] == DEAD),
        "in_combat": sum(1 for m in present if m["combat"]),
        "freshest_seconds": min((m["age_seconds"] for m in present), default=None),
    }
