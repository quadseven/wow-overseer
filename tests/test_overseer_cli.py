"""tools/overseer against a fake HTTP server (no network), and docs/API.md
against the routes the servers actually serve."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import gen_api_doc  # noqa: E402

_loader = importlib.machinery.SourceFileLoader(
    "overseer_cli", str(HERE / "tools" / "overseer")
)
_spec = importlib.util.spec_from_loader("overseer_cli", _loader)
overseer = importlib.util.module_from_spec(_spec)
_loader.exec_module(overseer)

SEEN = []
ANSWERS = {
    "/api/v2/stuck": [200, {"members": [{"name": "Grug", "step": "walk", "since": 5}]}],
    "/api/armory/member": [200, {"name": "Grug", "level": 12}],
    "/api/guildruns": [200, {"active": [], "recent": [{"id": 3, "state": "ended"}]}],
    "/api/v2/run": [404, {"error": "no such run", "id": 9}],
    "/api/realm": [200, {"build": "x"}],
    "/api/client/bags": [200, [{"bag": 1, "free": 4}, {"bag": 2, "free": 0}]],
    "/api/auras": [200, ["Grug", "Oden"]],
}


class Fake(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        SEEN.append(self.path)
        status, body = ANSWERS.get(self.path.split("?", 1)[0], [404, {"error": "nope"}])
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.env = mock.patch.dict(
            os.environ,
            {"OVERSEER_URL": "http://127.0.0.1:%d/" % cls.server.server_port},
        )
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def run_cli(self, *argv):
        SEEN.clear()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = overseer.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_stuck_path_and_guild(self):
        code, out, _ = self.run_cli("stuck")
        self.assertEqual((code, SEEN), (0, ["/api/v2/stuck"]))
        self.assertEqual(json.loads(out)["members"][0]["name"], "Grug")
        self.run_cli("stuck", "--guild", "cave")
        self.assertEqual(SEEN, ["/api/v2/stuck?guild=cave"])

    def test_member_path(self):
        code, out, _ = self.run_cli("member", "Grug")
        self.assertEqual((code, SEEN), (0, ["/api/armory/member?name=Grug"]))
        self.assertEqual(json.loads(out)["level"], 12)

    def test_runs_path_and_table(self):
        code, out, _ = self.run_cli("runs", "--table")
        self.assertEqual((code, SEEN), (0, ["/api/guildruns"]))
        self.assertEqual(out.split(), ["id", "state", "3", "ended"])

    def test_fake_routes_are_catalogued_routes(self):
        text = (HERE / "docs" / "API.md").read_text()
        for path in ANSWERS:
            self.assertIn("## `GET %s`" % path, text)

    def test_get_with_pairs(self):
        code, out, _ = self.run_cli("get", "/api/realm", "a=1", "b=two words")
        self.assertEqual(code, 0)
        self.assertEqual(SEEN, ["/api/realm?a=1&b=two+words"])
        self.assertEqual(json.loads(out), {"build": "x"})

    def test_table_on_stuck_members(self):
        _, out, _ = self.run_cli("--table", "stuck")
        self.assertEqual(out.splitlines()[0].split(), ["name", "step", "since"])

    def test_table_on_top_level_list(self):
        code, out, _ = self.run_cli("get", "/api/client/bags", "--table")
        self.assertEqual((code, SEEN), (0, ["/api/client/bags"]))
        self.assertEqual(out.split(), ["bag", "free", "1", "4", "2", "0"])

    def test_top_level_list_of_scalars_prints_json_but_no_table(self):
        code, out, _ = self.run_cli("get", "/api/auras")
        self.assertEqual((code, json.loads(out)), (0, ["Grug", "Oden"]))
        code, out, err = self.run_cli("get", "/api/auras", "--table")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("no list of records", err)

    def test_error_prints_status_and_body_and_exits_nonzero(self):
        code, out, err = self.run_cli("run", "9")
        self.assertEqual(SEEN, ["/api/v2/run?id=9"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("HTTP 404", err)
        self.assertIn("no such run", err)

    def test_bad_pair_and_missing_url(self):
        self.assertEqual(self.run_cli("get", "/api/realm", "oops")[0], 1)
        with mock.patch.dict(os.environ, {}, clear=True):
            code, _, err = self.run_cli("stuck")
        self.assertEqual(code, 1)
        self.assertIn("OVERSEER_URL", err)

    def test_routes_lists_catalog(self):
        code, out, _ = self.run_cli("routes")
        self.assertEqual(code, 0)
        self.assertIn("/api/v2/stuck", out)
        self.assertIn("/api/armory/member", out)


class CatalogTests(unittest.TestCase):
    def test_every_served_get_route_is_documented(self):
        import apiv2
        import map_server

        text = (HERE / "docs" / "API.md").read_text()
        served = set(map_server.Handler.GET_ROUTES) | set(apiv2.ROUTES)
        missing = sorted(p for p in served if f"## `GET {p}`" not in text)
        self.assertEqual(missing, [], "run python3 tools/gen_api_doc.py")

    def test_a_wrapped_first_sentence_is_read_whole(self):
        doc = """GET /api/x?name=X - the bank and its seven bag slots, a
        kept set saying why it is kept (#320). More after.

        Body."""
        self.assertEqual(
            gen_api_doc._split(doc),
            (
                ["name"],
                "the bank and its seven bag slots, a kept set saying why it is kept.",
            ),
        )

    def test_roster_and_stuck_answer_different_questions(self):
        summary = {e["path"]: e["summary"] for e in gen_api_doc.entries()}
        self.assertNotEqual(summary["/api/v2/roster"], summary["/api/v2/stuck"])

    def test_doc_is_current(self):
        self.assertEqual(
            gen_api_doc.main(["--check"]), 0, "run python3 tools/gen_api_doc.py"
        )


if __name__ == "__main__":
    unittest.main()
