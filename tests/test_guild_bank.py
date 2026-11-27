"""The guild bank under the Economy view (app/views/economy.js), rendered
under node from canned reads (#3374): the tab chip rail and read stamp,
the empty slots drawn, the split item marks, the list view, and the
last-viewed guild. Time is frozen so the read stamp is exact.
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

NOW = 1700000000000
AT = NOW - 40000  # every read landed 40 seconds before the frozen now


def run(script):
    code = (
        "globalThis.window = {setTimeout: (f) => f()};\n"
        "globalThis.location = {hash: '#/economy/bank'};\n"
        "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
        "Date.now = () => %d;\n"
        "const FAM = await import(%s);\n"
        "FAM.learn(%s);\n"
        "const E = await import(%s);\n"
        "const V = E.default;\n"
        "function ctx(tab, query, reads) {\n"
        "  return {view: 'economy', section: 'economy', params: {tab}, query: query || {}, hash: '',\n"
        "    isPhone: false, get: (p) => (p in reads ? {data: reads[p], at: %d, error: null}\n"
        "    : {data: undefined, at: 0, error: null, loading: true})};\n"
        "}\n%s"
    ) % (
        NOW,
        json.dumps((APP / "families.js").as_uri()),
        json.dumps(REALM),
        json.dumps((APP / "views" / "economy.js").as_uri()),
        AT,
        script,
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


def cell(entry, name, letters, count=1, quality=2, icon="inv_misc", category=None):
    c = {
        "entry": entry,
        "name": name,
        "quality": quality,
        "icon": icon,
        "letters": letters,
        "count": count,
    }
    if category is not None:
        c["category"] = category
        c["category_rank"] = 1
    return c


MATERIALS = {
    "tab": 0,
    "name": "Materials",
    "used": 3,
    "total": 8,
    "cells": [
        cell(2589, "Linen Cloth", "LC", 20),
        None,
        cell(2590, "Wool Cloth", "WC", 5),
        None,
        None,
        cell(2591, "Silk Cloth", "SC", 2),
        None,
        None,
    ],
}
GEAR = {
    "tab": 1,
    "name": "Gear for Later",
    "used": 3,
    "total": 98,
    "cells": [
        cell(999, "Libram of Rumination", "LO", 1, 3, icon=None),
        cell(1000, "Libram of Tenacity", "LO", 1, 3, icon=None),
        cell(1001, "Libram of Constitution", "LO", 1, 3, icon=None),
    ],
}
CAVE = {
    "guild": "Cave",
    "money": {"gold": 54, "silver": 0, "copper": 0},
    "tabs": [MATERIALS, GEAR],
}
BONK = {
    "guild": "Bonkers",
    "money": {"gold": 0, "silver": 0, "copper": 0},
    "tabs": [],
    "note": "the guild has not bought a bank tab yet.",
}
READS = {
    "/api/client/guildbank?name=Grug": CAVE,
    "/api/client/guildbank?name=Zug": BONK,
}


def page(query=None, reads=None, tab="bank"):
    reads = READS if reads is None else reads
    return run(
        "console.log(JSON.stringify(V.render(ctx(%s, %s, %s)).s));"
        % (json.dumps(tab), json.dumps(query or {}), json.dumps(reads))
    )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheTabRailAndStamp(unittest.TestCase):
    def test_the_tabs_are_chips_carrying_the_guild_not_cards(self):
        out = page()
        self.assertIn("Materials · 3/8", out)
        self.assertIn("Gear for Later · 3/98", out)
        self.assertIn("guild=cave", out)
        self.assertIn("tab=0", out)
        self.assertNotIn("eco-btabs", out)
        self.assertNotIn("eco-btab", out)

    def test_the_current_tab_says_how_full_it_is(self):
        self.assertIn("Materials is 38 percent full", page())

    def test_a_nearly_full_tab_warns(self):
        full = {
            "tab": 0,
            "name": "Full Tab",
            "used": 90,
            "total": 100,
            "cells": [cell(1, "Thing", "TH")],
        }
        reads = {
            "/api/client/guildbank?name=Grug": {
                "guild": "Cave",
                "money": {"gold": 0, "silver": 0, "copper": 0},
                "tabs": [full],
            }
        }
        out = page(reads=reads)
        self.assertIn("Full Tab is 90 percent full", out)
        self.assertIn("eco-bar warn", out)

    def test_the_stamp_names_the_read_age_and_the_vault_size(self):
        out = page()
        self.assertIn("read 40s ago", out)
        self.assertIn("6 stacks in 2 tabs", out)

    def test_the_bank_says_it_is_read_only(self):
        self.assertIn("Read only. The bank changes in game.", page())


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheEmptySlots(unittest.TestCase):
    def test_empty_slots_are_drawn(self):
        out = page()
        self.assertEqual(out.count('class="eco-cell eco-empty"'), 5)
        self.assertNotIn("eco-more", out)

    def test_a_mostly_empty_tab_caps_the_empties_with_a_counted_tail(self):
        out = page(query={"tab": 1})
        self.assertEqual(out.count('class="eco-cell eco-empty"'), 6)
        self.assertIn("+89 empty", out)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheItemMarks(unittest.TestCase):
    def test_colliding_marks_are_split_by_the_items_own_words(self):
        got = run(
            "console.log(JSON.stringify(Object.fromEntries(E.bankMarks(%s))));"
            % json.dumps(GEAR["cells"])
        )
        self.assertEqual(got, {"999": "LR", "1000": "LT", "1001": "LC"})

    def test_a_mark_nothing_collides_with_is_kept(self):
        items = [c for c in MATERIALS["cells"] if c]
        got = run(
            "console.log(JSON.stringify(Object.fromEntries(E.bankMarks(%s))));"
            % json.dumps(items)
        )
        self.assertEqual(got, {"2589": "LC", "2590": "WC", "2591": "SC"})

    def test_the_libram_tab_draws_the_split_marks(self):
        out = page(query={"tab": 1})
        for mark in ["LR", "LT", "LC"]:
            self.assertIn(">" + mark + "<", out)
        self.assertNotIn(">LO<", out)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheListViewAndTools(unittest.TestCase):
    def test_the_page_draws_both_views_and_the_tools(self):
        out = page()
        self.assertIn("data-bank-grid", out)
        self.assertIn("data-bank-list", out)
        self.assertIn('data-bank-mode="grid"', out)
        self.assertIn('data-bank-mode="list"', out)
        self.assertIn("data-bank-q", out)
        self.assertIn("Filter by item name", out)

    def test_the_list_merges_stacks_of_one_item(self):
        cells = [
            cell(2589, "Linen Cloth", "LC", 20),
            cell(2589, "Linen Cloth", "LC", 5),
            cell(2590, "Wool Cloth", "WC", 5),
        ]
        got = run(
            "console.log(JSON.stringify(E.bankListRows(%s).map((r) => [r.cell.entry, r.count])));"
            % json.dumps(cells)
        )
        self.assertEqual(got, [[2589, 25], [2590, 5]])

    def test_the_list_rows_show_the_summed_count(self):
        tab = {
            "tab": 0,
            "name": "Cloth",
            "used": 3,
            "total": 8,
            "cells": [
                cell(2589, "Linen Cloth", "LC", 20),
                cell(2589, "Linen Cloth", "LC", 5),
                cell(2590, "Wool Cloth", "WC", 5),
                None,
                None,
                None,
                None,
                None,
            ],
        }
        reads = {
            "/api/client/guildbank?name=Grug": {
                "guild": "Cave",
                "money": {"gold": 0, "silver": 0, "copper": 0},
                "tabs": [tab],
            }
        }
        out = page(reads=reads)
        listing = out[out.index("data-bank-list") : out.index("Read only")]
        self.assertIn("Linen Cloth", listing)
        self.assertIn('<span class="num">25</span>', listing)

    def test_the_panel_host_gets_the_grid_without_the_page_tools(self):
        got = run(
            "const c = ctx('guildbank', {}, %s);\nconsole.log(JSON.stringify(E.bankTab(c, c.get).s));"
            % json.dumps(READS)
        )
        self.assertNotIn("data-bank-q", got)
        self.assertNotIn("data-bank-list", got)
        self.assertIn("eco-grid", got)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheLastViewedGuild(unittest.TestCase):
    def test_the_bank_reopens_on_the_guild_last_viewed(self):
        got = run(
            "const r = %s;\n"
            "console.log(JSON.stringify([V.render(ctx('bank', {guild: 'bonkers'}, r)).s, V.render(ctx('bank', {}, r)).s]));"
            % json.dumps(READS)
        )
        self.assertIn("has not bought a bank tab", got[0])
        self.assertIn("has not bought a bank tab", got[1])

    def test_the_url_still_wins_over_the_last_viewed_guild(self):
        got = run(
            "const r = %s;\n"
            "V.render(ctx('bank', {guild: 'bonkers'}, r)).s;\n"
            "console.log(JSON.stringify(V.render(ctx('bank', {guild: 'cave'}, r)).s));"
            % json.dumps(READS)
        )
        self.assertIn("Materials · 3/8", got)

    def test_the_last_viewed_guild_is_written_to_storage(self):
        got = run(
            "const store = {};\n"
            "window.localStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; }};\n"
            "const r = %s;\n"
            "V.render(ctx('bank', {guild: 'bonkers'}, r)).s;\n"
            "console.log(JSON.stringify([store['overseer.bank-guild'], V.render(ctx('bank', {}, r)).s]));"
            % json.dumps(READS)
        )
        self.assertEqual(got[0], "bonkers")
        self.assertIn("has not bought a bank tab", got[1])


if __name__ == "__main__":
    unittest.main()
