"""The AzerothCore workflow must expose ccache results, not just use them."""

import pathlib
import re
import unittest


REPO = pathlib.Path(__file__).resolve().parents[4]
WORKFLOW = REPO / ".github" / "workflows" / "build.azerothcore-playerbots.yml"
README = REPO / "production" / "docker" / "azerothcore-playerbots" / "README.md"


class AzerothCoreBuildCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")

    def test_workflow_uses_upstream_ccache_mount_and_sized_cache(self):
        self.assertIn("--mount=type=cache,target=/ccache,sharing=locked", self.workflow)
        self.assertIn("--build-arg CCACHE_MAXSIZE=10G", self.workflow)

    def test_workflow_extracts_hits_and_publishes_a_rate(self):
        self.assertIn("^ *hits:", self.workflow)
        self.assertRegex(self.workflow, r"sed -nE[\s\S]*Hits:.*%")
        self.assertIn("ccache hit rate", self.workflow)
        self.assertIn("ccache hit rate |", self.workflow)

    def test_first_cold_build_is_not_mistaken_for_a_regression(self):
        self.assertRegex(self.workflow, r"first build is\s+.*expected to be cold")
        self.assertIn("should normally exceed 50%", self.workflow)
        self.assertIn("above 50 percent", self.readme)

    def test_readme_documents_the_two_run_measurement(self):
        self.assertIn("run `.github/workflows/build.azerothcore-playerbots.yml` twice", self.readme)
        self.assertIn("no_cache", self.readme)


if __name__ == "__main__":
    unittest.main()
