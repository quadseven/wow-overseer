"""Who has more gold than they need, and how much of it goes to the guild.

DEPOSIT ONLY (mod-overseer#437, infra#2831). Withdrawals need the guild's own
per-rank permission read (`guild_bank_right`) done on THIS side before an aim
is even written, so the module never asks the core to do something the
guild's own rank rules would refuse - that is a separate, harder feature and
is not attempted here. Deposit has no such rank gate: the core's own
`Guild::HandleMemberDepositMoney` performs no rank check at all, only a
bank-full ceiling, so any member may deposit and the only question this
module has to answer is how much of their own purse is actually spare.

THE RULE IS DELIBERATELY SIMPLE FOR A FIRST SLICE: leave every character a
fixed float, deposit whatever sits above it. No per-character judgement about
upcoming trainer costs, repair bills or auction listings - those are exactly
the kind of "surplus" question `disposition.py` answers for items, and a gold
version of that same judgement is future work, not this slice.
"""

from __future__ import annotations

from dataclasses import dataclass

# One gold. Comfortably above what a trainer visit or a repair bill costs a
# character in this level range, and round enough that a reader can check the
# arithmetic in their head. Not tuned against `professions.py` or any other
# module's own float - there isn't one to reuse (checked before writing this)
# - so this is its own named constant rather than a borrowed one.
FLOAT_COPPER = 10_000


@dataclass(frozen=True)
class Deposit:
    name: str
    copper: int


def plan_deposits(members: list[dict]) -> list[Deposit]:
    """One Deposit per character holding more than FLOAT_COPPER, or none.

    `members` is a list of {"name": str, "money": int, "in_guild": bool}. A
    character not in a guild is skipped rather than raising - the guild-bank
    errand is meaningless for them and the caller should not have to filter
    first. `money` missing or non-positive is treated as nothing to deposit,
    not an error: a stale or absent read should never manufacture a deposit
    order, only ever suppress one.
    """
    deposits: list[Deposit] = []
    for member in members:
        if not member.get("in_guild"):
            continue
        name = member.get("name")
        if not name:
            continue
        money = member.get("money") or 0
        if not isinstance(money, int) or money <= FLOAT_COPPER:
            continue
        deposits.append(Deposit(name=name, copper=money - FLOAT_COPPER))
    return deposits
