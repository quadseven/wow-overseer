-- ticket: 1897
-- repo: quadseven/wow-overseer
-- 1897: raid-supply cooking. Proven: a member has one campfire (spell 818) cast row followed by two
-- or more other cast rows from raidsupply within 30 minutes. Disproven: three or more errored 818
-- rows and no such batch.
SELECT '1897' AS ticket,
  CASE WHEN s.good_batches > 0 THEN 'proven'
       WHEN s.refused_818 >= 3 THEN 'disproven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('campfire_batches_with_2plus_casts=', s.good_batches, ' refused_818_rows=', s.refused_818,
         ' raidsupply_casts_since_ship=', s.casts) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_command c1
    WHERE c1.source LIKE 'raidsupply%' AND c1.kind = 'cast' AND c1.status IN ('applied', 'delivered')
      AND c1.command REGEXP '(^|[^0-9])818($|[^0-9])' AND c1.created_at >= '2026-11-06 00:03:00'
      AND (SELECT COUNT(*) FROM acore_characters.overseer_command c2
           WHERE c2.target_name = c1.target_name AND c2.kind = 'cast' AND c2.source LIKE 'raidsupply%'
             AND c2.status IN ('applied', 'delivered') AND c2.id > c1.id
             AND c2.created_at <= c1.created_at + INTERVAL 30 MINUTE
             AND NOT (c2.command REGEXP '(^|[^0-9])818($|[^0-9])')) >= 2) AS good_batches,
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.source LIKE 'raidsupply%' AND c.kind = 'cast' AND c.status = 'error'
      AND c.command REGEXP '(^|[^0-9])818($|[^0-9])' AND c.created_at >= '2026-11-06 00:03:00') AS refused_818,
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.source LIKE 'raidsupply%' AND c.kind = 'cast' AND c.status IN ('applied', 'delivered')
      AND c.created_at >= '2026-11-06 00:03:00') AS casts
) s;
