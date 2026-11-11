-- ticket: 2012
-- repo: quadseven/wow-overseer
-- 2012: member deaths on 2026-11-09 UTC. Proven: the day is over, player-killer deaths under 50 and
-- Dustwallow Marsh (zone 15) deaths under 350. Disproven: either bar already missed (counts only grow).
SELECT '2012' AS ticket,
  CASE WHEN s.player_deaths >= 50 OR s.dustwallow_deaths >= 350 THEN 'disproven'
       WHEN UTC_TIMESTAMP() >= '2026-11-10 00:00:00' AND s.all_deaths > 0 THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('day=2026-11-09 all_deaths=', s.all_deaths, ' player_deaths=', s.player_deaths,
         ' dustwallow_deaths=', s.dustwallow_deaths, ' bars=50/350') AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_death d
    WHERE d.created_at >= '2026-11-09 00:00:00' AND d.created_at < '2026-11-10 00:00:00') AS all_deaths,
  (SELECT COUNT(*) FROM acore_characters.overseer_death d
    WHERE d.created_at >= '2026-11-09 00:00:00' AND d.created_at < '2026-11-10 00:00:00'
      AND d.killer_type = 'player') AS player_deaths,
  (SELECT COUNT(*) FROM acore_characters.overseer_death d
    WHERE d.created_at >= '2026-11-09 00:00:00' AND d.created_at < '2026-11-10 00:00:00'
      AND d.zone = 15) AS dustwallow_deaths
) s;
