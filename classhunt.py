"""The kill and the loot of a class quest hunt, and what the bridge does next.

THE GAP. A class quest hunt used to end at `walk-to-spawn creature:<spawn id>`:
the member stood where its objective's creatures live and its own grind and
loot strategies were supposed to do the rest. No hunt ever produced a drop (not
one tank warrior has ever looted a Singed Scale). quadseven/mod-overseer#869
adds the verb that makes an arrived bot do it:

  hunt-spawn creature:<entry> [count:<n>] [max:<seconds>]      kind='job'

`<entry>` is a creature TEMPLATE entry, not a spawn id; `count:` is 1..200 kills
after which the row is done; `max:` is 1..1800 seconds (default 600). While it
runs the row is `verifying` and its result JSON is rewritten every 15 seconds
(`outcome` hunting, then done / timeout / refused, with `reason`, `retry`
later / elsewhere / never, `kills`, `pulls`, `loot_count`, `loot_items`). The
final status is `applied` (done, or timeout with kills), `unchanged` (timeout
with no kill) or `error` (refused). The bridge ends a row by moving it off
`verifying`; the module notices within 10 seconds.

WHAT THE BRIDGE DOES (bridge._class_hunt_row), after the walk row arrives:

  1. writes the hunt row for the entry of the creature at the pack it walked to
     (kill objective: `count:` is the quest's own kill count; an item that drops:
     no count, the counters decide);
  2. reads the member's quest counters from character_queststatus at every poll
     and ends the row the moment they say the objective is complete (finished);
  3. on a refusal, `later` waits and asks again (MAX_ATTEMPTS), `elsewhere`
     leaves this pack for the next one, `never` gives the quest up so the member
     asks guild chat (classask.py).

A WORLDSERVER BEFORE #869, or one with `Overseer.Hunt.Enable = 0`, answers
`unknown job mode` / `malformed request` or refuses with DISABLED. That is
UNSUPPORTED, exactly as classuse.py reads it: the plan goes back to today's
walk-only hunt for WALK_UNSUPPORTED_SECONDS (guildroute) and the verb is never
hammered. DISABLED is a refusal the module calls `never`, but it says nothing
about the quest, so it must not give the quest up.

THE REALM'S HUNT CEILING (`Overseer.Hunt.AtOnce`, default 4) is spent like the
far walk slots (classquest.FarSlots): the plan writes no more hunt rows than the
slots left after the open `hunt-spawn` rows, tank-spec warriors and healers
first (guildjobs.class_priority).

PURE MODULE: a row's answer in, a verdict out. No MySQL, no clock, no sleeping.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import classquest

VERB = "hunt-spawn"

# The module's hunt ceiling when the realm says nothing else.
HUNTS_AT_ONCE = 4
# A hunt row's own ceiling in seconds. The module allows 1800; the bridge asks
# for a modest one because the row is ended by the bridge when the quest is
# done and otherwise runs out by itself.
MAX_SECONDS = 480
# The module's count range.
MAX_COUNT = 200
# A member within this many yards of the pack's spawn is already inside the
# module's 60 yard reach and writes the row with no walk.
HUNT_NEAR = 40.0

# Verdicts.
RUNNING = "running"
DONE = "done"
NOTHING = "nothing"
LATER = "later"
ELSEWHERE = "elsewhere"
NEVER = "never"
UNSUPPORTED = "unsupported"
# A hunt that killed its target and found no respawn due before its clock ran
# out: the member is left alone (classquest.NO_RESPAWN_BACKOFF_MINUTES).
RESPAWNING = "respawning"
# The module's answer to a key it does not know, from a worldserver before
# mod-overseer#871: the item token is rejected as a malformed row.
ITEM_TOKEN = " item:"
ITEMLESS = "itemless"
UNREADABLE = "unreadable"

# The module's answers that mean "this worldserver does not hunt".
UNKNOWN_JOB_MODE = "unknown job mode"
OLD_PARSER = "malformed request"
DISABLED = "Overseer.Hunt.Enable is off"
# The module's refusal for a row it could not read: the bridge wrote it wrong.
MALFORMED = "malformed hunt-spawn command"

# Asks per step: the first and, after a wait, two more.
MAX_ATTEMPTS = 3
# Seconds to wait before asking again after a `later` refusal (a hunt at the
# ceiling, a bot resting, no creature in reach yet).
LATER_WAIT_SECONDS = 60.0
# Seconds between reads of a running row: the module rewrites it every 15.
POLL_SECONDS = 15.0
# The most seconds one step follows hunt rows for, across every ask. The guild
# step clock (guildroute.GUILD_STEP_SECONDS) also covers the walk before it.
FOLLOW_SECONDS = 900.0
# Extra seconds a row is followed past its own max, for the module's last write.
GRACE_SECONDS = 45.0


class Slots(classquest.FarSlots):
    """The hunt slots the realm has free this pass, spent as the plan writes
    hunt rows so the bridge never writes more than the realm can take. `free`
    None means the count is unknown and nothing is held back."""


def free_slots(open_rows, at_once=HUNTS_AT_ONCE):
    """The hunts the realm can still take, from the hunt rows still open
    (pending, claimed or verifying); None when the count could not be read."""
    if open_rows is None:
        return None
    return max(0, int(at_once) - int(open_rows))


def is_hunt_row(command) -> bool:
    """True for a job row that hunts."""
    return str(command or "").split(" ", 1)[0] == VERB


def command(quest: classquest.Quest, entry, held=None, item_form=True) -> str:
    """The `hunt-spawn` row for `entry`, a creature of the quest's objective,
    or "" when the quest has no creature to hunt there.

    A kill objective asks for its own kill count, so the row finishes by itself.
    An item the creature drops (mod-overseer#871) names the item and how many
    are still missing, `item:<entry> count:<needed>`: the module loots the
    corpse itself and ends the row `done` when the bot holds that many. `held`
    is the member's count of an item (guildjobs.Member.count). With
    `item_form` False (a worldserver that rejects `item:`) or no known item,
    the row asks for neither, and the bridge ends it when the member's counters
    say the quest is complete.
    """
    entry = int(entry or 0)
    if entry <= 0:
        return ""
    kills = dict(quest.kills)
    if entry in kills:
        word = " count:%d" % min(MAX_COUNT, max(1, int(kills[entry])))
        return "%s creature:%d%s max:%d" % (VERB, entry, word, MAX_SECONDS)
    word = ""
    wants = dict(quest.items)
    item = next((i for i, e in quest.drops if e == entry and i in wants), 0)
    if item and item_form:
        have = int(held(item)) if callable(held) else 0
        need = min(MAX_COUNT, max(1, int(wants[item]) - have))
        word = " item:%d count:%d" % (item, need)
    return "%s creature:%d%s max:%d" % (VERB, entry, word, MAX_SECONDS)


def plain_form(row) -> str:
    """The same row without the `item:` and `count:` keys, for a worldserver
    that rejects the item token."""
    return re.sub(r" (?:item|count):\d+", "", str(row or ""))


def wanted(quest: classquest.Quest) -> int:
    """The sum of every kill and item count the quest requires: what the
    counters of character_queststatus add up to when the objective is done."""
    return sum(n for _e, n in quest.kills) + sum(n for _i, n in quest.items)


def finished(quest: classquest.Quest, status, progress, held=None) -> bool:
    """True when character_queststatus says the objective is complete: the
    core's own complete status, counters (their sum, as LOG_SQL reads them)
    that reach what the quest requires, or, for an item objective with no kill
    in it, the bags (`held`, item entry -> count) holding every item required."""
    try:
        if int(status) == classquest.STATUS_COMPLETE:
            return True
        if held and quest.items and not quest.kills:
            if all(int(held.get(i, 0)) >= n for i, n in quest.items):
                return True
        return 0 < wanted(quest) <= int(progress)
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Answer:
    """One reading of a hunt row: `state`, the sentence for the log, and the
    seconds to wait before asking again."""

    state: str
    said: str = ""
    wait: float = 0.0


def _body(result) -> dict:
    if isinstance(result, dict):
        return result
    try:
        parsed = json.loads(result or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def unsupported(status, detail) -> bool:
    """True when this answer says the worldserver does not hunt (an older
    module, or a hunt switched off)."""
    if str(status or "").strip().lower() != "error":
        return False
    detail = str(detail or "")
    return (
        UNKNOWN_JOB_MODE in detail
        or detail.startswith(OLD_PARSER)
        or detail == DISABLED
    )


def _retry_word(detail, body) -> str:
    word = str(body.get("retry") or "").strip().lower()
    if word in (NEVER, ELSEWHERE, LATER):
        return word
    return LATER


def _count(body, key) -> int:
    try:
        return max(0, int(body.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _heard(body) -> str:
    """` (<kills> kill(s), <loot> looted)` from a result."""
    return " (%d kill(s), %d looted)" % (
        _count(body, "kills"),
        _count(body, "loot_count"),
    )


def judge(holder, status, detail, result, command="") -> Answer:
    """What one hunt row's status, detail and result say."""
    status = str(status or "").strip().lower()
    detail = str(detail or "").strip()
    body = _body(result)
    if status in ("pending", "claimed", "verifying", ""):
        return Answer(RUNNING, "%s's hunt row is running" % holder)
    if unsupported(status, detail):
        return Answer(
            UNSUPPORTED,
            "this worldserver answered the hunt as %r, so it cannot hunt a quest "
            "creature (yet); the walk-only hunt is used until it can" % detail,
        )
    if (
        status == "error"
        and ITEM_TOKEN in str(command)
        and MALFORMED
        in (
            detail,
            str(body.get("reason") or ""),
        )
    ):
        return Answer(
            ITEMLESS,
            "this worldserver rejects the item key of a hunt row; the plain row is "
            "used until it knows it",
        )
    if status == "applied":
        return Answer(DONE, "%s's hunt ended%s" % (holder, _heard(body)))
    if (
        status == "unchanged"
        and str(body.get("reason") or "") == classquest.NO_RESPAWN_REASON
    ):
        return Answer(RESPAWNING, "%s's target does not respawn in time" % holder)
    if status == "unchanged":
        return Answer(
            NOTHING,
            "%s's hunt ended with no kill%s"
            % (holder, " (%s)" % detail if detail else ""),
        )
    if str(body.get("outcome") or "").lower() == UNREADABLE:
        return Answer(UNREADABLE, "%s left the world during its hunt" % holder)
    reason = str(body.get("reason") or detail or "").strip()
    why = reason or "the world refused the hunt and said nothing about why"
    word = _retry_word(detail, body)
    if word == NEVER:
        return Answer(NEVER, "%s cannot hunt: %s" % (holder, why))
    if word == ELSEWHERE:
        return Answer(ELSEWHERE, "%s cannot hunt here: %s" % (holder, why))
    return Answer(
        LATER, "%s's hunt is refused for now: %s" % (holder, why), LATER_WAIT_SECONDS
    )
