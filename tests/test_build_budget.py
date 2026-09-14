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

STABLE MODULES RIDE THE FROZEN SIDE TOO (infra#3823). By 2026-09-14 the
source side was 794KB gzipped against the 786KB budget, every byte of it
.py except AGENTS.md's 1.5KB, so there was no second index.html to move.
The caller now also names every module that had gone a week without an
edit, except bridge.py and map_server.py, which change daily; that left
the source 207KB under its budget and the frozen side 135KB under.
"Frozen" means "rarely changing" from here on. A listed module that heats
up only charges the frozen side, whose own budget below still guards it,
and a listed name that no longer exists fails
test_every_name_the_glob_lists_exists, because a glob naming a vanished
file moves nothing and says nothing.

MEASURE THE ARTIFACT, NOT THE CHECKOUT (infra#3812). Its neighbour above
refuses to shrink the thing being measured; this one is about measuring the
right thing at all. packed() reads each file's bytes and replaces CRLF with
LF before handing them to the tar, because .gitattributes is `* text=auto`:
the repository stores LF, the Linux runner checks out LF, and the LF tarball
is therefore the one the build actually ships. A Windows working tree is CRLF
and weighs about 4.8KB more for the same commit - 785237 against 780477 on
the tree that filed the issue. Without the normalisation this file was
reading the developer's git config and calling it the artifact.

The error is always pessimistic, which is why it hid for most of this file's
life: while the margin was 30KB, being 4.8KB over-cautious cost nothing.
It stopped hiding when infra#3802 took the margin to 1195 bytes, which is
smaller than the spread. Measured on a real branch that night - PR #3808
rebased onto PR #3801's head - the same commit read 786454 on CRLF and FAILED
("786454 not less than 786432") while reading 781624 on LF and passing with
4808 bytes spare. A guard that answers differently on different machines
stops being read, which is worse than the thing it guards.

Note what this is NOT, because it looks like the trade the paragraph above
refuses and is its opposite: not one byte of budget, cap or margin moved, and
nothing was bought back that anyone can now spend. The numbers below are the
same numbers they were. The only thing that changed is which bytes get
weighed - and if a future change here ever needs the budget to go up or a
comment to come out, that is the signal to split the dir, not to edit this
paragraph.

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

ONE OF THOSE THREE READINGS IS GONE (infra#3812). The three numbers above are
kept as the record of how wide this can get, but the first two of them no
longer differ: normalising line endings in packed() collapses the 791111/786473
pair into a single reading, because that gap was the reader's checkout and
nothing else. What survives is the compressor - zlib-ng against stock zlib,
and Python's gzip against the GNU tar the build really runs - so the argument
for a fat margin is unchanged and so is the rule about reading the number as a
magnitude. The difference is that the remaining spread is a property of the
machine's libraries, which a test cannot normalise away, rather than of a
config setting, which it can.
"""
import fnmatch
import gzip
import io
import pathlib
import re
import shutil
import tarfile
import tempfile
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


def packed(names, root: pathlib.Path = HERE) -> int:
    """Gzipped size of a tarball of these top-level files, built the way the
    reusable builds it: sorted names, files only, no directories.

    CRLF becomes LF on read, so the number is a property of the committed
    bytes rather than of the reader's git config - see MEASURE THE ARTIFACT,
    NOT THE CHECKOUT above. That is why each member is read and added by hand
    instead of with tar.add(): tar.add() copies the working tree's bytes, and
    on Windows those are the wrong bytes.

    A member holding a NUL in its first 8000 bytes is left exactly as it sits,
    which is the same test git's own buffer_is_binary() applies and therefore
    the same set of files `text=auto` declines to normalise. Nothing at this
    level is binary today, so the skip changes no number below; it is here
    because of the DIRECTION its absence would err in. Every other
    approximation in this file is pessimistic - the CRLF reading was too
    heavy, so the guard cried wolf and nothing shipped over budget because of
    it. Normalising a binary is the opposite: it can only make the measurement
    SMALLER than the artifact, so the assertion could pass while the real
    tarball is over the cap and the build on main is what finds out. A guard
    that fails optimistically is worse than no guard, because it is trusted.
    A font, an icon sprite or a PNG landing in this directory is an ordinary
    afternoon, and without this line nothing would say the measurement had
    quietly become wrong.

    `root` exists so the CRLF/LF equality test below can pack a fixture it
    controls; everything that measures the real build leaves it alone.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name in sorted(names):
            path = root / name
            payload = path.read_bytes()
            if b"\x00" not in payload[:8000]:
                payload = payload.replace(b"\r\n", b"\n")
            info = _reproducible(tar.gettarinfo(str(path), arcname=name))
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
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
            "Shrink a book (tools/gen_*.py) or move a module back to the source "
            "side before the build on main finds out.")

    def test_the_gzipped_frozen_data_is_inside_the_hard_cap(self):
        _, frozen = split()
        size = packed(frozen)
        self.assertLess(
            size, CONFIGMAP_CAP,
            f"the frozen tarball is {size} bytes gzipped, past the "
            f"{CONFIGMAP_CAP} ConfigMap cap ITSELF. The build on main is "
            "failing now; shrink a book (tools/gen_*.py) or move a module back "
            "to the source side.")

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

    def test_stable_modules_move_and_the_hot_ones_stay(self):
        """infra#3823: the caller names rarely edited modules on the frozen
        side. bridge.py and map_server.py change daily and must stay on the
        source side, or the frozen side becomes the one that fills up."""
        source, frozen = split()
        self.assertIn("core.py", frozen)
        self.assertIn("bridge.py", source)
        self.assertIn("map_server.py", source)

    def test_every_name_the_glob_lists_exists(self):
        """A literal name that no longer exists (a renamed or deleted
        module) matches nothing and moves nothing, silently. Wildcard
        patterns are exempt: a '*.json' that matched nothing is caught by
        the test above."""
        present = set(top_level_files())
        missing = [g for g in frozen_globs()
                   if not any(c in g for c in "*?[") and g not in present]
        self.assertEqual(missing, [], f"shared-frozen-glob names files "
                         f"that do not exist: {missing}")

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


class TheMeasurementIsOfTheArtifactNotTheCheckout(unittest.TestCase):
    """infra#3812, pinned here because the bug WAS the measurement varying.

    The assertions above weigh the working tree, and a Windows working tree is
    CRLF while the repository and the Linux runner are LF - about 4.8KB of
    difference on this package for the same commit. That was invisible against
    a 30KB margin and decisive against the 1195 bytes infra#3802 left, so the
    budget assertion started passing on CI and failing on a developer's machine
    for one commit. These tests pack the same text twice, once in each line
    ending, and demand a single answer.
    """

    # Long enough that the two forms cannot gzip to the same size by luck: the
    # CRLF copy carries one extra byte per line and the bodies are varied
    # rather than repetitive, so the difference survives compression. A fixture
    # too small to expose the bug would make the equality below hold for the
    # wrong reason, which is what the second test is for.
    LINES = 400

    def _fixture(self, newline: bytes) -> pathlib.Path:
        """A throwaway directory holding the same two files in one line ending.

        Two files, not one, because the real measurement is a tarball of many
        members and the per-member size field is part of what packed() has to
        get right when it stops using tar.add().
        """
        root = pathlib.Path(tempfile.mkdtemp(prefix="budget-fixture-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        code = [f"def step_{i}(n):  # a comment, because comments are the point"
                for i in range(self.LINES)]
        data = [f'  {{"zone": {i}, "name": "a name for zone {i}"}},'
                for i in range(self.LINES)]
        for name, lines in (("sample.py", code), ("sample.json", data)):
            # The trailing "" gives the file a final line ending, so the count
            # of separators matches the count of lines on both forms.
            body = newline.join(line.encode("utf-8") for line in [*lines, ""])
            (root / name).write_bytes(body)
        return root

    def _binary_fixture(self) -> pathlib.Path:
        """A directory holding one file git would call binary: a NUL inside
        the first 8000 bytes, then varied CRLF-terminated records.

        Varied rather than one repeated record because the assertion is about
        gzipped size, and a highly compressible blob can weigh the same with
        and without its CR bytes - which would let the test pass whether or
        not packed() skipped it.
        """
        root = pathlib.Path(tempfile.mkdtemp(prefix="budget-binary-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        header = b"\x89SPRITE\x00\x1a\n"
        records = b"".join(f"tile {i} at offset {i * 37}\r\n".encode("utf-8")
                           for i in range(self.LINES))
        (root / "sprite.bin").write_bytes(header + records)
        return root

    def test_the_same_files_weigh_the_same_in_crlf_and_in_lf(self):
        """The whole of infra#3812 in one assertion. If this fails, packed()
        is measuring the reader's checkout again and the budget assertions
        above answer a different question on Windows than they do on CI."""
        names = ["sample.json", "sample.py"]
        crlf = packed(names, self._fixture(b"\r\n"))
        lf = packed(names, self._fixture(b"\n"))
        self.assertEqual(
            crlf, lf,
            f"the same files measured {crlf} bytes as CRLF and {lf} as LF. "
            "packed() is weighing the working tree instead of the artifact; "
            "the build ships LF, so LF is the honest number. Do not close the "
            "gap by raising the budget.")

    def test_the_crlf_and_lf_fixtures_really_are_different_bytes(self):
        """Guard the guard. If _fixture ignored its argument, the equality
        above would pass while proving nothing - the green test asking a
        question nothing answers that this file's docstring warns about.

        Asserted on line-ending counts and lengths rather than on the blobs
        themselves: assertNotEqual on two 25KB bodies prints both of them, and
        a 50KB diff is not a diagnosis. The length gap is one byte per line, so
        'different' cannot come down to a stray character somewhere.
        """
        crlf_root, lf_root = self._fixture(b"\r\n"), self._fixture(b"\n")
        for name in ("sample.py", "sample.json"):
            with self.subTest(name=name):
                crlf = (crlf_root / name).read_bytes()
                lf = (lf_root / name).read_bytes()
                self.assertEqual(crlf.count(b"\r\n"), self.LINES,
                                 f"the CRLF {name} fixture has no CRLF in it")
                self.assertEqual(lf.count(b"\r"), 0,
                                 f"the LF {name} fixture has a CR in it")
                self.assertEqual(len(crlf) - len(lf), self.LINES,
                                 f"{name} should be exactly one byte per line "
                                 "heavier as CRLF than as LF")

    def _verbatim(self, names, root: pathlib.Path) -> int:
        """What packed() would return if it normalised nothing at all: the
        same tarball, built from the bytes exactly as they sit on disk. Equal
        to packed() precisely when packed() left every member alone."""
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as tar:
            for name in sorted(names):
                tar.add(root / name, arcname=name, filter=_reproducible)
        return len(gzip.compress(raw.getvalue(), mtime=0))

    def test_normalising_does_not_change_what_an_lf_checkout_already_read(self):
        """The fix must be a no-op on the runner, which is where the number
        that matters comes from. An LF fixture packed by packed() has to equal
        a byte-for-byte tar of the same files, or the normalisation is doing
        something to the artifact rather than to the reading of it."""
        root = self._fixture(b"\n")
        names = ["sample.json", "sample.py"]
        self.assertEqual(packed(names, root), self._verbatim(names, root))

    def test_a_binary_member_is_weighed_exactly_as_it_sits(self):
        """The one case where normalising would err OPTIMISTICALLY, so it is
        the one case worth a test even though no top-level file is binary
        today. A blanket replace over a sprite or a font would report fewer
        bytes than the tarball really carries, and an under-reading assertion
        passes while the apiserver refuses the ConfigMap. git's `text=auto`
        leaves these files alone and so must this, or the two disagree about
        what the artifact is.

        The fixture carries CRLF pairs AFTER its NUL on purpose: without the
        skip there is something for the replace to find, so this fails rather
        than passing vacuously.
        """
        root = self._binary_fixture()
        names = ["sprite.bin"]
        self.assertEqual(
            packed(names, root), self._verbatim(names, root),
            "packed() rewrote a member that git's text=auto would have left "
            "alone. That under-reports the artifact, which is the one "
            "direction this guard must never be wrong in.")

    def test_the_binary_fixture_is_one_git_would_call_binary(self):
        """Guard this guard too. If the fixture had no NUL in git's window it
        would be a text file, packed() would rightly normalise it, and the
        test above would be asserting the opposite of what it claims."""
        blob = (self._binary_fixture() / "sprite.bin").read_bytes()
        # assertTrue, not assertIn: assertIn on a 12KB blob prints the blob,
        # and the answer here is one bit either way.
        self.assertTrue(b"\x00" in blob[:8000],
                        "the binary fixture has no NUL in git's 8000-byte "
                        "window, so git would treat it as text")
        self.assertTrue(b"\r\n" in blob,
                        "the binary fixture has no CRLF, so the test above "
                        "would hold for want of anything to normalise")


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
        globs = frozen_globs()
        self.assertEqual(globs[:2], ["*.json", "*.html"])
        # infra#3823: after the data patterns come literal names of rarely
        # edited modules, and never the two that change daily.
        self.assertTrue(all(g.endswith(".py") for g in globs[2:]), globs[2:])
        self.assertNotIn("bridge.py", globs)
        self.assertNotIn("map_server.py", globs)


if __name__ == "__main__":
    unittest.main()
