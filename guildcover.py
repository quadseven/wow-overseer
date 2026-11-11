"""Who in the family's own guild covers a trade nobody in the family holds (#1989).

Pure module, the same seam as craftpleas.py: rows in, names out. No SQL here.

professions.UNASSIGNED leaves inscription and jewelcrafting to the guild. The
guild passed five members long ago, so a gem or glyph ask has a real answer: an
online guildmate who holds the trade, highest skill first. Only the asking
family's OWN guild is ever read, so a Cave ask never names a Bonkers member.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# A guildmate counts as covering a trade from this skill up (the issue's bar).
MIN_SKILL = 260


@dataclass(frozen=True)
class GuildMember:
    name: str
    guild: str
    online: bool
    skills: Mapping = field(default_factory=dict)


def holders(members: Iterable[GuildMember], guild: str, skill: str) -> list:
    """Members of `guild` holding `skill` at MIN_SKILL or more, best first."""
    found = [
        m
        for m in members
        if guild and m.guild == guild and int(m.skills.get(skill, 0)) >= MIN_SKILL
    ]
    return sorted(found, key=lambda m: (-int(m.skills[skill]), m.name))


def online_holder(members: Iterable[GuildMember], guild: str, skill: str):
    """The highest-skilled ONLINE holder in `guild`, or None."""
    for member in holders(members, guild, skill):
        if member.online:
            return member
    return None


def guild_of(members: Iterable[GuildMember], name: str) -> str:
    """The guild a named member belongs to, or '' when none."""
    for member in members:
        if member.name.casefold() == (name or "").casefold():
            return member.guild
    return ""


def coverage(members: Iterable[GuildMember], guild: str, skills: Iterable[str]) -> dict:
    """skill -> count of holders at MIN_SKILL or more in `guild`."""
    members = list(members)
    return {s: len(holders(members, guild, s)) for s in skills}


_SKILL_WORDS = {755: "jewelcrafting", 773: "inscription"}


def members_from_rows(rows: Iterable[Mapping]) -> list:
    """Fold name/guild/online/skill/value rows into one GuildMember each."""
    folded: dict = {}
    for row in rows:
        entry = folded.setdefault(
            row["name"],
            {"guild": row["guild"], "online": bool(row["online"]), "skills": {}},
        )
        word = _SKILL_WORDS.get(row.get("skill"))
        if word:
            entry["skills"][word] = int(row.get("value") or 0)
    return [
        GuildMember(n, e["guild"], e["online"], e["skills"])
        for n, e in sorted(folded.items())
    ]
