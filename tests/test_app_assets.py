"""The app's files are addressed by build, cached for good and compressed.

WHY. Every app script and stylesheet used to answer `no-cache` with no
compression, so a repeat visit on a phone revalidated about forty-five files
before the page could draw, and a first visit downloaded the whole app as
plain text. The page now names its files as /app/<build>/<file>. Relative
imports stay inside one build, a file of the current build never changes (so
the browser may keep it for a year), and an old tab asking for an old build
is answered with the current bytes that are not kept as immutable.

Ticket: #2310 (epic #2309).
"""

import gzip
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import appbuild
    import map_server

from test_app_shell import FakeHandler, get  # noqa: E402

BUILD = appbuild.fingerprint(str(HERE))
MAIN = (HERE / "app" / "main.js").read_bytes()
IMMUTABLE = "public, max-age=31536000, immutable"


def gz(path):
    return get(path, {"Accept-Encoding": "gzip"})


class VersionedFiles(unittest.TestCase):
    def test_the_current_build_is_served_immutable_with_the_same_bytes(self):
        r = get("/app/%s/main.js" % BUILD)
        self.assertEqual(r.status(), 200)
        self.assertEqual(r.header("Cache-Control"), IMMUTABLE)
        self.assertEqual(r.header("Content-Type"), "text/javascript; charset=utf-8")
        self.assertEqual(r.body(), MAIN)
        self.assertIsNone(r.header("ETag"))

    def test_a_nested_file_and_a_stylesheet_are_served_under_the_build(self):
        self.assertEqual(get("/app/%s/views/now.js" % BUILD).status(), 200)
        css = get("/app/%s/tokens.css" % BUILD)
        self.assertEqual(css.status(), 200)
        self.assertEqual(css.header("Content-Type"), "text/css; charset=utf-8")
        self.assertEqual(css.header("Cache-Control"), IMMUTABLE)

    def test_another_build_gets_the_current_bytes_and_is_never_immutable(self):
        r = get("/app/0123456789ab/main.js")
        self.assertEqual(r.status(), 200)
        self.assertEqual(r.body(), MAIN)
        self.assertNotIn("immutable", r.header("Cache-Control"))
        self.assertEqual(r.header("Cache-Control"), "no-cache")

    def test_the_old_path_still_works_and_is_still_revalidated(self):
        r = get("/app/main.js")
        self.assertEqual(r.status(), 200)
        self.assertEqual(r.body(), MAIN)
        self.assertEqual(r.header("Cache-Control"), "no-cache")
        self.assertTrue(r.header("ETag"))

    def test_nothing_else_is_reachable_through_a_build_segment(self):
        for path in (
            "/app/%s/" % BUILD,
            "/app/%s/../map_server.py" % BUILD,
            "/app/%s/..%%2Fmap_server.py" % BUILD,
            "/app/%s/x.py" % BUILD,
            "/app/%s/Main.js" % BUILD,
            "/app/%s/missing.js" % BUILD,
            "/app/%s/.hidden.js" % BUILD,
            "/app/%s//main.js" % BUILD,
            "/app/%s/%s/main.js" % (BUILD, BUILD),
            "/app/ABCDEF012345/main.js",
            "/app/0123456789a/main.js",
            "/app/0123456789abc/main.js",
            "/app/0123456789ab",
        ):
            self.assertEqual(get(path).status(), 404, path)


class Compression(unittest.TestCase):
    def test_a_script_is_gzipped_for_a_client_that_accepts_it(self):
        r = gz("/app/%s/main.js" % BUILD)
        self.assertEqual(r.header("Content-Encoding"), "gzip")
        self.assertEqual(r.header("Vary"), "Accept-Encoding")
        self.assertEqual(gzip.decompress(r.body()), MAIN)
        self.assertLess(len(r.body()), len(MAIN) * 0.5)
        self.assertEqual(r.header("Content-Length"), str(len(r.body())))

    def test_a_stylesheet_is_gzipped_on_both_paths(self):
        css = (HERE / "app" / "app.css").read_bytes()
        for path in ("/app/%s/app.css" % BUILD, "/app/app.css"):
            r = gz(path)
            self.assertEqual(r.header("Content-Encoding"), "gzip", path)
            self.assertEqual(gzip.decompress(r.body()), css, path)

    def test_a_client_that_does_not_ask_gets_the_plain_file(self):
        for headers in (
            {},
            {"Accept-Encoding": "identity"},
            {"Accept-Encoding": "gzip;q=0"},
        ):
            r = get("/app/%s/main.js" % BUILD, headers)
            self.assertIsNone(r.header("Content-Encoding"), headers)
            self.assertEqual(r.body(), MAIN, headers)
            self.assertEqual(r.header("Vary"), "Accept-Encoding", headers)

    def test_a_small_file_is_left_as_it_is(self):
        small = map_server._gzipped(
            FakeHandler("/", {"Accept-Encoding": "gzip"}),
            "text/javascript; charset=utf-8",
            b"x" * 100,
        )
        self.assertIsNone(small)

    def test_the_compressed_bytes_are_kept_for_the_same_file_version(self):
        h = FakeHandler("/", {"Accept-Encoding": "gzip"})
        a = map_server._gzipped(h, "text/javascript; charset=utf-8", MAIN)
        b = map_server._gzipped(h, "text/javascript; charset=utf-8", MAIN)
        self.assertIs(a, b)

    def test_the_kept_compressed_bytes_are_bounded(self):
        h = FakeHandler("/", {"Accept-Encoding": "gzip"})
        for i in range(map_server.GZIP_KEPT_MAX + 20):
            map_server._gzipped(h, "text/css; charset=utf-8", (b"a%d " % i) * 2000)
        self.assertLessEqual(len(map_server._GZIP_KEPT), map_server.GZIP_KEPT_MAX)

    def test_other_types_are_still_not_compressed(self):
        h = FakeHandler("/", {"Accept-Encoding": "gzip"})
        self.assertIsNone(map_server._gzipped(h, "image/png", b"x" * 9000))


class ThePageNamesTheBuild(unittest.TestCase):
    def _page(self, base=""):
        original = map_server.BASE_PATH
        map_server.BASE_PATH = base
        try:
            return get("/").body().decode("utf-8")
        finally:
            map_server.BASE_PATH = original

    def test_the_root_page_names_every_style_and_script_under_the_build(self):
        page = self._page()
        self.assertIn('<script type="module" src="/app/%s/main.js">' % BUILD, page)
        self.assertIn('href="/app/%s/tokens.css"' % BUILD, page)
        self.assertIn('href="/app/%s/app.css"' % BUILD, page)
        self.assertNotIn("__OVERSEER_BUILD__", page)
        self.assertNotIn("__OVERSEER_BASE__", page)

    def test_a_prefixed_realm_gets_the_prefix_before_the_build(self):
        page = self._page("/dev")
        self.assertIn('src="/dev/app/%s/main.js"' % BUILD, page)
        self.assertIn('href="/dev/app/%s/app.css"' % BUILD, page)
        for url in re.findall(r'(?:href|src)="(/[^"]*)"', page):
            self.assertTrue(url.startswith("/dev/"), url)

    def test_the_page_itself_is_never_kept(self):
        r = get("/")
        self.assertEqual(r.header("Cache-Control"), "no-cache")

    def test_the_build_changes_when_a_file_changes(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "app").mkdir()
            (pathlib.Path(tmp) / "index.html").write_text("<html>")
            f = pathlib.Path(tmp) / "app" / "main.js"
            f.write_text("a")
            first = appbuild.fingerprint(tmp)
            f.write_text("b")
            os.utime(f, (1, 1))
            self.assertNotEqual(first, appbuild.fingerprint(tmp))


def app_url(base, build, path):
    """api.js's appUrl(path) under node, with the page's two meta tags stubbed."""
    metas = {"overseer-base": base, "overseer-build": build}
    prelude = (
        'globalThis.document = { querySelector: (q) => { const m = /name="([a-z-]+)"/.exec(q);'
        " const v = m && %s[m[1]]; return v === undefined ? null : { getAttribute: () => v }; },"
        " addEventListener: () => {}, hidden: false };\n"
        "globalThis.window = { sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },"
        " setTimeout: () => 0, clearTimeout: () => {} };\n" % json.dumps(metas)
    )
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "api.mjs"
        dst.write_text(
            (HERE / "app" / "api.js").read_text(encoding="utf-8"), encoding="utf-8"
        )
        code = prelude + "const M = await import(%s);\nconsole.log(M.appUrl(%s));" % (
            json.dumps(dst.as_uri()),
            json.dumps(path),
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
    return out.stdout.strip()


class TheAppsOwnUrls(unittest.TestCase):
    def test_a_view_stylesheet_is_named_under_the_mount_and_the_build(self):
        self.assertEqual(
            app_url("/dev", "0123456789ab", "views/now.css"),
            "/dev/app/0123456789ab/views/now.css",
        )

    def test_without_a_stamped_build_the_plain_path_is_used(self):
        for build in ("__OVERSEER_BUILD__", "", "XYZ"):
            self.assertEqual(
                app_url("/dev", build, "views/now.css"), "/dev/app/views/now.css", build
            )

    def test_the_root_mount_has_no_prefix(self):
        self.assertEqual(
            app_url("", "0123456789ab", "a.css"), "/app/0123456789ab/a.css"
        )

    def test_main_loads_view_styles_through_it(self):
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        self.assertIn("api.appUrl(path)", main)
        self.assertNotIn('api.u("/app/', main)


if __name__ == "__main__":
    unittest.main()
