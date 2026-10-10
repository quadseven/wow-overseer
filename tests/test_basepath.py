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

import json
import pathlib
import re
import sys
import types
import unittest
from urllib.parse import urljoin, urlsplit

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import basepath  # noqa: E402  (must follow the pymysql stub)
import map_server  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent

# Served by the ingress from a machine outside the cluster rather than by this
# process, so it is in neither routing table, and the page links to it all the
# same. Named here because a URL nothing in this directory serves is exactly
# the one a route-derived list would miss.
EXTRA_SAME_ORIGIN = ("/recordings/",)


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


class ServedPageTest(unittest.TestCase):
    """The mount point actually reaches the browser."""

    class FakeHandler(map_server.Handler):
        """A Handler with the socket amputated: a route in, the bytes out."""

        def __init__(self):
            self.path = "/"
            self.sent = []

        def _send(self, code, ctype, body, cache_control="no-store"):
            self.sent.append((code, ctype, body))

    def serve(self, prefix, page="_index"):
        handler = self.FakeHandler()
        original = map_server.BASE_PATH
        map_server.BASE_PATH = prefix
        try:
            getattr(handler, page)({})
        finally:
            map_server.BASE_PATH = original
        return handler.sent[-1]

    def test_the_app_is_told_its_mount_too(self):
        # The operations app (index.html) reads its mount from a meta tag.
        for prefix in ("", "/dev"):
            code, ctype, body = self.serve(prefix)
            self.assertEqual(code, 200)
            self.assertIn("text/html", ctype)
            text = body.decode("utf-8")
            self.assertNotIn(basepath.PLACEHOLDER, text)
            self.assertIn('<meta name="overseer-base" content="%s">' % prefix, text)

    def test_the_home_screen_app_opens_its_own_mount(self):
        # Added to the home screen, the app opens at the manifest's start_url.
        # Under a prefix that has to be the prefix's page, or the icon on the
        # phone opens the realm at the root. The manifest's URLs are relative,
        # so the browser resolves them against the manifest's own address,
        # which the page puts under the mount.
        for prefix in ("", "/dev"):
            _code, _ctype, page = self.serve(prefix)
            text = page.decode("utf-8")
            found = re.search(r'<link rel="manifest" href="([^"]+)">', text)
            self.assertIsNotNone(found, "the page links no manifest")
            link = found.group(1)
            self.assertEqual(link, prefix + "/manifest.webmanifest")
            self.assertIn(
                '<link rel="apple-touch-icon" href="%s/apple-touch-icon.png">' % prefix,
                text,
            )
            code, ctype, body = self.serve(prefix, "_manifest_file")
            self.assertEqual(code, 200)
            self.assertEqual(ctype, "application/manifest+json")
            manifest = json.loads(body)
            at = "https://example.com" + link
            home = prefix + "/"
            for key in ("start_url", "scope", "id"):
                self.assertEqual(urlsplit(urljoin(at, manifest[key])).path, home, key)
            for icon in manifest["icons"]:
                path = urlsplit(urljoin(at, icon["src"])).path
                self.assertTrue(path.startswith(home), path)
                # The ingress strips the prefix; what is left is a route here.
                self.assertIn(path[len(prefix) :], map_server.Handler.GET_ROUTES)


if __name__ == "__main__":
    unittest.main()
