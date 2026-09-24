"""Where a classic raid guild keeps what it is not using today (#320).

WHAT WAS ASKED FOR. Both guilds should use their banks the way a raid guild
does. Tradable rare and epic gear nobody wears now, but a family member will
wear once it levels into it, goes to the guild bank. So do the raid's consumables
and reagents (for Molten Core: fire resistance gear and the materials for
Greater Fire Protection Potions) and the corps' crafting materials, each in
its own tab. A family member keeps its own second set in its personal bank
instead of selling it: fire resistance for Molten Core, or the gear for a
role its class can also fill (a tank set, a healing set, a damage set).

WHAT THE REALM SAID (dev, read-only, 2026-09-24). The Alliance guild bank
held 16 stacks in tab 0, all materials and no rare gear. The Horde guild had
no tab. Personal banks were almost unused (Bork 11 items, Og 5, the other
eight 0 to 2). Nothing kept a fire resistance piece, an off-spec set or a
rare BoE from a sale.

PVP IS A SOURCE, NOT A STAT. The realm is PvE, and resilience does not exist
in classic, so an item counts as PvP only when its source says so: a
required honor rank (the Knight-Captain's and Legionnaire's sets), a
battleground faction's reputation, or a vendor that sells it for honor or
arena points. Everything else is judged as PvE gear.

THE ORDER OF THE RULES IS THE ORDER THEY OVERRIDE EACH OTHER.

  1. A piece somebody in the family would wear now belongs to the gear
     passes (equip, hand-off). This module says nothing about it.
  2. The holder's own second set: fire resistance it can wear, PvP gear it
     can wear, and gear for a role its class can fill that is not its role
     today. Only the best piece per set and slot is kept, so a set is a set
     and not a hoard. It goes to the PERSONAL bank.
  3. Raid supplies for the guild's "Raid Supplies" tab: fire resistance gear
     the holder cannot wear, raid consumables past the holder's own night,
     and reagents for a raid craft the holder does not work.
  4. Tradable rare and epic gear nobody in the family wears now, which another
     family member will wear at its required level, for the "Gear for Later"
     tab.

NATURAL THINGS ONLY (the operator's rule). The guild's factory-made members
were granted their levels, gear and skills, so nothing here is kept for
them or valued by them: every wearer this policy counts is a family member.
  5. Everything else is the keeper rule's (bank.storage_reason): the
     "Materials" tab or the personal bank, as before.

PURE MODULE apart from `read`, which runs three SELECTs on a cursor it is
handed, so the bridge and the site read the same facts and reach the same
answer. Every judgement is `place`, over plain rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import disposition
import goals
import guildbank
import raidsupply
import statweights

GUILD = "guild"
PERSONAL = "personal"

MATERIALS_TAB, GEAR_TAB, RAID_TAB = 0, 1, 2

RARE = 3

WEAPON, ARMOR, CONSUMABLE = 2, 4, 0

# What each set is called, which is also the word the page shows.
FIRE_SET = "fire resistance set"
PVP_SET = "PvP set"
ROLE_SET = {
    statweights.TANK: "tank set",
    statweights.HEALER: "healing set",
    statweights.MELEE: "damage set",
    statweights.RANGED: "damage set",
    statweights.CASTER: "damage set",
}

# THE PARTY ROLE, IN STAT WEIGHTS' TERMS. raidlineup packs one family as one
# tank, one healer and damage for the rest (bag_pressure.family_characters);
# statweights prices a piece for a role. Damage is any of the three damage
# roles, so a Balance druid's caster gear and its Feral gear are not two sets.
_KIND = {
    statweights.TANK: "tank",
    statweights.HEALER: "healer",
    statweights.MELEE: "damage",
    statweights.RANGED: "damage",
    statweights.CASTER: "damage",
}
# raidlineup.party_roles' words, which gear.ROLE_* spells the same way.
PARTY_TANK, PARTY_HEALER, PARTY_DAMAGE = "tank", "healer", "damage"
_PARTY_KIND = {PARTY_TANK: "tank", PARTY_HEALER: "healer", PARTY_DAMAGE: "damage"}

# ITEM_MOD_* -> the stat names statweights prices. The same modifiers the
# Armory draws (armory.BASE_STATS, armory.EQUIP_STATS).
STAT_NAMES = {
    3: "agility",
    4: "strength",
    5: "intellect",
    6: "spirit",
    7: "stamina",
    12: "defense",
    13: "dodge",
    14: "parry",
    15: "block",
    16: "hit",
    17: "hit",
    18: "spell_hit",
    19: "crit",
    20: "crit",
    21: "crit",
    31: "hit",
    32: "crit",
    38: "attack_power",
    39: "attack_power",
    41: "spell_power",
    42: "spell_power",
    43: "mana_regeneration",
    45: "spell_power",
    48: "block_value",
}

# The battleground factions whose reputation buys PvP gear: the League of
# Arathor and the Defilers, Frostwolf and Stormpike, the Warsong Outriders and
# the Silverwing Sentinels.
PVP_FACTIONS = frozenset({509, 510, 729, 730, 889, 890})
# Words in a vendor's subname that mark it as selling for honor or arena
# points (`npc_vendor.ExtendedCost` > 0 at such a vendor). Measured on the
# world database 2026-09-24: "Arena Vendor", "Legacy Armor Quartermaster",
# "Wintergrasp Quartermaster" and their kin.
PVP_VENDOR_WORDS = ("Arena", "Legacy", "Honor", "Wintergrasp", "Battleground")

# THE RAID'S SUPPLIES, from raidsupply's own table, so a potion this module
# banks is one the Raid tab counts.
RAID_CONSUMABLES = {s.entry: s for s in raidsupply.SUPPLIES}
_SKILL_NAMES = {v: k for k, v in goals.SKILL_IDS.items()}


def _raid_reagents() -> dict:
    """entry -> (the supply names it goes into, the trades that make them)."""
    out: dict = {}
    makes = [(s.name, s.make) for s in raidsupply.SUPPLIES if s.make]
    makes += [(g.name, g.make) for g in raidsupply.FIRE_GEAR if g.make]
    for name, make in makes:
        trade = _SKILL_NAMES.get(int(make.skill), "")
        for entry, _count in make.reagents:
            names, trades = out.setdefault(int(entry), (set(), set()))
            names.add(name)
            trades.add(trade)
        for entry, _count, _price in make.vendor:
            names, trades = out.setdefault(int(entry), (set(), set()))
            names.add(name)
            trades.add(trade)
    return {e: (tuple(sorted(n)), frozenset(t)) for e, (n, t) in out.items()}


RAID_REAGENTS = _raid_reagents()


@dataclass(frozen=True)
class Piece:
    """One stack a family member holds, in its bags or its bank."""

    holder: str
    guid: int
    entry: int
    name: str
    quality: int
    item_class: int
    required_level: int = 0
    item_level: int = 0
    count: int = 1
    bound: bool = True
    fire_res: int = 0
    stats: tuple = ()  # (stat name, value) pairs
    armor: int = 0
    pvp: bool = False
    place: str = "bags"
    quest_needed: bool = False

    @property
    def is_gear(self) -> bool:
        return self.item_class in (WEAPON, ARMOR)


@dataclass(frozen=True)
class Keeper:
    """A family member, as this policy needs them: its class, its party role
    (raidlineup.party_roles) and the trades it works."""

    name: str
    class_id: int
    level: int
    role: str = ""
    trades: frozenset = frozenset()


@dataclass(frozen=True)
class Placement:
    """Where one stack belongs, and the sentence that says why."""

    guid: int
    holder: str
    item: str
    to: str  # GUILD or PERSONAL
    tab: int | None
    kind: str
    why: str

    @property
    def where(self) -> str:
        if self.to == PERSONAL:
            return "%s's bank" % self.holder
        tab = guildbank.TAB_BY_ID.get(self.tab)
        return "the guild bank's %s tab" % (tab.name if tab else "first")

    @property
    def line(self) -> str:
        """The page's line: where it goes, then why."""
        return "Bank: %s - %s" % (self.where, self.why)


@dataclass(frozen=True)
class Facts:
    """What `read` found, ready for `place`."""

    pieces: tuple = ()
    family: tuple = ()  # Keeper
    # item guid -> bag_pressure.GearReach, for every piece of gear.
    reach: dict = field(default_factory=dict)
    claimed: frozenset = field(default_factory=frozenset)


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def role_scores(piece: Piece, class_id: int) -> dict:
    """role -> what the piece is worth to that role, over the class's roles."""
    out = {}
    stats = dict(piece.stats)
    for role in statweights.roles_of_class(class_id):
        weights = statweights.stat_weights(role)
        score = sum(
            weights.get(stat, 0.0) * _int(value) for stat, value in stats.items()
        )
        score += weights.get("armor", 0.0) * _int(piece.armor) / 10.0
        out[role] = score
    return out


def off_role(piece: Piece, keeper: Keeper) -> str:
    """The statweights role this piece is for, when it is not the holder's
    role today and its class can play it; '' otherwise."""
    mine = _PARTY_KIND.get(keeper.role, "")
    if not mine:
        return ""
    scores = role_scores(piece, keeper.class_id)
    if not scores:
        return ""
    best = max(sorted(scores), key=lambda r: scores[r])
    if scores[best] <= 0 or _KIND[best] == mine:
        return ""
    # The piece must be for that role and not merely good for everyone: a
    # stamina belt scores for every role and is nobody's second set.
    same = [scores[r] for r in scores if _KIND[r] == mine]
    if same and max(same) >= scores[best]:
        return ""
    return best


def claimed_from_rows(item_rows, worn_rows, names) -> frozenset:
    """Rule 1: the guids the gear passes have a wearer for now.

    The same two opinions the passes act on, never a third: what the holder's
    own equip pass puts on (`bag_pressure.holder_equips`) and what `gear.claims`
    hands to another family member. A piece whose only claimant is its holder
    but which the equip pass leaves in the bags is NOT claimed, because a
    better piece already has that slot.
    """
    import bag_pressure  # local: bag_pressure imports the travel stack

    names = [str(n) for n in names]
    gear_rows = [
        r
        for r in item_rows
        if _int(r.get("item_class")) in (WEAPON, ARMOR) and not _in_bank(r, item_rows)
    ]
    if not gear_rows:
        return frozenset()
    equips = bag_pressure.holder_equips(gear_rows, worn_rows, names)
    out = {int(e.guid) for e in equips}
    rows_by_guid = {_int(r.get("item_guid")): r for r in gear_rows}
    for guid, who in bag_pressure.family_claimants(gear_rows, worn_rows, names).items():
        holder = str(rows_by_guid.get(int(guid), {}).get("holder", ""))
        if who in names and who != holder:
            out.add(int(guid))
    return frozenset(out)


def _second_set(piece, keeper):
    """(set kind, score, why) when this piece is one of the holder's second
    sets, else None. Fire resistance first, then PvP, then an off role."""
    if piece.fire_res > 0:
        why = "+%d fire resistance for Molten Core; %s keeps a fire resistance set" % (
            piece.fire_res,
            piece.holder,
        )
        return FIRE_SET, (piece.fire_res, piece.item_level), why
    if piece.pvp:
        why = "%s keeps it as a PvP set: it comes from an honor source" % piece.holder
        return PVP_SET, (piece.item_level, 0), why
    item = disposition.Item(
        name=piece.name,
        known=True,
        equipment=True,
        required_level=piece.required_level,
        item_class=piece.item_class,
        quest_item=False,
    )
    if disposition.outgrown(item, keeper.level):
        return None
    role = off_role(piece, keeper)
    if not role:
        return None
    why = "%s keeps a %s for when it plays %s" % (piece.holder, ROLE_SET[role], role)
    return ROLE_SET[role], (piece.item_level, 0), why


def _personal(pieces, family, reach, claimed) -> dict:
    """Rule 2: guid -> Placement for each holder's best second-set pieces."""
    keepers = {k.name: k for k in family}
    best: dict = {}
    for piece in pieces:
        keeper = keepers.get(piece.holder)
        fit = reach.get(piece.guid)
        if keeper is None or fit is None or not piece.is_gear or piece.guid in claimed:
            continue
        if not fit.holder_wears or not fit.bucket:
            continue
        found = _second_set(piece, keeper)
        if found is None:
            continue
        kind, score, why = found
        key = (piece.holder, kind, fit.bucket)
        held = best.get(key)
        if held is None or score > held[0]:
            best[key] = (score, piece, kind, why)
    return {
        piece.guid: Placement(
            piece.guid, piece.holder, piece.name, PERSONAL, None, kind, why
        )
        for _score, piece, kind, why in best.values()
    }


def _own_night(piece: Piece, keeper: Keeper) -> int:
    """How many of this raid consumable the holder drinks in one night."""
    supply = RAID_CONSUMABLES.get(piece.entry)
    if supply is None:
        return 0
    lineup_role = {PARTY_TANK: raidsupply.TANK, PARTY_HEALER: raidsupply.HEALER}.get(
        keeper.role, ""
    )
    role = raidsupply.role_of(lineup_role, keeper.class_id)
    raider = raidsupply.Raider(name=keeper.name, role=role, class_id=keeper.class_id)
    return supply.per_raider(raider)


def _raid_supplies(pieces, family, claimed, taken) -> dict:
    """Rule 3: guid -> Placement for the Raid Supplies tab."""
    keepers = {k.name: k for k in family}
    out = {}
    # Consumables: the holder keeps its own night, largest stacks first.
    kept: dict = {}
    for piece in sorted(pieces, key=lambda p: (-p.count, p.guid)):
        if piece.guid in taken or piece.bound or piece.place != "bags":
            continue
        keeper = keepers.get(piece.holder)
        if keeper is None:
            continue
        if piece.item_class == CONSUMABLE and piece.entry in RAID_CONSUMABLES:
            want = _own_night(piece, keeper)
            have = kept.get((piece.holder, piece.entry), 0)
            if have < want:
                kept[(piece.holder, piece.entry)] = have + piece.count
                continue
            out[piece.guid] = Placement(
                piece.guid,
                piece.holder,
                piece.name,
                GUILD,
                RAID_TAB,
                "raid supply",
                "%s is a Molten Core consumable past the %d %s drinks in one "
                "night" % (piece.name, want, piece.holder),
            )
            continue
        if piece.entry in RAID_REAGENTS:
            supplies, trades = RAID_REAGENTS[piece.entry]
            if keeper.trades & trades:
                continue
            out[piece.guid] = Placement(
                piece.guid,
                piece.holder,
                piece.name,
                GUILD,
                RAID_TAB,
                "raid reagent",
                "%s goes into %s, which %s does not make"
                % (piece.name, " and ".join(supplies[:2]), piece.holder),
            )
            continue
        if piece.is_gear and piece.fire_res > 0 and piece.guid not in claimed:
            out[piece.guid] = Placement(
                piece.guid,
                piece.holder,
                piece.name,
                GUILD,
                RAID_TAB,
                "fire resistance",
                "+%d fire resistance for Molten Core that %s cannot wear, for "
                "a raider who can" % (piece.fire_res, piece.holder),
            )
    return out


def _gear_for_later(pieces, reach, claimed, taken) -> dict:
    """Rule 4: guid -> Placement for the Gear for Later tab."""
    out = {}
    for piece in pieces:
        fit = reach.get(piece.guid)
        if (
            fit is None
            or piece.guid in taken
            or piece.guid in claimed
            or not piece.is_gear
            or piece.bound
            or piece.quality < RARE
            or piece.place != "bags"
            or not fit.later_wearers
        ):
            continue
        wearers = fit.later_wearers
        out[piece.guid] = Placement(
            piece.guid,
            piece.holder,
            piece.name,
            GUILD,
            GEAR_TAB,
            "gear for later",
            "%s is %s gear nobody in the family wears now; %s will wear it "
            "at level %d"
            % (
                piece.name,
                "epic" if piece.quality >= 4 else "rare",
                wearers[0]
                if len(wearers) == 1
                else "%s and %d more" % (wearers[0], len(wearers) - 1),
                piece.required_level,
            ),
        )
    return out


def place(facts: Facts) -> dict:
    """guid -> Placement for every stack this policy has an answer for.

    A guid missing from the answer is not this policy's: the gear passes,
    the keeper rule and the sell passes decide it as they did before.
    """
    pieces = tuple(p for p in facts.pieces if not p.quest_needed)
    claimed = frozenset(facts.claimed)
    out = dict(_personal(pieces, facts.family, facts.reach, claimed))
    out.update(_raid_supplies(pieces, facts.family, claimed, frozenset(out)))
    out.update(_gear_for_later(pieces, facts.reach, claimed, frozenset(out)))
    return out


def why_stored(row: dict) -> str:
    """Why an item already in the guild bank is there, from its tab and kind.

    `row` carries tab_id, entry, item_class, quality and fire_res. The tab's
    own purpose first; a raid reagent or consumable says which supply.
    """
    tab = guildbank.TAB_BY_ID.get(_int(row.get("tab_id"), -1))
    entry = _int(row.get("entry"))
    parts = []
    if entry in RAID_REAGENTS:
        parts.append("a reagent for %s" % " and ".join(RAID_REAGENTS[entry][0][:2]))
    elif entry in RAID_CONSUMABLES:
        parts.append("a Molten Core consumable")
    elif _int(row.get("fire_res")) > 0:
        parts.append("+%d fire resistance for Molten Core" % _int(row.get("fire_res")))
    elif (
        _int(row.get("item_class")) in (WEAPON, ARMOR)
        and _int(row.get("quality")) >= RARE
    ):
        parts.append("rare gear kept for a guildmate who will wear it")
    if tab is not None:
        parts.append("%s: %s" % (tab.name, tab.holds))
    return "; ".join(parts)


def annotate_tips(payload, by_guid: dict) -> int:
    """Add each placement's line to the Bags payload's tooltip for that item.

    The same walk lootcouncil.annotate_tips makes: the line is composed here,
    never in the page. Returns how many tips were changed.
    """
    if not by_guid:
        return 0
    count = 0
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            guid = node.get("guid")
            if guid is not None and "tip" in node:
                placed = by_guid.get(_int(guid))
                if placed is not None and placed.line not in node["tip"]:
                    node["tip"] = "%s\n%s" % (node["tip"], placed.line)
                    count += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return count


# ---------------------------------------------------------------------------
# THE FACTS, READ THE SAME WAY BY THE BRIDGE AND THE SITE.

_STAT_COLUMNS = ", ".join(
    "it.stat_type%d AS stat_type%d, it.stat_value%d AS stat_value%d" % (n, n, n, n)
    for n in range(1, 11)
)

# S608: every piece of this string is a module constant; the names are bound
# as parameters by the caller.
ITEMS_SQL = (
    "SELECT c.name AS holder, ii.guid AS item_guid, ii.itemEntry AS entry, "  # noqa: S608
    "ii.count AS count, ii.flags AS instance_flags, ci.bag AS bag, ci.slot AS slot, "
    "it.name AS name, it.Quality AS quality, it.class AS item_class, "
    "it.subclass AS item_subclass, it.InventoryType AS inventory_type, "
    "it.RequiredLevel AS required_level, it.AllowableClass AS allowable_class, "
    "it.ItemLevel AS item_level, it.bonding AS bonding, it.fire_res AS fire_res, "
    "it.armor AS armor, it.ContainerSlots AS container_slots, "
    "it.requiredhonorrank AS honor_rank, "
    "it.RequiredReputationFaction AS rep_faction, "
    "(it.spellid_1 > 0 OR it.spellid_2 > 0) AS has_effect, "
    # An open quest needs it (bag_pressure.QUEST_NEEDED_SQL's own test): the
    # quest rule's, never this policy's.
    "EXISTS (SELECT 1 FROM character_queststatus qs "
    "  JOIN acore_world.quest_template qt ON qt.ID = qs.quest "
    "  WHERE qs.guid = ci.guid AND qs.status <> 0 AND ii.itemEntry IN ("
    "  qt.RequiredItemId1, qt.RequiredItemId2, qt.RequiredItemId3, "
    "  qt.RequiredItemId4, qt.RequiredItemId5, qt.RequiredItemId6, "
    "  qt.ItemDrop1, qt.ItemDrop2, qt.ItemDrop3, qt.ItemDrop4, qt.StartItem)"
    ") AS quest_needed, "
    "pv.item IS NOT NULL AS pvp_vendor, "
    + _STAT_COLUMNS
    + " FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    # THE HONOR VENDORS' ITEMS, READ ONCE PER QUERY. An EXISTS per row scanned
    # npc_vendor (37,753 rows, keyed by vendor first) for every stack, about
    # two seconds a family on the dev realm; one derived table is one scan.
    "LEFT JOIN (SELECT DISTINCT v.item FROM acore_world.npc_vendor v "
    "  JOIN acore_world.creature_template ct ON ct.entry = v.entry "
    "  WHERE v.ExtendedCost > 0 AND ("
    # LOCATE, NOT LIKE: this string passes through `% marks` and then
    # pymysql's own `query % args`, and a LIKE pattern's percent signs would
    # have to survive both.
    + " OR ".join("LOCATE('%s', ct.subname) > 0" % w for w in PVP_VENDOR_WORDS)
    + ")) pv ON pv.item = it.entry "
    "WHERE c.name IN (%s) AND NOT (ci.bag = 0 AND ci.slot < 19)"
)

WORN_SQL = (
    "SELECT c.name AS name, c.class AS class_id, c.level AS level, "
    "it.InventoryType AS inventory_type, it.ItemLevel AS item_level "
    "FROM characters c "
    "LEFT JOIN character_inventory ci ON ci.guid = c.guid AND ci.bag = 0 AND ci.slot < 19 "
    "LEFT JOIN item_instance ii ON ii.guid = ci.item "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s)"
)

SKILLS_SQL = (
    "SELECT c.name AS name, cs.skill AS skill, cs.value AS value "
    "FROM character_skills cs JOIN characters c ON c.guid = cs.guid "
    "WHERE c.name IN (%s) AND cs.skill IN ("
    + ", ".join(str(v) for v in sorted(set(goals.SKILL_IDS.values())))
    + ")"
)

# Player inventory geography, as bank.py reads it: the bank's own slots and
# its seven bag positions.
_BANK_ITEM_SLOTS = range(39, 67)
_BANK_BAG_POSITIONS = range(67, 74)
_BONDING_BOUND = frozenset({1, 4})


def _bank_bags(rows) -> frozenset:
    return frozenset(
        _int(r.get("item_guid"))
        for r in rows
        if _int(r.get("bag"), -1) == 0
        and _int(r.get("slot"), -1) in _BANK_BAG_POSITIONS
    )


def _in_bank(row, rows, bank_bags=None) -> bool:
    """Is this row in the bank: its 28 slots, or a bag in a bank bag position."""
    bags = _bank_bags(rows) if bank_bags is None else bank_bags
    bag, slot = _int(row.get("bag"), -1), _int(row.get("slot"), -1)
    return (bag == 0 and slot in _BANK_ITEM_SLOTS) or bag in bags


def pieces_from_rows(rows) -> tuple:
    """Pieces from ITEMS_SQL rows; a row that cannot be read is left out."""
    bank_bags = _bank_bags(rows)
    out = []
    for row in rows:
        try:
            if _int(row.get("container_slots")) > 0:
                continue
            in_bank = _in_bank(row, rows, bank_bags)
            stats = []
            for n in range(1, 11):
                name = STAT_NAMES.get(_int(row.get("stat_type%d" % n)))
                value = _int(row.get("stat_value%d" % n))
                if name and value:
                    stats.append((name, value))
            name = row.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            out.append(
                Piece(
                    holder=str(row["holder"]),
                    guid=int(row["item_guid"]),
                    entry=_int(row.get("entry")),
                    name=name,
                    quality=_int(row.get("quality")),
                    item_class=_int(row.get("item_class"), 12),
                    required_level=_int(row.get("required_level")),
                    item_level=_int(row.get("item_level")),
                    count=max(1, _int(row.get("count"), 1)),
                    bound=(
                        _int(row.get("bonding"), 1) in _BONDING_BOUND
                        or bool(_int(row.get("instance_flags")) & 0x1)
                    ),
                    fire_res=_int(row.get("fire_res")),
                    stats=tuple(stats),
                    armor=_int(row.get("armor")),
                    pvp=(
                        _int(row.get("honor_rank")) > 0
                        or _int(row.get("rep_faction")) in PVP_FACTIONS
                        or bool(_int(row.get("pvp_vendor")))
                    ),
                    place="bank" if in_bank else "bags",
                    quest_needed=bool(_int(row.get("quest_needed"))),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(out)


def trades_from_rows(rows) -> dict:
    """name -> the trades (lower-case) it holds any skill in."""
    out: dict = {}
    for row in rows:
        trade = _SKILL_NAMES.get(_int(row.get("skill")))
        if trade and _int(row.get("value")) > 0:
            out.setdefault(str(row.get("name")), set()).add(trade)
    return {name: frozenset(t) for name, t in out.items()}


def facts_from_rows(names, item_rows, worn_rows, skill_rows) -> Facts:
    """Facts for one family, from the three reads."""
    import bag_pressure  # local: bag_pressure imports the travel stack

    names = [str(n) for n in names]
    trades = trades_from_rows(skill_rows)
    gear_rows = [r for r in item_rows if _int(r.get("item_class")) in (WEAPON, ARMOR)]
    reach = bag_pressure.gear_reach(gear_rows, worn_rows, names)
    classes = {}
    for row in worn_rows:
        name = str(row.get("name") or "")
        if name in names:
            classes[name] = (_int(row.get("class_id")), _int(row.get("level")))
    party = _party_roles(names, classes)
    family = []
    for name in names:
        if name not in classes:
            continue
        class_id, level = classes[name]
        family.append(
            Keeper(
                name=name,
                class_id=class_id,
                level=level,
                role=party.get(name, ""),
                trades=trades.get(name, frozenset()),
            )
        )
    return Facts(
        pieces=pieces_from_rows(item_rows),
        family=tuple(family),
        reach=reach,
        claimed=claimed_from_rows(item_rows, worn_rows, names),
    )


def _party_roles(names, classes) -> dict:
    """name -> tank, healer or damage: raidlineup's packing of one party."""
    import raidlineup

    return raidlineup.party_roles(
        [{"name": n, "class_id": classes[n][0]} for n in names if n in classes]
    )


def read(cur, names) -> Facts:
    """The three reads over `cur`, for one family."""
    names = [str(n) for n in names or () if n]
    if not names:
        return Facts()
    marks = ",".join(["%s"] * len(names))
    cur.execute(ITEMS_SQL % marks, names)
    items = [dict(r) for r in cur.fetchall()]
    cur.execute(WORN_SQL % marks, names)
    worn = [dict(r) for r in cur.fetchall()]
    cur.execute(SKILLS_SQL % marks, names)
    skills = [dict(r) for r in cur.fetchall()]
    return facts_from_rows(names, items, worn, skills)
