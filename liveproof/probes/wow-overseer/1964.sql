-- ticket: 1964
-- repo: quadseven/wow-overseer
-- 1964: a planner or Jev BRD order, or a guild BRD run, created after the 19:41Z 11-07 ship.
-- Disproven: none by 2026-11-14.
SELECT '1964' AS ticket,
  CASE WHEN s.queue_rows + s.guild_runs > 0 THEN 'proven'
       WHEN UTC_TIMESTAMP() >= '2026-11-14 00:00:00' THEN 'disproven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('planner_or_jev_queue_rows=', s.queue_rows, ' guild_brd_runs=', s.guild_runs) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue q
    WHERE q.keyword LIKE 'blackrock-depths%' AND q.source IN ('overseer:planner', 'overseer:jev')
      AND q.created_at >= '2026-11-07 19:41:00') AS queue_rows,
  (SELECT COUNT(*) FROM acore_characters.overseer_guild_run g
    WHERE g.keyword LIKE 'blackrock-depths%' AND g.created_at >= '2026-11-07 19:41:00') AS guild_runs
) s;
