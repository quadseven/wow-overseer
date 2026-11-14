"""Carry out the item plan's disenchant decisions (#1978).

The plan names DISENCHANT for a carried stack its holder can break down: the
holder is an enchanter whose Enchanting reaches the skill the core asks
(`item_template.RequiredDisenchantSkill`, read by `itemplan_data`, with no
breakdown at all for an item without a DisenchantID). This route turns one
such decision into a `disenchant` command row, matching the rollout in
`docs/ITEM_PLAN.md`: one route at a time, each with its own switch, acting
only where the current protection would keep the stack.

THE SWITCH is ITEMPLAN_DISENCHANT, off unless it reads on/1/true/yes. Its own,
apart from ITEMPLAN_SELL_VENDOR and from DISENCHANT_ROUTE (which diverts a
stack a sale path already let go).

WHAT COUNTS. A decision is carried out only when every one of these holds:

  * its route is DISENCHANT and the stack is carried and placed (not stuck);
  * the current protection would keep the stack (`bag_pressure.vendor_refusal`
    refuses the row), so a stack the ordinary sale pass sells is left to it;
  * a `confirm` decision (quality 3 or better, or worth a gold or more) has
    been released: its key is in the caller's `released` set. Breaking an
    item down cannot be undone, so it waits exactly as a sale does.

PURE. Decisions and rows in, jobs out. No MySQL, no clock. The bridge reads
the plan, applies the keep marks and the epic gate, and writes the row.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import bag_pressure
import itemplan

ENV_SWITCH = "ITEMPLAN_DISENCHANT"
PREFIX = "itemplan disenchant:"


def enabled(environ=None) -> bool:
    """On only when ITEMPLAN_DISENCHANT says so."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


@dataclass(frozen=True)
class Job:
    """One carried stack to break down, ready for the bridge to write."""

    holder: str
    item_guid: int
    name: str
    skill: int  # the holder's Enchanting, as the plan read it
    reason: str
    key: tuple


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def jobs_for(
    plan_, stack_rows, keep_names=(), released=frozenset(), members=None
) -> tuple:
    """The route's jobs from a plan, in plan order.

    `stack_rows` is (stack, carried row) pairs as `itemplan_shadow.build_stacks`
    and the economy pass's rows give them. `members` maps a holder to its
    Enchanting skill for the log line; the plan's own reason carries it when
    omitted.
    """
    rows_by_key = {stack.key: row for stack, row in stack_rows}
    out = []
    for decision in plan_.decisions:
        row = rows_by_key.get(decision.key)
        if (
            row is None
            or decision.route != itemplan.DISENCHANT
            or decision.from_loc not in itemplan.CARRIED
            or decision.stuck
        ):
            continue
        # The owner's own never-dispose mark is a keep, not a protection to
        # act past.
        if bag_pressure.owner_keeps(row.get("name", ""), keep_names):
            continue
        if not bag_pressure.vendor_refusal(row, keep_names):
            continue
        if decision.confirm and decision.key not in released:
            continue
        guid = _int(row.get("item_guid"))
        if guid <= 0:
            continue
        skill = _int((members or {}).get(decision.holder), -1)
        if skill < 0:
            skill = _skill_in(decision.reason)
        out.append(
            Job(
                holder=decision.holder,
                item_guid=guid,
                name=decision.name,
                skill=skill,
                reason=decision.reason,
                key=decision.key,
            )
        )
    return tuple(out)


def _skill_in(reason: str) -> int:
    """The Enchanting skill the plan's reason names ('enchanting 60 ...')."""
    words = str(reason).split()
    for before, word in zip(words, words[1:], strict=False):
        if before == "enchanting":
            return _int(word)
    return 0


def lines(jobs) -> tuple:
    """One log line per job, naming the stack and the skill that breaks it."""
    return tuple(
        "%s %s breaks down %s (guid %d) at Enchanting %d: %s"
        % (PREFIX, job.holder, job.name, job.item_guid, job.skill, job.reason)
        for job in jobs
    )
