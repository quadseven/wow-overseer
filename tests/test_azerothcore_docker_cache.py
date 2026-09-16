import pathlib
import unittest


REPO = pathlib.Path(__file__).resolve().parents[4]
WORKFLOW = REPO / ".github" / "workflows" / "build.azerothcore-playerbots.yml"


class AzerothCoreDockerCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_build_uses_upstream_multistage_targets(self):
        self.assertIn("-f apps/docker/Dockerfile", self.workflow)
        self.assertEqual(self.workflow.count('--target "$target"'), 1)

    def test_cache_from_is_skipped_for_explicit_cold_build(self):
        self.assertIn('CACHE_FROM_ARG=()', self.workflow)
        self.assertIn('CACHE_FROM_ARG=(--cache-from "type=registry,ref=${CACHE_REF}")', self.workflow)
        self.assertIn('"${CACHE_FROM_ARG[@]}"', self.workflow)

    def test_context_excludes_only_non_build_inputs(self):
        self.assertIn("Prepare a minimal Docker build context", self.workflow)
        self.assertIn("**/.git", self.workflow)
        self.assertIn("docs", self.workflow)
        self.assertIn("tests", self.workflow)
        self.assertIn("source, SQL, scripts, or runtime data", self.workflow)


if __name__ == "__main__":
    unittest.main()
