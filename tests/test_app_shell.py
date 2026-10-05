"""The page opens and behaves like an app on the operator's phone.

Added to the Home Screen it runs full screen, so the things Safari drew around
it are the page's own now: the manifest and icon it is installed from, the
status bar's strip, the pressed state of a control, the edges a scroll stops
at, the sheets panels rise in, and where each view was left. The behaviour is
run under node with fake elements; the furniture is read from the files.
"""

import json
import pathlib
import shutil
import struct
import subprocess
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402  (must follow the pymysql stub)

PAGE = (HERE / "index.html").read_text(encoding="utf-8")
HEAD = PAGE[: PAGE.index("</head>")]
ICONS = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}


def fn(name):
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


def node(script):
    out = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class InstallsFromTheHomeScreen(unittest.TestCase):
    def test_the_manifest_opens_this_realm_full_screen(self):
        m = json.loads((HERE / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(m["display"], "standalone")
        # Relative, so each realm's copy resolves against its own mount.
        self.assertEqual(m["start_url"], "./")
        self.assertEqual(m["scope"], "./")
        self.assertTrue(m["name"] and m["short_name"])
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        for icon in m["icons"]:
            self.assertFalse(icon["src"].startswith("/"), icon["src"])
            self.assertTrue((HERE / icon["src"]).exists(), icon["src"])

    def test_every_icon_is_a_png_of_its_size_and_small(self):
        for name, size in ICONS.items():
            data = (HERE / name).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", name)
            w, h = struct.unpack(">II", data[16:24])
            self.assertEqual((w, h), (size, size), name)
            self.assertLess(len(data), 64 * 1024, name)

    def test_the_page_links_the_manifest_and_icon_through_the_mount(self):
        for path in ("/manifest.webmanifest", "/apple-touch-icon.png", "/icon-192.png"):
            self.assertIn('u("%s")' % path, HEAD)
        self.assertIn('["manifest", u("/manifest.webmanifest")', HEAD)
        self.assertIn('["apple-touch-icon", u("/apple-touch-icon.png")', HEAD)

    def test_the_page_asks_to_open_full_screen(self):
        for tag in (
            '<meta name="apple-mobile-web-app-capable" content="yes">',
            '<meta name="mobile-web-app-capable" content="yes">',
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
            '<meta name="apple-mobile-web-app-title" content="Overseer">',
            '<meta name="theme-color"',
        ):
            self.assertIn(tag, HEAD)
        self.assertIn("viewport-fit=cover", HEAD)

    def test_the_server_serves_every_file_with_its_type(self):
        class Fake(map_server.Handler):
            def __init__(self):
                self.sent = []

            def _send(self, code, ctype, body, cache_control="no-store"):
                self.sent.append((code, ctype, body))

        want = {
            "/manifest.webmanifest": (
                "manifest.webmanifest",
                "application/manifest+json",
            ),
            "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
            "/icon-192.png": ("icon-192.png", "image/png"),
            "/icon-512.png": ("icon-512.png", "image/png"),
        }
        for path, (name, ctype) in want.items():
            h = Fake()
            map_server.Handler.GET_ROUTES[path](h, {})
            code, got_type, body = h.sent[-1]
            self.assertEqual((code, got_type), (200, ctype), path)
            self.assertEqual(body, (HERE / name).read_bytes(), path)

    def test_the_image_ships_them(self):
        docker = (HERE / "Dockerfile").read_text(encoding="utf-8")
        line = [
            x for x in docker.splitlines() if x.startswith("COPY manifest.webmanifest")
        ]
        self.assertEqual(len(line), 1)
        for name in ["manifest.webmanifest", *ICONS]:
            self.assertIn(name, line[0])


class TheShellAroundTheViews(unittest.TestCase):
    def test_the_status_bar_strip_and_the_bars_clear_the_notch(self):
        self.assertIn("body { padding-top:env(safe-area-inset-top); }", PAGE)
        self.assertIn("height:env(safe-area-inset-top); background:#0A140E;", PAGE)
        self.assertIn(
            ":root :is(#tabbar, #ajump, #stjump) { top:env(safe-area-inset-top); }",
            PAGE,
        )
        self.assertIn(
            "env(safe-area-inset-bottom)",
            PAGE[PAGE.index("#hubs { position:fixed") :][:200],
        )
        self.assertIn(
            ":root #itemtip { padding-bottom:env(safe-area-inset-bottom); }", PAGE
        )

    def test_a_tap_is_answered_by_the_control(self):
        self.assertIn("-webkit-tap-highlight-color:transparent;", PAGE)
        self.assertRegex(
            PAGE,
            r"@media \(hover: none\) \{\s*:is\(a, button, summary, \.aslot, "
            r"tr\[tabindex\]\):active:not\(:disabled\) \{\s*opacity:\.6;",
        )
        self.assertIn(
            'document.addEventListener("touchstart", () => {}, { passive: true });',
            PAGE,
        )

    def test_the_page_does_not_rubber_band_and_fields_do_not_zoom(self):
        self.assertIn("overscroll-behavior-y:none;", PAGE)
        self.assertRegex(
            PAGE,
            r"@media \(pointer: coarse\) \{\s*:root :is\(input, select, textarea, "
            r"#pinput, #dcrtext, #dcrqueuetext\) \{\s*font-size:max\(16px, 1em\);",
        )

    def test_the_native_controls_follow_the_theme(self):
        self.assertIn(":root { color-scheme:light; }", PAGE)
        self.assertIn(':root:not([data-theme="light"]) { color-scheme:dark; }', PAGE)
        self.assertIn(':root[data-theme="dark"] { color-scheme:dark; }', PAGE)

    def test_motion_has_a_reduced_path(self):
        block = PAGE[PAGE.index("@keyframes sheet-up") :][:4000]
        reduced = block[block.index("@media (prefers-reduced-motion: reduce)") :]
        self.assertIn(
            "#itemtip:not([hidden]), #panel.sheet-open { animation:none; }", reduced
        )
        self.assertIn(".sheet-settling { transition:none; }", reduced)

    def test_the_dungeon_link_scrolls_once_not_every_poll(self):
        render = fn("dgnRender")
        self.assertIn(
            "dungeonTargetMap !== null && dungeonScrolledTo !== dungeonTargetMap",
            render,
        )
        self.assertIn("dungeonScrolledTo = dungeonTargetMap;", render)


SHEET = """
const PHONE = { matches: %s }, STILL = { matches: true };
function listeners() { const l = {}; return { l,
  addEventListener: (t, f) => { l[t] = f; } }; }
const sheet = Object.assign(listeners(), { style: {}, offsetHeight: 600,
  classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); } } });
const scroller = { scrollTop: %d };
let dismissed = 0;
const grip = {};
globalThis.Element = function () {};
Object.setPrototypeOf(grip, Element.prototype);
grip.closest = () => grip;
const body = Object.create(Element.prototype);
body.closest = () => null;
globalThis.setTimeout = (f) => f();
function ev(y, t, target) { return { touches: [{ clientY: y }], target, timeStamp: t,
  preventDefault() { this.prevented = true; } }; }
function drag(from, to, ms, target) {
  sheet.l.touchstart(ev(from, 0, target));
  const steps = 10; let last;
  for (let i = 1; i <= steps; i++) {
    last = ev(from + (to - from) * i / steps, ms * i / steps, target);
    sheet.l.touchmove(last);
  }
  sheet.l.touchend({});
  return !!last.prevented;
}
"""


@unittest.skipUnless(shutil.which("node"), "needs node to run the sheet")
class SheetsFollowAFinger(unittest.TestCase):
    def run_sheet(self, body, phone=True, scroll_top=0):
        return node(
            SHEET % ("true" if phone else "false", scroll_top)
            + fn("sheetReset")
            + fn("sheetGestures")
            + "sheetGestures(sheet, scroller, () => { dismissed += 1; });\n"
            + body
            + "process.stdout.write(JSON.stringify({dismissed, out: globalThis.out, "
            "transform: sheet.style.transform}));"
        )

    def test_a_long_pull_on_the_handle_puts_it_away(self):
        got = self.run_sheet("globalThis.out = drag(100, 400, 600, grip);")
        self.assertEqual(got["dismissed"], 1)
        self.assertTrue(got["out"], "the drag must not also scroll the page")

    def test_a_flick_puts_it_away(self):
        self.assertEqual(self.run_sheet("drag(100, 160, 60, grip);")["dismissed"], 1)

    def test_a_slow_nudge_settles_back(self):
        got = self.run_sheet("drag(100, 140, 800, grip);")
        self.assertEqual(got["dismissed"], 0)
        self.assertEqual(got["transform"], "")

    def test_a_drag_up_scrolls_the_reading(self):
        got = self.run_sheet("globalThis.out = drag(400, 100, 300, body);")
        self.assertEqual(got["dismissed"], 0)
        self.assertFalse(got["out"])

    def test_a_pull_on_a_scrolled_reading_scrolls_it(self):
        got = self.run_sheet(
            "globalThis.out = drag(100, 400, 600, body);", scroll_top=200
        )
        self.assertEqual(got["dismissed"], 0)
        self.assertFalse(got["out"])

    def test_a_wide_screen_has_no_sheet(self):
        self.assertEqual(
            self.run_sheet("drag(100, 400, 600, grip);", phone=False)["dismissed"], 0
        )


VIEWS = """
const MAP_VIEW = "map", STILL = { matches: true };
let view = "guild", opened = [], scrolled = [];
const viewScroll = new Map([["chronicle", 953]]);
function hubOf(v) { return { guild: "guild", council: "guild", chronicle: "families" }[v]; }
function openHub(k) { opened.push(k); }
const node = { classList: { add() {}, remove() {} }, offsetWidth: 1 };
globalThis.document = { getElementById: () => node };
globalThis.window = { scrollTo: (a, b) => scrolled.push(typeof a === "object" ? a.top : b) };
"""


@unittest.skipUnless(shutil.which("node"), "needs node to run the hubs")
class EachViewKeepsItsPlace(unittest.TestCase):
    def run_views(self, body):
        return node(
            VIEWS
            + fn("viewNode")
            + fn("arriveAt")
            + fn("tapHub")
            + body
            + "process.stdout.write(JSON.stringify({opened, scrolled}));"
        )

    def test_a_view_opens_where_it_was_left_and_a_new_one_at_the_top(self):
        got = self.run_views('arriveAt("chronicle"); arriveAt("raid");')
        self.assertEqual(got["scrolled"], [953, 0])

    def test_the_hub_you_are_in_tapped_again_goes_to_the_top(self):
        got = self.run_views('tapHub("guild"); tapHub("families");')
        self.assertEqual(got["scrolled"], [0])
        self.assertEqual(got["opened"], ["families"])

    def test_show_view_notes_the_place_before_it_hides_the_view(self):
        show = fn("showView")
        self.assertLess(
            show.index("viewScroll.set(from, window.scrollY)"),
            show.index("fsection.style.display"),
        )
        self.assertIn("if (from !== v) arriveAt(v);", show)


if __name__ == "__main__":
    unittest.main()
