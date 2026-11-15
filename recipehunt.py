"""Vendor recipes and Cenarion / Timbermaw reputation turn-ins (#2423).

Drives two things missing after recipe routing (#2418) and Dark Iron (#480):
1. All seven vendor-sold Alchemy (171) and Enchanting (333) recipes from #2423,
   learned from carried items (`use guid:<n>`) or bought strictly with the
   crafter's own gold above `guildjobs.recipe_purse_floor(level)`.
2. Repeatable Cenarion Circle (609 -> Friendly 3000) and Timbermaw Hold
   (576 -> Honored 9000) reputation turn-ins for crafters who need
   reputation-gated vendor recipes.
"""

from __future__ import annotations

from dataclasses import dataclass

import auction
import guildcorps
import guildroute
import purse
import towntrip

SOURCE = "overseer:recipe-hunt"
CORPS_SOURCE = "recipehunt"
TOWN_CLAIMANT = "recipehunt"
REFUSED_RETRY_MINUTES = 360

ALCHEMY = guildcorps.ALCHEMY
ENCHANTING = 333
TRADE_SKILLS = frozenset({ALCHEMY, ENCHANTING})

FACTION_TIMBERMAW = 576
FACTION_CENARION = 609

TIMBERMAW_HONORED = 9000
CENARION_FRIENDLY = 3000

# character_reputation.standing is stored relative to Faction.dbc ReputationBase.
# Cenarion Circle starts Neutral (0); Timbermaw Hold starts Hostile 2500/3000 (-3500).
BASE_STANDING = {
    FACTION_CENARION: 0,
    FACTION_TIMBERMAW: -3500,
}

TWILIGHT_TEXT = 20404
DEADWOOD_FEATHER = 21377
WINTERFALL_BEADS = 21383


@dataclass(frozen=True)
class VendorSpot:
    """One NPC that stocks a vendor recipe on one side and continent."""

    npc_entry: int
    name: str
    where: str
    map_id: int
    side: str  # "alliance", "horde", or "" for neutral


@dataclass(frozen=True)
class VendorRecipe:
    """One vendor-sold recipe from the #2423 Molten Core readiness table."""

    item_entry: int
    spell_id: int
    skill_id: int
    skill_rank: int
    price: int
    name: str
    vendors: tuple[VendorSpot, ...]
    rep_faction: int | None = None
    rep_standing: int = 0


@dataclass(frozen=True)
class RepTurnin:
    """One repeatable reputation quest for Cenarion Circle or Timbermaw Hold."""

    faction: int
    target_standing: int
    quest_id: int
    npc_entry: int
    npc_name: str
    where: str
    map_id: int
    min_level: int
    item_entry: int
    item_count: int
    prereq_quest: int | None = None


@dataclass(frozen=True)
class Crafter:
    """Pure snapshot of one Alchemy / Enchanting crafter."""

    name: str
    guild: str = ""
    level: int = 60
    race: int = 0
    map_id: int = 0
    alchemy: int = 0
    enchanting: int = 0
    learned: frozenset[int] = frozenset()
    held: tuple[tuple[int, int], ...] = ()  # ((item_entry, item_guid), ...)
    item_counts: tuple[tuple[int, int], ...] = ()  # ((item_entry, count), ...)
    in_log: frozenset[int] = frozenset()
    rewarded: frozenset[int] = frozenset()
    standing: tuple[tuple[int, int], ...] = ()  # ((faction, raw_standing), ...)
    money: int = 0
    free_slots: int = 0
    stocks: frozenset[int] = frozenset()
    family: bool = False
    online: bool = True

    def skill(self, skill_id: int) -> int:
        if skill_id == ALCHEMY:
            return int(self.alchemy)
        if skill_id == ENCHANTING:
            return int(self.enchanting)
        return 0

    def item_count(self, entry: int) -> int:
        return dict(self.item_counts).get(int(entry), 0)

    def raw_standing(self, faction: int) -> int:
        return dict(self.standing).get(int(faction), 0)


@dataclass(frozen=True)
class FamilyTurn:
    """Next action for one family crafter."""

    errand: towntrip.Errand | None = None
    note: str = ""
    walk_vendor_item: int = 0
    walk_npc_entry: int = 0


VENDOR_RECIPES: tuple[VendorRecipe, ...] = (
    VendorRecipe(
        6055,
        7257,
        ALCHEMY,
        165,
        1500,
        "Recipe: Fire Protection Potion",
        (
            VendorSpot(2812, "Nandar Branson", "Hillsbrad Foothills", 0, "alliance"),
            VendorSpot(3413, "Jeeda", "Stonetalon Mountains", 1, "horde"),
        ),
    ),
    VendorRecipe(
        13478,
        17554,
        ALCHEMY,
        265,
        13000,
        "Recipe: Elixir of Superior Defense",
        (
            VendorSpot(4226, "Soolie Berryfizz", "Ironforge", 0, "alliance"),
            VendorSpot(4610, "Kor'geld", "Orgrimmar", 1, "horde"),
        ),
    ),
    VendorRecipe(
        13501,
        17580,
        ALCHEMY,
        295,
        30000,
        "Recipe: Major Mana Potion",
        (VendorSpot(11278, "Magnus Frostwake", "Western Plaguelands", 0, ""),),
    ),
    VendorRecipe(
        16221,
        20026,
        ENCHANTING,
        275,
        16000,
        "Formula: Enchant Chest - Major Health",
        (VendorSpot(11189, "Qia", "Winterspring", 1, ""),),
    ),
    VendorRecipe(
        16224,
        20015,
        ENCHANTING,
        285,
        20000,
        "Formula: Enchant Cloak - Superior Defense",
        (VendorSpot(12022, "Lorelae Wintersong", "Moonglade", 1, ""),),
    ),
    VendorRecipe(
        19445,
        23800,
        ENCHANTING,
        290,
        30000,
        "Formula: Enchant Weapon - Agility",
        (VendorSpot(11557, "Meilosh", "Felwood", 1, ""),),
        rep_faction=FACTION_TIMBERMAW,
        rep_standing=TIMBERMAW_HONORED,
    ),
    VendorRecipe(
        20732,
        25081,
        ENCHANTING,
        300,
        40000,
        "Formula: Enchant Cloak - Greater Fire Resistance",
        (VendorSpot(15419, "Kania", "Silithus", 1, ""),),
        rep_faction=FACTION_CENARION,
        rep_standing=CENARION_FRIENDLY,
    ),
)

VENDOR_RECIPE_ITEMS = frozenset(r.item_entry for r in VENDOR_RECIPES)
VENDOR_RECIPE_SPELLS = frozenset(r.spell_id for r in VENDOR_RECIPES)

REP_TURNINS: tuple[RepTurnin, ...] = (
    RepTurnin(
        FACTION_CENARION,
        CENARION_FRIENDLY,
        8318,
        15306,
        "Bor Wildmane",
        "Silithus",
        1,
        57,
        TWILIGHT_TEXT,
        10,
        prereq_quest=None,
    ),
    RepTurnin(
        FACTION_CENARION,
        CENARION_FRIENDLY,
        8319,
        15306,
        "Bor Wildmane",
        "Silithus",
        1,
        57,
        TWILIGHT_TEXT,
        10,
        prereq_quest=8318,
    ),
    RepTurnin(
        FACTION_TIMBERMAW,
        TIMBERMAW_HONORED,
        8466,
        11554,
        "Grazle",
        "Felwood",
        1,
        45,
        DEADWOOD_FEATHER,
        5,
        prereq_quest=8460,
    ),
    RepTurnin(
        FACTION_TIMBERMAW,
        TIMBERMAW_HONORED,
        8467,
        15395,
        "Nafien",
        "Felwood",
        1,
        45,
        DEADWOOD_FEATHER,
        5,
        prereq_quest=8461,
    ),
    RepTurnin(
        FACTION_TIMBERMAW,
        TIMBERMAW_HONORED,
        8469,
        11556,
        "Salfa",
        "Winterspring",
        1,
        45,
        WINTERFALL_BEADS,
        5,
        prereq_quest=8464,
    ),
)

REP_FACTIONS = frozenset({FACTION_CENARION, FACTION_TIMBERMAW})
REP_QUEST_IDS = frozenset(
    {t.quest_id for t in REP_TURNINS}
    | {t.prereq_quest for t in REP_TURNINS if t.prereq_quest}
)
REP_ITEM_ENTRIES = frozenset(t.item_entry for t in REP_TURNINS)
REP_NPC_ENTRIES = frozenset(t.npc_entry for t in REP_TURNINS)


def effective_standing(faction: int, raw_standing: int) -> int:
    """Worldserver effective reputation (Faction.dbc base + raw standing)."""
    return int(BASE_STANDING.get(int(faction), 0)) + int(raw_standing)


def _own_vendor(recipe: VendorRecipe, race: int) -> VendorSpot | None:
    side = auction.team_of(race)
    neutral = None
    for spot in recipe.vendors:
        if not spot.side:
            neutral = spot
        elif side and spot.side == side:
            return spot
    return neutral


def _carried_recipe(crafter: Crafter) -> tuple[VendorRecipe, int] | None:
    held_map = {int(entry): int(guid) for entry, guid in crafter.held if int(guid) > 0}
    for recipe in VENDOR_RECIPES:
        guid = held_map.get(recipe.item_entry)
        if guid and recipe.spell_id not in crafter.learned:
            return recipe, guid
    return None


def _due_recipes(crafter: Crafter) -> list[VendorRecipe]:
    return [
        recipe
        for recipe in VENDOR_RECIPES
        if recipe.spell_id not in crafter.learned
        and crafter.skill(recipe.skill_id) >= recipe.skill_rank
    ]


def _rep_met(crafter: Crafter, recipe: VendorRecipe) -> bool:
    if recipe.rep_faction is None:
        return True
    eff = effective_standing(
        recipe.rep_faction, crafter.raw_standing(recipe.rep_faction)
    )
    return eff >= recipe.rep_standing


def _eligible_turnin(
    crafter: Crafter, faction: int, *, require_same_map: bool
) -> tuple[RepTurnin | None, str]:
    candidates = [t for t in REP_TURNINS if t.faction == faction]
    prereq_note = ""
    for turnin in candidates:
        if turnin.quest_id in crafter.in_log:
            if require_same_map and crafter.map_id != turnin.map_id:
                continue
            return turnin, ""
    for turnin in candidates:
        if turnin.quest_id in crafter.rewarded:
            continue
        if crafter.level < turnin.min_level:
            continue
        if crafter.item_count(turnin.item_entry) < turnin.item_count:
            continue
        if (
            turnin.prereq_quest is not None
            and turnin.prereq_quest not in crafter.rewarded
        ):
            prereq_note = "%s needs prerequisite quest %d rewarded for quest %d" % (
                crafter.name,
                turnin.prereq_quest,
                turnin.quest_id,
            )
            continue
        if require_same_map and crafter.map_id != turnin.map_id:
            prereq_note = "%s turns in quest %d in %s on map %d" % (
                crafter.name,
                turnin.quest_id,
                turnin.where,
                turnin.map_id,
            )
            continue
        return turnin, ""
    return None, prereq_note


def _check_block(errand: towntrip.Errand, blocked: frozenset) -> FamilyTurn:
    if (errand.member, errand.command) in blocked:
        return FamilyTurn(
            note="%s %s is pending or was refused inside retry window"
            % (errand.member, errand.command)
        )
    return FamilyTurn(errand=errand)


def _plan_buy_family(
    crafter: Crafter, recipe: VendorRecipe, seller: VendorSpot
) -> FamilyTurn | None:
    if seller.map_id != crafter.map_id:
        return FamilyTurn(
            note="%s buys %s from %s in %s on map %d"
            % (crafter.name, recipe.name, seller.name, seller.where, seller.map_id)
        )
    if recipe.item_entry not in crafter.stocks:
        return FamilyTurn(
            note="%s walks to %s for %s" % (crafter.name, seller.name, recipe.name),
            walk_vendor_item=recipe.item_entry,
        )
    if crafter.free_slots < 1:
        return FamilyTurn(
            note="%s has no free bag slot for %s" % (crafter.name, recipe.name)
        )
    floor = purse.recipe_purse_floor(crafter.level)
    if crafter.money < recipe.price + floor:
        return FamilyTurn(
            note="%s is short of gold for %s (has %d, needs %d + floor %d)"
            % (crafter.name, recipe.name, crafter.money, recipe.price, floor)
        )
    return FamilyTurn(
        errand=towntrip.Errand(
            crafter.name,
            "buy",
            "entry:%d count:1 max:%d" % (recipe.item_entry, recipe.price),
            recipe.name,
            recipe.price,
        )
    )


def plan_family_crafter(
    crafter: Crafter,
    *,
    nearby_spawns: dict | None = None,
    blocked: frozenset = frozenset(),
) -> FamilyTurn:
    """Next recipe-hunt errand, walk, or note for one family crafter."""
    carried = _carried_recipe(crafter)
    if carried is not None:
        recipe, guid = carried
        errand = towntrip.Errand(
            crafter.name, "cast", "use guid:%d" % guid, "learn %s" % recipe.name
        )
        return _check_block(errand, blocked)

    first_note = ""
    near = nearby_spawns or {}
    for recipe in _due_recipes(crafter):
        seller = _own_vendor(recipe, crafter.race)
        if seller is None:
            if not first_note:
                first_note = "%s's faction side is unread for %s" % (
                    crafter.name,
                    recipe.name,
                )
            continue
        if _rep_met(crafter, recipe):
            turn = _plan_buy_family(crafter, recipe, seller)
            if turn is not None:
                if turn.errand is not None:
                    return _check_block(turn.errand, blocked)
                if turn.walk_vendor_item:
                    return turn
                if not first_note:
                    first_note = turn.note
            continue
        turnin, note = _eligible_turnin(
            crafter, int(recipe.rep_faction), require_same_map=True
        )
        if turnin is None:
            if not first_note:
                first_note = note or "%s lacks turn-in items for %s" % (
                    crafter.name,
                    recipe.name,
                )
            continue
        verb = "turnin" if turnin.quest_id in crafter.in_log else "take"
        if turnin.npc_entry not in near:
            return FamilyTurn(
                note="%s walks to %s (%s) for quest %d"
                % (crafter.name, turnin.npc_name, turnin.where, turnin.quest_id),
                walk_npc_entry=turnin.npc_entry,
            )
        errand = towntrip.Errand(
            crafter.name,
            "quest",
            "%s quest:%d" % (verb, turnin.quest_id),
            "reputation for %s" % recipe.name,
        )
        return _check_block(errand, blocked)

    return FamilyTurn(note=first_note)


def _step_cooling(holder: str, key: int, recent: set) -> bool:
    return (holder, key) in recent


def plan_corps_step(
    crafter: Crafter,
    *,
    npc_spawns: dict | None = None,
    cap: float = guildroute.MAIL_RUN_YARDS,
) -> guildcorps.Step | None:
    """Next `guildcorps.Step` (with walk) for a maintenance guild crafter."""
    carried = _carried_recipe(crafter)
    if carried is not None:
        recipe, guid = carried
        return guildcorps.Step(
            crafter.name,
            "learn",
            recipe.item_entry,
            "%s learns %s" % (crafter.name, recipe.name),
            (
                guildcorps.Row(
                    "cast",
                    "use guid:%d" % guid,
                    "",
                    "%s:learn:%d" % (CORPS_SOURCE, recipe.item_entry),
                ),
            ),
        )

    spawns = npc_spawns or {}
    for recipe in _due_recipes(crafter):
        seller = _own_vendor(recipe, crafter.race)
        if seller is None or seller.map_id != crafter.map_id:
            continue
        if _rep_met(crafter, recipe):
            if crafter.free_slots < 1:
                continue
            floor = purse.recipe_purse_floor(crafter.level)
            if crafter.money < recipe.price + floor:
                continue
            walk = None
            if recipe.item_entry not in crafter.stocks:
                walk = guildcorps.Row(
                    "job",
                    "walk-to-vendor item:%d%s"
                    % (recipe.item_entry, guildroute.errand_cap_word(cap)),
                    "",
                    "%s:buy-walk:%d" % (CORPS_SOURCE, recipe.item_entry),
                )
            buy = guildcorps.Row(
                "buy",
                "entry:%d count:1 max:%d" % (recipe.item_entry, recipe.price),
                "",
                "%s:buy:%d" % (CORPS_SOURCE, recipe.item_entry),
            )
            return guildcorps.Step(
                crafter.name,
                "buy",
                recipe.item_entry,
                "%s buys %s from %s in %s"
                % (crafter.name, recipe.name, seller.name, seller.where),
                (buy,),
                walk=walk,
            )

        turnin, _ = _eligible_turnin(
            crafter, int(recipe.rep_faction), require_same_map=True
        )
        if turnin is None:
            continue
        spawn_guid = int(spawns.get(turnin.npc_entry) or 0)
        if not spawn_guid:
            continue
        rows = (
            (
                guildcorps.Row(
                    "quest",
                    "turnin quest:%d" % turnin.quest_id,
                    "",
                    "%s:turnin:%d" % (CORPS_SOURCE, turnin.quest_id),
                ),
            )
            if turnin.quest_id in crafter.in_log
            else (
                guildcorps.Row(
                    "quest",
                    "take quest:%d" % turnin.quest_id,
                    "",
                    "%s:take:%d" % (CORPS_SOURCE, turnin.quest_id),
                ),
                guildcorps.Row(
                    "quest",
                    "turnin quest:%d" % turnin.quest_id,
                    "",
                    "%s:turnin:%d" % (CORPS_SOURCE, turnin.quest_id),
                ),
            )
        )
        walk = guildcorps.Row(
            "job",
            "walk-to-spawn creature:%d near:12%s"
            % (spawn_guid, guildroute.errand_cap_word(cap)),
            "",
            "%s:rep-walk:%d" % (CORPS_SOURCE, turnin.quest_id),
        )
        return guildcorps.Step(
            crafter.name,
            "rep",
            turnin.quest_id,
            "%s hands in %s for %s" % (crafter.name, turnin.npc_name, recipe.name),
            rows,
            walk=walk,
        )
    return None


def plan_guild_steps(
    crafters: list[Crafter],
    busy: set[str],
    recent: set[tuple[str, int]],
    *,
    npc_spawns: dict | None = None,
    cap: float = guildroute.MAIL_RUN_YARDS,
) -> tuple[list[guildcorps.Step], list[str]]:
    """Plan at most one recipe-hunt step per guild this pass."""
    steps: list[guildcorps.Step] = []
    notes: list[str] = []
    chosen_guilds: set[str] = set()
    for crafter in sorted(crafters, key=lambda c: (c.guild, c.name)):
        if (
            crafter.family
            or not crafter.online
            or crafter.name in busy
            or crafter.guild in chosen_guilds
        ):
            continue
        step = plan_corps_step(crafter, npc_spawns=npc_spawns, cap=cap)
        if step is None:
            continue
        if _step_cooling(step.holder, step.key, recent):
            notes.append(
                "%s (%s) step %s %s is cooling"
                % (crafter.guild, step.holder, step.action, step.key)
            )
            continue
        steps.append(step)
        busy.add(step.holder)
        chosen_guilds.add(crafter.guild)
    return steps, notes
