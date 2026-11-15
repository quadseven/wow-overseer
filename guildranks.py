"""Guild rank promotion and MOTD planning rules (#2616).

Pure rules mapping a guild member's level and raid-lineup seat to the target
guild rank, plus the guild MOTD for its current goal, and the module verb
builders for `mod-overseer`.

Rank IDs match `Guild::_CreateDefaultGuildRanks` in pinned AzerothCore and
`GUILD_RANK_*` in `mod-overseer/src/overseer_decisions.h`:
  0 Master, 1 Officer, 2 Veteran, 3 Member, 4 Initiate.

Nothing here executes until `mod-overseer` handles `promote` and `motd`
and lists them in `guildcorps.MODULE_GUILD_VERBS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import raidteams

RANK_MASTER = 0
RANK_OFFICER = 1
RANK_VETERAN = 2
RANK_MEMBER = 3
RANK_INITIATE = 4

RANK_NAMES = {
    RANK_MASTER: "Guild Master",
    RANK_OFFICER: "Officer",
    RANK_VETERAN: "Veteran",
    RANK_MEMBER: "Member",
    RANK_INITIATE: "Initiate",
}

MEMBER_MIN_LEVEL = 20
PROMOTES_PER_PASS = 5
MAX_MOTD_BYTES = 128

_PROTECTED_RANKS = frozenset({RANK_MASTER, RANK_OFFICER})


@dataclass(frozen=True)
class Action:
    """One planned guild rank promotion or MOTD update."""

    verb: str
    target: str
    command: str
    why: str


def raid_seat_names(guild: str) -> frozenset[str]:
    """Approved and pre-rename character names holding a raid lineup seat."""
    return frozenset(
        name
        for seat in raidteams.seats(guild)
        for name in (seat.name, seat.was)
        if name
    )


def target_rank(level: int, in_raid_lineup: bool) -> int:
    """Target rank id from level and raid-lineup membership."""
    if in_raid_lineup:
        return RANK_VETERAN
    if int(level or 0) >= MEMBER_MIN_LEVEL:
        return RANK_MEMBER
    return RANK_INITIATE


def promotion_rank(
    current_rank: int | None,
    level: int,
    in_raid_lineup: bool,
) -> int | None:
    """Target rank when promoting upward, else None.

    Master (0) and Officer (1) are left untouched, and members are never demoted
    below their current rank.
    """
    if current_rank is None:
        return None
    rank = int(current_rank)
    if rank in _PROTECTED_RANKS:
        return None
    desired = target_rank(level, in_raid_lineup)
    if rank <= desired:
        return None
    return desired


def promote_command(rank_id: int) -> str:
    """Command string for `mod-overseer` `GuildVerb::Promote` (`target_arg` names the member)."""
    rid = int(rank_id)
    if rid not in RANK_NAMES or rid == RANK_MASTER:
        raise ValueError(f"unsupported promotion rank id: {rank_id}")
    return f"promote rank:{rid}"


def motd_command(text: str) -> str:
    """Command string for `mod-overseer` `GuildVerb::Motd`."""
    cleaned = _sanitize_motd(text)
    if not cleaned:
        raise ValueError("motd text cannot be empty")
    return f"motd {cleaned}"


def _sanitize_motd(text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    ascii_only = collapsed.encode("ascii", "ignore").decode("ascii").strip()
    if len(ascii_only) <= MAX_MOTD_BYTES:
        return ascii_only
    return ascii_only[: MAX_MOTD_BYTES - 3].rstrip() + "..."


def motd_for_goal(
    guild_name: str,
    active_goal: Mapping | None = None,
    raid_keyword: str = "",
) -> str:
    """Build a single-line ASCII MOTD naming the guild's current goal."""
    label = _goal_label(active_goal, raid_keyword)
    if not label:
        return ""
    prefix = f"{guild_name} goal: " if guild_name else "Goal: "
    return _sanitize_motd(prefix + label)


def _goal_label(active_goal: Mapping | None, raid_keyword: str) -> str:
    if isinstance(active_goal, Mapping) and active_goal:
        kind = str(active_goal.get("kind") or "").strip()
        instance = str(active_goal.get("instance") or "").strip()
        target = active_goal.get("target")
        if kind == "dungeon" and instance:
            return f"clear {instance} ({target}x)" if target else f"clear {instance}"
        if instance:
            return f"{kind} in {instance}" if kind else instance
        if kind:
            return f"{kind} {target}" if target is not None else kind
    kw = str(raid_keyword or "").strip()
    return f"raid {kw}" if kw else ""


def _master_online(members, master: str) -> bool:
    if not master:
        return False
    return any(
        m.get("name") == master
        and bool(m.get("online"))
        and int(m.get("rank") if m.get("rank") is not None else -1) == RANK_MASTER
        for m in members
    )


def plan_actions(
    guild_name: str,
    master: str,
    members,
    current_motd: str = "",
    *,
    active_goal: Mapping | None = None,
    raid_keyword: str = "",
    raid_seats: frozenset[str] | None = None,
    pending: frozenset[str] = frozenset(),
) -> tuple[Action, ...]:
    """Plan bounded promotion and MOTD actions for an online guild master."""
    if not _master_online(members, master):
        return ()
    seats = raid_seat_names(guild_name) if raid_seats is None else raid_seats
    actions: list[Action] = []
    for member in sorted(members, key=lambda m: str(m.get("name") or "")):
        name = str(member.get("name") or "")
        if not name or name == master or name in pending:
            continue
        new_rank = promotion_rank(
            member.get("rank"),
            int(member.get("level") or 0),
            name in seats,
        )
        if new_rank is None:
            continue
        why = "raid seat" if name in seats else f"level {int(member.get('level') or 0)}"
        actions.append(
            Action(
                verb="promote",
                target=name,
                command=promote_command(new_rank),
                why=f"{name} -> {RANK_NAMES[new_rank]} ({why})",
            )
        )
        if len(actions) >= PROMOTES_PER_PASS:
            break

    desired_motd = motd_for_goal(
        guild_name, active_goal=active_goal, raid_keyword=raid_keyword
    )
    if (
        desired_motd
        and desired_motd != _sanitize_motd(current_motd)
        and "motd" not in pending
    ):
        actions.append(
            Action(
                verb="motd",
                target=guild_name,
                command=motd_command(desired_motd),
                why=f"set MOTD to {desired_motd}",
            )
        )
    return tuple(actions)


def summarize_ranks(
    guild_name: str,
    members,
    *,
    current_motd: str = "",
    active_goal: Mapping | None = None,
    raid_keyword: str = "",
    raid_seats: frozenset[str] | None = None,
) -> dict:
    """Summarize rank counts and pending promotions for /api/v2/guild."""
    seats = raid_seat_names(guild_name) if raid_seats is None else raid_seats
    counts: dict[int, int] = {}
    pending_promotions = 0
    for member in members:
        raw_rank = member.get("rank")
        if raw_rank is None:
            continue
        rid = int(raw_rank)
        counts[rid] = counts.get(rid, 0) + 1
        name = str(member.get("name") or "")
        if (
            promotion_rank(rid, int(member.get("level") or 0), name in seats)
            is not None
        ):
            pending_promotions += 1
    return {
        "counts": dict(sorted(counts.items())),
        "pending_promotions": pending_promotions,
        "current_motd": str(current_motd or ""),
        "desired_motd": motd_for_goal(
            guild_name, active_goal=active_goal, raid_keyword=raid_keyword
        ),
    }
