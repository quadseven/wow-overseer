-- Meter: threat and damage for the party, from the tank's view.
--
-- WHAT THIS IS. A compact bar list a stream viewer can read: who is doing the
-- damage this fight, and how close each member is to pulling the mob the tank
-- holds. It lives in the client so the stream's own picture carries it, and so
-- it is live: /api/meter asks the worldserver once per cache window.
--
-- WHERE THE NUMBERS COME FROM. Damage is summed from the client's combat log,
-- in the 3.3.5a layout: eight base arguments, then the amount for a swing, or
-- spellId, spellName, school and then the amount for anything else. Overkill
-- follows the amount and is -1 when there is none. Threat is the client's own
-- UnitDetailedThreatSituation, whose third return is the percent toward pulling
-- aggro, so the member holding the mob reads 100.
--
-- WHICH MOB. The streamed heads are selfbots: the server drives them, so the
-- client may hold no target of its own. When it holds none, the mob is the one
-- a party member is targeting that the player is tanking, else the first
-- hostile one a party member is targeting.
--
-- WHERE IT SITS. The clients run 1920x1080 at uiScale 0.9, so 1080 pixels are
-- 853 units. Measured from a live frame, the left column is free from the fourth
-- party frame's end at y=-392 to the chat buttons at y=-495. A 720p viewer
-- scales it by 0.84 pixels per unit, so a 12 unit outlined font stays readable.
-- Loot cards sit in the opposite corner.
--
-- Party only. In a raid party1 to party4 are the player's own subgroup.

local ANCHOR_X = 14
local ANCHOR_Y = -394
local WIDTH = 204
local ROW_HEIGHT = 15
local ROW_COUNT = 5
local FONT_SIZE = 12
local TICK = 0.5

-- A pull with a breath in it is one fight.
local GAP_SECONDS = 3
-- How long a finished fight stays up, so the final numbers can be read.
local LINGER_SECONDS = 30
-- A member other than the tank at this percent is about to pull the mob.
local DANGER_PERCENT = 90

local PET_OF = {
    player = "pet", party1 = "partypet1", party2 = "partypet2",
    party3 = "partypet3", party4 = "partypet4",
}
local UNITS = { "player", "party1", "party2", "party3", "party4" }

-- The sub-events that are damage. A swing carries the amount first; the rest
-- carry spellId, spellName and school before it.
local SPELL_SHAPED = {
    SPELL_DAMAGE = true, SPELL_PERIODIC_DAMAGE = true,
    RANGE_DAMAGE = true, DAMAGE_SHIELD = true,
}

local meter = { rows = {} }
local damage = {}
local owners = {}
local started, stopped, lastCombat

local function readRoster()
    owners = {}
    for _, unit in ipairs(UNITS) do
        local name = UnitName(unit)
        if name then
            local guid, pet = UnitGUID(unit), UnitGUID(PET_OF[unit])
            if guid then owners[guid] = name end
            if pet then owners[pet] = name end
        end
    end
end

local function partyInCombat()
    for _, unit in ipairs(UNITS) do
        if UnitExists(unit) and UnitAffectingCombat(unit) then return true end
    end
    return false
end

local function beginFight()
    damage = {}
    started, stopped = GetTime(), nil
    lastCombat = started
end

local function trackFight()
    local active = started and not stopped
    if partyInCombat() then
        if not active then beginFight() end
        lastCombat = GetTime()
    elseif active and (GetTime() - lastCombat) >= GAP_SECONDS then
        stopped = lastCombat
    end
end

local function onCombatLog(sub, source, target, a, b, _, d, e)
    local amount, overkill
    if sub == "SWING_DAMAGE" then
        amount, overkill = a, b
    elseif SPELL_SHAPED[sub] then
        amount, overkill = d, e
    else
        return
    end
    local name = owners[source]
    if not name or owners[target] then return end
    if not started or stopped then
        if not partyInCombat() then return end
        beginFight()
    end
    damage[name] = (damage[name] or 0) + amount - math.max(overkill or 0, 0)
end

local function hostile(unit)
    return UnitExists(unit) and UnitCanAttack("player", unit) and not UnitIsDead(unit)
end

local function currentMob()
    if hostile("target") then return "target" end
    local first
    for i = 1, 4 do
        local unit = "party" .. i .. "target"
        if hostile(unit) then
            if UnitDetailedThreatSituation("player", unit) then return unit end
            first = first or unit
        end
    end
    return first
end

local function short(value)
    if value >= 1000000 then return string.format("%.1fM", value / 1000000) end
    if value >= 10000 then return string.format("%.1fk", value / 1000) end
    return tostring(math.floor(value + 0.5))
end

local function collect(mob)
    local list = {}
    local top = 1
    local threatened = false
    for _, unit in ipairs(UNITS) do
        local name = UnitName(unit)
        if name then
            local row = { name = name, unit = unit, damage = damage[name] or 0 }
            if mob then
                local tanking, _, percent = UnitDetailedThreatSituation(unit, mob)
                row.tanking, row.threat = tanking, percent
                threatened = threatened or percent ~= nil
            end
            top = math.max(top, row.damage)
            list[#list + 1] = row
        end
    end
    table.sort(list, function(l, r)
        if (l.threat or -1) ~= (r.threat or -1) then
            return (l.threat or -1) > (r.threat or -1)
        end
        if l.damage ~= r.damage then return l.damage > r.damage end
        return l.name < r.name
    end)
    return list, top, threatened
end

local function makeText(parent, justify)
    local text = parent:CreateFontString(nil, "OVERLAY")
    -- OUTLINE for the reason PartyStatus gives: an encoder drops a thin shadow.
    text:SetFont(STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF", FONT_SIZE, "OUTLINE")
    text:SetJustifyH(justify)
    text:SetText("")
    return text
end

local function makeCells(owner, y)
    local cells = {}
    cells.name = makeText(owner, "LEFT")
    cells.name:SetPoint("TOPLEFT", owner, "TOPLEFT", 4, y)
    cells.name:SetWidth(84)
    cells.name:SetHeight(ROW_HEIGHT)
    cells.damage = makeText(owner, "RIGHT")
    cells.damage:SetPoint("TOPRIGHT", owner, "TOPRIGHT", -80, y)
    cells.dps = makeText(owner, "RIGHT")
    cells.dps:SetPoint("TOPRIGHT", owner, "TOPRIGHT", -46, y)
    cells.threat = makeText(owner, "RIGHT")
    cells.threat:SetPoint("TOPRIGHT", owner, "TOPRIGHT", -4, y)
    return cells
end

local function makePanel()
    local frame = CreateFrame("Frame", nil, UIParent)
    frame:SetWidth(WIDTH)
    frame:SetHeight((ROW_COUNT + 1) * ROW_HEIGHT)
    frame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", ANCHOR_X, ANCHOR_Y)
    -- Never takes a click, as with the status labels.
    frame:EnableMouse(false)
    frame:Hide()

    local shade = frame:CreateTexture(nil, "BACKGROUND")
    shade:SetAllPoints(frame)
    shade:SetTexture(0, 0, 0, 0.55)

    local head = makeCells(frame, 0)
    head.damage:SetText("dmg")
    head.dps:SetText("dps")
    head.threat:SetText("threat")
    meter.frame, meter.title = frame, head.name

    for i = 1, ROW_COUNT do
        local y = -i * ROW_HEIGHT
        local row = makeCells(frame, y)
        row.bar = frame:CreateTexture(nil, "BORDER")
        row.bar:SetPoint("TOPLEFT", frame, "TOPLEFT", 0, y)
        row.bar:SetHeight(ROW_HEIGHT - 1)
        row.bar:SetWidth(1)
        meter.rows[i] = row
    end
end

local function paintRow(row, data, top, threatened, seconds)
    row.name:SetText(data.name)
    row.damage:SetText(short(data.damage))
    row.dps:SetText(short(data.damage / seconds))
    row.threat:SetText(data.threat and (short(data.threat) .. "%") or "--")
    if data.threat and data.threat >= DANGER_PERCENT and not data.tanking then
        row.threat:SetTextColor(1, 0.25, 0.2)
    else
        row.threat:SetTextColor(1, 1, 1)
    end
    local _, class = UnitClass(data.unit)
    local c = RAID_CLASS_COLORS[class] or { r = 0.5, g = 0.5, b = 0.5 }
    local share = threatened and (data.threat or 0) / 100 or data.damage / top
    row.bar:SetTexture(c.r, c.g, c.b, 0.75)
    row.bar:SetWidth(math.max(1, WIDTH * math.min(share, 1)))
    row.bar:Show()
end

local function clearRow(row)
    row.name:SetText("")
    row.damage:SetText("")
    row.dps:SetText("")
    row.threat:SetText("")
    row.bar:Hide()
end

local function paint()
    if not meter.frame then return end
    local now = GetTime()
    if not started or (stopped and (now - stopped) >= LINGER_SECONDS) then
        meter.frame:Hide()
        return
    end
    local mob = not stopped and currentMob() or nil
    local list, top, threatened = collect(mob)
    local seconds = math.max(1, (stopped or now) - started)
    meter.title:SetText(threatened and UnitName(mob) or "Damage")
    for i, row in ipairs(meter.rows) do
        if list[i] then
            paintRow(row, list[i], top, threatened, seconds)
        else
            clearRow(row)
        end
    end
    meter.frame:Show()
end

local function refresh()
    readRoster()
    trackFight()
    paint()
end

local driver = CreateFrame("Frame")
driver:RegisterEvent("PLAYER_LOGIN")
driver:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
driver:SetScript("OnEvent", function(_, event, ...)
    if event == "PLAYER_LOGIN" then
        if not meter.frame then makePanel() end
        readRoster()
        return
    end
    local _, sub, source, _, _, target, _, _, a, b, c, d, e = ...
    onCombatLog(sub, source, target, a, b, c, d, e)
end)

local since = 0
driver:SetScript("OnUpdate", function(_, elapsed)
    since = since + elapsed
    if since < TICK then return end
    since = 0
    -- pcall: a missing unit API on an unexpected build must cost the panel, not
    -- every other addon's frame, as in PartyStatus.lua.
    pcall(refresh)
end)

_G.PartyStatusMeter = meter
