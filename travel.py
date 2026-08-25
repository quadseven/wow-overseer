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
"""

# Canonical keyword -> the UNIT_NPC_FLAG_* the module matches spawns on.
#
# Every flag here is in mod-playerbots' own allowed-RPG-target list at the
# pinned module SHA, so a character standing in front of one of these is a
# state the rest of the RPG layer already expects and handles.
ROLES = {
    "trainer": "UNIT_NPC_FLAG_TRAINER",
    "class trainer": "UNIT_NPC_FLAG_TRAINER_CLASS",
    "profession trainer": "UNIT_NPC_FLAG_TRAINER_PROFESSION",
    "vendor": "UNIT_NPC_FLAG_VENDOR",
    "repair": "UNIT_NPC_FLAG_REPAIR",
    "banker": "UNIT_NPC_FLAG_BANKER",
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
