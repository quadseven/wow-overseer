"""The guild hand-over rows (#174): how they are keyed, and what the Bags page says.

WHO GETS A GUILDMATE'S LOOT IS NOT DECIDED HERE. `gear.rank_receivers`,
`gear.route_plan` and `gear.route_deliverable` decide it, through
`bag_pressure`'s adapters, because gear.py is the one opinion about what is
an upgrade and bag_pressure is the one place rows become its shapes. This
module owns only the two ends of the row the bridge writes:

    source   "guildroute:<gain>" on every overseer_command row the pass
             writes, so its retry window and the Bags page find its rows and
             the page can say why the item moved without a second table.
    view     one sentence per recent row, for the Bags tab.

PURE MODULE: no MySQL and no clock.
"""

from __future__ import annotations

import re

SOURCE = "guildroute"

# The verb a posted hand-over is written with (kind='mail'), and the only two
# kinds a hand-over row may carry: a trade between two characters standing
# together, or a letter. Never 'give', which moves an item across any distance.
MAIL = "mail"
VERBS = ("trade", MAIL)

VIEW_LABEL = "guild hand-overs"
VIEW_INDEX = "04"
VIEW_EMPTY = (
    "Nothing handed over across the guild lately. A guildmate's item moves "
    "only by a trade when the two are together, or by post from a mailbox."
)

_ITEM_GUID = re.compile(r"(?:^|\s)(?:guid|item):(\d+)")
_STATUS_WORDS = {
    "pending": "waiting for the world",
    "claimed": "under way",
    "delivered": "done",
}


def source_for(gain) -> str:
    """The `source` a hand-over row is written with."""
    return "%s:%d" % (SOURCE, max(0, int(gain)))


def gain_of(source) -> int:
    """The gain a row's `source` carries, 0 when it carries none."""
    text = str(source or "")
    if not text.startswith(SOURCE + ":"):
        return 0
    tail = text[len(SOURCE) + 1 :]
    return int(tail) if tail.isdigit() else 0


def guid_of(command) -> int:
    """The item_instance guid a trade or mail command names, 0 for none."""
    match = _ITEM_GUID.search(str(command or ""))
    return int(match.group(1)) if match else 0


def view(rows, item_names=None) -> dict:
    """One sentence per hand-over row, in the order given, for the Bags page.

    `rows` are overseer_command rows this pass wrote (target_name, target_arg,
    kind, command, status, detail, source). `item_names` maps item guid to the
    item's name, read by the caller; a guid it does not know is named by
    number rather than dropped. A delivered letter is POSTED, not received:
    the receiver still has to reach a mailbox, and the page says so.
    """
    names = dict(item_names or {})
    lines = []
    for row in rows or ():
        guid = guid_of(row.get("command"))
        item = names.get(guid) or ("item %d" % guid if guid else "an item")
        posted = row.get("kind") == MAIL
        status = str(row.get("status") or "")
        if status == "delivered" and posted:
            outcome = "posted, waiting at the mailbox"
        elif status == "error":
            outcome = "refused: %s" % (row.get("detail") or "no reason given")
        else:
            outcome = _STATUS_WORDS.get(status, status or "unknown")
        lines.append(
            "%s to %s: %s %s, +%d item levels - %s"
            % (
                row.get("target_name") or "?",
                row.get("target_arg") or "?",
                item,
                "by post" if posted else "by trade",
                gain_of(row.get("source")),
                outcome,
            )
        )
    return {
        "index": VIEW_INDEX,
        "label": VIEW_LABEL,
        "lines": lines,
        "empty": VIEW_EMPTY,
    }
