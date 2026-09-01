"""Pure builder for the Armory tab: character rows -> gear and build, per member.

WHY THIS EXISTS. What the five are WEARING and how they are SPECCED are the
two things that decide whether a dungeon run works, and until this tab both
were invisible on every surface the overseer has. Answering either one meant
writing SQL by hand, which is why a real defect - the watched character being
the only one nobody buffs (mod-overseer#80) - hid for as long as it did. A
thing nobody can see is a thing nobody checks.

Same seam rule as map_core, panel and family (infra#2597): the HTTP adapter
fetches rows and does nothing else. Every judgement here is a decision -
which slots count as gear at all, what an empty slot means, how a pile of
spell ids becomes "0/0/16 Protection" - so all of it lives in this module
where the stdlib suite can reach it without a database.

THE TALENT PROBLEM, AND THE ROUTE CHOSEN. `character_talent` stores one row
per learned talent and the only thing in that row is the spell id of the rank
currently held. Turning that back into a build needs the client's Talent.dbc
and TalentTab.dbc, and those are exactly what the server database does NOT
have: acore_world ships `talent_dbc` and `talenttab_dbc` as EMPTY tables
because the core reads the real DBCs off disk. The three routes were: mount
the DBC directory into this pod (a new runtime dependency, on a deployment
that is not the worldserver), populate the empty world tables (an admin
change to a database that gets rebuilt from upstream), or freeze the DBCs
into a committed reference file. The third is what zones.json and shapes.json
already do with frozen 3.3.5a client data, so it is what this does too:
tools/gen_talents.py writes talents.json, TalentBook reads it, and the
PER-CHARACTER data still comes from the live database on every poll.

Ticket: infra#3096.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import bonds
import family
from core import _ALLIANCE_RACES, _HORDE_RACES
from panel import _CLASS_NAMES, _EQUIPMENT_SLOT_NAMES, _RACE_NAMES

# The paper doll, in slot order, re-exported under a public name. panel owns
# the list; both the SQL bound (`ci.slot < len(EQUIPPED_SLOTS)`) and the rows
# this module builds read it from here, so the query and the grid cannot come
# to disagree about how many slots a character has.
EQUIPPED_SLOTS = _EQUIPMENT_SLOT_NAMES

# Item quality, and the word the game itself uses for each. The page owns the
# colours; naming them here keeps "what quality 4 is called" in one place
# rather than in a switch statement inside a render function.
QUALITY_NAMES = {
    0: "poor", 1: "common", 2: "uncommon", 3: "rare",
    4: "epic", 5: "legendary", 6: "artifact", 7: "heirloom",
}
UNKNOWN_QUALITY = "unknown"

# Shirt and tabard carry no stats in 3.3.5 - they are clothes, not equipment.
# They are still DRAWN, because "what is he wearing" includes them, but they
# are excluded from the empty count and the average item level. Without this
# every character on the server reads as permanently two slots short, and a
# number that is always wrong by two is a number nobody reads.
COSMETIC_SLOTS = frozenset({"shirt", "tabard"})

# A talent point arrives every level from 10 on. Rate.Talent is 1 on this
# realm, which is the assumption this budget makes.
FIRST_TALENT_LEVEL = 10

# Death Knights are the one class whose budget is not a function of level:
# theirs also counts quest rewards, tracked in memory by the core and not
# exposed as a column here. So for a DK the budget is reported as unknown
# rather than guessed - an "unspent points" number that is quietly wrong is
# worse than one that admits it does not know.
DEATH_KNIGHT = 6


@dataclass(frozen=True)
class TalentBook:
    """The frozen client talent tables: spell id -> which talent, which rank.

    Loaded the same way Geometry loads zones.json - once, at import, from a
    file committed beside the code. `trees` is keyed by tab id (as a string,
    because it came from JSON); `by_spell` is the reverse index built here so
    the committed file does not have to carry it twice.
    """

    trees: dict[str, dict]
    by_spell: dict[int, tuple[dict, int]]

    @classmethod
    def load(cls, static_dir: str) -> "TalentBook":
        with open(os.path.join(static_dir, "talents.json")) as f:
            book = json.load(f)
        by_spell: dict[int, tuple[dict, int]] = {}
        for talent in book["talents"]:
            for index, spell in enumerate(talent["ranks"]):
                by_spell[spell] = (talent, index + 1)
        return cls(trees=book["trees"], by_spell=by_spell)

    def trees_for(self, class_id: int) -> list[tuple[str, dict]]:
        """That class's three trees, in the order the game draws them."""
        trees = [(tid, t) for tid, t in self.trees.items() if t["class"] == class_id]
        return sorted(trees, key=lambda pair: pair[1]["order"])


def talent_points_at(level: int, class_id: int) -> int | None:
    """How many points a character of this level and class should have spent."""
    if class_id == DEATH_KNIGHT:
        return None
    return max(0, level - FIRST_TALENT_LEVEL + 1)


def _quality_name(quality: int | None) -> str:
    if quality is None:
        return UNKNOWN_QUALITY
    return QUALITY_NAMES.get(quality, UNKNOWN_QUALITY)


def _slot_payload(slot_name: str, row: dict | None) -> dict:
    """One paper-doll slot, whether or not anything is in it."""
    cosmetic = slot_name in COSMETIC_SLOTS
    if row is None:
        return {"slot": slot_name, "cosmetic": cosmetic, "empty": True}
    # A LEFT JOIN miss on acore_world.item_template is a custom or removed
    # item: it is genuinely equipped, so it must not read as an empty slot.
    # Say which item instead of drawing a blank, the same way panel does.
    name = row["item_name"] if row["item_name"] is not None else f"Item #{row['entry']}"
    max_durability = row["max_durability"] or 0
    return {
        "slot": slot_name,
        "cosmetic": cosmetic,
        "empty": False,
        "entry": row["entry"],
        "name": name,
        "quality": row["quality"],
        "quality_name": _quality_name(row["quality"]),
        "item_level": row["item_level"],
        "required_level": row["required_level"],
        # Rings, cloaks, necks and trinkets have no durability at all, so a
        # stored 0 only means "broken" when the item HAS durability to lose.
        "broken": bool(max_durability) and not row["durability"],
    }


def _build_gear(slots: list[dict]) -> dict:
    """The read across one character's slots: what is worn, what is missing."""
    counts = [s for s in slots if not s["cosmetic"]]
    worn = [s for s in counts if not s["empty"]]
    levels = [s["item_level"] for s in worn if s["item_level"] is not None]
    return {
        "worn": len(worn),
        "slots": len(counts),
        "empty_slots": [s["slot"] for s in counts if s["empty"]],
        # Averaged over what is WORN, not over every slot. Counting an empty
        # slot as item level 0 would fold two different complaints - "his gear
        # is old" and "he has no helmet" - into one number that answers
        # neither. The empty slots are listed right beside it instead.
        "average_item_level": round(sum(levels) / len(levels)) if levels else None,
        "broken": [s["slot"] for s in worn if s["broken"]],
    }


def _build_spec(class_id: int, level: int, talent_rows: list[dict],
                book: TalentBook) -> dict:
    """A pile of learned spell ids -> the build a person can read."""
    trees = {tid: {"name": t["name"], "points": 0, "talents": []}
             for tid, t in book.trees_for(class_id)}
    order = [tid for tid, _ in book.trees_for(class_id)]
    unplaced, spent = [], 0
    for row in sorted(talent_rows, key=lambda r: r["spell"]):
        found = book.by_spell.get(row["spell"])
        if found is None:
            # A talent the frozen tables do not know: a custom talent, or a
            # client newer than the committed file. It is still a real point
            # the character has spent, so it is counted and named - dropping
            # it would silently understate the build.
            unplaced.append({"name": f"Spell #{row['spell']}", "rank": None,
                             "max_rank": None})
            spent += 1
            continue
        talent, rank = found
        tid = str(talent["tree"])
        spent += rank
        if tid not in trees:
            # Learned from another class's tree - impossible in play, so it
            # means the character or the tables are wrong. Surfaced, not hidden.
            unplaced.append({"name": talent["name"], "rank": rank,
                             "max_rank": len(talent["ranks"])})
            continue
        trees[tid]["points"] += rank
        trees[tid]["talents"].append({
            "name": talent["name"],
            "rank": rank,
            "max_rank": len(talent["ranks"]),
            "row": talent["row"],
            "col": talent["col"],
        })
    for tree in trees.values():
        # Tier then column: the order the talents sit in on the trainer's
        # own grid, so reading the list top to bottom reads down the tree.
        tree["talents"].sort(key=lambda t: (t["row"], t["col"]))
    ordered = [trees[tid] for tid in order]
    available = talent_points_at(level, class_id)
    deepest = max(ordered, key=lambda t: t["points"], default=None)
    return {
        "trees": ordered,
        # The shorthand every WoW player already reads, in tree order.
        "distribution": "/".join(str(t["points"]) for t in ordered),
        "primary": deepest["name"] if deepest and deepest["points"] else None,
        "spent": spent,
        "available": available,
        "unspent": None if available is None else max(0, available - spent),
        "unplaced": unplaced,
    }


def _member(name: str, char_row: dict | None, equipment_rows: list[dict],
            talent_rows: list[dict], book: TalentBook) -> dict:
    bond = bonds.FAMILY[name]
    if char_row is None:
        # No `characters` row at all - the character was deleted or never
        # made. Unlike the Family tab there is no freshness window here:
        # gear and talents are what is SAVED, so a logged-out character still
        # has both and still gets a full column.
        return {
            "name": name,
            "role": bond.role,
            "class": bond.char_class.title(),
            "present": False,
        }
    class_id, race = char_row["class"], char_row["race"]
    by_slot = {r["slot"]: r for r in equipment_rows}
    slots = [_slot_payload(slot_name, by_slot.get(index))
             for index, slot_name in enumerate(EQUIPPED_SLOTS)]
    # Dual spec: character_talent holds BOTH builds, told apart by specMask,
    # and the active one is the only one the character is actually playing.
    # Summing the two would report a level-25 warrior with 32 points spent.
    active = 1 << char_row["activeTalentGroup"]
    in_play = [r for r in talent_rows if r["specMask"] & active]
    return {
        "name": char_row["name"],
        "role": bond.role,
        "present": True,
        "level": char_row["level"],
        "class": _CLASS_NAMES.get(class_id, f"class {class_id}"),
        "race": _RACE_NAMES.get(race, f"race {race}"),
        "faction": "alliance" if race in _ALLIANCE_RACES
                   else "horde" if race in _HORDE_RACES else "neutral",
        "online": bool(char_row["online"]),
        "slots": slots,
        "gear": _build_gear(slots),
        "spec": _build_spec(class_id, char_row["level"], in_play, book),
    }


def build_armory(char_rows: list[dict], equipment_rows: list[dict],
                 talent_rows: list[dict], book: TalentBook) -> dict:
    """Every member's gear and build, side by side and in roster order.

    All three row lists arrive keyed by character name, unfiltered; splitting
    them per member is this module's job so the adapter stays three queries
    and no logic. A member with no rows still gets a column - a family view
    that quietly drops somebody is the exact failure this tab exists to stop.
    """
    chars = {r["name"]: r for r in char_rows}
    equipment: dict[str, list[dict]] = {}
    for row in equipment_rows:
        equipment.setdefault(row["name"], []).append(row)
    talents: dict[str, list[dict]] = {}
    for row in talent_rows:
        talents.setdefault(row["name"], []).append(row)
    members = [
        _member(name, chars.get(name), equipment.get(name, []),
                talents.get(name, []), book)
        for name in family.roster()
    ]
    return {
        "members": members,
        # The row order for the grid, sent rather than retyped in the page:
        # the columns are characters and the rows are slots, so both ends
        # must agree on what the slots are and what order they come in.
        "slots": [{"slot": name, "cosmetic": name in COSMETIC_SLOTS}
                  for name in EQUIPPED_SLOTS],
        "expected": len(members),
    }
