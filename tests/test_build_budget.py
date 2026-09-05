"""The image build's delivery budget, checked here rather than found on main.

The wow-overseer image is built in the cluster, and its source reaches the
build Job as Kubernetes ConfigMaps: the top-level files of this directory,
packed into gzipped tarballs by _reusable.build-to-cluster-registry.yml.
A ConfigMap holds at most 1 MiB, the apiserver refuses anything larger,
and that refusal lands in the build workflow - which runs only on main,
AFTER the merge that broke it. This suite runs on the pull request.

TWO TARBALLS, TWO BUDGETS. The frozen client tables (every *.json here:
icons, items, spells, standing, talents, shapes, zones, entrances) are 250KB
gzipped and change roughly never; the source is 550KB and changes every
week. When both shared one ConfigMap (infra#3273) the source's headroom was
whatever the tables left it, and the last 1% of it was the choice between a
feature and its comments. build.wow-overseer.yml now passes
`shared-frozen-glob: '*.json'`, so the tables travel in a ConfigMap of their
own and the source budget is a source budget. Each side is checked against
three quarters of the cap, so the check fires while there is still room to
think rather than on the commit that has none.

THE TARBALL IS BUILT REPRODUCIBLY. A tar member records its mtime, owner and
group, and those differ per checkout; with 1.5KB of headroom the same commit
passed on CI and failed on a developer's machine (infra#3273, last comment).
Pinning them makes the number a property of the files. It is still an
approximation of GNU tar's output, a few hundred bytes either way, which the
quarter of slack absorbs.
"""
import fnmatch
import gzip
import io
import pathlib
import re
import tarfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = HERE.parent.parent.parent / ".github" / "workflows"
CONFIGMAP_CAP = 1024 * 1024
BUDGET = CONFIGMAP_CAP * 3 // 4


def frozen_glob() -> str:
    """The glob build.wow-overseer.yml hands the reusable, read rather than
    assumed, so this suite measures the split the build actually makes."""
    workflow = (WORKFLOWS / "build.wow-overseer.yml").read_text(encoding="utf-8")
    match = re.search(r"shared-frozen-glob:\s*'([^']+)'", workflow)
    return match.group(1) if match else ""


def _reproducible(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def packed(names) -> int:
    """Gzipped size of a tarball of these top-level files, built the way the
    reusable builds it: sorted names, files only, no directories."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name in sorted(names):
            tar.add(HERE / name, arcname=name, filter=_reproducible)
    return len(gzip.compress(raw.getvalue(), mtime=0))


def split() -> tuple:
    """(source names, frozen names), by the same rule as the workflow's two
    find invocations: -name GLOB and ! -name GLOB over top-level files."""
    files = sorted(p.name for p in HERE.iterdir() if p.is_file())
    glob = frozen_glob()
    frozen = [n for n in files if glob and fnmatch.fnmatchcase(n, glob)]
    return [n for n in files if n not in frozen], frozen


class TheSourceTarballFitsItsConfigMap(unittest.TestCase):
    def test_the_gzipped_source_is_inside_the_budget(self):
        source, _ = split()
        size = packed(source)
        self.assertLess(
            size, BUDGET,
            f"the source tarball is {size} bytes gzipped; the ConfigMap cap "
            f"is {CONFIGMAP_CAP} and the budget {BUDGET}. Split the shared "
            "dir before the build on main finds out; do not raise the number.")

    def test_the_gzipped_frozen_data_is_inside_its_own_budget(self):
        _, frozen = split()
        size = packed(frozen)
        self.assertLess(
            size, BUDGET,
            f"the frozen tarball is {size} bytes gzipped against {BUDGET}. "
            "Shrink a book (tools/gen_*.py) before the build on main finds out.")

    def test_the_frozen_glob_actually_moves_the_books(self):
        """A glob that matched nothing would put the whole dir back in one
        tarball and this suite would be measuring the split it wishes for."""
        source, frozen = split()
        self.assertIn("icons.json", frozen)
        self.assertIn("items.json", frozen)
        self.assertNotIn("bridge.py", frozen)
        self.assertNotIn("index.html", frozen)
        self.assertTrue(source)

    def test_the_measurement_is_a_property_of_the_files(self):
        source, _ = split()
        self.assertEqual(packed(source), packed(source))


class TheReusableActuallyShipsTwoTarballs(unittest.TestCase):
    """The budgets above are only the right budgets while the workflow packs
    the dir this way; if someone reverts to one key per file, the plain bytes
    are the number that matters and this suite is measuring the wrong one."""

    def setUp(self):
        self.workflow = (WORKFLOWS / "_reusable.build-to-cluster-registry.yml"
                         ).read_text(encoding="utf-8")

    def test_source_travels_as_one_tarball(self):
        self.assertIn("--from-file=shared.tgz=/tmp/shared.tgz", self.workflow)
        self.assertIn("tar -xzf /workspace-shared/shared.tgz -C /ctx/_shared", self.workflow)

    def test_frozen_data_travels_as_a_second_tarball_into_the_same_dir(self):
        """Same _shared/ on the far side: the Dockerfile's COPY lines do not
        know which configMap a file came from, and must not have to."""
        self.assertIn('! -name "$SHARED_FROZEN_GLOB"', self.workflow)
        self.assertIn("--from-file=frozen.tgz=/tmp/frozen.tgz", self.workflow)
        self.assertIn("tar -xzf /workspace-frozen/frozen.tgz -C /ctx/_shared", self.workflow)

    def test_the_frozen_configmap_always_exists_so_the_job_spec_stays_static(self):
        """Every other caller of the reusable leaves the glob empty. The Job
        mounts $JOB-frozen unconditionally, so a placeholder must be created
        on both the no-glob and the no-shared-dir paths."""
        self.assertEqual(self.workflow.count('kubectl create configmap "$JOB-frozen"'), 3)
        self.assertIn("configMap: {name: $JOB-frozen}", self.workflow)

    def test_wow_overseer_asks_for_the_split(self):
        self.assertEqual(frozen_glob(), "*.json")


if __name__ == "__main__":
    unittest.main()
