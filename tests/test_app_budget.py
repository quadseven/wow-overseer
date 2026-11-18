"""The boot path stays inside its committed budget (wow-overseer#2320)."""

import base64
import os
import pathlib
import re
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from scripts import app_budget  # noqa: E402

PAGE = (
    "<!doctype html><html><head>"
    '<link rel="stylesheet" href="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/app.css">'
    "%s</head><body>"
    '<script type="module" src="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/main.js"></script>'
    "</body></html>"
)


def fabricate(root, files, head=""):
    """A minimal app under `root`: the page plus `files` (path under app/ to text)."""
    os.makedirs(os.path.join(root, "app"), exist_ok=True)
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as f:
        f.write(PAGE % head)
    files = {"app.css": "body { margin: 0; }\n", **files}
    for rel, text in files.items():
        path = os.path.join(root, "app", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def limits():
    return app_budget.load(str(HERE))["boot"]["limits"]


class TheRepositoryIsInsideItsBudget(unittest.TestCase):
    def test_every_number_is_inside_its_limit(self):
        measured = app_budget.measure(str(HERE))
        self.assertEqual([], app_budget.check(measured, limits(), str(HERE)))

    def test_every_measured_number_has_a_limit_and_every_limit_is_measured(self):
        self.assertEqual(set(limits()), set(app_budget.measure(str(HERE))))

    def test_the_page_names_no_third_party_host(self):
        self.assertEqual(0, limits()["third_party_hosts"])
        self.assertEqual([], app_budget.third_party_hosts(str(HERE)))


class AHeavyModuleFails(unittest.TestCase):
    def test_a_module_that_pushes_the_sent_bytes_over_fails_and_is_named(self):
        heavy = base64.b64encode(os.urandom(150_000)).decode("ascii")
        with tempfile.TemporaryDirectory() as root:
            fabricate(
                root,
                {
                    "main.js": 'import "./heavy.js";\n',
                    "heavy.js": 'export const blob = "%s";\n' % heavy,
                },
            )
            measured = app_budget.measure(root)
            problems = app_budget.check(measured, limits(), root)
        self.assertGreater(measured["boot_sent_bytes"], limits()["boot_sent_bytes"])
        self.assertEqual(1, len(problems), problems)
        self.assertIn(
            "boot_sent_bytes is %d" % measured["boot_sent_bytes"], problems[0]
        )
        self.assertIn("limit of %d" % limits()["boot_sent_bytes"], problems[0])
        self.assertIn("app/heavy.js", problems[0])

    def test_a_small_file_is_sent_as_it_is_and_a_large_one_gzipped(self):
        small = b"x" * (app_budget.GZIP_MIN_BYTES - 1)
        large = b"x" * app_budget.GZIP_MIN_BYTES
        self.assertEqual(len(small), app_budget.sent_bytes(small))
        self.assertLess(app_budget.sent_bytes(large), len(large))


class AThirdPartyHostFails(unittest.TestCase):
    def test_a_page_that_names_another_host_fails_and_names_it(self):
        link = '<link rel="preconnect" href="https://fonts.example.net">'
        with tempfile.TemporaryDirectory() as root:
            fabricate(root, {"main.js": "export {};\n"}, head=link)
            problems = app_budget.check(app_budget.measure(root), limits(), root)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("third_party_hosts is 1, over its limit of 0", problems[0])
        self.assertIn("fonts.example.net", problems[0])

    def test_a_stylesheet_that_names_another_host_fails(self):
        css = '@import url("https://cdn.example.org/x.css");\n'
        with tempfile.TemporaryDirectory() as root:
            fabricate(root, {"main.js": "export {};\n", "app.css": css})
            self.assertEqual(["cdn.example.org"], app_budget.third_party_hosts(root))

    def test_an_xml_namespace_is_not_a_host(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        with tempfile.TemporaryDirectory() as root:
            fabricate(root, {"main.js": "export {};\n"}, head=svg)
            self.assertEqual([], app_budget.third_party_hosts(root))


class ADeepChainFails(unittest.TestCase):
    def test_a_chain_one_deeper_than_the_limit_fails_and_is_shown(self):
        depth = limits()["import_depth"] + 1
        files = {}
        for i in range(depth):
            name = "main.js" if i == 0 else "m%d.js" % i
            nxt = 'import "./m%d.js";\n' % (i + 1) if i + 1 < depth else "export {};\n"
            files[name] = nxt
        with tempfile.TemporaryDirectory() as root:
            fabricate(root, files)
            measured = app_budget.measure(root)
            problems = app_budget.check(measured, limits(), root)
        self.assertEqual(depth, measured["import_depth"])
        self.assertEqual(1, len(problems), problems)
        self.assertIn("import_depth is %d" % depth, problems[0])
        self.assertIn("main.js > m1.js", problems[0])


class EveryRaiseCarriesAReason(unittest.TestCase):
    def test_the_committed_budget_explains_every_limit(self):
        self.assertEqual([], app_budget.unexplained(app_budget.load(str(HERE))["boot"]))

    def test_a_raised_limit_with_no_new_entry_is_named(self):
        boot = app_budget.load(str(HERE))["boot"]
        boot["limits"]["boot_modules"] += 1
        problems = app_budget.unexplained(boot)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("boot_modules", problems[0])

    def test_a_raise_with_an_empty_reason_is_named(self):
        boot = app_budget.load(str(HERE))["boot"]
        boot["limits"]["boot_modules"] += 1
        boot["raises"].append(
            {
                "name": "boot_modules",
                "limit": boot["limits"]["boot_modules"],
                "reason": " ",
            }
        )
        problems = app_budget.unexplained(boot)
        self.assertEqual(1, len(problems), problems)
        self.assertIn("gives no reason", problems[0])

    def test_a_raise_with_a_reason_is_accepted(self):
        boot = app_budget.load(str(HERE))["boot"]
        boot["limits"]["boot_modules"] += 1
        boot["raises"].append(
            {
                "name": "boot_modules",
                "limit": boot["limits"]["boot_modules"],
                "reason": "The Now page boots one more module for the wall.",
            }
        )
        self.assertEqual([], app_budget.unexplained(boot))

    def test_a_limit_with_no_entry_is_named(self):
        boot = {"limits": {"boot_modules": 3}, "raises": []}
        self.assertEqual(
            ['boot_modules has no entry under "raises".'], app_budget.unexplained(boot)
        )


class TheServerSendsWhatIsMeasured(unittest.TestCase):
    """The measure gzips as map_server._gzipped does for a static file."""

    SOURCE = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_size_floor_matches_the_server(self):
        floor = re.search(r"^GZIP_MIN_BYTES = (\d+)$", self.SOURCE, re.M)
        self.assertIsNotNone(floor)
        self.assertEqual(int(floor.group(1)), app_budget.GZIP_MIN_BYTES)

    def test_the_static_level_matches_the_server(self):
        level = re.search(
            r"packed = gzip\.compress\(body, (\d+), mtime=0\)", self.SOURCE
        )
        self.assertIsNotNone(level)
        self.assertEqual(int(level.group(1)), app_budget.GZIP_STATIC_LEVEL)


if __name__ == "__main__":
    unittest.main()
