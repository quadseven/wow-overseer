-- ticket: 1418
-- repo: quadseven/mod-overseer
-- #1418 Guild warlocks (class 9) at level 40-49 die at most 1.5x as often per member as the other classes, last 24 h.
-- Window must start after the carrying restart: valid only from 2026-11-09 11:11Z (roll 102 + 24 h). Needs 10+ members in each group.
-- Patch 0022 must also be in the deployed tree; confirm from the roll notes before accepting 'disproven'.
SELECT '1418' AS ticket,
       CASE WHEN t.window_ok = 0 OR t.wl_members < 10 OR t.other_members < 10 OR t.other_deaths = 0 THEN 'no_evidence'
            WHEN (t.wl_deaths / t.wl_members) / (t.other_deaths / t.other_members) <= 1.5 THEN 'proven'
            ELSE 'disproven' END AS verdict,
       CONCAT('warlocks 40-49=', t.wl_members, ' deaths=', t.wl_deaths,
              ', others=', t.other_members, ' deaths=', t.other_deaths,
              ', ratio=', IFNULL(ROUND((t.wl_deaths / NULLIF(t.wl_members, 0)) / NULLIF(t.other_deaths / NULLIF(t.other_members, 0), 0), 2), 'n/a'),
              ', window after restart=', IF(t.window_ok = 1, 'yes', 'no'),
              ' (patch 0022 deployment unconfirmed)') AS evidence
FROM (
  SELECT SUM(c.class = 9) AS wl_members,
         SUM(c.class <> 9) AS other_members,
         COALESCE(SUM(IF(c.class = 9, COALESCE(d.n, 0), 0)), 0) AS wl_deaths,
         COALESCE(SUM(IF(c.class <> 9, COALESCE(d.n, 0), 0)), 0) AS other_deaths,
         (NOW() >= CONVERT_TZ('2026-11-09 11:11:00', '+00:00', @@session.time_zone)) AS window_ok
  FROM acore_characters.characters c
  JOIN acore_characters.guild_member gm ON gm.guid = c.guid
  LEFT JOIN (SELECT character_guid, COUNT(*) AS n
               FROM acore_characters.overseer_death
              WHERE created_at >= NOW() - INTERVAL 24 HOUR
              GROUP BY character_guid) d ON d.character_guid = c.guid
  WHERE c.level BETWEEN 40 AND 49
) t;
