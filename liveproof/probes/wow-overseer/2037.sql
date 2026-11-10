-- ticket: 2037
-- repo: quadseven/wow-overseer
-- 2037: same proof as 2060 (fix is #2061, live since 12:03Z).
SELECT '2037' AS ticket,
  CASE WHEN s.stalled_low_mana > 0 THEN 'disproven'
       WHEN s.gerstahn_clean > 0 THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('runs_since_ship=', s.runs, ' stalled_low_mana=', s.stalled_low_mana,
         ' gerstahn_runs_without_low_mana=', s.gerstahn_clean) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run r
    WHERE r.started_at >= '2026-11-08 12:03:00') AS runs,
  (SELECT COUNT(DISTINCT r.id) FROM acore_characters.overseer_dungeon_run r
    JOIN acore_characters.overseer_dungeon_run_event e ON e.run_id = r.id
    WHERE r.started_at >= '2026-11-08 12:03:00' AND r.outcome = 'stalled'
      AND e.detail LIKE '%low mana%') AS stalled_low_mana,
  (SELECT COUNT(DISTINCT r.id) FROM acore_characters.overseer_dungeon_run r
    WHERE r.started_at >= '2026-11-08 12:03:00' AND r.map_id = 230
      AND EXISTS (SELECT 1 FROM acore_characters.overseer_dungeon_run_summary m
                  WHERE m.run_id = r.id AND m.kind = 'boss_kill' AND m.subject_name LIKE '%Gerstahn%')
      AND NOT EXISTS (SELECT 1 FROM acore_characters.overseer_dungeon_run_event e
                      WHERE e.run_id = r.id AND e.detail LIKE '%low mana%')) AS gerstahn_clean
) s;
