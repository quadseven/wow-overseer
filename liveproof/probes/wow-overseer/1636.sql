-- ticket: 1636
-- repo: quadseven/wow-overseer
-- 1636: guild feed repeats since 05:00Z 11-08. Proven: guild chat rows exist and no speaker repeats an
-- identical sentence within 40 minutes, and no member re-asks the same door while the first ask is
-- still live. Disproven: any such pair.
SELECT '1636' AS ticket,
  CASE WHEN s.chat_pairs > 0 OR s.ask_pairs > 0 THEN 'disproven'
       WHEN s.chat_rows > 0 THEN 'proven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('guild_chat_rows=', s.chat_rows, ' repeated_sentence_pairs_40min=', s.chat_pairs,
         ' same_door_ask_pairs_while_live=', s.ask_pairs) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.overseer_command c
    WHERE c.kind = 'chat' AND c.channel = 'guild' AND c.source = 'overseer:guildsocial'
      AND c.status = 'delivered' AND c.created_at >= '2026-11-08 05:00:00') AS chat_rows,
  (SELECT COUNT(*) FROM acore_characters.overseer_command c1
    JOIN acore_characters.overseer_command c2
      ON c2.target_name = c1.target_name AND c2.command = c1.command AND c2.id > c1.id
     AND c2.created_at <= c1.created_at + INTERVAL 40 MINUTE
    WHERE c1.kind = 'chat' AND c1.channel = 'guild' AND c1.source = 'overseer:guildsocial'
      AND c1.status = 'delivered' AND c1.created_at >= '2026-11-08 05:00:00'
      AND c2.kind = 'chat' AND c2.channel = 'guild' AND c2.source = 'overseer:guildsocial'
      AND c2.status = 'delivered') AS chat_pairs,
  (SELECT COUNT(*) FROM acore_characters.overseer_guild_ask a1
    JOIN acore_characters.overseer_guild_ask a2
      ON a2.asker = a1.asker AND a2.target = a1.target AND a2.id > a1.id
     AND a2.created_at < a1.expires_at AND a2.created_at <= a1.created_at + INTERVAL 40 MINUTE
    WHERE a1.created_at >= '2026-11-08 05:00:00' AND a1.state <> 'cancelled') AS ask_pairs
) s;
