"""The performance budget keeps the first-load gains from eroding.

WHY. The app got fast by removing weight from its boot path: fewer round
trips, no third-party hosts, small compressed scripts. Nothing stopped it
getting slow again one module at a time. perf-budget.json holds numbers
measured from the files on disk; this test (which CI runs with the rest) fails
the pull request that crosses one, naming the number, the limit and the
biggest files.

Ticket: #2320 (epic #2309).
"""

import gzip
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import perfbudget  # noqa: E402

PAGE = """<!doctype html><html><head>
<link rel="stylesheet" href="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/app.css">
<link rel="preload" as="font" type="font/woff2" crossorigin href="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/fonts/f.woff2">
%s
<!--__OVERSEER_PRELOAD__-->
<script type="module" src="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/main.js"></script>
</head><body></body></html>
"""

LIMITS = {
    "boot_gzip_bytes": 4000,
    "boot_modules": 4,
    "import_depth": 3,
    "third_party_hosts": 0,
    "font_bytes": 100,
    "boot_requests": 8,
}


def fake_root(extra_head="", heavy=0, chain=0):
    """A small app on disk: main -> a -> b, a stylesheet and a font."""
    tmp = tempfile.TemporaryDirectory()
    root = pathlib.Path(tmp.name)
    (root / "app" / "fonts").mkdir(parents=True)
    (root / "index.html").write_text(PAGE % extra_head, encoding="utf-8")
    (root / "app" / "main.js").write_text('import "./a.js";\n', encoding="utf-8")
    (root / "app" / "a.js").write_text(
        'import "./b.js";\nexport const a = 1;\n', encoding="utf-8"
    )
    (root / "app" / "b.js").write_text("export const b = 1;\n", encoding="utf-8")
    (root / "app" / "app.css").write_text("body{margin:0}\n", encoding="utf-8")
    (root / "app" / "fonts" / "f.woff2").write_bytes(b"x" * 60)
    if heavy:
        # Random-looking text does not compress, so this really adds bytes.
        import hashlib

        junk = "".join(
            hashlib.sha256(str(i).encode()).hexdigest() for i in range(heavy)
        )
        (root / "app" / "b.js").write_text(
            'export const junk = "%s";\n' % junk, encoding="utf-8"
        )
    if chain:
        previous = "b.js"
        for i in range(chain):
            name = "c%d.js" % i
            (root / "app" / previous).write_text(
                (root / "app" / previous).read_text(encoding="utf-8")
                + 'import "./%s";\n' % name,
                encoding="utf-8",
            )
            (root / "app" / name).write_text(
                "export const x%d = 1;\n" % i, encoding="utf-8"
            )
            previous = name
    return tmp, root


def budget(limits=None):
    return {"limits": dict(LIMITS, **(limits or {})), "raises": []}


class Measuring(unittest.TestCase):
    def test_it_counts_what_the_page_loads_at_boot(self):
        tmp, root = fake_root()
        with tmp:
            got = perfbudget.measure(str(root))
        self.assertEqual(got["boot_modules"], 3)
        self.assertEqual(got["import_depth"], 3)
        self.assertEqual(got["third_party_hosts"], 0)
        self.assertEqual(got["font_bytes"], 60)
        # three modules, the stylesheet and the font; main.js is named twice.
        self.assertEqual(got["boot_requests"], 5)
        self.assertGreater(got["boot_gzip_bytes"], 0)

    def test_the_gzip_bytes_are_those_the_server_sends(self):
        tmp, root = fake_root()
        with tmp:
            got = perfbudget.measure(str(root))
            want = sum(
                len(gzip.compress((root / "app" / n).read_bytes(), 5, mtime=0))
                for n in ("main.js", "a.js", "b.js", "app.css")
            )
        self.assertEqual(got["boot_gzip_bytes"], want)

    def test_a_third_party_host_in_the_page_or_a_stylesheet_is_counted_once_each(self):
        tmp, root = fake_root(
            '<link rel="stylesheet" href="https://fonts.example.com/css">'
        )
        with tmp:
            (root / "app" / "app.css").write_text(
                '@import url("https://cdn.example.org/x.css");\n', encoding="utf-8"
            )
            got = perfbudget.measure(str(root))
        self.assertEqual(got["third_party_hosts"], 2)

    def test_a_link_in_a_script_is_not_a_boot_host(self):
        tmp, root = fake_root()
        with tmp:
            (root / "app" / "b.js").write_text(
                'export const u = "https://www.example.com/x";\n', encoding="utf-8"
            )
            got = perfbudget.measure(str(root))
        self.assertEqual(got["third_party_hosts"], 0)


class Checking(unittest.TestCase):
    def test_a_repository_inside_every_limit_passes(self):
        tmp, root = fake_root()
        with tmp:
            self.assertEqual(
                perfbudget.check(perfbudget.measure(str(root)), budget()), []
            )

    def test_a_heavy_module_in_the_boot_graph_fails_naming_the_number_and_the_file(
        self,
    ):
        tmp, root = fake_root(heavy=200)
        with tmp:
            problems = perfbudget.check(
                perfbudget.measure(str(root)), budget(), root=str(root)
            )
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("boot_gzip_bytes", problems[0])
        self.assertIn("4000", problems[0])
        self.assertIn("app/b.js", problems[0])

    def test_a_third_party_host_fails(self):
        tmp, root = fake_root(
            '<link rel="stylesheet" href="https://fonts.example.com/css">'
        )
        with tmp:
            problems = perfbudget.check(perfbudget.measure(str(root)), budget())
        self.assertTrue(any("third_party_hosts" in p for p in problems), problems)

    def test_a_deeper_import_chain_fails(self):
        tmp, root = fake_root(chain=2)
        with tmp:
            problems = perfbudget.check(perfbudget.measure(str(root)), budget())
        self.assertTrue(
            any("import_depth" in p and "5" in p and "3" in p for p in problems),
            problems,
        )

    def test_a_limit_the_budget_lacks_fails_rather_than_passing_unchecked(self):
        tmp, root = fake_root()
        with tmp:
            partial = budget()
            del partial["limits"]["font_bytes"]
            problems = perfbudget.check(perfbudget.measure(str(root)), partial)
        self.assertTrue(
            any("font_bytes" in p and "no limit" in p for p in problems), problems
        )


class TheBudgetFile(unittest.TestCase):
    def setUp(self):
        self.budget = json.loads(
            (HERE / "perf-budget.json").read_text(encoding="utf-8")
        )

    def test_the_repository_is_inside_its_own_budget(self):
        problems = perfbudget.check(
            perfbudget.measure(str(HERE)), self.budget, root=str(HERE)
        )
        self.assertEqual(problems, [], "\n".join(problems))

    def test_every_limit_carries_the_reason_for_its_current_value(self):
        for name, limit in self.budget["limits"].items():
            raises = [r for r in self.budget["raises"] if r["limit"] == name]
            self.assertTrue(raises, "%s has no entry in raises" % name)
            self.assertEqual(
                raises[-1]["max"], limit, "%s changed without a new raises entry" % name
            )
            self.assertGreaterEqual(
                len(raises[-1]["why"].strip()), 20, "%s needs a real reason" % name
            )

    def test_a_raise_names_a_limit_that_exists(self):
        for r in self.budget["raises"]:
            self.assertIn(r["limit"], self.budget["limits"])

    def test_the_budget_covers_every_number_that_is_measured(self):
        self.assertEqual(set(self.budget["limits"]), set(perfbudget.measure(str(HERE))))

    def test_nothing_third_party_is_the_standing_rule(self):
        self.assertEqual(self.budget["limits"]["third_party_hosts"], 0)


if __name__ == "__main__":
    unittest.main()
