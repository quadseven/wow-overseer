"""A raider's role from the talent tree they play, not only from their class.

WHY THIS EXISTS. The lineup (raidlineup.py) packed forty raiders by class: a
warrior tanked, a priest healed, a druid filled whatever gap was left. Read
against the realm's own talents on 2026-09-24, that put three Fury warriors
and an Arms warrior in four of Cave's eight tank seats, three Shadow priests in
healer seats, and a Restoration druid and two Restoration shamans among the
damage dealers. Horde's Bonkers had its Enhancement shaman in a healer seat. A
raid leader reads the talent tree before the class.

THE READ. `character_talent` holds one row per learned talent spell with a
specMask saying which of the two builds it belongs to; the active build is
`characters.activeTalentGroup`. TALENTS_COLUMN is one correlated subquery a
member query adds to its SELECT (every guild read here aliases characters as
`c`), so each member row carries its active talent spells as one
comma-separated string. `tree_of` turns that into the tree holding the most
points, using the committed talents.json (the same file armory.TalentBook
reads; loaded here directly so raidlineup does not import armory, which
imports raidlineup).

THE ROLE of a class and tree is statweights.role_for, the one table the loot
council and mod-overseer's GearRoleFor already share. A member with no talent
spells, or a tie at the top, has no known tree and falls back to the class
rule the lineup has always used.

PURE: strings in, words out. The only file read is talents.json, once.
"""

from __future__ import annotations

import json
import os

import statweights

TANK, HEALER = statweights.TANK, statweights.HEALER
MELEE, RANGED, CASTER = statweights.MELEE, statweights.RANGED, statweights.CASTER
UNKNOWN = statweights.UNKNOWN

# The member row's key, and the subquery that fills it. `c` is characters.
KEY = "talent_spells"
TALENTS_COLUMN = (
    "(SELECT GROUP_CONCAT(t.spell) FROM character_talent t "
    "WHERE t.guid = c.guid AND (t.specMask & (1 << c.activeTalentGroup))) "
    "AS talent_spells"
)

_BOOK: dict | None = None


def _book() -> dict:
    """spell id -> (class id, tree name, rank), from talents.json, once."""
    global _BOOK
    if _BOOK is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "talents.json")
        with open(path) as f:
            raw = json.load(f)
        trees = raw.get("trees") or {}
        book = {}
        for talent in raw.get("talents") or ():
            tree = trees.get(str(talent.get("tree"))) or {}
            for index, spell in enumerate(talent.get("ranks") or ()):
                book[int(spell)] = (
                    int(tree.get("class") or 0),
                    str(tree.get("name") or ""),
                    index + 1,
                )
        _BOOK = book
    return _BOOK


def _spells(text) -> list:
    out = []
    for part in str(text or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def tree_of(class_id, talent_spells) -> str:
    """The talent tree with the most points, or "" when none or a tie.

    A spell the book does not know, or one from another class's trees, is
    not counted: it cannot say which of this class's trees is played.
    """
    try:
        cid = int(class_id)
    except (TypeError, ValueError):
        return ""
    book = _book()
    points: dict = {}
    for spell in _spells(talent_spells):
        found = book.get(spell)
        if not found or found[0] != cid:
            continue
        points[found[1]] = points.get(found[1], 0) + found[2]
    if not points:
        return ""
    ranked = sorted(points.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return ""
    return ranked[0][0]


def role_of(member: dict) -> str:
    """tank, healer, melee, ranged or caster from the member's tree, or
    UNKNOWN when the tree is not known (no talent spells read)."""
    tree = member.get("spec")
    if tree is None:
        tree = tree_of(member.get("class_id"), member.get(KEY))
    if not tree:
        # A class with one role whatever its tree needs no talents to say it.
        return statweights.role_for(member.get("class_id"), "")
    return statweights.role_for(member.get("class_id"), tree)


def with_spec(member: dict) -> dict:
    """The member with `spec` (its tree, or "") and `raid_role` filled in."""
    out = dict(member)
    if out.get("spec") is None:
        out["spec"] = tree_of(out.get("class_id"), out.get(KEY))
    out["raid_role"] = role_of(out)
    return out
