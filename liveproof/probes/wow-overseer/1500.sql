-- ticket: 1500
-- repo: quadseven/wow-overseer
-- 1500 Item-goal queue entry. Proven: a done goal row with finished_at set and notice cleared, and a roster member owns the item.
-- No disproven branch: the plan's disproof needs the family run count, which no confirmed table gives by family.
SELECT '1500' AS ticket,
       CASE WHEN t.proven_rows > 0 THEN 'proven' ELSE 'no_evidence' END AS verdict,
       CONCAT('goal_rows=', t.goal_rows, ' done_goal_rows=', t.done_rows,
              ' done_with_owner_and_notice_cleared=', t.proven_rows) AS evidence
FROM (SELECT
        (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue WHERE goal_item > 0) AS goal_rows,
        (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue
          WHERE goal_item > 0 AND status = 'done') AS done_rows,
        (SELECT COUNT(*) FROM acore_characters.overseer_dungeon_queue q
          WHERE q.goal_item > 0 AND q.status = 'done' AND q.finished_at IS NOT NULL
            AND q.goal_notice_pending = 0
            AND EXISTS (SELECT 1 FROM acore_characters.item_instance ii
                        JOIN acore_characters.characters c ON c.guid = ii.owner_guid
                        JOIN acore_characters.overseer_roster r
                          ON r.name COLLATE utf8mb4_unicode_ci = c.name COLLATE utf8mb4_unicode_ci
                        WHERE ii.itemEntry = q.goal_item)) AS proven_rows) t;
