"""Immutable family values built from the established council grouping.

bridge._names_of resolves its legacy cohort=None through
resolve_legacy_family; the passes move onto Family in follow-up tickets.
"""

from __future__ import annotations

from dataclasses import dataclass

import council


@dataclass(frozen=True)
class Family:
    """A family grouping, with members ordered as the roster presents them."""

    name: str
    members: tuple[str, ...]
    at_large: bool = False


def families(roster_rows: list[dict] | None) -> tuple[Family, ...]:
    """Build immutable family values using the established roster ordering."""
    grouped = council.families_of(roster_rows)
    has_roster_family = any(
        str(row.get("family") or "").strip() and str(row.get("name") or "").strip()
        for row in roster_rows or []
    )
    return tuple(
        Family(name, tuple(names), at_large=not has_roster_family)
        for name, names in grouped
    )


def resolve_legacy_family(cohort, own_members) -> Family:
    """Resolve None to this bridge's family; explicit cohorts keep their key."""
    if cohort is None:
        return Family("", tuple(sorted(own_members)))
    return Family(str(cohort.key), tuple(sorted(cohort.names)))
