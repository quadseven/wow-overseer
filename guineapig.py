"""The guild corps' guinea pigs: one test crafter per trade, and the gate that
sends a new craft path to them before the family (#2398).

WHAT WAS ASKED FOR (the operator, 2026-11-13): the maintenance members are the
guild's craft guinea pigs. A new craft or reagent code path is tried on them
first, and reaches the family only once it has worked there.

WHO IS A GUINEA PIG. For each guild and each crafting trade, the natural
maintenance member with the highest skill in it, then the first name. A trade
nobody in the corps holds is a gap, said once per change: on the dev realm on
2026-11-13 the twenty maintenance members held Alchemy and Tailoring only,
with both primary slots of every member taken.

WHERE A FEATURE STANDS. FEATURES names each routed code path with its stage:
CORPS, guinea pigs only, or FAMILY, everyone. Promotion is a one-line change
here, made once the guinea pig's rows show the path works.

PURE MODULE: members in, names and sentences out.
"""

from __future__ import annotations

ALCHEMY, TAILORING, LEATHERWORKING, BLACKSMITHING = 171, 197, 165, 164
ENGINEERING, ENCHANTING, COOKING, FIRST_AID = 202, 333, 185, 129

# The crafting trades a guinea pig is picked for, in the order the line reads.
CRAFTS = {
    ALCHEMY: "Alchemy",
    TAILORING: "Tailoring",
    LEATHERWORKING: "Leatherworking",
    BLACKSMITHING: "Blacksmithing",
    ENGINEERING: "Engineering",
    ENCHANTING: "Enchanting",
    COOKING: "Cooking",
    FIRST_AID: "First Aid",
}

CORPS = "corps"
FAMILY = "family"

# A crafter that carries the gathered half of its next recipe buys the vendor
# half (a vial, a thread) at a vendor (guildjobs.reagent_buy_step). Measured
# 2026-11-13: every corps alchemist sat at Alchemy 1 with 100+ herbs and no
# Empty Vial, and nothing bought one.
VENDOR_REAGENTS = "vendor-reagents"

FEATURES = {
    VENDOR_REAGENTS: CORPS,
}

MAINTENANCE = "maintenance"


def _value(member, skill) -> int:
    held = (getattr(member, "skills", None) or {}).get(skill)
    return int(held[0]) if held else 0


def pick(members) -> dict:
    """guild -> {skill: name} of each trade's guinea pig."""
    best: dict = {}
    for m in members or ():
        if getattr(m, "role", "") != MAINTENANCE or not getattr(m, "eligible", False):
            continue
        for skill in CRAFTS:
            value = _value(m, skill)
            if value <= 0:
                continue
            key = (-value, str(m.name))
            mine = best.setdefault(m.guild, {})
            if skill not in mine or key < mine[skill][0]:
                mine[skill] = (key, str(m.name))
    return {
        guild: {skill: held[1] for skill, held in skills.items()}
        for guild, skills in best.items()
    }


def skills_of(pigs, guild, name) -> frozenset:
    """The trades `name` is its guild's guinea pig for."""
    return frozenset(
        skill for skill, who in (pigs or {}).get(guild, {}).items() if who == name
    )


def allows(feature, skill, pig_skills, stages=None) -> bool:
    """Whether a crafter may take `feature` for `skill`: everyone at FAMILY,
    only that trade's guinea pig at CORPS, nobody for an unknown feature."""
    stage = (FEATURES if stages is None else stages).get(feature)
    if stage == FAMILY:
        return True
    if stage == CORPS:
        return int(skill) in (pig_skills or frozenset())
    return False


def lines(pigs, members) -> list:
    """One line per guild: each trade's guinea pig and skill, then the gaps."""
    level = {
        (m.guild, m.name, skill): _value(m, skill)
        for m in members or ()
        for skill in CRAFTS
    }
    out = []
    for guild in sorted(pigs or {}):
        mine = pigs[guild]
        held = [
            "%s %s %d" % (CRAFTS[s], mine[s], level.get((guild, mine[s], s), 0))
            for s in CRAFTS
            if s in mine
        ]
        gaps = [CRAFTS[s] for s in CRAFTS if s not in mine]
        text = "%s guinea pigs: %s" % (guild, ", ".join(held) or "none")
        if gaps:
            text += "; nobody in the corps holds %s" % ", ".join(gaps)
        out.append(text)
    return out
