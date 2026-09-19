-- Loot Card (infra#3334, follow-up)
--
-- WHAT THIS IS. When the family wins something, a card carrying the item's own
-- tooltip and a large line saying who got it, for a couple of minutes. On a
-- stream the whole moment - what dropped, is it any good, who has it now - is
-- currently a truncated icon and a chat line that scrolls away, and nobody is
-- at the keyboard to hover.
--
-- THE STATS ARE THE GAME'S. GameTooltip:SetHyperlink on the link that came
-- through chat makes the client draw its own tooltip, so a suffix, an enchant
-- or a random roll is right because the client drew it. Nothing here composes
-- an item, and nothing here should: a display that builds its own stats starts
-- lying the first time an item is not the plain case.
--
-- WHERE THE JUDGEMENT LIVES, AND IT IS NOT HERE. The quality bar, the dwell,
-- how many cards may be up, which of them keep their tooltip, the words in the
-- headline, which chat lines are loot AND THE ORDER TO TRY THEM IN are all
-- decided in production/scripts/wow-overseer/lootcard.py and covered by its
-- stdlib suite. tests/test_lootcard.py reads this file as text and fails when
-- the two drift. This file turns those format strings into patterns and paints.
--
-- THE FORMAT STRINGS ARE THE CLIENT'S. LOOT_ITEM and friends only exist inside
-- a running client, which is why the pattern building cannot move to Python;
-- writing "%s receives loot: %s." in English here is exactly what those globals
-- exist to prevent.
--
-- WHERE IT SITS. Bottom right, growing UP, and measured against a PrintWindow
-- capture of a live client rather than guessed. That column holds the buffs and
-- the minimap down to y=200 and the quest tracker to y=345, then nothing at all
-- until the action bar art begins around y=875; the whole bottom UI - bar, bags,
-- micro menu - is about 103 units tall, which ANCHOR_Y clears. Growing upward
-- means a busy pull extends into empty sky rather than down over the action
-- bar, and it is the opposite corner from the party frames and the chat log, so
-- this and the status labels cannot reach each other. The one thing that would
-- break it is turning on the right-hand vertical action bars, which are off on
-- these clients and would occupy this column.

local lootAddon = {}

-- Mirrors lootcard.py. Every one of these is a decision made there.
local MIN_QUALITY = 2
local DWELL_SECONDS = 120
local MAX_CARDS = 3
local MAX_EXPANDED = 2
local DEDUPE_SECONDS = 15
local HEADLINE_SIZE = 18
local ANCHOR_X = -12
local ANCHOR_Y = 130
local WON = "won"
local LOOTED = "looted"

-- (global name, winner argument, item argument, what happened). Argument 0
-- means the message has no name in it because the client wrote it about
-- itself, and the watched character's name is used instead.
--
-- THE ORDER IS LOAD-BEARING. "%s won: %s" also matches the "(Need - 76)" line
-- with the suffix swallowed into the item capture, and matches "You won: ..."
-- with a winner called "You". Specific before general, self before third
-- person. Reorder it and the wrong capture wins silently.
local MESSAGE_FORMS = {
    { "LOOT_ROLL_YOU_WON_NO_SPAM_NEED", 0, 2, WON },
    { "LOOT_ROLL_YOU_WON_NO_SPAM_GREED", 0, 2, WON },
    { "LOOT_ROLL_YOU_WON_NO_SPAM_DE", 0, 2, WON },
    { "LOOT_ROLL_WON_NO_SPAM_NEED", 1, 3, WON },
    { "LOOT_ROLL_WON_NO_SPAM_GREED", 1, 3, WON },
    { "LOOT_ROLL_WON_NO_SPAM_DE", 1, 3, WON },
    { "LOOT_ROLL_YOU_WON", 0, 1, WON },
    { "LOOT_ROLL_WON", 1, 2, WON },
    { "LOOT_ITEM_SELF_MULTIPLE", 0, 1, LOOTED },
    { "LOOT_ITEM_MULTIPLE", 1, 2, LOOTED },
    { "LOOT_ITEM_PUSHED_SELF_MULTIPLE", 0, 1, LOOTED },
    { "LOOT_ITEM_SELF", 0, 1, LOOTED },
    { "LOOT_ITEM", 1, 2, LOOTED },
    { "LOOT_ITEM_PUSHED_SELF", 0, 1, LOOTED },
}

local CARD_GAP = 6
local CARD_WIDTH = 300

-- --- turning a format string into a pattern ----------------------------------

-- Lua's magic characters, MINUS % and $. % is left alone because the
-- specifiers are made of it, and a $ inside a pattern is literal anywhere but
-- the last character - which is the one this appends itself.
local MAGIC = "([%^%(%)%.%[%]%*%+%-%?])"

local function compile(fmt)
    -- Returns an anchored pattern plus, for each capture in text order, which
    -- ARGUMENT it is. Positional forms like "%1$s won: %3$s ... %2$d" put the
    -- arguments out of order on purpose, so the two are not the same list.
    local order = {}
    local body = string.gsub(fmt, MAGIC, "%%%1")
    body = string.gsub(body, "%%(%d?)%$?([sd])", function(idx, kind)
        local at = #order + 1
        order[at] = tonumber(idx) or at
        if kind == "d" then return "(%d+)" end
        return "(.-)"
    end)
    return "^" .. body .. "$", order
end

local function captureFor(order, argIndex)
    for i = 1, #order do
        if order[i] == argIndex then return i end
    end
    return nil
end

local forms = nil

local function buildForms()
    -- Built once, at login, because the globals do not exist before FrameXML
    -- has loaded. A form whose global is missing on this build is skipped
    -- rather than crashing the file: an absent string is one loot message that
    -- goes unread, and a hard error is every one of them.
    forms = {}
    for _, spec in ipairs(MESSAGE_FORMS) do
        local fmt = _G[spec[1]]
        if type(fmt) == "string" then
            local pattern, order = compile(fmt)
            local item = captureFor(order, spec[3])
            if item then
                table.insert(forms, {
                    pattern = pattern,
                    winner = spec[2] > 0 and captureFor(order, spec[2]) or nil,
                    item = item,
                    verb = spec[4],
                })
            end
        end
    end
end

-- --- reading one loot message ------------------------------------------------

local function qualityOf(link)
    -- The cache first, the link's own colour second. The colour is in every
    -- link the server sends, so it answers before the item is cached, which
    -- matters: the message arrives at the same moment the item does.
    local cached = select(3, GetItemInfo(link))
    if cached then return cached end
    local hex = string.match(link, "^|c(%x%x%x%x%x%x%x%x)")
    if not hex then return nil end
    hex = string.lower("|c" .. hex)
    for q = 0, 7 do
        local colour = ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[q]
        if colour and colour.hex and string.lower(colour.hex) == hex then
            return q
        end
    end
    return nil
end

local function read(message)
    -- One chat line to { winner, link, verb }, or nil for anything that is not
    -- a loot line we care about. Money, rolls in progress and another addon's
    -- traffic all land here and all leave as nil.
    if not forms or not message then return nil end
    for _, form in ipairs(forms) do
        local caps = { string.match(message, form.pattern) }
        if caps[1] ~= nil then
            local field = caps[form.item]
            local link = field and string.match(field, "|c%x+|Hitem:.-|h.-|h|r")
            if link then
                return {
                    winner = form.winner and caps[form.winner] or "",
                    link = link,
                    verb = form.verb,
                }
            end
        end
    end
    return nil
end

-- --- the stack ---------------------------------------------------------------

local stack = {}
local enabled = true
local dirty = false

local function expire(now)
    local kept = {}
    for _, card in ipairs(stack) do
        if (now - card.at) < DWELL_SECONDS then table.insert(kept, card) end
    end
    local changed = #kept ~= #stack
    stack = kept
    return changed
end

local function admit(card, now)
    expire(now)
    for _, existing in ipairs(stack) do
        if existing.link == card.link and existing.winner == card.winner
                and (now - existing.at) <= DEDUPE_SECONDS then
            -- Group loot says one drop twice: the roll result, then the loot.
            -- Take the better wording and leave the clock alone, so the second
            -- telling cannot buy the same drop another two minutes.
            if existing.verb == LOOTED and card.verb == WON then
                existing.verb = WON
                existing.headline = card.headline
                dirty = true
            end
            return
        end
    end
    card.at = now
    table.insert(stack, card)
    while #stack > MAX_CARDS do
        -- Oldest off the front. The newest drop is the one somebody is
        -- watching for, so it must never be the one that is refused.
        table.remove(stack, 1)
    end
    dirty = true
end

-- --- painting ----------------------------------------------------------------

local anchor, cards = nil, {}

local function makeCard(i)
    local card = CreateFrame("Frame", nil, UIParent)
    card:SetWidth(CARD_WIDTH)
    card:SetHeight(HEADLINE_SIZE + CARD_GAP)
    card:EnableMouse(false)
    card:Hide()

    local head = card:CreateFontString(nil, "OVERLAY")
    -- OUTLINE, and large. This is read off a video on a phone, where a shadow
    -- is the first thing an encoder throws away and 12 point is unreadable.
    head:SetFont(STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF", HEADLINE_SIZE, "OUTLINE")
    head:SetPoint("TOPRIGHT", card, "TOPRIGHT", 0, 0)
    head:SetJustifyH("RIGHT")
    head:SetTextColor(1, 0.82, 0)
    card.head = head

    local tip = CreateFrame("GameTooltip", "PartyStatusLootTip" .. i, card,
                            "GameTooltipTemplate")
    -- MEDIUM, not the template's TOOLTIP. A card is furniture; a real tooltip
    -- somebody hovered must still draw over it.
    tip:SetFrameStrata("MEDIUM")
    tip:Hide()
    card.tip = tip
    return card
end

local function build()
    anchor = CreateFrame("Frame", nil, UIParent)
    anchor:SetWidth(1)
    anchor:SetHeight(1)
    anchor:SetPoint("BOTTOMRIGHT", UIParent, "BOTTOMRIGHT", ANCHOR_X, ANCHOR_Y)
    for i = 1, MAX_CARDS do cards[i] = makeCard(i) end
end

local function draw()
    if not anchor then return end
    local total = #stack
    for slot = 1, MAX_CARDS do
        local card = cards[slot]
        -- Slot 1 is the NEWEST and sits nearest the anchor, so the card a
        -- viewer is waiting for always appears in the same place instead of
        -- being shoved around by the ones before it.
        local entry = enabled and stack[total - slot + 1] or nil
        if not entry then
            card:Hide()
            card.tip:Hide()
        else
            card.head:SetText(entry.headline .. " " .. entry.link)
            local expanded = slot <= MAX_EXPANDED
            local height = HEADLINE_SIZE + CARD_GAP
            if expanded then
                card.tip:SetOwner(card, "ANCHOR_NONE")
                card.tip:ClearAllPoints()
                card.tip:SetPoint("TOPRIGHT", card, "TOPRIGHT", 0, -height)
                -- pcall: a malformed link throws, and one bad drop must cost
                -- its own card rather than every card after it.
                if pcall(card.tip.SetHyperlink, card.tip, entry.link) then
                    card.tip:Show()
                    height = height + card.tip:GetHeight()
                else
                    card.tip:Hide()
                end
            else
                card.tip:Hide()
            end
            card:SetHeight(height)
            card:ClearAllPoints()
            if slot == 1 then
                card:SetPoint("BOTTOMRIGHT", anchor, "BOTTOMRIGHT", 0, 0)
            else
                card:SetPoint("BOTTOMRIGHT", cards[slot - 1], "TOPRIGHT", 0, CARD_GAP)
            end
            card:Show()
        end
    end
end

-- --- driving -----------------------------------------------------------------

local TICK = 1.0
local since = 0
local settle = 0

local driver = CreateFrame("Frame")
driver:RegisterEvent("PLAYER_LOGIN")
driver:RegisterEvent("PLAYER_ENTERING_WORLD")
driver:RegisterEvent("CHAT_MSG_LOOT")

lootAddon.onLoot = function(message)
    if not enabled then return end
    local found = read(message)
    if not found then return end
    if not lootAddon.worthShowing(qualityOf(found.link)) then return end
    local who = found.winner
    if who == "" then who = UnitName("player") or "" end
    found.headline = who .. " " .. found.verb
    admit(found, GetTime())
end

lootAddon.worthShowing = function(quality)
    -- An item whose quality cannot be read is NOT shown. The colour is in
    -- every link the server sends, so an unreadable one means this reader is
    -- broken rather than that one unusual item arrived - and a broken reader
    -- that shows everything would put every grey on a permanent stream.
    if quality == nil then return false end
    return quality >= MIN_QUALITY
end

driver:SetScript("OnEvent", function(_, event, ...)
    if event == "CHAT_MSG_LOOT" then
        lootAddon.onLoot((...))
        return
    end
    if not forms then buildForms() end
    if not anchor then build() end
    draw()
end)

driver:SetScript("OnUpdate", function(_, elapsed)
    since = since + elapsed
    if dirty then
        dirty = false
        draw()
        -- Redraw once more next frame. A tooltip reports its height only after
        -- it has been laid out, so the first draw of a new card sizes the ones
        -- stacked above it against a height that is not final yet.
        settle = 2
    elseif settle > 0 then
        settle = settle - 1
        draw()
    end
    if since < TICK then return end
    since = 0
    if expire(GetTime()) then draw() end
end)

-- /loot        - hide the cards, or bring them back
-- /loot test   - put a card up for the first item in the bags, so the thing
--                can be seen without waiting for a dungeon to drop something
SLASH_PARTYSTATUSLOOT1 = "/loot"
SlashCmdList["PARTYSTATUSLOOT"] = function(arg)
    if arg == "test" then
        for bag = 0, 4 do
            for slot = 1, GetContainerNumSlots(bag) do
                local link = GetContainerItemLink(bag, slot)
                if link then
                    admit({ winner = UnitName("player") or "?", link = link,
                            verb = WON,
                            headline = (UnitName("player") or "?") .. " " .. WON },
                          GetTime())
                    DEFAULT_CHAT_FRAME:AddMessage("LootCard: showing " .. link)
                    return
                end
            end
        end
        DEFAULT_CHAT_FRAME:AddMessage("LootCard: nothing in the bags to show")
        return
    end
    enabled = not enabled
    dirty = true
    DEFAULT_CHAT_FRAME:AddMessage("LootCard: " .. (enabled and "on" or "off"))
end

-- Exposed on purpose. This is how a person at a client inspects what the
-- addon actually read out of a chat line, with /script and no debugger, and
-- it is how the local Lua harness drives all of it without a game running.
_G.PartyStatusLoot = lootAddon
lootAddon.read = read
lootAddon.compile = compile
lootAddon.stack = function() return stack end
lootAddon.cards = function() return cards end
