-- ticket: 815
-- repo: quadseven/wow-overseer
-- 815 Crossings box 2. Proven: a ride-to-stop row applied for a Horde member whose snapshot is on map 0, zone 33.
-- Disproven: no applied ride-to-stop row at all, and rows created after the 2026-11-08 12:03 ship ended refused or errored.
SELECT '815' AS ticket,
       CASE WHEN t.applied_horde_in_zone33 > 0 THEN 'proven'
            WHEN t.applied_any = 0 AND t.refused_post_ship > 0 THEN 'disproven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('ride_to_stop_rows=', t.total, ' applied=', t.applied_any,
              ' applied_horde_now_map0_zone33=', t.applied_horde_in_zone33,
              ' refused_after_ship=', t.refused_post_ship) AS evidence
FROM (SELECT
        (SELECT COUNT(*) FROM acore_characters.overseer_command
          WHERE command LIKE 'ride-to-stop%') AS total,
        (SELECT COUNT(*) FROM acore_characters.overseer_command
          WHERE command LIKE 'ride-to-stop%' AND status = 'applied') AS applied_any,
        (SELECT COUNT(*) FROM acore_characters.overseer_command c
          JOIN acore_characters.overseer_snapshot s
            ON s.name COLLATE utf8mb4_unicode_ci = c.target_name COLLATE utf8mb4_unicode_ci
          WHERE c.command LIKE 'ride-to-stop%' AND c.status = 'applied'
            AND s.race IN (2, 5, 6, 8, 10) AND s.map_id = 0 AND s.zone_id = 33) AS applied_horde_in_zone33,
        (SELECT COUNT(*) FROM acore_characters.overseer_command
          WHERE command LIKE 'ride-to-stop%' AND created_at >= '2026-11-08 12:03:00'
            AND status NOT IN ('applied', 'pending', 'claimed', 'verifying', 'delivered')) AS refused_post_ship) t;
