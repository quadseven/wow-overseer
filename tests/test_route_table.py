"""The map server's fixed route tables, after the classic page went.

The classic page was the only reader of a set of GET routes. With it gone,
those routes answered nobody, so they are gone too and a request for one is
an ordinary 404. The routes something still reads stay, and so does every
POST route.
"""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402

# Read by nothing in app/, index.html, the Python outside tests/, the addons
# or the module once the classic page was deleted.
DEAD = (
    "/api/character",
    "/api/armory/guild",
    "/api/client/social",
    "/api/client/item",
    "/api/standing",
    "/api/achievements",
    "/api/dungeons",
    "/api/lineup",
    "/zones.json",
)


class FakeHandler(map_server.Handler):
    """A Handler with the socket cut off: the status it answered, nothing more."""

    def __init__(self, path):
        self.path = path
        self.command = "GET"
        self.headers = {}
        self.codes = []
        self.wfile = self

    def send_response(self, code, message=None):
        self.codes.append(code)

    def send_header(self, key, value):
        pass

    def end_headers(self):
        pass

    def write(self, body):
        pass


def status(path):
    h = FakeHandler(path)
    h.do_GET()
    return h.codes[0]


class TheClassicPagesRoutesAreGone(unittest.TestCase):
    def test_no_dead_route_is_in_the_table(self):
        for path in DEAD:
            self.assertNotIn(path, map_server.Handler.GET_ROUTES, path)

    def test_a_request_for_one_is_a_404(self):
        for path in DEAD:
            self.assertEqual(status(path + "?name=Grug&entry=5&guild=X"), 404, path)


class TheRoutesSomethingReadsStay(unittest.TestCase):
    def test_the_watch_and_director_reads_stay(self):
        # The operator Watcher UI reads /api/watch; the in-cluster director
        # and vision code read /api/director and /api/frame.
        routes = map_server.Handler.GET_ROUTES
        self.assertIs(routes["/api/watch"], map_server.Handler._watch_state)
        self.assertIs(routes["/api/director"], map_server.Handler._director_state)
        self.assertIs(routes["/api/frame"], map_server.Handler._frame_get)

    def test_the_static_files_the_page_loads_stay(self):
        routes = map_server.Handler.GET_ROUTES
        for path in ("/", "/index.html", "/shapes.json", "/healthz"):
            self.assertIn(path, routes, path)

    def test_every_post_route_stays(self):
        self.assertEqual(
            {k: v.__name__ for k, v in map_server.Handler.POST_ROUTES.items()},
            {
                "/api/chat": "_chat_post",
                "/api/decree": "_decree_post",
                "/api/watch": "_watch_post",
                "/api/director": "_director_post",
                "/api/frame": "_frame_post",
            },
        )


if __name__ == "__main__":
    unittest.main()
