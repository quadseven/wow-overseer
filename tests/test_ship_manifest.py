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
    # The COPY spans continuation lines; take everything up to the target dir.
    match = re.search(r"^COPY\s(.*?)\s/app/", text, re.MULTILINE | re.DOTALL)
    assert match, "no COPY ... /app/ block found in the Dockerfile"
    return set(re.findall(r"_shared/(\S+)", match.group(1)))


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

    def test_data_files_the_map_needs_are_copied(self):
        # transform.Geometry.load() reads these at import time in the pod.
        for needed in ("zones.json", "entrances.json", "index.html"):
            self.assertIn(needed, _copied_files(), needed)


if __name__ == "__main__":
    unittest.main()
