"""The journey of every epic item copy: where it dropped, who got it and how,
what the loot council decided, every hand-over, whether it was worn, and how
it ended.

PURE MODULE: rows in, journeys out. apiv2/journeys.py reads the realm.

ONE JOURNEY PER COPY. The module keys an item's loot, hand-over, equip and
tidy rows by its `item_guid`, so three copies of one sword are three
journeys. A vendor sale carries no guid (the module writes `vendor_sale`
rows per character, entry and hour), so a sale joins the copy of that entry
its seller held when it sold, the one it got most recently, and each sale
joins at most as many copies as it counts. A sale by somebody who never held
a copy joins nothing: it was some other copy the record does not follow.

THE ORDER INSIDE ONE SECOND. Rows of one flush share a second (lootstory
explains why), so ties go in the order an item moves: got, handed on, worn,
sold.

WHAT THE RECORD DOES NOT HOLD. The module writes no event for a disenchant
or a destroy, so a copy that ended that way reads as last seen in its
holder's bags. The ending says "as far as the record shows" for that reason.

FLAGS ARE FOR A HUMAN LOOK, not verdicts. One plain line each: an epic sold
to a vendor while a guild member could have used it, a roll won by a member
who cannot use it, and a council pick that went to somebody else. Whether a
member can use an item is read off its template and the member's class and
level (`can_use`); a member whose class is not known is never flagged.
"""

from __future__ import annotations

import re

import guildbank
import lootcouncil
import lootstory
import weaponskill

EPIC = 4

LOOT_KINDS = ("item_loot", "loot_won")
HANDED_KINDS = ("item_given", "tidy")
EQUIP = "item_equip"
SALE = "vendor_sale"
# Every kind a journey reads, in the order an item moves.
ORDER = {"item_loot": 0, "loot_won": 0, "item_given": 1, "tidy": 1, EQUIP: 2, SALE: 3}
EVENT_KINDS = LOOT_KINDS + HANDED_KINDS + (EQUIP,)

# How many journeys a read answers with.
LIMIT = 150

BASIS = (
    "Every epic item copy the families' guilds got, from the event record the "
    "module keeps for a fortnight, newest first. A vendor sale is recorded "
    "without the copy's id, so it joins the copy its seller held. The record "
    "has no disenchant or destroy event, so such a copy reads as last seen in bags."
)
EMPTY = "No epic item has been looted, won or handed over in the record."

ITEM_CLASS_ARMOR = 4
ARMOR_CLOTH, ARMOR_LEATHER, ARMOR_MAIL, ARMOR_PLATE = 1, 2, 3, 4
ARMOR_SHIELD = 6
# Relic subclasses (libram, idol, totem, sigil) -> the one class that holds it.
RELIC_CLASS = {7: 2, 8: 11, 9: 7, 10: 6}
SHIELD_CLASSES = frozenset({1, 2, 7})
WAND = 19
WAND_CLASSES = frozenset({5, 8, 9})
# Weapon subclasses anybody may hold: miscellaneous, fishing poles.
ANY_WEAPON = frozenset({14, 20})
# Slots any class wears: neck, finger, trinket, back, shirt, tabard, held in off hand.
ANY_SLOT = frozenset({2, 4, 11, 12, 16, 19, 23})
# A class's own armor kind: (kind before 40, kind from 40).
OWN_ARMOR = {
    1: (ARMOR_MAIL, ARMOR_PLATE),  # warrior
    2: (ARMOR_MAIL, ARMOR_PLATE),  # paladin
    6: (ARMOR_PLATE, ARMOR_PLATE),  # death knight
    3: (ARMOR_LEATHER, ARMOR_MAIL),  # hunter
    7: (ARMOR_LEATHER, ARMOR_MAIL),  # shaman
    4: (ARMOR_LEATHER, ARMOR_LEATHER),  # rogue
    11: (ARMOR_LEATHER, ARMOR_LEATHER),  # druid
    5: (ARMOR_CLOTH, ARMOR_CLOTH),  # priest
    8: (ARMOR_CLOTH, ARMOR_CLOTH),  # mage
    9: (ARMOR_CLOTH, ARMOR_CLOTH),  # warlock
}
HEAVIER_ARMOR_LEVEL = 40

_SOLD = re.compile(r"^\s*(\d+)\s+for\s+(\d+)\s+copper")


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def names_line(names, most: int = 3) -> str:
    """ "A", "A and B", "A, B and C", "A, B and 2 more"."""
    names = list(dict.fromkeys(n for n in names if n))
    if len(names) <= 1:
        return "".join(names)
    if len(names) <= most:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[: most - 1]) + " and %d more" % (len(names) - most + 1)


def _armor_ok(sub: int, inv: int, cls: int, level: int, own_kind: bool) -> bool | None:
    if inv in ANY_SLOT or sub == 0:
        return True
    if sub == ARMOR_SHIELD:
        return cls in SHIELD_CLASSES
    if sub in RELIC_CLASS:
        return RELIC_CLASS[sub] == cls
    own = OWN_ARMOR.get(cls)
    if own is None:
        return None
    best = own[1 if level >= HEAVIER_ARMOR_LEVEL else 0]
    return sub == best if own_kind else sub <= best


def _weapon_ok(sub: int, cls: int) -> bool | None:
    if sub in ANY_WEAPON:
        return True
    if sub == WAND:
        return cls in WAND_CLASSES
    skills = weaponskill.CLASS_WEAPONS.get(cls)
    return None if skills is None else sub in skills


def can_use(item: dict, member: dict, own_kind: bool = False) -> bool | None:
    """Can this member use this item: armor no heavier than its class wears
    at its level (with `own_kind`, exactly the kind it wears: a warrior can
    put on mail, but mail is not a warrior's piece from 40), a weapon its
    class can learn, the class mask and the required level. None when the
    item's template or the member's class is not known."""
    cls, level = _int((member or {}).get("class")), _int((member or {}).get("level"))
    if not item or not cls or item.get("class") is None:
        return None
    mask = _int(item.get("allowable_class"), -1)
    if mask > 0 and not mask & (1 << (cls - 1)):
        return False
    if level and _int(item.get("required_level")) > level:
        return False
    kind, sub = _int(item.get("class")), _int(item.get("subclass"))
    if kind == ITEM_CLASS_ARMOR:
        return _armor_ok(sub, _int(item.get("inventory_type")), cls, level, own_kind)
    if kind == weaponskill.ITEM_CLASS_WEAPON:
        return _weapon_ok(sub, cls)
    return None


def _sold(detail: str) -> tuple[int, int]:
    """(count, copper) from a vendor_sale detail, "1 for 44580 copper"."""
    m = _SOLD.match(detail or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _outside(name: str, families: dict, member_of: dict) -> str:
    """The words after a hand-over's receiver when it left the family."""
    if any(name in names for names in families.values()):
        return ""
    if name in member_of:
        return ", a guild member outside the family"
    return ", outside the family guilds"


def _won_step(rows: list, zones: dict, council: dict | None) -> dict:
    row = next((r for r in rows if r["kind"] == "item_loot"), rows[0])
    who, via = row.get("character_name") or "somebody", row.get("via") or ""
    source = row.get("source") or ""
    where = lootstory.place(row, zones)
    if via in (lootstory.VIA_NEED, lootstory.VIA_GREED):
        how, text = via, "%s won it on a %s roll" % (who, via)
    elif via == lootstory.VIA_COUNCIL or (council and council["kind"] == "master"):
        how, text = "master", "%s was given it by master loot" % who
    else:
        how, text = "loot", "%s looted it" % who
    if source:
        text += " from " + source
    if where:
        text += " in " + where
    return {
        "at": _int(row.get("at")),
        "kind": "won",
        "how": how,
        "who": who,
        "text": text + ".",
    }


def _handed_step(row: dict, families: dict, member_of: dict) -> dict:
    who, to = (
        row.get("character_name") or "somebody",
        row.get("counterpart") or "somebody",
    )
    via = row.get("via") or ""
    if row["kind"] == "tidy":
        verb = "passed it to %s in a family tidy" % to
    elif via == lootstory.VIA_TRADE:
        verb = "traded it to " + to
    elif via == lootstory.VIA_MAIL:
        verb = "mailed it to " + to
    elif via == lootstory.VIA_GIVE:
        verb = "gave it to %s by overseer command" % to
    else:
        verb = "handed it to " + to
    text = "%s %s%s." % (who, verb, _outside(to, families, member_of))
    return {
        "at": _int(row.get("at")),
        "kind": "handed",
        "how": via,
        "who": who,
        "to": to,
        "text": text,
    }


def _equip_step(row: dict) -> dict:
    who = row.get("character_name") or "somebody"
    state = row.get("prior_state") or ""
    if state == "item" and row.get("prior_name"):
        over = " over " + row["prior_name"]
    elif state == "empty":
        over = " into an empty slot"
    else:
        over = ""
    return {"at": _int(row.get("at")), "kind": "equipped", "who": who,
            "replaced": row.get("prior_name") or "", "text": "%s equipped it%s." % (who, over)}  # fmt: skip


def _council(row: dict | None) -> dict | None:
    if not row:
        return None
    candidates = [
        {"name": c.name, "family": c.family, "wearable": c.wearable, "comparison": c.comparison,
         "score": c.score, "upgrade_percent": c.upgrade_percent, "why": c.why}
        for c in lootcouncil.candidates_from_json(row.get("candidates"))
    ]  # fmt: skip
    return {
        "kind": str(row.get("kind") or ""),
        "decided_by": str(row.get("decided_by") or ""),
        "heuristic": str(row.get("heuristic") or ""),
        "heuristic_why": str(row.get("heuristic_why") or ""),
        "recipient": str(row.get("recipient") or ""),
        "given_to": str(row.get("given_to") or ""),
        "reason": str(row.get("reason") or ""),
        "status": str(row.get("status") or ""),
        "outcome": str(row.get("outcome") or ""),
        "candidates": candidates,
    }


def _council_step(c: dict, at: int) -> dict:
    pick = c["recipient"] or "nobody"
    text = "The loot council picked %s" % pick
    if c["decided_by"]:
        text += " (decided by %s)" % c["decided_by"]
    text += ": %s." % c["heuristic_why"] if c["heuristic_why"] else "."
    return {"at": at, "kind": "council", "who": c["recipient"], "text": text}


def _holder(steps: list) -> str:
    holder = ""
    for s in steps:
        if s["kind"] == "handed":
            holder = s.get("to") or s["who"]
        elif s["kind"] != "council":
            holder = s["who"]
    return holder


def _journey(guid: int, rows: list, ctx: dict) -> dict:
    rows.sort(
        key=lambda r: (_int(r.get("at")), ORDER.get(r["kind"], 9), _int(r.get("id")))
    )
    named = next((r for r in rows if r.get("subject_quality")), rows[0])
    council = _council(ctx["council"].get(guid))
    steps: list = []
    got = [r for r in rows if r["kind"] in LOOT_KINDS]
    if got:
        steps.append(_won_step(got, ctx["zones"], council))
    if council:
        steps.append(
            _council_step(council, steps[0]["at"] if steps else _int(rows[0].get("at")))
        )
    for row in rows:
        kind = row["kind"]
        if kind == "tidy":
            if not str(row.get("detail") or "").startswith("moved"):
                continue
            last = next((s for s in reversed(steps) if s["kind"] == "handed"), None)
            if (
                last
                and last["who"] == row.get("character_name")
                and last["to"] == row.get("counterpart")
            ):
                continue  # the tidy pass confirming a trade already told
        if kind in HANDED_KINDS:
            steps.append(_handed_step(row, ctx["families"], ctx["member_of"]))
        elif kind == EQUIP:
            if (
                steps
                and steps[-1]["kind"] == "equipped"
                and steps[-1]["who"] == row.get("character_name")
            ):
                continue  # one row an hour while worn: it went on once
            steps.append(_equip_step(row))
    return {
        "item_guid": guid,
        "entry": _int(named.get("subject_id")),
        "name": named.get("subject_name") or "",
        "quality": _int(named.get("subject_quality")),
        "council": council,
        "steps": steps,
    }


def _attach_sales(journeys: list, sales: list) -> None:
    """Each sale joins the copies of its entry its seller held then, the most
    recently got first, at most as many as it counts."""
    for row in sorted(sales, key=lambda r: (_int(r.get("at")), _int(r.get("id")))):
        count, copper = _sold(row.get("detail"))
        if not count:
            continue
        at, seller = _int(row.get("at")), row.get("character_name")
        held = [
            j for j in journeys
            if j["entry"] == _int(row.get("subject_id")) and j["steps"]
            and j["steps"][-1]["kind"] != "sold" and j["steps"][-1]["at"] <= at
            and _holder(j["steps"]) == seller
        ]  # fmt: skip
        held.sort(key=lambda j: -j["steps"][-1]["at"])
        each = copper // count
        for j in held[:count]:
            j["steps"].append({
                "at": at, "kind": "sold", "who": seller, "copper": each,
                "text": "%s sold it to a vendor for %s." % (seller, guildbank.gold(each)),
            })  # fmt: skip


def _ending(steps: list) -> dict:
    last, holder = steps[-1], _holder(steps)
    if last["kind"] == "sold":
        return {"state": "sold", "who": holder, "copper": last["copper"],
                "text": "Sold to a vendor by %s for %s." % (holder, guildbank.gold(last["copper"]))}  # fmt: skip
    if last["kind"] == "equipped":
        return {
            "state": "worn",
            "who": holder,
            "text": "Worn by %s, as far as the record shows." % holder,
        }
    return {"state": "in_bags", "who": holder,
            "text": "In %s's bags, as far as the record shows." % holder}  # fmt: skip


def _users(item: dict, members: list, guild: str, skip: str, family: set) -> list:
    """The guild's members for whom the item is their own kind of piece,
    the family first, then the highest level."""
    fit = [
        m for m in members
        if m["name"] != skip and (not guild or m.get("guild") == guild)
        and can_use(item, m, own_kind=True)
    ]  # fmt: skip
    fit.sort(key=lambda m: (m["name"] not in family, -_int(m.get("level")), m["name"]))
    return [m["name"] for m in fit]


def _flags(j: dict, item: dict, members: list, member_of: dict, family: set) -> list:
    flags = []
    won = next((s for s in j["steps"] if s["kind"] == "won"), None)
    if won and won["how"] in ("greed", "need"):
        winner = member_of.get(won["who"])
        if winner and can_use(item, winner) is False:
            line = "%s won it on %s but cannot use it" % (won["who"], won["how"])
            could = _users(item, members, winner.get("guild"), won["who"], family)
            flags.append(
                line + ("; %s could have." % names_line(could) if could else ".")
            )
    c = j["council"]
    if c and c["recipient"] and c["given_to"] and c["recipient"] != c["given_to"]:
        flags.append(
            "The loot council picked %s, but %s got it."
            % (c["recipient"], c["given_to"])
        )
    end = j["ending"]
    if end["state"] == "sold":
        seller = member_of.get(end["who"]) or {}
        who, price = end["who"], guildbank.gold(end["copper"])
        others = _users(item, members, seller.get("guild"), who, family)
        if seller and can_use(item, seller, own_kind=True):
            line = (
                "%s sold it to a vendor for %s though it was %s's own kind of piece"
                % (who, price, who)
            )
            flags.append(
                line
                + (
                    ", and %s could have used it too." % names_line(others)
                    if others
                    else "."
                )
            )
        elif others:
            flags.append(
                "%s sold it to a vendor for %s while %s could have used it."
                % (who, price, names_line(others))
            )
    return flags


def build(
    rows: list,
    sales: list = (),
    council: list = (),
    members: list = (),
    items: dict | None = None,
    zones: dict | None = None,
    families: dict | None = None,
) -> list:
    """Every epic copy's journey, newest first.

    `rows` are overseer_event rows of EVENT_KINDS with `at` in Unix seconds;
    `sales` are vendor_sale rows; `council` overseer_loot_council rows;
    `members` the family guilds' members as {name, class, level, guild};
    `items` entry -> item_template row; `zones` area id -> name;
    `families` family -> member names.
    """
    items, families = items or {}, families or {}
    member_of = {m["name"]: m for m in members}
    by_guid: dict = {}
    for r in rows:
        guid = _int(r.get("item_guid"))
        if guid and r.get("kind") in EVENT_KINDS:
            by_guid.setdefault(guid, []).append(r)
    epic = {
        g: rs
        for g, rs in by_guid.items()
        if any(_int(r.get("subject_quality")) >= EPIC for r in rs)
    }
    ctx = {
        "zones": zones or {},
        "families": families,
        "member_of": member_of,
        "council": {
            _int(c.get("item_guid")): c for c in council if _int(c.get("item_guid"))
        },
    }
    journeys = [_journey(g, rs, ctx) for g, rs in epic.items()]
    journeys = [j for j in journeys if j["steps"]]
    _attach_sales(journeys, list(sales))
    for j in journeys:
        j["ending"] = _ending(j["steps"])
        kin = {n for names in families.values() for n in names}
        j["flags"] = _flags(
            j, items.get(j["entry"]) or {}, list(members), member_of, kin
        )
        who = []
        for s in j["steps"]:
            who += [s["who"], s.get("to") or ""]
        j["who"] = list(dict.fromkeys(n for n in who if n))
        j["guilds"] = sorted(
            {
                member_of[n]["guild"]
                for n in j["who"]
                if n in member_of and member_of[n].get("guild")
            }
        )
        j["since"], j["at"] = j["steps"][0]["at"], max(s["at"] for s in j["steps"])
    journeys.sort(key=lambda j: (-j["at"], -j["item_guid"]))
    return journeys


def pick(journeys: list, guild: str = "", name: str = "") -> list:
    """The journeys that touch this guild and this character (any case)."""
    g, n = (guild or "").casefold(), (name or "").casefold()
    return [
        j for j in journeys
        if (not g or g in (x.casefold() for x in j["guilds"]))
        and (not n or n in (x.casefold() for x in j["who"]))
    ]  # fmt: skip
