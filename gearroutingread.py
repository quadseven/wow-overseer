"""The reads behind the guild gear-routing pass (gearrouting.py).

Shared by the site (map_server.py) and, next, the bridge, so both build the
routing report from the same rows. DB-free: the SQL is data, and `read` takes
any session with realmread.Session's `rows` method, so the planner stays pure.
"""

from __future__ import annotations

import os

import raidroles

# WHAT THE GUILD ROUTING PASS READS (gearrouting.py): every member of every
# family guild - not only the families themselves. The wearer facts
# equipscore.wearer_from_row reads, the scored gear of the bridge's equip
# read (bridge._SCORED_GEAR_SQL's columns) plus the two binding facts the
# routing turns on - the template's bonding and the instance's flags,
# because a bind-on-equip copy somebody wore is bound whatever its template
# says - and the guild banks' gear under the holder label the bridge's own
# bank reads use ('guild bank'). The guilds are the families' guilds, found
# the way _GUILD_GEAR finds them.
GUILDS = (
    "g.guildid IN (SELECT gm2.guildid FROM guild_member gm2 "
    "JOIN characters c2 ON c2.guid = gm2.guid WHERE c2.name IN ({holes}))"
)
RAID_TREE = "(SELECT s.tree FROM overseer_raid_spec s WHERE s.name = c.name LIMIT 1)"
WEARERS = (
    "SELECT g.name AS guild, c.name AS name, c.class AS class_id, "  # noqa: S608 - SQL fragments are constants; values use placeholders
    "c.level AS level, c.race AS race, " + raidroles.TALENTS_COLUMN + ", "
    "{target} AS target_tree, "
    "(SELECT GROUP_CONCAT(k.skill) FROM character_skills k "
    "WHERE k.guid = c.guid AND k.value > 0) AS skills "
    "FROM guild g JOIN guild_member gm ON gm.guildid = g.guildid "
    "JOIN characters c ON c.guid = gm.guid "
    "WHERE " + GUILDS
)
ITEM_COLUMNS = (
    "ii.guid AS item_guid, ii.itemEntry AS entry, "
    "ii.randomPropertyId AS random_property_id, ii.enchantments AS enchantments, "
    "ii.flags AS instance_flags, "
    "it.name AS name, it.Quality AS quality, it.ItemLevel AS item_level, "
    "it.RequiredLevel AS required_level, it.class AS item_class, "
    "it.subclass AS item_subclass, it.InventoryType AS inventory_type, "
    "it.bonding AS bonding, "
    "it.AllowableClass AS allowable_class, it.AllowableRace AS allowable_race, "
    "it.RequiredSkill AS required_skill, "
    "it.RequiredSkillRank AS required_skill_rank, "
    "it.requiredspell AS required_spell, "
    "it.RequiredReputationFaction AS required_reputation, "
    "it.MaxCount AS max_count, it.Flags AS item_flags, "
    "it.armor, it.block, it.fire_res, it.frost_res, it.nature_res, "
    "it.shadow_res, it.arcane_res, it.dmg_min1, it.dmg_max1, it.delay, "
    + ", ".join("it.stat_type%d, it.stat_value%d" % (n, n) for n in range(1, 11))
    + ", "
    + ", ".join(f"it.spellid_{n}, it.spelltrigger_{n}" for n in range(1, 6))
)
GEAR_KINDS = (
    "it.class IN (2, 4) AND it.InventoryType IN (1, 2, 3, 5, 6, 7, 8, 9, 10, "
    "11, 12, 13, 14, 15, 16, 17, 20, 21, 22, 23, 25, 26, 28)"
)
GEAR = (
    "SELECT c.name AS holder, g.name AS guild, "  # noqa: S608 - SQL fragments are constants; values use placeholders
    "IF(ci.bag = 0 AND ci.slot < 19, ci.slot, NULL) AS equipment_slot, "
    + ITEM_COLUMNS
    + " FROM guild g JOIN guild_member gm ON gm.guildid = g.guildid "
    "JOIN characters c ON c.guid = gm.guid "
    "JOIN character_inventory ci ON ci.guid = c.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE " + GUILDS + " AND ((ci.bag = 0 AND ci.slot < 19) "
    "OR (ci.bag = 0 AND ci.slot BETWEEN 19 AND 38) "
    "OR ci.bag IN (SELECT bag.item FROM character_inventory bag "
    "WHERE bag.guid = ci.guid AND bag.bag = 0 AND bag.slot BETWEEN 19 AND 22)) "
    "AND " + GEAR_KINDS
)
BANK = (
    "SELECT 'guild bank' AS holder, g.name AS guild, "  # noqa: S608 - SQL fragments are constants; values use placeholders
    "NULL AS equipment_slot, "
    + ITEM_COLUMNS
    + " FROM guild g JOIN guild_bank_item gbi ON gbi.guildid = g.guildid "
    "JOIN item_instance ii ON ii.guid = gbi.item_guid "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE " + GUILDS + " AND " + GEAR_KINDS
)

# The owner's never-dispose marks, from the same environment variable the
# bridge's OWNER_KEEPS reads (bridge.py): one hand brake, two readers, and
# a marked piece is never routed even in a dry run.
KEEPS = tuple(
    part.strip()
    for part in os.environ.get("OWNER_KEEPS", "").split(",")
    if part.strip()
)


def read(rd, names) -> tuple:
    """(wearers, gear, bank) rows for the guilds `names` belong to.

    A world without the raid-spec table reads the spent talents alone, the
    bridge's own fallback.
    """
    holes = ", ".join(["%s"] * len(names))
    params = tuple(names)
    wearers = rd.rows(
        WEARERS.format(holes=holes, target=RAID_TREE),  # noqa: S608 - holes is a generated placeholder list; names are bound
        params,
        fallback=WEARERS.format(holes=holes, target="''"),  # noqa: S608 - holes is a generated placeholder list; names are bound
        what="routing wearers",
    )
    gear = rd.rows(
        GEAR.format(holes=holes),  # noqa: S608 - holes is a generated placeholder list; names are bound
        params,
        what="routing gear",
    )
    bank = rd.rows(
        BANK.format(holes=holes),  # noqa: S608 - holes is a generated placeholder list; names are bound
        params,
        what="guild_bank_item routing",
    )
    return wearers, gear, bank
