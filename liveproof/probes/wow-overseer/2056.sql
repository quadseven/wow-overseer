-- ticket: 2056
-- repo: quadseven/wow-overseer
-- 2056: lockpicker standin. Proven: a standin row naming lockpick since the 07:57Z ship.
-- Disproven: a qualifying guild rogue exists (level 50+, class 4, Lockpicking 250+) and no lockpick
-- row exists (a standin row is deleted when no longer needed, so treat this as a prompt to read the log).
SELECT '2056' AS ticket,
  CASE WHEN s.lock_rows > 0 THEN 'proven'
       WHEN s.rogues > 0 AND s.lock_rows = 0 THEN 'disproven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('lockpick_standin_rows=', s.lock_rows, ' qualifying_guild_rogues=', s.rogues) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_family_standin f
    WHERE f.reason LIKE '%lockpick%' AND f.created_at >= '2026-11-08 07:57:00') AS lock_rows,
  (SELECT COUNT(DISTINCT c.guid) FROM acore_characters.characters c
    JOIN acore_characters.guild_member gm ON gm.guid = c.guid
    JOIN acore_characters.character_skills sk ON sk.guid = c.guid AND sk.skill = 633
    WHERE c.class = 4 AND c.level >= 50 AND sk.value >= 250) AS rogues
) s;
