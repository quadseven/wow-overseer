-- ticket: 1906
-- repo: quadseven/wow-overseer
-- 1906: death-loop count against the 2026-11-07 baseline. A loop is a member and zone with 3 or
-- more deaths inside 3 hours. Proven: the 24 hours after 2026-11-08 01:00Z are over and loops are
-- fewer than the 2026-11-07 day. Disproven: loops already equal or exceed the baseline.
SELECT '1906' AS ticket,
  CASE WHEN s.baseline > 0 AND s.after_ship >= s.baseline THEN 'disproven'
       WHEN s.baseline > 0 AND s.after_ship < s.baseline AND UTC_TIMESTAMP() >= '2026-11-09 01:00:00' THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('loops_2026-11-07=', s.baseline, ' loops_2026-11-08_0100_to_2026-11-09_0100=', s.after_ship) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM (
     SELECT DISTINCT d1.character_name, d1.zone FROM acore_characters.overseer_death d1
     WHERE d1.created_at >= '2026-11-07 00:00:00' AND d1.created_at < '2026-11-08 00:00:00'
       AND (SELECT COUNT(*) FROM acore_characters.overseer_death d2
            WHERE d2.character_name = d1.character_name AND d2.zone = d1.zone
              AND d2.created_at >= d1.created_at
              AND d2.created_at < d1.created_at + INTERVAL 3 HOUR) >= 3) x) AS baseline,
  (SELECT COUNT(*) FROM (
     SELECT DISTINCT d1.character_name, d1.zone FROM acore_characters.overseer_death d1
     WHERE d1.created_at >= '2026-11-08 01:00:00' AND d1.created_at < '2026-11-09 01:00:00'
       AND (SELECT COUNT(*) FROM acore_characters.overseer_death d2
            WHERE d2.character_name = d1.character_name AND d2.zone = d1.zone
              AND d2.created_at >= d1.created_at
              AND d2.created_at < d1.created_at + INTERVAL 3 HOUR) >= 3) x) AS after_ship
) s;
