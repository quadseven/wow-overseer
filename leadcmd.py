"""A family leader's movement belongs to mod-overseer's intent book.

WHY THIS EXISTS. The operator watched the Alliance leader's stream on the dev
realm and saw him walk in stutter steps. In one five-minute window
(2026-09-26 02:07-02:12 UTC) this bridge handed him `follow` twice, and the
module's regroup hold took it off each time. Over the week before, the
bridge's in-game ear queued `stay` for him 18 times, `follow` 21 times and
`reset ai` 31 times, every one off a line his own family's bots said. The life
rule toggled `nc +new rpg` / `nc -new rpg` on him every ten minutes. Upstream's
`stay` stops a moving bot on every tick its walk yields, and nothing ever took
it off again.

mod-overseer now gives each family leader one movement owner (its intent
book, mod-overseer#722) and refuses these commands for a leader unless the
operator sent them. This module is the bridge's half: it does not queue them
for a leader in the first place, so they are not written only to be refused.

THE SAME RULES AS THE MODULE'S `LeaderCommandRefusal`: `follow`, `stay`,
`reset ai` / `reset botai`, and any `nc` list that puts `new rpg`, `follow` or
`stay` on or off. Everything else passes, including `co +flee` and the
level strategies. A follower is never filtered.

Pure: strings in, strings out.
"""

from __future__ import annotations

_BARE = frozenset({"follow", "stay", "reset ai", "reset botai"})
_BOOK_OWNS = frozenset({"new rpg", "follow", "stay"})


def moves_the_leader(command: str) -> bool:
    """Would this bot command move a leader against the intent book?"""
    verb = " ".join(str(command or "").lower().split())
    if verb in _BARE:
        return True
    if not verb.startswith("nc "):
        return False
    for item in verb[3:].split(","):
        item = item.strip()
        if item[:1] in ("+", "-", "~"):
            item = item[1:].strip()
        if item in _BOOK_OWNS:
            return True
    return False


def for_character(commands, is_leader: bool) -> list:
    """`commands` minus what would move a leader, when this one leads."""
    if not is_leader:
        return list(commands)
    return [c for c in commands if not moves_the_leader(c)]
