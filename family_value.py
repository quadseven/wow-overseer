"""A family as one immutable value, so a pass takes a Family, not cohort=None.

Today about sixty bridge passes take `cohort=None` and branch on it: None is
this bridge's own family, a `townslot.Cohort` is any other roster family.
Every family-parity bug so far (#150, #167, #215, #246) was one of those
branches drifting from its twin. This module is the first step of #737: the
value, one builder, and one place that reads the legacy None.

  Family                  name, members (sorted, leader first where the
                          roster says so) and at_large.
  families(roster_rows)   every roster family as a Family, in
                          council.families_of's order.
  resolve_legacy_family   the ONE reading of `cohort=None`: this bridge's own
                          family (the protected, notable names), never every
                          enrolled member and never every family.

AT LARGE. A roster that names no family at all degrades to bonds' own family
(council.families_of's fallback). That family is not enrolled anywhere, so it
is `at_large=True`; every family read off roster rows is `at_large=False`.
The flag has no default: a caller states which one it builds.
"""

from __future__ import annotations

from dataclasses import dataclass

import council


@dataclass(frozen=True)
class Family:
    """One family: its key, its members in order, and whether it is at large."""

    name: str
    members: tuple[str, ...]
    at_large: bool


def _enrolled(roster_rows: list[dict] | None) -> bool:
    """True when any roster row names both a family and a member."""
    return any(
        str(row.get("family") or "").strip() and str(row.get("name") or "").strip()
        for row in roster_rows or []
    )


def families(roster_rows: list[dict] | None) -> tuple[Family, ...]:
    """Every family as a Family, in council.families_of's order.

    Either every family comes off the roster (at_large False) or the roster
    names none and the one family is bonds' own (at_large True): the two
    never mix, because families_of falls back only when no row groups.
    """
    at_large = not _enrolled(roster_rows)
    return tuple(
        Family(name, tuple(names), at_large=at_large)
        for name, names in council.families_of(roster_rows)
    )


def resolve_legacy_family(cohort, own_members) -> Family:
    """The Family a legacy `cohort` argument means.

    None is this bridge's own family: `own_members` (the protected names),
    sorted, with no key. Any other cohort keeps its roster key and names.
    Neither is at large: both are families a pass already drives.
    """
    if cohort is None:
        return Family("", tuple(sorted(own_members)), at_large=False)
    return Family(str(cohort.key), tuple(sorted(cohort.names)), at_large=False)
