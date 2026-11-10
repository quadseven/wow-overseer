-- ticket: 1767
-- repo: quadseven/wow-overseer
-- 1767: quest 87 Goldtooth (same rule).
SELECT '1767' AS ticket,
  CASE WHEN s.rewards_since > 0 THEN 'proven' ELSE 'no_evidence' END AS verdict,
  CONCAT('quest=87 reward_events_since_ship=', s.rewards_since, ' rewarded_rows_total=', s.rewarded_total,
         ' holders_now=', s.holders) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_event e
    WHERE e.kind = 'quest_reward' AND e.subject_id = 87 AND e.first_seen >= '2026-11-03 13:56:00') AS rewards_since,
  (SELECT COUNT(*) FROM acore_characters.character_queststatus_rewarded r WHERE r.quest = 87) AS rewarded_total,
  (SELECT COUNT(*) FROM acore_characters.character_queststatus q WHERE q.quest = 87) AS holders
) s;
