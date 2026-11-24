"""The page's modulepreload links are made from the boot graph (#2312, epic #2309).

WHY. A module is only discovered once the module that imports it has arrived
and been parsed, so a cold start pays one round trip per level of imports.
The page names the whole static import closure of app/main.js up front. The
list used to be kept by hand in index.html; it is now read from the files'
own import statements, so it cannot drift from the code, and a module that
is only reached through an import() call gets no hint.
"""

from __future__ import annotations

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

NODE = shutil.which("node")
needs_node = unittest.skipIf(NODE is None, "node is not on PATH")
BUILD = appbuild.fingerprint(str(HERE))
LINK = re.compile(r'<link rel="modulepreload" href="([^"]+)">')

# Logs every file node resolves, to a file beside the hook and before the
# resolve returns. Node runs the hook on its own thread, and a console.log
# there is only handed to the main thread to write: a process that ends first
# drops the lines, and the closure read back empty on a busy machine (#3013).
LINK_LOG = "linked.log"
RESOLVE_HOOK = """
import { appendFileSync } from "node:fs";
const LOG = new URL("./linked.log", import.meta.url);
export async function resolve(specifier, context, next) {
  const r = await next(specifier, context);
  if (r.url.startsWith("file:")) appendFileSync(LOG, "MOD " + r.url + "\\n");
  return r;
}
"""


def _served_page(base: str = "") -> str:
    original = map_server.BASE_PATH
    map_server.BASE_PATH = base
    try:
        r = get("/")
        assert r.status() == 200, r.status()
        return r.body().decode("utf-8")
    finally:
        map_server.BASE_PATH = original


def _node_linked(entry: str = "main.js", exit_at_once: bool = False) -> set[str]:
    """The app files node loads to link `entry`, with no module ever run.

    Node resolves and loads the whole static graph before it evaluates
    anything. The wrapper imports a module that throws ahead of the entry, so
    evaluation stops there: no app module runs, and so no import() call is
    ever made. What the hook saw is the static closure and nothing else.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp).resolve()
        shutil.copytree(HERE / "app", root / "app")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "hook.mjs").write_text(RESOLVE_HOOK, encoding="utf-8")
        (root / "stop.mjs").write_text(
            'throw new Error("linked, not run");\n', encoding="utf-8"
        )
        (root / "wrap.mjs").write_text(
            'import "./stop.mjs";\nimport "./app/%s";\n' % entry, encoding="utf-8"
        )
        (root / "run.mjs").write_text(
            'import { register } from "node:module";\n'
            'register("./hook.mjs", import.meta.url);\n'
            'try { await import("./wrap.mjs"); console.log("RAN"); }\n'
            'catch (e) { console.log("STOPPED " + e.message); }\n'
            + ("process.exit(0);\n" if exit_at_once else ""),
            encoding="utf-8",
        )
        out = subprocess.run(
            [NODE, str(root / "run.mjs")],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if out.returncode != 0 or "STOPPED linked, not run" not in out.stdout:
            raise AssertionError(out.stdout + out.stderr)
        prefix = (root / "app").as_uri() + "/"
        log = root / LINK_LOG
        lines = log.read_text("utf-8").splitlines() if log.exists() else []
        return {
            line[4 + len(prefix) :]
            for line in lines
            if line.startswith("MOD " + prefix)
        }


def _tree(files: dict[str, str]) -> str:
    tmp = tempfile.mkdtemp()
    for rel, text in files.items():
        path = pathlib.Path(tmp) / "app" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp


class ClosureTests(unittest.TestCase):
    @needs_node
    def test_closure_of_main_equals_what_node_links(self):
        linked = _node_linked()
        self.assertIn("main.js", linked)
        self.assertGreater(len(linked), 10)
        self.assertEqual(set(appbuild.boot_graph(str(HERE))), linked)

    @needs_node
    def test_the_link_log_survives_a_process_that_exits_at_once(self):
        # #3013: node runs the hook on its own thread. A line that thread
        # prints is handed to the main thread to write, and a process that
        # ends first drops it, so a busy machine read an empty closure. With
        # the process ended the moment the link stops, every line must still
        # be there.
        linked = _node_linked(exit_at_once=True)
        self.assertEqual(set(appbuild.boot_graph(str(HERE))), linked)

    def test_closure_is_stable_entry_first_and_without_repeats(self):
        graph = appbuild.boot_graph(str(HERE))
        self.assertEqual(graph[0], "main.js")
        self.assertEqual(len(graph), len(set(graph)))
        self.assertEqual(graph, appbuild.boot_graph(str(HERE)))

    def test_a_module_reached_only_by_import_call_is_not_in_the_closure(self):
        graph = appbuild.boot_graph(str(HERE))
        self.assertEqual([rel for rel in graph if rel.startswith("views/")], [])
        # Spell names load on first use (models/spelllookup.js imports the
        # catalog with import()), so the catalog is not a boot module.
        lookup = (HERE / "app" / "models" / "spelllookup.js").read_text("utf-8")
        lazy = re.findall(r"""import\(\s*["']\./([^"']+)["']\s*\)""", lookup)
        self.assertTrue(lazy)
        for name in lazy:
            self.assertNotIn("models/" + name, graph)
            self.assertNotIn(
                "models/" + name,
                appbuild.boot_graph(str(HERE), "models/spelllookup.js"),
            )

    def test_static_imports_are_read_the_way_modules_write_them(self):
        text = (
            'import a from "./a.js";\n'
            'import { b,\n  c } from "./b.js";\n'
            'import * as d from "./sub/d.js";\n'
            'import "./side.js";\n'
            "export { e } from './e.js';\n"
            'export * from "./f.js";\n'
            '// import nothing from "./comment.js";\n'
            "const s = \"import x from './string.js'\";\n"
            'const m = await import("./dynamic.js");\n'
            'import("./bare-dynamic.js");\n'
            "export const g = 1;\n"
            'const from = "./not-an-import.js";\n'
        )
        self.assertEqual(
            appbuild.static_imports(text),
            ["./a.js", "./b.js", "./sub/d.js", "./side.js", "./e.js", "./f.js"],
        )

    def test_closure_resolves_parent_paths_and_skips_bare_specifiers(self):
        root = _tree(
            {
                "main.js": 'import "./models/a.js";\nimport x from "some-package";\n',
                "models/a.js": 'import "../b.js";\nconst v = import("../views/v.js");\n',
                "b.js": "export const b = 1;\n",
                "views/v.js": "export default 1;\n",
            }
        )
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual(appbuild.boot_graph(root), ["main.js", "models/a.js", "b.js"])

    def test_a_missing_import_target_is_an_error_not_a_dead_hint(self):
        root = _tree({"main.js": 'import "./gone.js";\n'})
        self.addCleanup(shutil.rmtree, root)
        with self.assertRaises(OSError):
            appbuild.boot_graph(root)


class DeepestChainTests(unittest.TestCase):
    def test_deepest_chain_is_the_longest_static_chain(self):
        root = _tree(
            {
                "main.js": 'import "./a.js";\nimport "./c.js";\n',
                "a.js": 'import "./b.js";\n',
                "b.js": 'import "./d.js";\nimport("./lazy.js");\n',
                "c.js": "export const c = 1;\n",
                "d.js": "export const d = 1;\n",
                "lazy.js": 'import "./c.js";\n',
            }
        )
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual(
            appbuild.deepest_chain(root), ["main.js", "a.js", "b.js", "d.js"]
        )
        self.assertEqual(appbuild.deepest_chain(root, "c.js"), ["c.js"])

    def test_a_cycle_is_walked_once(self):
        root = _tree(
            {
                "main.js": 'import "./a.js";\n',
                "a.js": 'import "./b.js";\n',
                "b.js": 'import "./a.js";\nimport "./b.js";\n',
            }
        )
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual(appbuild.deepest_chain(root), ["main.js", "a.js", "b.js"])

    def test_the_real_chain_is_a_path_through_the_closure(self):
        chain = appbuild.deepest_chain(str(HERE))
        graph = appbuild.boot_graph(str(HERE))
        self.assertEqual(chain[0], "main.js")
        self.assertGreaterEqual(len(chain), 2)
        self.assertLessEqual(len(chain), len(graph))
        self.assertEqual(len(chain), len(set(chain)))
        for parent, child in zip(chain, chain[1:]):
            self.assertIn(child, appbuild._edges(str(HERE), parent))
            self.assertIn(child, graph)


class ServedPageTests(unittest.TestCase):
    def test_one_preload_link_per_closure_file_under_build_and_mount(self):
        graph = appbuild.boot_graph(str(HERE))
        for base in ("", "/dev"):
            links = LINK.findall(_served_page(base))
            self.assertEqual(
                links, ["%s/app/%s/%s" % (base, BUILD, rel) for rel in graph], base
            )

    def test_no_view_is_preloaded_and_no_marker_is_left(self):
        page = _served_page()
        self.assertNotIn("__OVERSEER_PRELOAD__", page)
        self.assertEqual([u for u in LINK.findall(page) if "/views/" in u], [])

    def test_the_page_on_disk_keeps_no_list_of_its_own(self):
        raw = (HERE / "index.html").read_text(encoding="utf-8")
        self.assertEqual(raw.count(appbuild.PRELOAD_PLACEHOLDER), 1)
        self.assertNotIn('rel="modulepreload"', raw)

    def test_a_page_that_lost_its_marker_is_refused(self):
        with self.assertRaises(ValueError):
            appbuild.preload(b"<html><head></head></html>", str(HERE))

    def test_the_hint_list_is_made_once_per_build(self):
        root = _tree(
            {
                "main.js": 'import "./a.js";\n',
                "a.js": "export const a = 1;\n",
                "b.js": "export const b = 2;\n",
            }
        )
        self.addCleanup(shutil.rmtree, root)
        self.addCleanup(appbuild._preload_memo.pop, root, None)
        (pathlib.Path(root) / "index.html").write_text("<html></html>", "utf-8")
        first = appbuild.preload_links(root)
        self.assertEqual(
            first.decode().splitlines(),
            [
                '<link rel="modulepreload" href="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/main.js">',
                '<link rel="modulepreload" href="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/a.js">',
            ],
        )
        real = appbuild.boot_graph
        calls = []

        def counted(*args, **kwargs):
            calls.append(args)
            return real(*args, **kwargs)

        appbuild.boot_graph = counted
        try:
            self.assertIs(appbuild.preload_links(root), first)
            self.assertEqual(calls, [])
            # A new build (a changed script) makes the list again.
            (pathlib.Path(root) / "app" / "main.js").write_text(
                'import "./a.js";\nimport "./b.js";\n', encoding="utf-8"
            )
            appbuild._memo.pop(root, None)
            again = appbuild.preload_links(root)
        finally:
            appbuild.boot_graph = real
        self.assertEqual(len(calls), 1)
        self.assertIn(b"/b.js", again)

    def test_the_worker_precaches_the_same_closure(self):
        original = map_server.BASE_PATH
        map_server.BASE_PATH = ""
        try:
            body = get("/sw.js").body().decode("utf-8")
        finally:
            map_server.BASE_PATH = original
        for rel in appbuild.boot_graph(str(HERE)):
            self.assertIn(json.dumps(rel), body, rel)


if __name__ == "__main__":
    unittest.main()
