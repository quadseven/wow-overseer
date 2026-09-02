"""A read-through cache in front of Wowhead's model-viewer data, for the Armory.

WHY THIS EXISTS. The Armory tab draws each of the five as a 3D model in the
gear they are wearing, and the only renderer that can draw a 3.3.5 character
without the game client is Wowhead's own (the ZamModelViewer that its
dressing room and "View in 3D" use). Its script loads from anywhere, but
the DATA behind it - model geometry, textures, the per-race customisation
tables - is served by wow.zamimg.com with a CORS wall: any browser request
whose Origin is not wowhead.com is refused outright. So the page cannot
fetch it, and this module is the same-origin path that can: the page asks
this server for `/modelviewer/<path>`, the server fetches the upstream file
once, keeps it on disk, and answers from disk from then on. The open-source
wrapper around the viewer documents exactly this shape (a "CORS bypass"
replica) as its hard requirement.

WHAT IS AND IS NOT FETCHED. Only a fixed list of path prefixes is ever
requested upstream - the character and item metadata, the geometry, the
skin, animation and bone files, and the textures - and only with a name
made of the characters those paths are made of. Anything else is a 404
here and never leaves the pod: this is a cache for one page's known
requests, not a general proxy, and the allowlist is what makes that true.

THE CACHE. A directory (an emptyDir on the pod, a temp dir locally) with a
byte cap. Files are named by the hash of their path, every hit touches the
file, and when the cap is crossed the least recently touched files go
first. A model of a character is a handful of MB, a full set of five with
gear is a few tens of MB, and the cap is set well above that, so eviction
is a safety valve rather than a thing that happens. Upstream 404s (the
viewer probes several paths for a weapon before settling on one) are
remembered in memory for a while so the probe does not reach zamimg on
every poll.

FAILURE IS A 502. When zamimg is unreachable, slow, or answers with an
error, the page gets a 502 and its own timeout draws the paper doll instead
of a blank pane. Nothing here retries; the next poll will.

Pure by the same rule as the rest of this directory: the module decides
what a request path means, what content type it carries and what to keep;
the fetch itself is a function passed in, so the stdlib suite exercises all
of it without a network.

Ticket: infra#88 (the epic).
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field

UPSTREAM = "https://wow.zamimg.com/modelviewer/wrath/"

# The prefixes the wrath viewer actually requests under its contentPath,
# read out of the viewer build the page loads (deployment/viewer/c3f890f,
# the one Wowhead's own WotLK dressing room runs): the four kinds of
# metadata a character in gear needs, then m2 geometry, skin, anim and
# bone files, and textures. NPC, object and item-visual metadata are
# deliberately absent - the Armory draws characters in gear and nothing
# else, and a prefix nobody asks for is a prefix nobody can abuse. The
# script itself is not here: the page loads it from Wowhead directly, the
# same way it loads the icons. (The older build at wrath/viewer/ asks for
# mo3/ files that no longer exist upstream; that is why the page pins a
# deployment hash rather than the friendly path.)
ALLOWED_PREFIXES = (
    "meta/armor/",
    "meta/character/",
    "meta/charactercustomization/",
    "meta/item/",
    "m2/",
    "skin/",
    "anim/",
    "bone/",
    "textures/",
)

# The content type by extension, and the list of extensions there are.
# An extension not here is not a file the viewer asks for.
CONTENT_TYPES = {
    ".json": "application/json",
    ".m2": "application/octet-stream",
    ".skin": "application/octet-stream",
    ".anim": "application/octet-stream",
    ".bone": "application/octet-stream",
    ".webp": "image/webp",
    ".png": "image/png",
}

# A path is segments of these characters and nothing else: no "..", no
# empty segment, no query, no encoded anything. A segment may carry a dot
# for its extension but never lead with one or double one. What the viewer builds
# from race ids, display ids and file names is exactly this shape.
_SEGMENT = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9]+)*$")

# Model data is immutable for a frozen expansion: a display id's m2 file
# is the same file tomorrow. A day is long enough that a browser reloads
# nothing across a session and short enough that a corrected upstream
# file arrives eventually.
BROWSER_CACHE_CONTROL = "public, max-age=86400"

# How long an upstream "no such file" is remembered, and how many are.
MISS_TTL_SECONDS = 3600
MISS_LIMIT = 4096

# Upstream refuses requests that do not look like a browser's. This is the
# one thing the viewer's browser would have sent anyway.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
UPSTREAM_TIMEOUT_SECONDS = 20

DEFAULT_CAP_BYTES = 512 * 1024 * 1024


def default_cache_dir() -> str:
    return os.environ.get("MODEL_CACHE_DIR") or os.path.join(
        tempfile.gettempdir(), "wow-modelviewer")


def classify(path: str) -> tuple[str, str] | None:
    """A request path -> (upstream path, content type), or None to refuse.

    `path` is what followed `/modelviewer/` in the URL. Refusal is the
    answer for anything not on the allowlist, anything with a segment
    the viewer would never build, and anything with an extension there is
    no content type for. A refused path is never fetched.
    """
    if not path or not path.startswith(ALLOWED_PREFIXES):
        return None
    segments = path.split("/")
    if any(not _SEGMENT.fullmatch(s) for s in segments):
        return None
    ext = os.path.splitext(segments[-1])[1].lower()
    ctype = CONTENT_TYPES.get(ext)
    if ctype is None:
        return None
    return path, ctype


@dataclass
class DiskCache:
    """Files by path hash, capped in bytes, least recently touched out first."""

    directory: str
    cap_bytes: int = DEFAULT_CAP_BYTES
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _name(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        return os.path.join(self.directory,
                            hashlib.sha256(path.encode()).hexdigest() + ext)

    def get(self, path: str) -> bytes | None:
        name = self._name(path)
        try:
            with open(name, "rb") as f:
                data = f.read()
        except OSError:
            return None
        # The touch is the whole of the LRU: eviction reads mtime, so a hit
        # has to move the file to the young end.
        try:
            os.utime(name, None)
        except OSError:
            pass
        return data

    def put(self, path: str, data: bytes) -> None:
        os.makedirs(self.directory, exist_ok=True)
        name = self._name(path)
        # Written beside and renamed over, so a reader never sees half a
        # file and two threads fetching the same path do not interleave.
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".part-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, name)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.evict()

    def evict(self) -> list[str]:
        """Drop the least recently touched files until under the cap."""
        with self._lock:
            entries = []
            total = 0
            try:
                names = os.listdir(self.directory)
            except OSError:
                return []
            for n in names:
                if n.startswith(".part-"):
                    continue
                full = os.path.join(self.directory, n)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                entries.append((st.st_mtime, st.st_size, full))
                total += st.st_size
            evicted = []
            for _mtime, size, full in sorted(entries):
                if total <= self.cap_bytes:
                    break
                try:
                    os.unlink(full)
                except OSError:
                    continue
                total -= size
                evicted.append(full)
            return evicted


@dataclass
class Response:
    status: int
    content_type: str
    body: bytes
    cache_control: str


class Store:
    """The read-through: classify, look in the cache, fetch, remember.

    `fetcher(url) -> (status, bytes)` is the only thing that touches the
    network. It raises for anything that is not an HTTP answer (a timeout,
    a refused connection), and that becomes the 502.
    """

    def __init__(self, cache: DiskCache, fetcher, clock=time.monotonic):
        self.cache = cache
        self.fetcher = fetcher
        self.clock = clock
        self._misses: dict[str, float] = {}
        self._lock = threading.Lock()

    def _missed(self, path: str) -> bool:
        with self._lock:
            until = self._misses.get(path)
            if until is None:
                return False
            if until < self.clock():
                del self._misses[path]
                return False
            return True

    def _remember_miss(self, path: str) -> None:
        with self._lock:
            if len(self._misses) >= MISS_LIMIT:
                # Bounded by construction: a viewer that could make this
                # grow without limit would be a slow memory hole. Dropping
                # the lot costs a few refetches, not correctness.
                self._misses.clear()
            self._misses[path] = self.clock() + MISS_TTL_SECONDS

    def serve(self, path: str) -> Response:
        found = classify(path)
        if found is None:
            return Response(404, "text/plain", b"not a model-viewer file", "no-store")
        upstream_path, ctype = found
        cached = self.cache.get(upstream_path)
        if cached is not None:
            return Response(200, ctype, cached, BROWSER_CACHE_CONTROL)
        if self._missed(upstream_path):
            return Response(404, "text/plain", b"upstream has no such file", "no-store")
        try:
            status, body = self.fetcher(UPSTREAM + upstream_path)
        except Exception:  # noqa: BLE001 - every network failure is one answer
            return Response(502, "text/plain", b"model host unreachable", "no-store")
        if status == 200:
            try:
                self.cache.put(upstream_path, body)
            except OSError:
                # A full or unwritable cache directory is not the viewer's
                # problem: the file still goes to the page, it just is not
                # kept, and the next request fetches it again.
                pass
            return Response(200, ctype, body, BROWSER_CACHE_CONTROL)
        if status == 404:
            self._remember_miss(upstream_path)
            return Response(404, "text/plain", b"upstream has no such file", "no-store")
        return Response(502, "text/plain", b"model host answered %d" % status, "no-store")
