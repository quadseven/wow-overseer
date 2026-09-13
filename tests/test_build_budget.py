"""The image build's delivery budget, checked here rather than found on main.

The wow-overseer image is built in the cluster, and its source reaches the
build Job as Kubernetes ConfigMaps: the top-level files of this directory,
packed into gzipped tarballs by _reusable.build-to-cluster-registry.yml.
A ConfigMap holds at most 1 MiB, the apiserver refuses anything larger,
and that refusal lands in the build workflow - which runs only on main,
AFTER the merge that broke it. This suite runs on the pull request.

TWO TARBALLS, TWO BUDGETS. The frozen side (every *.json here - icons, items,
spells, standing, talents, shapes, zones, entrances - plus the map's
index.html) is 430KB gzipped and changes roughly never; the source is 635KB
and changes every week. When both shared one ConfigMap (infra#3273) the
source's headroom was whatever the tables left it, and the last 1% of it was
the choice between a feature and its comments. build.wow-overseer.yml now
passes `shared-frozen-glob: '*.json *.html'`, so that side travels in a
ConfigMap of its own and the source budget is a source budget. Each side is
checked against three quarters of the cap, so the check fires while there is
still room to think rather than on the commit that has none.

WHY index.html IS ON THE FROZEN SIDE (infra#3711). It is 485KB of static
browser asset that map_server hands out verbatim, and it was contributing
143KB gzipped - 18% of the source tarball - for the single reason that it did
not match '*.json'. Four merges on 2026-09-13 put the source 4679 bytes past
its budget and turned main red for every wow-overseer PR behind them. Moving
that one file bought back about 140KB, thirty times the overage. Trimming
comments to find 4679 would have bought back the comments, which is the trade
the paragraph above exists to refuse.

THE WHOLE DIR NO LONGER FITS IN ONE CONFIGMAP. Packed as a single tarball it
is 1083564 bytes gzipped against the 1048576 cap, so the split is not a
tidiness preference any more - it is load-bearing, and anything that quietly
collapses it back to one tarball is a build outage rather than a tight
squeeze. That is also why the glob names the FROZEN side and not the source:
a pattern that matches nothing leaves its files on the SOURCE side, where the
budget assertion below sees them and fails on the pull request. Naming the
source side instead would let the same typo produce an EMPTY source tarball
that every assertion in this file sails happily through - a green test asking
a question nothing answers.

TWO LINES PER SIDE, NOT ONE. Each tarball is asserted against the 3/4 budget
AND against the cap itself, because "we have spent our margin" and "the build
on main will fail" are different emergencies and the failure output should
say which one is happening. A budget failure on its own means this check did
its job early, with room left to think.

THE TARBALL IS BUILT REPRODUCIBLY, BUT ONLY UP TO A POINT. A tar member
records its mtime, owner and group, and those differ per checkout; with 1.5KB
of headroom the same commit passed on CI and failed on a developer's machine
(infra#3273, last comment). Pinning them makes the number a property of the
files rather than of the checkout.

What pinning does NOT remove, measured on one commit during infra#3711, is a
spread of roughly ELEVEN kilobytes between environments - far more than the
"few hundred bytes" this paragraph used to claim:

  791111   CRLF working tree, zlib-ng      (a Windows developer)
  786473   LF working tree, zlib-ng        (the same files, LF)
  797564   LF, stock zlib                  (what CI actually reported)

Line endings change the bytes being compressed, and zlib-ng and stock zlib
disagree about how to compress them; neither is addressed by pinning tar
metadata, and Python's gzip is only ever an approximation of the GNU tar the
build really runs. So read the number as a magnitude, not a reading: the
three above all say "over budget", which is the answer that matters, but they
disagree on the margin by more than the 4679 bytes that turned main red.

That is an argument for keeping the margin FAT rather than for chasing the
last kilobyte. The split this file measures now leaves about 140KB of slack,
twelve times the spread above, so the verdict is the same wherever it runs.
A change that trims the slack back toward the noise floor has broken the
check even while it is passing.
"""
import fnmatch
import gzip
import io
import pathlib
import re
import tarfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
DOCKERFILE = REPO / "production" / "docker" / "wow-overseer" / "Dockerfile"
CONFIGMAP_CAP = 1024 * 1024
BUDGET = CONFIGMAP_CAP * 3 // 4


def frozen_globs() -> list:
    """The patterns build.wow-overseer.yml hands the reusable, read rather
    than assumed, so this suite measures the split the build actually makes.

    Split with bare str.split(), which breaks on runs of ANY whitespace and
    drops empties - exactly what the reusable's unquoted `for pat in
    $SHARED_FROZEN_GLOB` gets from IFS word splitting. `.split(' ')` would
    disagree with the shell the moment someone aligned two patterns with a
    tab or wrote them as a YAML block (infra#3711).
    """
    workflow = (WORKFLOWS / "build.wow-overseer.yml").read_text(encoding="utf-8")
    match = re.search(r"shared-frozen-glob:\s*'([^']+)'", workflow)
    return match.group(1).split() if match else []


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


def top_level_files() -> list:
    return sorted(p.name for p in HERE.iterdir() if p.is_file())


def split() -> tuple:
    """(source names, frozen names), by the same rule as the workflow's two
    find invocations over top-level files: `\\( -name A -o -name B \\)` for
    the frozen side and its negation for the source. Matching ANY pattern
    freezes a file, which is what the -o chain means."""
    files = top_level_files()
    globs = frozen_globs()
    frozen = [n for n in files
              if any(fnmatch.fnmatchcase(n, g) for g in globs)]
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

    def test_the_gzipped_source_is_inside_the_hard_cap(self):
        """Distinct from the budget above ON PURPOSE. If only the budget
        assertion fails, the margin is spent and there is still room to
        think. If this one fails too, the apiserver is already refusing the
        configMap and the build on main is down, not merely close."""
        source, _ = split()
        size = packed(source)
        self.assertLess(
            size, CONFIGMAP_CAP,
            f"the source tarball is {size} bytes gzipped, past the "
            f"{CONFIGMAP_CAP} ConfigMap cap ITSELF - not the {BUDGET} margin, "
            "the cap. The build on main is failing now: the apiserver refuses "
            "a ConfigMap this large. Move files to the frozen side.")

    def test_the_gzipped_frozen_data_is_inside_its_own_budget(self):
        _, frozen = split()
        size = packed(frozen)
        self.assertLess(
            size, BUDGET,
            f"the frozen tarball is {size} bytes gzipped against {BUDGET}. "
            "Shrink a book (tools/gen_*.py) before the build on main finds out.")

    def test_the_gzipped_frozen_data_is_inside_the_hard_cap(self):
        _, frozen = split()
        size = packed(frozen)
        self.assertLess(
            size, CONFIGMAP_CAP,
            f"the frozen tarball is {size} bytes gzipped, past the "
            f"{CONFIGMAP_CAP} ConfigMap cap ITSELF. The build on main is "
            "failing now; shrink a book (tools/gen_*.py).")

    def test_the_frozen_glob_actually_moves_the_books_and_the_page(self):
        """A glob that matched nothing would put the whole dir back in one
        tarball and this suite would be measuring the split it wishes for.
        index.html is named here because moving it is the whole of
        infra#3711: drop '*.html' from the caller and the source goes back
        over budget, so this names the cause before the byte count has to."""
        source, frozen = split()
        self.assertIn("icons.json", frozen)
        self.assertIn("items.json", frozen)
        self.assertIn("index.html", frozen)
        self.assertNotIn("bridge.py", frozen)
        self.assertIn("bridge.py", source)
        self.assertTrue(source)

    def test_every_frozen_pattern_matches_at_least_one_file(self):
        """A pattern matching nothing is dead weight that reads as protection
        - '*.htm' instead of '*.html' still parses, still splits, and quietly
        leaves 143KB on the source side. The budget test would fail, but it
        would blame the source; this one blames the typo."""
        files = top_level_files()
        for glob in frozen_globs():
            with self.subTest(glob=glob):
                self.assertTrue(
                    [n for n in files if fnmatch.fnmatchcase(n, glob)],
                    f"frozen pattern {glob!r} in build.wow-overseer.yml "
                    "matches no top-level file in this directory")

    def test_the_two_tarballs_partition_the_directory(self):
        """The reusable's two finds are complements, so every top-level file
        ships exactly once. A file in neither never reaches the build and the
        image fails on a COPY; a file in both ships twice and is charged to
        both budgets. Neither shows up as a size failure, so assert it."""
        source, frozen = split()
        self.assertEqual(sorted(source + frozen), top_level_files())
        self.assertEqual(set(source) & set(frozen), set())

    def test_everything_the_dockerfile_copies_is_in_one_of_the_tarballs(self):
        """The two configMaps unpack into the SAME _shared/, so which tarball
        a file rides in is invisible to the Dockerfile - that is the claim
        that makes moving index.html safe, and this is the assertion that
        keeps it true. It also catches the real hazard of a split: a file
        that falls out of both finds is missing at COPY time, in a build that
        only runs on main."""
        source, frozen = split()
        shipped = set(source) | set(frozen)
        copied = set(re.findall(r"_shared/(\S+)", DOCKERFILE.read_text(encoding="utf-8")))
        self.assertTrue(copied, "no _shared/ COPY found in the Dockerfile")
        self.assertEqual(copied - shipped, set())

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
        self.assertIn(r'! \( "${FROZEN_TEST[@]}" \)', self.workflow)
        self.assertIn("--from-file=frozen.tgz=/tmp/frozen.tgz", self.workflow)
        self.assertIn("tar -xzf /workspace-frozen/frozen.tgz -C /ctx/_shared", self.workflow)

    def test_the_two_finds_are_exact_complements(self):
        """split() above models the shell, so the shell must stay the shape
        split() models: ONE negated group for the source and ONE plain group
        for the frozen side, over the same array. Anything else - a second
        -name bolted on, a find that drops the negation - makes this suite
        measure a split the build does not make."""
        group = r'\( "${FROZEN_TEST[@]}" \)'
        self.assertEqual(self.workflow.count(group), 2)
        self.assertEqual(self.workflow.count("! " + group), 1)

    def test_the_reusable_builds_one_name_test_per_whitespace_separated_pattern(self):
        """The caller's glob is several patterns (infra#3711) and this is the
        loop that turns them into `-name A -o -name B`. `set -f` is asserted
        because it is load-bearing rather than decorative: without it the
        unquoted expansion of '*.json' is PATHNAME-EXPANDED against the
        runner's cwd, and the patterns silently become whatever files happen
        to sit in the repo root."""
        self.assertIn("for pat in $SHARED_FROZEN_GLOB; do", self.workflow)
        self.assertIn("FROZEN_TEST+=( -name \"$pat\" )", self.workflow)
        self.assertIn("FROZEN_TEST+=( -o )", self.workflow)
        self.assertIn("set -f", self.workflow)
        self.assertIn("set +f", self.workflow)

    def test_the_frozen_configmap_always_exists_so_the_job_spec_stays_static(self):
        """Every other caller of the reusable leaves the glob empty. The Job
        mounts $JOB-frozen unconditionally, so a placeholder must be created
        on both the no-glob and the no-shared-dir paths."""
        self.assertEqual(self.workflow.count('kubectl create configmap "$JOB-frozen"'), 3)
        self.assertIn("configMap: {name: $JOB-frozen}", self.workflow)

    def test_wow_overseer_asks_for_the_split(self):
        self.assertEqual(frozen_globs(), ["*.json", "*.html"])


if __name__ == "__main__":
    unittest.main()
