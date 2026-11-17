"""The tools a family member is owed for a trade it holds (ticket 2269).

WHY THIS EXISTS. The family supply pass buys a Mining Pick or a Skinning
Knife for a member holding the trade (ticket 2267, the guild jobs tables).
The Blacksmith Hammer was bought on a different key: the standing craft. A
smith whose family is out gathering, with no craft standing, was never
offered one, and every worn Blacksmithing recipe needs the hammer, so the
first craft could never start.

THE RULE. Holding the trade is the whole condition, for the hammer as for
the pick and the knife. The one exception is a smith whose standing craft
already names the hammer: the standing-craft buyer owns that member (it
answers the tool requests the module raises against the recipe), so the
trade buyer leaves the hammer to it and no member is judged twice.

HELD MEANS BAGS OR BANK. The module banks the hammer between crafts, so the
caller's holdings read counts every slot the character owns.

PURE: tables and a filter. No database, no clock.
"""

from __future__ import annotations

import craft
import craft_supply
import guildjobs

BLACKSMITHING = guildjobs.BLACKSMITHING

# skill -> (entry, label, vendor price in copper): the guild jobs rows for the
# gathering trades, and the supply pass's own row for the hammer.
TOOLS: dict = {
    **guildjobs.TOOLS,
    BLACKSMITHING: craft_supply.BLACKSMITH_HAMMER,
}

# skill -> every entry that counts as holding the tool. The hammer has one:
# the standing-craft buyer's holders read asks for this entry alone.
TOOL_ENTRIES: dict = {
    **guildjobs.TOOL_ENTRIES,
    BLACKSMITHING: frozenset({craft.BLACKSMITH_HAMMER}),
}


def trades_owed(trades: dict, standing: dict | None = None) -> dict:
    """name -> the held trades the trade buyer judges, out of `trades`.

    `trades` is name -> the tool trades each member holds. `standing` is the
    supply pass's name -> (craft_spell, money). Blacksmithing is dropped for
    a member whose standing craft needs the hammer, and a member left with
    no trade is dropped.
    """
    out: dict = {}
    for name, held in (trades or {}).items():
        kept = set(held)
        spell = (standing or {}).get(name, (0, 0))[0]
        if craft.tool_for(spell) == craft.BLACKSMITH_HAMMER:
            kept.discard(BLACKSMITHING)
        if kept:
            out[name] = kept
    return out
