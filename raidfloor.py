"""A per-role gear floor for a raid seat, read against Molten Core damage (#2110).

THE GAP THIS CLOSES. raidready flagged thin gear by a share of slots near
pre-raid best, which says nothing about whether a tank survives Ragnaros melee
plus a Magma Blast or a healer keeps the raid up. This module sets a floor per
role on the worn stats that decide those fights, derives each floor from the
boss damage written below, and reads a seat's worn stats against it.

PLANNING NUMBERS, like mcencounters.py's counts: the encounter scripts say a
mechanic exists, not how much a pre-raid seat must carry. The damage inputs
and the margins are kept in one block so a change is one line, and every floor
is computed from them, never typed beside them.

WHAT IS READ. Worn item template stats only (no enchants or gems), the same
read raidgear uses. A seat with no worn rows read has no floor verdict (not
read, never zero).

PURE MODULE: rows in, sentences out.
"""

from __future__ import annotations

import math

import gearscore

TANK, HEALER, DPS = "tank", "healer", "dps"

# --- encounter damage the floors are derived from (planning numbers) --------
# Ragnaros: raw (before armor) melee hit on his tank, and Magma Blast, the
# fire hit on anyone out of his melee reach. Majordomo Executus: the health
# of his eight adds, which the damage seats must burn down.
RAGNAROS_MELEE_HIT = 2000
MAGMA_BLAST_HIT = 1000
MAJORDOMO_ADDS = 8
MAJORDOMO_ADD_HEALTH = 3000
# Raw damage a tank takes before the healers answer, in Ragnaros melee hits.
HITS_BEFORE_HEAL = 2
# Share of raw melee damage a tank's armor must stop.
TANK_MITIGATION = 0.35
# Level-60 armor constant: reduction = armor / (armor + ARMOR_CONSTANT).
ARMOR_CONSTANT = 5500
# Health per point of worn stamina, mana per point of worn intellect.
HEALTH_PER_STAMINA = 10
MANA_PER_INTELLECT = 15
# Healers: one cast must heal a Magma Blast, and spell power alone supplies
# this share of it, so the floor is the blast over that share; the mana pool
# must pay this many heals of this cost.
HEALER_HEALS = 20
HEAL_MANA_COST = 150
HEAL_BASE_SHARE = 0.4
# Damage seats burn the adds in this many seconds.
ADD_BURN_SECONDS = 30
# Damage seats that share the add burn (planning number).
DAMAGE_SEATS = 4


def _derive() -> dict:
    armor = math.ceil(ARMOR_CONSTANT * TANK_MITIGATION / (1 - TANK_MITIGATION))
    health = HITS_BEFORE_HEAL * RAGNAROS_MELEE_HIT + MAGMA_BLAST_HIT
    return {
        TANK: {
            "effective health": (
                health,
                "%d Ragnaros melee hits of %d plus a Magma Blast of %d"
                % (HITS_BEFORE_HEAL, RAGNAROS_MELEE_HIT, MAGMA_BLAST_HIT),
            ),
            "armor": (
                armor,
                "%d%% of Ragnaros melee stopped" % round(TANK_MITIGATION * 100),
            ),
        },
        HEALER: {
            "healing power": (
                math.ceil(MAGMA_BLAST_HIT / HEAL_BASE_SHARE),
                "a Magma Blast of %d healed by one cast" % MAGMA_BLAST_HIT,
            ),
            "mana pool": (
                HEALER_HEALS * HEAL_MANA_COST,
                "%d heals of %d mana through Ragnaros" % (HEALER_HEALS, HEAL_MANA_COST),
            ),
        },
        DPS: {
            "attack or spell power": (
                math.ceil(
                    MAJORDOMO_ADDS
                    * MAJORDOMO_ADD_HEALTH
                    / ADD_BURN_SECONDS
                    / DAMAGE_SEATS
                ),
                "Majordomo's %d adds of %d health in %ds across %d damage seats"
                % (
                    MAJORDOMO_ADDS,
                    MAJORDOMO_ADD_HEALTH,
                    ADD_BURN_SECONDS,
                    DAMAGE_SEATS,
                ),
            ),
        },
    }


# role -> stat -> (floor, the encounter damage it comes from)
FLOORS = _derive()


def worn_stats(rows: list) -> dict:
    """The floor stats one character's worn rows add up to."""
    total: dict = {}
    for row in rows:
        for key, value in gearscore.stats_from_row(row).items():
            total[key] = total.get(key, 0) + value
    armor = total.get("armor", 0)
    raw = total.get("health", 0) + HEALTH_PER_STAMINA * total.get("stamina", 0)
    return {
        "effective health": round(raw / (1 - armor / (armor + ARMOR_CONSTANT))),
        "armor": armor,
        "healing power": total.get("spell_power", 0),
        "mana pool": total.get("mana", 0)
        + MANA_PER_INTELLECT * total.get("intellect", 0),
        "attack or spell power": max(
            total.get("attack_power", 0), total.get("spell_power", 0)
        ),
    }


def shortfalls(role: str, rows: list) -> list:
    """[(stat, have, floor)] for each floor this role's worn rows miss."""
    # A row with no item entry (the thin read) carries no stats: not read.
    rows = [r for r in rows if r.get("entry") is not None]
    if not rows:
        return []
    have = worn_stats(rows)
    return [
        (stat, have[stat], floor)
        for stat, (floor, _why) in FLOORS.get(role, {}).items()
        if have[stat] < floor
    ]


def hard_blockers(raiders: list, worn_rows: list) -> list:
    """HARD sentences for placed raiders under their role's floor."""
    by_name: dict = {}
    for row in worn_rows or ():
        by_name.setdefault(row.get("name"), []).append(row)
    under = []
    for member in raiders:
        role = member.get("role", DPS)
        for stat, have, floor in shortfalls(role, by_name.get(member["name"], [])):
            under.append(
                "%s %s %s %d of %d (short %d)"
                % (member["name"], role, stat, have, floor, floor - have)
            )
    if not under:
        return []
    shown = "; ".join(under[:3])
    if len(under) > 3:
        shown += "; and %d more" % (len(under) - 3)
    return ["Under the role gear floor Ragnaros and Majordomo damage sets: %s." % shown]
