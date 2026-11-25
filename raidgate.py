"""The first-clear gate: other guilds raid a tier only after a family guild did.

THE RULE. Cave and Bonkers clear each raid tier first. Any other guild may keep
running dungeons, gear and attunement runs, but its raid run for a tier waits
until a realm milestone for that tier exists. A milestone is the first kill of
the tier's final boss by a family guild. Molten Core's final boss is Ragnaros,
Blackwing Lair's is Nefarian and AQ's is C'Thun. One tier's milestone never
opens another tier.

PURE MODULE, same seam as raidrun.py: names and sets in, a sentence or a new
set out, nothing that talks to MySQL. The caller persists the milestone set.
"""

from __future__ import annotations

FAMILY_GUILDS = frozenset({"Cave", "Bonkers"})

# raid keyword -> the creature entry whose kill clears the tier.
FINAL_BOSS = {
    "moltencore": 11502,
    "blackwinglair": 11583,
    "aq": 15727,
}


def refusal(guild: str, keyword: str, milestones) -> str:
    """Why `guild` may not run the raid `keyword` yet, or "".

    `milestones` is the set of raid keywords a family guild has cleared."""
    if guild in FAMILY_GUILDS or keyword not in FINAL_BOSS:
        return ""
    if keyword in set(milestones or ()):
        return ""
    return "%s waits for a family guild to clear it first" % keyword


def record_kill(guild: str, boss_entry: int, milestones) -> frozenset:
    """The milestone set after `guild` killed creature `boss_entry`.

    Only a family guild's kill of a tier's final boss adds its keyword; an
    existing milestone is never written twice."""
    have = frozenset(milestones or ())
    if guild not in FAMILY_GUILDS:
        return have
    cleared = {kw for kw, entry in FINAL_BOSS.items() if entry == int(boss_entry)}
    return have | cleared
