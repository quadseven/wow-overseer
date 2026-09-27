"""The tidy pass: carried gear that belongs on somebody, put on its way.

WHY THIS EXISTS. Measured on the dev realm on 2026-09-27, the family's level
38 warrior carried 38 stacks with 18 of 56 bag slots free and 9 of his worn
slots empty. The existing passes each answer one question well, and between
them they left three kinds of carried gear where they lay:

  * gear nobody can wear YET. `gear.claimant` asks who would wear a piece
    now, so a leather kilt at required level 44 in a level 38 warrior's bags
    answers NOBODY for every member, although the family rogue is the one it
    is made for and reaches 44 in nine levels. The bank policy then keeps it
    for the warrior, who will never wear leather while he wears plate.
  * relics for a class the holder is not: an idol in a warrior's bags. They
    have no slot in gear.py, so they answer UNJUDGEABLE and are kept.
  * rings, necklaces and trinkets. gear.py cannot judge them from item level
    (a suffix like "of the Bear" is the whole value of a green ring), so they
    are kept, and nothing ever tries one on.

WHAT THIS MODULE DECIDES, AND NOTHING ELSE.

    hand_ons   which member a piece is FOR, judged by class, armour type and
               level: the member whose native armour type it is (cloth for
               a priest, leather for a rogue, plate for a warrior from 40),
               who can wield that weapon or use that relic, and who reaches
               its required level soonest. Only pieces gear.claims gave to
               nobody move here; a piece somebody would wear NOW belongs to
               the gear pass, which already hands it on.
    try_ons    which carried rings and trinkets the holder should try on.
               The bot judges them with its own stat weights: mod-playerbots'
               EquipAction compares a ring or trinket against both worn ones
               and replaces one only when the new piece scores higher, so a
               try-on never makes a character worse. A necklace has no such
               comparison, so it is tried only into an empty neck slot.
    settle     what a finished tidy row actually did, from where the item is
               now. `delivered` means the row was handed over, not that the
               item moved, so every step is read back before it is reported.

PURE MODULE: no MySQL, no clock. The bridge reads, calls, writes.
"""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure

# gear.py's one importer is bag_pressure, the adapter between world rows and
# its judgement; this module reaches it through that adapter, and turns a row
# into a Holding only with gear's own `holdings_from_rows`.
gear = bag_pressure.gear

SOURCE_HANDON = "tidy:handon"
SOURCE_TRYON = "tidy:tryon"

# How far ahead a piece is held for a member. The cap is 60 and the families
# level together, so a piece a caster at 35 wears at 60 is still theirs.
FUTURE_LEVELS = 25

INVTYPE_NECK = 2
INVTYPE_FINGER = 11
INVTYPE_TRINKET = 12
INVTYPE_RELIC = 28
TRY_ON_TYPES = frozenset({INVTYPE_NECK, INVTYPE_FINGER, INVTYPE_TRINKET})
NECK_SLOT = 1

# item_template.subclass for a relic -> the one class that can equip it.
# AllowableClass says -1 or 32767 on every relic on this realm, so the class
# gate lives here, the same shape as gear._ARMOR_TRAINED_AT.
_RELIC_CLASS = {7: 2, 8: 11, 9: 7, 10: 6}  # libram, idol, totem, sigil
_ARMOR_TYPES = (gear.ARMOR_CLOTH, gear.ARMOR_LEATHER, gear.ARMOR_MAIL, gear.ARMOR_PLATE)
SOULBOUND_FLAG = 0x1

# The gear pass's own delivery judgement (verb from where the two stand, the
# receiver's bag room budgeted across the pass), re-exported so the bridge
# keeps reaching gear.py only through its adapters.
deliverable = gear.deliverable


@dataclass(frozen=True)
class Member:
    name: str
    class_id: int
    level: int


@dataclass(frozen=True)
class TryOn:
    holder: str
    guid: int
    entry: int
    name: str

    @property
    def command(self) -> str:
        # The link form the equip pass already writes (bag_pressure.equip_entry
        # reads it back); EquipAction parses only the entry out of it.
        return "e Hitem:%d:0" % int(self.entry)


def members_from_rows(worn_rows) -> dict:
    """name -> Member, from `_fetch_family_equipped` rows (one per worn item)."""
    out = {}
    for row in worn_rows:
        name = row.get("name")
        if not name or name in out:
            continue
        out[name] = Member(
            name=name,
            class_id=int(row.get("class_id") or 0),
            level=int(row.get("level") or 0),
        )
    return out


def _holding(row: dict):
    """The row as gear.py's Holding, or None when the row cannot say."""
    found = gear.holdings_from_rows([row])
    return found[0] if found else None


def refusal(row: dict, member: Member) -> str:
    """Why `member` can never wear this piece, at any level, or ""."""
    holding = _holding(row)
    if holding is None:
        return "the row does not describe the piece"
    if int(holding.item_class) not in (gear.ITEM_CLASS_WEAPON, gear.ITEM_CLASS_ARMOR):
        return "not gear"
    if not gear.usable_by_class(holding, member.class_id):
        return "class cannot equip it"
    if (
        int(holding.item_class) == gear.ITEM_CLASS_ARMOR
        and int(holding.inventory_type) == INVTYPE_RELIC
    ):
        wanted = _RELIC_CLASS.get(int(holding.item_subclass))
        if wanted is None or wanted != member.class_id:
            return "relic for another class"
        return ""
    # Judged at the level the piece asks for: a warrior at 38 is in mail, and
    # a plate chest at 49 is his all the same.
    later = gear.CharacterState(
        name=member.name,
        class_id=member.class_id,
        level=max(member.level, holding.required_level),
    )
    if not gear.wearable_armor(holding, later):
        return "not trained in that armour type"
    if not gear.wieldable_weapon(holding, later):
        return "cannot wield that weapon type"
    return ""


def native(row: dict, member: Member) -> bool:
    """Is this piece's armour type the heaviest the member wears at its level.

    A warrior CAN wear a leather kilt; a rogue is who it is made for. Pieces
    with no armour type (weapons, cloaks, rings) are native to anybody who
    can use them.
    """
    holding = _holding(row)
    if holding is None:
        return False
    subclass = int(holding.item_subclass)
    if int(holding.item_class) != gear.ITEM_CLASS_ARMOR or subclass not in _ARMOR_TYPES:
        return True
    if int(holding.inventory_type) == 16:  # INVTYPE_CLOAK: always cloth
        return True
    at = max(member.level, int(holding.required_level))
    return subclass == gear.heaviest_armor(member.class_id, at)


def future_owner(row: dict, members: dict, horizon: int = FUTURE_LEVELS) -> tuple:
    """(member name or "", reason) for the member this piece is for.

    Ranked by native armour type first, then by how soon they reach its
    required level. The holder keeps it when they rank level with the best
    on armour type, so a piece never moves between two members who suit it
    equally well.
    """
    required = int(row.get("required_level") or 0)
    ranked = []
    for member in members.values():
        if refusal(row, member):
            continue
        gap = max(0, required - member.level)
        if gap > horizon:
            continue
        ranked.append((not native(row, member), gap, member.name))
    if not ranked:
        return "", "nobody in the family can wear it within %d levels" % horizon
    ranked.sort()
    best_foreign, best_gap, best = ranked[0]
    holder = row.get("holder", "")
    for foreign, _gap, name in ranked:
        if name == holder and foreign == best_foreign:
            return holder, "the holder suits it as well as anybody"
    member = members[best]
    when = "now" if best_gap == 0 else "at level %d" % required
    kind = "its armour type" if not best_foreign else "usable"
    return best, "%s (%s, level %d) wears it %s - %s" % (
        best,
        gear._CLASS_NAMES.get(member.class_id, "class %d" % member.class_id),
        member.level,
        when,
        kind,
    )


def declined_equips(history, give_up: int = 3) -> frozenset:
    """(holder, entry) pairs the equip pass asked for `give_up` times.

    `history` is the equip pass's own rows (`_equip_history`). A piece the
    holder's bot was told to put on three times and still carries is one it
    will not wear - measured on wow-dev 2026-09-27, a warrior's bot declined
    a leather tunic three times, because its own weights prefer mail - so the
    holder's claim on it is not a reason to keep it from the member whose
    armour type it is.
    """
    counts: dict = {}
    for row in history:
        if row.get("status") in ("pending", "claimed"):
            continue
        entry = gear.equip_entry(row.get("command", ""))
        if not entry:
            continue
        key = (row.get("target_name", ""), entry)
        counts[key] = counts.get(key, 0) + 1
    return frozenset(k for k, n in counts.items() if n >= max(1, int(give_up)))


def hand_ons(
    gear_rows,
    members: dict,
    claims: dict,
    horizon: int = FUTURE_LEVELS,
    declined: frozenset = frozenset(),
) -> list:
    """gear.Grant per carried piece that belongs with another member.

    Only pieces gear.claims gave to NOBODY or could not judge (relics), and
    pieces the holder's bot has `declined` to put on: a piece somebody would
    wear now is the gear pass's to move. Soulbound
    pieces cannot move and rings, necks and trinkets are tried on, not
    handed on. Returned as gear.Grant so gear.deliverable picks the verb and
    budgets the receiver's bag room exactly as it does for the gear pass.
    """
    out = []
    for row in gear_rows:
        if not _may_hand_on(row, claims, declined):
            continue
        holder = row.get("holder", "")
        owner, reason = future_owner(row, members, horizon)
        if not owner or owner == holder:
            continue
        name = row.get("name") or "item %d" % int(row.get("entry") or 0)
        out.append(
            gear.Grant(
                holder=holder,
                taker=owner,
                entry=int(row.get("entry") or 0),
                name=name,
                guid=int(row["item_guid"]),
                reason=reason,
                said="%s is for %s" % (name, owner),
            )
        )
    return out


def _may_hand_on(row: dict, claims: dict, declined: frozenset) -> bool:
    """Is this carried row one the tidy pass may move at all."""
    guid = int(row.get("item_guid") or 0)
    if not guid:
        return False
    holder = row.get("holder", "")
    claim = claims.get(guid)
    if claim == holder and (holder, int(row.get("entry") or 0)) in declined:
        claim = gear.NOBODY
    if claim not in (gear.NOBODY, gear.UNJUDGEABLE):
        return False
    if int(row.get("instance_flags") or 0) & SOULBOUND_FLAG:
        return False
    return int(row.get("inventory_type") or 0) not in TRY_ON_TYPES


def try_ons(gear_rows, members: dict, worn: dict) -> list:
    """TryOn per carried ring, trinket or necklace the holder may put on.

    `worn` is name -> {slot: entry} of what each member wears now. A copy of
    something already worn is skipped (the bot would compare it against
    itself), and one row per entry per holder is enough.
    """
    out, seen = [], set()
    for row in gear_rows:
        invtype = int(row.get("inventory_type") or 0)
        if invtype not in TRY_ON_TYPES:
            continue
        holder = row.get("holder", "")
        member = members.get(holder)
        if member is None:
            continue
        entry = int(row.get("entry") or 0)
        if int(row.get("required_level") or 0) > member.level:
            continue
        if refusal(row, member):
            continue
        on = worn.get(holder, {})
        if entry in on.values():
            continue
        if invtype == INVTYPE_NECK and on.get(NECK_SLOT):
            continue
        if (holder, entry) in seen:
            continue
        seen.add((holder, entry))
        out.append(
            TryOn(
                holder=holder,
                guid=int(row.get("item_guid") or 0),
                entry=entry,
                name=row.get("name") or "item %d" % entry,
            )
        )
    return out


def guid_of(command: str) -> int:
    """The item_instance guid a hand-on row names, or 0.

    `guid:N` for a trade or give, `send item:N subject:...` for a letter.
    """
    for word in str(command or "").split():
        for prefix in ("guid:", "item:"):
            if word.startswith(prefix) and word[len(prefix) :].isdigit():
                return int(word[len(prefix) :])
    return 0


# What a finished tidy row did, read from where the item is now.
MOVED = "moved"
WORN = "worn"
KEPT = "kept"
REFUSED = "refused"
WAITING = "waiting"

_ANSWERED = frozenset({"delivered", "applied", "unchanged", "error"})


def settle(row: dict, place: dict | None) -> tuple:
    """(outcome, sentence) for one tidy row.

    `row` is the overseer_command row (source, target_name, target_arg,
    status, detail, command, guid, name). `place` is where that item_instance
    is now: {"owner": name, "worn": bool, "mail": bool}, or None when it no
    longer exists. WAITING means ask again next pass.
    """
    status = row.get("status") or ""
    if status not in _ANSWERED:
        return WAITING, ""
    holder = row.get("target_name", "")
    name = row.get("name") or "item"
    if status == "error":
        return REFUSED, "%s: %s was not moved - %s" % (
            holder,
            name,
            row.get("detail") or "refused",
        )
    if row.get("source") == SOURCE_HANDON:
        return _settle_hand_on(row, place, holder, name)
    return _settle_try_on(place, holder, name)


def _settle_hand_on(row: dict, place, holder: str, name: str) -> tuple:
    """A delivered hand-on: moved only once the receiver owns the item."""
    taker = row.get("target_arg", "")
    owner = place.get("owner") if place else None
    if owner == taker:
        mail = bool(place.get("mail"))
        return MOVED, "%s passed %s to %s (%s), confirmed in %s's %s" % (
            holder,
            name,
            taker,
            "by post" if mail else "in hand",
            taker,
            "mailbox" if mail else "bags",
        )
    if owner == holder:
        return WAITING, ""
    return REFUSED, "%s: %s did not reach %s" % (holder, name, taker)


def _settle_try_on(place, holder: str, name: str) -> tuple:
    """A delivered try-on: worn, or kept because the bot scored it lower."""
    if not place or place.get("owner") != holder:
        return REFUSED, "%s: %s is no longer carried" % (holder, name)
    if place.get("worn"):
        return WORN, "%s put on %s, confirmed worn" % (holder, name)
    return (
        KEPT,
        "%s tried on %s and kept what it wears (the bot scored it lower)"
        % (holder, name),
    )
