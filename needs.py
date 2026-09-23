"""What the five NEED, and what the family is doing about it (infra#2597).

WHY THIS EXISTS AS A MODULE AND NOT AS FOUR TERNARIES IN THE PAGE. The Family
view already answers "is my family alive". It has never answered the question
underneath it - "and is anything wrong with them" - and every fact that would
answer it was already being computed somewhere: wealth.py counts the bag slots
and the purse, armory.py reads the durability off every worn item,
materials.py knows which stack is in the wrong bags, and bonds.py knows who
has stopped answering whom.

What was missing is the JUDGEMENT that turns those into a reading: what counts
as "no room", when a repair is overdue, which of a character's four problems
is THE problem, and the sentence that says so. Every one of those is a
decision, and infra#2597 puts decisions in a module the stdlib suite can
import with no database and no browser. A page that decided for itself that
39% durability is red would be a second opinion about the family that could
disagree with this one, silently, while rendering a perfectly plausible bar.

WHY ITS OWN ENDPOINT AND NOT MORE OF /api/family. /api/family is the 5s poll
behind five live cards and it is deliberately cheap - its own docstring
explains that it exists so the tab does not make five /api/character calls.
Everything here is SAVED state: bags, durability, money, give attempts and
thoughts are written by the core's own save timer and by the bridge, and none
of them can change faster than that. So this rides the 30s cadence the quest
board already rides, for the same reason the quest board rides it.

WHY A FULL BAR ALWAYS MEANS THE NEED IS MET. Four bars in a column have to
agree about which end is good, or they are four different charts sharing a
grid: "bags 100%" would mean full and bad while "repair 100%" would mean
intact and fine, and a reader would have to learn each one separately. So
every bar below is drawn as HOW MUCH IS LEFT - room in the bags, durability on
the gear, coin in the purse, bag positions filled - and a short red bar always
means the same thing.

WHAT THIS DOES NOT DO. It never asks for anything and never writes anything.
The handovers it lists are the plan the bridge is already acting on, read a
second time rather than recomputed with different inputs; a view that could
change what the family does by being looked at is a view nobody can trust.

Ticket: infra#2597.
"""

from __future__ import annotations

import bonds
import family
import goals
import materials
import wealth
from armory import EQUIPPED_SLOTS

# --- how far back this view looks --------------------------------------
#
# Read by the adapter's SQL rather than typed into it, the same way
# questlog.IN_LOG is: a window is a decision about what counts as recent, and a
# 24 in a query nothing tests is a decision nobody can find.
#
# A DAY, matching the bridge's own GIVE_GIVE_UP_HOURS default. The live
# refusals behind mod-overseer#169 were seven identical errors spread over six
# hours, so an hour-wide window sees one or two of them and this view would
# report a family that had given up as one that was still trying.
HISTORY_HOURS = 24
# A backstop on a busy stream, not the window itself.
HISTORY_MAX = 500

# --- the four motives, in the order a person reads them -----------------
BAGS = "bags"
REPAIR = "repair"
COIN = "coin"
BAG_POSITIONS = "bag_positions"

# What a bar can be. Three states and not two: "about to be a problem" is the
# one worth showing before it becomes one, and it is the whole reason a number
# that is fine today is on screen at all.
FINE = "fine"
CAUTION = "caution"
WARN = "warn"

_STATE_ORDER = {WARN: 0, CAUTION: 1, FINE: 2}

# DURABILITY. The two numbers in the design handoff, and they are the same two
# the game itself uses: an item at 0 stops working entirely, and the yellow
# warning in the default UI is what a player already reads as "go and repair".
# Below 40% a set is about to start falling off; below 75% it is worth the
# trip while somebody is in a town anyway.
REPAIR_BROKEN_PCT = 40
REPAIR_WORN_PCT = 75

# BAG SPACE. Zero free is the state that freezes a character outright: with no
# room, `open loot` can never complete, so it preempts questing forever and the
# character stands still (infra#2813 - Grug held one position to within 0.1
# yard for eight and a half hours). Three is a loot or two away from that.
ROOM_TIGHT_SLOTS = 3

# COIN, in copper. Not a wealth target - the family holds 140 to 170 gold each
# (wealth.py's docstring has the measurement), so both bars below are full for
# everyone today and that is the CORRECT reading: coin is not this family's
# problem, and a view that only ever shows problems cannot say so.
#
# The floor is what a character needs to get out of trouble on their own: a
# full repair, and a bag to put the next thing in.
POOR_COPPER = 1 * wealth.COPPER_PER_GOLD
THIN_COPPER = 10 * wealth.COPPER_PER_GOLD

# WHAT COUNTS AS SAID OUT LOUD. `overseer_thought` holds the family's inner
# life as well as its speech - a reflection, a goal, a command it was given -
# and putting any of those in a quotation box would be the page inventing a
# line nobody spoke. These two sources are the ones the bridge writes AFTER
# handing the same text to relay.SpeakCommand, so they are the ones that
# actually reached party chat.
SPOKEN_SOURCES = ("council", "chat")

# name -> the professions `character_skills` actually gives them. The ids come
# from goals.SKILL_IDS, which professions.py and standing.py already read for
# the same reason: it is the one place these numbers were verified live.
_SKILL_NAMES = {number: name for name, number in goals.SKILL_IDS.items()}


def _bar(key: str, label: str, pct: int | None, value: str, state: str) -> dict:
    """One motive bar. `pct` is HOW MUCH IS LEFT; see the module docstring.

    A pct of None means the question does not apply to this character at all
    (nothing worn that can break), which is a different answer from zero and
    must not be drawn as an empty bar.
    """
    return {
        "key": key,
        "label": label,
        "pct": pct,
        "value": value,
        "state": state,
        # The label goes ink when it is the problem and muted otherwise, which
        # is a decision about what a person should be reading first rather
        # than a style. Said here so the page has nothing to work out.
        "problem": state != FINE,
    }


def coin_words(purse: dict) -> str:
    """A purse as the game writes it: "142g 6s 51c", trailing units dropped.

    Composed here rather than in the page because it is a SENTENCE about a
    number, and because three views formatting the same purse three ways is
    how "142g" and "142g 6s" come to sit next to each other claiming to be the
    same amount. Zero is "nothing", not "0c": a character with an empty purse
    has nothing, and saying so in words is what a reader is looking for.
    """
    if not purse["total"]:
        return "nothing"
    bits = []
    if purse["gold"]:
        bits.append("%dg" % purse["gold"])
    if purse["silver"]:
        bits.append("%ds" % purse["silver"])
    if purse["copper"]:
        bits.append("%dc" % purse["copper"])
    return " ".join(bits)


def _bags_bar(capacity: dict) -> dict:
    free, slots = capacity["free"], capacity["slots"]
    if not slots:
        # A DIVISION GUARD, and nothing more. Every character is born with the
        # sixteen-slot backpack and wealth.split_inventory builds it whether or
        # not a single row came back, so this is unreachable against real
        # containers - which is the point: a member with no inventory rows
        # reads as an EMPTY backpack, not as a character with no bags, and
        # certainly not as one whose bags are full.
        return _bar(BAGS, "bag space", None, "no containers on record", FINE)
    if not free:
        state = WARN
    elif free <= ROOM_TIGHT_SLOTS:
        state = CAUTION
    else:
        state = FINE
    return _bar(
        BAGS,
        "bag space",
        round(100 * free / slots),
        "%d free of %d" % (free, slots),
        state,
    )


def _repair_bar(pct: int | None) -> dict:
    if pct is None:
        # Rings, cloaks, necks and trinkets have no durability at all, so a
        # character wearing only those has nothing that can break - which is
        # not the same as gear at zero. Same distinction armory._slot_payload
        # already draws for `broken`.
        return _bar(REPAIR, "repair", None, "nothing that can break", FINE)
    if pct < REPAIR_BROKEN_PCT:
        state = WARN
    elif pct < REPAIR_WORN_PCT:
        state = CAUTION
    else:
        state = FINE
    return _bar(REPAIR, "repair", pct, "%d%% durability" % pct, state)


def _coin_bar(purse: dict) -> dict:
    total = purse["total"]
    if total < POOR_COPPER:
        state = WARN
    elif total < THIN_COPPER:
        state = CAUTION
    else:
        state = FINE
    return _bar(
        COIN,
        "coin",
        min(100, round(100 * total / THIN_COPPER)),
        coin_words(purse),
        state,
    )


def _positions_bar(capacity: dict) -> dict:
    """The bag POSITIONS, which is a different complaint from a full bag.

    wealth.build_capacity says it in one line: three empty bag slots on a
    character with nothing to put in them is a different problem from four
    full bags, and the two want different answers - find them a bag, versus go
    and sell something. An empty position on a character whose bags are
    already full is the actionable one, so that is the only WARN here.
    """
    empty = capacity["empty_bag_slots"]
    held = capacity["bag_slots"] - empty
    if empty and capacity.get("full"):
        state = WARN
    elif empty:
        state = CAUTION
    else:
        state = FINE
    return _bar(
        BAG_POSITIONS,
        "bag slots",
        round(100 * held / capacity["bag_slots"]),
        "%d of %d bags carried" % (held, capacity["bag_slots"]),
        state,
    )


def _worst_line(
    name: str, bars: list[dict], capacity: dict, purse: dict, repair_pct: int | None
) -> dict:
    """The one rust-coloured line under the bars, naming the worst thing.

    ONE line, and it names ONE thing. Four bars already say what is true; what
    a person cannot do at a glance is rank them, and a card that listed all
    four problems would be back to making them do it.
    """
    worst = min(
        bars,
        key=lambda b: (_STATE_ORDER[b["state"]], 999 if b["pct"] is None else b["pct"]),
    )
    if worst["state"] == FINE:
        return {"text": "nothing %s needs right now" % name, "state": FINE}
    if worst["key"] == BAGS:
        if worst["state"] == WARN:
            text = (
                "%s has no room left - %d of %d slots used. A character "
                "with no room cannot finish a loot, and stops."
                % (name, capacity["used"], capacity["slots"])
            )
        else:
            text = "%s has %d slots free of %d, which is a loot or two from none." % (
                name,
                capacity["free"],
                capacity["slots"],
            )
    elif worst["key"] == REPAIR:
        if worst["state"] == WARN:
            text = (
                "%s's gear is at %d%% durability. Things are about to "
                "start falling off." % (name, repair_pct)
            )
        else:
            text = (
                "%s's gear is at %d%% durability and worth repairing next "
                "time %s is in a town." % (name, repair_pct, name)
            )
    elif worst["key"] == COIN:
        if worst["state"] == WARN:
            text = "%s is carrying %s, which does not cover a repair bill." % (
                name,
                coin_words(purse),
            )
        else:
            text = "%s is carrying %s - thin for a repair and a bag both." % (
                name,
                coin_words(purse),
            )
    elif worst["state"] == WARN:
        text = (
            "%s has %d empty bag position(s) and no room in the bags "
            "%s is carrying. %s needs a bag, not a vendor."
            % (name, capacity["empty_bag_slots"], name, name)
        )
    else:
        text = "%s has %d empty bag position(s) - there is room for more bag." % (
            name,
            capacity["empty_bag_slots"],
        )
    return {"text": text, "state": worst["state"]}


def _repair_pct(rows: list[dict]) -> int | None:
    """One character's worn durability, as a percentage of what it could be.

    Summed over the whole set rather than averaged per item, because that is
    what a repair bill is: one item at 5% among fifteen at 100% is a cheap
    trip, and averaging would report the same number as fifteen items at 94%,
    which is not.

    Only items that HAVE durability count. A stored 0 on a ring means the ring
    cannot break, not that it is broken - the same rule armory follows.
    """
    total = worn = 0
    for row in rows:
        maximum = int(row.get("max_durability") or 0)
        if not maximum:
            continue
        total += maximum
        worn += min(maximum, int(row.get("durability") or 0))
    if not total:
        return None
    return round(100 * worn / total)


def _said(name: str, rows: list[dict]) -> dict:
    """The last thing this character actually said out loud, if anything.

    `rows` are newest first. An absent answer is a SENTENCE rather than a
    blank, because an empty quotation box on a card reads as a page that
    failed to load rather than as a character who has not spoken.
    """
    for row in rows:
        if row.get("character_name") != name:
            continue
        if (row.get("source") or "") not in SPOKEN_SOURCES:
            continue
        text = (row.get("text") or "").strip()
        if text:
            return {"text": text, "source": row["source"], "spoken": True}
    return {
        "text": "%s has not said anything out loud lately." % name,
        "source": "",
        "spoken": False,
    }


def held_skills(skill_rows: list[dict]) -> dict:
    """name -> {profession: value}, from raw `character_skills` rows.

    PROFESSIONS ONLY. `character_skills` also holds languages, Defence and
    every weapon skill, and handing those to code that reasons about
    profession slots is exactly how `trades` came to mean nothing in the
    bridge. Filtered here rather than in the query so the adapter stays a
    SELECT and this stays testable.
    """
    out: dict = {}
    for row in skill_rows:
        skill = _SKILL_NAMES.get(int(row.get("skill") or 0))
        if skill is None:
            continue
        out.setdefault(row["name"], {})[skill] = int(row.get("value") or 0)
    return out


def holdings(inventory_rows: list[dict]) -> list:
    """Every reagent stack in the family's bags, as materials.Holding.

    ONE ROW PER item_instance guid, matching what `materials.plan` expects and
    what `DoGive` can actually move. Equipped items are excluded and nothing
    else is: bridge.py's own _HOLDINGS_SQL draws the line in the same place,
    and a reagent is never worn, so this only ever excludes gear.
    """
    out = []
    for row in inventory_rows:
        material = row.get("item_name")
        if material not in materials.REAGENTS:
            continue
        if row["bag"] == 0 and row["slot"] < len(EQUIPPED_SLOTS):
            continue
        out.append(
            materials.Holding(
                holder=row["name"],
                material=material,
                count=int(row.get("count") or 1),
                guid=int(row["item_guid"]),
            )
        )
    return out


def attempts(give_rows: list[dict]) -> list:
    """Every give this family has tried lately, as materials.Attempt.

    `target_name` is the holder and `target_arg` the taker, which is the shape
    bridge.py's `_insert_give` writes and `_give_attempts` reads back. Named
    here rather than unpacked in the adapter so there is one answer to which
    column is which.
    """
    return [
        materials.Attempt(
            holder=row.get("target_name") or "",
            taker=row.get("target_arg") or "",
            status=row.get("status") or "",
            detail=row.get("detail") or "",
        )
        for row in give_rows
    ]


def _answering_headline(rows: tuple) -> str:
    """The one line over the pair rows.

    A refusal is the finding; failing that, the counter closest to becoming
    one; failing that, say plainly that nothing has started, because a blank
    line over an empty section reads as a failed read.
    """
    stopped = [r for r in rows if r.word == bonds.STOPPED]
    if stopped:
        return "%d of these pairs %s stopped answering" % (
            len(stopped),
            "has" if len(stopped) == 1 else "have",
        )
    counting = [r for r in rows if r.word == bonds.COUNTING]
    if counting:
        nearest = min(counting, key=lambda r: r.threshold - r.count)
        left = nearest.threshold - nearest.count
        return (
            "nobody has stopped answering anybody - %s to %s is the "
            "nearest, %d answer%s away"
            % (nearest.responder, nearest.caller, left, "" if left == 1 else "s")
        )
    return "nobody has answered anybody yet, so no counter has started"


# --- the payload is JSON, and a dataclass is not ------------------------
#
# `materials.board` and `bonds.answers` hand back dataclasses, which is the
# right shape for the modules and their suites and the wrong one for
# json.dumps. Converted HERE rather than by making those modules return dicts,
# because their computed fields - a row key, a percentage capped at 100 - are
# judgement too and belong beside the rules that produce them.


def _move_row(move) -> dict:
    return {
        "key": move.key,
        "title": move.title,
        "refusal_line": move.refusal_line,
        "holder": move.holder,
        "taker": move.taker,
        "material": move.material,
        "skill": move.skill,
        "count": move.count,
        "said": move.said,
        "word": move.word,
        "blocked": move.blocked,
        "refusals": move.refusals,
        "refusal": move.refusal,
    }


def _answer_row(row) -> dict:
    return {
        "key": row.key,
        "pair": row.pair,
        "progress": row.progress,
        # The word again, lower case, because it is what the page hangs a
        # class on and a page that lower-cased it for itself would be deciding
        # what the states ARE - which is this module's decision, and one it
        # already made when it named them.
        "state": row.word.lower(),
        "responder": row.responder,
        "caller": row.caller,
        "will_answer": row.will_answer,
        "reason": row.reason,
        "word": row.word,
        "rule": row.rule,
        "counted": row.counted,
        "count": row.count,
        "threshold": row.threshold,
        "pct": row.pct,
        "note": row.note,
    }


def _moving(board: dict) -> dict:
    """`materials.board`, with its rows turned into something json can hold."""
    return {
        "rows": [_move_row(r) for r in board["rows"]],
        "notes": list(board["notes"]),
        "give_up_after": board["give_up_after"],
        "rule": board["rule"],
        "headline": board["headline"],
    }


def _member(
    name: str,
    char_row: dict | None,
    inventory_rows: list[dict],
    equipment_rows: list[dict],
    thought_rows: list[dict],
    history: list,
) -> dict:
    """One card's worth of need.

    A member with no `characters` row still gets an entry, for the same reason
    family.build_family renders an absent member rather than dropping them: a
    card that vanishes is how somebody stops being noticed, which is the whole
    complaint the Family view answers.
    """
    # bonds.bond_of rather than bonds.FAMILY[name]: FAMILY is the driven family
    # only, and bond_of knows every family bonds describes. A character none
    # of them claims has no persona, no role and no bond note, and note_for
    # already answers "" for them.
    bond = bonds.bond_of(name)
    role = bond.role if bond else ""
    note = bonds.note_for(name, history=history)
    if char_row is None:
        return {
            "name": name,
            "role": role,
            "present": False,
            "needs": [],
            "worst": {
                "text": "%s has no saved character row, so there is nothing "
                "to read off %s's bags." % (name, name),
                "state": FINE,
            },
            "said": _said(name, thought_rows),
            "bond": note,
        }
    # No icons: this view draws no item pictures, only counts. split_inventory
    # takes the map so it can hand one to every item payload, and passing an
    # empty one costs the icon field it does not read - which is honest rather
    # than clever, and keeps the slot arithmetic in the one module that owns
    # where the backpack starts.
    split = wealth.split_inventory(inventory_rows, {})
    capacity = wealth.build_capacity(split["containers"])
    purse = wealth.coins(char_row.get("money"))
    repair = _repair_pct(equipment_rows)
    bars = [
        _bags_bar(capacity),
        _repair_bar(repair),
        _coin_bar(purse),
        _positions_bar(capacity),
    ]
    return {
        "name": name,
        "role": role,
        "present": True,
        "needs": bars,
        "worst": _worst_line(name, bars, capacity, purse, repair),
        "said": _said(name, thought_rows),
        "bond": note,
    }


def build_needs(
    char_rows: list[dict],
    inventory_rows: list[dict],
    equipment_rows: list[dict],
    skill_rows: list[dict],
    give_rows: list[dict],
    thought_rows: list[dict],
    roster: list[str] | None = None,
) -> dict:
    """Everything under the five cards, in one payload.

    Three sections that are one story: what each of them needs, what the
    family is trying to hand to whom about it, and who will still answer whom
    when it is asked. They ride one endpoint rather than three because they
    are read together and because a page that could show the handovers while
    the needs failed would be showing a plan with no problem attached to it.

    Every row list arrives keyed by character name and unfiltered; splitting
    them per member is this module's job, so the adapter stays a handful of
    SELECTs and no logic.

    `roster` is which family, resolved by the adapter from the roster table;
    None keeps the family bonds holds. The give rows are not read per family
    in SQL, so they are narrowed here to attempts this family's members made:
    otherwise one family's refused handovers would be listed on the other's
    tab. The pair rules are bonds', and bonds knows one family, so a family
    it does not know gets no pair rows rather than the other family's.
    """
    roster = list(roster) if roster else family.roster()
    ours = set(roster)
    give_rows = [r for r in give_rows if (r.get("target_name") or "") in ours]
    chars = {r["name"]: r for r in char_rows}
    inventory: dict[str, list[dict]] = {}
    for row in inventory_rows:
        inventory.setdefault(row["name"], []).append(row)
    equipment: dict[str, list[dict]] = {}
    for row in equipment_rows:
        equipment.setdefault(row["name"], []).append(row)

    # The bonds count HELPING and nothing else, so the reflection rows are
    # sieved out of the same read that feeds the quotation boxes. One query,
    # two uses, and no chance of the two disagreeing about what was recent.
    history = bonds.history_from_thoughts(
        [r for r in reversed(thought_rows) if (r.get("source") or "") == "reflection"]
    )
    members = [
        _member(
            name,
            chars.get(name),
            inventory.get(name, []),
            equipment.get(name, []),
            thought_rows,
            history,
        )
        for name in roster
    ]
    # One family's rules, the family on screen: a roster is one family, and
    # its bonds are read off whichever family its members belong to.
    bonded = bool(roster) and all(bonds.bond_of(n) is not None for n in roster)
    kin = roster[0] if bonded else None
    answering = bonds.answers(history, kin) if bonded else ()
    board = materials.board(
        holdings(inventory_rows),
        attempts=attempts(give_rows),
        held=held_skills(skill_rows),
    )
    return {
        "members": members,
        "expected": len(members),
        "moving": _moving(board),
        "answering": {
            "rows": [_answer_row(r) for r in answering],
            "rule": bonds.answering_rule(kin) if bonded else "",
            "headline": _answering_headline(answering)
            if bonded
            else "no family rules are written for this family yet, so nobody "
            "is counting who answers whom",
        },
    }
