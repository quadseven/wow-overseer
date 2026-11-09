-- ticket: 1962
-- repo: quadseven/wow-overseer
-- 1962: refused sale rows (kind sell, status error) in the 24 hours after the 01:30Z 11-08 ship
-- against the 24 hours before it. Proven: the window is over and refusals are at most half of
-- the baseline. Disproven: refusals already exceed half of the baseline.
SELECT '1962' AS ticket,
  CASE WHEN s.base_n > 0 AND s.post_n * 2 > s.base_n THEN 'disproven'
       WHEN s.base_n > 0 AND s.post_n * 2 <= s.base_n AND UTC_TIMESTAMP() >= '2026-11-09 01:30:00' THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('refused_sell_rows_baseline_24h=', s.base_n, ' refused_sell_rows_after_ship_24h=', s.post_n) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.kind = 'sell' AND c.status = 'error'
      AND c.created_at >= '2026-11-07 01:30:00' AND c.created_at < '2026-11-08 01:30:00') AS base_n,
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.kind = 'sell' AND c.status = 'error'
      AND c.created_at >= '2026-11-08 01:30:00' AND c.created_at < '2026-11-09 01:30:00') AS post_n
) s;
