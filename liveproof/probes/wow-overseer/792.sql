-- ticket: 792
-- repo: quadseven/wow-overseer
-- 792 Class training gaps. Proven: zero 'no trainer of this character' refusals in 24h and the draenei shamans' trainer walks end delivered or applied.
-- Disproven: any of Tugga, Bluk, Cronk, Ezzo still appears among the refusals.
SELECT '792' AS ticket,
       CASE WHEN t.all_refusals = 0 AND t.named_ok > 0 THEN 'proven'
            WHEN t.named_refusals > 0 THEN 'disproven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('refusals_24h=', t.all_refusals, ' refusals_named_four=', t.named_refusals,
              ' named_four_walks_delivered_or_applied_24h=', t.named_ok) AS evidence
FROM (SELECT
        (SELECT COUNT(*) FROM acore_characters.overseer_command
          WHERE command LIKE 'walk-to-trainer%'
            AND CONCAT(COALESCE(detail, ''), ' ', COALESCE(result, '')) LIKE '%no trainer of this character%'
            AND updated_at > NOW() - INTERVAL 1 DAY) AS all_refusals,
        (SELECT COUNT(*) FROM acore_characters.overseer_command
          WHERE command LIKE 'walk-to-trainer%'
            AND CONCAT(COALESCE(detail, ''), ' ', COALESCE(result, '')) LIKE '%no trainer of this character%'
            AND updated_at > NOW() - INTERVAL 1 DAY
            AND target_name IN ('Tugga', 'Bluk', 'Cronk', 'Ezzo')) AS named_refusals,
        (SELECT COUNT(*) FROM acore_characters.overseer_command
          WHERE command LIKE 'walk-to-trainer%' AND status IN ('delivered', 'applied')
            AND updated_at > NOW() - INTERVAL 1 DAY
            AND target_name IN ('Tugga', 'Bluk', 'Cronk', 'Ezzo')) AS named_ok) t;
