-- ticket: 2062
-- repo: quadseven/wow-overseer
-- 2062: BRD in-run bag evacuation. Proven: a map 230 run since roll 103 (13:45Z) ended without
-- 'evacuated' and a bag-related run event exists (the strand-warning log half is not visible here).
-- Disproven: any map 230 run since 13:45Z with outcome evacuated.
SELECT '2062' AS ticket,
  CASE WHEN s.evacuated > 0 THEN 'disproven'
       WHEN s.runs > 0 AND s.bag_events > 0 THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('map230_runs_since_roll=', s.runs, ' evacuated=', s.evacuated, ' bag_events=', s.bag_events) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run r
    WHERE r.map_id = 230 AND r.started_at >= '2026-11-08 13:45:00') AS runs,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run r
    WHERE r.map_id = 230 AND r.started_at >= '2026-11-08 13:45:00' AND r.outcome = 'evacuated') AS evacuated,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run_event e
    JOIN acore_characters.overseer_dungeon_run r ON r.id = e.run_id
    WHERE r.map_id = 230 AND e.created_at >= '2026-11-08 13:45:00'
      AND (e.detail LIKE '%bag%' OR e.detail LIKE '%evacuat%')) AS bag_events
) s;
