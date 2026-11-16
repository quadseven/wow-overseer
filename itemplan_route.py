"""Carry out the item plan's bank routes (#2136).

WHY. `itemplan.plan` names GUILD_BANK (with a tab) and BANK_PERSONAL for a
stack nobody in the family will wear, and nothing carried either route out.
The loot policy refuses every sale of an uncommon or better piece, the plan's
own executors write only a give, a sale, a listing or a breakdown, and the
bank pass answered a separate question (its keeper rule), so a bag full of
unworn greens stayed full: measured on the dev realm, three members sat at
two or three free slots with 8 to 16 stacks planned for a bank and no bank row
written for the family in a day.

WHAT THIS DOES. It turns those two routes into the bank pass's own `bank.Move`
values and adds them to `bank.Plan`, so the rows are written by the machinery
that already walks a family to a banker or the guild vault, writes
`bank deposit-item guid:<n> tab:<t>` or `deposit guid:<n>`, keeps the retry
window and refuses a row for an item a quest in the log names.

THE GUARD. Every move passes the loot policy first (`lootpolicy.allowed`
with the deposit kinds): the guild vault takes only what the policy files
under BANK_OR_AUCTION, the holder's own bank also takes a bound piece that
stays with its holder, and an upgrade for a guildmate, an unread fact or a
quest-log hold never moves. A deposit never writes a sale, so an epic is never
sold by this route. A judge that is missing or fails deposits nothing.

PURE. Decisions and rows in, moves out. No MySQL, no clock.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

import bank
import bag_pressure
import itemplan
import lootpolicy

ENV_SWITCH = "ITEMPLAN_BANK"
PREFIX = "item plan bank route:"


def enabled(environ=None) -> bool:
    """On unless ITEMPLAN_BANK reads off, 0, false or no."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


@dataclass(frozen=True)
class Held:
    """A stack the plan would bank that the guard kept in the bags."""

    holder: str
    name: str
    why: str


@dataclass(frozen=True)
class Routed:
    moves: tuple = ()
    held: tuple = ()


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def routes_for(plan_, stack_rows, judge, keep_names=()) -> Routed:
    """The bank moves for a plan's GUILD_BANK and BANK_PERSONAL decisions.

    `stack_rows` is (stack, carried row) pairs; `judge(row, holder)` returns
    the loot policy's Verdict for the carried copy and may raise.
    """
    by_key = {stack.key: (stack, row) for stack, row in stack_rows}
    moves, held = [], []
    for d in plan_.decisions:
        if (
            d.route not in (itemplan.GUILD_BANK, itemplan.BANK_PERSONAL)
            or d.from_loc not in itemplan.CARRIED
            or d.stuck
        ):
            continue
        found = by_key.get(d.key)
        if found is None:
            continue
        stack, row = found
        guid = _int(row.get("item_guid"))
        if guid <= 0 or bag_pressure.owner_keeps(row.get("name", ""), keep_names):
            continue
        to_guild = d.route == itemplan.GUILD_BANK
        why = _refusal(stack, row, d, judge, to_guild)
        if why:
            held.append(Held(d.holder, d.name, why))
            continue
        moves.append(
            bank.Move(
                d.holder,
                bank.DEPOSIT,
                guid,
                d.name,
                d.count,
                d.reason,
                bank.GUILD if to_guild else bank.PERSONAL,
                d.tab if to_guild and d.tab >= 0 else 0,
            )
        )
    return Routed(tuple(moves), tuple(held))


def _refusal(stack, row, d, judge, to_guild) -> str:
    """Why the guard keeps this stack in the bags, or '' to move it."""
    if stack.quest_needed is not False:
        return "a quest in the holder's log names it, or the log was not read"
    if judge is None:
        return "the loot policy could not be judged"
    try:
        verdict = judge(row, d.holder)
    except Exception:
        return "the loot policy could not be judged (the read failed)"
    kind = lootpolicy.GUILD_DEPOSIT if to_guild else lootpolicy.BANK_DEPOSIT
    if lootpolicy.allowed(verdict, kind):
        return ""
    return "the loot policy says %s: %s" % (verdict.route, verdict.why)


def merge(plan_, routed: Routed, limit: int = bank.VISIT_LIMIT):
    """`bank.Plan` plus the routed moves, deduplicated by item guid.

    A holder carries at most `limit` moves in all, the bank pass's own visit
    cap. Banker moves join `moves`, vault moves join `guild`.
    """
    seen = {m.guid for m in plan_.moves} | {m.guid for m in plan_.guild}
    per = {}
    for m in tuple(plan_.moves) + tuple(plan_.guild):
        per[m.character] = per.get(m.character, 0) + 1
    banker, vault = [], []
    for m in routed.moves:
        if m.guid in seen or per.get(m.character, 0) >= limit:
            continue
        seen.add(m.guid)
        per[m.character] = per.get(m.character, 0) + 1
        (vault if m.to == bank.GUILD else banker).append(m)
    notes = list(plan_.notes)
    if banker or vault:
        notes.append(
            "%s %d to a banker and %d to the guild vault, from the item plan"
            % (PREFIX, len(banker), len(vault))
        )
    for h in routed.held:
        notes.append(
            "%s %s keeps %s in the bags: %s" % (PREFIX, h.holder, h.name, h.why)
        )
    return replace(
        plan_,
        moves=tuple(plan_.moves) + tuple(banker),
        guild=tuple(plan_.guild) + tuple(vault),
        notes=tuple(dict.fromkeys(notes)),
    )
