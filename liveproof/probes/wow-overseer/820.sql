-- ticket: 820
-- repo: quadseven/wow-overseer
-- 820 Jev scorecard: 7-day shadow numbers. Proven: non-Jev model rows since the #1633 merge span 7 days or more.
-- Disproven: no such rows, or they stop early (span under 7 days and last row older than 1 day).
-- The Jev model name is not known, so any model containing 'jev' is excluded.
SELECT '820' AS ticket,
       CASE WHEN t.n > 0 AND TIMESTAMPDIFF(SECOND, t.first_row, t.last_row) >= 604800 THEN 'proven'
            WHEN t.n = 0 THEN 'disproven'
            WHEN t.n > 0 AND TIMESTAMPDIFF(SECOND, t.first_row, t.last_row) < 604800
                 AND t.last_row < NOW() - INTERVAL 1 DAY THEN 'disproven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('rows=', t.n, ' agreed=', COALESCE(t.agreed, 0), ' not_answered=', COALESCE(t.bad, 0),
              ' avg_ms=', COALESCE(t.avg_ms, 'NA'), ' first=', COALESCE(t.first_row, 'NA'),
              ' last=', COALESCE(t.last_row, 'NA'), ' models=', COALESCE(t.models, 'none')) AS evidence
FROM (SELECT COUNT(*) AS n, SUM(agree = 1) AS agreed, SUM(status <> 'answered') AS bad,
             ROUND(AVG(latency_ms)) AS avg_ms, MIN(created_at) AS first_row, MAX(created_at) AS last_row,
             GROUP_CONCAT(DISTINCT model) AS models
      FROM acore_characters.overseer_jev_judgment
      WHERE created_at >= '2026-10-29 02:38:20' AND model <> '' AND LOWER(model) NOT LIKE '%jev%') t;
