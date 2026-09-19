"""The model-viewer cache: what is fetched, what is kept, what is refused.

The rules here are the ones a general-purpose proxy would get wrong and
this one must not: a path off the allowlist never leaves the pod, a path
with ".." in it never reaches the disk, an unreachable upstream is a 502
the page can act on, and the cache is bounded in bytes with the oldest
untouched file going first. All exercised with a fake fetcher, so none of
it needs a network.

Ticket: infra#88.
"""
import os
import tempfile
import time
import unittest

import modelviewer
from modelviewer import DiskCache, Store, classify


class WhatIsAllowed(unittest.TestCase):
    def test_every_prefix_the_viewer_uses_is_admitted(self):
        for path in ("meta/character/1.json", "meta/charactercustomization/1.json",
                     "meta/armor/1/1170.json", "meta/item/20379.json",
                     "m2/121087.m2", "skin/471401.skin", "anim/1.anim",
                     "bone/12.bone", "textures/1234.webp"):
            self.assertIsNotNone(classify(path), path)

    def test_the_content_type_is_the_files_own(self):
        self.assertEqual(classify("meta/item/1.json")[1], "application/json")
        self.assertEqual(classify("m2/1.m2")[1], "application/octet-stream")
        self.assertEqual(classify("skin/1.skin")[1], "application/octet-stream")
        self.assertEqual(classify("textures/1.webp")[1], "image/webp")

    def test_anything_off_the_allowlist_is_refused(self):
        """A cache for one page's known requests, not a proxy."""
        for path in ("", "meta/npc/1.json", "meta/object/1.json", "etc/passwd",
                     "modelviewer/m2/1.m2", "viewer/viewer.min.js", "mo3/1.mo3",
                     "deployment/viewer/c3f890f/viewer.min.js", "../meta/item/1.json"):
            self.assertIsNone(classify(path), path)

    def test_a_path_that_climbs_or_hides_is_refused(self):
        for path in ("meta/item/../../x.json", "meta/item//1.json",
                     "meta/item/1.json?x=1", "meta/item/%2e%2e/1.json",
                     "meta/item/1.json/", "m2/a b.m2", "textures/1.php"):
            self.assertIsNone(classify(path), path)

    def test_an_extension_with_no_content_type_is_refused(self):
        self.assertIsNone(classify("m2/1.wasm"))
        self.assertIsNone(classify("m2/model"))


class Fetcher:
    """A fake upstream: answers from a table, counts every call."""

    def __init__(self, table=None, fail=False):
        self.table = table or {}
        self.fail = fail
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if self.fail:
            raise OSError("unreachable")
        if url in self.table:
            return 200, self.table[url]
        return 404, b""


def store(fetcher, cap=modelviewer.DEFAULT_CAP_BYTES, clock=None):
    directory = tempfile.mkdtemp(prefix="mv-test-")
    kwargs = {"clock": clock} if clock else {}
    return Store(DiskCache(directory, cap), fetcher, **kwargs)


class TheReadThrough(unittest.TestCase):
    def test_the_first_request_fetches_and_the_second_does_not(self):
        f = Fetcher({modelviewer.UPSTREAM + "meta/item/1.json": b'{"a":1}'})
        s = store(f)
        first = s.serve("meta/item/1.json")
        second = s.serve("meta/item/1.json")
        self.assertEqual((first.status, first.body), (200, b'{"a":1}'))
        self.assertEqual((second.status, second.body), (200, b'{"a":1}'))
        self.assertEqual(len(f.calls), 1)

    def test_the_fetch_goes_to_the_wrath_environment_and_nowhere_else(self):
        f = Fetcher({modelviewer.UPSTREAM + "m2/1.m2": b"m"})
        store(f).serve("m2/1.m2")
        self.assertEqual(f.calls, ["https://wow.zamimg.com/modelviewer/wrath/m2/1.m2"])

    def test_a_refused_path_makes_no_outbound_call(self):
        f = Fetcher()
        r = store(f).serve("meta/npc/1.json")
        self.assertEqual(r.status, 404)
        self.assertEqual(f.calls, [])

    def test_a_kept_file_tells_the_browser_to_keep_it_too(self):
        f = Fetcher({modelviewer.UPSTREAM + "textures/1.webp": b"w"})
        r = store(f).serve("textures/1.webp")
        self.assertEqual(r.cache_control, "public, max-age=86400")
        self.assertEqual(r.content_type, "image/webp")

    def test_an_unreachable_upstream_is_a_502_not_a_hang_or_a_blank(self):
        """The page keys its fallback off a failed load; a 502 fails it."""
        r = store(Fetcher(fail=True)).serve("meta/character/1.json")
        self.assertEqual(r.status, 502)
        self.assertEqual(r.cache_control, "no-store")

    def test_an_upstream_error_is_a_502_and_is_not_kept(self):
        class Angry(Fetcher):
            def __call__(self, url):
                self.calls.append(url)
                return 503, b"later"
        f = Angry()
        s = store(f)
        self.assertEqual(s.serve("meta/item/1.json").status, 502)
        self.assertEqual(s.serve("meta/item/1.json").status, 502)
        self.assertEqual(len(f.calls), 2)

    def test_an_upstream_404_is_remembered_so_the_probe_stops_hitting_zamimg(self):
        """The viewer tries meta/armor and meta/item in turn for a weapon."""
        f = Fetcher()
        s = store(f)
        self.assertEqual(s.serve("meta/armor/5/9.json").status, 404)
        self.assertEqual(s.serve("meta/armor/5/9.json").status, 404)
        self.assertEqual(len(f.calls), 1)

    def test_a_remembered_404_expires(self):
        now = [1000.0]
        f = Fetcher()
        s = store(f, clock=lambda: now[0])
        s.serve("meta/armor/5/9.json")
        now[0] += modelviewer.MISS_TTL_SECONDS + 1
        s.serve("meta/armor/5/9.json")
        self.assertEqual(len(f.calls), 2)


class TheDisk(unittest.TestCase):
    def test_files_are_named_by_hash_not_by_path(self):
        """No path from the request ever becomes a path on the disk."""
        c = DiskCache(tempfile.mkdtemp(prefix="mv-test-"))
        c.put("meta/item/1.json", b"x")
        names = os.listdir(c.directory)
        self.assertEqual(len(names), 1)
        self.assertNotIn("/", names[0])
        self.assertTrue(names[0].endswith(".json"))
        self.assertEqual(c.get("meta/item/1.json"), b"x")

    def test_the_cap_holds_and_the_least_recently_touched_goes_first(self):
        c = DiskCache(tempfile.mkdtemp(prefix="mv-test-"), cap_bytes=25)
        c.put("m2/a.m2", b"a" * 10)
        old = c._name("m2/a.m2")
        c.put("m2/b.m2", b"b" * 10)
        # Touch a so b is the older one; mtimes need to differ on a coarse
        # filesystem, so set them explicitly rather than sleep.
        os.utime(c._name("m2/b.m2"), (time.time() - 100, time.time() - 100))
        self.assertIsNotNone(c.get("m2/a.m2"))
        evicted = []
        c.put("m2/c.m2", b"c" * 10)
        evicted = [n for n in ("a", "b", "c") if c.get(f"m2/{n}.m2") is None]
        self.assertEqual(evicted, ["b"])
        self.assertTrue(os.path.exists(old))

    def test_a_missing_directory_reads_as_empty_not_an_error(self):
        c = DiskCache(os.path.join(tempfile.mkdtemp(prefix="mv-test-"), "nope"))
        self.assertIsNone(c.get("m2/a.m2"))
        self.assertEqual(c.evict(), [])

    def test_the_default_directory_is_the_pods_when_the_pod_says_so(self):
        os.environ["MODEL_CACHE_DIR"] = "/var/cache/modelviewer"
        try:
            self.assertEqual(modelviewer.default_cache_dir(), "/var/cache/modelviewer")
        finally:
            del os.environ["MODEL_CACHE_DIR"]
        self.assertTrue(modelviewer.default_cache_dir().endswith("wow-modelviewer"))


class TheEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.server = open(os.path.join(here, "map_server.py")).read()
        cls.dockerfile = open(os.path.join(here, "Dockerfile")).read()

    def test_the_route_is_a_prefix_and_the_prefix_is_the_pages_content_path(self):
        self.assertIn('MODEL_PREFIX = "/modelviewer/"', self.server)
        self.assertIn("if path.startswith(MODEL_PREFIX):", self.server)

    def test_the_fetch_carries_a_browser_user_agent_and_a_timeout(self):
        """zamimg answers 403 to anything that does not look like a browser,
        and an upstream that hangs must become a 502 rather than a stuck
        thread per request."""
        fetch = self.server[self.server.index("def _fetch_upstream"):]
        fetch = fetch[:fetch.index("MODELS = ")]
        self.assertIn('"User-Agent": modelviewer.USER_AGENT', fetch)
        self.assertIn("timeout=modelviewer.UPSTREAM_TIMEOUT_SECONDS", fetch)
        self.assertIn("except urllib.error.HTTPError", fetch)

    # test_the_cache_is_an_emptydir_on_the_pod removed here: it asserted
    # against quadseven/infra's production/oke/manifests/wow/80-map.yaml,
    # which this repo does not carry (infra owns the deployment manifests).
    # An equivalent assertion should live in infra's own render-test suite
    # for that manifest instead - see the tracking issue for this split.

    def test_the_module_ships_in_the_image(self):
        self.assertIn("modelviewer.py", self.dockerfile)


if __name__ == "__main__":
    unittest.main()
