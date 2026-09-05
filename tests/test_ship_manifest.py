"""Every module that ships must be in the image.

The build's shared-dir copy takes TOP-LEVEL FILES ONLY and the Dockerfile
names them explicitly, so a new module is one forgotten line away from an
image that imports something it does not contain - a crash at pod start,
long after CI went green.

This is not hypothetical: merging three concurrent feature branches on
2026-08-21, a git rerere replay resolved the Dockerfile conflict by keeping
two of the three new modules and silently dropping panel.py, which
map_server.py imports. Caught by hand; this test is so the next one is not.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE = os.path.normpath(
    os.path.join(HERE, "..", "..", "docker", "wow-overseer", "Dockerfile")
)


def _copied_files() -> set:
    with open(DOCKERFILE, encoding="utf-8") as f:
        text = f.read()
    # EVERY `COPY ... /app/` block, not the first one. The Dockerfile grew a
    # second COPY when jquery.min.js moved out of the shared tarball and into
    # this image's own build context, and a non-greedy search for the first
    # block silently returned that one instead - reporting that fifty modules
    # had stopped shipping. The failure was in the reader, not the manifest.
    blocks = re.findall(r"^COPY\s(.*?)\s/app/", text, re.MULTILINE | re.DOTALL)
    assert blocks, "no COPY ... /app/ block found in the Dockerfile"
    return {name for b in blocks for name in re.findall(r"_shared/(\S+)", b)}


def _context_files() -> set:
    """Files copied from the build CONTEXT rather than the shared tarball.

    The shared dir is packed into one configMap and handed to every image built
    from it, so a browser asset there is charged to the bridge as well as to
    the map. This image's own context is the right home for one.
    """
    with open(DOCKERFILE, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(r"^COPY\s+([^/\s]+)\s+/app/", text, re.MULTILINE))


class ShipManifestTest(unittest.TestCase):
    def test_every_top_level_module_is_copied_into_the_image(self):
        on_disk = {f for f in os.listdir(HERE) if f.endswith(".py")}
        missing = sorted(on_disk - _copied_files())
        self.assertEqual(
            missing, [], "modules present but NOT in the Dockerfile COPY: %s" % missing
        )

    def test_every_copied_module_exists_on_disk(self):
        copied_py = {f for f in _copied_files() if f.endswith(".py")}
        phantom = sorted(copied_py - set(os.listdir(HERE)))
        self.assertEqual(
            phantom, [], "Dockerfile COPYs files that do not exist: %s" % phantom
        )

    def test_every_continuation_is_a_real_line_break(self):
        """A backslash that is not the last character on its line is not a
        continuation, it is an argument.

        The manifest tests above read the COPY block as text, so a line break
        that got written as the two characters backslash-n still parses into
        the right set of filenames and still reports healthy - while docker
        would take the backslash-n as part of a path and fail the build. That
        build runs on a push to main and NEVER on a pull request
        (build.wow-overseer.yml's own trigger), so there is no other gate in
        front of it: a malformed continuation merges green and breaks the
        image afterwards. Caught here instead, which is the only place a PR
        can catch it.
        """
        backslash = chr(92)
        with open(DOCKERFILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
        stray = []
        for n, line in enumerate(lines, 1):
            # Drop the one trailing backslash a real continuation is allowed.
            # ANY that survives is in the middle of the line, which is the
            # shape the bug had - and note the naive check (does the line END
            # with a backslash) passes it happily, because a line carrying
            # backslash-n mid-way still ends with its own real continuation.
            body = line.rstrip()
            if body.endswith(backslash):
                body = body[:-1]
            if backslash in body:
                stray.append((n, line))
        self.assertEqual(stray, [], "backslash not at end of line: %s" % stray)

    def test_jquery_ships_from_the_context_and_not_the_shared_tarball(self):
        """It is a browser asset, not a Python module, and the shared tarball
        goes to every image built from that directory. Moving it here freed
        30KB gzipped of a 786KB budget that two finished views were blocked
        on. It stays VENDORED: map_server._jquery_file explains that the page
        reaches no third host for it, and a CDN would have saved the same
        bytes by trading that away."""
        self.assertIn("jquery.min.js", _context_files())
        self.assertNotIn("jquery.min.js", _copied_files())
        here = os.path.dirname(DOCKERFILE)
        self.assertTrue(os.path.exists(os.path.join(here, "jquery.min.js")),
                        "the Dockerfile copies it from the context but it is "
                        "not in the context")
        self.assertFalse(os.path.exists(os.path.join(HERE, "jquery.min.js")),
                         "still in the shared dir, so still in the tarball")

    def test_data_files_the_map_needs_are_copied(self):
        # transform.Geometry.load() reads these at import time in the pod;
        # shapes.json is served to the page, and its absence is invisible in
        # CI - the pod starts fine and the map just draws empty sea.
        for needed in ("zones.json", "entrances.json", "shapes.json", "index.html"):
            self.assertIn(needed, _copied_files(), needed)


if __name__ == "__main__":
    unittest.main()
