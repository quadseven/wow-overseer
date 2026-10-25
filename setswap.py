"""Plan role-specific gear swaps between a member's bags and personal bank."""

from __future__ import annotations

from dataclasses import dataclass

import bankpolicy


@dataclass(frozen=True)
class Swap:
    holder: str
    role: str
    withdraw: tuple
    equip: tuple
    restore_equip: tuple
    restore_bank: tuple
    reason: str = ""


def plan(holder, role, class_id, level, worn, banked):
    """Return better banked role pieces and the rows needed to restore them.

    Rows are bankpolicy Piece objects with an added ``slot`` attribute supplied
    by the caller. Command rows use the existing guid withdrawal and equip verbs.
    """
    keeper = bankpolicy.Keeper(holder, class_id, level, "damage", frozenset())
    worn_by_slot = {int(piece.slot): piece for piece in worn}
    choices = {}
    for piece in banked:
        if bankpolicy.off_kind(piece, keeper) != role:
            continue
        slot = int(piece.slot)
        current = worn_by_slot.get(slot)
        current_score = (
            bankpolicy.situational_score(current, class_id, level, role)
            if current
            else 0
        )
        score = bankpolicy.situational_score(piece, class_id, level, role)
        if score > current_score and score > choices.get(slot, (None, 0))[1]:
            choices[slot] = (piece, score)
    if not choices:
        return Swap(holder, role, (), (), (), (), "no better banked pieces")
    pairs = sorted(
        (slot, piece, worn_by_slot.get(slot)) for slot, (piece, _) in choices.items()
    )
    return Swap(
        holder,
        role,
        tuple("withdraw guid:%d" % piece.guid for _, piece, _ in pairs),
        tuple("e Hitem:%d" % piece.entry for _, piece, _ in pairs),
        tuple("e Hitem:%d" % old.entry for _, _, old in pairs if old is not None),
        tuple("deposit guid:%d" % piece.guid for _, piece, _ in pairs),
    )
