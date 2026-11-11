-- ticket: 1882
-- repo: quadseven/wow-overseer
-- 1882: Dustwallow Marsh death loops (health endpoint proxy). Proven: from 2026-11-09 10:27Z, no
-- member has 3 or more zone 15 deaths inside any 1-hour window since 2026-11-08 10:27Z.
-- Disproven: such a loop exists.
SELECT '1882' AS ticket,
  CASE WHEN s.loops > 0 THEN 'disproven'
       WHEN UTC_TIMESTAMP() >= '2026-11-09 10:27:00' AND s.dw_deaths > 0 THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('members_with_3_dustwallow_deaths_in_1h=', s.loops, ' dustwallow_deaths_since_1027=', s.dw_deaths) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM (
     SELECT DISTINCT d1.character_name FROM acore_characters.overseer_death d1
     WHERE d1.zone = 15 AND d1.created_at >= '2026-11-08 10:27:00'
       AND (SELECT COUNT(*) FROM acore_characters.overseer_death d2
            WHERE d2.character_name = d1.character_name AND d2.zone = 15
              AND d2.created_at >= d1.created_at
              AND d2.created_at < d1.created_at + INTERVAL 1 HOUR) >= 3) x) AS loops,
  (SELECT COUNT(*) FROM acore_characters.overseer_death d
    WHERE d.zone = 15 AND d.created_at >= '2026-11-08 10:27:00') AS dw_deaths
) s;
