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
    "/api/loot": {"stories": [], "empty": "none", "basis": ""},
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


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's views")
class TheGuildChatFeed(unittest.TestCase):
    def test_state_badge_on_every_ask(self):
        out = render()
        self.assertIn('class="g-chat-state" data-gt="">open</span>', out)
        self.assertIn('class="g-chat-state" data-gt="good">filled</span>', out)
        self.assertIn('class="g-chat-state" data-gt="good">ran</span>', out)
        self.assertIn('class="g-chat-state" data-gt="bad">expired</span>', out)

    def test_run_link_renders_for_an_ask_that_ran(self):
        out = render()
        self.assertIn("The run cleared", out)


if __name__ == "__main__":
    unittest.main()
