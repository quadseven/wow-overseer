"""Meter.lua: the threat and damage panel a stream viewer reads.

The panel only exists inside a running client, so these tests run the real file
under a real Lua 5.1, the language version of the 3.3.5a client (build 12340),
with a stub of the client API. They read what the panel paints, not its
internals.

THE COMBAT LOG FIXTURES ARE THE 3.3.5a LAYOUT: eight base arguments, with no
hideCaster and no raid flags, which only arrived in later clients. A swing puts
the amount first. A spell puts spellId, spellName and school first. Overkill
comes right after the amount and is -1 when there is none.
"""

import pathlib
import re
import unittest

try:
    from lupa.lua51 import LuaRuntime
except ImportError:  # the lane check's plain python3; CI installs it
    LuaRuntime = None

ADDON = pathlib.Path(__file__).resolve().parents[1] / "wow-addons/PartyStatus"
NO_LUPA = "needs lupa (pip install -r tests/requirements.txt); CI installs it"

CLIENT_STUB = r"""
now = 100
units = {}
threat = {}
frames = {}
STANDARD_TEXT_FONT = "font"
RAID_CLASS_COLORS = setmetatable({}, { __index = function()
    return { r = 0.5, g = 0.5, b = 0.5 } end })
function GetTime() return now end
local function field(u, k) local e = units[u]; return e and e[k] end
function UnitExists(u) return units[u] ~= nil end
function UnitName(u) return field(u, "name") end
function UnitGUID(u) return field(u, "guid") end
function UnitClass(u) return field(u, "class"), field(u, "class") end
function UnitAffectingCombat(u) return field(u, "combat") end
function UnitCanAttack(_, u) return field(u, "hostile") end
function UnitIsDead(u) return field(u, "dead") end
function UnitDetailedThreatSituation(u, mob)
    local t = threat[u .. ">" .. mob]
    if not t then return nil end
    return t[1], 3, t[2], t[2], t[2] * 100
end
local method = {}
function method:SetScript(k, f) self.scripts[k] = f end
function method:RegisterEvent(e) self.events[e] = true end
function method:Show() self.shown = true end
function method:Hide() self.shown = false end
function method:IsShown() return self.shown end
function method:SetText(t) self.text = t end
function method:GetText() return self.text end
function method:SetWidth(w) self.width = w end
function method:GetWidth() return self.width end
function method:SetPoint(...) self.point = { ... } end
function method:CreateFontString() return newFrame() end
function method:CreateTexture() return newFrame() end
local shape = { __index = function(_, k)
    return method[k] or function() end end }
function newFrame()
    local f = setmetatable(
        { scripts = {}, events = {}, shown = true, text = "" }, shape)
    frames[#frames + 1] = f
    return f
end
function CreateFrame() return newFrame() end
UIParent = newFrame()

function fire(event, ...)
    for _, f in ipairs(frames) do
        if f.events[event] and f.scripts.OnEvent then
            f.scripts.OnEvent(f, event, ...)
        end
    end
end
function tick(seconds)
    now = now + seconds
    for _, f in ipairs(frames) do
        if f.scripts.OnUpdate then f.scripts.OnUpdate(f, seconds) end
    end
end
function swing(src, amount, overkill)
    fire("COMBAT_LOG_EVENT_UNFILTERED", now, "SWING_DAMAGE", src, "s", 0,
         "mob-guid", "Mob", 0, amount, overkill or -1, 1, 0, 0, 0)
end
function spell(event, src, amount, overkill, dst)
    fire("COMBAT_LOG_EVENT_UNFILTERED", now, event, src, "s", 0,
         dst or "mob-guid", "Mob", 0, 133, "Fireball", 4, amount,
         overkill or -1, 4, 0, 0, 0)
end
function set_unit(u, name, guid, class, combat)
    units[u] = { name = name, guid = guid, class = class, combat = combat }
end
function set_mob(u, name) units[u] = { name = name, hostile = true } end
function set_threat(u, mob, tanking, pct) threat[u .. ">" .. mob] = { tanking, pct } end
"""


@unittest.skipIf(LuaRuntime is None, NO_LUPA)
class Panel(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(CLIENT_STUB)
        self.lua.execute((ADDON / "Meter.lua").read_text())
        self.g = self.lua.globals()
        self.g.set_unit("player", "Tank", "g-tank", "WARRIOR", False)
        self.g.set_unit("party1", "Mage", "g-mage", "MAGE", False)
        self.g.set_unit("party2", "Hunt", "g-hunt", "HUNTER", False)
        self.g.set_unit("partypet2", "Wolf", "g-wolf", "HUNTER", False)
        self.g.fire("PLAYER_LOGIN")
        self.g.tick(0.5)
        self.panel = self.g.PartyStatusMeter

    def combat(self, on=True):
        for unit in ("player", "party1", "party2"):
            self.g.units[unit].combat = on

    def rows(self):
        """Each visible row as the viewer reads it."""
        out = []
        for i in range(1, 6):
            row = self.panel.rows[i]
            if row.name.GetText(row.name):
                out.append(
                    tuple(
                        cell.GetText(cell)
                        for cell in (row.name, row.damage, row.dps, row.threat)
                    )
                )
        return out

    def shown(self):
        return self.panel.frame.IsShown(self.panel.frame)

    def title(self):
        return self.panel.title.GetText(self.panel.title)

    def fight(self):
        self.combat()
        self.g.tick(0.5)

    def test_it_is_loaded_by_the_toc(self):
        self.assertIn("Meter.lua", (ADDON / "PartyStatus.toc").read_text().split())

    def test_no_fight_shows_nothing(self):
        self.assertFalse(self.shown())

    def test_a_fight_counts_swings_and_every_spell_shape(self):
        self.fight()
        self.g.swing("g-tank", 100)
        self.g.spell("SPELL_DAMAGE", "g-mage", 300)
        self.g.spell("SPELL_PERIODIC_DAMAGE", "g-mage", 50)
        self.g.spell("RANGE_DAMAGE", "g-hunt", 70)
        self.g.spell("DAMAGE_SHIELD", "g-tank", 5)
        self.g.tick(10)
        self.assertTrue(self.shown())
        self.assertEqual(
            self.rows(),
            [
                ("Mage", "350", "35", "--"),
                ("Tank", "105", "11", "--"),
                ("Hunt", "70", "7", "--"),
            ],
        )

    def test_overkill_is_not_damage(self):
        self.fight()
        self.g.swing("g-tank", 100, 40)
        self.g.spell("SPELL_DAMAGE", "g-mage", 100, 90)
        self.g.tick(0.5)
        by_name = {row[0]: row[1] for row in self.rows()}
        self.assertEqual(by_name["Tank"], "60")
        self.assertEqual(by_name["Mage"], "10")

    def test_a_pet_counts_for_its_owner(self):
        self.fight()
        self.g.swing("g-wolf", 40)
        self.g.swing("g-hunt", 2)
        self.g.tick(0.5)
        self.assertEqual({row[0]: row[1] for row in self.rows()}["Hunt"], "42")

    def test_strangers_and_friendly_fire_do_not_count(self):
        self.fight()
        self.g.swing("g-stranger", 500)
        self.g.spell("SPELL_DAMAGE", "g-mage", 500, -1, "g-tank")
        self.g.tick(0.5)
        self.assertEqual({row[1] for row in self.rows()}, {"0"})

    def test_threat_on_the_watched_target_orders_the_rows(self):
        self.g.set_mob("target", "Ogre")
        self.g.set_threat("player", "target", True, 100)
        self.g.set_threat("party1", "target", False, 88.6)
        self.g.set_threat("party2", "target", False, 12)
        self.fight()
        self.g.spell("SPELL_DAMAGE", "g-mage", 900)
        self.g.tick(0.5)
        self.assertEqual(self.title(), "Ogre")
        self.assertEqual(
            [(row[0], row[3]) for row in self.rows()],
            [("Tank", "100%"), ("Mage", "89%"), ("Hunt", "12%")],
        )
        bars = [
            self.panel.rows[i].bar.GetWidth(self.panel.rows[i].bar) for i in (1, 2, 3)
        ]
        self.assertGreater(bars[0], bars[1])
        self.assertGreater(bars[1], bars[2])

    def test_a_selfbot_with_no_client_target_uses_the_mob_it_is_tanking(self):
        self.g.set_mob("party1target", "Other")
        self.g.set_mob("party2target", "Ogre")
        self.g.set_threat("player", "party2target", True, 100)
        self.g.set_threat("party2", "party2target", False, 40)
        self.fight()
        self.g.tick(0.5)
        self.assertEqual(self.title(), "Ogre")
        self.assertEqual(self.rows()[0][3], "100%")

    def test_a_dead_target_falls_back_to_damage(self):
        self.g.set_mob("target", "Ogre")
        self.g.units["target"].dead = True
        self.fight()
        self.g.swing("g-tank", 10)
        self.g.tick(0.5)
        self.assertEqual(self.title(), "Damage")

    def test_large_numbers_stay_short(self):
        self.fight()
        self.g.swing("g-tank", 12345)
        self.g.tick(0.5)
        self.assertEqual(self.rows()[0][1], "12.3k")

    def test_a_short_gap_is_one_fight_and_a_new_pull_resets(self):
        self.fight()
        self.g.swing("g-tank", 100)
        self.combat(False)
        self.g.tick(0.5)
        self.combat()
        self.g.tick(0.5)
        self.g.swing("g-tank", 1)
        self.g.tick(0.5)
        self.assertEqual(self.rows()[0][1], "101")
        self.combat(False)
        self.g.tick(5)
        self.g.tick(0.5)
        self.combat()
        self.g.tick(0.5)
        self.g.swing("g-tank", 7)
        self.g.tick(0.5)
        self.assertEqual(self.rows()[0][1], "7")

    def test_the_finished_fight_lingers_then_leaves_the_screen(self):
        self.fight()
        self.g.swing("g-tank", 100)
        self.g.tick(10)
        self.combat(False)
        self.g.tick(5)
        self.g.tick(0.5)
        self.assertTrue(self.shown())
        frozen = self.rows()
        self.g.tick(10)
        self.assertEqual(self.rows(), frozen)
        self.g.tick(30)
        self.assertFalse(self.shown())


class Source(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lua = (ADDON / "Meter.lua").read_text()
        cls.code = "".join(
            line for line in lua.splitlines(True) if not line.strip().startswith("--")
        )

    def test_it_never_takes_a_click(self):
        self.assertIn("EnableMouse(false)", self.code)

    def test_it_only_watches(self):
        for call in (
            "TargetUnit",
            "CastSpell",
            "AssistUnit",
            "SendChatMessage",
            "RunMacro",
        ):
            self.assertNotIn(call, self.code)

    def test_the_panel_fits_between_the_party_frames_and_the_chat(self):
        # Units at uiScale 0.9: 1080 pixels are 853 units. The fourth party
        # frame ends near y=-392 and the chat buttons begin near y=-495.
        top = int(re.search(r"ANCHOR_Y = -(\d+)", self.code).group(1))
        row = int(re.search(r"ROW_HEIGHT = (\d+)", self.code).group(1))
        rows = int(re.search(r"ROW_COUNT = (\d+)", self.code).group(1))
        self.assertGreaterEqual(top, 392)
        self.assertLessEqual(top + (rows + 1) * row, 495)


if __name__ == "__main__":
    unittest.main()
