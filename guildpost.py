"""A guild bot's own post: the letters with items, taken out at a mailbox (#625).

WHY THIS EXISTS. Measured on wow-dev 2026-10-05: 293 letters carrying items,
sent from one guildmate to another, sat unopened (Bonkers 210 of them since
2026-09-30, Cave 100). The gear route posts upgrades, the corps posts bags and
cloth, the dues and supply passes post materials, and only two kinds of
receiver ever collected: a roster family (its own mail pass) and a designated
crafter with a recipe letter (crafters.py). Every other guildmate's post
stayed in the box, so a bag or an upgrade sent to it was never worn.

WHAT A PLAYER DOES. Walks to a mailbox now and then and takes out what was
sent. So a guild member off the roster with letters waiting is walked to the
nearest mailbox by the module's own `walk-to-mailbox` row
(quadseven/mod-overseer#570) and takes each attachment out with `take-item`,
the same two rows the crafter pickup writes. Never a give, never a GM command.
What it does with the item afterwards is its own AI's and the other passes'
business: a bag is worn by the bag hand-over, gear by the playerbot's equip.

BOUNDED, like every guild pass: WALKS_PER_PASS receivers a pass, the ones with
the most letters waiting first, TAKES_PER_VISIT takes each, never more than
the free bag slots, never a letter still inside its delivery delay or one
carrying cash on delivery.

PURE MODULE: rows in, a plan and sentences out. No MySQL and no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import guildroute
import mailrun

LOG_PREFIX = "guild post:"
WALK_SOURCE = "guildpostwalk"
TAKE_SOURCE = "guildposttake"

WALKS_PER_PASS = 3
TAKES_PER_VISIT = 6


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Letter:
    """One attachment in one letter to one guild member."""

    receiver: str
    mail_id: int
    item_guid: int
    name: str
    ready: bool = True


def letter_from_row(row) -> Letter | None:
    """A Letter from one mail row, or None for a row that cannot be read.

    `ready` is False for a letter still inside its delivery delay or carrying
    cash on delivery; neither is ever taken from.
    """
    try:
        receiver = str(row["receiver"]).strip()
        mail_id = int(row["mail_id"])
        item_guid = int(row["item_guid"])
    except (KeyError, TypeError, ValueError):
        return None
    if not receiver or mail_id <= 0 or item_guid <= 0:
        return None
    ready = bool(_int(row.get("delivered"), 1)) and _int(row.get("cod")) == 0
    name = str(row.get("name") or "item %d" % item_guid)
    return Letter(receiver, mail_id, item_guid, name, ready)


@dataclass(frozen=True)
class Take:
    """One attachment to take out of one letter."""

    receiver: str
    mail_id: int
    item_guid: int
    name: str

    @property
    def command(self) -> str:
        return "%s mail:%d item:%d" % (mailrun.TAKE_ITEM, self.mail_id, self.item_guid)


@dataclass(frozen=True)
class Visit:
    """One guild member walked to a mailbox to take out its post."""

    receiver: str
    takes: tuple
    waiting: int = 0

    def walk_command(self, cap=guildroute.MAIL_RUN_YARDS) -> str:
        return guildroute.mailbox_walk_command(cap)

    @property
    def said(self) -> str:
        return "%s %s walks to a mailbox to take out %s (%d letter(s) waiting)" % (
            LOG_PREFIX,
            self.receiver,
            ", ".join(t.name for t in self.takes),
            self.waiting,
        )


def _waiting_by_receiver(letters, roster) -> dict:
    """receiver -> its ready letters, a roster member's left to its family.

    `roster` is the family names whose own mail pass collects; a member sitting
    out to craft is taken out of it by `visits` (see there).
    """
    out: dict = {}
    for letter in letters or ():
        if letter.receiver not in roster and letter.ready:
            out.setdefault(letter.receiver, []).append(letter)
    return out


def _visit_for(receiver, waiting, online, busy, free_slots):
    """(Visit or None, note) for one receiver with letters waiting."""
    if receiver not in online:
        return None, ""
    if receiver in busy:
        return None, "%s is already on a walk" % receiver
    room = _int(free_slots.get(receiver), -1)
    limit = TAKES_PER_VISIT if room < 0 else min(TAKES_PER_VISIT, room)
    if limit <= 0:
        return None, "%s has %d letter(s) and no free bag slot" % (
            receiver,
            len(waiting),
        )
    takes = tuple(
        Take(x.receiver, x.mail_id, x.item_guid, x.name)
        for x in sorted(waiting, key=lambda x: (x.mail_id, x.item_guid))[:limit]
    )
    return Visit(receiver, takes, len(waiting)), ""


def visits(
    letters,
    online,
    busy=frozenset(),
    free_slots=None,
    roster=frozenset(),
    sitting_out=frozenset(),
):
    """(visits, notes): which guild members walk to take out their post.

    `online` holds the names standing in the world now; `busy` the names
    another guild pass has on a walk; `roster` the family members, whose own
    mail pass collects. `free_slots` maps a name to its free bag slots, -1 or
    absent when unread (then TAKES_PER_VISIT stands).

    `sitting_out` holds the family members the caller found free to walk: out
    of their family's campaign to craft (standin.py), so the family's own mail
    pass, which collects only when the family stands at a mailbox, never
    reaches them. They are walked like any guildmate. A name here that is not
    on the roster changes nothing.
    """
    free_slots = free_slots or {}
    online, busy = set(online or ()), set(busy or ())
    by_receiver = _waiting_by_receiver(
        letters, set(roster or ()) - set(sitting_out or ())
    )
    order = sorted(by_receiver, key=lambda n: (-len(by_receiver[n]), n))
    out, notes = [], []
    for receiver in order:
        if len(out) >= WALKS_PER_PASS:
            notes.append("%s waits: %d walks this pass" % (receiver, WALKS_PER_PASS))
            continue
        visit, note = _visit_for(
            receiver, by_receiver[receiver], online, busy, free_slots
        )
        if visit is not None:
            out.append(visit)
        elif note:
            notes.append(note)
    return out, notes


def walk_refusal(name: str, walker, cap=guildroute.MAIL_RUN_YARDS) -> str:
    """Why this member is not walked to a mailbox now, "" when it can be.

    The gear route's own refusals (`guildroute.cannot_walk`) at the cap this
    pass walks (`guildroute.walk_cap`), and only a bot the module's walk row
    can move.
    """
    why = guildroute.cannot_walk(walker, name, cap)
    if not why and walker is not None and not walker.by_row:
        why = "%s cannot be walked by the mailbox walk row" % name
    return "%s waits: %s" % (name, why) if why else ""
