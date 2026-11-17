"""Quests a holder could take for the quest items it already carries (#2648).

Pure module, the same seam as questbook.py: facts in, judgements out. Nothing
is read here. The caller reads `quest_template` (required items, drops and
start item) and the holder's quest tables, builds a `questbook.Member` and a
catalogue of `questbook.Quest`, and hands them in.

WHY THIS EXISTS. About 40 percent of the quest-class stacks the guilds carry
are named by a quest the holder has not taken yet and could. No pass sends the
holder to take them, so they sit in the bags. This module answers the first
half of that: for one holder, which untaken quests do its quest-class stacks
name, and which of those may it take. It chooses nothing and walks nowhere;
the take step that acts on the answer is a later slice.

A quest counts as takable when it is not in the log, not rewarded, and
`questbook.blockers` finds nothing against it: class, race, level window,
prerequisite and exclusive group are all judged there, once, for every caller.
Items named only by finished or closed quests, and by no quest at all, are not
this module's concern (#2607 destroys those).
"""

from __future__ import annotations

from dataclasses import dataclass

import questbook

REQUIRED_COLUMNS = tuple(f"RequiredItemId{i}" for i in range(1, 7))
DROP_COLUMNS = tuple(f"ItemDrop{i}" for i in range(1, 5))
ITEM_COLUMNS = (*REQUIRED_COLUMNS, *DROP_COLUMNS, "StartItem")


@dataclass(frozen=True)
class Untaken:
    """One quest the holder could take, and the carried items that name it."""

    quest_id: int
    title: str
    items: tuple  # carried item ids that this quest names, sorted


@dataclass(frozen=True)
class Cover:
    """What one pass found for one holder."""

    name: str
    quests: tuple  # Untaken, sorted by quest id
    items: frozenset  # carried item ids covered by at least one takable quest
    refused: tuple  # (quest id, blockers) for named quests that cannot be taken


def item_quests(rows) -> dict:
    """Map item id -> frozenset of quest ids that name it.

    `rows` are quest_template rows carrying `ID` and the item columns above. A
    zero or missing column names nothing.
    """
    out: dict = {}
    for row in rows:
        quest_id = int(row.get("ID") or 0)
        if not quest_id:
            continue
        for column in ITEM_COLUMNS:
            item = int(row.get(column) or 0)
            if item:
                out.setdefault(item, set()).add(quest_id)
    return {item: frozenset(ids) for item, ids in out.items()}


def untaken_for(member, carried, naming, catalog) -> Cover:
    """The untaken, takable quests the holder's carried items name.

    `carried` is the item ids of the holder's quest-class stacks, `naming` the
    map from `item_quests`, `catalog` a dict of quest id -> `questbook.Quest`.
    A named quest missing from the catalogue is skipped: it cannot be judged,
    and a guess would send a holder after a quest it may be shut out of.
    """
    seen: dict = {}
    for item in carried:
        for quest_id in naming.get(int(item), ()):
            seen.setdefault(quest_id, set()).add(int(item))
    quests = []
    refused = []
    covered: set = set()
    for quest_id in sorted(seen):
        quest = catalog.get(quest_id)
        if quest is None or quest_id in member.held:
            continue
        reasons = questbook.blockers(member, quest, catalog=catalog)
        if questbook.DONE in reasons:
            continue
        if reasons:
            refused.append((quest_id, reasons))
            continue
        items = tuple(sorted(seen[quest_id]))
        quests.append(Untaken(quest_id, quest.title, items))
        covered.update(items)
    return Cover(member.name, tuple(quests), frozenset(covered), tuple(refused))


def say(cover: Cover) -> str:
    """The one log line per holder per pass: items covered and quests takable."""
    return (
        f"untaken quests: {cover.name} {len(cover.items)} items covered, "
        f"{len(cover.quests)} takable, {len(cover.refused)} closed"
    )
