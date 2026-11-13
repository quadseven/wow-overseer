"""A seated tank's spellbook, checked against its class trainer list.

Slice 1 of the tank spellbook audit: the pure step only. A seated tank
(the raid-teams seat source decides who that is) should know every spell
its class trainer teaches at or below its level. A due spell it has not
learned is missing, in one of the two states the shared spell-state rule
already names: trainable now, or needs another spell first. Above-level
spells are not missing: the tank cannot learn them yet.

The rule is classtrain.spell_state, the same rule the training surface
and the guild training pass use, so this audit cannot disagree with
them about a spell. Spells are given by id: the world's tables carry no
spell names. Nothing here grants a spell; a missing spell routes
through the normal trainer machinery.

PURE MODULE: rows in, an audit out. No MySQL and no clock.
"""

from __future__ import annotations

import campaignplan
import classtrain

# The states that mean a due spell has not been learned.
MISSING_STATES = ("trainable", "needs")


def audit_tank(
    seat: dict, trainer: list, known: set, cap: int = campaignplan.LEVEL_CAP
) -> dict:
    """One seated tank: the due trainer spells it has not learned."""
    level = int(seat.get("level") or 0)
    missing = []
    for row in sorted(
        trainer or (), key=lambda r: (int(r.get("level") or 0), int(r["spell"]))
    ):
        state = classtrain.spell_state(row, known, level, cap)
        if state in MISSING_STATES:
            missing.append(
                {
                    "spell": int(row["spell"]),
                    "level": int(row.get("level") or 0),
                    "state": state,
                }
            )
    return {
        "name": seat.get("name"),
        "class": seat.get("class") or "",
        "level": level,
        "missing": missing,
        "complete": not missing,
    }


def audit_tanks(
    seats: list,
    trainer_by_class: dict,
    known_by_name: dict,
    cap: int = campaignplan.LEVEL_CAP,
) -> dict:
    """Every filled tank seat, in seat order, with the audit totals."""
    tanks = []
    for seat in seats or ():
        if seat.get("seat") != "tank" or not seat.get("name"):
            continue
        trainer = (trainer_by_class or {}).get(int(seat.get("class_id") or 0), [])
        known = (known_by_name or {}).get(seat["name"], set())
        tanks.append(audit_tank(seat, trainer, known, cap))
    return {
        "tanks": tanks,
        "audited": len(tanks),
        "incomplete": sum(1 for t in tanks if not t["complete"]),
        "missing_total": sum(len(t["missing"]) for t in tanks),
    }
