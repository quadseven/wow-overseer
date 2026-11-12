"""Which build of the operations app this server would serve now.

A phone keeps a tab open for hours, and the open page goes on running the
scripts it loaded. `page` in /api/realm fingerprints index.html alone, but a
deploy that changes only app/*.js or app/*.css leaves index.html as it was,
so a page comparing that value never learns its code is old.

The build fingerprint covers the page and every script, stylesheet and font under
app/, by path and content. The page is served with the build it belongs to
(BUILD_PLACEHOLDER in index.html), /api/realm reports the build the server
holds now as `app_build`, and app/update.js offers a refresh when the two
differ.

Each call lists the files and stats them; their contents are read and
hashed again only when a file was added or removed or one changed its size
or modification time, so the realm poll does not hash forty files each time.
"""

from __future__ import annotations

import hashlib
import os
import re

BUILD_PLACEHOLDER = "__OVERSEER_BUILD__"
APP_KINDS = (".js", ".css", ".woff2")

_memo: dict[str, tuple[tuple, str]] = {}


def _app_files(root: str) -> list[str]:
    """index.html and every .js, .css and .woff2 file under app/, relative to root, sorted."""
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


def fingerprint(root: str) -> str:
    """Twelve hex characters naming the app's files as they sit on disk now."""
    files = _app_files(root)
    sig = _signature(root, files)
    kept = _memo.get(root)
    if kept is not None and kept[0] == sig:
        return kept[1]
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
    _memo[root] = (sig, build)
    return build


def stamp(html: bytes, build: str) -> bytes:
    """The page with its build substituted in, where it asks for one."""
    return html.replace(BUILD_PLACEHOLDER.encode(), build.encode())


# ---- the boot graph --------------------------------------------------------
# The page names every module of the entry script's static import closure with
# <link rel="modulepreload">, so the browser fetches them in one round instead
# of discovering each one when the module that imports it has been parsed. The
# graph is read from the files' own import statements; a view loaded by an
# import() call is not part of it.

PRELOAD_PLACEHOLDER = "<!--__OVERSEER_PRELOAD__-->"
ENTRY = "app/main.js"

# `import ... from "x"`, `export ... from "x"` and `import "x"`, each at the
# start of a line (so a comment or a string that mentions one does not count).
_IMPORT = re.compile(
    r"""^[ \t]*(?:import|export)\b[^;'"]*?\bfrom\s*["']([^"']+)["']|^[ \t]*import\s*["']([^"']+)["']""",
    re.M,
)


def static_imports(text: str) -> list[str]:
    """The module specifiers a source imports statically, in source order."""
    return [a or b for a, b in _IMPORT.findall(text)]


def _edges(root: str, rel: str) -> list[str]:
    """The files `rel` imports (paths relative to root); unreadable ones are skipped."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    out = []
    for spec in static_imports(text):
        if not spec.startswith("."):
            continue
        out.append(os.path.normpath(os.path.join(os.path.dirname(rel), spec)).replace(os.sep, "/"))
    return out


def boot_graph(root: str, entry: str = ENTRY) -> list[str]:
    """The entry and every file it imports statically, entry first, in a stable order."""
    seen = [entry]
    todo = [entry]
    while todo:
        for dep in _edges(root, todo.pop(0)):
            if dep not in seen:
                seen.append(dep)
                todo.append(dep)
    return seen


def import_depth(root: str, entry: str = ENTRY) -> int:
    """The longest chain of static imports from the entry, counted in files.

    The browser discovers a chain one link per round trip, so this is the
    number of rounds a cold start pays without preload hints. A cycle is
    counted once (its back edge is ignored).
    """
    best: dict[str, int] = {}

    def depth(rel: str, path: tuple[str, ...]) -> int:
        if rel in best:
            return best[rel]
        longest = 0
        for dep in _edges(root, rel):
            if dep not in path:
                longest = max(longest, depth(dep, path + (rel,)))
        best[rel] = longest + 1
        return best[rel]

    return depth(entry, ())


_preload_memo: dict[tuple[str, str, str], str] = {}


def preload(html: bytes, root: str, prefix: str, build: str) -> bytes:
    """The page with its modulepreload links in, one per file of the boot graph.

    `prefix` is the mount ("" or "/dev"); the files are named under the build
    the page was stamped with. Made once per mount and build.
    """
    marker = PRELOAD_PLACEHOLDER.encode()
    if marker not in html:
        return html
    key = (root, prefix, build)
    links = _preload_memo.get(key)
    if links is None:
        links = "\n".join(
            '<link rel="modulepreload" href="%s/app/%s/%s">' % (prefix, build, rel[len("app/"):])
            for rel in boot_graph(root)
        )
        _preload_memo[key] = links
    return html.replace(marker, links.encode())
