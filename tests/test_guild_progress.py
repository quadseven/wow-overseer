"""The Guild view's Progress tab (app/views/guild.js), rendered under node
from canned reads, the way test_guild_view.py renders the Chronicle:
the readiness strip from /api/v2/raidteams (#3374), the problem-first
tiles, and the bank summary card.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}

GUILD = {
    "guild": "Cave",
    "count": 4,
    "online": 3,
    "faction": "Alliance",
    "gaining": [{"name": "Grug"}],
    "deaths": {
        "total": 5,
        "ghosts": [
            {
                "name": "Diggo",
                "killer": "Gordok Brute",
                "where": "Western Plaguelands",
                "at": None,
            }
        ],
        "killers": [{"killer": "Gordok Brute", "members": 3, "n": 9}],
    },
    "class_quests": {
        "done": 644,
        "open": 72,
        "blocked": 6,
        "rows": [
            {
                "member": "Grug",
                "class": "Warrior",
                "quest": "Warrior chain",
                "state": "blocked",
                "note": "waiting on a drop",
                "at": None,
            },
            {
                "member": "Ugga",
                "class": "Priest",
                "quest": "Priest chain",
                "state": "blocked",
                "note": "waiting on a drop",
                "at": None,
            },
            {
                "member": "Og",
                "class": "Mage",
                "quest": "Mage chain",
                "state": "open",
                "note": "",
                "at": None,
            },
        ],
    },
    "dungeons": [
        {
            "place": "Molten Core",
            "floor": 60,
            "ceiling": 60,
            "cleared": 2,
            "runs": 3,
            "wiped": 1,
            "last_at": None,
            "inside": False,
            "lesson": None,
        }
    ],
    "members": [
        {"name": "Grug", "level": 60, "class": "Warrior", "ghost": False},
        {"name": "Ugga", "level": 60, "class": "Priest", "ghost": False},
        {"name": "Grog", "level": 46, "class": "Paladin", "ghost": False},
        {"name": "Og", "level": 36, "class": "Mage", "ghost": True},
    ],
}


def seat(name, role, level):
    return {
        "name": name,
        "class": "Warrior",
        "seat": role,
        "approved": name or "Hopeful",
    }


def teams(gaps=None, open_seat=False):
    g1 = [
        seat("A", "tank", 60),
        seat("B", "healer", 60),
        seat("C", "dps", 60),
        seat("D", "dps", 60),
        seat("E", "dps", 46),
    ]
    g2 = [
        seat("F", "tank", 60),
        seat("G", "healer", 60),
        seat("H", "healer", 60),
        seat("I", "dps", 60),
        seat("J", "dps", 36),
    ]
    if open_seat:
        g2[0] = {
            "name": None,
            "class": "Warrior",
            "seat": "tank",
            "approved": "Hopeful",
        }
    members = {}
    for s in g1 + g2:
        if s["name"]:
            members[s["name"]] = {
                "level": {
                    "A": 60,
                    "B": 60,
                    "C": 60,
                    "D": 60,
                    "E": 46,
                    "F": 60,
                    "G": 60,
                    "H": 60,
                    "I": 60,
                    "J": 36,
                }[s["name"]]
            }
    return {
        "guild": "Cave",
        "groups": [[s["name"] for s in g1], [s["name"] for s in g2]],
        "gaps": gaps or {"tanks": 0, "healers": 0, "damage": 0},
        "seats": [g1, g2],
        "members": members,
    }


BANK = {
    "guild": "Cave",
    "money": {"gold": 54, "silver": 0, "copper": 0},
    "tabs": [
        {"tab": 0, "name": "Materials", "used": 86, "total": 98, "cells": []},
        {"tab": 1, "name": "Gear for Later", "used": 44, "total": 98, "cells": []},
    ],
}

SEED = {
    "/api/v2/guild?guild=cave": GUILD,
    "/api/v2/series?guild=cave": {
        "xp_per_hour": [],
        "measured": 0,
        "members": 4,
        "basis": "basis",
    },
    "/api/v2/roster": {
        "members": [
            {
                "name": "Grug",
                "guild": "Cave",
                "stuck": True,
                "online": True,
                "life": "alive",
                "since": None,
            }
        ],
        "checked_at": 0,
    },
    "/api/v2/raidteams?guild=cave": teams(),
    "/api/client/guildbank?name=Grug": BANK,
}


def render(seed=None, tab="progress", query=None):
    seed = SEED if seed is None else seed
    view_uri = (APP / "views" / "guild.js").as_uri()
    ctx = {
        "view": "guild",
        "section": "guilds",
        "params": {"guild": "cave", "tab": tab},
        "query": query or {},
        "hash": "#/guilds/cave" if tab == "progress" else "#/guilds/cave/" + tab,
        "isPhone": False,
    }
    code = (
        "globalThis.window = {setTimeout: (f) => f(), addEventListener() {},"
        " matchMedia: () => ({matches: false})};\n"
        "globalThis.location = {hash: %s};\n"
        "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
        "globalThis.history = {replaceState() {}};\n"
        "const FAM = await import(new URL('../families.js', %s).href);\n"
        "FAM.learn(%s);\n"
        "const API = await import(new URL('../api.js', %s).href);\n"
        "globalThis.fetch = async (url) => ({ok: true, status: 200, text: async () => JSON.stringify(%s[url])});\n"
        "await Promise.all(Object.keys(%s).map((p) => API.load(p)));\n"
        "const V = (await import(%s)).default;\n"
        "const out = V.render(%s);\n"
        "console.log(JSON.stringify(String(out.s)));\n"
    ) % (
        json.dumps(ctx["hash"]),
        json.dumps(view_uri),
        json.dumps(REALM),
        json.dumps(view_uri),
        json.dumps(seed),
        json.dumps(seed),
        json.dumps(view_uri),
        json.dumps(ctx),
    )
    out = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheReadinessStrip(unittest.TestCase):
    def test_the_strip_states_cap_groups_seats_and_the_weakest_group(self):
        out = render()
        self.assertIn("Raid readiness", out)
        self.assertIn("At cap (level 60)", out)
        self.assertIn("2 of 4", out)
        self.assertIn("Raid groups formed", out)
        self.assertIn("2 formed", out)
        self.assertIn("0 seats open", out)
        self.assertIn("10 seats, all filled", out)
        self.assertIn("tanks 2", out)
        self.assertIn("healers 3", out)
        self.assertIn("damage 5", out)
        self.assertIn("Weakest group", out)
        self.assertIn("Group 2, lowest member 36", out)
        self.assertIn("#/raid/mc/cave", out)

    def test_one_tick_per_seat_and_a_filled_seat_is_lit(self):
        out = render()
        start = out.index('class="g-ticks"')
        strip = out[start : out.index("</div>", start)]
        self.assertEqual(strip.count("<i"), 10)
        self.assertEqual(strip.count('class="on"'), 10)

    def test_an_open_seat_reads_as_open_and_bad(self):
        seed = dict(SEED)
        seed["/api/v2/raidteams?guild=cave"] = teams(
            gaps={"tanks": 1, "healers": 0, "damage": 0}, open_seat=True
        )
        out = render(seed)
        self.assertIn("1 formed", out)
        self.assertIn("9 of 10 seats filled", out)
        self.assertIn('data-gt="bad"', out)
        self.assertIn("1 tank seat open", out)
        start = out.index('class="g-ticks"')
        strip = out[start : out.index("</div>", start)]
        self.assertEqual(strip.count('class="on"'), 9)

    def test_an_empty_teams_read_is_not_measured_never_a_made_up_zero(self):
        seed = dict(SEED)
        seed["/api/v2/raidteams?guild=cave"] = {}
        out = render(seed)
        self.assertIn("Raid readiness", out)
        self.assertIn("not measured", out)
        self.assertNotIn("0 seats open", out)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheSwitcherStaysOnAPhone(unittest.TestCase):
    def test_the_mobile_rules_keep_the_switcher_and_make_it_tappable(self):
        css = (APP / "views" / "guild.css").read_text(encoding="utf-8")
        self.assertNotIn(".g-pick { display: none; }", css)
        mobile = css.split("@media (max-width: 759.98px)", 1)[1][:600]
        self.assertIn(".g-pick", mobile)
        self.assertIn("44px", mobile)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheProblemFirstTiles(unittest.TestCase):
    def tiles(self, out):
        return out[out.index('class="g-kpis"') : out.index('class="g-two"')]

    def test_the_tiles_lead_with_problems_in_order(self):
        tiles = self.tiles(render())
        order = [
            tiles.index(w)
            for w in ["Stuck", "Ghosts now", "Blocked class quests", "Gaining XP"]
        ]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("Median level", tiles)
        self.assertNotIn("Class quests done", tiles)

    def test_each_tile_names_its_window(self):
        tiles = self.tiles(render())
        self.assertIn("right now, of 4 members", tiles)
        self.assertIn("72 open · 644 done, all time", tiles)
        self.assertIn("in the last 24h, of 4 members", tiles)

    def test_live_problems_carry_their_tones(self):
        tiles = self.tiles(render())
        self.assertIn('Stuck</span><span class="v" data-gt="warn">1</span>', tiles)
        self.assertIn('Ghosts now</span><span class="v" data-gt="bad">1</span>', tiles)
        self.assertIn(
            'Blocked class quests</span><span class="v" data-gt="warn">6</span>', tiles
        )

    def test_the_blocked_tile_lands_on_the_blocked_filter(self):
        self.assertIn("#/guilds/cave?cq=blocked", self.tiles(render()))


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheProgressOrder(unittest.TestCase):
    def test_deaths_sit_above_the_xp_card(self):
        out = render()
        self.assertLess(out.index("Raid readiness"), out.index("Deaths and ghosts"))
        self.assertLess(out.index("Deaths and ghosts"), out.index("XP per hour"))

    def test_the_dungeon_card_says_its_count_is_all_time(self):
        self.assertIn("2 clears, all time", render())


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheClassQuestFilter(unittest.TestCase):
    def card(self, out):
        return out[out.index("Class quests") : out.index("Dungeons, level order")]

    def test_the_card_carries_both_filter_chips_and_shows_everything_by_default(self):
        card = self.card(render())
        self.assertIn("Blocked only (6)", card)
        self.assertIn('data-cq="blocked"', card)
        self.assertIn('data-cq="all"', card)
        self.assertIn("Mage chain", card)

    def test_the_blocked_tile_link_lands_on_a_filtered_card(self):
        card = self.card(render(query={"cq": "blocked"}))
        self.assertIn("Warrior chain", card)
        self.assertIn("Priest chain", card)
        self.assertNotIn("Mage chain", card)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheBankSummaryCard(unittest.TestCase):
    def test_the_card_sums_the_vault_and_links_with_the_guild(self):
        out = render()
        self.assertIn("Guild bank, Cave vault", out)
        self.assertIn("54g 00s", out)
        self.assertIn("fullest tab: Materials, 86 of 98", out)
        self.assertIn("130 stacks in 2 tabs", out)
        self.assertIn("Open the guild bank", out)
        self.assertIn("#/economy/bank?guild=cave", out)

    def test_the_header_carries_a_bank_tab_with_the_guild(self):
        out = render()
        tabs_row = out[out.index('class="tabs"') : out.index('class="g-kpis"')]
        self.assertIn("Guild bank", tabs_row)
        self.assertIn("#/economy/bank?guild=cave", tabs_row)

    def test_a_vault_with_no_tabs_shows_its_note_not_a_made_up_sum(self):
        seed = dict(SEED)
        seed["/api/client/guildbank?name=Grug"] = {
            "guild": "Cave",
            "note": "The bank bot has not read the vault yet.",
            "tabs": [],
        }
        out = render(seed)
        self.assertIn("The bank bot has not read the vault yet.", out)
        self.assertNotIn("fullest tab", out)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheJumpRows(unittest.TestCase):
    def test_runs_puts_seats_second_and_every_jump_target_exists(self):
        out = render(tab="runs")
        self.assertLess(
            out.index("Groups out now"), out.index("Tanks and healers ready")
        )
        self.assertLess(
            out.index("Tanks and healers ready"), out.index("How they came back")
        )
        for target in [
            "g-sec-out",
            "g-sec-seats",
            "g-sec-back",
            "g-sec-learned",
            "g-sec-path",
            "g-sec-timelines",
        ]:
            self.assertIn('data-jump="' + target + '"', out)
            self.assertIn('id="' + target + '"', out)

    def test_chronicle_carries_a_jump_row_over_its_eight_sections(self):
        out = render(tab="chronicle")
        for target in [
            "g-sec-now",
            "g-sec-done",
            "g-sec-loot",
            "g-sec-council",
            "g-sec-sittings",
            "g-sec-chat",
            "g-sec-clips",
            "g-sec-journeys",
        ]:
            self.assertIn('data-jump="' + target + '"', out)
            self.assertIn('id="' + target + '"', out)


if __name__ == "__main__":
    unittest.main()
