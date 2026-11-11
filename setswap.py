"""Fetch a family member's banked upgrades for its actual tank or healing spec.

The normal bank visit owns room and travel; the normal equip drive puts the
withdrawn piece on. This first slice does not assign seats or restore a
previous outfit. The equip scorer owns item legality and comparisons.
"""

import equipscore
import guildrun


def bank_routes(wearer_rows, gear_rows, banked_rows, names, keep_names=(), book=None):
    """Banked item guid -> its holder, for upgrades a real support spec can use.

    Include carried competitors so a bank trip never fetches a weaker copy
    than an upgrade already in the bags. Unspent target talents do not count.
    """
    names = set(names)
    rows = []
    for row in wearer_rows:
        member = guildrun.member_from_row(row)
        if (
            member
            and member.name in names
            and (member.plays(guildrun.TANK) or member.plays(guildrun.HEALER))
        ):
            rows.append(row)
    banked = {(int(row["item_guid"]), str(row["holder"])) for row in banked_rows}
    plan = equipscore.plan(
        (),
        rows,
        list(gear_rows) + list(banked_rows),
        names,
        keep_names=keep_names,
        book=book,
    )
    return {
        equip.guid: equip.holder
        for equip in plan.equips
        if (equip.guid, equip.holder) in banked
    }
