-- ticket: 783
-- repo: quadseven/wow-overseer
-- 783 BRD guild run ends at first boss. Finished runs exclude outcome '' and 'reset_failed' (the 7 known rows are reset_failed: no evidence).
-- Proven: average bosses_done above 1. Disproven: finished runs exist and none got past 1 boss.
SELECT '783' AS ticket,
       CASE WHEN t.finished > 0 AND t.avg_bosses > 1 THEN 'proven'
            WHEN t.finished > 0 AND t.max_bosses <= 1 THEN 'disproven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('brd_rows=', t.total, ' finished_not_reset_failed=', t.finished,
              ' avg_bosses=', COALESCE(ROUND(t.avg_bosses, 2), 'NA'),
              ' max_bosses=', COALESCE(t.max_bosses, 'NA')) AS evidence
FROM (SELECT COUNT(*) AS total,
             SUM(outcome NOT IN ('', 'reset_failed')) AS finished,
             AVG(CASE WHEN outcome NOT IN ('', 'reset_failed') THEN bosses_done END) AS avg_bosses,
             MAX(CASE WHEN outcome NOT IN ('', 'reset_failed') THEN bosses_done END) AS max_bosses
      FROM acore_characters.overseer_guild_run
      WHERE keyword = 'blackrock-depths') t;
