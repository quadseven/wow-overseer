-- ticket: 769
-- repo: quadseven/wow-overseer
-- 769 Family crafters learn trainer recipes. Proven: Ugga and Uzza above 80 Alchemy (171), Og above 100 Tailoring (197).
-- No disproven branch: the plan says absence never disproves.
SELECT '769' AS ticket,
       CASE WHEN t.ugga > 80 AND t.uzza > 80 AND t.og > 100 THEN 'proven'
            ELSE 'no_evidence' END AS verdict,
       CONCAT('Ugga171=', COALESCE(t.ugga, 'NA'), ' Uzza171=', COALESCE(t.uzza, 'NA'),
              ' Og197=', COALESCE(t.og, 'NA')) AS evidence
FROM (SELECT MAX(CASE WHEN c.name = 'Ugga' AND cs.skill = 171 THEN cs.value END) AS ugga,
             MAX(CASE WHEN c.name = 'Uzza' AND cs.skill = 171 THEN cs.value END) AS uzza,
             MAX(CASE WHEN c.name = 'Og' AND cs.skill = 197 THEN cs.value END) AS og
      FROM acore_characters.character_skills cs
      JOIN acore_characters.characters c ON c.guid = cs.guid
      WHERE c.name IN ('Ugga', 'Uzza', 'Og') AND cs.skill IN (171, 197)) t;
