"""Every module that ships must be in the image.

The Dockerfile names top-level modules explicitly (no wildcard COPY), so a
new module is one forgotten line away from an image that imports something
it does not contain - a crash at pod start, long after CI went green.

This is not hypothetical: merging three concurrent feature branches on
2026-08-21, a git rerere replay resolved the Dockerfile conflict by keeping
two of the three new modules and silently dropping panel.py, which
map_server.py imports. Caught by hand; this test is so the next one is not.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE = os.path.join(HERE, "Dockerfile")


def _copied_files() -> set:
    with open(DOCKERFILE, encoding="utf-8") as f:
        text = f.read()
    # EVERY `COPY ... /app/` block, not the first one. The Dockerfile carries
    # a second, single-file COPY for jquery.min.js alongside the big
    # multi-file block, and a non-greedy search for the first block alone
    # would miss it.
    blocks = re.findall(r"^COPY\s(.*?)\s/app/", text, re.MULTILINE | re.DOTALL)
    assert blocks, "no COPY ... /app/ block found in the Dockerfile"
    names = set()
    for b in blocks:
        for tok in b.split():
            tok = tok.strip()
            if not tok or tok == "\\":
                continue
            names.add(tok)
    return names


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
        would take the backslash-n as part of a path and fail the build.
        Caught here instead, which is the only place a PR can catch it.
        """
        backslash = chr(92)
        with open(DOCKERFILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
        stray = []
        for n, line in enumerate(lines, 1):
            body = line.rstrip()
            if body.endswith(backslash):
                body = body[:-1]
            if backslash in body:
                stray.append((n, line))
        self.assertEqual(stray, [], "backslash not at end of line: %s" % stray)

    def test_jquery_ships_from_the_build_context(self):
        """It is a browser asset, not a Python module, but it is still one
        `docker build .` context now - not a separate shared tarball, which
        no longer exists in this repo's build. It stays VENDORED:
        map_server._jquery_file explains that the page reaches no third host
        for it, and a CDN would have saved the same bytes by trading that
        away."""
        self.assertIn("jquery.min.js", _copied_files())
        self.assertTrue(
            os.path.exists(os.path.join(HERE, "jquery.min.js")),
            "the Dockerfile copies jquery.min.js but it is not in the repo",
        )

    def test_data_files_the_map_needs_are_copied(self):
        # transform.Geometry.load() reads these at import time in the pod;
        # shapes.json is served to the page, and its absence is invisible in
        # CI - the pod starts fine and the map just draws empty sea.
        for needed in ("zones.json", "entrances.json", "shapes.json", "index.html"):
            self.assertIn(needed, _copied_files(), needed)


if __name__ == "__main__":
    unittest.main()
