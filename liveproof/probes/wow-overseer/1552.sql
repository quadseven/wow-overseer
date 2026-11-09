-- ticket: 1552
-- repo: quadseven/wow-overseer
-- 1552: Zul'Farrak (map 209) reset. Proven: no reset_failed or reset-failure event on map 209 since
-- roll 103 (13:45Z) and either two or more map 209 runs (a later run implies the reset worked) or
-- one run and 24 hours passed. Disproven: a map 209 run with outcome reset_failed, or a reset-failure
-- event on a map 209 run, since 13:45Z.
SELECT '1552' AS ticket,
  CASE WHEN s.failed_runs > 0 OR s.failure_events > 0 THEN 'disproven'
       WHEN s.runs >= 2 THEN 'proven'
       WHEN s.runs >= 1 AND UTC_TIMESTAMP() >= '2026-11-09 13:45:00' THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('map209_runs_since_roll=', s.runs, ' reset_failed_runs=', s.failed_runs,
         ' reset_failure_events=', s.failure_events) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run r
    WHERE r.map_id = 209 AND r.started_at >= '2026-11-08 13:45:00') AS runs,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run r
    WHERE r.map_id = 209 AND r.started_at >= '2026-11-08 13:45:00' AND r.outcome = 'reset_failed') AS failed_runs,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run_event e
    JOIN acore_characters.overseer_dungeon_run r ON r.id = e.run_id
    WHERE r.map_id = 209 AND e.created_at >= '2026-11-08 13:45:00'
      AND e.detail LIKE '%reset%' AND (e.detail LIKE '%fail%' OR e.detail LIKE '%could not%')) AS failure_events
) s;
