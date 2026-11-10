-- ticket: 2045
-- repo: quadseven/wow-overseer
-- 2045: the next BRD run of each family with an operator order starts before 08:36Z, with no
-- step_down or stall_out pace row tied to an operator order since 06:36Z.
SELECT '2045' AS ticket,
  CASE WHEN s.pace_bad > 0 THEN 'disproven'
       WHEN s.fams_ordered > 0 AND s.fams_ran = s.fams_ordered THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('families_with_operator_brd_order=', s.fams_ordered, ' families_run_started_before_0836=', s.fams_ran,
         ' pace_step_down_or_stall_out_on_operator_order=', s.pace_bad) AS evidence
FROM (SELECT
  (SELECT COUNT(DISTINCT q.family) FROM acore_characters.overseer_dungeon_queue q
    WHERE q.keyword LIKE 'blackrock-depths%' AND q.id >= 145 AND q.source = 'web:overseer') AS fams_ordered,
  (SELECT COUNT(DISTINCT q.family) FROM acore_characters.overseer_dungeon_queue q
    WHERE q.keyword LIKE 'blackrock-depths%' AND q.id >= 145 AND q.source = 'web:overseer'
      AND EXISTS (SELECT 1 FROM acore_characters.overseer_dungeon_run r
                  JOIN acore_characters.overseer_roster ro
                    ON ro.name = r.leader_name COLLATE utf8mb4_unicode_ci
                  WHERE ro.family = q.family COLLATE utf8mb4_unicode_ci
                    AND r.map_id = 230
                    AND r.started_at >= '2026-11-08 06:36:00'
                    AND r.started_at < '2026-11-08 08:36:00')) AS fams_ran,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_pace p
    JOIN acore_characters.overseer_dungeon_queue q ON q.id = p.queue_id
    WHERE p.created_at >= '2026-11-08 06:36:00' AND p.decision IN ('step_down', 'stall_out')
      AND q.source = 'web:overseer') AS pace_bad
) s;
