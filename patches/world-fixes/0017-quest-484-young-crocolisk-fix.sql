-- Quest 484: Young Crocolisk Skins
-- WHY THIS FIX EXISTS
--
-- Quest 484 is broken: players cannot take it because the quest template
-- references creature 1417 (The Prophet Skeram from the Sunken Temple) as
-- the objective, not the Young Crocolisk in the Wetlands.
--
-- The take was refused because no living creature linked to the quest
-- matched within the 20-yard arrival radius. The questgiver (Bromli) is
-- on map 0 (Loch Modan), but creature 1417 only spawns on map 1 (The
-- Sunken Temple), which is far outside the 20-yard arrival radius.
--
-- The correct Young Crocolisk in the Wetlands has entry 1415. This patch
-- updates the quest template to use the correct creature entry.
--
-- FIX DETAILS
--
-- - Quest ID: 484 (Young Crocolisk Skins)
-- - Old objective creature entry: 1417 (Sunken Temple boss, The Prophet Skeram)
-- - New objective creature entry: 1415 (Young Crocolisk)
-- - Map where questgiver stands: 0 (Loch Modan)
-- - Map where Young Crocolisks spawn: 0 (Wetlands)
-- - Fix applies to: quest_template.RequiredNpcOrGo1 = -1415 (signed negative)
--
-- WHAT WOULD LET THIS PATCH BE DELETED
--
-- If the world database is ever updated with a correct quest template from
-- the official database, this patch can be removed.
--
-- APPLIES TO
--
--     acore_world.quest_template, ID = 484
--
-- REBASED 2026-11-27

UPDATE acore_world.quest_template
SET RequiredNpcOrGo1 = -1415
WHERE ID = 484
AND RequiredNpcOrGo1 = -1417;
