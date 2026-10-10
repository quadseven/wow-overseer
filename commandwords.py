"""A command the bridge sent a character, said in words.

The member page's activity log printed overseer_command.command as written:
"walk-to-spawn creature:10076 near:3", "guid:10136135 count:1", "co +flee",
"e Hitem:10298:0". Every one of those is a real fact with its object named
only by an id. This names the object: the creature, the item, the quest, the
dungeon, the map.

TWO STEPS, SO THE WORDS STAY PURE. `wanted(rows)` lists the ids a page of
commands needs names for, by table; the handler reads those names (NAMES_SQL,
one bounded read per table) and `say(row, names)` composes the sentence. An id
the world database does not hold says so with its number rather than vanish.
A command this module has no words for returns "" and the page shows the
command itself.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

import council
import places

# One read per table, ids bound as values; `{holes}` is sized by the caller.
NAMES_SQL = {
    "item": "SELECT entry AS id, name FROM acore_world.item_template "
    "WHERE entry IN ({holes})",
    "creature": "SELECT entry AS id, name FROM acore_world.creature_template "
    "WHERE entry IN ({holes})",
    "quest": "SELECT ID AS id, LogTitle AS name FROM acore_world.quest_template "
    "WHERE ID IN ({holes})",
    "object": "SELECT entry AS id, name FROM acore_world.gameobject_template "
    "WHERE entry IN ({holes})",
    # A carried item is named by its instance: sold, given or traded away, it
    # may be gone by the time the page asks.
    "guid": "SELECT ii.guid AS id, it.name FROM item_instance ii "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE ii.guid IN ({holes})",
}

_ARG = re.compile(r"\b(item|creature|quest|entry|guid|skill|mail|map|count):(\d+)")
_HITEM = re.compile(r"Hitem:(\d+)")
# Commands whose `item:` is an item entry; in mail commands it is an instance.
_ENTRY_ITEM_HEADS = ("walk-to-vendor", "hunt-spawn", "use-item-on")

# playerbots strategy sets: `co` in combat, `nc` out of it; "+" on, "-" off.
_STRATEGY_SETS = {"co": "In combat", "nc": "Out of combat"}
_STRATEGIES = {
    "flee": "fleeing when hurt",
    "follow": "following the leader",
    "grind": "grinding nearby mobs",
    "new rpg": "wandering on its own",
    "rpg": "wandering on its own",
}
# The roster jobs a `kind = 'job'` command sets, by keyword.
_JOBS = {
    "town run": "the town run job (sell, repair and restock)",
    "quest": "the questing job",
    "craft": "the crafting job",
}
_BATTLEGROUNDS = {"wsg": 489, "ab": 529, "av": 30, "eots": 566}


def _args(command: str) -> dict:
    return {k: int(v) for k, v in _ARG.findall(command)}


def wanted(rows) -> dict:
    """table -> the ids a page of command rows needs names for."""
    out: dict = {table: set() for table in NAMES_SQL}
    for row in rows or ():
        command = str(row.get("command") or "")
        head = command.split(" ", 1)[0]
        args = _args(command)
        if "creature" in args:
            out["creature"].add(args["creature"])
        if "quest" in args:
            out["quest"].add(args["quest"])
        if "entry" in args:
            out["item"].add(args["entry"])
        if "item" in args and head in _ENTRY_ITEM_HEADS:
            out["item"].add(args["item"])
        if "guid" in args:
            out["guid"].add(args["guid"])
        out["item"].update(int(x) for x in _HITEM.findall(command))
        if head == "use-gameobject" and command[len(head) :].strip().isdigit():
            out["object"].add(int(command[len(head) :]))
    return {table: sorted(ids) for table, ids in out.items() if ids}


def _name(names: dict, table: str, key: int, what: str) -> str:
    found = (names.get(table) or {}).get(int(key))
    if found:
        return found
    return "%s %d, which the world database does not hold" % (what, key)


@lru_cache(maxsize=1)
def _crafts() -> dict:
    """craft spell id -> what it makes, from the committed craftbook.json."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "craftbook.json")) as f:
            book = json.load(f)
    except (OSError, ValueError):
        return {}
    return {
        int(spell): str(entry[0])
        for spells in book.values()
        for spell, entry in spells.items()
    }


def _strategy(head: str, rest: str) -> str:
    sign, name = rest[:1], rest[1:].strip()
    if sign not in ("+", "-") or not name:
        return ""
    what = _STRATEGIES.get(name, "the '%s' strategy" % name)
    return "%s: %s %s" % (
        _STRATEGY_SETS[head],
        "start" if sign == "+" else "stop",
        what,
    )


def _and(names: list) -> str:
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _finder(rest: str) -> str:
    keyword, *seats = rest.split()
    place = council.keyword_place(keyword)
    if not seats:
        return "Run %s through the dungeon finder" % place
    group = "%s healing" % seats[0]
    if seats[1:]:
        group += ", with " + _and(seats[1:])
    return "Run %s through the dungeon finder: this member tanks, %s" % (place, group)


def _vendor(args: dict, names: dict) -> str:
    if "item" in args:
        return "Walk to a vendor that sells " + _name(
            names, "item", args["item"], "item"
        )
    return "Walk to the nearest vendor"


def _count(args: dict) -> int:
    return int(args.get("count") or 1)


def _carried(args: dict, names: dict, verb: str) -> str:
    item = (names.get("guid") or {}).get(args.get("guid", 0))
    count = _count(args)
    if item:
        return "%s %s%s" % (verb, "%d x " % count if count > 1 else "", item)
    gone = "a carried item that has since left its bags"
    return "%s %s%s" % (verb, "%d of " % count if count > 1 else "", gone)


def _with_arg(row: dict) -> str:
    return str(row.get("target_arg") or "").strip()


def _creature(args: dict, names: dict) -> str:
    return _name(names, "creature", args["creature"], "creature")


def _quest(args: dict, names: dict) -> str:
    return _name(names, "quest", args["quest"], "quest")


def _needs(key: str, verb: str, name):
    """A handler that says `verb` + the named object, or "" without `key`."""

    def handler(rest, row, args, names):
        return verb + name(args, names) if key in args else ""

    return handler


def _trainer(rest, row, args, names):
    if "skill" not in args:
        return ""
    import crafters

    trade = crafters.TRADES.get(args["skill"])
    if trade:
        return "Walk to a %s trainer" % trade
    return "Walk to the trainer for skill line %d" % args["skill"]


def _use_on(rest, row, args, names):
    if "item" not in args or "creature" not in args:
        return ""
    return "Use %s on %s" % (
        _name(names, "item", args["item"], "item"),
        _creature(args, names),
    )


def _hunt(rest, row, args, names):
    if "creature" not in args:
        return ""
    said = "Hunt " + _creature(args, names)
    if "item" in args:
        count = _count(args)
        said += " for %s%s" % (
            "%d x " % count if count > 1 else "",
            _name(names, "item", args["item"], "item"),
        )
    return said


def _send(rest, row, args, names):
    subject = rest.split("subject:", 1)[1] if "subject:" in rest else "an item"
    return "Mail %s to %s" % (subject, _with_arg(row) or "its recipient")


def _gameobject(rest, row, args, names):
    if not rest.isdigit():
        return ""
    return "Use " + _name(names, "object", int(rest), "object")


def _cross(rest, row, args, names):
    return "Cross to " + places.map_name(args["map"]) if "map" in args else ""


def _bg_queue(rest, row, args, names):
    battleground = _BATTLEGROUNDS.get(rest)
    return "Queue for " + places.map_name(battleground) if battleground else ""


def _fixed(text: str, needs_rest: bool = False):
    def handler(rest, row, args, names):
        if needs_rest and not rest:
            return ""
        return text.format(rest=rest)

    return handler


_BY_HEAD = {
    "walk-to-mailbox": _fixed("Walk to the nearest mailbox"),
    "take-money": _fixed("Take the money out of a mail"),
    "take-item": _fixed("Take an item out of a mail"),
    "delete": _needs("mail", "Delete an emptied mail", lambda a, n: ""),
    "recall": _fixed("Recall to its bind point"),
    "party-disband": _fixed("Leave the party"),
    "party-up": _fixed("Invite {rest} to a party", needs_rest=True),
    "rename-to": _fixed("Take the name {rest}", needs_rest=True),
    "finder-run": lambda rest, row, args, names: _finder(rest) if rest else "",
    "cross-to-map": _cross,
    "walk-to-vendor": lambda rest, row, args, names: _vendor(args, names),
    "walk-to-spawn": _needs("creature", "Walk to ", _creature),
    "party-walk": _needs("creature", "Walk the party to ", _creature),
    "use-gameobject": _gameobject,
    "take": _needs("quest", "Take the quest ", _quest),
    "turnin": _needs("quest", "Hand in ", _quest),
    "destroy": _needs("guid", "", lambda a, n: _carried(a, n, "Destroy")),
    "send": _send,
    "walk-to-trainer": _trainer,
    "use-item-on": _use_on,
    "hunt-spawn": _hunt,
    "bg-queue": _bg_queue,
}
# Verbs that mean something only for one command kind.
_BY_KIND_HEAD = {
    ("hearth", "use"): "Use the hearthstone",
    ("repair", "all"): "Repair everything it wears and carries",
    ("bot", "open"): "Open the containers it carries",
}


def _say_head(head: str, rest: str, row: dict, args: dict, names: dict) -> str:
    """The sentence for a command by its first word, or ""."""
    if head in _STRATEGY_SETS:
        return _strategy(head, rest)
    if head in _BY_HEAD:
        return _BY_HEAD[head](rest, row, args, names)
    return _BY_KIND_HEAD.get((str(row.get("kind") or ""), head), "")


# Commands known by their shape and kind rather than a verb. Each sayer gets
# (command, head, row, args, names) and returns "" when the shape is not its.
def _job(command, head, row, args, names):
    if command in _JOBS:
        return "Take " + _JOBS[command]
    if head.startswith("dungeon:") and head == command:
        return "Take the %s dungeon job" % council.keyword_place(head[8:])
    return ""


def _buy(command, head, row, args, names):
    if not head.startswith("entry:"):
        return ""
    count = _count(args)
    item = _name(names, "item", args["entry"], "item")
    return "Buy %s%s" % ("%d x " % count if count > 1 else "", item)


_CARRY_VERBS = {"sell": "Sell", "give": "Give away", "trade": "Trade"}


def _carry(command, head, row, args, names):
    if not head.startswith("guid:"):
        return ""
    kind = str(row.get("kind") or "")
    said = _carried(args, names, _CARRY_VERBS[kind])
    target = _with_arg(row)
    return said + (" to " + target if target and kind != "sell" else "")


def _share(command, head, row, args, names):
    if not head.startswith("quest:"):
        return ""
    target = _with_arg(row)
    quest = _name(names, "quest", args["quest"], "quest")
    return "Share %s%s" % (quest, " with " + target if target else "")


def _equip(command, head, row, args, names):
    found = _HITEM.search(command) if head == "e" else None
    return "Equip " + _name(names, "item", int(found.group(1)), "item") if found else ""


def _craft(command, head, row, args, names):
    made = _crafts().get(int(command)) if command.isdigit() else None
    return "Craft " + made if made else ""


_BY_KIND = {
    "job": _job,
    "buy": _buy,
    "sell": _carry,
    "give": _carry,
    "trade": _carry,
    "share": _share,
    "bot": _equip,
    "cast": _craft,
}


def _say_shape(command: str, row: dict, args: dict, names: dict) -> str:
    """The sentence for a command known by its shape rather than its verb."""
    sayer = _BY_KIND.get(str(row.get("kind") or ""))
    head = command.split(" ", 1)[0]
    return sayer(command, head, row, args, names) if sayer else ""


def say(row: dict, names: dict | None = None) -> str:
    """The command of an overseer_command row in words, or "" when this
    module has none for it."""
    command = str(row.get("command") or "").strip()
    if not command:
        return ""
    names = names or {}
    args = _args(command)
    head, _, rest = command.partition(" ")
    return _say_head(head, rest.strip(), row, args, names) or _say_shape(
        command, row, args, names
    )
