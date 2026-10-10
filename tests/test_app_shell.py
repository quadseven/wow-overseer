"""The operations app's shell: the page, the files it loads, the router, the
fetch layer's server half and the /api/v2 namespace.

The page is index.html; its modules live in app/ and are served one file at a
time from /app/. The classic page it replaced is gone, and /classic with it.
The router and the markup helpers are pure modules, run under node.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import basepath  # noqa: E402
import map_server  # noqa: E402
from apiv2 import operator as v2operator  # noqa: E402

PAGE = (HERE / "index.html").read_text(encoding="utf-8")
APP = HERE / "app"
APP_FILES = sorted(p for p in APP.rglob("*") if p.suffix in (".js", ".css"))


def node_module(module, script, realm=None):
    """Run `script` (ES module code) with `module` (a file in app/) imported
    as M. The app is copied whole beside a package.json saying it is ES
    modules, so a module's own imports resolve whatever node's version.
    `realm`, when given, is an /api/realm payload families.js learns first."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        learn = ""
        if realm is not None:
            learn = "import * as F from %s;\nF.learn(%s);\n" % (
                json.dumps((root / "families.js").as_uri()),
                json.dumps(realm),
            )
        dst = root / module
        code = "%simport * as M from %s;\n%s" % (
            learn,
            json.dumps(dst.as_uri()),
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


class FakeHandler(map_server.Handler):
    """A Handler with the socket cut off: a request in, what was sent out."""

    def __init__(self, path="/", headers=None, command="GET"):
        self.path = path
        self.command = command
        self.headers = headers or {}
        self.sent = []
        self.lines = []
        self.wfile = self

    # The real _send runs; only the socket is fake.
    def send_response(self, code, message=None):
        self.lines.append(("status", code))

    def send_header(self, key, value):
        self.lines.append((key, value))

    def end_headers(self):
        self.lines.append(("end", None))

    def write(self, body):
        self.sent.append(body)

    def status(self):
        return next(v for k, v in self.lines if k == "status")

    def header(self, name):
        return next((v for k, v in self.lines if k == name), None)

    def body(self):
        return b"".join(self.sent)


def get(path, headers=None):
    h = FakeHandler(path, headers)
    h.do_GET()
    return h


class ThePage(unittest.TestCase):
    def test_every_url_on_the_page_starts_at_the_mount(self):
        # A root-anchored URL on a page served under a prefix reads the realm
        # at the root (basepath.py). Every same-origin URL here is built on
        # the placeholder; the only other hosts are the font and icon CDNs.
        for m in re.finditer(r'(?:href|src)="([^"]+)"', PAGE):
            url = m.group(1)
            if url.startswith("https://"):
                self.assertTrue(
                    url.startswith(
                        (
                            "https://fonts.googleapis.com",
                            "https://fonts.gstatic.com",
                            "https://unpkg.com/@phosphor-icons/web@2.1.1/",
                        )
                    ),
                    url,
                )
                continue
            self.assertTrue(url.startswith(basepath.PLACEHOLDER + "/"), url)

    def test_the_page_tells_the_app_where_it_is_mounted(self):
        self.assertIn(
            '<meta name="overseer-base" content="%s">' % basepath.PLACEHOLDER, PAGE
        )
        app = (APP / "api.js").read_text(encoding="utf-8")
        self.assertIn('meta[name="overseer-base"]', app)
        self.assertIn("export function u(path)", app)

    def test_the_app_never_fetches_outside_the_mount_helper(self):
        for path in APP_FILES:
            if path.suffix != ".js":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"""fetch\(\s*["'`]/""", path.name)
            self.assertNotRegex(text, r"""import\(\s*["'`]/""", path.name)

    def test_the_icon_styles_are_pinned_by_integrity(self):
        links = re.findall(r"<link[^>]+unpkg\.com[^>]+>", PAGE)
        self.assertEqual(len(links), 2)
        for link in links:
            self.assertRegex(link, r'integrity="sha384-[A-Za-z0-9+/=]{64}"')
            self.assertIn('crossorigin="anonymous"', link)
        self.assertNotIn('<script src="https://', PAGE)

    def test_it_opens_full_screen_from_the_home_screen(self):
        for tag in (
            '<meta name="apple-mobile-web-app-capable" content="yes">',
            '<meta name="mobile-web-app-capable" content="yes">',
            "viewport-fit=cover",
            'rel="manifest" href="__OVERSEER_BASE__/manifest.webmanifest"',
            'rel="apple-touch-icon" href="__OVERSEER_BASE__/apple-touch-icon.png"',
        ):
            self.assertIn(tag, PAGE)

    def test_jquery_is_gone_from_the_app(self):
        # One exception, and only one: the paperdoll's model stage reuses the
        # classic Armory's 3D viewer, a third-party script that needs jQuery.
        # It loads both lazily, when a model comes near the screen; the page
        # and every other module stay free of it.
        self.assertNotIn("jquery", PAGE.lower())
        for path in APP_FILES:
            if path.relative_to(APP).as_posix() == "views/_model.js":
                continue
            self.assertNotIn(
                "jquery", path.read_text(encoding="utf-8").lower(), path.name
            )

    def test_the_theme_is_set_before_the_first_paint(self):
        boot = PAGE.index('localStorage.getItem("overseer.theme")')
        self.assertLess(boot, PAGE.index("app/tokens.css"))

    def test_the_module_loads_last(self):
        self.assertTrue(
            PAGE.rstrip().endswith(
                '<script type="module" src="__OVERSEER_BASE__/app/main.js"></script>\n</body>\n</html>'.strip()
            )
        )


class TheTokens(unittest.TestCase):
    TOKENS = (APP / "tokens.css").read_text(encoding="utf-8")
    CSS = (APP / "app.css").read_text(encoding="utf-8")

    def test_dark_and_light_both_exist_and_the_system_decides_by_default(self):
        self.assertIn("--color-bg: #161826;", self.TOKENS)
        self.assertIn(':root[data-theme="light"]', self.TOKENS)
        self.assertIn("@media (prefers-color-scheme: light)", self.TOKENS)
        self.assertIn(':root:not([data-theme="dark"])', self.TOKENS)

    def test_the_type_scale_and_status_colours(self):
        for token in (
            "--fs-0: 11px",
            "--fs-2: 14px",
            "--fs-5: 28px",
            "--ok:",
            "--warn:",
            "--bad:",
            "--warn-line:",
            "--bad-line:",
        ):
            self.assertIn(token, self.TOKENS)

    def test_every_class_colour_exists_in_both_themes(self):
        for cls in (
            "warrior",
            "paladin",
            "rogue",
            "priest",
            "mage",
            "shaman",
            "druid",
            "hunter",
            "warlock",
        ):
            self.assertEqual(self.TOKENS.count("--cls-%s:" % cls), 3, cls)

    def test_focus_is_visible_and_taps_are_44px(self):
        self.assertIn(
            ":focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px;",
            self.CSS,
        )
        self.assertIn(
            "min-height: 44px",
            self.CSS[self.CSS.index(".btn {") : self.CSS.index(".btn:disabled")],
        )
        self.assertIn("min-height: 48px", self.CSS[self.CSS.index(".tab {") :])

    def test_headings_never_go_above_500(self):
        for weight in re.findall(r"font-weight:\s*(\d+)", self.TOKENS + self.CSS):
            self.assertLessEqual(int(weight), 500)

    def test_the_tooltip_stays_dark_in_both_themes(self):
        light = self.TOKENS[self.TOKENS.index(':root[data-theme="light"]') :]
        self.assertNotIn("--tip-bg", light)


class TheHouseRules(unittest.TestCase):
    def test_ascii_and_no_em_dashes(self):
        for path in [
            HERE / "index.html",
            *APP_FILES,
            *sorted((HERE / "apiv2").glob("*.py")),
        ]:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.isascii(), path.name)


class TheServer(unittest.TestCase):
    def test_a_worn_bonus_is_read_as_its_score(self):
        # /api/upgrades sends a worn item's extras as {enchants, stats, score};
        # the panel once printed the object as a number: "+NaN".
        src = (APP / "views" / "_members.js").read_text(encoding="utf-8")
        self.assertIn("function bonusScore(b)", src)
        self.assertNotIn("score(s.worn.bonus)", src)

    def test_a_name_outside_the_roster_reads_only_the_roster(self):
        src = (APP / "views" / "member.js").read_text(encoding="utf-8")
        # Until the roster is in and holds the name, only the roster is read:
        # main.js widens the reads once it holds the name.
        self.assertIn(
            'if (!roster || !byName(roster.members).has(ctx.params.name)) return ["/api/v2/roster"];',
            src,
        )
        main = (APP / "main.js").read_text(encoding="utf-8")
        self.assertIn("module.reads(ctx)", main)

    def test_search_takes_the_keys_typed_straight_after_the_slash(self):
        # The box was focused on a timer, so a quick "/Grug" lost its letters
        # to the page and Enter opened nothing. open() focuses it at once.
        src = (APP / "search.js").read_text(encoding="utf-8")
        opener = src[src.index("export function open()") :]
        opener = opener[: opener.index("\n}\n")]
        self.assertIn("input.focus();", opener)
        self.assertNotIn("setTimeout", opener)

    def test_ghosts_and_stuck_are_counted_from_the_roster_everywhere(self):
        # The wall carries no ghost state, so Now said "Ghosts not measured"
        # while Members listed ghosts; the guild's Stuck tile never counted.
        views = APP / "views"
        now = (views / "now.js").read_text(encoding="utf-8")
        data = (views / "now" / "data.js").read_text(encoding="utf-8")
        guild = (views / "guild.js").read_text(encoding="utf-8")
        self.assertIn('"/api/v2/stuck", "/api/v2/roster"', now)
        self.assertEqual(now.count('D.ghosts(ctx.get("/api/v2/roster"))'), 2)
        self.assertIn('m.life === "ghost" || m.life === "dead"', data)
        self.assertNotIn("m.ghost === true", now)
        self.assertNotIn(
            "m.ghost === true", (views / "map.js").read_text(encoding="utf-8")
        )
        self.assertIn('progress: ["guild", "series", "roster"]', guild)
        self.assertNotIn('tile("Stuck", notMeasured()', guild)

    def test_nothing_still_points_at_the_classic_page(self):
        # Every section has its own view now: no stub, no link to /classic.
        self.assertFalse((APP / "views" / "_pending.js").exists())
        self.assertNotIn("classicFor", (APP / "router.js").read_text(encoding="utf-8"))
        self.assertNotIn("/classic", PAGE)

    def test_the_root_serves_the_app_and_the_classic_page_is_gone(self):
        app = get("/")
        self.assertEqual(app.status(), 200)
        self.assertIn(b'<script type="module" src="/app/main.js">', app.body())
        for old in ("/classic", "/classic.html"):
            self.assertNotIn(old, map_server.Handler.GET_ROUTES)
            self.assertEqual(get(old).status(), 404, old)
        self.assertFalse((HERE / "classic.html").exists())

    def test_a_prefixed_realm_gets_its_prefix_in_the_app(self):
        original = map_server.BASE_PATH
        map_server.BASE_PATH = "/dev"
        try:
            body = get("/").body().decode("utf-8")
        finally:
            map_server.BASE_PATH = original
        self.assertIn('<meta name="overseer-base" content="/dev">', body)
        self.assertIn('src="/dev/app/main.js"', body)
        self.assertNotIn(basepath.PLACEHOLDER, body)

    def test_app_files_are_served_with_their_types(self):
        js = get("/app/main.js")
        self.assertEqual(js.status(), 200)
        self.assertEqual(js.header("Content-Type"), "text/javascript; charset=utf-8")
        css = get("/app/tokens.css")
        self.assertEqual(css.header("Content-Type"), "text/css; charset=utf-8")
        self.assertEqual(get("/app/views/operator.js").status(), 200)

    def test_nothing_else_is_reachable_through_the_app_prefix(self):
        for path in (
            "/app/../map_server.py",
            "/app/..%2Fmap_server.py",
            "/app/x.py",
            "/app/Main.js",
            "/app/views/../../bridge.py",
            "/app/",
            "/app/missing.js",
            "/app/.hidden.js",
            "/app//main.js",
        ):
            self.assertEqual(get(path).status(), 404, path)

    def test_a_get_carries_an_etag_and_an_unchanged_one_is_a_304(self):
        first = get("/app/app.css")
        tag = first.header("ETag")
        self.assertRegex(tag, r'^"[0-9a-f]{24}"$')
        self.assertEqual(first.header("Cache-Control"), "no-cache")
        again = get("/app/app.css", {"If-None-Match": tag})
        self.assertEqual(again.status(), 304)
        self.assertEqual(again.body(), b"")
        other = get("/app/app.css", {"If-None-Match": '"0000"'})
        self.assertEqual(other.status(), 200)

    def test_posts_and_errors_stay_uncached(self):
        h = FakeHandler("/api/chat", command="POST")
        h._send(200, "application/json", b"{}")
        self.assertEqual(h.header("Cache-Control"), "no-store")
        self.assertIsNone(h.header("ETag"))
        missing = get("/nope")
        self.assertEqual(missing.header("Cache-Control"), "no-store")

    def test_the_realm_reports_the_pages_version(self):
        # `page` and `app_page` stay in the payload (the contract is kept);
        # with the classic page gone both are the app's page.
        h = FakeHandler("/api/realm")
        with (
            mock.patch.object(map_server, "_fetch_realm", return_value={}),
            mock.patch.object(map_server.realm, "build_realm", return_value={}),
        ):
            h._realm({})
        payload = json.loads(h.body())
        self.assertEqual(
            payload["page"], basepath.page_version((HERE / "index.html").read_bytes())
        )
        self.assertEqual(
            payload["app_page"],
            basepath.page_version((HERE / "index.html").read_bytes()),
        )

    def test_the_post_routes_are_unchanged(self):
        self.assertEqual(
            sorted(map_server.Handler.POST_ROUTES),
            ["/api/chat", "/api/decree", "/api/director", "/api/frame", "/api/watch"],
        )


class TheV2Namespace(unittest.TestCase):
    def test_operator_actions_are_off_unless_the_server_says_so(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(v2operator.ENV_VAR, None)
            h = get("/api/v2/operator")
        self.assertEqual(h.status(), 200)
        self.assertFalse(json.loads(h.body())["enabled"])
        with mock.patch.dict(os.environ, {v2operator.ENV_VAR: "on"}):
            self.assertTrue(json.loads(get("/api/v2/operator").body())["enabled"])
        for word in ("", "0", "off", "no", "maybe"):
            self.assertFalse(v2operator.enabled({v2operator.ENV_VAR: word}), word)

    def test_an_unknown_v2_path_is_a_json_404(self):
        h = get("/api/v2/nothing-here")
        self.assertEqual(h.status(), 404)
        self.assertIn("/api/v2/operator", json.loads(h.body())["endpoints"])

    def test_every_v2_route_lives_under_the_prefix(self):
        self.assertTrue(apiv2.ROUTES)
        for path in apiv2.ROUTES:
            self.assertTrue(path.startswith(apiv2.PREFIX), path)

    def test_a_failing_handler_is_a_503_not_a_crash(self):
        def boom(_q, _ctx):
            raise RuntimeError("world gone")

        with mock.patch.dict(apiv2.ROUTES, {"/api/v2/boom": boom}):
            h = get("/api/v2/boom")
        self.assertEqual(h.status(), 503)


# The families and guilds /api/realm reports for a realm like the live one.
REALM = {
    "families": [
        {"key": "Grug", "names": ["Grug", "Bork"]},
        {"key": "Zug", "names": ["Zug", "Oz"]},
    ],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheRouter(unittest.TestCase):
    def test_every_old_address_has_a_new_home(self):
        cases = {
            "#armory": "#/members/gear",
            "#bags": "#/economy",
            "#upgrades": "#/members/gear/upgrades",
            "#lineup": "#/members/gear/table",
            "#trades": "#/economy/trades",
            "#family": "#/now/family/grug",
            "#family/Zug": "#/now/family/zug",
            "#watch": "#/now",
            "#dungeons": "#/guilds/cave/runs",
            "#dungeons/33": "#/guilds/cave/runs",
            "#guild": "#/guilds/cave/runs",
            "#guildchat": "#/guilds/cave/chronicle",
            "#chronicle": "#/guilds/cave/chronicle",
            "#achievements": "#/guilds/cave/chronicle",
            "#council": "#/guilds/cave/chronicle",
            "#raid": "#/raid/mc",
            "#eye": "#/now/server",
            "#map": "#/now/map",
            "#map/kalimdor": "#/now/map?c=kal",
            "#decree": "#/operator",
            "#aprof-Grog": "#/m/Grog/gear",
            "#aprof-Some%20One": "#/m/Some%20One/gear",
            "#nonsense": "#/now",
        }
        got = node_module(
            "router.js",
            "console.log(JSON.stringify(%s.map((h) => M.legacy(h))));"
            % json.dumps(list(cases)),
            realm=REALM,
        )
        self.assertEqual(dict(zip(cases, got)), cases)

    def test_new_routes_are_not_redirected(self):
        got = node_module(
            "router.js",
            'console.log(JSON.stringify(["#/now", "#/m/Grug", "", "#"].map(M.legacy)));',
        )
        self.assertEqual(got, ["", "", "", ""])

    def test_routes_resolve_to_views_and_bad_ones_redirect(self):
        script = """
const r = (h) => M.resolve(M.parse(h));
console.log(JSON.stringify([
  r("#/now"), r("#/now/family/zug"), r("#/now/family/x"), r("#/now/map?c=ek"), r("#/guilds/bonkers/runs"),
  r("#/guilds/elsewhere"), r("#/runs/391"), r("#/members?stuck=1"), r("#/members/gear/table"),
  r("#/m/Grug/bags"), r("#/m/Grug/nope"), r("#/raid/mc"), r("#/raid/mc/bonkers"), r("#/economy/trades"),
  r("#/operator"), r("#/nothing"), r("")
]));"""
        got = node_module("router.js", script, realm=REALM)
        self.assertEqual(got[0], {"view": "now", "section": "now", "params": {}})
        self.assertEqual(got[1]["params"], {"family": "zug"})
        self.assertEqual(got[2], {"redirect": "#/now/family/grug"})
        self.assertEqual(got[3]["params"], {"continent": "ek"})
        self.assertEqual(got[4]["params"], {"guild": "bonkers", "tab": "runs"})
        self.assertEqual(got[5], {"redirect": "#/guilds/cave"})
        self.assertEqual(got[6]["params"], {"id": "391"})
        self.assertEqual(got[7]["view"], "members")
        self.assertEqual(got[8]["params"], {"tab": "table"})
        self.assertEqual(got[9]["params"], {"name": "Grug", "tab": "bags"})
        self.assertEqual(got[10]["params"]["tab"], "overview")
        self.assertEqual(got[11], {"redirect": "#/raid/mc/cave"})
        self.assertEqual(got[12]["params"], {"guild": "bonkers"})
        self.assertEqual(got[13]["params"], {"tab": "trades"})
        self.assertEqual(got[14]["view"], "operator")
        self.assertEqual(got[15]["view"], "notfound")
        self.assertEqual(got[16], {"redirect": "#/now"})

    def test_the_families_and_guilds_are_the_realms_own(self):
        """Another realm's names route the same way: nothing is written in."""
        realm = {
            "families": [{"key": "Ard", "names": ["Ard"]}],
            "guilds": [{"name": "Ironpact", "family": "Ard"}],
        }
        script = """
const r = (h) => M.resolve(M.parse(h));
console.log(JSON.stringify([
  r("#/guilds/ironpact"), r("#/guilds/cave"), r("#/now/family/grug"), r("#/raid/mc/ironpact"),
  r("#/raid/mc"), M.legacy("#family"), M.legacy("#guild")
]));"""
        got = node_module("router.js", script, realm=realm)
        self.assertEqual(got[0]["params"], {"guild": "ironpact", "tab": "progress"})
        self.assertEqual(got[1], {"redirect": "#/guilds/ironpact"})
        self.assertEqual(got[2], {"redirect": "#/now/family/ard"})
        self.assertEqual(got[3]["params"], {"guild": "ironpact"})
        self.assertEqual(got[4], {"redirect": "#/raid/mc/ironpact"})
        self.assertEqual(got[5:], ["#/now/family/ard", "#/guilds/ironpact/runs"])

    def test_before_the_realm_answers_a_route_keeps_its_slug(self):
        script = """
const r = (h) => M.resolve(M.parse(h));
console.log(JSON.stringify([r("#/guilds/cave/runs"), r("#/guilds"), r("#/now/family/zug"), r("#/raid/mc")]));"""
        got = node_module("router.js", script)
        self.assertEqual(got[0]["params"], {"guild": "cave", "tab": "runs"})
        self.assertEqual(got[1], {"redirect": "#/now"})
        self.assertEqual(got[2]["params"], {"family": "zug"})
        self.assertEqual(got[3], {"redirect": "#/now"})

    def test_the_nav_lists_the_realms_families_and_guilds(self):
        realm = {
            "families": [{"key": "Ard", "names": ["Ard"]}],
            "guilds": [{"name": "Ironpact", "family": "Ard"}],
        }
        got = node_module(
            "shell.js",
            "console.log(JSON.stringify([M.SUBS.now, M.SUBS.guilds, M.SUBS.raid]));",
            realm=realm,
        )
        self.assertIn(["Ard family", "#/now/family/ard"], got[0])
        self.assertEqual(got[1], [["Ironpact", "#/guilds/ironpact"]])
        self.assertEqual(got[2], [["Ironpact", "#/raid/mc/ironpact"]])

    def test_a_realm_answer_without_the_names_keeps_what_was_learned(self):
        got = node_module(
            "families.js",
            """
const before = M.learn({realm: "older server"});
const after = M.learn({families: null, guilds: null});
console.log(JSON.stringify([before, after, M.guildSlugs(), M.familyKeys(), M.guildFamily("bonkers")]));""",
            realm=REALM,
        )
        self.assertEqual(
            got, [False, False, ["cave", "bonkers"], ["Grug", "Zug"], "Zug"]
        )

    def test_queries_round_trip(self):
        got = node_module(
            "router.js",
            """
const p = M.parse("#/members?stuck=1&lvl=10-20&q=Gr%C3%BCg");
console.log(JSON.stringify([p, M.build(p.parts, p.query), M.build(["m", "Some One"], {})]));""",
        )
        self.assertEqual(got[0]["query"], {"stuck": "1", "lvl": "10-20", "q": "Grüg"})
        self.assertEqual(got[1], "#/members?stuck=1&lvl=10-20&q=Gr%C3%BCg")
        self.assertEqual(got[2], "#/m/Some%20One")

    def test_a_swipe_walks_the_tab_row(self):
        got = node_module(
            "router.js",
            """
console.log(JSON.stringify([M.swipeSiblings(["a", "b", "c"], "b"), M.swipeSiblings(["a", "b"], "a"), M.swipeSiblings(["a"], "z")]));""",
        )
        self.assertEqual(
            got,
            [
                {"prev": "a", "next": "c"},
                {"prev": "", "next": "b"},
                {"prev": "", "next": ""},
            ],
        )

    def test_every_view_the_router_names_exists(self):
        views = {p.stem for p in (APP / "views").glob("*.js")}
        router = (APP / "router.js").read_text(encoding="utf-8")
        named = set(re.findall(r'view: "([a-z]+)"', router))
        self.assertTrue(named)
        self.assertLessEqual(named, views)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheMarkup(unittest.TestCase):
    def test_text_from_the_realm_never_becomes_markup(self):
        got = node_module(
            "ui.js",
            r"""
const evil = '<img src=x onerror=alert(1)>"&\'';
console.log(JSON.stringify([
  String(M.html`<b>${evil}</b>`),
  String(M.html`<a title="${evil}">x</a>`),
  String(M.html`<i>${[evil, M.html`<u>${evil}</u>`]}</i>`),
  String(M.member({name: evil, cls: "Warrior"})),
  String(M.item({entry: 5, name: evil, quality: 9})),
]));""",
        )
        for out in got:
            self.assertNotIn("<img", out)
            self.assertNotIn("\"&'", out)

    def test_a_missing_number_says_not_measured(self):
        got = node_module(
            "ui.js",
            """
console.log(JSON.stringify([String(M.value(null)), String(M.value(undefined)), String(M.value(0)), M.ago(null), M.ago(42), M.ago(3700), M.gold(123456), M.gold(null)]));""",
        )
        self.assertIn("not measured", got[0])
        self.assertIn("not measured", got[1])
        self.assertEqual(got[2], "0")
        self.assertEqual(got[3], "not measured")
        self.assertEqual(got[4:7], ["42s ago", "1h ago", "12g 34s"])
        self.assertIsNone(got[7])

    def test_a_sparkline_needs_two_points(self):
        got = node_module(
            "ui.js",
            """
console.log(JSON.stringify([String(M.sparkline([5])), String(M.sparkline([1, null, 3]))]));""",
        )
        self.assertIn("not measured", got[0])
        self.assertIn("<polyline", got[1])

    def test_the_status_vocabulary(self):
        got = node_module(
            "ui.js", "console.log(JSON.stringify(Object.keys(M.STATUS)));"
        )
        self.assertEqual(
            got,
            [
                "stuck",
                "stalled",
                "ghost",
                "live",
                "online",
                "offline",
                "upgrade",
                "best",
                "near",
                "inside",
                "cleared",
                "wiped",
                "new",
            ],
        )


class TheImage(unittest.TestCase):
    def test_the_image_carries_the_app_and_v2_and_not_the_old_page(self):
        docker = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY app /app/app", docker)
        self.assertIn("COPY apiv2 /app/apiv2", docker)
        self.assertNotIn("classic.html", docker)


if __name__ == "__main__":
    unittest.main()
