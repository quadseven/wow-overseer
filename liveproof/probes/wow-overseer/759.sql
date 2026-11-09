-- ticket: 759
-- repo: quadseven/wow-overseer
-- 759 Tank fire resistance road, box 3 only (box 2 is a bridge log line, see NOT RUNNABLE note below).
-- Proven: a Grug level_up to 55 exists and his worn fire resistance is above 0.
-- Disproven: that level_up is more than 7 days old and worn fire resistance is still 0.
SELECT '759' AS ticket,
       CASE WHEN t.lvl55 > 0 AND t.fire_worn > 0 THEN 'proven'
            WHEN t.lvl55 > 0 AND t.lvl55_last < NOW() - INTERVAL 7 DAY AND t.fire_worn = 0 THEN 'disproven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('Grug_level_up_rows_55=', t.lvl55, ' max_level_up_seen=', COALESCE(t.max_level, 'NA'),
              ' worn_fire_res=', t.fire_worn) AS evidence
FROM (SELECT
        (SELECT COUNT(*) FROM acore_characters.overseer_event
          WHERE kind = 'level_up' AND character_name = 'Grug' AND subject_id = 55) AS lvl55,
        (SELECT MAX(last_seen) FROM acore_characters.overseer_event
          WHERE kind = 'level_up' AND character_name = 'Grug' AND subject_id = 55) AS lvl55_last,
        (SELECT MAX(subject_id) FROM acore_characters.overseer_event
          WHERE kind = 'level_up' AND character_name = 'Grug') AS max_level,
        (SELECT COALESCE(SUM(it.fire_res), 0) FROM acore_characters.characters c
          JOIN acore_characters.character_inventory ci ON ci.guid = c.guid AND ci.bag = 0 AND ci.slot < 19
          JOIN acore_characters.item_instance ii ON ii.guid = ci.item
          JOIN acore_world.item_template it ON it.entry = ii.itemEntry
          WHERE c.name = 'Grug') AS fire_worn) t;
