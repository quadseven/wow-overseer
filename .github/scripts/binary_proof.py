#!/usr/bin/env python3
"""Prove a built binary carries a change, reading only the registry (#2273).

docs/ROLLS.md section 1b proves the worldserver binary before its digest is
pinned. The pod route starts a throwaway pod on the new image, which a session
that may only read the cluster cannot do. This is the second route: the image
is public, so its layers can be streamed from the registry with an anonymous
pull token, the binary read out of the stream and searched for each needle (a
log text, query text or symbol unique to a carried change). Nothing is written
to disk and no cluster is touched.

    python3 .github/scripts/binary_proof.py IMAGE@sha256:DIGEST \\
        --needle 'new log text' --needle NewSymbolName --optional 'maybe text'

It prints the hit count per needle and exits 1 when a `--needle` has no hit
(2 when the image could not be read: no verdict). An `--optional` needle is
counted and printed but never fails the run. On success the last line is the
`Binary proof:` line the roll body carries.

THE LIMIT. A change that adds only data rows or a constant leaves no string
or symbol in the binary, so no needle exists for it. ROLLS.md says what
counts as proof for such a commit.

The layers are read newest first and the first one holding the binary is the
one a container would see. Only gzip and plain tar layers are read; any other
layer encoding is reported and the run fails rather than guessing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import urllib.error
import urllib.request
from typing import Callable, Iterable, Iterator

BINARY = "azerothcore/env/dist/bin/worldserver"
PLATFORM = "linux/amd64"
CHUNK = 1 << 20

INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
# How a layer's media type ends, and the encoding that names. OCI writes
# `...layer.v1.tar+gzip`, Docker writes `...rootfs.diff.tar.gzip`; both are a
# gzip tar. Longest ending first, so `.tar` does not answer for a longer one.
LAYER_ENDINGS = (
    (".tar+gzip", "tar+gzip"),
    (".tar.gzip", "tar+gzip"),
    (".tar", "tar"),
)
READABLE_LAYERS = ("tar", "tar+gzip")

OK, MISSING, UNREADABLE = 0, 1, 2


class ProofError(Exception):
    """The registry or the image could not be read; no verdict."""


# --- the scanner (pure) ---------------------------------------------------


def scan(chunks: Iterable[bytes], needles: Iterable[bytes]) -> dict:
    """How many times each needle starts in the stream, counted exactly.

    A stream arrives in chunks and a needle can straddle a boundary. For each
    needle the last len(needle) - 1 bytes are kept and searched again in front
    of the next chunk. That tail is one byte too short to hold a whole needle,
    so a match is never counted twice, and every start position is seen whole
    exactly once. Overlapping matches each count.
    """
    wanted = list(dict.fromkeys(needles))
    for needle in wanted:
        if not needle:
            raise ValueError("an empty needle matches everywhere")
    counts = {needle: 0 for needle in wanted}
    tails = {needle: b"" for needle in wanted}
    for chunk in chunks:
        if not chunk:
            continue
        for needle in wanted:
            window = tails[needle] + chunk
            at = window.find(needle)
            while at != -1:
                counts[needle] += 1
                at = window.find(needle, at + 1)
            keep = len(needle) - 1
            tails[needle] = window[-keep:] if keep else b""
    return counts


def missing(counts: dict, required: Iterable[bytes]) -> list:
    """The required needles with no hit, in the order given."""
    return [n for n in dict.fromkeys(required) if not counts.get(n)]


def report(counts: dict, required: Iterable[bytes]) -> list:
    """One line per needle: its hit count, and whether a miss fails."""
    must = set(required)
    lines = []
    for needle, count in counts.items():
        kind = "required" if needle in must else "optional"
        lines.append(
            "%6d  %s  %s" % (count, kind, needle.decode("utf-8", "backslashreplace"))
        )
    return lines


def body_line(counts: dict) -> str:
    """The roll body's proof line (docs/ROLLS.md section 1b, step 5)."""
    found = ", ".join(
        "%s (%d)" % (needle.decode("utf-8", "backslashreplace"), count)
        for needle, count in counts.items()
        if count
    )
    return "Binary proof: registry stream; found: %s" % (found or "nothing")


# --- the image reference (pure) -------------------------------------------

_REF = re.compile(
    r"^(?P<host>[A-Za-z0-9.-]+(?::\d+)?)/(?P<repo>[a-z0-9._/-]+?)"
    r"(?:@(?P<digest>sha256:[0-9a-f]{64})|:(?P<tag>[A-Za-z0-9._-]+))?$"
)


def parse_ref(ref: str) -> tuple:
    """(registry host, repository, digest or tag). A digest is what a roll
    pins, so it is what a roll should prove; a bare name means `latest`."""
    found = _REF.match(ref.strip())
    if not found:
        raise ProofError("not an image reference: %r" % ref)
    return (
        found["host"],
        found["repo"],
        found["digest"] or found["tag"] or "latest",
    )


def pick_platform(index: dict, platform: str = PLATFORM) -> str:
    """The digest of the platform's manifest in a multi-platform index."""
    os_name, _, arch = platform.partition("/")
    for entry in index.get("manifests") or ():
        have = entry.get("platform") or {}
        if have.get("os") == os_name and have.get("architecture") == arch:
            return entry["digest"]
    raise ProofError("the image has no %s manifest" % platform)


def layer_kind(media_type: str) -> str:
    """`tar` or `tar+gzip` for a layer this script reads, by how its media
    type ends; any other type answers "" and is not read."""
    for ending, kind in LAYER_ENDINGS:
        if media_type.endswith(ending):
            return kind
    return ""


# --- reading a layer as a stream ------------------------------------------


def _same_path(member_name: str, path: str) -> bool:
    return member_name.lstrip("./") == path.lstrip("./")


def binary_chunks(layer, path: str, size: int = CHUNK) -> Iterator[bytes] | None:
    """The file at `path` in a layer stream, as chunks, or None when the
    layer does not hold it. `layer` is any object with read(); the tar is
    read forward only, so nothing is buffered beyond one chunk."""
    archive = tarfile.open(fileobj=layer, mode="r|*")
    for member in archive:
        if member.isfile() and _same_path(member.name, path):
            return _chunks_of(archive.extractfile(member), size)
    return None


def _chunks_of(handle, size: int) -> Iterator[bytes]:
    while True:
        chunk = handle.read(size)
        if not chunk:
            return
        yield chunk


# --- the registry ---------------------------------------------------------


class Registry:
    """Anonymous, read-only access to one repository of an OCI registry."""

    def __init__(self, host: str, repo: str, opener: Callable | None = None):
        self.host, self.repo = host, repo
        self.opener = opener or urllib.request.urlopen
        self._token: str | None = None

    def open(self, request, timeout: int):
        """Open a request to the registry, over https only. Every URL here
        is built from the `https://` literal; this refuses anything else
        (a `file:` URL, say) should a later edit build one another way."""
        if not request.full_url.startswith("https://"):
            raise ProofError("refusing a URL that is not https: %s" % request.full_url)
        return self.opener(request, timeout=timeout)  # noqa: S310 - https checked above

    def _url(self, tail: str) -> str:
        return "https://%s/v2/%s/%s" % (self.host, self.repo, tail)

    def token(self) -> str:
        if self._token is None:
            url = "https://%s/token?scope=repository:%s:pull" % (self.host, self.repo)
            request = urllib.request.Request(url)  # noqa: S310 - https literal above
            with self.open(request, timeout=30) as answer:
                body = json.load(answer)
            self._token = body.get("token") or body.get("access_token") or ""
            if not self._token:
                raise ProofError("the registry gave no anonymous pull token")
        return self._token

    def get(self, tail: str, accept: Iterable[str] = ()):
        request = urllib.request.Request(self._url(tail))  # noqa: S310 - _url is https
        request.add_header("Authorization", "Bearer " + self.token())
        if accept:
            request.add_header("Accept", ", ".join(accept))
        return self.open(request, timeout=60)

    def manifest(self, reference: str, platform: str = PLATFORM) -> dict:
        with self.get("manifests/" + reference, INDEX_TYPES + MANIFEST_TYPES) as answer:
            found = json.load(answer)
        if found.get("manifests") is not None:
            with self.get(
                "manifests/" + pick_platform(found, platform), MANIFEST_TYPES
            ) as answer:
                found = json.load(answer)
        if not found.get("layers"):
            raise ProofError("the manifest lists no layers")
        return found

    def layer(self, digest: str):
        return self.get("blobs/" + digest)


def prove(registry, reference: str, path: str, needles, platform=PLATFORM) -> dict:
    """The hit count per needle in the binary at `path`, read from the newest
    layer that holds it. Raises ProofError when no layer does."""
    layers = registry.manifest(reference, platform)["layers"]
    for layer in reversed(layers):
        kind = layer_kind(layer.get("mediaType") or "")
        if kind not in READABLE_LAYERS:
            raise ProofError(
                "layer %s is %s, which this script does not read"
                % (layer.get("digest"), layer.get("mediaType"))
            )
        with registry.layer(layer["digest"]) as stream:
            chunks = binary_chunks(stream, path)
            if chunks is not None:
                return scan(chunks, needles)
    raise ProofError("no layer of the image holds %s" % path)


# --- the command ----------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Count needles in a binary streamed from an image registry."
    )
    parser.add_argument("image", help="HOST/REPOSITORY@sha256:DIGEST (or :TAG)")
    parser.add_argument(
        "--needle",
        action="append",
        default=[],
        help="text that must be in the binary; repeat for each change",
    )
    parser.add_argument(
        "--optional",
        action="append",
        default=[],
        help="text to count without failing when it is absent",
    )
    parser.add_argument("--path", default=BINARY, help="the binary inside the image")
    parser.add_argument("--platform", default=PLATFORM)
    args = parser.parse_args(argv)
    if not (args.needle or args.optional):
        parser.error("name at least one --needle or --optional")
    return args


def main(argv=None, registry_of: Callable = Registry, out=None) -> int:
    out = out or sys.stdout
    args = parse_args(argv)
    required = [n.encode("utf-8") for n in args.needle]
    optional = [n.encode("utf-8") for n in args.optional]
    try:
        host, repo, reference = parse_ref(args.image)
        counts = prove(
            registry_of(host, repo),
            reference,
            args.path,
            required + optional,
            args.platform,
        )
    except (
        ProofError,
        ValueError,
        OSError,
        tarfile.TarError,
        urllib.error.URLError,
    ) as exc:
        print("binary proof: could not read the image: %s" % exc, file=out)
        return UNREADABLE
    for line in report(counts, required):
        print(line, file=out)
    absent = missing(counts, required)
    if absent:
        print(
            "binary proof: %d required needle(s) not found; do not pin this digest"
            % len(absent),
            file=out,
        )
        return MISSING
    print(body_line(counts), file=out)
    return OK


if __name__ == "__main__":
    sys.exit(main())
