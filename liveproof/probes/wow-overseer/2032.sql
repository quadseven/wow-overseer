-- ticket: 2032
-- repo: quadseven/wow-overseer
-- 2032: guild warlocks with Summon Voidwalker (697). Proven: lacking is 21 or fewer and at least 5
-- of the 21 names the ticket listed now hold 697. Disproven: still 26 or more lacking 24 hours
-- after the 05:53Z 11-08 ship (checked from 2026-11-09 05:53Z).
SELECT '2032' AS ticket,
  CASE WHEN s.lacking <= 21 AND s.named_holding >= 5 THEN 'proven'
       WHEN s.lacking >= 26 AND UTC_TIMESTAMP() >= '2026-11-09 05:53:00' THEN 'disproven'
       ELSE 'no_evidence' END AS verdict,
  CONCAT('lacking=', s.lacking, ' named_now_holding_697=', s.named_holding) AS evidence
FROM (SELECT
  (SELECT COUNT(*) FROM acore_characters.characters c
    JOIN acore_characters.guild_member gm ON gm.guid = c.guid
    WHERE c.class = 9 AND c.level >= 10
      AND NOT EXISTS (SELECT 1 FROM acore_characters.character_spell sp
                      WHERE sp.guid = c.guid AND sp.spell = 697)) AS lacking,
  (SELECT COUNT(*) FROM acore_characters.characters c
    JOIN acore_characters.character_spell sp ON sp.guid = c.guid AND sp.spell = 697
    WHERE c.name IN ('Hrunt','Gorrk','Mukk','Yobb','Nubb','Krog','Fuggo','Fizzik','Wukk','Booga','Mok',
                     'Sogg','Lugg','Ooga','Grakk','Hungrygrunt','Bonesy','Deadpan','Morbidly',
                     'Bonejangles','Skelly')) AS named_holding
) s;
