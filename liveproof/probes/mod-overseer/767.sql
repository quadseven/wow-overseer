-- ticket: 767
-- repo: quadseven/mod-overseer
-- #767 Dungeon queue no longer holds families: in the last 24 h each roster family gained a level or cleared a run,
-- and no roster member died 10 or more times. Level gains = overseer_event kind 'level_up'; clears = overseer_dungeon_run outcome 'complete'.
SELECT '767' AS ticket,
       CASE WHEN t.families = 0 THEN 'no_evidence'
            WHEN t.max_deaths >= 10 OR t.families_with_progress < t.families THEN 'disproven'
            ELSE 'proven' END AS verdict,
       CONCAT('families=', t.families,
              ', families with a level_up or complete run in 24h=', t.families_with_progress,
              ', max deaths per member in 24h=', t.max_deaths,
              ' (the spirit healer log count is in LOG 767)') AS evidence
FROM (
  SELECT COUNT(*) AS families,
         COALESCE(SUM(x.levels + x.clears > 0), 0) AS families_with_progress,
         (SELECT COALESCE(MAX(m.n), 0) FROM (
             SELECT d.character_name, COUNT(*) AS n
               FROM acore_characters.overseer_death d
               JOIN acore_characters.overseer_roster r
                 ON r.name COLLATE utf8mb4_unicode_ci = d.character_name COLLATE utf8mb4_unicode_ci
              WHERE d.created_at >= NOW() - INTERVAL 24 HOUR
              GROUP BY d.character_name
          ) m) AS max_deaths
  FROM (
    SELECT f.family,
           (SELECT COUNT(*) FROM acore_characters.overseer_event e
              JOIN acore_characters.overseer_roster r2
                ON r2.name COLLATE utf8mb4_unicode_ci = e.character_name COLLATE utf8mb4_unicode_ci
             WHERE r2.family COLLATE utf8mb4_unicode_ci = f.family
               AND e.kind = 'level_up'
               AND e.last_seen >= NOW() - INTERVAL 24 HOUR) AS levels,
           (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_run u
             WHERE u.family COLLATE utf8mb4_unicode_ci = f.family
               AND u.outcome = 'complete'
               AND u.ended_at >= NOW() - INTERVAL 24 HOUR) AS clears
    FROM (SELECT DISTINCT r.family COLLATE utf8mb4_unicode_ci AS family
            FROM acore_characters.overseer_roster r) f
  ) x
) t;
