"""Startup ordering for the first view and its navigation badges.

These run the startup helpers and fetch layer under Node with a fake browser.
The realm read can be held open so route and badge requests are observable
before it answers.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
API = HERE / "app" / "api.js"
STARTUP = HERE / "app" / "startup.js"

PRELUDE = r"""
globalThis.__fetches = [];
globalThis.document = {
  querySelector: () => ({ getAttribute: () => "/dev" }),
  addEventListener: () => {},
  hidden: false,
};
globalThis.window = {
  sessionStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
  setTimeout: () => 0,
  clearTimeout: () => {},
};
let releaseRealm;
const realmResponse = new Promise((resolve) => { releaseRealm = resolve; });
globalThis.__releaseRealm = () => releaseRealm({
  ok: true,
  status: 200,
  text: async () => JSON.stringify({ families: [], guilds: [] }),
});
globalThis.fetch = (url) => {
  globalThis.__fetches.push(url);
  if (url.endsWith("/api/realm")) return realmResponse;
  return Promise.resolve({ ok: true, status: 200, text: async () => "{}" });
};
"""


def run(script):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        api = root / "api.mjs"
        startup = root / "startup.mjs"
        api.write_text(API.read_text(encoding="utf-8"), encoding="utf-8")
        startup.write_text(STARTUP.read_text(encoding="utf-8"), encoding="utf-8")
        code = (
            PRELUDE
            + f"const M = await import({json.dumps(api.as_uri())});\n"
            + f"const S = await import({json.dumps(startup.as_uri())});\n"
            + script
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


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app modules")
class FirstRouteStartup(unittest.TestCase):
    def test_independent_sections_start_their_view_and_reads_before_realm_answers(self):
        got = run(
            "const events = [];"
            "const realm = M.load('/api/realm');"
            "const paths = [['#/quests', 'quests'], ['#/members', 'members'], "
            "['#/economy', 'economy'], ['#/raid/mc/cave', 'raid'], ['#/now', 'now']];"
            "const routes = paths.map(([hash, view]) => "
            "S.waitForRouteRealm(hash, false, realm).then(() => {"
            "events.push('module:' + view);"
            "return M.load('/api/view-' + view).then(() => events.push('read:' + view));"
            "}));"
            "await new Promise((resolve) => setTimeout(resolve, 0));"
            "const before = {events: events.slice(), fetches: globalThis.__fetches.slice()};"
            "globalThis.__releaseRealm();"
            "await Promise.all([realm, ...routes]);"
            "console.log(JSON.stringify(before));"
        )
        self.assertEqual(
            got["events"],
            [
                "module:quests",
                "module:members",
                "module:economy",
                "module:raid",
                "module:now",
                "read:quests",
                "read:members",
                "read:economy",
                "read:raid",
                "read:now",
            ],
        )
        self.assertEqual(
            got["fetches"],
            [
                "/dev/api/realm",
                "/dev/api/view-quests",
                "/dev/api/view-members",
                "/dev/api/view-economy",
                "/dev/api/view-raid",
                "/dev/api/view-now",
            ],
        )

    def test_family_and_guild_routes_wait_for_the_realm_read(self):
        got = run(
            "const events = [];"
            "const realm = M.load('/api/realm');"
            "const routes = ['#/now/family/cave', '#/guilds/cave'].map((hash) => "
            "S.waitForRouteRealm(hash, false, realm).then(() => { events.push(hash); }));"
            "await new Promise((resolve) => setTimeout(resolve, 0));"
            "const before = {events: events.slice(), fetches: globalThis.__fetches.slice()};"
            "globalThis.__releaseRealm();"
            "await Promise.all([realm, ...routes]);"
            "console.log(JSON.stringify({before, after: events}));"
        )
        self.assertEqual(got["before"]["events"], [])
        self.assertEqual(got["before"]["fetches"], ["/dev/api/realm"])
        self.assertEqual(got["after"], ["#/now/family/cave", "#/guilds/cave"])

    def test_saved_realm_lists_let_family_routes_start_during_refresh(self):
        got = run(
            "const events = [];"
            "const realm = M.load('/api/realm');"
            "const route = S.waitForRouteRealm('#/guilds/cave', true, realm)"
            ".then(() => events.push('module'));"
            "await new Promise((resolve) => setTimeout(resolve, 0));"
            "const before = {events: events.slice(), fetches: globalThis.__fetches.slice()};"
            "globalThis.__releaseRealm();"
            "await Promise.all([realm, route]);"
            "console.log(JSON.stringify(before));"
        )
        self.assertEqual(got["events"], ["module"])
        self.assertEqual(got["fetches"], ["/dev/api/realm"])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app modules")
class BadgeStartup(unittest.TestCase):
    def test_badges_start_after_first_draw_and_keep_the_one_minute_refresh(self):
        got = run(
            "const events = []; const timers = [];"
            "const startBadges = S.afterFirstDraw(() => {"
            "events.push('badges');"
            "return M.loadAll(['/api/v2/chronicle', '/api/loot', '/api/v2/stuck']);"
            "}, 60000, (fn, ms) => { timers.push({fn, ms}); });"
            "await M.load('/api/view-quests');"
            "events.push('draw');"
            "const first = await startBadges();"
            "const again = startBadges();"
            "await timers[0].fn();"
            "console.log(JSON.stringify({events, fetches: globalThis.__fetches, "
            "first: first.length, again: again === null, "
            "interval: timers[0].ms, timerCount: timers.length}));"
        )
        self.assertEqual(got["events"], ["draw", "badges", "badges"])
        self.assertEqual(got["interval"], 60000)
        self.assertEqual(got["timerCount"], 1)
        self.assertTrue(got["again"])
        self.assertEqual(
            got["fetches"],
            [
                "/dev/api/view-quests",
                "/dev/api/v2/chronicle",
                "/dev/api/loot",
                "/dev/api/v2/stuck",
                "/dev/api/v2/chronicle",
                "/dev/api/loot",
                "/dev/api/v2/stuck",
            ],
        )


class MainStartupWiring(unittest.TestCase):
    def test_main_waits_before_resolving_family_and_guild_routes(self):
        """The app has no DOM harness, so pin the Node-tested gate's call site."""
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        wait = main.index("await waitForRouteRealm(hash, hasRealmLists(), realmReady)")
        resolve = main.index("const old = legacy(hash)")
        self.assertLess(wait, resolve)

    def test_main_starts_badges_after_the_route_has_drawn_and_started_reads(self):
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        draw = main.index("draw(!fresh)")
        view_reads = main.index("api.watch(current.reads", draw)
        badges = main.index("startBadges();", view_reads)
        self.assertLess(draw, view_reads)
        self.assertLess(view_reads, badges)
        self.assertIn("afterFirstDraw(refreshBadges, 60000", main)


if __name__ == "__main__":
    unittest.main()
