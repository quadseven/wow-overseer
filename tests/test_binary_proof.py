"""The registry stream route proves a binary with no pod (#2273).

docs/ROLLS.md section 1b proves the worldserver binary before its digest is
pinned. The pod route needs write access to the cluster; the second route
streams the image's layers from the registry and searches the binary as it
arrives (.github/scripts/binary_proof.py). These tests drive the scanner and
the layer reader on chunked streams and a fake registry, so they need no
network, and keep the doc naming both routes.
"""

import gzip
import importlib.util
import io
import json
import pathlib
import tarfile
import unittest
import urllib.request

TESTS = pathlib.Path(__file__).resolve().parent
REPO = TESTS.parent
SCRIPT = REPO / ".github" / "scripts" / "binary_proof.py"
ROLLS = REPO / "docs" / "ROLLS.md"


def load():
    spec = importlib.util.spec_from_file_location("binary_proof", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bp = load()


def chunked(data, size):
    return [data[i : i + size] for i in range(0, len(data), size)]


def whole_count(data, needle):
    return sum(1 for i in range(len(data)) if data.startswith(needle, i))


class TheScanner(unittest.TestCase):
    def test_a_needle_that_straddles_a_chunk_boundary_is_found(self):
        needle = b"GUILD FINDER RUN"
        data = b"\x00" * 10 + needle + b"\x00" * 10
        # The boundary falls inside the needle: neither chunk holds it whole.
        chunks = [data[:17], data[17:]]
        self.assertNotIn(needle, chunks[0])
        self.assertNotIn(needle, chunks[1])
        self.assertEqual({needle: 1}, bp.scan(chunks, [needle]))

    def test_every_chunk_size_counts_what_the_whole_buffer_holds(self):
        data = b"xxabcabcxx-abc-aaaa-abcab" + b"cabc" + b"\x00abc"
        needles = [b"abc", b"aa", b"abcabc", b"x", b"never"]
        want = {n: whole_count(data, n) for n in needles}
        # Overlapping matches each count: "aaaa" holds "aa" three times.
        self.assertEqual((3, 3, 0), (want[b"aa"], want[b"abcabc"], want[b"never"]))
        for size in range(1, len(data) + 2):
            with self.subTest(size=size):
                self.assertEqual(want, bp.scan(chunked(data, size), needles))

    def test_a_match_inside_the_kept_tail_is_not_counted_twice(self):
        # "ab" ends chunk one; the tail kept for "ab" is one byte, so the
        # match already counted cannot be seen again in front of chunk two.
        self.assertEqual({b"ab": 2}, bp.scan([b"xab", b"ab"], [b"ab"]))
        self.assertEqual({b"a": 3}, bp.scan([b"a", b"", b"aa"], [b"a"]))

    def test_an_empty_needle_is_refused(self):
        with self.assertRaises(ValueError):
            bp.scan([b"abc"], [b""])

    def test_a_missing_required_needle_is_named(self):
        counts = bp.scan([b"has one"], [b"one", b"two", b"three"])
        self.assertEqual([b"two"], bp.missing(counts, [b"one", b"two"]))
        lines = bp.report(counts, [b"one", b"two"])
        self.assertEqual(3, len(lines))
        self.assertIn("required  two", lines[1])
        self.assertIn("optional  three", lines[2])


class SlowStream(io.RawIOBase):
    """A stream that never hands back more than `step` bytes a read."""

    def __init__(self, data, step):
        self.data, self.step, self.at = data, step, 0

    def readable(self):
        return True

    def read(self, n=-1):
        take = self.step if n is None or n < 0 else min(n, self.step)
        out = self.data[self.at : self.at + take]
        self.at += len(out)
        return out


def layer(files, compress=True):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue()) if compress else raw.getvalue()


BINARY = b"\x7fELF" + b"\x00" * 300 + b"new log text" + b"\x01" * 300 + b"NewSymbol"


class TheLayerReader(unittest.TestCase):
    def test_the_binary_is_read_out_of_a_gzip_layer_in_small_reads(self):
        blob = layer({"etc/other": b"new log text", bp.BINARY: BINARY})
        chunks = bp.binary_chunks(SlowStream(blob, 7), bp.BINARY, size=5)
        counts = bp.scan(chunks, [b"new log text", b"NewSymbol"])
        self.assertEqual({b"new log text": 1, b"NewSymbol": 1}, counts)

    def test_a_plain_tar_layer_and_a_dotted_path_are_read(self):
        blob = layer({"./" + bp.BINARY: BINARY}, compress=False)
        chunks = bp.binary_chunks(io.BytesIO(blob), "/" + bp.BINARY)
        self.assertEqual(BINARY, b"".join(chunks))

    def test_a_layer_without_the_binary_answers_none(self):
        blob = layer({"etc/other": b"new log text"})
        self.assertIsNone(bp.binary_chunks(io.BytesIO(blob), bp.BINARY))


GZIP = "application/vnd.oci.image.layer.v1.tar+gzip"


class FakeRegistry:
    def __init__(self, layers, kinds=None):
        self.blobs = {"sha256:%064d" % i: blob for i, blob in enumerate(layers)}
        self.kinds = kinds or [GZIP] * len(layers)
        self.read = []

    def manifest(self, reference, platform=None):
        return {
            "layers": [
                {"digest": d, "mediaType": k}
                for d, k in zip(self.blobs, self.kinds, strict=True)
            ]
        }

    def layer(self, digest):
        self.read.append(digest)
        return io.BytesIO(self.blobs[digest])


class TheProof(unittest.TestCase):
    def run_main(self, registry, *argv):
        out = io.StringIO()
        code = bp.main(
            ["ghcr.io/example/world@sha256:" + "a" * 64, *argv],
            registry_of=lambda host, repo: registry,
            out=out,
        )
        return code, out.getvalue()

    def test_the_newest_layer_holding_the_binary_is_the_one_read(self):
        old = layer({bp.BINARY: b"old build"})
        new = layer({bp.BINARY: BINARY})
        top = layer({"etc/conf": b"NewSymbol NewSymbol"})
        registry = FakeRegistry([old, new, top])
        counts = bp.prove(registry, "ref", bp.BINARY, [b"NewSymbol", b"old build"])
        self.assertEqual({b"NewSymbol": 1, b"old build": 0}, counts)
        self.assertEqual(2, len(registry.read))  # the oldest layer is not pulled

    def test_every_required_needle_found_exits_zero_with_the_body_line(self):
        code, out = self.run_main(
            FakeRegistry([layer({bp.BINARY: BINARY})]),
            "--needle",
            "new log text",
            "--optional",
            "absent text",
        )
        self.assertEqual(bp.OK, code)
        self.assertIn("     1  required  new log text", out)
        self.assertIn("     0  optional  absent text", out)
        self.assertEqual(
            "Binary proof: registry stream; found: new log text (1)",
            out.strip().splitlines()[-1],
        )

    def test_a_required_needle_with_no_hit_exits_nonzero(self):
        code, out = self.run_main(
            FakeRegistry([layer({bp.BINARY: BINARY})]),
            "--needle",
            "new log text",
            "--needle",
            "text of a stale layer",
        )
        self.assertEqual(bp.MISSING, code)
        self.assertNotEqual(0, code)
        self.assertIn("     0  required  text of a stale layer", out)
        self.assertIn("do not pin", out)
        self.assertNotIn("Binary proof:", out)

    def test_an_image_without_the_binary_is_no_verdict(self):
        code, out = self.run_main(
            FakeRegistry([layer({"etc/conf": b"x"})]), "--needle", "x"
        )
        self.assertEqual(bp.UNREADABLE, code)
        self.assertIn("no layer of the image holds", out)

    def test_the_docker_and_oci_gzip_layer_types_are_both_read(self):
        for kind in (
            "application/vnd.oci.image.layer.v1.tar+gzip",
            "application/vnd.docker.image.rootfs.diff.tar.gzip",
        ):
            with self.subTest(kind=kind):
                self.assertEqual("tar+gzip", bp.layer_kind(kind))
                registry = FakeRegistry([layer({bp.BINARY: BINARY})], kinds=[kind])
                code, _ = self.run_main(registry, "--needle", "NewSymbol")
                self.assertEqual(bp.OK, code)
        self.assertEqual("tar", bp.layer_kind("application/vnd.oci.image.layer.v1.tar"))
        for other in ("application/vnd.oci.image.layer.v1.tar+zstd", "gzip", ""):
            self.assertEqual("", bp.layer_kind(other))

    def test_a_layer_encoding_it_cannot_read_is_no_verdict(self):
        registry = FakeRegistry(
            [layer({bp.BINARY: BINARY})],
            kinds=["application/vnd.oci.image.layer.v1.tar+zstd"],
        )
        code, out = self.run_main(registry, "--needle", "NewSymbol")
        self.assertEqual(bp.UNREADABLE, code)
        self.assertIn("does not read", out)


class TheReference(unittest.TestCase):
    def test_a_digest_a_tag_and_a_bare_name_are_read(self):
        digest = "sha256:" + "b" * 64
        self.assertEqual(
            ("ghcr.io", "example/world", digest),
            bp.parse_ref("ghcr.io/example/world@" + digest),
        )
        self.assertEqual(
            ("ghcr.io", "example/world", "v1"), bp.parse_ref("ghcr.io/example/world:v1")
        )
        self.assertEqual(
            ("localhost:5000", "world", "latest"), bp.parse_ref("localhost:5000/world")
        )

    def test_a_bad_reference_is_refused(self):
        for bad in ("", "world", "ghcr.io/example/world@sha256:short", "a b/c"):
            with self.subTest(bad=bad), self.assertRaises(bp.ProofError):
                bp.parse_ref(bad)

    def test_the_platform_manifest_is_picked_from_an_index(self):
        index = {
            "manifests": [
                {
                    "digest": "sha256:arm",
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
                {
                    "digest": "sha256:amd",
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
            ]
        }
        self.assertEqual("sha256:amd", bp.pick_platform(index))
        with self.assertRaises(bp.ProofError):
            bp.pick_platform(index, "linux/s390x")


class FakeAnswer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class TheRegistryClient(unittest.TestCase):
    def test_an_index_is_followed_to_the_platform_manifest_with_one_token(self):
        asked = []
        index = {
            "manifests": [
                {
                    "digest": "sha256:amd",
                    "platform": {"os": "linux", "architecture": "amd64"},
                }
            ]
        }
        answers = {
            "https://ghcr.io/token?scope=repository:example/world:pull": {"token": "t"},
            "https://ghcr.io/v2/example/world/manifests/v1": index,
            "https://ghcr.io/v2/example/world/manifests/sha256:amd": {
                "layers": [{"digest": "sha256:l", "mediaType": GZIP}]
            },
        }

        def opener(request, timeout=None):
            asked.append((request.full_url, request.get_header("Authorization")))
            return FakeAnswer(json.dumps(answers[request.full_url]).encode())

        registry = bp.Registry("ghcr.io", "example/world", opener)
        found = registry.manifest("v1")
        self.assertEqual("sha256:l", found["layers"][0]["digest"])
        self.assertEqual([None, "Bearer t", "Bearer t"], [a[1] for a in asked])

    def test_a_url_that_is_not_https_is_never_opened(self):
        opened = []
        registry = bp.Registry("ghcr.io", "example/world", opened.append)
        for url in ("file:///etc/hostname", "http://ghcr.io/v2/"):
            with self.subTest(url=url), self.assertRaises(bp.ProofError):
                # The refusal is the thing under test; nothing is opened.
                request = urllib.request.Request(url)  # noqa: S310
                registry.open(request, timeout=1)
        self.assertEqual([], opened)


class TheDoc(unittest.TestCase):
    def setUp(self):
        text = ROLLS.read_text(encoding="utf-8")
        self.step = text.split("### 1b.", 1)[1].split("### 1c.", 1)[0]

    def test_section_1b_names_both_routes_and_when_to_use_the_second(self):
        for kept in (
            "Pod route",
            "Registry stream route",
            "python3 .github/scripts/binary_proof.py",
            "no write access to the cluster",
            "--needle",
        ):
            with self.subTest(kept=kept):
                self.assertIn(kept, self.step)

    def test_section_1b_says_what_proves_a_commit_with_no_string(self):
        for kept in (
            "adds no string or symbol",
            "clone line",
            "never the build log alone",
        ):
            with self.subTest(kept=kept):
                self.assertIn(kept, self.step)

    def test_the_roll_body_line_names_the_route(self):
        self.assertIn(
            "Binary proof: <pod | registry stream | build log only>", self.step
        )
        self.assertTrue(
            bp.body_line({b"x": 1}).startswith("Binary proof: registry stream")
        )

    def test_the_script_parses_on_the_ci_interpreter_floor(self):
        compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec")


if __name__ == "__main__":
    unittest.main()
