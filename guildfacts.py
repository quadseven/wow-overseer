"""The member read behind a guild run, shared by the bridge's planner and the
decree console's guild run order.

One statement, because the console must seat a run from the same facts the
planner does or it would be a second judgement of who is free. The bridge
keeps `_GUILD_RUN_MEMBERS_SQL` as a name for it.
"""

import campaignplan
import raidroles
import standin

MEMBERS_SQL = (
    "SELECT s.name, s.level, s.class AS class_id, s.map_id, s.in_combat, s.health, "  # noqa: S608 - only the guild placeholder list is formatted in; values stay bound
    "s.race, s.zone_id, s.pos_x, s.pos_y, "
    "(SELECT AVG(it.ItemLevel) FROM character_inventory ci "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    # The shirt and the tabard (slots 3 and 18) carry no stats and are item
    # level 1, so counting them pulled a member under the gate for wearing a
    # shirt; gearup.stale_gear leaves them out the same way.
    "WHERE ci.guid = s.guid AND ci.bag = 0 AND ci.slot < 19 "
    "AND ci.slot NOT IN (3, 18)) AS gear_ilvl, "
    # The coverage gate (guildrun.covered): the 8 body-armor slots (head 0,
    # shoulders 2, chest 4, waist 5, legs 6, feet 7, wrists 8, hands 9), and
    # the main hand (15).
    "(SELECT COUNT(*) FROM character_inventory ci WHERE ci.guid = s.guid "
    "AND ci.bag = 0 AND ci.slot IN (0, 2, 4, 5, 6, 7, 8, 9)) AS worn_slots, "
    "EXISTS (SELECT 1 FROM character_inventory ci WHERE ci.guid = s.guid "
    "AND ci.bag = 0 AND ci.slot = 15) AS has_weapon, "
    # A shield in the off hand (slot 16, armor subclass 6), for guildrun.tank_ready.
    "EXISTS (SELECT 1 FROM character_inventory ci JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry WHERE ci.guid = s.guid "
    "AND ci.bag = 0 AND ci.slot = 16 AND it.class = 4 AND it.subclass = 6) AS has_shield, "
    # The spell its class tanks with (raidroles.TANK_KIT), for guildrun.tank_ready.
    + raidroles.TANK_KIT_COLUMN
    + ", "
    # The door keys it carries (campaignplan.KEY_ITEMS), for a keyed wing's seat
    # (guildrun.opens_for, #785): its bags and key ring, never the bank (bank
    # slots 39 to 73, and the bags in them), as the dungeon brain's
    # HasItemCount reads them.
    "(SELECT GROUP_CONCAT(DISTINCT ii.itemEntry) FROM character_inventory ci "
    "JOIN item_instance ii ON ii.guid = ci.item WHERE ci.guid = s.guid "
    "AND ii.itemEntry IN ("
    + ", ".join(str(int(k)) for k in campaignplan.KEY_ITEMS)
    + ") "
    "AND ((ci.bag = 0 AND ci.slot NOT BETWEEN 39 AND 73) OR ci.bag IN ("
    "SELECT b.item FROM character_inventory b WHERE b.guid = s.guid AND b.bag = 0 "
    "AND b.slot BETWEEN 19 AND 22))) AS door_keys, "
    # Its Lockpicking, for a locked gate's seat (standin.LOCKS, #2056).
    "(SELECT MAX(lp.value) FROM character_skills lp WHERE lp.guid = s.guid "
    "AND lp.skill = " + str(int(standin.LOCKPICKING)) + ") AS lockpicking, "
    # IN THE WORLD IS A FRESH SNAPSHOT, NOT characters.online. The flag reads
    # 0 for random bots that are in the world (8 guild members flipped to 0 at
    # once on the dev realm while their snapshots kept updating), and the
    # snapshot is written only for characters in the world.
    "s.group_leader, g.name AS guild_name, "
    "(s.updated_at > NOW() - INTERVAL 60 SECOND) AS online, "
    "EXISTS (SELECT 1 FROM corpse k WHERE k.guid = s.guid) AS has_corpse, "
    + raidroles.TALENTS_COLUMN
    + " "
    "FROM overseer_snapshot s JOIN characters c ON c.guid = s.guid "
    "JOIN guild g ON g.guildid = s.guild_id "
    "WHERE s.updated_at > NOW() - INTERVAL 60 SECOND AND s.is_bot = 1 "
    "AND g.name IN ({holes})"
)
