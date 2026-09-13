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

ITEM DEPOSIT (mod-overseer, infra#3647): MECHANISM ONLY, no auto-policy.

`format_item_deposit` below produces the exact `bank deposit-item
guid:<n>`/`entry:<n>` command text `GuildVerb::BankDepositItem` parses
(overseer_decisions.cpp) and `DoGuild` executes against the real,
verified-at-the-pinned-SHA `Guild::SwapItemsWithInventory` API
(mod_overseer.cpp). It is deliberately NOT wired into an automatic pass the
way `plan_deposits`/`_guild_bank_once` are for gold: deciding WHICH items a
character should give up - crafted potions above some held count, spare
ore, whatever the profession-supply-chain work landing this session
actually produces - needs real measured inventory data this session had no
way to read (no live pymysql connection, same constraint `guildbank.py`'s
own money-deposit design doc already ran into for the API itself). Inventing
a threshold with no data to check it against is exactly the failure mode
this project's own history warns about, so that policy is left for a
follow-up once real holdings can be read, not guessed here. This function
exists so that follow-up (or an operator, by hand) has a correct command to
enqueue through the same `_insert_guild` path `_guild_bank_once` already
uses for gold - it does not decide anything on its own.
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


def format_item_deposit(*, item_guid: int | None = None, entry: int | None = None) -> str:
    """The `bank deposit-item guid:<n>` / `entry:<n>` command text
    `GuildVerb::BankDepositItem` parses (overseer_decisions.cpp) and `DoGuild`
    executes against `Guild::SwapItemsWithInventory` (mod_overseer.cpp).

    Exactly one of `item_guid` (the specific `item_instance.guid` to move) or
    `entry` (an item type - whichever matching item the character happens to
    be carrying) must be given, the same guid-preferred/entry-fallback
    convention DoGive's own item spec already uses. This is a pure command
    formatter, not a decision: it does not choose which item to deposit, only
    renders the request once something else - an operator, or a future
    policy module reading real holdings - has already chosen. See this
    module's own top-of-file docstring for why no such policy is written
    here yet.
    """
    if (item_guid is None) == (entry is None):
        raise ValueError("give exactly one of item_guid or entry")
    if item_guid is not None:
        if not isinstance(item_guid, int) or item_guid <= 0:
            raise ValueError("item_guid must be a positive integer")
        return f"bank deposit-item guid:{item_guid}"
    if not isinstance(entry, int) or entry <= 0:
        raise ValueError("entry must be a positive integer")
    return f"bank deposit-item entry:{entry}"
