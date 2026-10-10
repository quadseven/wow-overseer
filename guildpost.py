"""A guild bot's own post: the letters with items or gold, taken out at a mailbox (#625).

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
    # Copper on a letter of gold (item_guid 0), taken with `take-money`.
    money: int = 0


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
    money = _int(row.get("money"))
    # A LETTER OF GOLD (2026-10-10): a row with no attachment and money on it
    # is the gold itself, taken out with `take-money` (the guild fund's
    # training letters and dues refunds, guildfund.py).
    if not receiver or mail_id <= 0 or item_guid < 0 or (item_guid == 0 and money <= 0):
        return None
    ready = bool(_int(row.get("delivered"), 1)) and _int(row.get("cod")) == 0
    if item_guid == 0:
        return Letter(receiver, mail_id, 0, "%d copper" % money, ready, money)
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
        if not self.item_guid:
            return "%s mail:%d" % (mailrun.TAKE_MONEY, self.mail_id)
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
    # GOLD FIRST, AND IT NEEDS NO BAG SLOT (mailrun's own order): a member
    # with full bags still takes the gold the guild posted it.
    gold = sorted((x for x in waiting if not x.item_guid), key=lambda x: x.mail_id)
    items = sorted(
        (x for x in waiting if x.item_guid), key=lambda x: (x.mail_id, x.item_guid)
    )
    chosen = (
        gold[:TAKES_PER_VISIT]
        + items[: max(0, min(limit, TAKES_PER_VISIT - len(gold)))]
    )
    if not chosen:
        return None, "%s has %d letter(s) and no free bag slot" % (
            receiver,
            len(waiting),
        )
    takes = tuple(Take(x.receiver, x.mail_id, x.item_guid, x.name) for x in chosen)
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
    # A MEMBER SITTING OUT TO CRAFT GOES FIRST. WALKS_PER_PASS is 3 and the
    # order was most letters first, so the master tailor with one letter of
    # cloth from the crew stood behind 23 guildmates (93 letters on wow-dev,
    # 2026-10-06) and his 20 Linen Cloth sat unclaimed for hours.
    crafters = set(sitting_out or ())
    order = sorted(
        by_receiver, key=lambda n: (n not in crafters, -len(by_receiver[n]), n)
    )
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
