"""The page can be mounted under a path, and every URL it emits follows it.

WHY THIS SUITE EXISTS. Three realms are served from one hostname now, told
apart by the path: production at the root, the others under a prefix. The
danger in that arrangement is not a broken link. A browser resolves an
absolute path against the ORIGIN and not against the path the document came
from, so a page served under a prefix that emits one root-anchored URL does
not fail. It reads the realm at the root, which is production, and renders
production's characters under a path promising otherwise. That is the same
silent, symptomless failure the ingress guard in
../../oke/manifests/wow-dev/tests exists to catch, arriving through the front
end instead of through a proxy target.

So the load-bearing test here is not any single assertion about normalize(). It
is test_every_server_route_is_reached_through_the_mount_helper, which takes the
endpoint list FROM THE SERVER rather than from a copy, and so fails the day a
new endpoint is added to the page with a root-anchored URL.

Ticket: infra#3239.
"""
import pathlib
import re
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import basepath  # noqa: E402  (must follow the pymysql stub)
import map_server  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
PAGE = (HERE.parent / "index.html").read_text(encoding="utf-8")

# Served by the ingress from a machine outside the cluster rather than by this
# process, so it is in neither routing table, and the page links to it all the
# same. Named here because a URL nothing in this directory serves is exactly
# the one a route-derived list would miss.
EXTRA_SAME_ORIGIN = ("/recordings/",)


def page_code_lines():
    """The page with its comment-only lines dropped.

    The prose in that file quotes the very URLs being asserted about, and a
    check that could not tell a sentence from a call site would either fail on
    the explanation or be weakened until it passed. Only whole-line comments
    are dropped, so a URL smuggled onto the end of a code line is still seen.
    """
    return [line for line in PAGE.splitlines() if not line.strip().startswith("//")]


class NormalizeTest(unittest.TestCase):
    def test_nothing_at_all_means_the_root(self):
        # The load-bearing default: the realm at the root sets nothing new and
        # must keep behaving exactly as it did.
        for value in (None, "", "   ", "/"):
            self.assertEqual(basepath.normalize(value), "")

    def test_a_prefix_comes_back_ready_to_concatenate(self):
        # Every spelling an operator might reasonably write lands on the one
        # form that makes prefix + an absolute path correct without a branch.
        for value in ("/dev", "dev", "/dev/", "dev/", "  /dev/  ", "//dev//"):
            self.assertEqual(basepath.normalize(value), "/dev")

    def test_a_deeper_mount_point_keeps_its_shape(self):
        self.assertEqual(basepath.normalize("/worlds/dev/"), "/worlds/dev")

    def test_a_value_that_cannot_be_read_stops_the_process(self):
        # NOT a fallback to the root, and this is the whole reason the function
        # can raise at all: the root is production. A prefixed realm handed the
        # root's URLs reads production and says nothing about it.
        bad = ['/dev"', "/de v", "/dev\\x", "http://elsewhere/dev", "/../wow"]
        for value in bad:
            with self.assertRaises(ValueError):
                basepath.normalize(value)

    def test_the_refusal_names_the_variable_and_the_way_out(self):
        with self.assertRaises(ValueError) as caught:
            basepath.normalize('/de"v')
        message = str(caught.exception)
        self.assertIn(basepath.ENV_VAR, message)
        self.assertIn("leave it unset", message)


class ApplyTest(unittest.TestCase):
    def test_the_prefix_reaches_the_page(self):
        body = b"x = '" + basepath.PLACEHOLDER.encode() + b"';"
        self.assertEqual(basepath.apply(body, "/dev"), b"x = '/dev';")

    def test_the_root_substitutes_to_nothing(self):
        body = b"[" + basepath.PLACEHOLDER.encode() + b"]"
        self.assertEqual(basepath.apply(body, ""), b"[]")

    def test_a_page_with_no_placeholder_is_refused(self):
        # Serving it would look completely normal and address the wrong realm,
        # which is the one outcome this module exists to prevent.
        with self.assertRaises(ValueError):
            basepath.apply(b"<html></html>", "/dev")


class PageTest(unittest.TestCase):
    """What the shipped page has to look like for any of the above to matter."""

    def test_the_page_carries_exactly_one_placeholder(self):
        # More than one would still substitute, but it would mean two places
        # decide where the page is mounted, and two places can disagree.
        self.assertEqual(PAGE.count(basepath.PLACEHOLDER), 1)

    def test_the_page_declares_the_helper_once_and_falls_back_to_the_root(self):
        self.assertEqual(len(re.findall(r"\bfunction u\(", PAGE)), 1)
        self.assertEqual(len(re.findall(r"\bconst BASE\b", PAGE)), 1)
        # The fallback matters for a copy of this file opened straight off
        # disk, where the token is still a literal token: it has to read as the
        # root rather than as a path segment named after the placeholder.
        self.assertIn('charAt(0) === "/"', PAGE)

    def test_every_server_route_is_reached_through_the_mount_helper(self):
        # THE ONE THAT MATTERS. The list comes from the server's own routing
        # tables, so an endpoint added to both sides is covered here without
        # anybody remembering this file exists.
        routes = set(map_server.Handler.GET_ROUTES)
        routes |= set(map_server.Handler.POST_ROUTES)
        routes.discard("/")            # the root is not a literal the page writes
        routes.discard("/index.html")  # nor is the page's own name
        routes.add(map_server.MODEL_PREFIX)
        routes.update(EXTRA_SAME_ORIGIN)
        lines = page_code_lines()
        checked = 0
        for route in sorted(routes):
            for number, line in enumerate(lines, 1):
                for match in re.finditer(re.escape('"' + route), line):
                    checked += 1
                    start = max(0, match.start() - 2)
                    self.assertEqual(
                        line[start:match.start() + 1],
                        'u("',
                        f"index.html writes {route!r} outside u() at code line "
                        f"{number}. A root-anchored URL on a page served under "
                        "a prefix reads the realm at the ROOT, which is "
                        "production, and renders its characters with no error "
                        "anywhere on the page.",
                    )
        # A scan that matched nothing would pass forever. These URLs are the
        # page's entire conversation with its realm, so finding none means the
        # scan is broken rather than the page being clean.
        self.assertGreater(checked, 15)

    def test_no_base_element_ever_appears(self):
        # A <base href> is the obvious fix and it is the wrong one here: it
        # also rewrites in-page fragment links and the functional IRI
        # references that point this page's SVG arrowheads at their own marker
        # definitions, which would start resolving against another document.
        # The second assertion is what keeps the first one honest: the page
        # really does use those references.
        self.assertNotIn("<base ", PAGE)
        self.assertIn("url(#ah-", PAGE)


class ServedPageTest(unittest.TestCase):
    """The mount point actually reaches the browser."""

    class FakeHandler(map_server.Handler):
        """A Handler with the socket amputated: a route in, the bytes out."""

        def __init__(self):
            self.path = "/"
            self.sent = []

        def _send(self, code, ctype, body, cache_control="no-store"):
            self.sent.append((code, ctype, body))

    def serve(self, prefix):
        handler = self.FakeHandler()
        original = map_server.BASE_PATH
        map_server.BASE_PATH = prefix
        try:
            handler._index({})
        finally:
            map_server.BASE_PATH = original
        return handler.sent[-1]

    def test_the_root_serves_the_page_it_always_served(self):
        code, ctype, body = self.serve("")
        self.assertEqual(code, 200)
        self.assertIn("text/html", ctype)
        text = body.decode("utf-8")
        self.assertNotIn(basepath.PLACEHOLDER, text)
        self.assertIn('})("");', text)

    def test_a_prefixed_realm_gets_its_prefix(self):
        code, _ctype, body = self.serve("/dev")
        self.assertEqual(code, 200)
        text = body.decode("utf-8")
        self.assertNotIn(basepath.PLACEHOLDER, text)
        self.assertIn('})("/dev");', text)


if __name__ == "__main__":
    unittest.main()
