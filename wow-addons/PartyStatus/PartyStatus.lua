-- Party Status (infra#3334)
--
-- WHAT THIS IS. One small label beside each family member's name saying what
-- they are doing. Five clients each stream one of them, and on every one of
-- those streams the party frames name the other four and say nothing else.
--
-- WHERE THE JUDGEMENT LIVES, AND IT IS NOT HERE. Every state, every word a
-- viewer reads, and the order the local facts are asked in are decided in
-- production/scripts/wow-overseer/partystatus.py and covered by its stdlib
-- suite. This file gathers facts, applies that order, and paints. The only
-- thing it decides on its own is the palette, which is a view's business.
--
-- LOCAL_RULES BELOW MUST STAY IN THE SAME ORDER AS partystatus.PRECEDENCE.
-- It cannot be moved to Python - the facts only exist inside a running client
-- - so tests/test_partystatus.py reads this file as text and fails if the two
-- lists differ. Reorder one and the suite tells you about the other.
--
-- WHERE IT SITS, AND WHY IT COVERS NOTHING. Measured against 3.3.5a's own
-- PartyFrameTemplates.xml rather than by eye. A party member frame is 128x53
-- from its TOPLEFT, and every pixel of that is already spoken for:
--
--     portrait      (7,-6) 37x37          name       bottom-left at (50,-10)
--     health bar    (47,-12) 70x8         mana bar   (47,-21) 70x8
--     debuffs       (48,-32) 4 x 15x15    role icon  (7,-33) 19x19
--     pet frame     64x26, hanging BELOW the frame, and it MOVES:
--                   PartyMemberFrame_UpdatePet re-anchors it on every update,
--                   to (23,-43) when that member has a pet and (23,-27) when
--                   it does not, overriding the (20,-47) in the XML
--
-- The next party frame is anchored to that pet frame, so the pitch is 79 units
-- with a pet and 63 without - NOT the 83 the XML anchor alone suggests, which
-- is what reading PartyFrameTemplates.xml without reading PartyMemberFrame.lua
-- gets you. None of the five classes here carries a pet at this level, so 63 is
-- the live case; a PrintWindow capture of a running client measures the pitch
-- at 73 screen pixels against 1.111 pixels per unit, derived from the exactly
-- 9-unit gap between each frame's own health and mana bars. Either way there is
-- no free space inside the frame and none underneath it, and the tighter the
-- pitch the truer that is. The label
-- goes OUTSIDE the right edge instead, at the height of the name, which is
-- what "next to their name" means here. Two things live near that edge and
-- neither is reached: PartyMemberBackground, the optional panel behind the
-- whole party, is 134 wide from x=-5 and so ends at x=129; the voice-chat
-- speaker icon is at x=123 and is hidden unless voice chat is on, which it is
-- not on this realm. CLEAR_X = 6 puts the label's left edge at x=134.
--
-- THE PLAYER'S OWN FRAME IS ANCHORED DIFFERENTLY, because the same rule does
-- not fit there. PlayerFrame ends at screen x=213 and TargetFrame begins at
-- x=250, so the gap to its right is 37 pixels - narrower than the words. The
-- free space near PlayerFrame is underneath it: the pet frame ends at y=-117
-- and the party block does not begin until y=-154, so the label goes at
-- y=-120, left-aligned with the party column. On a stream of one character
-- that label is the one the viewer most wants, so leaving the player out was
-- not an option.
--
-- IT DEGRADES TO SILENCE, NOT TO A GUESS. Nothing carries the pushed line
-- today. With none arriving, the five locally observed states still work and
-- everything else shows nothing at all, because a member standing quietly with
-- the party and a member nobody is driving are indistinguishable from inside
-- the client, and only one of them is a problem.

local PREFIX = "OVSR"
local VERSION = "1"
local SEP = "\t"

-- Mirrors partystatus.PUSH_STALE_SECONDS. A pushed state older than this is
-- dropped and the label falls back to the local states, because a dead sender
-- must go quiet rather than leave "on task" under someone who stopped an hour
-- ago.
local PUSH_STALE_SECONDS = 90

-- Mirrors partystatus.PRECEDENCE and partystatus.LOCAL_LABELS. First true one
-- wins. `away` sits above `fighting` on purpose: a member the client cannot
-- see is the failure this exists to catch, and a drifted member is nearly
-- always fighting something.
-- `aboutOthers` marks the two rules that are statements about the DISTANCE
-- between a member and the person watching. Neither can be true of the
-- streamed character himself, and UnitInRange("player") is not a question
-- Blizzard_RaidUI ever asks, so asking it would risk labelling every stream's
-- own subject `apart` forever on the strength of an untested return value.
local LOCAL_RULES = {
    { code = "offline",  label = "offline",
      test = function(u) return not UnitIsConnected(u) end },
    { code = "dead",     label = "dead",
      test = function(u) return UnitIsDeadOrGhost(u) end },
    { code = "away",     label = "away", aboutOthers = true,
      test = function(u) return not UnitIsVisible(u) end },
    { code = "fighting", label = "fighting",
      test = function(u) return UnitAffectingCombat(u) end },
    { code = "apart",    label = "apart", aboutOthers = true,
      test = function(u) return not UnitInRange(u) end },
}

-- The palette, which is the one decision this file owns. Held as a table so a
-- code with no colour is a missing entry the suite can find rather than a
-- silent black label on a dark background.
local COLOUR = {
    offline  = { 0.55, 0.55, 0.55 },
    dead     = { 0.90, 0.25, 0.25 },
    away     = { 1.00, 0.45, 0.10 },
    fighting = { 1.00, 0.82, 0.20 },
    apart    = { 0.95, 0.70, 0.35 },
    task     = { 0.45, 0.85, 0.45 },
    travel   = { 0.45, 0.70, 1.00 },
    dungeon  = { 0.75, 0.55, 1.00 },
    stalled  = { 1.00, 0.35, 0.30 },
    idle     = { 0.60, 0.60, 0.60 },
}

-- Clearance from the right edge of a party frame. See the header: the party
-- background panel ends at x=129 and this puts the label at x=134.
local CLEAR_X = 6

-- The name row's vertical middle. The name's baseline box runs from the frame
-- top down to y=-10 and the health bar starts at y=-12.
local NAME_Y = -5

-- How often the local facts are re-read. UnitInRange and UnitIsVisible fire no
-- events, so there is nothing to listen to; twice a second is far below the
-- rate anything here changes and costs nothing measurable.
local TICK = 0.5

-- name -> { code, label, at }. Only ever written by a line that parsed.
local pushed = {}

-- The units this addon draws, in the order the frames appear on screen.
local UNITS = {
    { unit = "player",  anchor = "player" },
    { unit = "party1",  anchor = "PartyMemberFrame1" },
    { unit = "party2",  anchor = "PartyMemberFrame2" },
    { unit = "party3",  anchor = "PartyMemberFrame3" },
    { unit = "party4",  anchor = "PartyMemberFrame4" },
}

local labels = {}

local function makeLabel(spec)
    local parent
    if spec.anchor == "player" then
        parent = PlayerFrame
    else
        parent = _G[spec.anchor]
    end
    if not parent then return nil end

    local frame = CreateFrame("Frame", nil, parent)
    frame:SetWidth(90)
    frame:SetHeight(12)
    -- Never takes a click. The label sits over the 3D world and anything that
    -- swallowed a click there would break targeting for a person playing.
    frame:EnableMouse(false)

    local text = frame:CreateFontString(nil, "OVERLAY")
    -- OUTLINE rather than a shadow: this is read off a video stream, where a
    -- one-pixel shadow is the first thing an encoder throws away.
    text:SetFont(STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF", 10, "OUTLINE")
    text:SetJustifyH("LEFT")

    if spec.anchor == "player" then
        frame:SetPoint("TOPLEFT", parent, "BOTTOMLEFT", 29, -16)
        text:SetPoint("LEFT", frame, "LEFT", 0, 0)
    else
        frame:SetPoint("LEFT", parent, "TOPRIGHT", CLEAR_X, NAME_Y)
        text:SetPoint("LEFT", frame, "LEFT", 0, 0)
    end

    frame.text = text
    return frame
end

-- --- the pushed half ---------------------------------------------------------

local function absorb(message)
    -- One line, split into name/code/label triples. No decision is taken here
    -- and none is available to take: the words arrived already chosen.
    if not message then return false end
    local fields = { strsplit(SEP, message) }
    if fields[1] ~= PREFIX then return false end
    if fields[2] ~= VERSION then
        -- A version this build does not know is treated exactly like silence.
        -- Guessing at an unknown layout is how a label ends up naming the
        -- wrong character.
        return true
    end
    local now = GetTime()
    local i = 3
    while fields[i + 2] ~= nil do
        local name, code, label = fields[i], fields[i + 1], fields[i + 2]
        if name ~= "" and COLOUR[code] then
            pushed[name] = { code = code, label = label, at = now }
        end
        i = i + 3
    end
    return true
end

-- The party-chat route, and its own suppression in one function. mod-overseer
-- can already broadcast a party message today, so that is what works with no
-- server change; the addon-channel route needs four lines in DoChat and is
-- handled by the CHAT_MSG_ADDON branch below. Returning true removes the line
-- from every chat frame, which is what keeps machine traffic off the stream.
local function chatFilter(_, _, message)
    if message and strsub(message, 1, strlen(PREFIX) + 1) == PREFIX .. SEP then
        absorb(message)
        return true
    end
    return false
end

-- --- painting ----------------------------------------------------------------

local function livePush(unit)
    local name = UnitName(unit)
    if not name then return nil end
    local entry = pushed[name]
    if not entry then return nil end
    if (GetTime() - entry.at) > PUSH_STALE_SECONDS then return nil end
    return entry
end

local function paint(spec, frame)
    local unit = spec.unit
    if not UnitExists(unit) then
        frame:Hide()
        return
    end
    for _, rule in ipairs(LOCAL_RULES) do
        if not (rule.aboutOthers and unit == "player") and rule.test(unit) then
            local c = COLOUR[rule.code]
            frame.text:SetText(rule.label)
            frame.text:SetTextColor(c[1], c[2], c[3])
            frame:Show()
            return
        end
    end
    local entry = livePush(unit)
    if entry then
        local c = COLOUR[entry.code]
        frame.text:SetText(entry.label)
        frame.text:SetTextColor(c[1], c[2], c[3])
        frame:Show()
        return
    end
    -- Nothing to say. An empty label rather than a cheerful one: with no
    -- sender running there is no honest way to tell "with the party, working"
    -- from "with the party, being driven by nothing".
    frame.text:SetText("")
    frame:Hide()
end

local function repaint()
    for i, spec in ipairs(UNITS) do
        local frame = labels[i]
        if frame then
            -- pcall: a missing unit API on an unexpected client build must
            -- cost one blank label, not the whole addon and every label after
            -- it. OverseerCam takes the same care with SetCVar.
            pcall(paint, spec, frame)
        end
    end
end

local driver = CreateFrame("Frame")
driver:RegisterEvent("PLAYER_LOGIN")
driver:RegisterEvent("PLAYER_ENTERING_WORLD")
driver:RegisterEvent("PARTY_MEMBERS_CHANGED")
driver:RegisterEvent("CHAT_MSG_ADDON")

driver:SetScript("OnEvent", function(_, event, ...)
    if event == "CHAT_MSG_ADDON" then
        local prefix, message = ...
        if prefix == PREFIX then
            absorb(PREFIX .. SEP .. message)
        end
        return
    end
    if not labels[1] then
        for i, spec in ipairs(UNITS) do
            labels[i] = makeLabel(spec)
        end
        ChatFrame_AddMessageEventFilter("CHAT_MSG_PARTY", chatFilter)
        ChatFrame_AddMessageEventFilter("CHAT_MSG_RAID", chatFilter)
    end
    repaint()
end)

local since = 0
driver:SetScript("OnUpdate", function(_, elapsed)
    since = since + elapsed
    if since < TICK then return end
    since = 0
    repaint()
end)

-- /pstat - say what each label currently reads, and where its answer came
-- from. There is no mouse on an unattended client and no tooltip to hover, so
-- this is how a person checks the addon agrees with the world.
SLASH_PARTYSTATUS1 = "/pstat"
SlashCmdList["PARTYSTATUS"] = function()
    for _, spec in ipairs(UNITS) do
        if UnitExists(spec.unit) then
            local name = UnitName(spec.unit) or spec.unit
            local shown, source = "", "nothing to say"
            for _, rule in ipairs(LOCAL_RULES) do
                if shown == "" and not (rule.aboutOthers and spec.unit == "player")
                        and rule.test(spec.unit) then
                    shown, source = rule.label, "seen here"
                end
            end
            if shown == "" then
                local entry = livePush(spec.unit)
                if entry then shown, source = entry.label, "pushed" end
            end
            DEFAULT_CHAT_FRAME:AddMessage(
                "PartyStatus: " .. name .. " - " .. shown .. " (" .. source .. ")")
        end
    end
end
