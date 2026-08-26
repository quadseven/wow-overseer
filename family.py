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

import bonds
import stream
from core import _ALLIANCE_RACES, _HORDE_RACES
from panel import _CLASS_NAMES, _RACE_NAMES

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
            "present": False,
            "condition": GONE,
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
