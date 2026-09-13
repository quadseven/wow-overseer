"""Where the family can be sent, and what to call it.

infra#2783. Until this existed the family could walk to a quest objective and
nowhere else - no trainer, no vendor, no repair, no bank, no guild-charter
petitioner, no tabard designer. Every one of those was already an allowed RPG
target in mod-playerbots (PossibleRpgTargetsValue.cpp:23-46, one unconditional
block); what was missing was any way to say WHICH one. This module is the
vocabulary for saying it.

WHY A ROLE AND NOT A CREATURE ID. "Send Grug to a profession trainer" is a
decision the council can make from what it knows. "Send Grug to creature 5511"
requires knowing which trainer is nearest to wherever Grug is standing right
now, which is a fact only the worldserver holds and which changes as he walks.
So the roles below are the normal way to aim, and mod-overseer resolves the
nearest matching spawn on the character's own map at the moment it aims him. A
bare creature entry is still accepted for the case where the target really is
one specific NPC.

WHY THE KEYWORDS ARE DUPLICATED IN C++. mod-overseer reads overseer_roster
directly inside the worldserver; there is no shared schema between a Python
process and a compiled module, so the table exists twice and the two copies
have to agree. tests/test_travel_npc.py compares them line for line, in both
directions, because a keyword this side would resolve and that side would not
is precisely a "written and unread" bug of the kind #2776 already produced.

WHAT THIS DELIVERS IS TRAVEL, NOT TRANSACTION. Aiming a character at a trainer
makes it walk to the trainer and stand there. It does not train. Buying,
training, repairing and signing a charter are each their own issue; every one
of them was blocked on the character being unable to get there at all.

AND ONE OF THE ROLES BELOW IS NOT A CREATURE AT ALL - see the note on
"guild banker", and `ground_aim`/`vault_aim` at the foot of this file for the
aim that reaches it instead.
"""

from dataclasses import dataclass

# Canonical keyword -> the UNIT_NPC_FLAG_* the module matches spawns on.
#
# Every flag here is in mod-playerbots' own allowed-RPG-target list at the
# pinned module SHA, so a character standing in front of one of these is a
# state the rest of the RPG layer already expects and handles.
#
# THIS TABLE IS A MIRROR, NOT A WISHLIST. test_travel_npc.py asserts it is
# EQUAL to mod-overseer's own `TravelAimBook::TravelRoles()` - keys and values,
# in both directions - so an entry is here because the C++ carries it, and
# removing one here without removing it there is a test failure, not a fix.
# That is why the dead entry below is documented rather than deleted.
ROLES = {
    "trainer": "UNIT_NPC_FLAG_TRAINER",
    "class trainer": "UNIT_NPC_FLAG_TRAINER_CLASS",
    "profession trainer": "UNIT_NPC_FLAG_TRAINER_PROFESSION",
    "vendor": "UNIT_NPC_FLAG_VENDOR",
    "repair": "UNIT_NPC_FLAG_REPAIR",
    "banker": "UNIT_NPC_FLAG_BANKER",
    # DEAD ON 3.3.5, AND KEPT ONLY BECAUSE THE MIRROR ABOVE REQUIRES IT
    # (infra#3702). Counted against the live wow-dev world database rather
    # than a wiki:
    #
    #     SELECT COUNT(*) FROM acore_world.creature_template
    #      WHERE npcflag & 0x8000000;   -> 0
    #
    # Not one creature template in the entire world carries
    # UNIT_NPC_FLAG_GUILD_BANKER, so `travel_npc = 'guild banker'` can never
    # resolve to a spawn - not on any map, for any character, ever. The guild
    # bank in this expansion is a GAMEOBJECT ("Guild Vault",
    # gameobject_template.type = 34, GUILD_VAULT_GO_TYPE below), of which the
    # same database has 41 spawns across four maps. `ResolveTravelTarget`'s
    # role-keyword branch searches `_travelSpawns`, which is built from
    # creatures, so it searches a table the answer is not in.
    #
    # NOTHING IN THIS PROCESS WRITES THIS KEYWORD ANY MORE. The guild bank
    # pass aims at the vault's own spawn row through `vault_aim` below. This
    # entry stays so `travel.ROLES == TravelRoles()` keeps holding; making the
    # C++ side stop claiming the flag is a module change and its own issue,
    # not something to fake from this side.
    "guild banker": "UNIT_NPC_FLAG_GUILD_BANKER",
    "auctioneer": "UNIT_NPC_FLAG_AUCTIONEER",
    "petitioner": "UNIT_NPC_FLAG_PETITIONER",
    "tabard designer": "UNIT_NPC_FLAG_TABARDDESIGNER",
    "innkeeper": "UNIT_NPC_FLAG_INNKEEPER",
    "flight master": "UNIT_NPC_FLAG_FLIGHTMASTER",
    "stable master": "UNIT_NPC_FLAG_STABLEMASTER",
}

# How a person or a council actually says it. The canonical keyword is always
# an alias of itself, so `resolve` needs no special case for the exact form.
ALIASES = {
    "spell trainer": "class trainer",
    "class": "class trainer",
    "profession": "profession trainer",
    "professions": "profession trainer",
    "merchant": "vendor",
    "shop": "vendor",
    "general goods": "vendor",
    "repairs": "repair",
    "armourer": "repair",
    "armorer": "repair",
    "bank": "banker",
    "guild bank": "guild banker",
    "auction": "auctioneer",
    "auction house": "auctioneer",
    "ah": "auctioneer",
    "charter": "petitioner",
    "guild charter": "petitioner",
    "tabard": "tabard designer",
    "inn": "innkeeper",
    "hearth": "innkeeper",
    "flight": "flight master",
    "flightmaster": "flight master",
    "stable": "stable master",
    "stablemaster": "stable master",
}

# overseer_roster.travel_npc is VARCHAR(32). A keyword that does not fit is a
# keyword the module can never read back, so the limit is enforced here rather
# than discovered as a silently truncated row.
COLUMN_WIDTH = 32

# The sentinel for "no opinion", matching every other column on this table.
# Not NULL: mod-overseer reads these with Field::Get<std::string> and a
# nullable column would put a NULL check in front of every read for no gain.
NONE = ""

# GAMEOBJECT_TYPE_GUILD_BANK. What a Guild Vault actually is on 3.3.5, and the
# reason the "guild banker" npcflag above has never matched anything - see its
# note. Named here rather than written as a bare 34 in a WHERE clause because
# it is a fact about the game, and facts about the game live in the pure
# module where a test can reach them.
GUILD_VAULT_GO_TYPE = 34

# GAMEOBJECT_TYPE_SPELL_FOCUS, and the focus id a Forge answers to (infra#3748).
#
# THESE ARE TWO DIFFERENT COLUMNS AND infra#3617 READ THE WRONG ONE. That issue
# investigated the sibling anvil question and recorded: "Every 'Anvil'-named row
# is `type = 8` (GAMEOBJECT_TYPE_SPELL_FOCUS) with `data1 = 10`
# (`SPELL_FOCUS_ANVIL`). This is the same field `SpellInfo::RequiresSpellFocus`
# checks against at cast time." It is not. Counted against the live world
# database on 2026-09-13:
#
#     SELECT Data1, COUNT(*) FROM gameobject_template
#      WHERE type = 8 AND Data0 = 1 GROUP BY Data1;   -> 10:289  8:4  5:2  17:1
#     SELECT Data1, COUNT(*) FROM gameobject_template
#      WHERE type = 8 AND Data0 = 3 GROUP BY Data1;   -> 10:136  8:4  12:3
#                                                        15:2  30:2  4:1  5:1
#
# `Data0` IS THE FOCUS ID (1 Anvil, 2 Loom, 3 Forge - SpellFocusObject.dbc) and
# `Data1` IS THE RADIUS IN YARDS. Anvils and forges BOTH mostly carry Data1 =
# 10, which is why reading it as the focus id looked right: entries 1684, 1744
# and 1748 really are anvils, and really do say 10, and the 10 means ten yards.
# A query built on that misreading would return every focus object in the world
# whose radius happens to be ten - forges, anvils and looms alike - and aim a
# smelter at whichever was nearest.
SPELL_FOCUS_GO_TYPE = 8
FORGE_FOCUS_ID = 3

# HOW CLOSE AN `at:` AIM ACTUALLY LANDS A CHARACTER, mirrored from mod-overseer
# rather than guessed, and load-bearing for the whole forge walk.
#
# The travel drive hands a ground errand back once the traveller is within
# `TRAVEL_ARRIVED_POSITION_YARDS` of it (mod_overseer.cpp: `entry ?
# TRAVEL_ARRIVED_YARDS : TRAVEL_ARRIVED_POSITION_YARDS`, where `entry` is zero
# for an `at:` aim) - so "walked to the forge" means "somewhere inside five
# yards of the forge's own surveyed position", not "on top of it".
#
# THAT IS WHY THE RADIUS HAS TO BE CHECKED AND NOT ASSUMED. #3748 records the
# focus radius as 10, which is true of 136 of the 149 forge templates and false
# of the rest: one carries 4 and one carries 5. A five-yard arrival at a
# four-yard forge is a character standing just outside the focus, and CheckCast
# refuses the smelt with SPELL_FAILED_REQUIRES_SPELL_FOCUS - which DriveCraft
# logs as a bare numeric SpellCastResult at INFO, indistinguishable from a
# cooldown, and retries every twenty seconds for ever. `forge_aim` below
# refuses such a forge with a sentence instead.
#
# tests/test_travel_forge.py asserts this equals the constant in the pinned
# mod-overseer source, the same two-way mirror discipline `ROLES` already has
# against `TravelRoles()`: if the module ever loosens its arrival tolerance
# past a forge's radius, the walk stops being enough and CI says so rather than
# the family standing at a forge casting nothing.
ARRIVED_POSITION_YARDS = 5

# The prefix `ResolveTravelTarget` answers with GROUND instead of a spawn:
# `at:<map>:<x>,<y>,<z>`, parsed before the NPC index is even built, with
# `outEntry = 0` because the walk is the whole errand (mod_overseer.cpp).
GROUND_AIM_PREFIX = "at:"

# HOW MANY DECIMALS A GROUND AIM CARRIES, AND WHY IT IS NOT OUR CHOICE.
# mod-overseer writes its own `at:` aims with `std::fixed <<
# std::setprecision(1)` (the berth aim in the crossing coordinator), so one
# decimal IS the established precision of this column and matching it keeps a
# Python-written aim byte-identical in shape to a module-written one. It is
# also what makes the aims FIT: at full float precision the longest Guild
# Vault spawn in the live world renders as
#
#     at:530:-3909.75,-11548.9,-149.957     (33 characters)
#
# which is one character past COLUMN_WIDTH and would be TRUNCATED by MySQL
# outside strict mode - silently turning a real spawn into a coordinate
# nobody surveyed. At one decimal the same spawn is 30 characters and every
# one of the 41 live vault spawns fits. Rounding to a tenth of a yard is not
# hand-authoring a coordinate: the point still comes from the spawn table, and
# a tenth of a yard is two orders of magnitude inside the 5-yard interact gate
# `GuildBankInReach` judges arrival by.
GROUND_AIM_DECIMALS = 1


def resolve(text):
    """The canonical travel target named by `text`, or None.

    Accepts a role keyword, one of its aliases, or a bare creature entry.
    Returns the exact string to store in overseer_roster.travel_npc.

    Returning None rather than raising is deliberate: this is fed by chat and
    by council decisions, and "that is not somewhere I can send you" is an
    ordinary answer, not an error.
    """
    if text is None:
        return None
    cleaned = " ".join(str(text).strip().lower().split())
    if not cleaned:
        return None
    if cleaned.isdigit():
        # A creature entry. Rejecting 0 matters: it is the sentinel the
        # worldserver uses for "no creature", so an aim at entry 0 would
        # resolve to nothing and look like an aim that simply did not work.
        entry = int(cleaned)
        return str(entry) if entry > 0 else None
    if cleaned in ROLES:
        return cleaned
    return ALIASES.get(cleaned)


def is_target(value):
    """Whether `value` is something mod-overseer will act on.

    The empty string is a valid column value and is NOT a target - that is the
    cleared state - so this is not the same question as `resolve` succeeding.
    """
    return bool(value) and resolve(value) == value


def describe(value):
    """How to say the target out loud, for a log line or party chat."""
    target = resolve(value)
    if target is None:
        return "nowhere"
    if target.isdigit():
        return "creature %s" % target
    return "the nearest %s" % target


def aim_statements(names, target):
    """The writes that aim `names` at `target` and clear everyone else.

    Returned as (sql, params) pairs rather than executed, so the ordering and
    the clearing half are testable without a database. The caller runs them in
    order on one cursor.

    THE CLEARING HALF IS NOT OPTIONAL. An aim is a standing intent that
    survives a relog, and mod-playerbots re-rolls a bot's own status once the
    lease lapses - so a stale row left behind sends a character to a trainer
    nobody asked about, days later, and the party spreads. Setting the aim and
    clearing everyone else in the same pass is what makes the column say
    exactly who is travelling.
    """
    resolved = resolve(target) if target else None
    if target and resolved is None:
        raise ValueError("not a travel target: %r" % (target,))
    if resolved is not None and len(resolved) > COLUMN_WIDTH:
        raise ValueError("travel target too long for the column: %r" % (resolved,))

    chosen = sorted({str(n) for n in (names or [])})
    if not resolved or not chosen:
        return [("UPDATE overseer_roster SET travel_npc = %s "
                 "WHERE travel_npc <> %s", (NONE, NONE))]

    # `marks` is a run of "%s" placeholders whose LENGTH comes from a count of
    # names - no name and no target reaches the SQL text. Every value is bound,
    # which is what test_names_are_bound_and_never_interpolated asserts. Same
    # construction, and same suppression, as bridge._aim_traveller.
    marks = ", ".join(["%s"] * len(chosen))
    return [
        ("UPDATE overseer_roster SET travel_npc = %%s "  # noqa: S608 - placeholders from a COUNT, values still bound
         "WHERE name IN (%s)" % marks,
         (resolved, *chosen)),
        ("UPDATE overseer_roster SET travel_npc = %%s "  # noqa: S608 - placeholders from a COUNT, values still bound
         "WHERE travel_npc <> %%s AND name NOT IN (%s)" % marks,
         (NONE, NONE, *chosen)),
    ]


def is_ground_aim(value):
    """Whether `value` is an `at:<map>:<x>,<y>,<z>` aim rather than a keyword.

    Deliberately a PREFIX test and not a parse: every caller that asks this is
    asking "which kind of aim am I holding", and the authority on whether the
    coordinates are readable is `ResolveTravelTarget`, which re-parses them on
    the other side of the column anyway. A second parser here would be a
    second opinion that could drift out of step with the first.
    """
    return bool(value) and str(value).startswith(GROUND_AIM_PREFIX)


def ground_aim(map_id, x, y, z):
    """The `at:<map>:<x>,<y>,<z>` aim that walks a character to that ground.

    Returns None rather than a too-long or malformed aim, for the same reason
    mod-overseer's own berth writer refuses one: `overseer_roster.travel_npc`
    is VARCHAR(32) (`TRAVEL_AIM_COLUMN_CHARS` on that side, COLUMN_WIDTH on
    this one) and MySQL TRUNCATES rather than refuses outside strict mode. A
    truncated aim is not a failed aim - it is a DIFFERENT, plausible-looking
    coordinate that no survey ever produced, which is the one failure this
    project has already paid for in dead characters. Better to write nothing
    and say so.
    """
    if map_id is None or x is None or y is None or z is None:
        return None
    try:
        where = int(map_id)
        point = (float(x), float(y), float(z))
    except (TypeError, ValueError):
        return None
    if where < 0:
        return None
    aim = "%s%d:%s" % (
        GROUND_AIM_PREFIX, where,
        ",".join("%.*f" % (GROUND_AIM_DECIMALS, axis) for axis in point),
    )
    return aim if len(aim) <= COLUMN_WIDTH else None


@dataclass(frozen=True)
class VaultAim:
    """Either the aim that reaches a Guild Vault, or why nobody can be sent.

    Two fields rather than a bare None because the refusals are genuinely
    different situations and a person reading the log has a different thing to
    do about each: a vault on another continent is a travel problem, a vault
    nobody can see is a snapshot problem. `bool(result.aim)` is the success
    test; `refused` is a whole sentence, already actionable, never a code.
    """

    aim: str = ""
    refused: str = ""


def vault_aim(spawn, standing_on):
    """Aim a character standing on map `standing_on` at the Guild Vault `spawn`.

    `spawn` is a row from the live `gameobject` spawn table - {"map_id", "x",
    "y", "z"} - or None when nothing was found. Reading that row is the same
    resolution the module already performs for creature spawns, against the
    table the answer is actually in; it is not hand-authored geometry, and the
    z is the surveyed one that came with the spawn.

    SAME MAP ONLY, AND THE REFUSAL IS THE POINT. `MoveFarTo` paths through
    PathGenerator and there is no navmesh across an ocean, so a vault on
    another map is not a longer walk, it is not a walk. `ResolveTravelTarget`
    refuses a mismatched map on its own side too; this check exists so the
    refusal carries a sentence instead of arriving as an aim that silently
    resolves to nothing.
    """
    if standing_on is None:
        return VaultAim(refused=(
            "nobody can say which map the leader is standing on - "
            "overseer_snapshot has no fresh row for it, so the family is "
            "either offline or the module has stopped writing the snapshot"))
    if not spawn:
        return VaultAim(refused=(
            "no Guild Vault is spawned on map %s, so the family has to travel "
            "to a map that has one before any deposit can land" % standing_on))
    where = spawn.get("map_id")
    if where is None or int(where) != int(standing_on):
        return VaultAim(refused=(
            "the nearest Guild Vault is on map %s and the leader is on map %s "
            "- there is no navmesh between them, so this needs a boat, a "
            "portal or a flight before an aim can do anything" % (
                where, standing_on)))
    aim = ground_aim(where, spawn.get("x"), spawn.get("y"), spawn.get("z"))
    if not aim:
        return VaultAim(refused=(
            "the nearest Guild Vault on map %s cannot be named in the %d "
            "characters overseer_roster.travel_npc holds, so aiming at it "
            "would truncate into a coordinate nobody surveyed" % (
                where, COLUMN_WIDTH)))
    return VaultAim(aim=aim)


@dataclass(frozen=True)
class ForgeAim:
    """Either the aim that stands a character in a Forge's focus, or why not.

    THE SAME TWO-FIELD SHAPE AS `VaultAim`, AND FOR THE SAME REASON: a forge on
    another continent is a travel problem, a forge nobody can see is a snapshot
    problem, and a forge whose focus is narrower than the travel drive's own
    arrival tolerance is a mod-overseer problem - three different things for a
    person to do, so `refused` is a whole sentence rather than a code.

    `radius` IS CARRIED OUT, not just checked and dropped, because the caller
    needs it for a question this module cannot answer: "is the character ALREADY
    inside the focus", which needs a live distance the pure module never sees.
    `within_focus` below is the judgement; this is the number it judges against.
    """

    aim: str = ""
    refused: str = ""
    radius: int = 0


def forge_aim(spawn, standing_on):
    """Aim a character standing on map `standing_on` at the Forge `spawn`.

    `spawn` is a row from the live `gameobject` spawn table joined to its
    template - {"map_id", "x", "y", "z", "radius"} - or None when nothing was
    found. Every field comes out of the table the world itself was built from;
    the z is the surveyed one that shipped with the spawn, which is the whole
    reason this is a lookup and not hand-authored geometry.

    THIS IS `vault_aim` WITH ONE EXTRA REFUSAL, and the refusal is the point.
    infra#3617 parked the forge/anvil question believing a focus object could
    only be reached by indexing GameObject spawns the way creatures are indexed;
    infra#3702 had already disproved that by walking the leader to a Guild
    Vault through `ground_aim`. So the mechanism is settled and shipped. What is
    NOT settled by copying it is whether arriving is enough: a Guild Vault is
    judged by `GuildBankInReach`'s own five-yard interact gate, while a smelt is
    judged by the FORGE's `Data1` radius, which varies from 4 to 30 across this
    world's 149 forge templates. Arriving within `ARRIVED_POSITION_YARDS` of a
    four-yard forge puts the character outside the focus, and the refusal that
    follows is one DriveCraft cannot tell from a cooldown. Better to say so.
    """
    if standing_on is None:
        return ForgeAim(refused=(
            "nobody can say which map the smelter is standing on - "
            "overseer_snapshot has no fresh row for it, so the family is "
            "either offline or the module has stopped writing the snapshot"))
    if not spawn:
        return ForgeAim(refused=(
            "no Forge whose focus is wider than the %d-yard arrival tolerance "
            "is spawned on map %s, so nothing can be smelted there until the "
            "family travels to a map that has one" % (
                ARRIVED_POSITION_YARDS, standing_on)))
    where = spawn.get("map_id")
    if where is None or int(where) != int(standing_on):
        return ForgeAim(refused=(
            "the nearest Forge is on map %s and the smelter is on map %s - "
            "there is no navmesh between them, so this needs a boat, a portal "
            "or a flight before an aim can do anything" % (where, standing_on)))
    radius = int(spawn.get("radius") or 0)
    if radius <= ARRIVED_POSITION_YARDS:
        # RE-CHECKED HERE THOUGH THE QUERY ALREADY FILTERS ON IT, exactly as
        # `vault_aim` re-checks the same-map rule `_VAULT_SQL`'s own JOIN
        # enforces. The query decides which spawn is a candidate; this decides
        # what to SAY when there is none, and a sentence a person can act on is
        # worth more than a row that silently did not match.
        return ForgeAim(refused=(
            "the nearest Forge on map %s has a %d-yard focus and the travel "
            "drive only promises to land a character within %d yards of an "
            "`at:` aim, so walking there would not reliably put the smelter "
            "inside the focus - and CheckCast's refusal for that is one "
            "DriveCraft logs as a bare SpellCastResult, not as a distance" % (
                where, radius, ARRIVED_POSITION_YARDS)))
    aim = ground_aim(where, spawn.get("x"), spawn.get("y"), spawn.get("z"))
    if not aim:
        return ForgeAim(refused=(
            "the nearest Forge on map %s cannot be named in the %d characters "
            "overseer_roster.travel_npc holds, so aiming at it would truncate "
            "into a coordinate nobody surveyed" % (where, COLUMN_WIDTH)))
    return ForgeAim(aim=aim, radius=radius)


def within_focus(spawn) -> bool:
    """Is the character this spawn row was measured for already in the focus?

    `spawn` carries `d2`, the SQUARE of the planar distance from the character
    to the spawn - squared because that is what the query sorts on and taking a
    root to compare against a squared threshold would be arithmetic for its own
    sake (`_VAULT_SQL`'s own comment makes the same argument).

    JUDGED AGAINST THE FORGE'S OWN RADIUS AND NOT A CONSTANT OF OURS. A caller
    might reasonably reach for `TOWN_COUNTER_YARDS` here the way the guild bank
    pass does for a vault, and it would be wrong in both directions: 8 is
    outside a 4-yard forge and needlessly inside a 30-yard one. The radius IS
    the game's own rule for whether `CheckCast` passes, so it is the only
    honest threshold, and reading it per spawn is free - the template row is
    already joined for the query that found the spawn.

    False for a row that cannot answer - no distance, no radius - because the
    fail-closed reading of "I do not know whether they are close enough" is to
    walk them there, which costs a walk, rather than to skip the walk and let
    the cast be refused for ever.
    """
    if not spawn:
        return False
    near = spawn.get("d2")
    radius = spawn.get("radius")
    if near is None or not radius:
        return False
    return float(near) <= float(radius) ** 2
