-- ticket: 1980
-- repo: quadseven/wow-overseer
-- 1980: guild bank tabs. Proven: a guild with a roster member holds 2 or more purchased tabs.
-- Disproven is not reachable (no tabs means the purchase was not reached), so none here.
SELECT '1980' AS ticket,
  CASE WHEN s.family_guilds_2plus > 0 THEN 'proven' ELSE 'no_evidence' END AS verdict,
  CONCAT('guilds_with_2plus_tabs=', s.guilds_2plus, ' of_those_with_roster_member=', s.family_guilds_2plus) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM (
     SELECT t.guildid FROM acore_characters.guild_bank_tab t GROUP BY t.guildid HAVING COUNT(*) >= 2) g) AS guilds_2plus,
  (SELECT COUNT(*) FROM (
     SELECT t.guildid FROM acore_characters.guild_bank_tab t GROUP BY t.guildid HAVING COUNT(*) >= 2) g
   WHERE EXISTS (SELECT 1 FROM acore_characters.guild_member gm
                 JOIN acore_characters.characters c ON c.guid = gm.guid
                 JOIN acore_characters.overseer_roster ro ON ro.name = c.name COLLATE utf8mb4_unicode_ci
                 WHERE gm.guildid = g.guildid)) AS family_guilds_2plus
) s;
