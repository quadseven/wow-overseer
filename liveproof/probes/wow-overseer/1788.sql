-- ticket: 1788
-- repo: quadseven/wow-overseer
-- 1788: quest 103 Keeper of the Flame. Proven: a quest_reward event for quest 103 since the
-- 2026-11-03 13:56Z ship. Disproven (a holder with no progress for 2 hours) is not readable here.
SELECT '1788' AS ticket,
  CASE WHEN s.rewards_since > 0 THEN 'proven' ELSE 'no_evidence' END AS verdict,
  CONCAT('quest=103 reward_events_since_ship=', s.rewards_since, ' rewarded_rows_total=', s.rewarded_total,
         ' holders_now=', s.holders) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_event e
    WHERE e.kind = 'quest_reward' AND e.subject_id = 103 AND e.first_seen >= '2026-11-03 13:56:00') AS rewards_since,
  (SELECT COUNT(*) FROM acore_characters.character_queststatus_rewarded r WHERE r.quest = 103) AS rewarded_total,
  (SELECT COUNT(*) FROM acore_characters.character_queststatus q WHERE q.quest = 103) AS holders
) s;
