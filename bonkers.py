"""The isolated Horde cohort reserved for future duel experiments.

Bonkers is deliberately not another spelling of ``bonds.FAMILY``.  The
existing family drives travel, professions, guild work, streams and the
Discord bridge.  Putting these names into that roster would make an operator
provisioned test cohort steer those systems by accident.

This module is pure data and validation only.  It does not create characters,
write ``overseer_roster`` or imply that cross-faction duels work in the pinned
core.  Provisioning and duel execution are separate, later slices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


HORDE = "horde"


# WotLK player races/classes used here are each legal Horde combinations.  The
# names are the proposal in infra#4110/4111 and remain operator-checkable before
# any character is created in the dev realm.
@dataclass(frozen=True)
class Member:
    name: str
    race: str
    char_class: str
    faction: str = HORDE


COHORT: tuple[Member, ...] = (
    Member("Blammo", "orc", "warrior"),
    Member("Hexmama", "troll", "priest"),
    Member("Moojuice", "tauren", "druid"),
    Member("Rotgut", "undead", "rogue"),
    Member("Zapzap", "blood elf", "mage"),
)

_LEGAL_HORDE_PAIRS = frozenset(
    {
        ("orc", "warrior"),
        ("troll", "priest"),
        ("tauren", "druid"),
        ("undead", "rogue"),
        ("blood elf", "mage"),
    }
)


def validate(members: Iterable[Member] = COHORT) -> tuple[Member, ...]:
    """Validate and return a stable cohort tuple without touching live state."""

    result = tuple(members)
    names = [member.name for member in result]
    if len(result) != 5:
        raise ValueError("Bonkers must contain exactly five members")
    if len(set(names)) != len(names):
        raise ValueError("Bonkers member names must be unique")
    if any(
        not name.isascii() or not name.isalpha() or not 2 <= len(name) <= 12
        for name in names
    ):
        raise ValueError("Bonkers names must be ASCII WoW character names")
    if any(member.faction != HORDE for member in result):
        raise ValueError("Bonkers members must all be Horde")
    pairs = {(member.race, member.char_class) for member in result}
    if not pairs <= _LEGAL_HORDE_PAIRS:
        raise ValueError("Bonkers contains an invalid Horde race/class pair")
    if len(pairs) != len(result):
        raise ValueError("Bonkers race/class pairs must be unique")
    return result


def names() -> tuple[str, ...]:
    """The proposed names in stable operator-facing order."""

    return tuple(member.name for member in COHORT)


def overlap_with(names_to_check: Iterable[str]) -> tuple[str, ...]:
    """Return Bonkers names that overlap another roster, in cohort order."""

    other = set(names_to_check)
    return tuple(name for name in names() if name in other)


validate()
