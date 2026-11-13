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
import unittest
from urllib.parse import urljoin, urlsplit

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import basepath
    import map_server

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


GOOD_ID = "Q7m2Zk9xLw3TnB8vCd5Rha"  # 22 characters, an invented value
assert len(GOOD_ID) == 22


class SecretMountTest(unittest.TestCase):
    """The mount can come from one secret id, validated, never echoed."""

    def mount(self, **env):
        return basepath.mount_from_environment(env)

    def test_a_well_formed_id_is_mounted_under_the_fixed_prefix(self):
        self.assertEqual(self.mount(OVERSEER_SITE_PATH_ID=GOOD_ID), "/d/" + GOOD_ID)
        long_id = "A-_" * 40  # 120 characters of the base64url alphabet
        self.assertEqual(self.mount(OVERSEER_SITE_PATH_ID=long_id), "/d/" + long_id)

    def test_the_id_is_trimmed(self):
        self.assertEqual(
            self.mount(OVERSEER_SITE_PATH_ID="  " + GOOD_ID + "\n"), "/d/" + GOOD_ID
        )

    def test_unset_or_empty_means_the_existing_setting(self):
        # A Secret committed empty reads as an empty variable, so an empty id
        # must mean "not configured", exactly like an absent one.
        for env in ({}, {"OVERSEER_SITE_PATH_ID": ""}, {"OVERSEER_SITE_PATH_ID": "  "}):
            self.assertEqual(self.mount(**env), "")
            self.assertEqual(self.mount(OVERSEER_BASE_PATH="/dev", **env), "/dev")

    def test_the_id_wins_over_the_older_setting_when_both_are_set(self):
        # The pod manifest still carries the older setting while the id is
        # optional; once the id is set it must be the one that counts.
        self.assertEqual(
            self.mount(OVERSEER_BASE_PATH="/dev", OVERSEER_SITE_PATH_ID=GOOD_ID),
            "/d/" + GOOD_ID,
        )

    def test_a_short_malformed_or_over_long_id_stops_the_process(self):
        bad = [
            "short",
            GOOD_ID[:-1],
            GOOD_ID + " x",
            GOOD_ID + "/",
            "/" + GOOD_ID,
            GOOD_ID + '"',
            "..." + GOOD_ID,
            GOOD_ID.replace("Z", "%"),
            "A" * 129,
        ]
        for value in bad:
            with self.subTest(value=len(value)):
                with self.assertRaises(ValueError):
                    self.mount(OVERSEER_SITE_PATH_ID=value)

    def test_no_refusal_contains_the_value(self):
        bad = ["short", GOOD_ID + '"', "x" * 200, GOOD_ID.replace("Z", "%")]
        for value in bad:
            with self.assertRaises(ValueError) as caught:
                self.mount(OVERSEER_SITE_PATH_ID=value)
            message = str(caught.exception)
            self.assertNotIn(value, message)
            self.assertNotIn(value.strip(), message)
            self.assertNotIn(repr(value), message)
            self.assertIn(basepath.SITE_PATH_ID_VAR, message)

    def test_the_older_setting_still_raises_as_before(self):
        with self.assertRaises(ValueError):
            self.mount(OVERSEER_BASE_PATH='/de"v')

    def test_the_server_reads_its_mount_through_it(self):
        source = (HERE.parent / "map_server.py").read_text(encoding="utf-8")
        self.assertIn("BASE_PATH = basepath.mount_from_environment(os.environ)", source)

    def test_the_mount_it_builds_is_a_usable_prefix(self):
        prefix = self.mount(OVERSEER_SITE_PATH_ID=GOOD_ID)
        self.assertEqual(basepath.normalize(prefix), prefix)
        page = basepath.apply(b"[" + basepath.PLACEHOLDER.encode() + b"]", prefix)
        self.assertEqual(page, ("[" + prefix + "]").encode())


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

    def test_under_the_secret_mount_every_page_url_stays_under_it(self):
        # AI-REVIEW 2026-11-12 [grug-elder/code-review] 2326-E1 (PR #2326):
        # the mount built from the id is exercised on the served page itself,
        # not only as a token in a byte string. A root-anchored URL here would
        # resolve against the origin and read another realm.
        prefix = basepath.mount_from_environment({"OVERSEER_SITE_PATH_ID": GOOD_ID})
        code, _ctype, body = self.serve(prefix)
        self.assertEqual(code, 200)
        text = body.decode("utf-8")
        self.assertNotIn(basepath.PLACEHOLDER, text)
        self.assertIn('<meta name="overseer-base" content="%s">' % prefix, text)
        urls = re.findall(r'(?:href|src)="([^"]+)"', text)
        same_origin = [
            u for u in urls if not urlsplit(u).scheme and not u.startswith("//")
        ]
        self.assertTrue(same_origin, "the page links nothing of its own")
        page_url = "https://example.invalid" + prefix + "/"
        for url in same_origin:
            resolved = urlsplit(urljoin(page_url, url)).path
            self.assertTrue(resolved.startswith(prefix + "/"), url)

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
