-- ticket: 781
-- repo: quadseven/wow-overseer
-- 781 Class quests ahead. Proven: a roster member holds 3599 or 5394.
-- Disproven: none holds either and it is 12 days or more past the #1497 merge (2026-10-26 12:32).
SELECT '781' AS ticket,
       CASE WHEN t.holders_3599_5394 > 0 THEN 'proven'
            WHEN t.holders_3599_5394 = 0 AND NOW() >= '2026-11-07 12:32:00' THEN 'disproven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('members_with_2458=', t.holders_2458, ' members_with_3599_or_5394=', t.holders_3599_5394) AS evidence
FROM (SELECT
        (SELECT COUNT(DISTINCT cs.guid) FROM acore_characters.character_spell cs
          JOIN acore_characters.characters c ON c.guid = cs.guid
          JOIN acore_characters.overseer_roster r
            ON r.name COLLATE utf8mb4_unicode_ci = c.name COLLATE utf8mb4_unicode_ci
          WHERE cs.spell = 2458) AS holders_2458,
        (SELECT COUNT(DISTINCT cs.guid) FROM acore_characters.character_spell cs
          JOIN acore_characters.characters c ON c.guid = cs.guid
          JOIN acore_characters.overseer_roster r
            ON r.name COLLATE utf8mb4_unicode_ci = c.name COLLATE utf8mb4_unicode_ci
          WHERE cs.spell IN (3599, 5394)) AS holders_3599_5394) t;
