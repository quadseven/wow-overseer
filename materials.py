"""Which crafting material should move from whose bags to whose (infra#2830).

Pure module, same seam as questshare.py and professions.py: facts in, a plan
out. bridge.py reads `character_inventory` joined against
`acore_world.item_template` (the same join shape `_QUEST_SQL`'s item lookups
already use), builds one Holding per item stack, calls `plan()`, and turns
each Grant into one `overseer_command` row with `kind='give'`. mod-overseer's
`DoGive` performs the actual transfer.

WHY THIS EXISTS. Measured live 2026-08-24 against `character_inventory`, with
every bag at 100% full (#2813):

    holder  has                                            relevant to
    Bork    Linen Cloth x19, Silverleaf x19, Bolt x2        tailoring
    Ugga    Linen Cloth x13, Silverleaf x18, Bolt x1        tailoring
    Og      Linen Cloth x15, Silverleaf x13, Peacebloom x7  tailoring/alchemy
    Grog    Linen Cloth x18                                 tailoring
    Grug    Linen Cloth x19, Silver Ore x2, Malachite x4    tailoring/smithing

84 Linen Cloth, spread across five characters, and - per professions.ROSTER,
infra#2757 - exactly one of them (Og) is actually assigned tailoring. Nobody
had a way to move a stack from one character's bags into another's as part of
a plan; #2793 gave the family quest SHARING, and this is the equivalent for
STUFF.

WHY kind='give' AND NOT NEW C++. infra#2597 already built a real item
transfer between two living characters - `guid:<item_instance.guid>` or
`entry:<id>` in, one `CharacterDatabase` transaction, both inventories
updated - to solve the Severing Axe problem (a loot roll hands a two-hander to
a priest). #2830 is the same mechanism aimed at a different noun: reagents
instead of gear. `DoGive` does not know or care why an item is moving, so this
module supplies only the WHO and the WHAT; `tests/test_give.py` already proves
the HOW - the atomic move, the five distinguishable refusals, the widened
ENUM - and none of that needs re-proving here.

WHAT THIS DECIDES AND WHAT IT DOES NOT. This module answers "whose bags should
this stack end up in", never "should this stack exist" - the item is already
real and already sitting in somebody's inventory. REAGENTS below is read-only
domain knowledge (which profession consumes which material), the same shape
as professions.ARMOUR and professions.CRAFT_ARMOUR: a short, named table
rather than a derivation, because the correctness here is Evan's own
observation of what is actually in these bags, not a rule that could
reverse-engineer it. Deliberately small: a material not listed is left alone
rather than guessed at, exactly as craftpleas.PRODUCTS (#2829) leaves an
unlisted product unanswered rather than inventing an opinion.

WHAT IS STILL UNVERIFIED. Every fact in REAGENTS and every line of bridge.py's
SQL that reads `character_inventory` was written with `wow-dev` mid-RAM-swap
and unreachable - so none of it has been watched moving a real item. This
module's tests are unit tests against synthetic Holdings; they prove the
DECISION is right for the inputs given, not that the SQL that will produce
those inputs is. Say so plainly rather than implying otherwise, per this
service's own hard-won rule about `delivered` meaning nothing was verified.
"""

from __future__ import annotations

from dataclasses import dataclass

import professions

# Which profession consumes which material, restricted to what infra#2830
# actually measured in the family's bags. Keyed on the item's NAME because
# that is what `character_inventory` joined to `acore_world.item_template`
# gives back - not a hardcoded item entry id, which this repo has nowhere
# else needed and which cannot be checked against a live server right now
# (see the module docstring).
REAGENTS = {
    "Linen Cloth": "tailoring",
    "Bolt of Linen Cloth": "tailoring",
    "Silverleaf": "alchemy",
    "Peacebloom": "alchemy",
    "Silver Ore": "blacksmithing",
    "Malachite": "jewelcrafting",
}


@dataclass(frozen=True)
class Holding:
    """One item stack, in one character's bags, right now.

    ONE ROW PER `item_instance.guid`. A stack split across two bag slots
    because it never fully merged is two Holdings, not one merged count -
    `DoGive` moves a single guid, and cannot address "19 Linen Cloth,
    wherever it happens to sit."
    """

    holder: str
    material: str
    count: int
    guid: int


@dataclass(frozen=True)
class Grant:
    """One stack, moving from one family member's bags into another's."""

    holder: str
    taker: str
    material: str
    count: int
    guid: int
    skill: str
    reason: str
    said: str

    @property
    def command(self) -> str:
        """What mod-overseer's DoGive parses out of `overseer_command.command`."""
        return "guid:%d" % int(self.guid)


@dataclass(frozen=True)
class Plan:
    grants: tuple = ()
    # Materials REAGENTS names but that professions.ROSTER assigns to nobody -
    # costs no give command, said rather than silently skipped, same reason
    # professions._notes exists.
    notes: tuple = ()


def crafter_for(material: str) -> str:
    """Who should end up holding this material, or '' if this module has no
    opinion (not in REAGENTS, or REAGENTS names a skill nobody is assigned)."""
    skill = REAGENTS.get(material, "")
    if not skill:
        return ""
    return professions.crafter_for(skill)


def plan(holdings) -> Plan:
    """Every stack that should move, in one pass.

    Deterministic: the same holdings in produce the same grants in the same
    order, sorted by (holder, material, guid) - so a re-run against unchanged
    bags proposes an identical plan and bridge.py's dedupe (the `give` sibling
    of `_recent_share_keys`) sees the same key twice rather than a shuffled
    one that never matches.
    """
    grants = []
    notes = []
    for holding in sorted(holdings, key=lambda h: (h.holder, h.material, h.guid)):
        skill = REAGENTS.get(holding.material, "")
        if not skill:
            continue
        taker = professions.crafter_for(skill)
        if not taker:
            note = (
                f"{holding.material} feeds {skill}, and nobody is assigned "
                f"{skill} - see professions.UNASSIGNED."
            )
            if note not in notes:
                notes.append(note)
            continue
        if taker == holding.holder:
            # Already in the right hands. Not a note - this is the common,
            # boring, correct case and saying it every pass would drown the
            # notes that are actually asking for something.
            continue
        grants.append(Grant(
            holder=holding.holder, taker=taker, material=holding.material,
            count=holding.count, guid=holding.guid, skill=skill,
            reason=(
                f"{holding.holder} holds {holding.count} {holding.material}, "
                f"which feeds {skill}, and {taker} is the family's assigned "
                f"{skill}. {holding.holder} is not assigned {skill}, so the "
                f"stack does {holding.holder} no good where it sits."
            ),
            said=(
                f"{holding.holder} give {taker} {holding.count} "
                f"{holding.material}. {taker} need it for {skill}."
            ),
        ))
    return Plan(grants=tuple(grants), notes=tuple(notes))


def lines(material_plan: Plan) -> list:
    """The family saying it, "Name: words" - the shape professions.lines and
    kin's muster report already speak in, so a handoff is a line in party
    chat and never a silent database write (#2830: "The request should be
    legible in party chat, not silent")."""
    return [f"{g.holder}: {g.said}" for g in material_plan.grants]
