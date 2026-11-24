"""Which build of the operations app this server would serve now.

A phone keeps a tab open for hours, and the open page goes on running the
scripts it loaded. `page` in /api/realm fingerprints index.html alone, but a
deploy that changes only an app/*.js, app/*.css or app/*.woff2 file leaves
index.html as it was, so a page comparing that value never learns its code is
old.

The build fingerprint covers the page and every script, stylesheet and font
under app/, by path and content. The page is served with the build it belongs to
(BUILD_PLACEHOLDER in index.html), /api/realm reports the build the server
holds now as `app_build`, and app/update.js offers a refresh when the two
differ.

The page's modulepreload links are made here too (boot_graph, preload): one per
file of the entry script's static import closure, read from the files' own
import statements, so the list cannot drift from the code.

Each call reuses a cached build for FINGERPRINT_TTL_SECONDS without walking
disk; once that TTL expires, it lists and stats the files and hashes contents
again only when a file was added or removed or one changed its size or
modification time, so the realm poll does not walk or hash forty files each time.
"""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import os
import posixpath
import re
import time

BUILD_PLACEHOLDER = "__OVERSEER_BUILD__"
SHELL_PLACEHOLDER = "__OVERSEER_SHELL__"
APP_KINDS = (".js", ".css", ".woff2")
_APP_LINK_PREFIX = re.compile(r"/app/(?:__OVERSEER_BUILD__|[0-9a-f]{12})/(.+)$")

FINGERPRINT_TTL_SECONDS = 5.0
_clock = time.monotonic

_memo: dict[str, tuple[float, tuple, str]] = {}


def clear_cache(root: str | None = None) -> None:
    """Drop cached fingerprints and preload links for `root`, or all roots."""
    if root is None:
        _memo.clear()
        _preload_memo.clear()
    else:
        _memo.pop(root, None)
        _preload_memo.pop(root, None)


def _app_files(root: str) -> list[str]:
    """index.html and every app script, style and woff2 font, sorted."""
    out = ["index.html"]
    app = os.path.join(root, "app")
    for here, dirs, files in os.walk(app):
        dirs.sort()
        for name in files:
            if name.endswith(APP_KINDS):
                out.append(os.path.relpath(os.path.join(here, name), root))
    return sorted(out)


def _signature(root: str, files: list[str]) -> tuple:
    sig = []
    for rel in files:
        try:
            st = os.stat(os.path.join(root, rel))
        except OSError:
            sig.append((rel, -1, -1))
            continue
        sig.append((rel, st.st_size, st.st_mtime_ns))
    return tuple(sig)


def fingerprint(root: str, *, ttl: float | None = None) -> str:
    """Twelve hex characters naming the app's files as they sit on disk now."""
    max_age = FINGERPRINT_TTL_SECONDS if ttl is None else ttl
    now = _clock()
    kept = _memo.get(root)
    if kept is not None and max_age > 0 and (now - kept[0]) < max_age:
        return kept[2]
    files = _app_files(root)
    sig = _signature(root, files)
    if kept is not None and kept[1] == sig:
        _memo[root] = (now, sig, kept[2])
        return kept[2]
    digest = hashlib.sha256()
    for rel in files:
        digest.update(rel.replace(os.sep, "/").encode() + b"\0")
        try:
            with open(os.path.join(root, rel), "rb") as f:
                digest.update(f.read())
        except OSError:
            digest.update(b"missing")
        digest.update(b"\0")
    build = digest.hexdigest()[:12]
    _memo[root] = (now, sig, build)
    return build


def stamp(html: bytes, build: str) -> bytes:
    """The page with its build substituted in, where it asks for one."""
    return html.replace(BUILD_PLACEHOLDER.encode(), build.encode())


# ---- the boot graph --------------------------------------------------------
# A module is only discovered once the module that imports it has arrived and
# been parsed, so a cold start pays one round trip per level of imports. The
# page names every file of the entry's static import closure up front instead.
# A module reached only through an import() call (a view, a lazy lookup) is not
# part of the closure and gets no hint.

PRELOAD_PLACEHOLDER = "<!--__OVERSEER_PRELOAD__-->"
ENTRY = "main.js"

# `import ... from "x"`, `export ... from "x"` and `import "x"`, each starting
# a line, so a comment or a string that mentions one does not count and an
# import("x") call never matches.
_STATIC_IMPORT = re.compile(
    r"""^[ \t]*(?:import|export)\b[^;'"()]*?\bfrom\s*["']([^"']+)["']"""
    r"""|^[ \t]*import\s*["']([^"']+)["']""",
    re.M,
)

_preload_memo: dict[str, tuple[str, bytes]] = {}


def static_imports(text: str) -> list[str]:
    """The module specifiers a source imports statically, in source order."""
    return [a or b for a, b in _STATIC_IMPORT.findall(text)]


def _edges(root: str, rel: str) -> list[str]:
    """The app files `rel` imports statically, as paths relative to app/."""
    with open(os.path.join(root, "app", *rel.split("/")), encoding="utf-8") as f:
        text = f.read()
    out = []
    for spec in static_imports(text):
        if not spec.startswith("."):
            continue
        dep = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
        if dep not in out:
            out.append(dep)
    return out


def boot_graph(root: str, entry: str = ENTRY) -> list[str]:
    """`entry` and every app file it reaches by static imports, entry first.

    Paths are relative to app/ and the order is breadth first in source order,
    so the same files always give the same list. A missing file raises OSError:
    a hint for a file that is not there would be a 404 on every page load.
    """
    seen = [entry]
    todo = [entry]
    while todo:
        for dep in _edges(root, todo.pop(0)):
            if dep not in seen:
                seen.append(dep)
                todo.append(dep)
    return seen


def deepest_chain(root: str, entry: str = ENTRY) -> list[str]:
    """The longest chain of static imports from `entry`, entry first.

    Without hints the browser learns of each link only after the one before
    it, so the length of this list is the number of dependent rounds a cold
    start would pay. An import that points back into the chain being walked
    (a cycle) is not followed. Ties go to the import written first.
    """
    best: dict[str, list[str]] = {}

    def walk(rel: str, above: tuple[str, ...]) -> list[str]:
        if rel in best:
            return best[rel]
        longest: list[str] = []
        for dep in _edges(root, rel):
            if dep == rel or dep in above:
                continue
            chain = walk(dep, above + (rel,))
            if len(chain) > len(longest):
                longest = chain
        best[rel] = [rel] + longest
        return best[rel]

    return list(walk(entry, ()))


def preload_links(root: str) -> bytes:
    """One modulepreload link per boot graph file, mount and build left to stamp.

    The links carry the same placeholders as the rest of the page, so the
    mount and the build are substituted with everything else. Made once per
    build: the fingerprint covers every app script, so the same build has the
    same graph.
    """
    build = fingerprint(root)
    kept = _preload_memo.get(root)
    if kept is not None and kept[0] == build:
        return kept[1]
    links = "\n".join(
        '<link rel="modulepreload" href="__OVERSEER_BASE__/app/%s/%s">'
        % (BUILD_PLACEHOLDER, rel)
        for rel in boot_graph(root)
    ).encode()
    _preload_memo[root] = (build, links)
    return links


def preload(html: bytes, root: str) -> bytes:
    """The page with its modulepreload links in, where it asks for them.

    Raises ValueError when the page has lost the marker: served anyway it
    would look normal and boot one round trip per import level, and the
    service worker would precache no script.
    """
    marker = PRELOAD_PLACEHOLDER.encode()
    if marker not in html:
        raise ValueError("the page has no %s marker" % PRELOAD_PLACEHOLDER)
    return html.replace(marker, preload_links(root))


class _ShellLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        by_name = {k.lower(): (v or "") for k, v in attrs}
        rels = set(by_name.get("rel", "").split())
        if not rels.intersection(("stylesheet", "modulepreload")):
            return
        href = by_name.get("href", "")
        matched = _APP_LINK_PREFIX.search(href)
        if not matched:
            return
        rel_path = matched.group(1)
        if rel_path not in self.assets:
            self.assets.append(rel_path)


def shell_assets(html: bytes) -> list[str]:
    """Relative paths under app/<build>/ from the page's style and modulepreload links."""
    parser = _ShellLinkParser()
    parser.feed(html.decode("utf-8"))
    parser.close()
    return parser.assets


def stamp_worker(sw: bytes, build: str, index_html: bytes) -> bytes:
    """Stamp build fingerprint and precache shell list into sw.js."""
    assets = json.dumps(shell_assets(index_html)).encode("utf-8")
    return stamp(sw, build).replace(SHELL_PLACEHOLDER.encode(), assets)
