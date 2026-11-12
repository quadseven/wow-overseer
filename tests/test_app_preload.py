"""The page lists the boot graph, so the browser fetches it in one round.

WHY. The boot graph is about twenty small modules in four dependent rounds:
each module is only discovered once the one that imports it has arrived and
been parsed, so a cold start paid four round trips before the first route
could run. The graph is known from the files' own import statements, so the
page names every file of it up front with <link rel="modulepreload">.

Ticket: #2312 (epic #2309).
"""

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

from test_app_shell import get  # noqa: E402

BUILD = appbuild.fingerprint(str(HERE))

# Logs every file node resolves while linking main.js. Linking loads the whole
# static graph before anything runs, so it names the real closure even though
# main.js then fails on the missing browser.
RESOLVE_HOOK = """
export async function resolve(specifier, context, next) {
  const r = await next(specifier, context);
  if (r.url.startsWith("file:")) console.log("MOD " + r.url);
  return r;
}
"""


def node_graph():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(HERE / "app", root / "app")
        (root / "app" / "package.json").write_text(
            '{"type": "module"}', encoding="utf-8"
        )
        hook = root / "hook.mjs"
        hook.write_text(RESOLVE_HOOK, encoding="utf-8")
        code = (
            'import { register } from "node:module";\n'
            "register(%s);\n"
            "try { await import(%s); } catch (e) { /* no browser here */ }\n"
        ) % (json.dumps(hook.as_uri()), json.dumps((root / "app" / "main.js").as_uri()))
        out = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", code],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        base = (root / "app").as_uri() + "/"
        seen = set()
        for line in out.stdout.splitlines():
            if line.startswith("MOD ") and line[4:].startswith(base):
                seen.add("app/" + line[4 + len(base) :])
        return seen


class TheGraph(unittest.TestCase):
    def test_the_closure_equals_what_node_links(self):
        if not shutil.which("node"):
            self.skipTest("node is needed")
        linked = node_graph()
        self.assertIn("app/main.js", linked)
        self.assertGreater(len(linked), 10)
        self.assertEqual(set(appbuild.boot_graph(str(HERE))), linked)

    def test_it_is_in_a_stable_order_with_the_entry_first_and_no_repeats(self):
        graph = appbuild.boot_graph(str(HERE))
        self.assertEqual(graph[0], "app/main.js")
        self.assertEqual(len(graph), len(set(graph)))
        self.assertEqual(graph, appbuild.boot_graph(str(HERE)))

    def test_a_view_loaded_by_import_call_is_not_in_it(self):
        graph = appbuild.boot_graph(str(HERE))
        self.assertNotIn("app/views/now.js", graph)

    def test_imports_are_read_the_way_modules_write_them(self):
        text = (
            'import a from "./a.js";\n'
            'import { b,\n  c } from "./b.js";\n'
            'import * as d from "./sub/d.js";\n'
            'import "./side.js";\n'
            'export { e } from "./e.js";\n'
            '// import nothing from "./comment.js";\n'
            "const s = \"import x from \\'./string.js\\'\";\n"
            'const m = await import("./dynamic.js");\n'
        )
        self.assertEqual(
            appbuild.static_imports(text),
            ["./a.js", "./b.js", "./sub/d.js", "./side.js", "./e.js"],
        )

    def test_the_depth_is_the_longest_static_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = pathlib.Path(tmp) / "app"
            app.mkdir()
            (app / "main.js").write_text('import "./a.js";\nimport "./c.js";\n')
            (app / "a.js").write_text('import "./b.js";\n')
            (app / "b.js").write_text('import "./a.js";\n')  # a cycle
            (app / "c.js").write_text("export const c = 1;\n")
            self.assertEqual(appbuild.import_depth(tmp), 3)
            self.assertEqual(
                sorted(appbuild.boot_graph(tmp)),
                ["app/a.js", "app/b.js", "app/c.js", "app/main.js"],
            )

    def test_the_real_depth_is_known_and_small(self):
        self.assertTrue(2 <= appbuild.import_depth(str(HERE)) <= 6)


class ThePage(unittest.TestCase):
    def _page(self, base=""):
        original = map_server.BASE_PATH
        map_server.BASE_PATH = base
        try:
            return get("/").body().decode("utf-8")
        finally:
            map_server.BASE_PATH = original

    def test_one_preload_per_file_of_the_graph_under_the_build(self):
        page = self._page()
        links = re.findall(r'<link rel="modulepreload" href="([^"]+)">', page)
        want = [
            "/app/%s/%s" % (BUILD, rel[len("app/") :])
            for rel in appbuild.boot_graph(str(HERE))
        ]
        self.assertEqual(links, want)

    def test_a_prefixed_mount_puts_its_prefix_first(self):
        links = re.findall(
            r'<link rel="modulepreload" href="([^"]+)">', self._page("/dev")
        )
        self.assertTrue(links)
        for link in links:
            self.assertTrue(link.startswith("/dev/app/%s/" % BUILD), link)

    def test_no_placeholder_is_left_and_nothing_for_a_view(self):
        page = self._page()
        self.assertNotIn("__OVERSEER_PRELOAD__", page)
        self.assertNotIn(
            "views/",
            "".join(re.findall(r'<link rel="modulepreload" href="([^"]+)">', page)),
        )

    def test_the_hints_are_made_once_per_build(self):
        appbuild._preload_memo.clear()
        self._page()
        self._page()
        self.assertEqual(len(appbuild._preload_memo), 1)


if __name__ == "__main__":
    unittest.main()
