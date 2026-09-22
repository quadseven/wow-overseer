"""Keep a named character from being re-rolled by the random-bot manager.

WHY THIS EXISTS (infra#2656). Making an account autonomous - so its
characters play while nobody is at the keyboard - means handing them to
RandomPlayerbotMgr, which periodically calls Randomize() on idle bots.
Above level 3 that is harmless under our config: DisableRandomLevels=1
keeps levels, EquipAndSpecPersistence=1 keeps gear and spec, and the
destructive ClearAllItems/ClearSkills/ClearSpells calls sit behind
`if (!incremental)`. BELOW level 3 it is not harmless: Randomize() routes
to RandomizeFirst(), which assigns a level and re-gears from scratch.
Grug is level 1. That narrow window is what this protects.

HOW. The manager decides "time to randomize" from a row in
playerbots_random_bots: FindEvent drops the row once
`NowSeconds() - time >= validIn`, GetEventValue then returns 0, and the
update loop randomizes. So suppression is simply keeping a row whose
validIn has not elapsed - no fork of mod-playerbots, no patched binary,
just the manager's own bookkeeping held open.

WHAT THIS DOES NOT SUPPRESS. The `teleport` event is left alone on
purpose: being moved to a level-appropriate grind spot IS the autonomous
play we want, not damage.
"""

from __future__ import annotations

# Ten years. The manager's own slowest natural interval is 14 days, so the
# horizon must dwarf it - and a horizon this long means a protected
# character survives even if this loop stops running entirely, which is
# the failure mode that would otherwise cost a character.
PROTECT_HORIZON_SECONDS = 10 * 365 * 24 * 3600

# Refresh once less than a third of the horizon remains. Nothing depends on
# the loop being punctual; this is belt-and-braces on top of the horizon.
_REFRESH_AT = 1 / 3


def rows_needing_refresh(protected: dict, rows: dict, now: int) -> list:
    """Which protected guids need a `randomize` row written.

    `protected` is guid -> name, `rows` is guid -> {"time", "validIn"} as
    read from playerbots_random_bots. A row is rewritten when it is
    missing, already expired, close to expiring, or carries a shorter
    validIn than ours (the manager rescheduling on its own terms).
    """
    due = []
    for guid in protected:
        row = rows.get(guid)
        if not row:
            due.append(guid)
            continue
        if int(row.get("validIn") or 0) < PROTECT_HORIZON_SECONDS:
            due.append(guid)
            continue
        remaining = int(row["time"]) + int(row["validIn"]) - now
        if remaining <= PROTECT_HORIZON_SECONDS * _REFRESH_AT:
            due.append(guid)
    return due


def report(protected: dict, written: list, now: int) -> str:
    """One line per cycle, whether or not anything was written.

    Said every cycle on purpose: a protection that has silently stopped
    running must not look like one that had nothing to do.
    """
    names = ", ".join(sorted(protected.values())) or "nobody"
    return "protect: covering %d (%s), refreshed %d this cycle" % (
        len(protected),
        names,
        len(written),
    )
