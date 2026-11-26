"""The gaming section view (app/views/gaming.js) and its route, for #2075.

Rendered under node from canned reads, the way test_economy_view.py runs
its view. No new data source: families, realm, roster and loot payloads
are the existing reads.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug", "size": 45},
        {"name": "Bonkers", "family": "Zug", "size": 12},
    ],
}

READS = {
    "/api/realm": REALM,
    "/api/family?family=Grug": {
        "family": "Grug",
        "members": [
            {
                "name": "Grug",
                "level": 42,
                "class": "Warrior",
                "zone": "Elwynn",
                "online": True,
            }
        ],
    },
    "/api/family?family=Zug": {
        "family": "Zug",
        "members": [
            {"name": "Zug", "level": 60, "class": "Druid", "zone": "", "online": False}
        ],
    },
    "/api/v2/roster": {
        "members": [
            {"name": "Grug", "level": 60, "guild": "Cave"},
            {"name": "Wug", "level": 60, "guild": "Cave"},
            {"name": "Zug", "level": 12, "guild": "Bonkers"},
        ]
    },
    "/api/loot": {
        "stories": [
            {
                "item": {"name": "Staff", "quality": 4},
                "guild": "Cave",
                "line": "Wug won Staff from Boss in Blackrock Depths and equipped it.",
                "at": "2026-11-01T10:00:00",
            }
        ]
    },
}


def run(module, script):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = (
            "globalThis.window = {setTimeout: (f) => f()};\n"
            "const F = await import(%s); F.learn(%s);\n"
            "const NS = await import(%s);\n"
            "const M = NS; const V = NS.default || NS;\n%s"
        ) % (
            json.dumps((root / "families.js").as_uri()),
            json.dumps(REALM),
            json.dumps((root / module).as_uri()),
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


def render(error_path=None):
    reads = {}
    for path, data in READS.items():
        entry = {"data": data, "at": 1700000000000, "error": None}
        if path == error_path:
            entry["error"] = "no answer"
        reads[path] = entry
    script = (
        "const reads = %s;\n"
        "const ctx = {view:'gaming', section:'gaming', params:{}, query:{}, hash:'#/gaming', "
        "get:(p)=> reads[p] || {data: undefined, at: 0, error: null, loading: true}};\n"
        "console.log(JSON.stringify({reads: V.reads(ctx), html: String(V.render(ctx).s || V.render(ctx))}));"
    ) % json.dumps(reads)
    return run("views/gaming.js", script)


@unittest.skipUnless(shutil.which("node"), "node is needed")
class GamingView(unittest.TestCase):
    def test_reads_cover_family_realm_roster_and_loot(self):
        got = render()
        for path in READS:
            self.assertIn(path, got["reads"])

    def test_renders_families_guilds_and_moments(self):
        html = render()["html"]
        self.assertIn("Grug", html)
        self.assertIn("Elwynn", html)
        self.assertIn("2 of 40 raid-ready (level 60)", html)
        self.assertIn("Staff", html)
        self.assertIn("Wug", html)
        self.assertIn("#/guilds/cave/chronicle", html)
        self.assertIn("Last sync", html)
        self.assertNotIn("stale", html.lower().split("last sync")[0])

    def test_failed_read_marks_section_stale(self):
        html = render(error_path="/api/loot")["html"]
        self.assertIn("stale", html.lower())


@unittest.skipUnless(shutil.which("node"), "node is needed")
class GamingRoute(unittest.TestCase):
    def test_gaming_resolves_and_is_a_section(self):
        got = run(
            "router.js",
            "console.log(JSON.stringify([M.resolve(M.parse('#/gaming')), M.SECTIONS]));",
        )
        self.assertEqual(got[0], {"view": "gaming", "section": "gaming", "params": {}})
        self.assertIn("gaming", got[1])


if __name__ == "__main__":
    unittest.main()
