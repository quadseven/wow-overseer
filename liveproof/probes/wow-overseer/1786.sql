-- ticket: 1786
-- repo: quadseven/wow-overseer
-- 1786: craft at a forge. Proven: a smelt cast (spell 2657) applied or delivered since 22:00Z
-- 11-05 and no focus refusal. Disproven: a Requires Forge or focus refusal on a smelt row.
SELECT '1786' AS ticket,
  CASE WHEN s.refusals > 0 THEN 'disproven'
       WHEN s.smelts > 0 THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('smelt_2657_rows_ok=', s.smelts, ' focus_refusals=', s.refusals) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.kind = 'cast' AND c.command REGEXP '(^|[^0-9])2657($|[^0-9])'
      AND c.status IN ('applied', 'delivered') AND c.created_at >= '2026-11-05 22:00:00') AS smelts,
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.kind = 'cast' AND c.command REGEXP '(^|[^0-9])2657($|[^0-9])'
      AND c.status = 'error' AND c.created_at >= '2026-11-05 22:00:00'
      AND (c.detail LIKE '%Requires Forge%' OR c.detail LIKE '%focus%')) AS refusals
) s;
