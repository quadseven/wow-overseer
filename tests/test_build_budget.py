"""The image build's delivery budget, checked here rather than found on main.

The wow-overseer image is built in the cluster, and its source reaches the
build Job as a Kubernetes ConfigMap: every top-level file of this directory,
packed into one gzipped tarball by _reusable.build-to-cluster-registry.yml.
A ConfigMap holds at most 1 MiB, the apiserver refuses anything larger,
and that refusal lands in the build workflow - which runs only on main,
AFTER the merge that broke it. This suite runs on the pull request.

The budget is the tarball, not the plain bytes, because that is what the
ConfigMap holds. Three quarters of the cap, so the check fires while there
is still room to think rather than on the commit that has none. When it
fires, the answers are, in order: shrink what is frozen (the three item books
are the largest things here by far), or split the shared dir - not raise the number.

Ticket: infra#3139 (the item table that made the plain-file delivery
impossible, and the tarball that replaced it).
"""
import gzip
import io
import pathlib
import tarfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
CONFIGMAP_CAP = 1024 * 1024
BUDGET = CONFIGMAP_CAP * 3 // 4


class TheSharedTarballFitsTheConfigMap(unittest.TestCase):
    def test_the_gzipped_source_is_inside_the_budget(self):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as tar:
            for path in sorted(p for p in HERE.iterdir() if p.is_file()):
                tar.add(path, arcname=path.name)
        packed = gzip.compress(raw.getvalue())
        self.assertLess(
            len(packed), BUDGET,
            f"the shared tarball is {len(packed)} bytes gzipped; the ConfigMap "
            f"cap is {CONFIGMAP_CAP} and the budget {BUDGET}. Shrink what is "
            "frozen before the build on main finds out.")

    def test_the_reusable_actually_ships_a_tarball(self):
        """The budget above is only the right budget while the workflow packs
        the dir; if someone reverts to one key per file, the plain bytes are
        the number that matters and this suite is measuring the wrong one."""
        workflow = (HERE.parent.parent.parent / ".github" / "workflows"
                    / "_reusable.build-to-cluster-registry.yml").read_text()
        self.assertIn("--from-file=shared.tgz=/tmp/shared.tgz", workflow)
        self.assertIn("tar -xzf /workspace-shared/shared.tgz -C /ctx/_shared", workflow)


if __name__ == "__main__":
    unittest.main()
