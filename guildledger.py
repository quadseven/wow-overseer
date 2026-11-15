"""One picture of what a guild holds: the vault, its members and its bankers.

WHY. The guild's stock sits in three places that no pass reads together: the
vault tabs (the bank pass and the forecast read them), each member's bags and
bank (the item plan reads them) and, once the bankers exist, each banker's bags
and bank. A stack the plan wants to move needs one answer to "where is this
item now, and who has room for more". This module is that answer.

NOT A SECOND SYSTEM. It owns no table and keeps no state. It folds three reads
that already happen every pass (`bank.members_from_rows` for the members and the
bankers, the guild bank's per-stack rows for the vault) into one value, rebuilt
each time. A caller that cannot read the vault passes none, and the vault is
simply absent from the picture.

THE ONE NUMBER THE ITEM PLAN TAKES is `banker_room`: how many more stacks the
bankers can take by mail, which is `itemplan.Context.banker_free`.

PURE: plain values in, a `Ledger` out. No database, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import bank

# Free bag slots a banker never fills: mail arrives into the bags and a
# withdrawn stack needs one, so a full banker would strand both.
BAG_RESERVE = 6

VAULT = "vault"


@dataclass(frozen=True)
class Ledger:
    """What the guild holds, by item entry, and what its bankers can still take."""

    # entry -> ((holder, count), ...), holders sorted, the vault named `vault`
    held: dict
    bankers: tuple  # the bankers' names
    room: int  # free stacks across the bankers, reserves taken off

    def banker_room(self) -> int:
        """Stacks the bankers can take now: bag and bank slots free, less the
        reserves, summed over the bankers."""
        return self.room

    def line(self, guild: str) -> str:
        """One log line: how much the guild holds and what the bankers can take."""
        stacks = sum(len(v) for v in self.held.values())
        count = len(self.bankers)
        return (
            "ledger %s: %d item kind(s) held across members, bankers and vault; %d banker%s can take %d more stack(s)"
            % (
                guild,
                len(self.held),
                count,
                "" if count == 1 else "s",
                self.room,
            )
            + ("" if stacks else " (nothing read)")
        )


def _units(member) -> list:
    """(entry, count) for every stack a bank.Member carries or has banked."""
    return [(h.template_id, h.count) for h in (*member.carried, *member.banked)]


def build(members, *, bankers=(), vault=()) -> Ledger:
    """The ledger of `members` (family characters), `bankers` and the `vault`.

    `members` and `bankers` are `bank.Member` rows. `vault` is dicts with
    `entry` and `count` (and `tab`) for each stack in the guild bank.
    """
    totals: dict = {}

    def add(entry, holder, count):
        if int(entry) <= 0 or int(count) <= 0:
            return
        by_holder = totals.setdefault(int(entry), {})
        by_holder[holder] = by_holder.get(holder, 0) + int(count)

    for member in (*members, *bankers):
        for entry, count in _units(member):
            add(entry, member.name, count)
    for stack in vault:
        add(stack.get("entry") or 0, VAULT, stack.get("count") or 0)
    room = sum(
        max(0, m.bag_free - BAG_RESERVE) + max(0, m.bank_free - bank.BANK_FREE_RESERVE)
        for m in bankers
    )
    return Ledger(
        held={e: tuple(sorted(h.items())) for e, h in totals.items()},
        bankers=tuple(sorted(m.name for m in bankers)),
        room=room,
    )
