-- ticket: 446
-- repo: quadseven/mod-overseer
-- #446 job='fish' raises Fishing (skill 356) above 1 on a roster member.
-- Proven: a roster member with Fishing > 1. Not decidable in SQL: disproof (started-fishing line with value stuck at 1), see LOG 446.
SELECT '446' AS ticket,
       CASE WHEN t.fishers > 0 THEN 'proven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('roster members with Fishing>1=', t.fishers,
              ', top Fishing value=', t.top_value,
              ', roster currently job=fish=', t.fish_job,
              ', fish decree rows in overseer_command=', t.fish_cmds) AS evidence
FROM (
  SELECT
    (SELECT COUNT(*) FROM acore_characters.character_skills cs
      WHERE cs.skill = 356 AND cs.value > 1
        AND cs.guid IN (SELECT c.guid FROM acore_characters.characters c
                          JOIN acore_characters.overseer_roster r
                            ON r.name COLLATE utf8mb4_unicode_ci = c.name COLLATE utf8mb4_unicode_ci)) AS fishers,
    (SELECT COALESCE(MAX(cs.value), 0) FROM acore_characters.character_skills cs
      WHERE cs.skill = 356
        AND cs.guid IN (SELECT c.guid FROM acore_characters.characters c
                          JOIN acore_characters.overseer_roster r
                            ON r.name COLLATE utf8mb4_unicode_ci = c.name COLLATE utf8mb4_unicode_ci)) AS top_value,
    (SELECT COUNT(*) FROM acore_characters.overseer_roster r WHERE r.job = 'fish') AS fish_job,
    (SELECT COUNT(*) FROM acore_characters.overseer_command oc WHERE oc.command LIKE '%fish%') AS fish_cmds
) t;
