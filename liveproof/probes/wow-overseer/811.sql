-- ticket: 811
-- repo: quadseven/wow-overseer
-- 811 Dark Iron Legacy. Proven: a quest_accept for 3801 and a roster member carries the Shadowforge Key (11000).
-- No disproven branch: the plan says absence never disproves.
SELECT '811' AS ticket,
       CASE WHEN t.accepts > 0 AND t.key_owners > 0 THEN 'proven' ELSE 'no_evidence' END AS verdict,
       CONCAT('quest_accept_3801=', t.accepts, ' quest_rows_3801_3802=', t.quest_rows,
              ' key_11000_member_owners=', t.key_owners) AS evidence
FROM (SELECT
        (SELECT COUNT(*) FROM acore_characters.overseer_event
          WHERE subject_id = 3801 AND kind = 'quest_accept') AS accepts,
        (SELECT COUNT(*) FROM acore_characters.overseer_event
          WHERE subject_id IN (3801, 3802)
            AND kind IN ('quest_accept', 'quest_complete', 'quest_reward')) AS quest_rows,
        (SELECT COUNT(*) FROM acore_characters.item_instance ii
          JOIN acore_characters.characters c ON c.guid = ii.owner_guid
          JOIN acore_characters.overseer_roster r
            ON r.name COLLATE utf8mb4_unicode_ci = c.name COLLATE utf8mb4_unicode_ci
          WHERE ii.itemEntry = 11000) AS key_owners) t;
