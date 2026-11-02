"""The Guild view (app/views/guild.js): the Chronicle's chat feed (#570).

Rendered under node from canned reads, the way test_measured_views.py renders
its views: one ask in each state, and the state badge shows on every one.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}],
    "guilds": [{"name": "Cave", "family": "Grug"}],
}

SEED = {
    "/api/v2/guild?guild=cave": {
        "guild": "Cave",
        "count": 1,
        "gaining": [],
        "deaths": {"ghosts": [], "total": 0},
        "class_quests": {"done": 0, "open": 0, "blocked": 0},
        "online": 1,
        "faction": "Alliance",
    },
    "/api/guildruns": [],
    "/api/v2/chronicle?guild=cave": {"items": []},
    "/api/loot": {
        "stories": [
            {
                "guild": "Cave",
                "at": "2026-11-01T17:29:12",
                "line": "Sogg won Buzzer Blade on a need roll from Sneed's "
                "Shredder in The Deadmines and equipped it.",
                "item": {"entry": 5196, "name": "Buzzer Blade", "quality": 3},
            }
        ],
        "empty": "none",
        "basis": "",
    },
    "/api/recap": {"families": []},
    "/api/council": {"families": []},
    "/api/guildchat?guild=Cave": {
        "guild": "Cave",
        "guilds": ["Cave"],
        "ready": True,
        "asks": [
            {
                "id": 1,
                "asker": "A",
                "said": "open ask",
                "created_at": "2026-10-04 12:00:00",
                "state": "open",
                "answers": [],
                "run": None,
            },
            {
                "id": 2,
                "asker": "B",
                "said": "filled ask",
                "created_at": "2026-10-04 12:00:00",
                "state": "filled",
                "answers": [{"member": "C", "said": "yes", "created_at": "x"}],
                "run": None,
            },
            {
                "id": 3,
                "asker": "D",
                "said": "ran ask",
                "created_at": "2026-10-04 12:00:00",
                "state": "ran",
                "answers": [{"member": "E", "said": "yes"}],
                "run": {
                    "outcome": "cleared",
                    "state": "ended",
                    "bosses_done": 1,
                    "bosses_total": 1,
                },
            },
            {
                "id": 4,
                "asker": "F",
                "said": "expired ask",
                "created_at": "2026-10-04 12:00:00",
                "state": "expired",
                "answers": [{"member": "G", "said": "late"}],
                "run": None,
            },
            {
                "id": 5,
                "asker": "H",
                "said": "unentered ask",
                "created_at": "2026-10-04 12:00:00",
                "state": "ran",
                "answers": [{"member": "I", "said": "yes"}],
                "run": {"outcome": "not entered", "state": "ended"},
            },
            {
                "id": 6,
                "asker": "J",
                "said": "short ask",
                "created_at": "2026-10-04 12:00:00",
                "state": "ran",
                "answers": [{"member": "K", "said": "yes"}],
                "run": {
                    "outcome": "cleared",
                    "state": "ended",
                    "bosses_done": 5,
                    "bosses_total": 6,
                },
            },
        ],
    },
    "/api/v2/achievements?guild=cave": {"items": [], "guilds": ["Cave"]},
}


def render():
    view_uri = (APP / "views" / "guild.js").as_uri()
    code = (
        "globalThis.window = {setTimeout: (f) => f(), addEventListener() {},"
        " matchMedia: () => ({matches: false})};\n"
        "globalThis.location = {hash: '#/guilds/cave/chronicle'};\n"
        "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
        "globalThis.history = {replaceState() {}};\n"
        "const FAM = await import(new URL('../families.js', %s).href);\n"
        "FAM.learn(%s);\n"
        "const API = await import(new URL('../api.js', %s).href);\n"
        "globalThis.fetch = async (url) => ({ok: true, status: 200, text: async () => JSON.stringify(%s[url])});\n"
        "await Promise.all(Object.keys(%s).map((p) => API.load(p)));\n"
        "const V = (await import(%s)).default;\n"
        "const out = V.render({view:'guild',section:'guild',params:{guild:'cave',tab:'chronicle'},query:{},hash:location.hash,isPhone:false,get:(p)=>API.peek(p)});\n"
        "console.log(JSON.stringify(String(out.s)));\n"
    ) % (
        json.dumps(view_uri),
        json.dumps(REALM),
        json.dumps(view_uri),
        json.dumps(SEED),
        json.dumps(SEED),
        json.dumps(view_uri),
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


def asks(out):
    """Each ask's rendered block, keyed by what the asker said."""
    blocks = out.split('<div class="g-chat">')[1:]
    return {
        said: b
        for b in blocks
        for said in (
            "open ask",
            "filled ask",
            "ran ask",
            "expired ask",
            "unentered ask",
            "short ask",
        )
        if said in b
    }


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheGuildChatFeed(unittest.TestCase):
    def test_state_badge_on_every_ask(self):
        got = asks(render())
        want = {
            "open ask": ("accent", "open"),
            "filled ask": ("ok", "filled"),
            "ran ask": ("ok", "ran"),
            "unentered ask": ("ok", "ran"),
            "short ask": ("ok", "ran"),
            "expired ask": ("warn", "expired"),
        }
        self.assertEqual(set(got), set(want))
        for said, (tone, st) in want.items():
            with self.subTest(ask=said):
                self.assertIn(
                    'g-ask-state" data-gt="%s">%s</span>' % (tone, st), got[said]
                )

    def test_filled_and_expired_asks_with_answers_still_show_their_state(self):
        got = asks(render())
        for said, st in (("filled ask", "filled"), ("expired ask", "expired")):
            with self.subTest(ask=said):
                self.assertNotIn("No answer", got[said])
                self.assertIn(">%s</span>" % st, got[said])

    def test_a_run_with_bosses_left_is_not_called_cleared(self):
        self.assertIn(
            "The run finished, 5 of 6 bosses</a>", asks(render())["short ask"]
        )

    def test_a_run_that_never_went_in_reads_as_a_sentence(self):
        self.assertIn("The run never went in</a>", asks(render())["unentered ask"])

    def test_a_loot_line_holds_the_item_link_where_it_names_the_item(self):
        rendered = render()
        self.assertIn("Sogg won <a ", rendered)
        self.assertIn(
            "Buzzer Blade</span></a> on a need roll from Sneed&#39;s Shredder",
            rendered,
        )
        self.assertNotIn("Sogg won Buzzer Blade", rendered)

    def test_run_link_renders_for_an_ask_that_ran(self):
        got = asks(render())
        self.assertIn("The run cleared, 1 of 1 bosses</a>", got["ran ask"])


if __name__ == "__main__":
    unittest.main()
