-- ticket: 1590
-- repo: quadseven/wow-overseer
-- 1590: hammer buy. Proven: a smith has exactly one buy row for item 5956 since 04:02Z 10-28 and an
-- event row for spell 2666 since then. Disproven needs a smith's job duration, which SQL cannot read,
-- so none here.
SELECT '1590' AS ticket,
  CASE WHEN s.smiths_ok > 0 THEN 'proven' ELSE 'no_evidence' END AS verdict,
  CONCAT('smiths_with_exactly_one_5956_buy_and_2666_event=', s.smiths_ok, ' buy_rows_5956=', s.buys,
         ' events_2666=', s.events) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM (
     SELECT c.target_name FROM acore_characters.overseer_command c
     WHERE c.kind = 'buy' AND c.command REGEXP '(^|[^0-9])5956($|[^0-9])'
       AND c.created_at >= '2026-10-28 04:02:00'
     GROUP BY c.target_name HAVING COUNT(*) = 1) b
   WHERE EXISTS (SELECT 1 FROM acore_characters.overseer_event e
                 WHERE e.character_name = b.target_name COLLATE utf8mb4_unicode_ci
                   AND e.subject_id = 2666 AND e.first_seen >= '2026-10-28 04:02:00')) AS smiths_ok,
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.kind = 'buy' AND c.command REGEXP '(^|[^0-9])5956($|[^0-9])'
      AND c.created_at >= '2026-10-28 04:02:00') AS buys,
  (SELECT COUNT(*) FROM acore_characters.overseer_event e
    WHERE e.subject_id = 2666 AND e.first_seen >= '2026-10-28 04:02:00') AS events
) s;
