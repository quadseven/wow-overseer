"""In-process ownership for travel columns and family members.

Column arbitration remains implemented by townslot; this module is the
bridge's single entry point for column slots and member occupancy decisions.
"""

from __future__ import annotations

import townslot
import classquest


Slot = townslot.Slot


def member_holds(
    *,
    guild_runs=(),
    corps_steps=(),
    dues_walks=(),
    handover_runs=(),
    crafter_walks=(),
    job_steps=(),
    train_walks=(),
    post_walks=(),
    now=None,
):
    """Return member -> reasons for active in-process holds.

    Inputs are the existing per-pass maps/sets, whose owners continue to
    expire them using their established clocks. This reports purpose without
    inventing a second lifetime or persisted state.
    """
    sources = (
        ("guild run", guild_runs),
        ("corps step", corps_steps),
        ("dues walk", dues_walks),
        ("hand-over run", handover_runs),
        ("crafter walk", crafter_walks),
        ("job step", job_steps),
        ("train walk", train_walks),
        ("post walk", post_walks),
    )
    held = {}
    for reason, names in sources:
        for name in names or ():
            held.setdefault(name, []).append(reason)
    return {name: tuple(reasons) for name, reasons in held.items()}


def busy_members(**holds):
    """Members occupied by any supplied hold source."""
    return set(member_holds(**holds))


def stranded_knights(members, holds, *, job_steps=()):
    """Names of stranded starting-zone knights held outside their own step."""
    return {
        member.name
        for member in members
        if member.online
        and int(member.class_id) == classquest.DEATH_KNIGHT
        and member.map_id == classquest.DEATH_KNIGHT_START_MAP
        and member.name not in job_steps
        and member.name in holds
    }


def urgent_ground_release(**decision):
    """Centralized release eligibility for an urgent bag-room ground walk."""
    return townslot.urgent_ground_release(**decision)
