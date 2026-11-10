-- ticket: 2058
-- repo: quadseven/wow-overseer
-- 2058: operator BRD order survives. Proven: an operator row (source web:overseer, id 145 or later)
-- that reached active or done. Disproven: operator rows exist, each cancelled within 45 seconds of
-- creation, none survived.
SELECT '2058' AS ticket,
  CASE WHEN s.ran > 0 THEN 'proven'
       WHEN s.early_cancel > 0 AND s.survived = 0 THEN 'disproven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('operator_rows=', s.op_rows, ' ran_active_or_done=', s.ran, ' survived_45s=', s.survived,
         ' cancelled_within_45s=', s.early_cancel) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue q
    WHERE q.keyword LIKE 'blackrock-depths%' AND q.id >= 145 AND q.source = 'web:overseer') AS op_rows,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue q
    WHERE q.keyword LIKE 'blackrock-depths%' AND q.id >= 145 AND q.source = 'web:overseer'
      AND q.status IN ('active', 'done')) AS ran,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue q
    WHERE q.keyword LIKE 'blackrock-depths%' AND q.id >= 145 AND q.source = 'web:overseer'
      AND (q.status IN ('queued', 'active', 'done')
           OR TIMESTAMPDIFF(SECOND, q.created_at, q.finished_at) > 45)) AS survived,
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue q
    WHERE q.keyword LIKE 'blackrock-depths%' AND q.id >= 145 AND q.source = 'web:overseer'
      AND q.status = 'cancelled'
      AND TIMESTAMPDIFF(SECOND, q.created_at, q.finished_at) <= 45) AS early_cancel
) s;
