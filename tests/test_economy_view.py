"""The Economy view (app/views/economy.js), rendered under node from canned
reads: what it draws from the server's payloads and what it says when a
number is missing. The search provider's groups (app/searchv2.js) too.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"


# The families and guilds /api/realm reports; app/families.js learns them
# before a view is drawn, as main.js does before the first route.
REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}


def learn(root):
    """The line that teaches the copied app the realm's families and guilds."""
    return "(await import(%s)).learn(%s);\n" % (
        json.dumps((root / "families.js").as_uri()),
        json.dumps(REALM),
    )


def render(script):
    """Run `script` with the app copied to a module package; V is the view."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = (
            "globalThis.window = {setTimeout: (f) => f()}; globalThis.location = {hash: '#/now'};\n"
            "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
            "%s"
            "const V = (await import(%s)).default;\n"
            "const S = await import(%s);\n"
            "function ctx(tab, query, reads) {\n"
            "  return {view: 'economy', section: 'economy', params: {tab}, query: query || {}, hash: '',\n"
            "    isPhone: false, get: (p) => (p in reads ? {data: reads[p], at: 1, error: null}"
            " : {data: undefined, at: 0, error: null, loading: true})};\n"
            "}\n%s"
        ) % (
            learn(root),
            json.dumps((root / "views" / "economy.js").as_uri()),
            json.dumps((root / "searchv2.js").as_uri()),
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


LISTING = {
    "item": {
        "entry": 2589,
        "name": "Linen Cloth",
        "quality": 1,
        "icon": "inv_fabric_linen_01",
        "count": 20,
    },
    "owner": "Grug",
    "has_bid": False,
    "start": {"total": 150},
    "bid": {"total": 0},
    "buyout_label": None,
    "buyout": {"total": 0},
    "expires_at": None,
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheEconomyView(unittest.TestCase):
    def test_our_listings_are_a_table_and_cards(self):
        wealth = {
            "auctions": {
                "listings": [LISTING],
                "any": True,
                "tracked": False,
                "caveat": "Live only.",
            }
        }
        got = render(
            "const c = ctx('auction', {}, {'/api/wealth': {family: {}, auctions: %s}});\n"
            "console.log(JSON.stringify({reads: V.reads(c), html: V.render(c).s}));"
            % json.dumps(wealth["auctions"])
        )
        self.assertEqual(got["reads"], ["/api/wealth"])
        html = got["html"]
        self.assertIn('data-item="2589"', html)
        self.assertIn("eco-auc-table", html)
        self.assertIn("eco-auc-cards", html)
        self.assertIn("1s 50c", html)
        # No buyout is a fact, no expiry is not measured.
        self.assertIn(">none<", html)
        self.assertIn("not measured", html)

    def test_a_missing_purse_is_not_measured_never_zero(self):
        member = {
            "name": "Grug",
            "class": "Warrior",
            "present": True,
            "money": None,
            "room": {"percent": 50, "tone": ""},
            "capacity": {"used": 8, "slots": 16},
            "containers": [],
            "guild": "Cave",
        }
        payload = {
            "members": [member],
            "sides": [{"family": "Grug", "guild": "Cave", "names": ["Grug"]}],
            "family": {},
        }
        got = render(
            "const c = ctx('gold', {}, {'/api/wealth': %s});\nconsole.log(JSON.stringify(V.render(c).s));"
            % json.dumps(payload)
        )
        self.assertIn("not measured", got)
        self.assertNotIn(">0c<", got)
        self.assertIn("#/m/Grug/bags", got)

    def test_an_opened_trade_reads_its_crafts_for_the_family_in_the_url(self):
        got = render(
            "console.log(JSON.stringify([V.reads(ctx('trades', {family: 'zug', open: '197'}, {})),"
            " V.reads(ctx('trades', {open: '197'}, {})), V.reads(ctx('bank', {}, {}))]));"
        )
        self.assertEqual(got[0], ["/api/trades", "/api/trades?skill=197&family=Zug"])
        self.assertEqual(got[1], ["/api/trades"])
        self.assertEqual(
            got[2],
            ["/api/client/guildbank?name=Grug", "/api/client/guildbank?name=Zug"],
        )

    def test_the_guild_bank_picks_the_guild_in_the_url(self):
        cave = {
            "guild": "Cave",
            "money": {"gold": 1, "silver": 0, "copper": 0},
            "tabs": [
                {
                    "tab": 0,
                    "name": "Materials",
                    "used": 1,
                    "total": 98,
                    "cells": [
                        None,
                        {
                            "entry": 7909,
                            "name": "Aquamarine",
                            "quality": 2,
                            "icon": "x",
                            "count": 20,
                        },
                    ],
                }
            ],
        }
        bonk = {
            "guild": "Bonkers",
            "money": {"gold": 0, "silver": 0, "copper": 0},
            "tabs": [],
            "note": "the guild has not bought a bank tab yet.",
        }
        reads = {
            "/api/client/guildbank?name=Grug": cave,
            "/api/client/guildbank?name=Zug": bonk,
        }
        got = render(
            "const r = %s;\nconsole.log(JSON.stringify([V.render(ctx('bank', {}, r)).s, V.render(ctx('bank', {guild: 'bonkers'}, r)).s]));"
            % json.dumps(reads)
        )
        self.assertIn('data-item="7909"', got[0])
        self.assertIn(">20<", got[0])
        self.assertIn("has not bought a bank tab", got[1])
        self.assertNotIn("data-item", got[1])

    def test_the_app_loads_the_realm_search(self):
        main = (APP / "main.js").read_text(encoding="utf-8")
        self.assertIn('import "./searchv2.js";', main)
        self.assertIn("addProvider(", (APP / "searchv2.js").read_text(encoding="utf-8"))

    def test_search_hits_link_where_the_brief_says(self):
        payload = {
            "members": [
                {
                    "name": "Grug",
                    "level": 42,
                    "class": "Warrior",
                    "guild": "Cave",
                    "online": True,
                }
            ],
            "items": [
                {"entry": 2589, "name": "Linen Cloth", "quality": 1, "item_level": 5}
            ],
            "quests": [
                {"quest": 83, "title": "Red Linen Goods", "holders": ["Bork", "Og"]}
            ],
            "dungeons": [{"map": 36, "name": "The Deadmines", "guild": "Bonkers"}],
            "runs": [
                {
                    "id": 424,
                    "guild": "Cave",
                    "place": "The Deadmines",
                    "state": "inside",
                    "when": "",
                }
            ],
        }
        got = render("console.log(JSON.stringify(S.groups(%s)));" % json.dumps(payload))
        by = {g["label"]: g["rows"][0] for g in got}
        self.assertEqual(by["Members"]["href"], "#/m/Grug")
        self.assertEqual(by["Items"]["item"], 2589)
        self.assertEqual(by["Quests"]["href"], "#/m/Bork/quests")
        self.assertEqual(by["Dungeons"]["href"], "#/guilds/bonkers/runs")
        self.assertEqual(by["Runs"]["href"], "#/runs/424")


if __name__ == "__main__":
    unittest.main()
