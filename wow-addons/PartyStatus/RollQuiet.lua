-- RollQuiet: the streamed heads are selfbots. Their own playerbot AI rolls
-- need, greed or pass on the server, so the roll windows this client opens
-- are never answered from here and stack up across the screen until each
-- roll's timer runs out. Hide them as they open; the roll itself is the
-- AI's. Nothing here ever rolls or passes.

local function hideRollFrames()
    for i = 1, (NUM_GROUP_LOOT_FRAMES or 4) do
        local f = _G["GroupLootFrame" .. i]
        if f and f:IsShown() then
            f:Hide()
        end
    end
end

if GroupLootFrame_OpenNewFrame then
    hooksecurefunc("GroupLootFrame_OpenNewFrame", hideRollFrames)
end

local driver = CreateFrame("Frame")
driver:RegisterEvent("PLAYER_ENTERING_WORLD")
driver:RegisterEvent("START_LOOT_ROLL")
driver:SetScript("OnEvent", hideRollFrames)
